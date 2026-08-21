# How RAG-OCR Works

An engineering walkthrough of what happens inside the system, from the moment a
file is dropped into the UI to the moment an answer, a diff, or an Excel report
comes back out.

> This document explains **mechanism**. For setup, deployment and troubleshooting see
> [README.md](README.md) and [DOCKER_DEPLOYMENT.md](DOCKER_DEPLOYMENT.md).

---

## 1. What the system is

RAG-OCR is a **fully local** document-intelligence app for technical manuals —
spares lists (MRLS / ISPL), parts catalogs, engineering specs. Nothing leaves the
machine: Django serves the API, ChromaDB + SQLite hold the indexes, and Ollama on
`localhost:11434` provides both the embedding model and the answering LLM.

It does four distinct jobs, and they use **separate engines** that happen to share
a UI:

| Job | Page | Engine |
|---|---|---|
| Ask questions about documents | Workspace (chat) | `pipeline/query.py` — hybrid RAG |
| Compare a column across documents (conversationally) | Workspace (chat) | `comparison.py` → `table_search_engine.py` |
| Check a column against a manual's whole text | Workspace (chat) | `comparison.py` → `mentions.py` |
| Compare a column across documents (batch + Excel) | Reports | `reports_engine.py` |
| Line-by-line diff of two revisions | Compare | `document_compare.py` |

Understanding that these are independent code paths — not one pipeline with four
modes — is the single most useful thing to know about this codebase. Chat
comparison is the exception that used to prove the rule: it had two engines with
different matching rules, and both chat routers now funnel into one
(`process/comparison.py`, §6).

---

## 2. Runtime topology

```
┌─────────────────────────────────────────────────────────────────┐
│  Browser / Electron BrowserWindow                               │
│  React 18 + Vite + Tailwind   (Landing, Workspace, Reports,     │
│                                Compare, Settings)               │
└───────────────┬─────────────────────────────────────────────────┘
                │  fetch('/api/...')
                │  dev: Vite proxy :5173 → :8000
                │  prod: Django serves the built SPA itself
┌───────────────▼─────────────────────────────────────────────────┐
│  Django 6 (gunicorn in Docker, runserver in standalone)         │
│                                                                 │
│  process/views.py ── 37 API routes, the chat router             │
│  process/pipeline/ ── ingest · embed · retrieve · generate      │
│  process/comparison.py ── THE comparison entry point            │
│  process/table_search_engine.py ── structured table compare     │
│  process/mentions.py ── identifier index (prose + cells)        │
│  process/column_roles.py ── per-document pinned columns         │
│  process/reports_engine*.py ── batch comparator + Excel         │
│  process/document_compare.py ── line diff                       │
└───┬────────────────┬──────────────────┬─────────────────────────┘
    │                │                  │
┌───▼──────┐  ┌──────▼───────┐  ┌───────▼────────┐
│ SQLite   │  │ ChromaDB     │  │ BM25 pickle    │
│ threads, │  │ chunk        │  │ same chunk IDs │
│ docs,    │  │ embeddings   │  │ as Chroma      │
│ tables,  │  │              │  │                │
│ mentions │  │              │  │                │
└──────────┘  └──────────────┘  └────────────────┘
                       │
              ┌────────▼─────────┐
              │ Ollama :11434    │
              │ /api/embed       │  ← nomic-embed-text.v1.5 (batch; per-text /api/embeddings fallback)
              │ /api/generate    │  ← llama3.1:8b (selectable), stream: false
              └──────────────────┘
```

Ollama is a **hard external dependency**. If it is down, ingestion cannot embed
and chat cannot answer — the app degrades to table search and diffing only.
There is no streaming anywhere: every LLM call is a blocking `POST /api/generate`
with `stream: false` (`_call_llm`, 120 s timeout, `num_ctx 4096`, `keep_alive 5m`),
and no view uses `StreamingHttpResponse`.

There is also **no authentication**: every endpoint is `@csrf_exempt` and none checks
a user. The app is single-user-on-localhost by design; do not expose port 8000.

---

## 3. Data model

Defined in [backend/process/models.py](backend/process/models.py). Everything is
scoped to a **Thread**, which is the unit of context.

```
Thread ──┬── (self FK) parent          threads inherit their ancestors' documents
         ├── Document      file, category (mrls/ispl/manual/catalog/specification/
         │                 drawing/other), status (pending/processing/done/error),
         │                 progress, progress_detail, error_message, tags, notes,
         │                 version, previous_version FK
         ├── ChatMessage   role, content, sources, chunks, confidence, confidence_label
         └── ExtractedTable ── TableRow ── TableCell
             (page, caption,   (row_index,   (column_index, column_name,
              table_type,       is_header)    value, is_key)
              searchable_text,
              parent_thread FK)

DocumentPageText   (doc_id, page, kind, text_norm, text_nospace)
IdentifierMention  (doc_id, value_norm, value_nospace, page, kind, occurrences)
                   ▲ §6.4 — the only SQL-searchable copy of a document's prose
ColumnRole         (doc_id, field, header_text) — a human's pinned column, §7.2
ConfirmedMatch   (source_a, source_b, column_key, value_a, value_b) — unique together
AppConfig        key/value table, one row per key: llm_model, embedding_provider,
                 ollama_embedding_model, embedding_model_path
```

Two design decisions worth calling out:

