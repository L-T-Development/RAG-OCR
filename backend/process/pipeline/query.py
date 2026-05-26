"""
Query pipeline.

Flow:
  user_query
    → parse (file filter, intent, search terms)
    → retrieve (vector chunks + SQL tables)
    → route to response generator
    → return {answer, sources, chunks, confidence, confidence_label, retrieval_type}
"""

import re
import time

import requests

from .config import OLLAMA_API, CANDIDATE_K, MAX_FINAL_CHUNKS, get_current_llm_model
from .embedding import model_manager
from .storage import get_collection
from .tables import search_tables, get_ancestor_ids, extract_search_terms, compare_tables, compare_columns, cross_doc_search

# ── File-scope filter (@filename.ext) ────────────────────────────────────────

def extract_file_filter(query_text):
    """Strip @filename.ext from query and return (clean_query, filename or None)."""
    match = re.search(r"@(.+?\.(pdf|xlsx|xls|docx))(?:\s|$)", query_text, re.IGNORECASE)
    if not match:
        return query_text, None
    fn = match.group(1).strip()
    clean = re.sub(r"@" + re.escape(fn), "", query_text, flags=re.IGNORECASE).strip()
    return clean, fn


# ── Intent classification ─────────────────────────────────────────────────────

_TABLE_KEYWORDS = {
    "table", "specification", "spec", "parameter", "value", "property", "attribute",
    "dimension", "measurement", "rating", "capacity", "range", "limit", "requirement",
    "threshold", "tolerance", "part", "nsn", "model", "code", "number", "serial",
    "item", "component", "drg", "dwg", "drawing", "nomenclature", "ref", "reference",
    "plate", "sr. no", "sr.no", "sl. no", "sl.no",
}
_CODE_RE = [
    re.compile(r"\b\d{5,}\b"),
    re.compile(r"\b[A-Z0-9]{6,}\b"),
    re.compile(r"\b\d+[A-Z]+\d+\b"),
    re.compile(r"\b[A-Z]+\d+[A-Z]*\d*\b"),
    re.compile(r"\b\w+[-_]\w+[-_]\w+\b"),
]
_LIST_PHRASES = {
    "list all", "show all", "get all", "list the", "show the", "get the",
    "display all", "display the", "give me all", "give me the",
}
_FIND_PHRASES = {"locate ", "show me where", "where is", "where are", "where can i find"}
_QUESTION_STARTS = {
    "is ", "are ", "does ", "do ", "what ", "which ", "how ", "why ", "when ",
    "where ", "can ", "could ", "should ", "would ", "will ", "has ", "have ",
    "was ", "were ", "tell me", "explain", "describe",
}


def _is_table_query(query_text):
    ql = query_text.lower()
    if any(kw in ql for kw in _TABLE_KEYWORDS):
        return True
    return any(p.search(query_text) for p in _CODE_RE)


def _classify_intent(query_text):
    """Return LIST | FIND | QUESTION | LOOKUP."""
    ql = query_text.lower().strip()
    if any(ql.startswith(p) or p in ql for p in _LIST_PHRASES):
        return "LIST"
    if any(ql.startswith(p) for p in _FIND_PHRASES):
        return "FIND"
    if query_text.strip().endswith("?") or any(
        ql.startswith(p) or p in ql for p in _QUESTION_STARTS
    ):
        return "QUESTION"
    return "LOOKUP"


# ── Hybrid retrieval (BM25 + vector → RRF) ───────────────────────────────────

_RRF_K = 60  # standard constant — higher = less aggressive rank weighting


def _build_thread_filter(thread_id):
    ancestors = get_ancestor_ids(thread_id)
    all_ids = [str(thread_id)] + ancestors
    if len(all_ids) == 1:
        return {"thread_id": {"$eq": all_ids[0]}}
    return {"$or": [{"thread_id": {"$eq": tid}} for tid in all_ids]}


