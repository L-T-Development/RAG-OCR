import re
from django.db.models import Q

# ── Table classification ──────────────────────────────────────────────────────

def classify_table_type(headers, rows, row_count, column_count):
    if row_count <= 0 or (row_count == 1 and column_count == 1):
        return "single_cell"
    if column_count == 2 and row_count <= 10 and headers and len(headers) == 2:
        first_col = [str(r[0]).strip() for r in rows if r]
        kws = ["parameter", "property", "specification", "attribute", "field", "name", "type"]
        if any(k in " ".join(first_col).lower() for k in kws):
            return "key_value"
    if row_count <= 2:
        return "single_row"
    return "multi_row"


def generate_searchable_text(headers, rows, table_type, caption=""):
    parts = []
    if caption:
        parts.append(caption)
    if headers:
        parts.append(" ".join(str(h) for h in headers if h))
    for row in rows:
        if row:
            parts.append(" ".join(str(c) for c in row if c))
    if table_type == "key_value":
        for row in rows:
            if len(row) >= 2 and row[0] and row[1]:
                parts.append(f"{row[0]}={row[1]}")
                parts.append(f"{row[0]} is {row[1]}")
    return " ".join(parts)


# ── Table storage (Django ORM) ────────────────────────────────────────────────

def store_table(table_id, doc_id, thread_id, parent_id, source, page,
                table_index, headers, row_count, column_count, table_data, caption=""):
    from django.db import transaction
    from process.models import ExtractedTable, TableRow, TableCell, Thread
    try:
        with transaction.atomic():
            rows = table_data[1:] if len(table_data) > 1 else []
            table_type = classify_table_type(headers, rows, row_count, column_count)
            searchable_text = generate_searchable_text(headers, rows, table_type, caption=caption)

            thread = Thread.objects.get(id=thread_id)
            parent_thread = Thread.objects.get(id=parent_id) if parent_id else None

            table_obj, created = ExtractedTable.objects.update_or_create(
                id=table_id,
                defaults={
                    "doc_id": doc_id,
                    "thread": thread,
                    "parent_thread": parent_thread,
                    "source": source,
                    "page": page,
                    "table_index": table_index,
                    "row_count": row_count,
                    "column_count": column_count,
                    "table_type": table_type,
                    "searchable_text": searchable_text,
                    "caption": caption[:500] if caption else "",
                },
            )
            if not created:
                table_obj.rows.all().delete()

            # One transaction and two bulk inserts for the whole table.
            #
            # This used to be a create() per row and per CELL, each its own SQLite
            # transaction — measured at 4.9 ms per cell, which on a 582-page spares
            # list came to ~150 s of pure commit overhead (a third of the ingest time)
            # for a few thousand small rows.
            rows_to_make, cell_specs = [], []

            if headers and any(headers):
                rows_to_make.append(TableRow(table=table_obj, row_index=0, is_header=True))
                cell_specs.append([
                    (col_idx, str(h) if h else "", str(h) if h else "", False)
                    for col_idx, h in enumerate(headers)
                ])

            data_rows = table_data[1:] if (len(table_data) > 1) else ([] if headers else table_data)
            start_idx = 1 if headers else 0
            is_kv = table_type == "key_value"

            for offset, row_data in enumerate(data_rows):
                if not row_data or not isinstance(row_data, (list, tuple)):
                    continue
                rows_to_make.append(
                    TableRow(table=table_obj, row_index=start_idx + offset, is_header=False))
                spec = []
                for col_idx, cell_value in enumerate(row_data):
                    if col_idx >= column_count:
                        break
                    col_name = (
                        str(headers[col_idx])
                        if (headers and col_idx < len(headers) and headers[col_idx])
                        else f"Column {col_idx}"
                    )
                    spec.append((col_idx, col_name,
                                 str(cell_value) if cell_value else "",
                                 is_kv and col_idx == 0))
                cell_specs.append(spec)

            if rows_to_make:
                TableRow.objects.bulk_create(rows_to_make, batch_size=500)
                # bulk_create only returns primary keys on some backends; read them
                # back by (row_index, is_header) so the cell FKs are always correct.
                saved = {(r.row_index, r.is_header): r
                         for r in TableRow.objects.filter(table=table_obj)}
                cells = []
                for row_obj, spec in zip(rows_to_make, cell_specs):
                    parent = saved.get((row_obj.row_index, row_obj.is_header))
                    if parent is None:
                        continue
                    for col_idx, col_name, value, is_key in spec:
                        cells.append(TableCell(row=parent, column_index=col_idx,
                                               column_name=col_name, value=value,
                                               is_key=is_key))
                if cells:
                    TableCell.objects.bulk_create(cells, batch_size=2000)
    except Exception as e:
        import traceback
        print(f"[TABLE] Error storing {table_id}: {e}")
        traceback.print_exc()


def delete_tables(doc_id=None, thread_id=None):
    from process.models import ExtractedTable
    if doc_id:
        count, _ = ExtractedTable.objects.filter(doc_id=doc_id).delete()
    elif thread_id:
        count, _ = ExtractedTable.objects.filter(thread_id=thread_id).delete()
    else:
        return False
    print(f"[TABLE] Deleted {count} table(s)")
    return True


# ── Thread ancestry ───────────────────────────────────────────────────────────

