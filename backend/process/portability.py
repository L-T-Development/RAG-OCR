"""
Carrying your decisions off this machine.
================================================================================

Almost everything here can be rebuilt by re-uploading a document: the tables, the
embeddings, the mention index. Two things cannot, because they are judgments a
person made while reading a document:

    ConfirmedMatch   "NAMP-08020000 and DIC-NAMP-08020000 are the same part"
    ColumnRole       "in THIS ISPL, the part number is the Firms Part No. column"

plus the `field_schema.json` override, which is a person deciding what a whole
document family calls things. They accumulate, they get more valuable with use, and
they exist in exactly one SQLite file on one desktop. Nothing wipes them — but a
dead disk, a new laptop or a colleague who needs the same corrections all lose them.

    export_decisions()   → a small, readable JSON document
    import_decisions()   → merge it into another install (dry-run first)
    backup_data_dir()    → a zip of everything, for disaster recovery

WHY EXPORT IS KEYED BY FILENAME
-------------------------------
`ColumnRole.doc_id` is a UUID generated when a document is uploaded, so the *same
PDF* has a different id on every machine. Exporting that id would produce a file
that silently applies to nothing. The export therefore records the **filename**, and
the import resolves it against whatever that machine calls the same document —
applying to every copy of it, since one file is often uploaded into several threads.
"""
from __future__ import annotations

import json
import os
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

FORMAT_VERSION = 1


# ── Export ─────────────────────────────────────────────────────────────────────

def export_decisions(thread_id: Optional[str] = None) -> Dict[str, Any]:
    """
    Every human decision on this install, as plain data.

    `thread_id` narrows it to one thread's decisions; by default everything is
    exported, because these are corrections about *documents*, not conversations.
    """
    from .field_schema import override_path
    from .models import ColumnRole, ConfirmedMatch

    matches = ConfirmedMatch.objects.all()
    roles = ColumnRole.objects.all()
    if thread_id:
        key = str(thread_id)
        matches = matches.filter(thread_id=key)
        roles = roles.filter(thread_id=key)

    schema_override = None
    try:
        path = override_path()
        if path.exists():
            schema_override = json.loads(path.read_text(encoding="utf-8"))
    except Exception as e:
        print(f"[PORTABILITY] could not read the schema override: {e}")

    return {
        "format": "ragocr-decisions",
        "version": FORMAT_VERSION,
        "exported_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "confirmed_matches": [
            {
                "source_a": m.source_a, "source_b": m.source_b,
                "column_key": m.column_key,
                "value_a": m.value_a, "value_b": m.value_b,
                "note": m.note or "",
            }
            for m in matches.order_by("source_a", "source_b", "value_a")
        ],
        # Keyed by filename, never by the local document id — see the module note.
        "column_roles": [
            {
                "source": r.source, "field": r.field,
                "header_text": r.header_text, "note": r.note or "",
            }
            for r in roles.exclude(source="").order_by("source", "field")
        ],
        "field_schema_override": schema_override,
    }


def summarize(payload: Dict[str, Any]) -> str:
    return (f"{len(payload.get('confirmed_matches') or [])} confirmed match(es), "
            f"{len(payload.get('column_roles') or [])} column role(s), "
            f"schema override: "
            f"{'yes' if payload.get('field_schema_override') else 'no'}")


# ── Import ─────────────────────────────────────────────────────────────────────