def _retrieve_vectors(query_text, thread_id, file_filter):
    """
    Hybrid retrieval: vector (ChromaDB) + keyword (BM25) merged via RRF.
    Returns up to MAX_FINAL_CHUNKS of (doc, meta, pseudo_distance) tuples.
    """
    ancestors = get_ancestor_ids(thread_id)
    all_thread_ids = set([str(thread_id)] + ancestors)

    # ── 1. Vector search ──────────────────────────────────────────────────────
    query_vec   = model_manager.encode([query_text]).tolist()
    base_filter = _build_thread_filter(thread_id)
    where = (
        {"$and": [base_filter, {"source": {"$eq": file_filter}}]}
        if file_filter else base_filter
    )

    v_result = get_collection().query(
        query_embeddings=query_vec, n_results=CANDIDATE_K, where=where,
        include=["documents", "metadatas", "distances"],
    )
    v_ids   = v_result.get("ids",        [[]])[0]
    v_docs  = v_result.get("documents",  [[]])[0]
    v_metas = v_result.get("metadatas",  [[]])[0]
    v_dists = v_result.get("distances",  [[]])[0]

    # ── 2. BM25 search ────────────────────────────────────────────────────────
    from .bm25 import bm25_index
    b_hits = bm25_index.search(
        query_text,
        thread_ids=all_thread_ids,
        file_filter=file_filter,
        top_k=CANDIDATE_K,
    )

    # ── 3. Reciprocal Rank Fusion ─────────────────────────────────────────────
    rrf: dict[str, float] = {}
    vector_by_id: dict[str, tuple] = {}
    bm25_by_id:   dict[str, tuple] = {}

    for rank, (cid, doc, meta, dist) in enumerate(
        zip(v_ids, v_docs, v_metas, v_dists)
    ):
        rrf[cid] = rrf.get(cid, 0.0) + 1.0 / (_RRF_K + rank + 1)
        vector_by_id[cid] = (doc, meta, dist)

    for rank, (cid, _score, text, meta) in enumerate(b_hits):
        rrf[cid] = rrf.get(cid, 0.0) + 1.0 / (_RRF_K + rank + 1)
        bm25_by_id[cid] = (text, meta)

    if not rrf:
        return []

    merged = []
    for cid, score in sorted(rrf.items(), key=lambda x: x[1], reverse=True):
        pseudo_dist = max(0.0, 1.0 - score * _RRF_K)
        if cid in vector_by_id:
            doc, meta, _ = vector_by_id[cid]
        else:
            doc, meta = bm25_by_id[cid]
        merged.append((doc, meta, pseudo_dist))
        if len(merged) >= MAX_FINAL_CHUNKS:
            break

    return merged


# ── LLM call ─────────────────────────────────────────────────────────────────

def _call_llm(prompt, system_prompt, temperature=0, num_ctx=4096, timeout=120):
    payload = {
        "model": get_current_llm_model(),
        "prompt": prompt,
        "system": system_prompt,
        "stream": False,
        "temperature": temperature,
        "options": {"num_thread": 8, "num_ctx": num_ctx},
        "keep_alive": "5m",
    }
    r = requests.post(OLLAMA_API, json=payload, timeout=timeout)
    return r.json().get("response", "Error: No response from LLM.")


# ── Confidence evaluation ─────────────────────────────────────────────────────

def _evaluate(query, answer, used_docs):
    from process.eval_utils import answer_relevance, context_precision, faithfulness
    embed = model_manager.get_model()
    if embed is None:
        return 0.0, "LOW"
    try:
        rel,   _ = answer_relevance(embed, query, answer)
        ctx      = context_precision(embed, query, used_docs)
        faith    = faithfulness(answer, used_docs, embed)
        score    = (float(rel) * 0.4 + float(faith) * 0.4 + float(ctx) * 0.2) * 100
        label    = "HIGH" if score >= 75 else "MEDIUM" if score >= 50 else "LOW"
        return round(score, 1), label
    except Exception:
        return 0.0, "LOW"