def get_ancestor_ids(thread_id):
    from process.models import Thread
    ancestors = []
    try:
        t = Thread.objects.get(id=thread_id)
        while t.parent:
            ancestors.append(str(t.parent.id))
            t = t.parent
    except Thread.DoesNotExist:
        pass
    return ancestors


# ── Abbreviation expansion ───────────────────────────────────────────────────

_SYNONYMS: dict[str, list[str]] = {
    "drg":          ["drg", "drawing", "dwg"],
    "dwg":          ["dwg", "drawing", "drg"],
    "drawing":      ["drawing", "drg", "dwg"],
    "nsn":          ["nsn", "n.s.n", "stock number"],
    "pn":           ["pn", "part no", "part number"],
    "part":         ["part", "part no", "part number"],
    "sl":           ["sl", "sr", "serial no", "sl no", "sr no"],
    "sr":           ["sr", "sl", "serial no", "sl no", "sr no"],
    "qty":          ["qty", "quantity", "qnty"],
    "nomenclature": ["nomenclature", "description", "designation", "name"],
    "ref":          ["ref", "reference", "ref no"],
    "spec":         ["spec", "specification"],
    "assy":         ["assy", "assembly"],
    "assembly":     ["assembly", "assy"],
    "fig":          ["fig", "figure"],
    "no":           ["no", "number"],
}


def _expand_terms(terms: list[str]) -> list[str]:
    """Add known synonyms/abbreviations to a list of search terms."""
    expanded = list(terms)
    seen = {t.lower() for t in terms}
    for t in terms:
        for syn in _SYNONYMS.get(t.lower(), []):
            if syn not in seen:
                expanded.append(syn)
                seen.add(syn)
    return expanded


# ── Search term extraction ────────────────────────────────────────────────────

_STOP_WORDS = {
    "is", "it", "there", "the", "in", "a", "an", "and", "or", "for", "to", "of",
    "on", "at", "find", "get", "show", "list", "does", "do", "has", "have", "this",
    "that", "available", "document", "documents", "part", "number", "name", "if",
    "can", "you", "me", "what", "where", "which", "how", "many", "much", "are",
    "was", "were", "been", "be", "being", "search", "look", "looking", "check",
    "checking", "tell", "give", "please", "could", "would", "should", "want",
    "need", "item", "items", "component", "components", "with", "from", "about",
    "into", "any", "all", "some", "whether", "contains", "contain",
}

_CODE_PATTERNS = [
    re.compile(r"\b(\d{5,})\b"),
    re.compile(r"\b(\d+[A-Za-z]+\d+[A-Za-z0-9]*)\b"),
    re.compile(r"\b([A-Za-z]+\d+[A-Za-z0-9]*)\b"),
    re.compile(r"\b([A-Za-z0-9]+[-_][A-Za-z0-9]+(?:[-_][A-Za-z0-9]+)*)\b"),
]


def extract_search_terms(query_text):
    result = {"codes": [], "names": [], "keywords": []}

    # Quoted strings (highest priority)
    for m in re.findall(r"['\"]([^'\"]+)['\"]", query_text):
        m = m.strip()
        if len(m) < 2:
            continue
        if " " in m or (not re.search(r"\d", m) and not m.isupper()):
            result["names"].append(m)
        else:
            result["codes"].append(m)

    clean = re.sub(r"['\"]([^'\"]+)['\"]", " ", query_text)

    # Codes from unquoted text
    for pat in _CODE_PATTERNS:
        for m in pat.findall(clean):
            if m not in result["codes"] and len(m) >= 5 and m.lower() not in _STOP_WORDS:
                result["codes"].append(m)

    # Uppercase multi-word part names
    for m in re.findall(r"\b([A-Z][A-Z]+(?:\s+[A-Z][A-Z]+){1,3})\b", clean):
        words = [w for w in m.split() if w.lower() not in _STOP_WORDS]
        if words and m not in result["names"]:
            result["names"].append(m)

    # Remaining keywords
    for token in clean.split():
        t = re.sub(r"['\",?!.:;()]", "", token)
        if len(t) < 3 or t.lower() in _STOP_WORDS:
            continue
        if t in result["codes"] or t in result["names"]:
            continue
        if re.search(r"\d", t) and len(t) >= 5:
            result["codes"].append(t)
        elif t.isupper() and len(t) >= 3:
            result["keywords"].append(t)
        elif len(t) >= 4:
            result["keywords"].append(t.lower())

    return result


# ── Unified SQL table search ──────────────────────────────────────────────────

def search_tables(query_text, thread_id, file_filter=None):
    """
    Search Django ORM tables for matching content.
    Priority: exact codes → part names → keywords → return all.
    Respects thread inheritance (current + all ancestors).
    """
    from process.models import ExtractedTable

    all_thread_ids = [str(thread_id)] + get_ancestor_ids(thread_id)
    base_qs = ExtractedTable.objects.filter(thread_id__in=all_thread_ids)
    if file_filter:
        base_qs = base_qs.filter(source=file_filter)

    terms = extract_search_terms(query_text)

    def _run(values):
        q = Q()
        for v in _expand_terms(values):
            q |= Q(searchable_text__icontains=v)
        qs = base_qs.filter(q).distinct()
        return [dict(t.to_dict(), source_type="sql_search") for t in qs] if qs.exists() else None

    for field in ("codes", "names", "keywords"):
        if terms[field]:
            result = _run(terms[field])
            if result is not None:
                return result

    return [dict(t.to_dict(), source_type="sql_search") for t in base_qs.all()]
