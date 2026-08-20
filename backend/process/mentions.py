"""
Identifier mention index — "is this part number anywhere in that manual?"
================================================================================

Column-to-column comparison only works when both documents are tables. Technical
manuals are not: they mention part numbers in running text, figure callouts,
maintenance steps and notes. Prose is embedded into ChromaDB for semantic search,
which cannot answer an exact-string question, so those mentions were invisible to
every comparison path.

This module keeps a SQL-searchable copy of each document's text and an index of
the identifier-shaped tokens in it, from BOTH prose and table cells:

    index_chunks()   ← called from ingestion for every document type
    index_tables()   ← table cells, from the persisted ExtractedTable rows
    lookup_values()  ← {value: [(source, page, kind), …]} for a set of values

Matching mirrors the rules the comparison engine already uses: values are
normalised with `field_schema.normalize_value`, and every check is tried against
both the whitespace-collapsed and the whitespace-free form of the page, because
PDF extraction drops spaces when a line wraps ("BIG LAUNCHER PAD" →
"BIG LAUNCHERPAD"). Nothing here is fuzzy — a hit is an exact substring of the
document's own text.
"""
from __future__ import annotations

import re
from collections import defaultdict
from typing import Dict, Iterable, List, Sequence, Tuple

from django.db.models import Q

from .field_schema import normalize_value

# ── What counts as an identifier ───────────────────────────────────────────────
# Catalogue/part/drawing numbers, not English words. A candidate must contain a
# digit and enough structure to be an identifier rather than a quantity or a year.
_TOKEN_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9\-/_.]{2,63}")
_YEARISH_RE = re.compile(r"^(19|20)\d{2}$")
_MAX_LEN = 64
_MIN_DIGITS_LEN = 5          # pure numbers shorter than this are quantities, not parts


def is_identifier_like(token: str) -> bool:
    """True for values shaped like a catalogue/part/drawing number."""
    t = token.strip(" .,;:()[]{}'\"")
    if not (3 < len(t) <= _MAX_LEN):
        return False
    if not any(c.isdigit() for c in t):
        return False                      # pure words are not identifiers
    if t.isdigit():
        # A bare number: long enough not to be a page/quantity, and not a year.
        return len(t) >= _MIN_DIGITS_LEN and not _YEARISH_RE.match(t)
    if not any(c.isalnum() for c in t):
        return False
    # Reject decimals and section numbers ("3.2", "1.4.5", "12.50")
    if re.fullmatch(r"\d+(\.\d+)+", t):
        return False
    return True


def extract_identifiers(text: str) -> List[str]:
    """Identifier-shaped tokens in `text`, in order of appearance (with repeats)."""
    if not text:
        return []
    return [m.group(0).strip(" .,;:()[]{}'\"")
            for m in _TOKEN_RE.finditer(text)
            if is_identifier_like(m.group(0))]


def norm_forms(value: str) -> Tuple[str, str]:
    """(whitespace-collapsed, whitespace-free) upper-case forms used for matching."""
    n = normalize_value(value)
    return n, re.sub(r"\s+", "", n)


def doc_key(doc_id) -> str:
    """
    One canonical string form of a document id for these CharField columns.

    Callers hand us a UUID either way round — ingestion passes the dashed
    `str(uuid)`, management commands and views often pass the 32-char hex — and
    unlike `ExtractedTable.doc_id` (a UUIDField, which Django coerces) these
    columns are plain text, so the two forms would never match each other.
    """
    return str(doc_id).replace("-", "").strip().lower()


def _page_forms(text: str) -> Tuple[str, str]:
    up = re.sub(r"\s+", " ", (text or "").upper()).strip()
    return up, re.sub(r"\s+", "", up)


# ── Writing the index ──────────────────────────────────────────────────────────