# ── Chunk formatters ──────────────────────────────────────────────────────────

def _fmt_text(doc, meta, dist):
    return {
        "text": doc,
        "source": meta["source"],
        "page": meta["page"],
        "similarity_score": round(float(1 - dist), 3),
        "type": "text",
    }


def _fmt_table(table):
    return {
        "type": "table",
        "table_id": table["id"],
        "source": table["source"],
        "page": table["page"],
        "table_index": table["table_index"],
        "table_data": {
            "headers": table["headers"],
            "row_count": table["row_count"],
            "column_count": table["column_count"],
            "data": table["data"],
        },
        "table_type": table.get("table_type", "unknown"),
        "has_structured_data": True,
        "similarity_score": 0.0,
        "retrieval_source": table.get("source_type", "sql_search"),
    }


# ── Column keyword map for list queries ──────────────────────────────────────

_COLUMN_MAP = {
    "drg":          ["drg", "dwg", "drawing", "drg.", "dwg.", "drg. no", "dwg. no", "drawing no", "drawing number"],
    "part":         ["part", "part no", "part number", "part.no", "partno"],
    "nsn":          ["nsn", "n.s.n", "stock number"],
    "nomenclature": ["nomenclature", "designation", "description", "name", "item"],
    "ref":          ["ref", "reference", "ref no", "ref.", "ref. no"],
    "plate":        ["plate", "plate ref"],
    "sr":           ["sr", "sr.", "sr no", "sr. no", "serial", "sl", "sl.", "sl no"],
}


# ── Response generators ───────────────────────────────────────────────────────

def _gen_list(query_text, sql_tables, search_terms, vector_chunks):
    """Extract and list specific column values from tables."""
    ql = query_text.lower()
    target = next(
        (col for col, kws in _COLUMN_MAP.items() if any(kw in ql for kw in kws)),
        "all",
    )

    extracted, seen = [], set()
    for table in sql_tables:
        headers = table.get("headers", [])
        data    = table.get("data", [])
        src     = f"{table['source']} (Page {table['page']})"
        if not headers or not data:
            continue

        header_lower = [str(h).lower().strip() for h in headers]
        col_idx = None
        if target != "all":
            for kw in _COLUMN_MAP[target]:
                for i, h in enumerate(header_lower):
                    if kw in h:
                        col_idx = i
                        break
                if col_idx is not None:
                    break

        for row in data:
            if col_idx is not None and col_idx < len(row):
                val = str(row[col_idx]).strip()
                if val and val != "None" and val not in seen:
                    seen.add(val)
                    extracted.append({"value": val, "source": src, "column": headers[col_idx]})
            elif target == "all":
                extracted.append({
                    "value": " | ".join(str(c) for c in row),
                    "source": src,
                    "column": " | ".join(str(h) for h in headers),
                })

    if not extracted:
        return None  # caller falls through to location response

    answer = f"**Found {len(extracted)} entries:**\n\n"
    if target != "all" and extracted:
        answer += f"**{extracted[0]['column']}:**\n"
        for idx, item in enumerate(extracted[:100], 1):
            answer += f"{idx}. {item['value']}\n"
        if len(extracted) > 100:
            answer += f"\n... and {len(extracted) - 100} more"
    else:
        for item in extracted[:50]:
            answer += f"\n**{item['source']}**\n{item['column']}\n{item['value']}\n"

    all_chunks = [_fmt_table(t) for t in sql_tables] + [_fmt_text(*c) for c in vector_chunks]
    return {
        "answer": answer,
        "sources": list({t["source"] for t in sql_tables}),
        "chunks": all_chunks,
        "confidence": 95.0,
        "confidence_label": "HIGH",
        "retrieval_type": "sql_list",
    }


