import difflib
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
    from process.models import ExtractedTable, TableRow, TableCell, Thread
    try:
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

        # Header row
        if headers and any(headers):
            hr = TableRow.objects.create(table=table_obj, row_index=0, is_header=True)
            for col_idx, h in enumerate(headers):
                TableCell.objects.create(
                    row=hr, column_index=col_idx,
                    column_name=str(h) if h else "",
                    value=str(h) if h else "",
                    is_key=False,
                )

        # Data rows
        data_rows = table_data[1:] if (len(table_data) > 1) else ([] if headers else table_data)
        start_idx = 1 if headers else 0
        is_kv = table_type == "key_value"

        for offset, row_data in enumerate(data_rows):
            if not row_data or not isinstance(row_data, (list, tuple)):
                continue
            dr = TableRow.objects.create(table=table_obj, row_index=start_idx + offset, is_header=False)
            for col_idx, cell_value in enumerate(row_data):
                if col_idx >= column_count:
                    break
                col_name = (
                    str(headers[col_idx])
                    if (headers and col_idx < len(headers) and headers[col_idx])
                    else f"Column {col_idx}"
                )
                TableCell.objects.create(
                    row=dr,
                    column_index=col_idx,
                    column_name=col_name,
                    value=str(cell_value) if cell_value else "",
                    is_key=(is_kv and col_idx == 0),
                )
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


# ── Key-column auto-detection priority ───────────────────────────────────────

_KEY_PRIORITY = ["part", "nsn", "drg", "dwg", "drawing", "sr", "sl", "ref", "code", "item", "id"]


def _detect_key_col(headers):
    """Return index of the best key column from a header list, or 0 as fallback."""
    hl = [str(h).lower().strip() for h in headers]
    for kw in _KEY_PRIORITY:
        for i, h in enumerate(hl):
            if kw in h:
                return i
    return 0


def _build_row_index(tables, key_col_hint=None):
    """
    Build {key_value: {row, headers, source, key_col}} mapping across all tables.
    key_col_hint is a partial column name string (e.g. "part", "drg").
    """
    index = {}
    for table in tables:
        orig_headers = table.get("headers", [])
        headers_lower = [str(h).lower().strip() for h in orig_headers]
        data = table.get("data", [])
        src = f"{table['source']} (Page {table['page']})"

        k_idx = None
        if key_col_hint:
            hint_l = key_col_hint.lower()
            for i, h in enumerate(headers_lower):
                if hint_l in h:
                    k_idx = i
                    break
        if k_idx is None:
            k_idx = _detect_key_col(orig_headers)

        for row in data:
            if not row or k_idx >= len(row):
                continue
            key_val = str(row[k_idx]).strip()
            if not key_val or key_val.lower() in ("none", "", "-"):
                continue
            # First occurrence wins — keeps one canonical row per key
            if key_val not in index:
                index[key_val] = {
                    "row": row,
                    "headers": orig_headers,
                    "source": src,
                    "key_col": k_idx,
                }
    return index


# ── Column-value extraction ───────────────────────────────────────────────────

def extract_column_values(tables, column_name):
    """
    Find every non-empty value in `column_name` across all tables.
    Uses case-insensitive partial header match.
    Returns {value: {source, header}} — first occurrence wins for duplicates.
    """
    col_lower = column_name.lower().strip()
    index = {}
    for table in tables:
        headers = table.get("headers", [])
        data    = table.get("data", [])
        src     = f"{table['source']} (Page {table['page']})"

        col_idx = None
        for i, h in enumerate(headers):
            if col_lower in str(h).lower():
                col_idx = i
                break
        if col_idx is None:
            continue

        actual_header = str(headers[col_idx])
        for row in data:
            if col_idx >= len(row):
                continue
            val = str(row[col_idx]).strip()
            if val and val.lower() not in ("none", "", "-", "n/a"):
                if val not in index:
                    index[val] = {"source": src, "header": actual_header}

    return index