def _store(doc_id, thread_id, parent_id, source, per_page: Dict[int, List[str]], kind: str) -> int:
    """Persist page text + mentions for one document/kind. Replaces what was there."""
    from django.db import transaction
    from .models import DocumentPageText, IdentifierMention

    doc_id = doc_key(doc_id)
    page_rows, mention_rows = [], []
    for page, texts in per_page.items():
        joined = "\n".join(t for t in texts if t)
        if not joined.strip():
            continue
        norm, nospace = _page_forms(joined)
        page_rows.append(DocumentPageText(
            doc_id=doc_id, thread_id=str(thread_id),
            parent_thread_id=str(parent_id) if parent_id else None,
            source=source, page=page, kind=kind,
            text_norm=norm, text_nospace=nospace,
        ))
        counts: Dict[str, Tuple[str, int]] = {}
        for tok in extract_identifiers(joined):
            n, _ns = norm_forms(tok)
            if not n:
                continue
            raw, c = counts.get(n, (tok, 0))
            counts[n] = (raw, c + 1)
        for n, (raw, c) in counts.items():
            mention_rows.append(IdentifierMention(
                doc_id=doc_id, thread_id=str(thread_id),
                parent_thread_id=str(parent_id) if parent_id else None,
                source=source, value_norm=n[:255],
                value_nospace=re.sub(r"\s+", "", n)[:255],
                value_raw=raw[:255], page=page, kind=kind, occurrences=c,
            ))

    if not page_rows and not mention_rows:
        return 0
    with transaction.atomic():
        DocumentPageText.objects.filter(doc_id=doc_id, kind=kind).delete()
        IdentifierMention.objects.filter(doc_id=doc_id, kind=kind).delete()
        DocumentPageText.objects.bulk_create(page_rows, batch_size=500)
        IdentifierMention.objects.bulk_create(mention_rows, batch_size=2000,
                                              ignore_conflicts=True)
    return len(mention_rows)


def index_chunks(doc_id, thread_id, parent_id, source, chunks: Sequence[str],
                 metas: Sequence[dict]) -> int:
    """
    Index prose. Called from ingestion with the same chunks that go to ChromaDB,
    so every document type is covered by one hook. Chunk overlap duplicates some
    text — harmless here, since only presence and page matter.
    """
    per_page: Dict[int, List[str]] = defaultdict(list)
    for chunk, meta in zip(chunks, metas):
        try:
            page = int(meta.get("page") or 1)
        except (TypeError, ValueError):
            page = 1
        per_page[page].append(chunk)
    try:
        n = _store(doc_id, thread_id, parent_id, source, per_page, "text")
        if n:
            print(f"[MENTIONS] {source}: indexed {n} identifier mention(s) from text")
        return n
    except Exception as e:                 # indexing must never fail an ingestion
        print(f"[MENTIONS] text indexing skipped for {source}: {e}")
        return 0


def index_tables(doc_id, thread_id=None, parent_id=None, source=None) -> int:
    """Index every table cell of one document from the persisted ExtractedTable rows."""
    from .models import ExtractedTable
    tables = list(ExtractedTable.objects.filter(doc_id=doc_id).prefetch_related("rows__cells"))
    if not tables:
        return 0
    thread_id = thread_id or tables[0].thread_id
    parent_id = parent_id or tables[0].parent_thread_id
    source = source or tables[0].source

    per_page: Dict[int, List[str]] = defaultdict(list)
    for t in tables:
        cells = [c.value for r in t.rows.all() for c in r.cells.all() if c.value]
        if cells:
            per_page[t.page or 1].append(" \n ".join(cells))
    try:
        n = _store(doc_id, thread_id, parent_id, source, per_page, "table")
        if n:
            print(f"[MENTIONS] {source}: indexed {n} identifier mention(s) from tables")
        return n
    except Exception as e:
        print(f"[MENTIONS] table indexing skipped for {source}: {e}")
        return 0


def delete_for(doc_id=None, thread_id=None) -> int:
    """Drop the index for a document or a whole thread (called on delete)."""
    from .models import DocumentPageText, IdentifierMention
    if not doc_id and not thread_id:
        return 0
    f = {"doc_id": doc_key(doc_id)} if doc_id else {"thread_id": str(thread_id)}
    n1, _ = IdentifierMention.objects.filter(**f).delete()
    n2, _ = DocumentPageText.objects.filter(**f).delete()
    return n1 + n2