def _gen_sql_answer(query_text, sql_tables, search_terms, vector_chunks):
    """Generate an LLM answer grounded in table data."""
    all_terms = search_terms["codes"] + search_terms["names"] + search_terms["keywords"]
    table_ctx = ""
    exact, partial = [], []

    for table in sql_tables[:5]:
        headers     = table.get("headers", [])
        data        = table.get("data", [])
        src         = f"{table['source']} (Page {table['page']})"
        header_lower = [str(h).lower() for h in headers]
        name_col = next(
            (i for i, h in enumerate(header_lower) if any(x in h for x in ["name", "designation", "description", "item"])),
            None,
        )
        for row in data:
            row_text = " ".join(str(c) for c in row).lower()
            for term in all_terms:
                tl = term.lower().strip()
                is_exact = any(str(c).strip().lower() == tl for c in row) or (
                    name_col is not None and name_col < len(row)
                    and str(row[name_col]).strip().lower() == tl
                )
                entry = {"term": term, "row": row, "headers": headers, "source": src}
                if is_exact:
                    exact.append(entry)
                elif tl in row_text:
                    partial.append(entry)

    seen = set()

    def _add_match(m, label):
        nonlocal table_ctx
        k = str(m["row"])
        if k in seen:
            return
        seen.add(k)
        table_ctx += f"\nSearched: '{m['term']}' → {label}\nSource: {m['source']}\n"
        for i, h in enumerate(m["headers"]):
            if i < len(m["row"]):
                table_ctx += f"  {h}: {m['row'][i]}\n"

    if exact:
        table_ctx += "\n=== EXACT MATCHES (use these) ===\n"
        for m in exact:
            _add_match(m, "EXACT MATCH")
    elif partial:
        table_ctx += "\n=== PARTIAL MATCHES ===\n"
        for m in partial[:5]:
            _add_match(m, "PARTIAL MATCH")

    if not exact and not partial:
        if len(sql_tables) > 50:
            answer = (
                f"ℹ️ **Searched {len(sql_tables)} tables** — no specific matches found.\n\n"
                "💡 Tips: use exact codes, compare specific columns, list queries, or @filename.pdf.\n\n"
                f"**Searched:** {sql_tables[0]['source']} (+{len(sql_tables)-1} more)"
            )
            return {
                "answer": answer,
                "sources": [f"{sql_tables[0]['source']} (+{len(sql_tables)-1} more)"],
                "chunks": [_fmt_table(t) for t in sql_tables[:5]],
                "confidence": 30.0,
                "confidence_label": "LOW",
                "retrieval_type": "sql_no_match",
            }
        table_ctx += "\n=== TABLE SAMPLE ===\n"
        for t in sql_tables[:3]:
            table_ctx += f"\nFrom {t['source']} (Page {t['page']}):\nHeaders: {' | '.join(str(h) for h in t.get('headers', []))}\n"
            for row in t.get("data", [])[:5]:
                table_ctx += f"Row: {' | '.join(str(c) for c in row)}\n"

    system = (
        "You are a precise document assistant. Answer using ONLY the provided data.\n"
        "RULES:\n"
        "1. Use ONLY data from 'EXACT MATCHES' when available.\n"
        "2. Never confuse similar names (e.g., 'SUPPORT ROLLER' ≠ 'SUPPORT ROLLER FIXING').\n"
        "3. If no exact match: say 'No exact match found for [term]'.\n"
        "4. Be concise and direct."
    )
    prompt = (
        f"QUESTION: {query_text}\n\n"
        f"SEARCH TERMS:\n"
        f"- Codes: {search_terms['codes'] or 'None'}\n"
        f"- Names: {search_terms['names'] or 'None'}\n\n"
        f"{table_ctx}\n\n"
        "Answer using ONLY the EXACT MATCH data above."
    )

    try:
        answer = _call_llm(prompt, system, temperature=0)
        locs   = "\n".join(
            f"• {t['source']} (Page {t['page']}, Table {t['table_index']})"
            for t in sql_tables
        )
        answer += f"\n\n**Source(s):** {len(sql_tables)} table(s)\n{locs}"
        all_chunks = [_fmt_table(t) for t in sql_tables] + [_fmt_text(*c) for c in vector_chunks]
        return {
            "answer": answer,
            "sources": list({f"{t['source']} (Page {t['page']})" for t in sql_tables}),
            "chunks": all_chunks,
            "confidence": 95.0,
            "confidence_label": "HIGH",
            "retrieval_type": "sql_intelligent",
        }
    except Exception as e:
        print(f"[QUERY] LLM error in sql_answer: {e}")
        return None  # caller falls through to location response


