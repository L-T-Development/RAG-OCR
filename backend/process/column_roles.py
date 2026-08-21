"""
Per-document column roles — "in THIS document, the part number is that column".
================================================================================

Three things can identify the column a user means:

  1. `field_schema.resolve_header`  — the header text. Precise, covers every label
     we have seen, extensible via field_schema.json. Tried first.
  2. `column_profile`               — the shape of the values. Can spot identifier
     columns, but provably cannot separate a part number from a stock number
     (measured 1/6 on real MRLS/ISPL pairs), so it only ever *suggests*.
  3. A person looking at the document. Always right, and previously had to be
     re-expressed in every single query as a quoted header.

This module is (3): a durable record of the human's answer, scoped to one document
and one concept. It is consulted before the schema, because a stored decision by
someone who read the document beats any rule we could write.

    role_map(doc_id)                    → {field: header_text} the user has set
    override_header(term, headers, doc) → the real header to use, or None
    describe(document)                  → what each concept resolves to, and how
                                          (used by the API / document panel)
"""
from __future__ import annotations

from typing import Dict, List, Optional, Sequence

from .field_schema import (CANONICAL_FIELDS, _canon_loose, canonical_field_for_query,
                           resolve_header)


def _key(doc_id) -> str:
    """Match ExtractedTable.doc_id (a UUIDField) whichever string form we are given."""
    return str(doc_id).replace("-", "").strip().lower()


def role_map(doc_id) -> Dict[str, str]:
    """{canonical field: header text} the user has pinned for this document."""
    from .models import ColumnRole
    return {r.field: r.header_text
            for r in ColumnRole.objects.filter(doc_id=_key(doc_id))}


def set_role(document, field: str, header_text: Optional[str], note: str = "") -> dict:
    """Pin (or clear, with header_text falsy) one concept for one document."""
    from .models import ColumnRole
    if field not in CANONICAL_FIELDS:
        return {"ok": False, "error": f"Unknown field '{field}'. "
                                      f"Known: {', '.join(sorted(CANONICAL_FIELDS))}"}
    key = _key(document.id)
    if not header_text:
        n, _ = ColumnRole.objects.filter(doc_id=key, field=field).delete()
        return {"ok": True, "cleared": bool(n), "field": field}

    headers = document_headers(document)
    actual = _match_header(header_text, headers)
    if actual is None:
        return {"ok": False,
                "error": f"'{header_text}' is not a column in {document.filename}.",
                "available_columns": headers}
    obj, created = ColumnRole.objects.update_or_create(
        doc_id=key, field=field,
        defaults={"header_text": actual, "source": document.filename,
                  "thread_id": str(document.thread_id), "note": note},
    )
    return {"ok": True, "created": created, "field": field, "header": actual}


def _match_header(wanted: str, headers: Sequence[str]) -> Optional[str]:
    """The real header equal to `wanted` ignoring punctuation/case/whitespace."""
    w = _canon_loose(wanted)
    if not w:
        return None
    for h in headers:
        if _canon_loose(h) == w:
            return str(h)
    for h in headers:                      # tolerate the user typing a shortened form
        if w in _canon_loose(h):
            return str(h)
    return None


def override_header(term: str, headers: Sequence[str], doc_id) -> Optional[str]:
    """
    The user-pinned header for `term`'s concept, if one exists **and** appears in
    `headers` (a single table may not carry every column of the document).
    """
    if not doc_id:
        return None
    field = canonical_field_for_query(term)
    if not field:
        return None
    pinned = role_map(doc_id).get(field)
    if not pinned:
        return None
    return _match_header(pinned, headers)


def resolve(term: str, headers: Sequence[str], category=None, doc_id=None,
            prefer_literal: bool = False) -> Optional[str]:
    """
    Column resolution with the user's decisions applied.

    A header the user quoted in *this* query still wins (`prefer_literal`) — it is
    the most specific instruction available. Otherwise a stored role wins, then the
    category schema.
    """
    if prefer_literal:
        hit = resolve_header(term, headers, category, prefer_literal=True)
        if hit is not None:
            return hit
    pinned = override_header(term, headers, doc_id)
    if pinned is not None:
        return pinned
    return resolve_header(term, headers, category, prefer_literal=prefer_literal)


# ── Introspection for the UI / API ─────────────────────────────────────────────

def _frames(document, thread_ids=None):
    from .table_search_engine import _search_engine
    return _search_engine.load_structured_tables(
        document.filename, doc_id=str(document.id), thread_ids=thread_ids)


def document_headers(document, thread_ids=None) -> List[str]:
    """Every distinct real column header across the document's persisted tables."""
    seen, out = set(), []
    for df in _frames(document, thread_ids):
        for c in df.columns:
            s = str(c)
            if s.startswith("_"):
                continue
            k = _canon_loose(s)
            if k and k not in seen:
                seen.add(k)
                out.append(s)
    return out


def describe(document, thread_ids=None) -> dict:
    """
    How this document's columns are currently understood:

      roles[field] = {header, origin: user|schema|none, ...}

    plus the value-shape suggestions for anything unresolved, and the full header
    list — everything the document panel needs to show and correct a mapping.
    """
    from .column_profile import columns_from_frames, identifier_columns

    dfs = _frames(document, thread_ids)
    headers = document_headers(document, thread_ids)
    pinned = role_map(document.id)

    roles = {}
    for field in CANONICAL_FIELDS:
        if field in pinned:
            actual = _match_header(pinned[field], headers) or pinned[field]
            roles[field] = {"header": actual, "origin": "user"}
            continue
        hit = resolve_header(field, headers, document.category)
        roles[field] = ({"header": hit, "origin": "schema"} if hit
                        else {"header": None, "origin": "none"})

    suggestions = []
    if dfs and any(r["header"] is None for r in roles.values()):
        try:
            suggestions = [{"header": h, "why": why}
                           for h, why in identifier_columns(columns_from_frames(dfs))]
        except Exception as e:
            print(f"[COLUMN_ROLES] suggestion failed: {e}")

    return {
        "document_id": str(document.id),
        "filename": document.filename,
        "category": document.category,
        "table_count": len(dfs),
        "headers": headers,
        "roles": roles,
        "suggestions": suggestions,
        "fields": sorted(CANONICAL_FIELDS),
    }