# ── Reading the index ──────────────────────────────────────────────────────────

def indexed_documents(doc_ids: Iterable[str]) -> set:
    """Which of these documents actually have an index (so callers can say so)."""
    from .models import DocumentPageText
    keys = [doc_key(d) for d in doc_ids]
    return set(DocumentPageText.objects.filter(doc_id__in=keys)
               .values_list("doc_id", flat=True).distinct())


def vocabulary(doc_id: str, limit: int = 50_000) -> List[str]:
    """Every distinct identifier indexed for a document.

    Used to give text mode the same deterministic near-match tier the column
    comparison has: a value that is not present verbatim may still be present as
    a variant ("XL17461 NAMICA" in the spares list vs "XL17461" in the manual),
    and `field_schema.pair_likely_values` is the reviewed rule set for deciding that.
    """
    from .models import IdentifierMention
    return list(IdentifierMention.objects.filter(doc_id=doc_key(doc_id))
                .values_list("value_norm", flat=True).distinct()[:limit])


def pages_for(value_norm: str, doc_id: str) -> List[dict]:
    """Pages where one exact indexed identifier appears."""
    from .models import IdentifierMention
    return [{"page": r["page"], "kind": r["kind"], "occurrences": r["occurrences"]}
            for r in IdentifierMention.objects.filter(
                doc_id=doc_key(doc_id), value_norm=value_norm)
            .values("page", "kind", "occurrences").order_by("page")]


def lookup_values(values: Iterable[str], doc_id: str,
                  chunk_size: int = 400) -> Dict[str, List[dict]]:
    """
    Where does each of `values` appear in document `doc_id`?

    Returns {normalised value: [{page, kind, occurrences}, …]} — absent keys mean
    "not found anywhere in that document's text or tables".

    Two passes: an indexed exact-token lookup (the common case, O(1) per value),
    then whole-page substring containment for whatever is left, which is what
    catches multi-token values and identifiers glued to neighbouring text by PDF
    extraction. Both forms — spaced and space-free — are tried in each pass.
    """
    from .models import DocumentPageText, IdentifierMention

    key_doc = doc_key(doc_id)
    wanted: Dict[str, Tuple[str, str]] = {}
    for v in values:
        n, ns = norm_forms(v)
        if n:
            wanted[n] = (n, ns)
    if not wanted:
        return {}

    out: Dict[str, List[dict]] = defaultdict(list)

    # Pass 1 — exact token hits, batched to stay under SQLite's parameter cap.
    keys = list(wanted)
    for i in range(0, len(keys), chunk_size):
        batch = keys[i:i + chunk_size]
        nospace_batch = [wanted[k][1] for k in batch]
        rows = IdentifierMention.objects.filter(doc_id=key_doc).filter(
            Q(value_norm__in=batch) | Q(value_nospace__in=nospace_batch)
        ).values("value_norm", "value_nospace", "page", "kind", "occurrences")
        by_nospace = {wanted[k][1]: k for k in batch}
        for r in rows:
            key = r["value_norm"] if r["value_norm"] in wanted else by_nospace.get(r["value_nospace"])
            if key:
                out[key].append({"page": r["page"], "kind": r["kind"],
                                 "occurrences": r["occurrences"]})

    # Pass 2 — containment for values the token index did not resolve.
    missing = [k for k in wanted if k not in out]
    if missing:
        pages = list(DocumentPageText.objects.filter(doc_id=key_doc)
                     .values("page", "kind", "text_norm", "text_nospace"))
        for key in missing:
            n, ns = wanted[key]
            if len(ns) < 4:
                continue                       # too short to be safe as a substring
            for p in pages:
                if (n and n in p["text_norm"]) or (ns and ns in p["text_nospace"]):
                    out[key].append({"page": p["page"], "kind": p["kind"], "occurrences": 1})
    for hits in out.values():
        hits.sort(key=lambda h: (h["page"], h["kind"]))
    return dict(out)
