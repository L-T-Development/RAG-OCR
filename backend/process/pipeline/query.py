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
from .tables import search_tables, get_ancestor_ids, extract_search_terms
from process.field_schema import resolve_header

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

def _call_llm(prompt, system_prompt, temperature=0, num_ctx=4096, num_predict=None, timeout=120):
    options = {"num_thread": 8, "num_ctx": num_ctx}
    if num_predict is not None:
        options["num_predict"] = num_predict
    payload = {
        "model": get_current_llm_model(),
        "prompt": prompt,
        "system": system_prompt,
        "stream": False,
        "temperature": temperature,
        "options": options,
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


def _gen_sql_answer(query_text, sql_tables, search_terms, vector_chunks, long_response=False):
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

    if long_response:
        system = (
            "You are a thorough document assistant. Answer using ONLY the provided data.\n"
            "RULES:\n"
            "1. Use ONLY data from 'EXACT MATCHES' when available.\n"
            "2. Never confuse similar names (e.g., 'SUPPORT ROLLER' ≠ 'SUPPORT ROLLER FIXING').\n"
            "3. If no exact match: say 'No exact match found for [term]'.\n"
            "4. Provide a detailed answer: list every matching row, include all column "
            "values, group by source, and explain any patterns or relationships you notice."
        )
        num_predict = 2048
    else:
        system = (
            "You are a precise document assistant. Answer using ONLY the provided data.\n"
            "RULES:\n"
            "1. Use ONLY data from 'EXACT MATCHES' when available.\n"
            "2. Never confuse similar names (e.g., 'SUPPORT ROLLER' ≠ 'SUPPORT ROLLER FIXING').\n"
            "3. If no exact match: say 'No exact match found for [term]'.\n"
            "4. Be concise and direct."
        )
        num_predict = None
    prompt = (
        f"QUESTION: {query_text}\n\n"
        f"SEARCH TERMS:\n"
        f"- Codes: {search_terms['codes'] or 'None'}\n"
        f"- Names: {search_terms['names'] or 'None'}\n\n"
        f"{table_ctx}\n\n"
        "Answer using ONLY the EXACT MATCH data above."
    )

    try:
        answer = _call_llm(prompt, system, temperature=0, num_predict=num_predict)
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


def _gen_text_answer(query_text, vector_chunks, long_response=False):
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

    if long_response:
        system = (
            "You are a thorough and detailed document assistant.\n"
            "- Answer ONLY using the provided context.\n"
            "- If the answer is not in the context, say "
            "'I don't know based on the provided documents'.\n"
            "- Never make up information.\n"
            "- Provide a detailed, comprehensive answer. Explain reasoning, give "
            "supporting evidence from the context, quote relevant passages, "
            "and use headings or bullet points where helpful.\n"
            "- Include every related detail from the context that helps the user understand the topic."
        )
        num_predict = 2048
    else:
        system = (
            "You are a precise and helpful document assistant.\n"
            "- Answer ONLY using the provided context.\n"
            "- If the answer is not in the context, say "
            "'I don't know based on the provided documents'.\n"
            "- Never make up information. Be concise. Use bullet points for longer answers."
        )
        num_predict = None

    try:
        t0     = time.time()
        answer = _call_llm(
            f"Context:\n{context}\nUser Query: {query_text}",
            system,
            temperature=0,
            num_predict=num_predict,
        )
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

_COMPARE_PATTERNS = [
    # "compare parts list between file1.pdf and file2.pdf"
    re.compile(r"compare\s+(.+?)\s+(?:between|in|from|across)\s+(.+?)\s+and\s+(.+)", re.I),
    # "difference between file1.pdf and file2.pdf"
    re.compile(r"difference[s]?\s+between\s+(.+?)\s+and\s+(.+)", re.I),
    # "file1.pdf vs file2.pdf"
    re.compile(r"([\w\-. ]+\.(?:pdf|xlsx|xls|docx))\s+vs\.?\s+([\w\-. ]+\.(?:pdf|xlsx|xls|docx))", re.I),
]


def _is_compare_query(query_text, thread_id=None):
    """Ask the shared parser (process/intent.py), so both routers agree."""
    from process.intent import parse as parse_intent
    doc_count = None
    if thread_id is not None:
        try:
            from process.models import Thread
            from process.comparison import documents_in_scope
            doc_count = documents_in_scope(Thread.objects.get(id=thread_id)).count()
        except Exception:
            doc_count = None
    return parse_intent(query_text, doc_count=doc_count).is_comparison


def _parse_compare_files(query_text):
    """
    Extract (files, column_hint) from a compare query.

    @file syntax (preferred): `@a.pdf @b.pdf @c.pdf ...` — any number ≥ 2.
    Regex fallback for natural language (still pairwise: two files).

    Returns (files_list, column_hint) — files_list is empty if not parseable.
    """
    # @file1 @file2 [@file3 ...] syntax (highest priority)
    at_files = re.findall(r"@([\w\-. ]+\.(?:pdf|xlsx|xls|docx))", query_text, re.I)
    if len(at_files) >= 2:
        # Dedupe preserving order
        seen, ordered = set(), []
        for f in at_files:
            key = f.lower().strip()
            if key not in seen:
                seen.add(key)
                ordered.append(f.strip())
        clean = re.sub(r"@[\w\-. ]+\.(?:pdf|xlsx|xls|docx)", "", query_text, flags=re.I).strip()
        return ordered, clean or None

    for pat in _COMPARE_PATTERNS:
        m = pat.search(query_text)
        if m:
            groups = m.groups()
            if len(groups) == 3:
                # "compare <col> between <A> and <B>"
                return [groups[1].strip(), groups[2].strip()], groups[0].strip()
            if len(groups) == 2:
                return [groups[0].strip(), groups[1].strip()], None

    return [], None


# ── Compare response generators ───────────────────────────────────────────────
# Both delegate to process/comparison.py — the same engine, formatting and Excel
# report as the chat router in views.py, so a comparison gives the same answer
# whichever router caught it. (The previous implementation here used
# pipeline/tables.compare_tables with SequenceMatcher fuzzy matching, which merges
# sequential part numbers; that engine has been retired.)



def _gen_compare(query_text, thread_id, file_a, file_b, column_hint):
    return _gen_compare_multi(query_text, thread_id, [file_a, file_b], column_hint)


def _gen_compare_multi(query_text, thread_id, files, column_hint):
    """2 files → pairwise comparison; ≥3 files → first file vs each of the rest
    (presence matrix). Any table-bearing document type (pdf/xlsx/xls/docx)."""
    from process import comparison as cmp
    from process.models import Thread

    thread = Thread.objects.get(id=thread_id)
    docs = cmp.resolve_documents(thread, files)
    if len(docs) < 2:
        found_names = {d.filename.lower() for d in docs}
        unresolved = [f for f in files
                      if not any(f.lower() == n or f.lower() in n for n in found_names)]
        in_scope = [d.filename for d in cmp.documents_in_scope(thread)]
        return {
            "answer": (
                "I couldn't find these file(s) in this thread: "
                + ", ".join(f"`{f}`" for f in unresolved) + ".\n\n"
                + ("Files available here: " + ", ".join(f"`{n}`" for n in in_scope)
                   if in_scope else "No documents with tables are uploaded in this thread yet.")
                + "\n\nTip: name files with `@`, e.g. `compare part no between @a.pdf and @b.pdf`."
            ),
            "sources": [], "chunks": [],
            "confidence": 0, "confidence_label": "LOW",
            "retrieval_type": "compare_no_data",
        }

    # What to compare comes from the shared parser, so this router cannot reach a
    # different conclusion than views.chat_thread for the same sentence.
    from process.intent import parse as parse_intent
    intent = parse_intent(query_text,
                          available_files=[d.filename for d in cmp.documents_in_scope(thread)],
                          doc_count=len(docs))
    column = intent.columns[0] or intent.concept
    column_b = intent.columns[1]

    print(f"[QUERY] compare via process.comparison | files={[d.filename for d in docs]} "
          f"| {intent.describe()}")
    result = cmp.run_comparison(thread, docs, column, column_b=column_b,
                                comparison_type=intent.comparison_type,
                                prefer_literal=intent.prefer_literal,
                                text_mode=(intent.mode == "mentions"))
    ok = bool(result.get("results") or result.get("matrix"))
    return {
        "answer":           result.get("formatted_answer", "Comparison produced no answer."),
        "sources":          [d.filename for d in docs],
        "chunks":           [],
        "confidence":       95.0 if ok else 0,
        "confidence_label": "HIGH" if ok else "LOW",
        "retrieval_type":   ("mention_check" if result.get("mode") == "text"
                             else "column_compare" if len(docs) == 2
                             else "column_compare_multi") if ok else "compare_failed",
        "report_job_id":    result.get("report_job_id"),
    }


def _fetch_tables_for_file(thread_id, file_name):
    """Tables for one file, matched on a partial source name, across the thread tree."""
    from process.models import ExtractedTable
    all_thread_ids = [str(thread_id)] + get_ancestor_ids(thread_id)
    qs = ExtractedTable.objects.filter(thread_id__in=all_thread_ids, source__icontains=file_name)
    return [dict(t.to_dict()) for t in qs]


# ── Multi-column lookup (source vs N targets, OR across columns) ─────────────

def _extract_rows_for_columns(tables, columns, category=None):
    """
    Extract rows from the given tables that have at least one of `columns` populated.

    Returns: list of {col_name: value, "_source_page": "file (page N)"} dicts.
    The col names in the dict are the canonical names we were asked about, not the
    actual header found in the PDF (so callers can present them consistently).
    """
    col_lowers = [c.lower().strip() for c in columns]
    rows_out = []
    for table in tables:
        headers = table.get("headers", [])
        data    = table.get("data", [])
        src     = f"{table.get('source', '?')} (Page {table.get('page', '?')})"

        # Map each requested column to the header index where it best matches:
        # category-aware schema resolution first ("part" → "Firms Part No."),
        # plain substring as the fallback.
        col_idx_map = {}
        hdr_strs = [str(h) for h in headers]
        for canon, canon_lower in zip(columns, col_lowers):
            resolved = resolve_header(canon, hdr_strs, category)
            if resolved is not None:
                col_idx_map[canon] = hdr_strs.index(resolved)
                continue
            for i, h in enumerate(hdr_strs):
                if canon_lower in h.lower():
                    col_idx_map[canon] = i
                    break

        if not col_idx_map:
            continue

        for row in data:
            row_vals = {}
            for canon, idx in col_idx_map.items():
                if idx < len(row):
                    val = str(row[idx]).strip()
                    if val and val.lower() not in ("none", "", "-", "n/a"):
                        row_vals[canon] = val
            if row_vals:
                row_vals["_source_page"] = src
                rows_out.append(row_vals)
    return rows_out


def _build_corpus(tables):
    """Concatenate every cell in every table into a single searchable string."""
    parts = []
    for t in tables:
        for row in t.get("data", []):
            for cell in row:
                if cell is not None:
                    parts.append(str(cell))
    return " \n ".join(parts)


def _match_value_in_corpus(value, corpus_spaced, corpus_nospace):
    """Same OR matcher used by the reports engine — spaced & no-space variants."""
    if not value:
        return False
    v = value.lower().strip()
    v_spaced = re.sub(r"\s+", " ", v)
    v_nospace = re.sub(r"\s+", "", v)
    if not v_nospace:
        return False
    if v_spaced in corpus_spaced or v_nospace in corpus_nospace:
        return True
    return False


def _gen_lookup_multi_col(thread_id, source_file, target_files, columns):
    """
    For each row in source_file's tables, OR-match its column values against
    every target file's table content.

    Args:
        source_file:   the spares list (treated as source of truth)
        target_files:  the manuals (where we expect to find each spare)
        columns:       identifier columns to OR-match across (Part No, Nomenclature, …)
    """
    source_tables = _fetch_tables_for_file(thread_id, source_file)
    if not source_tables:
        return {
            "answer": (
                f"No tables found in source `{source_file}`.\n\n"
                "Make sure it's uploaded and finished processing — the lookup needs the source "
                "to have at least one extracted table."
            ),
            "sources": [], "chunks": [],
            "confidence": 0, "confidence_label": "LOW",
            "retrieval_type": "lookup_no_source",
        }

    from process.models import Document
    src_doc = Document.objects.filter(filename__iexact=source_file).first() or               Document.objects.filter(filename__icontains=source_file).first()
    rows = _extract_rows_for_columns(source_tables, columns,
                                     category=src_doc.category if src_doc else None)
    if not rows:
        return {
            "answer": (
                f"None of the columns {columns} were found in `{source_file}`.\n\n"
                f"Available headers in the source tables: "
                + ", ".join(sorted({str(h) for t in source_tables for h in t.get('headers', [])}))
            ),
            "sources": [source_file], "chunks": [],
            "confidence": 0, "confidence_label": "LOW",
            "retrieval_type": "lookup_no_columns",
        }

    # Build a normalized corpus per target file (once per file — rows are iterated against each)
    target_corpora = {}
    for tf in target_files:
        tables = _fetch_tables_for_file(thread_id, tf)
        corpus = _build_corpus(tables).lower()
        target_corpora[tf] = (
            re.sub(r"\s+", " ", corpus).strip(),  # spaced
            re.sub(r"\s+", "", corpus),           # nospace
        )

    # Per-row OR-matching across all targets and columns
    found = []   # rows where at least one column-value matched in at least one target
    missing = [] # rows where nothing matched anywhere
    for row in rows:
        match_info = {}  # {target_file: (column_name, value)}
        for tf, (sp, ns) in target_corpora.items():
            for col in columns:
                v = row.get(col)
                if v and _match_value_in_corpus(v, sp, ns):
                    match_info[tf] = (col, v)
                    break  # this target is satisfied
        if match_info:
            found.append({"row": row, "matched_in": match_info})
        else:
            missing.append(row)

    return {
        "answer": _format_lookup_answer(source_file, target_files, columns, rows, found, missing),
        "sources": [source_file] + list(target_files),
        "chunks": [],
        "confidence": 95.0,
        "confidence_label": "HIGH",
        "retrieval_type": "lookup_multi_col",
        "diff_data": {
            "source_file": source_file,
            "target_files": target_files,
            "columns": columns,
            "row_count": len(rows),
            "found_count": len(found),
            "missing_count": len(missing),
            "missing_rows": missing[:200],  # cap for payload size
        },
    }


def _format_lookup_answer(source_file, target_files, columns, rows, found, missing):
    pct = (len(found) / len(rows) * 100) if rows else 0
    target_label = ", ".join(target_files)

    lines = [
        f"**Spare-lookup — `{source_file}` against {target_label}**",
        f"_Identifier columns: {', '.join(columns)}_",
        "",
        "| Outcome | Count |",
        "|---|---|",
        f"| Total rows in source | {len(rows)} |",
        f"| Found in any target | {len(found)} ({pct:.1f}%) |",
        f"| **Missing from all targets** | **{len(missing)}** |",
        "",
    ]

    # Missing — the actionable list. Show up to 50.
    if missing:
        lines.append(f"### ⚠️ Missing from every target ({len(missing)})")
        for r in missing[:50]:
            ident = " · ".join(f"**{c}:** {r[c]}" for c in columns if c in r)
            src = r.get("_source_page", "")
            lines.append(f"- {ident}   _(from {src})_")
        if len(missing) > 50:
            lines.append(f"  _...and {len(missing) - 50} more_")
        lines.append("")

    # Found summary — show first 25 with which column matched
    if found:
        lines.append(f"### ✅ Found in at least one target ({len(found)})")
        lines.append("| Identifier | Matched via | Target | Source page |")
        lines.append("|---|---|---|---|")
        for f in found[:25]:
            r = f["row"]
            # Identifier: prefer the first non-empty column's value
            ident_val = next((r[c] for c in columns if c in r), "")
            ident_col = next((c for c in columns if c in r), "")
            # Match info from first matched target
            tf, (mcol, mval) = next(iter(f["matched_in"].items()))
            lines.append(f"| {ident_col}: {ident_val} | {mcol} (`{mval}`) | {tf} | {r.get('_source_page', '')} |")
        if len(found) > 25:
            lines.append(f"\n_…and {len(found) - 25} more found rows_")

    return "\n".join(lines)


# ── Main entry point ──────────────────────────────────────────────────────────

def query_rag(query_text, current_thread_id, parent_thread_id=None, conversation_history=None, long_response=False):
    if not model_manager.is_ready():
        model_manager.load_model()
    if not model_manager.is_ready():
        return {
            "answer": "Embedding model not configured. Set model path in Settings.",
            "sources": [], "chunks": [], "confidence": 0, "confidence_label": "ERROR",
        }

    t0 = time.time()

    # 0. Compare intent — check before single-file filter extraction
    if _is_compare_query(query_text, current_thread_id):
        files, col_hint = _parse_compare_files(query_text)
        # Comma-separated column hint → multi-column OR-match (source vs targets lookup)
        col_list = [c.strip() for c in (col_hint or "").split(",") if c.strip()]
        if len(files) >= 2 and len(col_list) >= 2:
            print(f"\n[QUERY] intent=LOOKUP_MULTI_COL | source={files[0]} | targets={files[1:]} | cols={col_list}")
            result = _gen_lookup_multi_col(current_thread_id, files[0], files[1:], col_list)
            print(f"[QUERY] done in {time.time()-t0:.2f}s | type={result.get('retrieval_type')}")
            return result
        if len(files) == 2:
            print(f"\n[QUERY] intent=COMPARE | A={files[0]} | B={files[1]} | col={col_hint}")
            result = _gen_compare(query_text, current_thread_id, files[0], files[1], col_hint)
            print(f"[QUERY] done in {time.time()-t0:.2f}s | type={result.get('retrieval_type')}")
            return result
        if len(files) >= 3:
            print(f"\n[QUERY] intent=COMPARE_MULTI | files={files} | col={col_hint}")
            result = _gen_compare_multi(query_text, current_thread_id, files, col_hint)
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
            result = _gen_sql_answer(query_text, sql_tables, search_terms, vector_chunks, long_response=long_response)
        if result is None:
            result = _gen_location(sql_tables, vector_chunks)
    else:
        result = _gen_text_answer(query_text, vector_chunks, long_response=long_response)

    print(f"[QUERY] done in {time.time()-t0:.2f}s | type={result.get('retrieval_type')}")
    return result
