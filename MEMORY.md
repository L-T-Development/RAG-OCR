# RAG-OCR — Comparison Work: Status & Roadmap

**Last updated:** 2026-08-21

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

## Status at a glance

| # | Item | Status |
|---|---|---|
| 0.1 | Data-driven header schema — `field_schema.json` override, `GET /api/field-schema/` | ✅ done |
| 0.2 | One comparison engine behind both chat routers | ✅ done |
| 0.3 | `manage.py reextract_tables` back-fill | ✅ done |
| 0.4 | Docker single worker | ✅ done |
| 1.1 | **Identifier mention index** — compare a column against a manual's prose | ✅ done |
| 1.2 | Value-shape column detection | ⚠️ **advisory only, by design** (§1.2) |
| 2.1 | Per-document pinned column roles + API + chat command | ✅ done |
| 2.2 | Row-level diff — "same part, different details" | ✅ done |
| 2.3 | Comparison wizard UI on the Workspace page | ❌ not started |
| 2.4 | Structured comparison intent parser | ❌ not started |
| 2.5 | Whitespace-tolerant value matching | ✅ done |
| 2.6 | Ingestion performance — 405 s → 165 s on a 582-page file | ✅ done |
| 3.1 | **Regression suite in the repo** | ❌ **← next step** |
| 3.2 | Extraction QA surfaced per document | ❌ not started |
| 3.3 | Real OCR | ❌ not started |
| 3.4 | Reports page unification | ❌ not started |

**What is working today:** every comparison question — column vs column, one file vs
many, column vs a manual's full text, quantity/description discrepancies — through one
engine, with per-document column pinning and human-confirmed aliases, and an Excel report
for each.

**What is missing:** no UI for any of it beyond chat (2.3), phrasing still matters at the
edges (2.4), and — most urgently — **none of it is protected by tests in the repo (3.1)**.

**Recommended next step: 3.1.** Four phases of behaviour are currently guarded only by
throwaway scripts in a temporary session scratchpad. See Phase 3 for exactly what they
cover and must be rebuilt as.

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

### 1.3 Per-document `ColumnRole` map ✅ DONE in Phase 2.1 (see below)

---

## Phase 2 — Corrections & discrepancies 🟡 PARTIALLY COMPLETE (2026-08-21)

**Done:** 2.1 column roles · 2.2 row-level diff · 2.5 whitespace matching · 2.6 ingestion performance.  
**Remaining:** 2.3 wizard UI · 2.4 intent parser.

### 2.1 Per-document column roles ✅ DONE (backend + API + chat command; no UI panel yet)
`backend/process/column_roles.py` + model `ColumnRole` (migration `0013`, additive).

A person who has read the document can pin what a column means, **once**, instead of
quoting the header in every query. Resolution order is now:

```
a header quoted in THIS query   (most specific instruction)
  → a pinned ColumnRole          (a human decided this, for this document)
    → the category schema        (field_schema.json)
      → fail, with value-shape suggestions (§1.2)
```

- **Only user decisions are stored.** Schema-derived resolutions are recomputed every
  time, so improving `field_schema.json` immediately improves every document instead of
  leaving stale cached rows behind.
- `GET /api/documents/<id>/columns/` — what each concept resolves to and *why*
  (`origin: user | schema | none`), the full header list, and value-shape suggestions
  for anything unresolved. `POST` pins, `DELETE` clears.
- **Chat command**, so it is usable without any UI:
  `set the part no column to "Firms Part No." in @ISPL_MMME.pdf` (also `use "X" as the
  part number column in …`, and `clear the part no column in @…`). Checked early and
  narrowly so it cannot swallow a comparison question.
- Unknown concepts and headers that are not in the document are **rejected with the
  real column list**, never silently accepted.

### 2.2 Row-level diff — "same part, different details" ✅ DONE
Values that matched are now cross-checked on their *other* columns, and disagreements
reported as a `modified` bucket in chat and a "Changed Details" Excel sheet.

Getting this to be signal rather than noise was the whole job. First cut flagged
**71 of 71** matched rows. Three rules fixed it, ending at **2**:

- **Separator-insensitive comparison.** PDF extraction yields `Set ofFuelLine- 1setconsist`
  in one document and `Set of Fuel Line - 1 set consist` in the other — same text.
- **Quantities are only compared between columns labelled the same way.** An MRLS
  `Total Qty. / Launcher` (fleet total) and an ISPL `No. Off` (fitted in one assembly)
  both resolve to `qty`, but they count different things — `18 nos.` vs `1` is two
  different questions, not a discrepancy. Same-header pairs (revision vs revision) are
  where a quantity change *is* meaningful.
- **Figure/drawing references are excluded entirely** — `Figure3- 12,Item No.1` vs
  `Figure 3-12 1` is house style, not a change.
- Small character damage in long descriptions is tolerated (`Drai Plug` / `Drain plug`),
  never for identifiers, where one character is a different part.

The 2 that survive on the NAMICA pair are real: `S067327-LC-001` described as
`PKT sight` vs `Night Sight`, and `XL60120` losing its motor specification.