def compare_columns(tables_a, tables_b, column_name):
    """
    Extract one column from each table set and compare the unique values.

    Returns:
        {
          column_name: str (resolved header name),
          only_in_a:  [{value, source}],
          only_in_b:  [{value, source}],
          common:     [value],
          summary:    {total_a, total_b, only_in_a, only_in_b, common},
        }
    """
    vals_a = extract_column_values(tables_a, column_name)
    vals_b = extract_column_values(tables_b, column_name)

    keys_a = set(vals_a)
    keys_b = set(vals_b)
    only_a = sorted(keys_a - keys_b)
    only_b = sorted(keys_b - keys_a)
    common = sorted(keys_a & keys_b)

    resolved = (
        vals_a[next(iter(vals_a))]["header"] if vals_a else
        vals_b[next(iter(vals_b))]["header"] if vals_b else
        column_name
    )

    return {
        "column_name": resolved,
        "only_in_a":  [{"value": v, "source": vals_a[v]["source"]} for v in only_a],
        "only_in_b":  [{"value": v, "source": vals_b[v]["source"]} for v in only_b],
        "common":     common,
        "summary": {
            "total_a":   len(vals_a),
            "total_b":   len(vals_b),
            "only_in_a": len(only_a),
            "only_in_b": len(only_b),
            "common":    len(common),
        },
    }


# ── Fuzzy key matching ────────────────────────────────────────────────────────

# Common military/technical abbreviations expanded before comparison
_ABBREVS = {
    "assy":  "assembly",
    "bkt":   "bracket",
    "mtg":   "mounting",
    "brg":   "bearing",
    "spt":   "support",
    "cyl":   "cylinder",
    "ret":   "retainer",
    "hsg":   "housing",
    "cvr":   "cover",
    "plt":   "plate",
    "shft":  "shaft",
    "spkt":  "sprocket",
    "spr":   "spring",
    "scr":   "screw",
    "blk":   "block",
    "hex":   "hexagonal",
    "csk":   "countersunk",
    "lhd":   "left hand",
    "rhd":   "right hand",
    "stl":   "steel",
    "alum":  "aluminium",
    "no":    "number",
    "qty":   "quantity",
    "ref":   "reference",
    "drg":   "drawing",
    "dwg":   "drawing",
    "nsn":   "stock number",
    "pn":    "part number",
}

_PUNCT_RE = re.compile(r"[^\w\s]")


def _normalize_key(text: str) -> str:
    """Lowercase, strip punctuation, expand abbreviations."""
    text = _PUNCT_RE.sub(" ", text.lower())
    tokens = [_ABBREVS.get(t, t) for t in text.split()]
    return " ".join(tokens).strip()


def _fuzzy_score(a: str, b: str) -> float:
    """
    Return similarity in [0, 1].
    Takes the max of:
      • SequenceMatcher character ratio  (good for typos / substrings)
      • Token Jaccard similarity          (good for reordered / abbreviated words)
    After normalizing both strings via _normalize_key.
    """
    na, nb = _normalize_key(a), _normalize_key(b)
    if na == nb:
        return 1.0

    seq = difflib.SequenceMatcher(None, na, nb, autojunk=False).ratio()

    ta, tb = set(na.split()), set(nb.split())
    union = ta | tb
    jaccard = len(ta & tb) / len(union) if union else 0.0

    return max(seq, jaccard)


# ── Table comparison (row-level diff) ────────────────────────────────────────