def _gen_location(sql_tables, vector_chunks):
    """Simple 'found at these locations' response for FIND-intent queries."""
    locs = "\n".join(
        f"• {t['source']} (Page {t['page']}, Table {t['table_index']})"
        for t in sql_tables
    )
    return {
        "answer": f"**Found** in {len(sql_tables)} table(s):\n\n{locs}",
        "sources": list({f"{t['source']} (Page {t['page']})" for t in sql_tables}),
        "chunks": [_fmt_table(t) for t in sql_tables] + [_fmt_text(*c) for c in vector_chunks],
        "confidence": 100.0,
        "confidence_label": "EXACT_MATCH",
        "retrieval_type": "sql_direct",
    }


def _gen_text_answer(query_text, vector_chunks):
    """Standard semantic RAG: context → LLM → evaluate."""
    if not vector_chunks:
        return {
            "answer": "I don't know based on the uploaded documents.",
            "sources": [],
            "chunks": [],
            "confidence": 0,
            "confidence_label": "LOW",
            "retrieval_type": "no_results",
        }

    context  = "".join(
        f"--- Source: {m['source']} (Page {m['page']}) ---\n{d}\n\n"
        for d, m, _ in vector_chunks
    )
    sources  = list({f"{m['source']} (Page {m['page']})" for _, m, _ in vector_chunks})
    used_docs = [d for d, _, _ in vector_chunks]

    system = (
        "You are a precise and helpful document assistant.\n"
        "- Answer ONLY using the provided context.\n"
        "- If the answer is not in the context, say "
        "'I don't know based on the provided documents'.\n"
        "- Never make up information. Be concise. Use bullet points for longer answers."
    )

    try:
        t0     = time.time()
        answer = _call_llm(f"Context:\n{context}\nUser Query: {query_text}", system, temperature=0)
        print(f"[QUERY] LLM done in {time.time()-t0:.2f}s")
        confidence, label = _evaluate(query_text, answer, used_docs)
        return {
            "answer": answer,
            "sources": sources,
            "chunks": [_fmt_text(d, m, dist) for d, m, dist in vector_chunks],
            "confidence": confidence,
            "confidence_label": label,
            "retrieval_type": "vector_semantic",
        }
    except Exception as e:
        return {
            "answer": f"Error connecting to Ollama: {e}",
            "sources": [],
            "chunks": [],
            "confidence": 0,
            "confidence_label": "ERROR",
            "retrieval_type": "error",
        }


# ── Compare intent detection ──────────────────────────────────────────────────

_COMPARE_WORDS = {
    "compare", "comparison", "difference", "differences", "diff", "versus",
    "contrast", "mismatch", "missing", "added", "removed", "only in",
}

_COMPARE_PATTERNS = [
    # "compare parts list between file1.pdf and file2.pdf"
    re.compile(r"compare\s+(.+?)\s+(?:between|in|from|across)\s+(.+?)\s+and\s+(.+)", re.I),
    # "difference between file1.pdf and file2.pdf"
    re.compile(r"difference[s]?\s+between\s+(.+?)\s+and\s+(.+)", re.I),
    # "file1.pdf vs file2.pdf"
    re.compile(r"([\w\-. ]+\.(?:pdf|xlsx|xls|docx))\s+vs\.?\s+([\w\-. ]+\.(?:pdf|xlsx|xls|docx))", re.I),
]


def _is_compare_query(query_text):
    ql = query_text.lower()
    return sum(1 for w in _COMPARE_WORDS if w in ql) >= 2


