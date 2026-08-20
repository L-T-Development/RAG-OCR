# RAG-OCR — Comparison Work: Status & Roadmap

**Last updated:** 2026-08-19

The goal driving this work, in the user's words: *compare files with each other — be it
ISPL, MRLS or manuals — mostly tables, comparing part numbers or any other column. The
problem is that one ISPL calls it "Part No", another calls it "Manufacturer's Part No",
and some documents are manuals containing descriptive prose, where the question becomes
"are all the part numbers in the ISPL mentioned in the manual?"*

That splits into four hard requirements, and this document tracks them:

| # | Requirement | Status |
|---|---|---|
| A | The same concept is labelled differently in every document | ✅ solved (schema + data-driven overrides) |
| B | Compare **all** files, not just two | ✅ solved (N-way presence matrix) |
| C | Targets are prose manuals, not tables | ✅ solved (identifier mention index) |
| D | One answer per question, whichever way it is phrased | ✅ solved (single comparison engine) |

> This file is the roadmap and status record. For *how the system works*, see
> [HOW_IT_WORKS.md](HOW_IT_WORKS.md). For setup and deployment see
> [README.md](README.md) and [DOCKER_DEPLOYMENT.md](DOCKER_DEPLOYMENT.md).

---

## Phase 0 — Foundations ✅ COMPLETE (2026-08-19)

*Goal: stop the bleeding — one engine, extensible column names, repairable data.*

### 0.1 The header schema became data, not code ✅
- `backend/process/field_schema.py`: added the missing variants (`firms/firm's part no`,
  `mfr / mfg / oem / vendor / supplier part no`, `part code`, `catalogue no`, `stock no`).
- Added real schema rows for `manual`, `specification`, `drawing`, `other` — all four
  previously fell through to a generic fallback.
- A shared `_PART_ID_PATTERNS` list makes the **cross-document** identifier
  (manufacturer's / OEM / firm's part no) outrank service-internal numbers
  (`DS Cat No.`) in *every* category. This is what makes MRLS ↔ ISPL parts line up.
- Header matching is punctuation-insensitive both ways: pattern `firms part no` now
  hits `Firm's Part-No.` and `FIRMS PART NO`.