def compare_tables(tables_a, tables_b, key_column=None, fuzzy_threshold=0.75):
    """
    Row-level diff between two sets of tables.

    Pass 1 — exact key match.
    Pass 2 — fuzzy match remaining unmatched keys using SequenceMatcher + token Jaccard.
             Pairs above fuzzy_threshold are treated as the same item and show up in
             fuzzy_matches (separate from exact modified rows).

    Returns:
        {
          only_in_a:     [{key, row, headers, source}],
          only_in_b:     [{key, row, headers, source}],
          modified:      [{key, differences:[{column, value_a, value_b}], source_a, source_b}],
          fuzzy_matches: [{key_a, key_b, score, differences:[...], source_a, source_b}],
          unchanged_count: int,
          summary: {total_a, total_b, only_in_a, only_in_b, modified, fuzzy_matched, unchanged},
        }
    """
    idx_a = _build_row_index(tables_a, key_column)
    idx_b = _build_row_index(tables_b, key_column)

    keys_a = set(idx_a)
    keys_b = set(idx_b)

    # ── Pass 1: exact match ───────────────────────────────────────────────────
    common  = sorted(keys_a & keys_b)
    unmatched_a = keys_a - keys_b
    unmatched_b = keys_b - keys_a

    modified, unchanged = [], []
    for k in common:
        ra      = idx_a[k]["row"]
        rb      = idx_b[k]["row"]
        headers = idx_a[k]["headers"]
        diffs   = []
        for i in range(max(len(ra), len(rb))):
            va = str(ra[i]).strip() if i < len(ra) else ""
            vb = str(rb[i]).strip() if i < len(rb) else ""
            h  = str(headers[i]) if i < len(headers) else f"Col {i}"
            if va != vb:
                diffs.append({"column": h, "value_a": va, "value_b": vb})
        if diffs:
            modified.append({
                "key": k, "differences": diffs,
                "source_a": idx_a[k]["source"],
                "source_b": idx_b[k]["source"],
            })
        else:
            unchanged.append(k)

    # ── Pass 2: fuzzy match remaining keys ───────────────────────────────────
    fuzzy_matches  = []
    used_b: set[str] = set()

    for ka in sorted(unmatched_a):
        best_score, best_kb = 0.0, None
        for kb in unmatched_b:
            if kb in used_b:
                continue
            score = _fuzzy_score(ka, kb)
            if score >= fuzzy_threshold and score > best_score:
                best_score, best_kb = score, kb

        if best_kb is None:
            continue

        used_b.add(best_kb)
        ra      = idx_a[ka]["row"]
        rb      = idx_b[best_kb]["row"]
        headers = idx_a[ka]["headers"]
        k_col   = idx_a[ka]["key_col"]

        # Collect non-key column differences
        val_diffs = []
        for i in range(max(len(ra), len(rb))):
            if i == k_col:
                continue     # skip — keys already differ by definition
            va = str(ra[i]).strip() if i < len(ra) else ""
            vb = str(rb[i]).strip() if i < len(rb) else ""
            h  = str(headers[i]) if i < len(headers) else f"Col {i}"
            if va != vb:
                val_diffs.append({"column": h, "value_a": va, "value_b": vb})

        fuzzy_matches.append({
            "key_a":       ka,
            "key_b":       best_kb,
            "score":       round(best_score, 2),
            "differences": val_diffs,
            "source_a":    idx_a[ka]["source"],
            "source_b":    idx_b[best_kb]["source"],
        })

    # Keys in A that had no fuzzy partner remain as truly only-in-A
    fuzzy_matched_a = {m["key_a"] for m in fuzzy_matches}
    fuzzy_matched_b = {m["key_b"] for m in fuzzy_matches}
    only_a = sorted(unmatched_a - fuzzy_matched_a)
    only_b = sorted(unmatched_b - fuzzy_matched_b)

    return {
        "only_in_a":     [{"key": k, **idx_a[k]} for k in only_a],
        "only_in_b":     [{"key": k, **idx_b[k]} for k in only_b],
        "modified":      modified,
        "fuzzy_matches": fuzzy_matches,
        "unchanged_count": len(unchanged),
        "summary": {
            "total_a":      len(idx_a),
            "total_b":      len(idx_b),
            "only_in_a":    len(only_a),
            "only_in_b":    len(only_b),
            "modified":     len(modified),
            "fuzzy_matched": len(fuzzy_matches),
            "unchanged":    len(unchanged),
        },
    }


# ── Cross-document table retrieval ────────────────────────────────────────────

def cross_doc_search(query_text, thread_id, file_a=None, file_b=None):
    """
    Retrieve tables from two specific documents (partial name match) or
    all tables grouped by source when no files are specified.

    Returns:
        Two-file mode:  {file_a: {name, tables, table_count}, file_b: {...}}
        All-docs mode:  {grouped: {source: [tables]}, file_count: int}
    """
    from process.models import ExtractedTable

    all_thread_ids = [str(thread_id)] + get_ancestor_ids(thread_id)
    base_qs = ExtractedTable.objects.filter(thread_id__in=all_thread_ids)

    if not file_a and not file_b:
        all_tables = [dict(t.to_dict()) for t in base_qs]
        grouped: dict = {}
        for t in all_tables:
            grouped.setdefault(t["source"], []).append(t)
        return {"grouped": grouped, "file_count": len(grouped)}

    qs_a = base_qs.filter(source__icontains=file_a) if file_a else base_qs.none()
    qs_b = (
        base_qs.filter(source__icontains=file_b)
        if file_b
        else base_qs.exclude(source__icontains=file_a)
    )

    return {
        "file_a": {"name": file_a, "tables": [dict(t.to_dict()) for t in qs_a], "table_count": qs_a.count()},
        "file_b": {"name": file_b or "other", "tables": [dict(t.to_dict()) for t in qs_b], "table_count": qs_b.count()},
    }