### 2.3 Comparison wizard on the Workspace page ❌ NOT DONE
Pick documents (or "all") → review each document's detected columns (editable, using the
`/columns/` API above) → run → tabbed results with "confirm match" buttons (that endpoint
already exists) → Excel. **All the backend it needs is now in place**; this is frontend
work in `frontend/src/pages/Workspace.jsx` plus a column-mapping panel in the document
sidebar.

### 2.4 Structured comparison intent parser ❌ NOT DONE
Replace the keyword lists with an explicit parse: files (or "all"), concept, direction,
mode (present / count / diff). Deterministic first, local LLM → JSON only when ambiguous.
Would kill the remaining "use this exact phrasing" failure mode.

### 2.5 Whitespace-tolerant value matching ✅ DONE — *from a user report*
A catalogue number that wraps inside its cell comes back as `442 071 820394` from one
document and `442 071 820 394` from the other: `normalize_value` strips the newline
without inserting a space, so the two strings differ by one space and the set difference
called it **missing** — the most misleading thing this report can say.

Pass 0 of `field_schema.pair_likely_values` now pairs values whose whitespace-free forms
are identical, reported as *"differs only by spacing (wrapped in the cell)"*. Removing
whitespace cannot merge two genuinely different identifiers — their character sequences
would have to be identical — so it is the most certain rule here and runs first, ahead of
the leading-zero and annotation rules. Every caller benefits at once: both chat routers,
the second-chance pass, and text mode's near-match tier.

Measured on the SSBS pair: **missing 6 → 0**, and three further values (`MFIR G34BSP`,
`WELDABLENIPPLE`, `1CEB 120-P-35S 3 1`) came out of the "extra" bucket as well. NAMICA
unchanged at 64/7/3/54.

*This is the class of bug worth hunting: the comparison is only as good as the string
normalisation, and PDF extraction damages strings in a handful of repeatable ways
(dropped spaces on wrap, leading zeros, annotation suffixes, single-character OCR-ish
damage). Each is now an explicit, named rule.*

### 2.6 Ingestion performance ✅ DONE — *measured, not guessed*
A 582-page spares list took **405 s** to ingest tables; it now takes **165 s** — the same
290 tables, byte-for-byte. Profiling on real pages (30 sampled evenly across the document,
not the front matter, which is sparse and understates the cost ~7x) split the original:

| Stage | Before | After |
|---|---:|---:|
| pdfplumber `extract_tables()` (ruled tables) | ~290 s | ~290 s (kept) |
| Anchor extractor's word boxes | ~47 s standalone | **~0.1 s** |
| Database writes | **~150 s** | **~4 s** |
| **Measured end-to-end** | **405 s** | **165 s** (2.4x) |

**Database writes were a third of the time.** `store_table` did one `create()` per row
and per *cell*, each its own SQLite transaction — 4.89 ms per cell. It is now a single
`transaction.atomic()` with two `bulk_create` calls: **0.14 ms per cell, 35x faster**.
Verified byte-for-byte: re-extracting a document produced 60 identical tables, every
row/cell content hash matching (`verify_store.py`).

**Word boxes now come from PyMuPDF** (`words_from_fitz_page`). The anchor extractor only
reads x0/x1/top/bottom/text, and both libraries report those in the same coordinate
space — verified identical output on **449 pages across 13 PDFs, 0 differences**, at
202x the speed in isolation. (In the pipeline the saving is smaller, because
`extract_tables()` has already parsed the page's characters and the word extraction was
reusing that cache — but the anchor pass is now independent of pdfplumber entirely.)

**pdfplumber was NOT replaced for ruled tables, deliberately.** PyMuPDF's `find_tables()`
looked 1.6x faster with 100% identical content on one document — but tested across all
13 it *loses data* on real files (SSBS MRLS: 6 tables instead of 18, 89% of cells;
Final_SOP: 77%) and is *slower* on most (S1000D 3.3x slower). A single-document benchmark
would have shipped a silent extraction regression. **Benchmark across the whole corpus
before swapping an extractor.**

Still on the table if ingestion needs to be faster: parallelise pages across processes
(the remaining cost is ~97% pdfplumber's ruled-table detection, which is CPU-bound and
embarrassingly parallel), or skip the ruled pass on pages with no ruling lines — though
the cheap PyMuPDF `get_drawings()` probe for that costs 48 ms/page, so it only pays off
on documents that are mostly prose.

---

## Phase 3 — Trust & coverage ❌ NOT STARTED

### 3.1 is the next thing to build — here is what it must cover

`backend/process/tests.py` is still 3 lines. Everything in Phases 0–2 is verified only by
scripts in a **temporary** session scratchpad, which will not survive. They must be
rewritten as Django tests with **self-contained fixtures** — not real PDFs, because the
source files for the original baselines have already been deleted from `backend/pdfs/`
once during development (see *Environment drift* below).