def import_decisions(payload: Dict[str, Any], *, dry_run: bool = False,
                     overwrite: bool = False,
                     apply_schema: bool = False) -> Dict[str, Any]:
    """
    Merge an exported file into this install.

    Additive by default: an existing decision is left alone unless `overwrite`.
    Nothing is written when `dry_run`, so the same call previews exactly what a
    real run would do. Column roles for documents this machine does not have are
    reported rather than silently dropped — upload the document, then re-import.
    """
    from .field_schema import override_path
    from .models import ColumnRole, ConfirmedMatch, Document

    if not isinstance(payload, dict) or payload.get("format") != "ragocr-decisions":
        return {"ok": False, "error": "Not a RAG-OCR decisions file."}
    if int(payload.get("version") or 0) > FORMAT_VERSION:
        return {"ok": False,
                "error": f"File is version {payload.get('version')}; this build "
                         f"understands up to {FORMAT_VERSION}."}

    report: Dict[str, Any] = {
        "ok": True, "dry_run": dry_run,
        "confirmed_matches": {"added": 0, "updated": 0, "unchanged": 0, "invalid": []},
        "column_roles": {"added": 0, "updated": 0, "unchanged": 0,
                         "no_such_document": [], "invalid": []},
        "field_schema_override": "not included",
    }

    # ── confirmed matches ─────────────────────────────────────────────────────
    for item in payload.get("confirmed_matches") or []:
        need = ("source_a", "source_b", "column_key", "value_a", "value_b")
        if not all(str(item.get(k) or "").strip() for k in need):
            report["confirmed_matches"]["invalid"].append(item)
            continue
        lookup = {k: item[k] for k in need}
        existing = ConfirmedMatch.objects.filter(**lookup).first()
        if existing:
            if overwrite and (existing.note or "") != (item.get("note") or ""):
                if not dry_run:
                    existing.note = item.get("note") or ""
                    existing.save(update_fields=["note"])
                report["confirmed_matches"]["updated"] += 1
            else:
                report["confirmed_matches"]["unchanged"] += 1
            continue
        if not dry_run:
            ConfirmedMatch.objects.create(note=item.get("note") or "", **lookup)
        report["confirmed_matches"]["added"] += 1

    # ── column roles, resolved by filename ────────────────────────────────────
    from .field_schema import CANONICAL_FIELDS
    for item in payload.get("column_roles") or []:
        source = str(item.get("source") or "").strip()
        field = str(item.get("field") or "").strip()
        header = str(item.get("header_text") or "").strip()
        if not (source and header) or field not in CANONICAL_FIELDS:
            report["column_roles"]["invalid"].append(item)
            continue

        docs = list(Document.objects.filter(filename__iexact=source))
        if not docs:
            report["column_roles"]["no_such_document"].append(source)
            continue

        for doc in docs:
            doc_key = str(doc.id).replace("-", "").lower()
            existing = ColumnRole.objects.filter(doc_id=doc_key, field=field).first()
            if existing and not overwrite:
                report["column_roles"]["unchanged"] += 1
                continue
            if existing and existing.header_text == header:
                report["column_roles"]["unchanged"] += 1
                continue
            if not dry_run:
                ColumnRole.objects.update_or_create(
                    doc_id=doc_key, field=field,
                    defaults={"header_text": header, "source": doc.filename,
                              "thread_id": str(doc.thread_id),
                              "note": item.get("note") or ""},
                )
            report["column_roles"]["updated" if existing else "added"] += 1

    # ── schema override, only when explicitly asked ───────────────────────────
    override = payload.get("field_schema_override")
    if override and apply_schema:
        try:
            if not dry_run:
                path = override_path()
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(json.dumps(override, indent=2, ensure_ascii=False),
                                encoding="utf-8")
            report["field_schema_override"] = "written"
        except Exception as e:
            report["field_schema_override"] = f"failed: {e}"
    elif override:
        report["field_schema_override"] = "present in file, not applied (ask for it)"

    return report


# ── Whole-install backup ───────────────────────────────────────────────────────

def data_dir() -> Path:
    """Where this install keeps everything writable."""
    root = os.environ.get("RAGOCR_DATA_DIR")
    if root:
        return Path(root)
    from django.conf import settings
    return Path(getattr(settings, "DATA_DIR", Path(settings.BASE_DIR)))


# What a backup consists of, named explicitly rather than "the whole directory".
#
# In the packaged app the data directory holds nothing but data. In development it
# is the backend source tree, because RAGOCR_DATA_DIR is unset and Django falls back
# to BASE_DIR — so "zip everything except a few folders" would quietly archive the
# source. Listing what data *is* keeps both cases correct.
_ESSENTIAL = ("db.sqlite3", "db.sqlite3-wal", "db.sqlite3-shm", "field_schema.json")
_VECTOR_DIRS = ("local_chroma_db",)
_MEDIA_DIRS = ("media", "pdfs")


def backup_data_dir(destination: Optional[str] = None, *,
                    include_media: bool = True,
                    include_vectors: bool = True) -> Dict[str, Any]:
    """
    Zip this install's data: the database (with every decision in it), any schema
    override, and — unless excluded — the uploaded files and the vector store.

    Vectors and uploads are the bulk of the size and both rebuildable, from the
    original documents and by re-ingesting. Leaving them out gives a small backup
    that still contains everything irreplaceable.
    """
    src = data_dir()
    if not src.exists():
        return {"ok": False, "error": f"No data directory at {src}"}

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    dest = Path(destination) if destination else src / "backups" / f"ragocr_backup_{stamp}.zip"
    dest.parent.mkdir(parents=True, exist_ok=True)

    wanted: List[Path] = [src / name for name in _ESSENTIAL]
    for group, included in ((_VECTOR_DIRS, include_vectors), (_MEDIA_DIRS, include_media)):
        if not included:
            continue
        for name in group:
            folder = src / name
            if folder.is_dir():
                wanted.extend(p for p in folder.rglob("*") if p.is_file())

    written, total, skipped = 0, 0 , []
    with zipfile.ZipFile(dest, "w", zipfile.ZIP_DEFLATED) as zf:
        for path in wanted:
            if not path.is_file():
                continue
            try:
                zf.write(path, path.relative_to(src).as_posix())
                written += 1
                total += path.stat().st_size
            except (OSError, PermissionError) as e:      # a locked sqlite-wal, say
                skipped.append(f"{path.name}: {e}")
                print(f"[PORTABILITY] skipped {path.name}: {e}")

    if not written:
        dest.unlink(missing_ok=True)
        return {"ok": False, "error": f"Nothing to back up in {src}"}

    return {"ok": True, "path": str(dest), "files": written,
            "bytes_uncompressed": total, "bytes_zip": dest.stat().st_size,
            "skipped": skipped,
            "included": {"media": include_media, "vectors": include_vectors}}