def _parse_compare_files(query_text):
    """
    Extract (file_a, file_b, column_hint) from a compare query.
    @file syntax: @file1.pdf vs @file2.pdf  →  most reliable.
    Regex fallback for natural language.
    Returns (None, None, None) if not parseable.
    """
    # @file1 @file2 syntax (highest priority)
    at_files = re.findall(r"@([\w\-. ]+\.(?:pdf|xlsx|xls|docx))", query_text, re.I)
    if len(at_files) >= 2:
        clean = re.sub(r"@[\w\-. ]+\.(?:pdf|xlsx|xls|docx)", "", query_text, flags=re.I).strip()
        return at_files[0], at_files[1], clean or None

    for pat in _COMPARE_PATTERNS:
        m = pat.search(query_text)
        if m:
            groups = m.groups()
            if len(groups) == 3:
                # "compare <col> between <A> and <B>"
                return groups[1].strip(), groups[2].strip(), groups[0].strip()
            if len(groups) == 2:
                return groups[0].strip(), groups[1].strip(), None

    return None, None, None


# ── Column hint resolver ──────────────────────────────────────────────────────

# Maps user-facing keyword → canonical column search string
_COL_KEYWORDS: list[tuple[list[str], str]] = [
    (["part no", "part number", "part.no", "partno", "part"],          "part"),
    (["nsn", "n.s.n", "stock number"],                                  "nsn"),
    (["drg", "dwg", "drawing no", "drawing number", "drawing"],        "drg"),
    (["nomenclature", "designation", "description", "name"],           "nomenclature"),
    (["ref no", "reference no", "ref.", "reference"],                   "ref"),
    (["plate", "plate ref"],                                            "plate"),
    (["sr no", "sl no", "serial", "sr.", "sl."],                       "sr"),
    (["qty", "quantity"],                                               "qty"),
    (["price", "cost", "rate", "amount"],                               "price"),
    (["date"],                                                          "date"),
]


def _resolve_column(hint_text):
    """
    Extract a column search string from free-text like
    'compare part numbers between ...' or 'NSN column'.
    Returns None if no recognisable column keyword is found.
    """
    if not hint_text:
        return None
    hl = hint_text.lower()
    for keywords, canonical in _COL_KEYWORDS:
        if any(kw in hl for kw in keywords):
            return canonical
    # Fallback: any token that looks like a column name (short, not stop-word)
    _stops = {"compare", "between", "and", "the", "of", "in", "from", "across", "column", "field"}
    for token in re.split(r"[\s,]+", hl):
        t = token.strip()
        if len(t) >= 2 and t not in _stops:
            return t
    return None


# ── Compare diff formatter ────────────────────────────────────────────────────