| Harness (scratchpad) | What it proves | Rebuild as |
|---|---|---|
| `regress.py` | NAMICA / SSBS / TGS bucket counts, file path vs DB path | `RealCorpusTests`, skipped when the PDFs are absent |
| `e2e_compare.py` | 8 chat-endpoint cases: both routers, 2-file, N-file, column-not-found, unresolved filename, `/api/field-schema/` | `ChatComparisonTests` with synthetic `ExtractedTable` fixtures |
| `e2e_mentions.py` | 6 cases: text mode, multi-target, near-match tier, column mode unaffected | `TextModeTests` |
| `e2e_phase2.py` | 10 cases: column roles, row-level diff, API + chat command | `ColumnRoleTests`, `RowDiffTests` |
| `verify_store.py` | `store_table` bulk rewrite is byte-identical | `StorageTests` (build a table, store, read back, compare hashes) |
| `verify_words.py` | PyMuPDF vs pdfplumber word boxes give identical anchor tables | `AnchorExtractorTests` on one small fixture PDF |
| `audit_missing.py` | Every "missing" value really is absent from the target | keep as a diagnostic script, committed under `backend/tools/` |
| `compare_gridders.py` | Corpus-wide extractor comparison | keep as a diagnostic script — **run it before any extractor swap** |

Pure-function tests need no fixtures at all and should come first: `resolve_header`
across categories, all four `pair_likely_values` passes, `normalize_value`,
`is_boilerplate_value`, `mentions.extract_identifiers`, `column_profile.profile_column`.

### The rest of Phase 3

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
| Fix a column for **one document** | `set the part no column to "Firms Part No." in @a.pdf` (undo: `clear the part no column in @a.pdf`) |
| Teach it a column name **everywhere** | edit `field_schema.json`; check `GET /api/field-schema/` |
| Inspect one document's columns | `GET /api/documents/<id>/columns/` |

---

## Regression baselines — *do not change these without a reason*

Measured on `backend/pdfs/` with the part column. **These are historical:** the NAMICA
and TGS source PDFs were deleted from `backend/pdfs/` during development, so those pairs
can now only be re-checked through the DB path (their `ExtractedTable` rows survive in a
scratch copy) — which is exactly why 3.1 must build self-contained fixtures.

| Pair | Result | Notes |
|---|---|---|
| **NAMICA** MRLS ↔ ISPL | **64 common / 7 likely / 3 missing / 54 extra** (3 boilerplate excluded) | The canonical baseline. Must hold on **both** the file path and the DB path, and via **both** chat routers. |
| NAMICA, row-level diff | **2 modified** | `S067327-LC-001` and `XL60120`. If this jumps back into the dozens, the noise filters in `_same_enough` / `_SAME_HEADER_ONLY` have regressed. |
| **SSBS** MRLS ↔ ISPL | **102 common / 9 likely / 0 missing / 35 extra** | Was 102/3/6/41 before the spacing pass — all six "missing" were cell-wrap artefacts (`442 071 820394` vs `442 071 820 394`). If `missing` returns to 6, Pass 0 of `pair_likely_values` has regressed. |
| TGS, audited | 237 / 0 / 31 / 2149 | 30 of the 31 "missing" are genuinely absent from the whole document; `TGS-01-12-03-00` appears in the ISPL's **prose** on p27 but not in its part column — column mode is right to exclude it, and text mode is how you find it. |
| NAMICA, text mode | **70 mentioned (4 as variants) / 3 missing** | The same 3: `2608300`, `DD901201-1`, `S067255-LC-001`. Column and text mode agreeing is itself the check. |

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
- **Migrations applied so far:** `0011_confirmedmatch`, `0012_documentpagetext_identifiermention`,
  `0013_columnrole` — all additive, all applied to the dev DB and the packaged
  `%APPDATA%\RAG-OCR\data` DB with row counts verified unchanged.
- **Environment drift is real — check before trusting a fixture.** Mid-development the
  dev database went from 8 documents to 2 (the NAMICA/TGS documents were deleted in the
  app and a new 582-page SSBS ISPL, `DT0081_U0500_SSBS_10M_R3.pdf`, was uploaded), and
  deleting a document also deletes its PDF. Any test that reads `backend/pdfs/` or
  `backend/db.sqlite3` can therefore vanish without warning. Verify what is actually
  present before assuming a baseline can be reproduced.
- **Quantity columns are not comparable across document types** — see 2.2. If a future
  change makes `qty` compare across differently-named columns again, every matched row
  will be flagged.

## Where the code lives

| Concern | File |
|---|---|
| Comparison entry point (all callers) | `backend/process/comparison.py` |
| Matching cascade + anchor extractor | `backend/process/table_search_engine.py` |
| Column-name resolution + value rules | `backend/process/field_schema.py` |
| Identifier index (prose + cells) | `backend/process/mentions.py` |
| Value-shape column hints (advisory) | `backend/process/column_profile.py` |
| Per-document pinned columns | `backend/process/column_roles.py` |
| Ingestion (3-stage PDF + hooks) | `backend/process/pipeline/ingestion.py` |
| Chat router 1 | `backend/process/views.py` — `chat_thread` |
| Chat router 2 | `backend/process/pipeline/query.py` — `query_rag` |
| Back-fill commands | `backend/process/management/commands/` |
