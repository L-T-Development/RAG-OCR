"""
Extraction quality — say what could NOT be read, before anyone compares it.
================================================================================

Every wrong answer this system can give traces back to something it silently failed
to read. A page that is a scan has no text, so nothing on it is searchable and no
part on it can ever be "found". A table whose header row did not survive extraction
has columns called `Column_3`, so no concept resolves to it. Neither failure raises
an error: the comparison just reports parts as *missing from* a document that
plainly contains them, and looks authoritative doing it.

This module turns those silences into statements:

    scan_text_coverage(path)  → pages, how many carry no text, how many are images
    document_qa(document)     → the above plus table/header/column health
    warnings_for(document)    → short human sentences, or [] when all is well

`scan_text_coverage` is deliberately cheap (~1 ms/page via PyMuPDF) so it can run on
every ingest, and it distinguishes a *scanned* page (no text, has an image — OCR
would help) from a *blank* one (no text, no image — nothing to recover).
"""
from __future__ import annotations

import os
from typing import Any, Dict, List, Optional

# A page with less than this many characters is treated as having no text layer.
# Real pages carry hundreds; scans and blanks carry a stray header at most.
_MIN_CHARS = 20


def scan_text_coverage(pdf_path: str) -> Dict[str, Any]:
    """Per-page text-layer coverage for one PDF. Cheap enough to run at ingest."""
    try:
        import fitz
    except Exception as e:                      # pragma: no cover - env without PyMuPDF
        return {"error": f"PyMuPDF unavailable: {e}"}
    try:
        doc = fitz.open(pdf_path)
    except Exception as e:
        return {"error": str(e)}

    textless, scanned, pages_list = 0, 0, []
    try:
        for i, page in enumerate(doc, 1):
            text = (page.get_text("text") or "").strip()
            if len(text) >= _MIN_CHARS:
                continue
            textless += 1
            has_image = bool(page.get_images(full=True))
            if has_image:
                scanned += 1
            if len(pages_list) < 50:
                pages_list.append(i)
        total = len(doc)
    finally:
        doc.close()

    return {
        "pages": total,
        "textless_pages": textless,
        "scanned_pages": scanned,          # textless AND carrying an image → OCR would help
        "blank_pages": textless - scanned,  # textless with no image → nothing to recover
        "textless_page_numbers": pages_list,
    }


def document_qa(document, thread_ids: Optional[List[str]] = None) -> Dict[str, Any]:
    """
    Everything known about how well this document was read.

    Combines what ingestion recorded (text coverage) with what can be checked from
    the stored tables right now (how many tables, how many lost their header, and
    whether a part column resolves at all).
    """
    from .column_roles import describe
    from .models import ExtractedTable

    stats = dict(getattr(document, "extraction_stats", None) or {})

    doc_key = str(document.id)
    tables = ExtractedTable.objects.filter(doc_id=doc_key)
    table_count = tables.count()

    headerless = 0
    for t in tables.only("id"):
        headers = (t.to_dict() or {}).get("headers") or []
        if not headers or all(_is_placeholder(h) for h in headers):
            headerless += 1

    columns = describe(document, thread_ids=thread_ids)
    resolved = {f: r for f, r in columns["roles"].items() if r["header"]}

    return {
        "document_id": str(document.id),
        "filename": document.filename,
        "category": document.category,
        "status": document.status,
        "text_coverage": stats or None,
        "tables": table_count,
        "headerless_tables": headerless,
        "resolved_concepts": {f: r["header"] for f, r in resolved.items()},
        "has_part_column": "part_no" in resolved,
        "headers": columns["headers"],
        "suggestions": columns["suggestions"],
        "warnings": warnings_for(document, table_count=table_count,
                                 headerless=headerless, resolved=resolved, stats=stats),
    }


def _is_placeholder(header) -> bool:
    import re
    h = str(header).strip()
    return (not h) or bool(re.fullmatch(r"Column_?\s*\d+(_\d+)?", h))


def warnings_for(document, table_count=None, headerless=None,
                 resolved=None, stats=None) -> List[str]:
    """Plain sentences about what will not be findable in this document."""
    from .column_roles import describe
    from .models import ExtractedTable

    doc_key = str(document.id)
    if table_count is None:
        table_count = ExtractedTable.objects.filter(doc_id=doc_key).count()
    if resolved is None:
        resolved = {f: r for f, r in describe(document)["roles"].items() if r["header"]}
    if stats is None:
        stats = dict(getattr(document, "extraction_stats", None) or {})

    out: List[str] = []

    scanned = stats.get("scanned_pages") or 0
    pages = stats.get("pages") or 0
    if scanned:
        pct = f" ({scanned / pages * 100:.0f}% of the file)" if pages else ""
        out.append(
            f"{scanned} page{'s' if scanned != 1 else ''} of **{document.filename}** "
            f"appear to be scanned images{pct} — there is no OCR, so nothing on those "
            f"pages is searchable or comparable.")

    if table_count == 0:
        out.append(
            f"No tables were extracted from **{document.filename}** — a column "
            f"comparison cannot use it. Text-based checks still can.")
    elif headerless:
        out.append(
            f"{headerless} of {table_count} tables in **{document.filename}** lost their "
            f"header row, so their columns cannot be resolved by name.")

    if table_count and not resolved.get("part_no"):
        out.append(
            f"No part-number column resolves in **{document.filename}**. Pin one with "
            f"`set the part no column to \"<header>\" in @{document.filename}`.")

    return out


def record_for_document(document, pdf_path: Optional[str] = None) -> Dict[str, Any]:
    """Scan and persist text coverage onto the Document. Never raises."""
    try:
        path = pdf_path
        if path is None:
            path = document.file.path if document.file else None
        if not path or not os.path.exists(path) or not path.lower().endswith(".pdf"):
            return {}
        stats = scan_text_coverage(path)
        if "error" in stats:
            return {}
        document.extraction_stats = stats
        document.save(update_fields=["extraction_stats"])
        if stats.get("scanned_pages"):
            print(f"[QA] {document.filename}: {stats['scanned_pages']} scanned page(s) "
                  f"with no text layer — not searchable without OCR")
        return stats
    except Exception as e:
        print(f"[QA] text-coverage scan skipped for {getattr(document, 'filename', '?')}: {e}")
        return {}