def _format_diff_answer(diff, file_a, file_b):
    s = diff["summary"]
    fuzzy_count = s.get("fuzzy_matched", 0)
    lines = [
        f"**Table Comparison: {file_a} vs {file_b}**\n",
        "| | Count |",
        "|---|---|",
        f"| Rows only in **{file_a}** | {s['only_in_a']} |",
        f"| Rows only in **{file_b}** | {s['only_in_b']} |",
        f"| Modified rows (exact key match) | {s['modified']} |",
        f"| Similar rows (fuzzy key match) | {fuzzy_count} |",
        f"| Identical rows | {s['unchanged']} |",
        f"| Total in A | {s['total_a']} |",
        f"| Total in B | {s['total_b']} |",
        "",
    ]

    def _abbrev_keys(items, limit=20):
        shown = [f"• {x['key']}" for x in items[:limit]]
        if len(items) > limit:
            shown.append(f"  _...and {len(items)-limit} more_")
        return shown

    if diff["only_in_a"]:
        lines.append(f"\n**Only in {file_a} ({s['only_in_a']}):**")
        lines.extend(_abbrev_keys(diff["only_in_a"]))

    if diff["only_in_b"]:
        lines.append(f"\n**Only in {file_b} ({s['only_in_b']}):**")
        lines.extend(_abbrev_keys(diff["only_in_b"]))

    if diff["modified"]:
        lines.append(f"\n**Modified rows — exact key match ({s['modified']}):**")
        for item in diff["modified"][:10]:
            lines.append(f"\n• **{item['key']}**")
            for d in item["differences"][:4]:
                lines.append(f"  - {d['column']}: `{d['value_a']}` → `{d['value_b']}`")
        if s["modified"] > 10:
            lines.append(f"\n  _...and {s['modified']-10} more_")

    if diff.get("fuzzy_matches"):
        lines.append(f"\n**Similar rows — fuzzy key match ({fuzzy_count}):**")
        lines.append(f"_Keys differ but are likely the same item (similarity ≥ 75%)_\n")
        for item in diff["fuzzy_matches"][:10]:
            score_pct = int(item["score"] * 100)
            lines.append(f"\n• **{item['key_a']}** ↔ **{item['key_b']}** _{score_pct}% similar_")
            for d in item["differences"][:4]:
                lines.append(f"  - {d['column']}: `{d['value_a']}` → `{d['value_b']}`")
            if not item["differences"]:
                lines.append("  _(all other columns identical)_")
        if fuzzy_count > 10:
            lines.append(f"\n  _...and {fuzzy_count-10} more_")

    return "\n".join(lines)


# ── Column comparison formatter ───────────────────────────────────────────────

def _format_column_diff_answer(col_diff, file_a, file_b):
    s   = col_diff["summary"]
    col = col_diff["column_name"]
    lines = [
        f"**Column Comparison — `{col}`**\n",
        f"**{file_a}** has **{s['total_a']}** unique values &nbsp;·&nbsp; "
        f"**{file_b}** has **{s['total_b']}** unique values\n",
        "| | Count |",
        "|---|---|",
        f"| Only in **{file_a}** | {s['only_in_a']} |",
        f"| Only in **{file_b}** | {s['only_in_b']} |",
        f"| Present in both | {s['common']} |",
        "",
    ]

    def _abbrev(items, limit=30):
        shown = [f"• {x['value']}" for x in items[:limit]]
        if len(items) > limit:
            shown.append(f"  _...and {len(items)-limit} more_")
        return shown

    def _abbrev_plain(values, limit=30):
        shown = [f"• {v}" for v in values[:limit]]
        if len(values) > limit:
            shown.append(f"  _...and {len(values)-limit} more_")
        return shown

    if col_diff["only_in_a"]:
        lines.append(f"\n**Only in {file_a} ({s['only_in_a']}):**")
        lines.extend(_abbrev(col_diff["only_in_a"]))

    if col_diff["only_in_b"]:
        lines.append(f"\n**Only in {file_b} ({s['only_in_b']}):**")
        lines.extend(_abbrev(col_diff["only_in_b"]))

    if col_diff["common"]:
        lines.append(f"\n**Present in both ({s['common']}):**")
        lines.extend(_abbrev_plain(col_diff["common"]))

    return "\n".join(lines)


# ── Compare response generator ────────────────────────────────────────────────