**Tables are normalised down to cells.** A PDF table is not stored as a JSON blob —
it becomes one `ExtractedTable` row plus a `TableRow` per line plus a `TableCell`
per cell, each indexed. That is what makes `WHERE cells.value ILIKE '%XL17461%'`
possible, and it is why the comparison engines can work entirely from the database
without ever reopening the original PDF.

**Thread ancestry is a retrieval filter, not a copy.** `get_ancestor_ids()` walks
the parent chain, and every retrieval (`Chroma where`, BM25 filter, SQL `thread_id__in`)
includes the whole chain. A sub-thread sees its parent's documents automatically.

---

## 4. Ingestion — how a file becomes searchable

Entry: `POST /api/upload/<thread_id>/` or `POST /api/quick-upload/` (which also
creates a thread named after the document's extracted title).

The view saves the file, marks the `Document` as `pending`, and **returns
immediately**. Ingestion runs on a daemon thread (`_ingest_background` in
[views.py:119](backend/process/views.py#L119)), writing progress back to the
`Document` row as it goes. The frontend polls `/api/documents/<id>/progress/`.

```
upload → 200 {status: "pending"}
            │
            └─ background thread ─ process_document() dispatch by extension (_DISPATCH)
                                     ├── .pdf          → three-stage PDF path (below)
                                     ├── .xlsx / .xls  → openpyxl, one table per sheet
                                     ├── .docx         → python-docx, paragraphs + tables
                                     └── .jpg .jpeg .png .bmp .tiff .tif
                                                       → one metadata-only chunk
                                                         (size/format/mode) — no OCR
```

Two things to know here. `.xls` passes upload validation and is routed to
`_ingest_excel`, but that function calls `openpyxl.load_workbook`, which cannot read
legacy `.xls` — those uploads fail at ingest time. And there is **no OCR anywhere in
the ingest path**: images become a metadata chunk and scanned PDFs yield only
whatever text layer they already carry (see §12 for the state of the Docling path).
`RETAIN_UPLOADED_FILES=false` deletes the uploaded file from disk after ingestion.

### 4.1 The three-stage PDF path

[pipeline/ingestion.py](backend/process/pipeline/ingestion.py) is deliberately
redundant, because no single PDF extractor handles technical manuals well:

**Stage 1 — OpenDataLoader (preferred).** A Java-backed extractor invoked in
120-page batches (`ODL_PAGE_BATCH_SIZE`) under a 6 GB JVM heap. Returns typed
elements: headings, text, tables. Batch-relative page numbers are shifted back to
absolute. Headings become table captions via `_odl_caption()` — the nearest heading
at or above the table's page.

**Stage 2 — PyMuPDF (fallback).** If ODL is missing (no Java) or throws, the whole
document is re-run through PyMuPDF's `page.find_tables()`. This path adds
**multi-page table merging**: `_is_table_continuation()` decides whether a table
starting at the top of page N+1 is really the continuation of the one that ended on
page N (column counts within ±1, and a blank, very short (< 10 chars) or dissimilar
header), and merges it.
Captions come from `_extract_headings_pymupdf()`, which infers headings by font
size ≥ 1.2× the page median, bold weight, or a `3.2 Title` numbering pattern.

> **Cost.** On a 582-page spares list this whole path takes minutes, and profiling on
> evenly-sampled real pages shows where: pdfplumber's ruled-table detection is ~500 ms
> per table-dense page (~97% of parse time), while PyMuPDF text extraction of the same
> document is ~1 s in total. Two fixes landed after measuring — table storage became one
> transaction with bulk inserts (4.89 → 0.14 ms per cell, a third of total ingest time
> removed), and the anchor extractor now takes its word boxes from PyMuPDF instead of
> pdfplumber. Replacing pdfplumber's ruled-table pass with PyMuPDF's `find_tables()` was
> tried and **rejected**: it looked 1.6x faster on one document but loses cells on others
> (an MRLS dropped from 18 tables to 6). See MEMORY.md §2.6.

**Stage 3 — pdfplumber supplementary pass (always runs).** Both engines above miss
**line-less tables** — spares lists laid out purely by column position with no ruled
borders. This pass, `_ingest_pdfplumber_tables()`, catches them using the *anchor
extractor* described in §7.1. It writes to SQL only — nothing from this pass is
embedded into Chroma. Duplicate tables are harmless because comparisons dedupe by
value.

Because this pass is what feeds the fast DB-backed comparison path, documents
ingested before it existed (or before a fix to it) have no or stale tables.
`manage.py reextract_tables` re-runs *only* this pass — no re-embedding, no Ollama
— and is the supported way to repair them:

```
manage.py reextract_tables              # PDFs with no pdfplumber tables yet
manage.py reextract_tables --all        # refresh everything after an extractor fix
manage.py reextract_tables --source ISPL_MMME --dry-run
```

The effect is not cosmetic: on the NAMICA pair the DB path went from *no result at
all* to exactly the file path's numbers (64 common / 7 likely / 3 missing / 54
extra) and from 7.9 s to 0.6 s.

### 4.2 Chunking, embedding, and the dual index

Text is cleaned (`_is_noise_line` strips page numbers, rules, `RESTRICTED`-style
watermarks), then chunked at **200 words with 40-word overlap**, page by page.
The 200/40 are the defaults of `smart_chunk_text(text, max_words=200, overlap=40)`,
not config constants; chunks under 50 characters are dropped.

Every chunk is embedded once and written to **two** indexes under the **same chunk ID**:

```
_embed_and_store(chunks, metas, ids, collection)
    ├── model_manager.encode()      → Ollama /api/embed, batches of 8
    ├── collection.add(...)         → ChromaDB, batches of 5000
    └── bm25_index.add_batch(...)   → BM25 pickle, same IDs
```

Sharing IDs is the whole trick — it is what lets retrieval fuse the two rankings
later without any join.

Practical details that matter:
- Chunks are truncated to **8000 chars** before embedding (`nomic-embed-text`'s
  8192-token window). This is the fix for the `HTTP 400 input length exceeds context` class of error.
- The Chroma collection **name encodes provider + dimension**
  (`rag_knowledge_base_ollama_768`). Switching embedding models therefore lands in a
  fresh collection instead of silently mixing incompatible vector spaces. (One legacy
  carve-out: `sentence-transformers` at 384 dims keeps the bare `rag_knowledge_base`
  name.) The re-embed started from Settings pages the old collection 200 chunks at a
  time into the new one, then rebuilds BM25 from it.
- The BM25 index is a pickle (`local_chroma_db/bm25_index.pkl`) loaded **once at
  import** into a module-level singleton. Despite the module docstring, it does
  **not** rebuild itself when the file is missing — `rebuild_from_chroma()` is only
  called at the end of a re-embed. Lose the pickle and keyword search silently returns
  nothing (retrieval degrades to vector-only) until the next re-embed.
- A **table quality gate** (`_is_quality_table`) rejects anything with < 2 columns
  or < 25 % filled cells, so page furniture doesn't pollute the table store.

---

## 5. Query — how a chat message becomes an answer

There are **two routers in series**, which surprises people. `views.chat_thread`
routes first; only if it declines does `query_rag` route again.

### 5.1 Router 1 — `views.chat_thread` ([views.py:354](backend/process/views.py#L354))

Deterministic, keyword-driven, and it wins when it fires:

```
save user message   (the last 5 messages are also captured as conversation_context)
   │
   ├─ _resolve_conversation_references()   "compare this" → resolved with history
   │
   ├─ confirm-match?      "confirm X and Y are the same … in @a.pdf and @b.pdf"
   │                       → writes a ConfirmedMatch row   (checked first; narrow regex)
   ├─ set-column?         'set the part no column to "Firms Part No." in @a.pdf'
   │                       → writes a ColumnRole row (§7.2); also `clear the … column`
   ├─ conflict query?     any of 9 words — duplicate / repeated / conflict / inconsistent /
   │                       same nomenclature / different part number / different drawing …
   │                       → detect_conflicts() + Excel report   (a single PDF is enough)
   ├─ comparison query?   any of ~17 words (compare / difference / missing / vs / between /
   │                       "present or not" …), OR the strict-assessment rule below, OR an
   │                       assessment word + domain word when the thread holds ≥2 PDFs
   │                       → _extract_comparison_info() → comparison.run_comparison()
   │                            2 files  → pairwise;  ≥3 files → presence matrix (§6.1)
   ├─ table search?       explicit "part number" / "drawing no" / code-shaped token
   │                       → search_in_pdf() via pdfplumber; a miss falls through ↓
   │
   └─ otherwise ────────────────────────────────────► query_rag()
```

Two scoping details are easy to miss. The conflict and table-search branches query
`Document.objects.filter(thread=thread)` — the **current thread only** — while the
comparison branch and `query_rag` include ancestor threads; an inherited PDF is
therefore invisible to conflict detection and table search. And the comparison and
conflict branches have side effects on every turn: they generate an Excel file,
register it in an in-memory report store, and append a download link to the answer.

The **strict-assessment rule** fires on ≥2 `.pdf` mentions + a domain word
(drg / drawing / dwg / part / nsn) + an intent word (compare / between / present /
found / assessment / confirm / whether). When it fires and extraction fails, the
router retries once with the query rewritten as `Compare DRG present or not between
…`; if that also fails it **refuses to fall back to a narrative RAG answer** and returns
an explicit "Assessment Could Not Be Completed, try this exact format" message — a
wrong-but-fluent LLM answer is worse than an honest failure for this use case.

### 5.2 Router 2 — `query_rag` ([pipeline/query.py:1105](backend/process/pipeline/query.py#L1105))

```
query
  ├─ compare intent (≥2 compare words)?
  │    ├─ ≥2 files + ≥2 comma-separated columns → _gen_lookup_multi_col (§6.3)
  │    └─ ≥2 files → _gen_compare / _gen_compare_multi
  │                    both call comparison.run_comparison() — the same engine,
  │                    formatting and Excel report the chat router uses (§6.1)
  │
  ├─ extract_file_filter()   strips "@name.pdf|xlsx|xls|docx" → scopes retrieval to one file
  ├─ _classify_intent()      → LIST | FIND | QUESTION | LOOKUP
  ├─ _is_table_query()       → table keywords, or a part-code-shaped regex hit
  │
  ├─ RETRIEVE
  │    ├─ _retrieve_vectors()  hybrid, always
  │    └─ search_tables()      SQL, only if table-ish or LIST/FIND
  │
  └─ GENERATE
       tables present?
         LIST              → _gen_list        pure extraction, no LLM, conf 95 HIGH
         QUESTION/LOOKUP   → _gen_sql_answer  LLM grounded in matched rows, conf 95 HIGH
                                              (>50 tables and no term hit → conf 30 LOW)
         anything else, or either of the above returned None
                           → _gen_location    "found in these tables", conf 100 EXACT_MATCH
       no tables
                           → _gen_text_answer classic RAG, conf = evaluated
                                              (0 LOW if no chunks, 0 ERROR if Ollama fails)
```

`query_rag` accepts `conversation_history` and `parent_thread_id` but uses neither:
ancestry is re-derived via `get_ancestor_ids()`, and multi-turn context only reaches
the model through the string rewriting `_resolve_conversation_references` does
upstream. `search_tables()` has no relevance ranking and, when nothing matches, returns
**every** table in the thread tree — that is what trips the >50-table LOW exit above.

### 5.3 Hybrid retrieval (RRF)

`_retrieve_vectors()` runs both indexes and fuses them with **Reciprocal Rank Fusion**:

```
vector search  (Chroma, k=10, filtered by thread ancestry [+ file])
keyword search (BM25,   k=10, same filters)
        │
        └── score(id) = Σ  1 / (60 + rank)     over both result lists
                        └─ top 5 chunks survive
```

RRF needs no score normalisation between two incomparable scales, and it is why the
system finds a bare part number (BM25's strength) *and* a paraphrased concept
(vector's strength) with one query. `_RRF_K = 60` lives in `query.py`, not
`config.py`. The fused score is converted back into a pseudo-distance
(`1 - score × 60`) purely so the UI can keep showing a similarity bar; SQL-table hits
are shown with similarity `0.0`.

### 5.4 Confidence scoring

Only the pure-semantic path is actually measured. `_evaluate()`
([pipeline/query.py:183](backend/process/pipeline/query.py#L183)) blends three
embedding-cosine primitives from
[eval_utils.py](backend/process/eval_utils.py):

```
relevance          = cosine(query, answer)
faithfulness       = fraction of retrieved chunks with cosine(answer, chunk) ≥ 0.35
context_precision  = fraction of retrieved chunks with cosine(query,  chunk) ≥ 0.35

score = (relevance × 0.4 + faithfulness × 0.4 + context_precision × 0.2) × 100
        ≥75 HIGH · ≥50 MEDIUM · else LOW      (0 / LOW on any exception)
```

Deterministic paths (SQL extraction, table location) hard-code 95–100, because
their answer *is* the data rather than a generation over it. Note the **two scales
that reach the client**: `query_rag` returns 0–100 with upper-case labels
(`95.0 / "HIGH"`, `100.0 / "EXACT_MATCH"`), whereas Router 1's table-search branch
returns `0.95 / "High"`. `context_recall` in `eval_utils.py` is never called.

---

## 6. Table comparison — one engine, three front ends

This is where most of the domain complexity lives.
[comparison.py](backend/process/comparison.py) is the **single entry point** for
every conversational comparison — both chat routers call it, so the same question
gets the same answer whichever router's keyword list catches it. (Until recently
Router 2 used a separate `pipeline/tables.py` engine with 0.75 SequenceMatcher
fuzzy matching, which merges sequential part numbers; that engine has been deleted.)

```
views.chat_thread (Router 1) ─┐
pipeline/query.query_rag (R2) ─┴→ comparison.run_comparison()
                                    ├─ resolve_documents()   names → Document rows
                                    ├─ 2 docs → compare_documents()  (§6.1)
                                    ├─ ≥3     → compare_many()       presence matrix
                                    ├─ text mode → compare_against_text() (§6.4)
                                    ├─ format_*()                    markdown
                                    └─ attach_excel_report()         xlsx + link
```

`compare_documents()` tries the **DB path first** (persisted `ExtractedTable` rows —
works after the upload is gone, and is the only path for xlsx/docx), then falls back
to re-reading the PDFs from disk. Every failure is an explicit answer, never a
silent narrative fallback: "Column Not Found" lists both documents' real headers and
points at `field_schema.json`; "No Extracted Tables" points at `reextract_tables`.

### 6.1 The matching cascade — `table_search_engine.compare_tables()`

The engine underneath. `compare_tables()` runs this cascade:

```
1. resolve the column per document      (§7.2 — category-aware header schema)
2. normalise values, extract sets A and B
3. set difference → only_in_A, only_in_B, common
   └ side channel: count per-value occurrences in B, taken here on the raw rows
     ("present" vs "present 3 times" are different questions)
4. subtract user-ConfirmedMatch pairs   ← human decisions win, always, first
5. subtract boilerplate values          ("Standard Item", footnote markers)
6. pair_likely_values(A_left, B_left)   ← leading zeros, annotation prefixes, typos
7. second-chance pass: pair leftovers against values that ALREADY matched exactly
   (catches MRLS listing both "XL17461" and "XL17461 NAMICA")
```

A ninth step then asks a different question of the values that *did* match: do the
two documents agree about them? `_row_differences()` cross-checks nomenclature, NSN
and quantity for each matched row and reports what disagrees — the `modified`
bucket, "same part, different details".

Making that signal rather than noise took three rules, without which every matched
row was flagged (71 of 71 on the NAMICA pair; now 2):

- values are compared with every separator stripped, because PDF extraction yields
  `Set ofFuelLine- 1setconsist` in one document and `Set of Fuel Line - 1 set
  consist` in the other;
- **quantities are only compared between columns labelled the same way** — an MRLS
  `Total Qty. / Launcher` (fleet total) and an ISPL `No. Off` (fitted in one
  assembly) both resolve to `qty` but count different things, so `18 nos.` vs `1`
  is two questions, not a discrepancy. Same-header pairs are the revision-vs-revision
  case, where a change *is* meaningful;
- figure/drawing references are excluded outright — `Figure3- 12,Item No.1` versus
  `Figure 3-12 1` is house style.

Steps 4–7 exist because "is this part in that manual?" is almost never a string
equality question in real documents. Each rule is deterministic and reviewable;
nothing is fuzzy-matched into a silent pass — the typo pass is Levenshtein ≤ 1
(≤ 2 over 15 chars) and is gated to word-like values only, so sequential catalogue
codes (`10106255` / `10106256`) can never merge.

For **three or more documents**, `compare_many()` runs this same pairwise cascade
once per target and folds the results into a per-value presence matrix
(`exact | confirmed | likely | missing | n/a` per file), so "is every part in the
MRLS present in these four manuals?" is one question with one answer. The chat reply
leads with the values missing from *every* file; the Excel report carries the full
matrix. Naming ≥3 files used to silently compare only the first two.

One implementation detail matters for debugging: `TableSearchEngine` is a module
singleton whose `extracted_tables` cache is keyed by **bare filename**.
`compare_structured_sources()` borrows those keys for the duration of one call and
restores whatever was there afterwards, and the file-backed fallback passes
`force_extract=True`, so the two paths can no longer hand each other stale tables.
Two documents that share a filename across threads still collide within a single
process; nothing evicts entries.

### 6.2 Batch comparison — `reports_engine.py` (Reports page)

Different problem: *one source column vs many whole PDFs*, with an Excel deliverable.

```
POST /api/reports/compare/     → create_report_job() → job_id, thread starts
GET  /api/reports/status/<id>/ → {progress, message, logs[]}   ← frontend polls
GET  /api/reports/download/<id>/ → xlsx bytes
```

`MultiPDFComparator` extracts the source column's unique values, then walks the
target PDFs **carrying forward only the not-yet-found set** — each PDF only searches
for what previous PDFs missed, so cost falls as matches accumulate. Matching uses a
**spaced + no-space dual normalisation** (`_normalize_for_match`), because PDF text
extraction drops spaces when a cell wraps: `BIG LAUNCHER PAD` becomes
`BIG LAUNCHERPAD`. Comparing both variants recovers those without loosening the
match. Docling with OCR is used when available; PyPDF2 supplies accurate page
numbers. **Docling is not in `requirements.txt`**, so in every shipped configuration
`_init_docling` hits its `ImportError` branch and the `use_ocr` request flag is a
no-op — the Reports path is PyPDF2 text-layer only. Jobs live in an **in-process
dict** (`_report_jobs`); a second one, `_comparison_reports` in `views.py`, holds
Excel bytes for chat-generated reports and is checked first by `download_report`.
Neither survives a restart. `reports_engine_merge.py` is a near-duplicate of
`reports_engine.py` (1469 vs 1431 lines) that `download_report` falls back to for
both status and Excel bytes; nothing else imports it.

### 6.3 Per-row OR-matching — `_gen_lookup_multi_col`

The "is every spare in `spares.pdf` mentioned anywhere in `manual.pdf`?" question.
For each source row, several identifier columns are OR-matched against a flattened
corpus of each target's cells — a row counts as found if **any** of its identifiers
appears in **any** target. Output leads with the actionable list: what is missing
everywhere.

Triggered from chat by naming ≥2 files and ≥2 comma-separated columns:
`compare part no, nomenclature between @spares.pdf and @manual.pdf`.

---

### 6.4 Text mode — a column vs a manual's whole text

Column-to-column comparison presumes both documents are tables. A technical
manual is not one: it mentions part numbers in running text, figure callouts and
maintenance steps. Prose lives only in ChromaDB as embedded chunks, which cannot
answer *"does the exact string XL17461 appear in this document?"* — so before
this, a spares list could only ever be compared against another table.

[mentions.py](backend/process/mentions.py) keeps a SQL-searchable copy of every
document's text, from **both prose and table cells**:

```
ingest ─→ _embed_and_store()  ─→ index_chunks()   one hook, every document type
       └→ _ingest_pdfplumber_tables() ─→ index_tables()

DocumentPageText    page text, twice: whitespace-collapsed and whitespace-free
IdentifierMention   every identifier-shaped token, with its page
```

`compare_against_text()` then answers *"is every part in the MRLS mentioned
anywhere in these manuals?"* — each source value is looked up in each target and
reported with the pages it was found on. Lookup is two-pass: an indexed exact
token hit (the common case), then whole-page substring containment for what is
left, each tried against both the spaced and the space-free form — the same
trick the reports engine uses, because PDF extraction drops spaces when a line
wraps.

Two things keep this honest:

- **The same near-match rules as column mode.** A value absent verbatim is
  re-checked against the target's identifier vocabulary with
  `pair_likely_values` (leading zeros, annotation prefixes, typos in word-like
  values). Without it, text mode called `XL17461 NAMICA` missing from a document
  that says `XL17461`, contradicting the column answer for the very same pair.
  Variant hits are reported as ⚠️, never silently as matches.
- **Nothing is fuzzy.** A hit is an exact substring of the document's own text,
  or an explicitly-reasoned variant.

Triggered by asking about *mentions* rather than a diff ("are all the part
numbers in @spares.pdf mentioned anywhere in @manual.pdf"), and automatically
whenever a column comparison fails only because the target has no such column —
the spares-list-vs-manual case, answered instead of refused.

Measured on the NAMICA pair: column mode reports 64 exact + 7 near-matches + 3
missing; text mode against the ISPL's full text reports 70 mentioned (4 as
variants) and **the same 3 missing**. The two modes agree.

New uploads are indexed during ingestion; existing documents need one pass of
`manage.py build_mention_index` (no re-embedding, Ollama not required).

---

## 7. The two hard problems, and how they're solved

### 7.1 Line-less tables — the anchor extractor

Defence spares lists print a numbered reference row (`1 2 3 … 8`) under the header
and then rely on column alignment alone. No ruling lines means
`page.extract_tables()` returns nothing.

`_extract_anchor_tables()` ([table_search_engine.py:333](backend/process/table_search_engine.py#L333))
reconstructs the grid geometrically:

```
1. cluster words into lines by y-coordinate (±3pt), drop the RESTRICTED watermark
2. find the "1 2 3 … N" row  → its x-centres ARE the column centres
3. column bounds = midpoints between adjacent centres
4. header  = words in the 60pt band above the anchor, bucketed into those columns
5. rows    = a new logical row starts when column 0 holds a serial number ("11.");
             every other line is a wrapped continuation appended to the row above
6. stop at the first footnote/terminator line after real data has started
```

Two corrections then run on the reconstructed headers:

- **`_canonicalise_spares_headers()`** — wrapped headers arrive fragmented
  (`Manufacturer's` and `Part No.` on different visual rows). When the spares-list
  signature is present (a part-column pattern *and* a context column like
  Nomenclature or Source of Supply), columns snap to canonical names by keyword.
  Critically, column 0 is forced to `Sr. No.` so the serial column can never
  masquerade as the part column.
- **Header carry-forward (`header_memo`)** — continuation pages reprint the numbered
  anchor row but not the header band, leaving every column named `Column_N`. The
  memo, keyed by column count, replays the header from the page where the table
  started. `load_structured_tables()` repeats this repair when reading back rows that
  were persisted with a bad header — and pushes the misread header row back into the
  data where it belongs.

### 7.2 The same concept, a different label per document

An MRLS calls it `Manufacturer's Part No.`; the matching ISPL calls it `DS Cat No.`;
a catalog calls it `P/N`. A user typing "compare part" must reach the right real
column **in each document independently**.

[field_schema.py](backend/process/field_schema.py) solves this in two layers:

```
CANONICAL_FIELDS   what the user might type      → canonical key
                   "part", "p/n", "firms part no" → part_no
                   (keys: part_no, nomenclature, drawing_no, nsn, qty, serial, reference)

CATEGORY_SCHEMA    canonical key + doc category  → ordered header patterns
                   categories: mrls, ispl, catalog, manual, specification,
                               drawing, other, _default (fallback)
                   part_no @ any → manufacturer's / mfr / mfg / oem / firm's part no …
                                   ▲ the identifier that lines up ACROSS documents
                                     always outranks a service-internal number
                   part_no @ ispl → …then "ds cat no", "cat no", "part no", "part"
                   nsn     @ ispl → ["ds cat no", …]
                                     ▲ first match wins — order is priority
```

`resolve_header(term, real_headers, category, prefer_literal=False)` returns the
actual header string to use. Matching is quote-glyph and punctuation insensitive in
both directions, so a pattern `firms part no` hits `Firm's Part-No.` and `FIRMS PART
NO`, and `part no` hits `Part-No.`.

**The schema is data, not code.** Dropping a `field_schema.json` beside the data
(`%APPDATA%\RAG-OCR\data\` in the packaged app, `backend/` in dev) extends or
overrides it — new header names, new document categories, different priority order —
and it is re-read whenever the file changes: no rebuild, no restart, no
`patch-runtime.ps1`. `canonical_fields` entries are appended; a
`category_schema[cat][field]` list replaces the built-in one, because order is
priority and you must be able to control it. An invalid file is ignored with the
error kept, and the last good schema stays in force. `GET /api/field-schema/` returns
the effective schema, the override path, and any load error — the first thing to look
at when a comparison reports "Column Not Found".
See `backend/field_schema.example.json`.

**When the header is unknown anyway.**
[column_profile.py](backend/process/column_profile.py) scores a column by what
its *values* look like — code-shaped, distinct, not a 1..N counter — and lists
the columns that hold identifiers. It is deliberately **advisory only**: measured
against the real MRLS/ISPL pairs it reliably finds identifier columns but cannot
tell a part number from a stock number without the header (an `NSN Nos.` column
outscores the real part column), and silently comparing the wrong column is the
one failure this codebase works hardest to avoid. So it never picks a column — it
adds a "these columns hold identifier-shaped values" hint to the *Column Not
Found* message, leaving the choice with the person who can read the document.

**Resolution order.** A pinned column beats the schema, and a header quoted in the
current query beats everything:

```
"Firms Part No." quoted in THIS query    most specific instruction available
  └→ ColumnRole for (document, concept)   a person read the document and decided
      └→ CATEGORY_SCHEMA for its category  the rules above
          └→ fail — with value-shape suggestions
```

[column_roles.py](backend/process/column_roles.py) stores **only** the human
decisions. Schema resolutions are recomputed on every query rather than cached, so
editing `field_schema.json` improves every document at once instead of leaving stale
rows behind. Pins are set from chat (`set the part no column to "X" in @a.pdf`) or
over `GET/POST/DELETE /api/documents/<id>/columns/`, which also reports *why* each
concept currently resolves the way it does (`origin: user | schema | none`).

Two further escape hatches sit on top:
- **Quoted columns** in a chat query (`compare "Firms Part No." in @a.pdf with "DS Cat No." in @b.pdf`)
  switch resolution to **literal** mode, bypassing the canonical mapping entirely —
  the user named the header, so it is not second-guessed.
- **`ConfirmedMatch`** records human decisions that no rule anticipated
  (`NAMP-08020000` ≡ `DIC-NAMP-08020000`), scoped to the file pair *and* the column
  concept so a part-number alias never leaks into a drawing-number comparison.

---

## 8. Document diff — the Compare page

Entirely separate from everything above; no embeddings, no tables.
[document_compare.py](backend/process/document_compare.py) extracts plain lines
(PyMuPDF / python-docx / openpyxl), runs `difflib.SequenceMatcher`, and classifies
each line `equal | added | removed | modified`. It runs as a polled background job
like Reports, and an LLM summary of the diff is available via `llm_summary.py`.

---

## 9. Frontend

React 18 + React Router + Tailwind 4, five routes in
[frontend/src/App.jsx](frontend/src/App.jsx):

| Route | Purpose |
|---|---|
| `/` | Landing |
| `/workspace` | Threads sidebar · chat · document panel — the main surface |
| `/reports` | Column comparator wizard → live progress log → Excel download |
| `/compare` | Two-file line diff viewer, paginated at 100 lines |
| `/settings` | Embedding provider, LLM selection, re-embed status |

Every call goes through the single wrapper in
[frontend/src/services/api.js](frontend/src/services/api.js). There is **no
websocket** anywhere — all long-running work (ingestion, reports, diffs) is
progress-polled over plain HTTP.

In dev, Vite proxies `/api` and `/media` to `:8000`. In the packaged build Django
serves the SPA itself: the catch-all in
[backend/ragocr/urls.py](backend/ragocr/urls.py) returns `index.html` for any path
that isn't `api/`, `admin/`, `static/` or `media/`, letting React Router own routing.

---

## 10. Configuration and state

| Var | Default | Effect |
|---|---|---|
| `OLLAMA_API_BASE` | `http://localhost:11434` | Where embed + generate calls go |
| `RAGOCR_DATA_DIR` | unset | **Relocates all state** — sqlite, media, Chroma, BM25, logs |
| `RAGOCR_FRONTEND_DIR` | unset | Override for the built SPA path |
| `DEBUG` / `ALLOWED_HOSTS` / `CORS_ALLOWED_ORIGINS` | Django defaults | Standard |
| `ODL_JAVA_OPTS` | `-Xms512m -Xmx6g -XX:+UseG1GC` | JVM heap for OpenDataLoader (copied into `JAVA_TOOL_OPTIONS` if that is unset) |
| `ODL_PAGE_BATCH_SIZE` | `120` | Pages per ODL invocation |
| `RETAIN_UPLOADED_FILES` | `true` | `false` deletes the upload from disk after ingestion |
| `SECRET_KEY` | dev fallback | Django secret; set it in any shared deployment |
| `ANONYMIZED_TELEMETRY` | forced `False` | Disables Chroma telemetry (set by `config.py`) |

Runtime-mutable settings live in the `AppConfig` key/value table, not in env —
changed from the Settings page, read on next use. Keys: `llm_model`,
`embedding_provider`, `ollama_embedding_model`, `embedding_model_path`.

One more piece of runtime-editable state is a file rather than a row:
`<data dir>/field_schema.json` overrides the column-name schema (§7.2), re-read on
change.

Logging: when `RAGOCR_DATA_DIR` is set, Django logs to a rotating
`<data>/logs/ragocr.log`; otherwise to the console only. Most of the pipeline still
uses bare `print()`, which is what you see in the launcher's stdout.

`RAGOCR_DATA_DIR` is the pivot for packaging: the Electron launcher sets it to
`%APPDATA%\RAG-OCR\data\`, which moves every writable artefact out of the read-only
app bundle in one move.

State that **does not persist across a restart**: report jobs (`_report_jobs`),
chat-generated report bytes (`_comparison_reports`), diff jobs, the comparator's
temp-file cache, `TableSearchEngine.extracted_tables`, and the loaded-model flag.
State that does: sqlite, Chroma, the BM25 pickle, uploaded files.

---

## 11. Startup sequence

```
Django starts
  └─ ProcessConfig.ready()          [process/apps.py]
       └─ daemon thread, 0.5s delay
            ├─ read AppConfig["ollama_embedding_model"]
            └─ model_manager.load_model()   probes Ollama for the vector dimension
```

Model init is **non-blocking and failure-tolerant** — if Ollama isn't up yet, the
app still serves and the model loads on first use. The 0.5 s delay is a race guard
against the DB not being ready; in the standalone launcher this occasionally races
migrations and logs a harmless first-run `no such table: process_appconfig`.

Deployment shapes:

- **Docker** — gunicorn (**1 worker**, 8 threads, 300 s timeout) behind an nginx
  frontend container; Ollama reached via `host.docker.internal`. Four named volumes
  keep sqlite/pdfs/chroma/media outside the image. The single worker is deliberate:
  job dicts, daemon ingestion threads and the BM25 index all live in process memory,
  so a second worker made status polls 404 intermittently and left keyword search
  stale. Concurrency comes from threads; `--max-requests` recycling was removed
  because it killed long ingestions mid-run.
- **Standalone Electron** — [standalone-launcher/](standalone-launcher/) (not
  `electron-launcher/`, which is a separate Docker-stack control panel that never
  touches Python). Its `main.js` picks a free port, runs `manage.py migrate`, spawns
  `runserver --noreload --insecure` against a bundled Python + JRE runtime, waits for
  `/api/model/status/` to answer, then opens a BrowserWindow on Django's own port.
  `patch-runtime.ps1` hot-swaps backend code into an installed launcher without a
  full rebuild.

---

## 12. Reading the code — a map

Start here, in this order:

| To understand… | Read |
|---|---|
| How a file becomes searchable | [pipeline/ingestion.py](backend/process/pipeline/ingestion.py) — `_ingest_pdf` |
| How a question becomes an answer | [pipeline/query.py](backend/process/pipeline/query.py) — `query_rag` at the bottom |
| How two documents get compared | [comparison.py](backend/process/comparison.py) — `run_comparison` |
| How a spares list is checked against a manual | [mentions.py](backend/process/mentions.py) + `comparison.compare_against_text` |
| Why chat sometimes bypasses RAG | [views.py:354](backend/process/views.py#L354) — `chat_thread` |
| Hybrid search | [pipeline/query.py](backend/process/pipeline/query.py) — `_retrieve_vectors` |
| Line-less table extraction | [table_search_engine.py:333](backend/process/table_search_engine.py#L333) — `_extract_anchor_tables` |
| Column name resolution | [field_schema.py](backend/process/field_schema.py) — then [column_roles.py](backend/process/column_roles.py) |
| Batch comparison + Excel | [reports_engine.py](backend/process/reports_engine.py) — `MultiPDFComparator` |
| Tuning constants | [pipeline/config.py](backend/process/pipeline/config.py) |

`process/rag_engine.py` is a **compatibility shim** — it only re-exports
`process/pipeline/`. New code should import from `pipeline` directly.

### Extension points

- **New file type** → add an extractor + one entry to `_DISPATCH` in `ingestion.py`.
- **New column name / document category** → usually no code at all: add it to
  `field_schema.json` (§7.2) and it takes effect on the next query. Edit
  `field_schema.py` only to change the shipped defaults.
- **New comparable concept** → add to `CANONICAL_FIELDS` *and* to each category.
- **Retrieval tuning** → `CANDIDATE_K`, `MAX_FINAL_CHUNKS`, `_RRF_K`, chunk size in
  `smart_chunk_text`.

### Sharp edges

- Changing the embedding model changes the Chroma collection name — old vectors
  become invisible rather than corrupt. Re-embed from Settings.
- The chat router is keyword-driven; adding keywords to one branch can steal queries
  from another. `_CONFIRM_MATCH_RE` is checked first and narrowly for exactly this
  reason. Both routers now share one comparison engine (§6), so which one catches a
  query no longer changes the answer.
- Report and comparison jobs are in-memory dicts. A restart loses in-flight work and
  makes pending `job_id`s 404.
- **The code assumes a single process.** Job dicts, ingestion threads and the BM25
  index all live in process memory, which is why Docker runs `--workers 1 --threads 8`.
  Do not raise the worker count without moving that state out of process.
- Ingestion threads are daemons — a shutdown (or worker recycle) mid-ingest leaves a
  `Document` stuck in `processing`.
- The BM25 pickle does not auto-rebuild if missing (§4.2).
- `TableSearchEngine.extracted_tables` is a filename-keyed, never-evicted cache.
  The compare paths no longer leak tables into each other (§6.1), but two documents
  with the same filename in different threads still share an entry.
- The Reports page's OCR toggle does nothing: Docling is not installed, and there is
  no other OCR engine in the codebase. Scanned PDFs produce no text and no tables —
  and therefore no mention index either, so text mode (§6.4) silently has nothing to
  search for them. The Landing page still advertises "Smart OCR".
- The mention index is built at ingest. Documents ingested earlier answer "not
  mentioned" for everything until `manage.py build_mention_index` has run.
- `.xls` is accepted at upload and fails at ingest (§4).
- The conflict and table-search chat branches ignore inherited (ancestor-thread)
  documents; comparison and RAG include them (§5.1).
- Comparison covers pdf/xlsx/xls/docx, but the file-backed fallback is PDF-only —
  an xlsx with no persisted tables cannot be compared until it is re-ingested.
- Confidence reaches the client on two scales, `0.95 / "High"` and `95.0 / "HIGH"`
  (§5.4).
- `query_rag` ignores `conversation_history`; `suggested_questions` is always empty.
- There are no automated tests (`process/tests.py` is empty). The de-facto regression
  check is the NAMICA MRLS↔ISPL "part" comparison: 64 common / 7 likely / 3 MRLS-only /
  54 ISPL-only after boilerplate exclusion — the file path and (after
  `reextract_tables`) the DB path must both produce exactly that.