- **Extensible without a rebuild:** drop a `field_schema.json` beside the data
  (`%APPDATA%\RAG-OCR\data\` packaged, `backend/` in dev). Re-read on change — no
  restart, no `patch-runtime.ps1`. Invalid file is ignored and the last good schema
  stays live. See `backend/field_schema.example.json`.
- `GET /api/field-schema/` returns the effective schema, override path and any load
  error — the first thing to check on a "Column Not Found".
- *Verified:* 16 resolution cases pass, including `Firms Part No.` beating `DS Cat No.`
  in an ISPL, and override hot-reload / validation / bad-file tolerance.

### 0.2 One comparison engine ✅
- New `backend/process/comparison.py` is **the** entry point. Both chat routers
  (`views.chat_thread` and `pipeline/query.query_rag`) call `run_comparison()`.
- Deleted the rival fuzzy engine in `pipeline/tables.py` (SequenceMatcher ≥ 0.75, which
  merges sequential part numbers like `10106255`/`10106256`) — **670 → 265 lines**.
- **Naming ≥3 files no longer silently compares only the first two** — you get a
  value × file presence matrix, led by "missing from every file", with its own Excel sheet.
- Comparison now covers **xlsx / xls / docx**, not just PDF.
- Fixed a filename-keyed cache collision where the DB and file paths handed each other
  stale tables (`compare_structured_sources` saves/restores; `compare_pdfs(force_extract=True)`).
- Every failure is now an explicit answer, never a silent narrative fallback.

### 0.3 `manage.py reextract_tables` ✅
Back-fills the structured table store for documents ingested before the extraction pass
existed (or after a fix to it). No re-embedding, Ollama not required.

### 0.4 Docker single worker ✅
`--workers 1 --threads 8`, `--max-requests` removed. Job dicts, ingestion daemon threads
and the BM25 index are all per-process; a second worker made status polls 404
intermittently, left keyword search stale, and recycling killed long ingestions.

---

## Phase 1 — Answering the real question ✅ COMPLETE (2026-08-19)

### 1.1 Identifier mention index ✅ — *the headline feature*
**The problem:** prose lived only in ChromaDB as embeddings, which cannot answer
*"does the exact string XL17461 appear in this manual?"* So a spares list could only ever
be compared against another **table**. Manuals mention parts in running text, figure
callouts and maintenance steps — all invisible to comparison.

**The fix:** `backend/process/mentions.py` + models `DocumentPageText` and
`IdentifierMention` (migration `0012`, additive).
- Every document's page text is mirrored into SQL in two forms (whitespace-collapsed and
  whitespace-free — PDF extraction drops spaces when a line wraps), plus one indexed row
  per identifier-shaped token with its page.
- Indexed from **both prose and table cells**.
- **One ingestion hook** (`_embed_and_store`) covers every document type. Indexing
  failure can never break an ingestion.
- `comparison.compare_against_text()` answers *"is every value mentioned anywhere in
  these documents?"*, reporting the pages of each hit.
- Triggered by mention phrasing ("mentioned / anywhere / appears in / referenced") — which
  had to be added to **both** routers' comparison triggers, since none of the existing
  comparison keywords fire on that wording — **and automatically** whenever a column
  comparison fails only because the target has no such column.

**Correctness detail that matters:** text mode first reported 7 missing where column mode
said 3. The 4 extra were annotation variants (`XL17461 NAMICA` vs `XL17461`). A near-match
tier now runs the *same* `pair_likely_values` rules against the target's indexed
vocabulary, rendered as a distinct ⚠️ "variant match" tier — never silently counted as a
match. **Both modes now report exactly the same 3 genuinely missing parts.**

### 1.2 Value-shape column detection ⚠️ ADVISORY ONLY — *deliberately not auto-applied*
`backend/process/column_profile.py` scores a column by what its values look like
(code-shaped, distinct, not a 1..N counter).

**Tested as an auto-picker against the six real MRLS/ISPL documents: 1 of 6 correct.**
It ranks `NSN Nos.` above the real part column, and picked `Fig, Item` for the NAMICA
ISPL — because both part numbers and stock numbers are long, distinct, code-shaped
values. Shape alone cannot separate them without the header.

Auto-selecting on that would reintroduce the silent wrong-column comparison this codebase
works hardest to avoid, so **it never picks a column**. It powers a "these columns hold
identifier-shaped values" hint in the *Column Not Found* message (where it *does* rank
`Manufacturer's Part No.` first), leaving the decision with the person who can read the
document. Do not promote it to auto-selection without a stronger signal.

### 1.3 Per-document `ColumnRole` map ❌ NOT DONE
Deferred to Phase 2 — see below.

---

## Phase 2 — Next up ❌ NOT STARTED

| # | Item | Why it matters |
|---|---|---|
| 2.1 | **Persisted `ColumnRole` per document + UI override** | Show "Part No ← *Firms Part No.*" in the document panel with a one-click correction. Fixes a wrong guess **once, permanently**, instead of per query — and it is the natural home for the advisory detector from 1.2, since a human confirms what shape alone cannot decide. Needs a model + migration + a small frontend panel. |
| 2.2 | **Row-level diff on common keys** | Today a part is "present" or "missing". This reports *same part, different quantity / nomenclature / drawing no* — the `modified` class, using deterministic rules only. |
| 2.3 | **Comparison wizard on the Workspace page** | Pick documents (or "all") → review each document's detected columns (editable) → run → tabbed results (missing / likely / confirmed / common / matrix) with "confirm match" buttons (the endpoint already exists) → Excel. Removes the need to phrase a query correctly. |
| 2.4 | **Structured comparison intent parser** | Replace the keyword lists with an explicit parse: files (or "all"), concept, direction, mode (present / count / diff). Deterministic first, local LLM → JSON only when ambiguous. Kills the remaining "use this exact phrasing" failure mode. |

---

## Phase 3 — Trust & coverage ❌ NOT STARTED

| # | Item | Why it matters |
|---|---|---|
| 3.1 | **Regression suite in the repo** | `backend/process/tests.py` is still empty. The harnesses that validate all of the above (`regress.py`, `e2e_compare.py`, `e2e_mentions.py`) live only in a session scratchpad. They should be committed with the NAMICA/SSBS/TGS baselines wired to CI or a single `manage.py test`. |
| 3.2 | **Extraction QA per document** | Surface "12 tables, 2 headerless, part column unresolved" in the document panel *before* a comparison, so bad extraction is caught up front rather than as a wrong "missing" list. |
| 3.3 | **Real OCR** | There is **no OCR engine in the codebase** — Docling is imported behind a try/except and is not in `requirements.txt`, so every `use_ocr` flag is a no-op, and the Landing page's "Smart OCR" is marketing only. Scanned PDFs yield no text, no tables **and no mention index**. Cheapest offline route: RapidOCR on `onnxruntime` (already a dependency), triggered only for pages with no text layer, feeding the existing pipeline. Needs model bundling in the standalone launcher. |
| 3.4 | **Reports page unification** | `reports_engine.py` / `reports_engine_merge.py` still bypass the schema, `ConfirmedMatch`, boilerplate filtering and the mention index. `reports_engine_merge.py` is a near-duplicate (1469 vs 1431 lines) kept alive only by one fallback path in `download_report`. |

---

## Operating it

```bash
cd backend

# One-time after this work (existing documents only; new uploads are automatic)
python manage.py reextract_tables --all      # structured table store
python manage.py build_mention_index         # identifier index for text mode

# Useful flags on both: --doc <id> --thread <id> --source <substring> --dry-run
```

**Asking the questions:**

| Question | Say |
|---|---|
| Column vs column, two files | `compare part no between @a.pdf and @b.pdf` |
| Column vs column, many files | `compare part no in @spares.pdf against @m1.pdf and @m2.pdf` |
| Against a **manual's prose** | `are all the part numbers in @spares.pdf mentioned anywhere in @manual.pdf` |
| Exact headers, no guessing | `compare "Firms Part No." in @a.pdf with "Part No" in @b.pdf` |
| Teach it a permanent alias | `confirm "NAMP-08020000" and "DIC-NAMP-08020000" are the same part in @a.pdf and @b.pdf` |
| Teach it a new column name | edit `field_schema.json`; check `GET /api/field-schema/` |

---

## Regression baselines — *do not change these without a reason*

Measured on `backend/pdfs/` with the part column:

| Pair | Result | Notes |
|---|---|---|
| **NAMICA** MRLS ↔ ISPL | **64 common / 7 likely / 3 missing / 54 extra** (3 boilerplate excluded) | The canonical baseline. Must hold on **both** the file path and the DB path, and via **both** chat routers. |
| NAMICA, text mode | **70 mentioned (4 as variants) / 3 missing** | The same 3: `2608300`, `DD901201-1`, `S067255-LC-001`. Column and text mode agreeing is itself the check. |
| TGS | 237 / 0 / 31 / 2149 | DB path identical to file path. |
| SSBS | file 102/3/9/41 vs DB 102/3/6/41 | Not a DB loss — the *live* extraction is worse here (splits a header into a junk `PER CONTRACT` value, and loses the `Part No. As per Contract` column on p34). The persisted tables are the better extraction. |

After `reextract_tables`, the DB path **matches or beats** the file path everywhere
tested, and is 10–300× faster (NAMICA: 7.9 s → 0.6 s; chat comparisons 8–300 s → 1–2 s).

---

## Known caveats

- **No OCR.** Scanned PDFs produce nothing — no text, no tables, no mention index.
- **The mention index is built at ingest.** Documents ingested earlier answer "not
  mentioned" for everything until `build_mention_index` has run.
- **Single process assumed.** Job dicts, ingestion threads and BM25 live in process
  memory. Do not raise gunicorn workers above 1 without moving that state out.
- **`.xls` is accepted at upload and fails at ingest** (`openpyxl` cannot read it).
- **Conflict detection and table search ignore inherited (ancestor-thread) documents**;
  comparison and RAG include them.
- **Three backend copies must stay in sync**: `backend/`,
  `standalone-launcher/dist/win-unpacked/resources/backend`, and
  `standalone-launcher/runtime/backend`. Use `standalone-launcher/patch-runtime.ps1`
  (robocopy; **exit code 1 means success**).
- **Migrations applied so far:** `0011_confirmedmatch`, `0012_documentpagetext_identifiermention`
  — both additive, both applied to the dev DB and the packaged `%APPDATA%\RAG-OCR\data` DB
  with row counts verified unchanged.

## Where the code lives

| Concern | File |
|---|---|
| Comparison entry point (all callers) | `backend/process/comparison.py` |
| Matching cascade + anchor extractor | `backend/process/table_search_engine.py` |
| Column-name resolution + value rules | `backend/process/field_schema.py` |
| Identifier index (prose + cells) | `backend/process/mentions.py` |
| Value-shape column hints (advisory) | `backend/process/column_profile.py` |
| Ingestion (3-stage PDF + hooks) | `backend/process/pipeline/ingestion.py` |
| Chat router 1 | `backend/process/views.py` — `chat_thread` |
| Chat router 2 | `backend/process/pipeline/query.py` — `query_rag` |
| Back-fill commands | `backend/process/management/commands/` |