def _gen_compare(query_text, thread_id, file_a, file_b, column_hint):
    cross    = cross_doc_search(query_text, thread_id, file_a, file_b)
    tables_a = cross.get("file_a", {}).get("tables", [])
    tables_b = cross.get("file_b", {}).get("tables", [])

    if not tables_a and not tables_b:
        return {
            "answer": (
                "No tables found for either document.\n\n"
                "Tip: Upload both documents, then use `@file1.pdf vs @file2.pdf` syntax."
            ),
            "sources": [], "chunks": [],
            "confidence": 0, "confidence_label": "LOW",
            "retrieval_type": "compare_no_data",
        }

    if not tables_a or not tables_b:
        missing    = file_a if not tables_a else file_b
        found_name = file_b if not tables_a else file_a
        found_tables = tables_b if not tables_a else tables_a
        return {
            "answer": f"No tables found for **{missing}**. Found {len(found_tables)} table(s) in **{found_name}**.",
            "sources": [found_name],
            "chunks": [_fmt_table(t) for t in found_tables[:5]],
            "confidence": 30, "confidence_label": "LOW",
            "retrieval_type": "compare_one_sided",
        }

    preview = [_fmt_table(t) for t in tables_a[:3]] + [_fmt_table(t) for t in tables_b[:3]]

    # ── Column-specific comparison ────────────────────────────────────────────
    col_key = _resolve_column(column_hint or query_text)
    if col_key:
        col_diff = compare_columns(tables_a, tables_b, col_key)
        if col_diff["summary"]["total_a"] > 0 or col_diff["summary"]["total_b"] > 0:
            print(f"[QUERY] column compare on '{col_key}' → col={col_diff['column_name']}")
            return {
                "answer":           _format_column_diff_answer(col_diff, file_a, file_b),
                "sources":          [file_a, file_b],
                "chunks":           preview,
                "confidence":       95.0,
                "confidence_label": "HIGH",
                "retrieval_type":   "column_compare",
                "diff_data":        col_diff,
            }
        # Column not found in either doc — fall through to full-table diff

    # ── Full row-level table diff ─────────────────────────────────────────────
    diff = compare_tables(tables_a, tables_b, key_column=col_key)
    return {
        "answer":           _format_diff_answer(diff, file_a, file_b),
        "sources":          [file_a, file_b],
        "chunks":           preview,
        "confidence":       95.0,
        "confidence_label": "HIGH",
        "retrieval_type":   "table_compare",
        "diff_data":        diff,
    }


# ── Main entry point ──────────────────────────────────────────────────────────

def query_rag(query_text, current_thread_id, parent_thread_id=None, conversation_history=None):
    if not model_manager.is_ready():
        model_manager.load_model()
    if not model_manager.is_ready():
        return {
            "answer": "Embedding model not configured. Set model path in Settings.",
            "sources": [], "chunks": [], "confidence": 0, "confidence_label": "ERROR",
        }

    t0 = time.time()

    # 0. Compare intent — check before single-file filter extraction
    if _is_compare_query(query_text):
        file_a, file_b, col_hint = _parse_compare_files(query_text)
        if file_a and file_b:
            print(f"\n[QUERY] intent=COMPARE | A={file_a} | B={file_b} | col={col_hint}")
            result = _gen_compare(query_text, current_thread_id, file_a, file_b, col_hint)
            print(f"[QUERY] done in {time.time()-t0:.2f}s | type={result.get('retrieval_type')}")
            return result

    # 1. Parse
    query_text, file_filter = extract_file_filter(query_text)
    intent       = _classify_intent(query_text)
    is_table     = _is_table_query(query_text)
    search_terms = extract_search_terms(query_text)

    print(f"\n[QUERY] intent={intent} | table={is_table} | filter={file_filter}")

    # 2. Retrieve
    vector_chunks = _retrieve_vectors(query_text, current_thread_id, file_filter)
    sql_tables    = (
        search_tables(query_text, current_thread_id, file_filter)
        if (is_table or intent in ("LIST", "FIND"))
        else []
    )
    print(f"[QUERY] vectors={len(vector_chunks)} | sql_tables={len(sql_tables)}")

    # 3. Route → generate
    result = None
    if sql_tables:
        if intent == "LIST":
            result = _gen_list(query_text, sql_tables, search_terms, vector_chunks)
        if result is None and intent in ("QUESTION", "LOOKUP"):
            result = _gen_sql_answer(query_text, sql_tables, search_terms, vector_chunks)
        if result is None:
            result = _gen_location(sql_tables, vector_chunks)
    else:
        result = _gen_text_answer(query_text, vector_chunks)

    print(f"[QUERY] done in {time.time()-t0:.2f}s | type={result.get('retrieval_type')}")
    return result
