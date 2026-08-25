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
| 2.3 | **Comparison wizard** — pick documents, review the columns, run, export | ✅ done |
| 2.4 | **Structured intent parser** — one parse replaces both routers' keyword lists | ✅ done |
| 2.5 | Whitespace-tolerant value matching | ✅ done |
| 2.6 | Ingestion performance — 405 s → 165 s on a 582-page file | ✅ done |
| 3.1 | **Regression suite in the repo** — 107 tests, `manage.py test process` | ✅ done |
| 3.2 | **Extraction QA** — warns on the comparison itself when a document could not be read | ✅ done |
| 3.3 | Real OCR | ❌ not started |
| 3.4 | **Reports page** — same value rules as chat; duplicate engine deleted | ✅ done |
| 4.1 | **Portability** — export/import your corrections, back up the install | ✅ done |

**What is working today:** every comparison question — column vs column, one file vs
many, column vs a manual's full text, quantity/description discrepancies — through one
engine, with per-document column pinning and human-confirmed aliases, and an Excel report
for each.

**What is missing:** no UI for any of it beyond chat (2.3), phrasing still matters at the
edges (2.4), scanned documents produce nothing at all (3.3), and the Reports page still
runs its own weaker comparison (3.4).

**Nothing substantive is outstanding.** 3.3 (OCR) is the only unbuilt roadmap item, and
the corpus measurement demoted it to 0.4% of pages — re-check on the deployed machine with
`manage.py extraction_report --problems` before spending anything on it.

Deployment is **single-user Electron**, not Docker: the packaged app under
`standalone-launcher/` is the product, `%APPDATA%\RAG-OCR\data` is the real data home,
and the Docker single-worker fix (§0.4), while correct, is moot in practice.

OCR was the earlier recommendation and the measurement overturned it: **38 of 10,399
pages (0.4%) have no text layer**, and every MRLS/ISPL spares list has a complete one.
The only real scanned content is 11 pages of one SOP. What is missing is not OCR but
*knowing* when a document is unreadable — hence 3.2, which is cheap and tells you whether
3.3 is ever worth doing. Re-run the check on the deployed machine before deciding, since
this measures only the corpus on the dev box.

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

## Phase 2 — Corrections & discrepancies ✅ COMPLETE (2026-08-21)

**All done:** 2.1 column roles · 2.2 row-level diff · 2.3 wizard UI · 2.4 intent parser · 2.5 whitespace matching · 2.6 ingestion performance.

### 2.1 Per-document column roles ✅ DONE (backend + API + chat command; UI in §2.3)
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

### 2.3 Comparison wizard ✅ DONE (2026-08-21)
`frontend/src/components/workspace/ComparePanel.jsx` (+ `.css`), opened by a **Compare
documents** button that appears in the document panel once a thread holds two files.
Backed by a new `POST /api/comparison/run/`.

Three steps, in the order the decisions actually happen:

1. **Pick documents** — checkboxes over the thread's documents (inherited ones included);
   the first ticked is the source.
2. **What to compare** — a concept (part number / drawing / NSN / description / quantity)
   and a mode (*the same column in each document* or *anywhere in the text*, for manuals).
   Then the part that matters: **the real column each document will be read from**, shown
   with a badge saying whether that was the schema's choice or a human's, and editable
   from a dropdown of that document's actual headers. Changing it writes a `ColumnRole`
   (§2.1), so the correction sticks for that document.
3. **Result** — count tiles that double as tabs (missing · written differently · details
   differ · matched · only in target), the extraction warnings from §3.2, the full written
   report in a disclosure, and the Excel download.

`POST /api/comparison/run/` exists because the chat router has to *guess* the intent from
a sentence, and a UI already knows it. Same engine, same rules, same Excel — no phrasing.
It returns flattened counts for whichever shape came back (pairwise, N-way matrix, or
mention check), the resolved column label, extraction warnings, and the report id.
Eight tests cover it, including that a document outside the thread is refused.

**Two bugs fell out of building it:**

- The files endpoint returns `name`, with no `status` — the panel had been written
  against `filename`, so it would have listed rows with blank names. The endpoint now
  returns `filename` and `status` as well (`name` kept for the existing panel), and the
  component accepts either.
- **The preview could disagree with the comparison.** The column preview reads the
  *stored* tables; when those cannot supply the column, the engine falls back to re-reading
  the PDF, which can extract different headers — on the real SSBS pair the preview said
  `PART. NO` while the comparison actually used `FIRMS PART NO.`. The response now carries
  `engine_path` (`db` / `file`) and the panel says, next to the column it actually read,
  when the PDF was re-read and why the preview may differ. Showing a column that is not the
  one used is precisely the failure this panel exists to prevent.

Verified end to end against the real dev database: files list → per-document columns →
comparison (44 matched / 5 near / 3 details differ / 61 missing / 699 extra) → a 73 KB
Excel that downloads.

### 2.4 Structured intent parser ✅ DONE (2026-08-21)
`backend/process/intent.py` — one `parse(query, available_files, doc_count)` returning
what the question asks for: which documents (or *all* of them), which concept, quoted
columns if the user named them, the mode (columns vs mentions), the kind of answer, and
**the evidence it used**.

It replaces four overlapping keyword blocks in `views.chat_thread` (a 17-word comparison
list, a "strict assessment" rule, a mention-phrase rule, an assessment-terms rule), the
whole parsing half of `_extract_comparison_info` (**96 lines** of a second comparison-type
list, its own column keywords and its own quoted-name regex), and Router 2's
`_is_compare_query` / `_COL_KEYWORDS` / `_resolve_column` / `_QUOTED_COL_RE`. Both routers
now reach the same conclusion for the same sentence, by construction.

Two properties worth keeping:

- **The concept vocabulary is the schema's.** `_find_concept` scans
  `field_schema.CANONICAL_FIELDS`, so teaching `field_schema.json` a new word for "part"
  teaches the router too — there is no second list to update. Matching is whole-word, so
  "partial" is not "part".
- **Routing is explainable.** Every decision carries its evidence and is logged:
  `[ROUTING] comparison=True concept='part no' mode=columns type=all files=[…]
  because[2 file(s) named, concept=part_no, says 'compare']`.

An LLM pass for ambiguous questions was considered and **left out**: it would make routing
non-reproducible and slow, and the wizard (§2.3) now covers the case where words fail by
letting someone point at the documents instead.

Verified by a corpus of 12 phrasings that must route to a comparison (including
`cross-check the nsn against all the documents` and `reconcile part numbers across every
document`, neither of which worked before) and 7 ordinary questions that must **not** —
plus the same phrasings run against the real database through the live chat endpoint.

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

## Phase 4 — Durability (beyond the original roadmap)

### 4.1 Portability of the corrections ✅ DONE (2026-08-21)
`backend/process/portability.py`, `manage.py decisions`, three endpoints, and a
**Your corrections** panel in Settings.

Everything here can be rebuilt by re-uploading a document — tables, embeddings, the
mention index — *except* two things, because they are judgments someone made while
reading: `ConfirmedMatch` ("these two part numbers are the same item") and `ColumnRole`
("in THIS ISPL the part column is Firms Part No."), plus the `field_schema.json` override.
They accumulate, they get more valuable with use, and they lived in exactly one SQLite
file on one desktop with no export and no backup.

**Export is keyed by filename, never by document id.** `ColumnRole.doc_id` is a UUID
minted at upload, so the same PDF has a different id on every install; exporting it would
produce a file that silently applies to nothing. The import resolves the filename against
whatever that machine calls the same document, and applies to every copy of it.

- `GET /api/decisions/export/` — a small, readable JSON download.
- `POST /api/decisions/import/` — **additive**; an existing decision is kept unless
  `overwrite`. Send `dry_run` first: the response describes exactly what a real run would
  change, *including documents this machine does not have yet*, which are reported rather
  than silently dropped.
- `POST /api/decisions/backup/` — zips the install. Uses an **allowlist** (db, schema
  override, uploads, vectors), because in development the data directory is the backend
  source tree and "zip everything except…" would archive the source. `--no-media
  --no-vectors` gives a small backup that still holds everything irreplaceable.
- `manage.py decisions export|import|backup` for the same, scriptable.

Verified across two **real** installs: a decision made on the dev database exported,
dry-run against the packaged app's own database (different ids, no documents) correctly
reported "1 match would be added, 0 roles — that document is not here", then imported for
real. Both databases left exactly as found.

---

## Phase 3 — Trust & coverage 🟡 PARTIALLY COMPLETE (2026-08-21)

**Done:** 3.1 regression suite · 3.2 extraction QA · 3.4 Reports page.  
**Remaining:** 3.3 OCR (measured low priority).

### 3.1 Regression suite ✅ DONE (2026-08-21)
`backend/process/tests.py` — **55 tests, `python manage.py test process`, under a second.**

```
python manage.py test process                          # fast, every commit
python manage.py test process.tests.MatchingRuleTests   # one class
RAGOCR_CORPUS_TESTS=1 python manage.py test process     # + the real PDFs (~3 min)
```

**Fixtures are synthetic on purpose.** One MRLS and one ISPL are built in the test
database, through the real `store_table` path, carrying one row for every rule the engine
implements: an annotation suffix (`XL17461 NAMICA`), a leading-zero variant, a
wrapped-cell spacing artefact (`442 071 820394`), an exact match, a genuinely absent
part, boilerplate on both sides (`Standard Item` / `STANDAR ITEM`), and a part whose
description changed. One comparison then asserts the whole cascade at once:
**2 exact · 3 near-match · 1 missing · 2 excluded · 1 changed-detail**.

They deliberately do **not** read `backend/pdfs/` or `backend/db.sqlite3` — during
development the source PDFs for the original baselines were deleted by ordinary app use,
which silently disabled the file-based regressions. Tests that can evaporate are not tests.

Covered: header resolution across categories · all four `pair_likely_values` passes and
their limits · boilerplate vs empty · identifier extraction from prose · value-shape
advisories · `store_table` round-trip and idempotency · the full comparison cascade ·
row-level diff (including that `qty` is *not* compared across differently-named columns)
· ConfirmedMatch · N-way matrix · text mode with page numbers and the variant tier ·
column-role pin/clear/reject · `field_schema.json` override, hot-reload and bad-file
tolerance · `/api/field-schema/` · `/api/documents/<id>/columns/` · both chat routers.

`RealCorpusTests` pins the hand-verified baselines (NAMICA 64/7/3/54, SSBS R0 102/9/0/35)
plus a snapshot of the SSBS P3 ↔ R3 pair that is still on disk (44/5/64/699 — a *different
revision*, so a large missing count is expected; it resolves the ISPL column to
`FIRMS PART NO.`, the header Phase 0 was built for). Snapshot baselines are labelled
`verified=False` in the table: a change there means "look at this", not "bug".

**A bug fell out of writing them.** Asking `compare part no between @A.pdf and @NOPE.pdf`
did not complain about the missing file — Router 1 fell through to its "just use the first
two documents in the thread" rule and confidently compared a pair the user never named.
It now names what it could not find and lists what is available. (Router 2 already did.)

Still worth committing as diagnostics rather than tests: `audit_missing.py` (is every
reported-missing value really absent?) and `compare_gridders.py` (**run before any
extractor swap** — see 2.6).

### 3.2 Extraction QA ✅ DONE (2026-08-21)
`backend/process/extraction_qa.py` + `Document.extraction_stats` (migration `0014`).

Every wrong answer this system can give traces back to something it silently failed to
read. A scanned page has no text, so every part printed on it is reported as **missing**
from a document that plainly contains it — and the report looks just as confident as a
correct one. Neither that nor a table that lost its header row raises an error.

- **Ingestion records what it could not read** (~1 ms/page, PyMuPDF): total pages, pages
  with no text layer, and — the useful distinction — how many of those carry an image
  (a scan, where OCR would help) versus none (a blank page, where nothing is recoverable).
- **The comparison report says so itself.** All three renderers (pairwise, N-way, text
  mode) are prefixed with a "⚠️ Before trusting this comparison" banner listing anything
  unreadable in either document. This is the point of the whole item: the warning appears
  on the artefact that would otherwise mislead, not in a log nobody reads.
- Warnings also cover **0 tables extracted**, **N of M tables lost their header row**, and
  **no part-number column resolves** (with the exact chat command to pin one).
- `GET /api/documents/<id>/extraction/` — coverage, table health, which concept resolves
  to which real column, and the warnings.
- `manage.py extraction_report [--problems] [--source X] [--no-rescan]` — the same per
  document, and back-fills the stats for documents ingested before this existed.

Measured on the current corpus: **10,399 pages, 38 with no text layer (0.4%)**, and every
MRLS/ISPL spares list has a complete one. That number is why 3.3 (OCR) was demoted — and
this command is how you re-check it on any machine.

### 3.4 Reports page ✅ DONE (2026-08-21)

**The Excel download was broken.** `download_report` did a *local* import of
`get_report_job_status` / `get_report_excel_bytes` from `reports_engine_merge` — a
near-duplicate module with its own, permanently empty, job dict — which shadowed the
module-level imports from `reports_engine`, where the jobs are actually registered. Every
Reports-page download returned **404 "Report not found"**. Fixed, covered by a test, and
`reports_engine_merge.py` (1,470 lines) is deleted.

**The page also disagreed with the chat about the same documents.** It compares *ad-hoc
uploaded files*, which have no Document rows, no stored tables and no mention index, so it
cannot use `process/comparison.py`. What it can share — and now does — is the part that
decides whether two strings are the same item:

- `is_boilerplate_value` excludes placeholder text ("Standard Item", "N/A", footnote
  markers) up front, so it no longer counts as a missing part;
- values still unmatched get the same second look via `pair_likely_values` against the
  target's identifier vocabulary (extracted from the PDF text with the mention index's
  own tokeniser), reported as a **"Written Differently"** tier — its own tab, its own
  Excel sheet, never silently counted as found.

Measured on a fixture carrying every awkward case, this run reported **4 not found**
before and **1** after — matching what the chat says about the same documents:

| | Before | After |
|---|---|---|
| `XL17461 NAMICA` (annotation) | not found | review tier |
| `01534601` (leading zero) | not found | review tier |
| `442 071 820394` (wrapped cell) | found | found — the page search already compares a space-free form |
| `Standard Item` (placeholder) | not found | excluded |
| `DD901201-1` (genuinely absent) | not found | not found |

Excel now carries `Review - Written Differently` and `Excluded Placeholders` sheets.

### The rest of Phase 3

| # | Item | Why it matters |
|---|---|---|
| 3.2 | **Extraction QA per document** | Surface "12 tables, 2 headerless, part column unresolved" in the document panel *before* a comparison, so bad extraction is caught up front rather than as a wrong "missing" list. |
| 3.3 | **Real OCR** — *measured as low priority, see below* | There is **no OCR engine in the codebase**: Docling sits behind a try/except and is not in `requirements.txt`, so every `use_ocr` flag is a no-op and the Landing page's "Smart OCR" is marketing. But **only 0.4% of the corpus needs it** (38 of 10,399 pages, and every MRLS/ISPL spares list has a complete text layer). Route when needed: RapidOCR on `onnxruntime` (already a dependency), gated to pages with no text layer, feeding word boxes into the existing anchor extractor. |


---

## Operating it

```bash
cd backend

# One-time after this work (existing documents only; new uploads are automatic)
python manage.py reextract_tables --all      # structured table store
python manage.py build_mention_index         # identifier index for text mode

# Useful flags on both: --doc <id> --thread <id> --source <substring> --dry-run

# What could NOT be read — run this before trusting a "missing parts" list
python manage.py extraction_report --problems

# Carry your corrections to another machine, or back this install up
python manage.py decisions export --out my-corrections.json
python manage.py decisions import --in my-corrections.json --dry-run
python manage.py decisions backup --no-vectors --no-media
```

**Before committing a change to extraction, matching or storage:**

```bash
python manage.py test process                       # 107 tests, < 2 s
RAGOCR_CORPUS_TESTS=1 python manage.py test process # + real PDFs, ~3 min
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

- **No OCR.** Scanned PDFs produce nothing — no text, no tables, no mention index. Since 3.2 this is at least *reported*: ingestion counts textless pages and the comparison banner names them. Only 0.4% of the current corpus is affected.
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
| What could not be read | `backend/process/extraction_qa.py` |
| Export / import / backup | `backend/process/portability.py` |
| Ingestion (3-stage PDF + hooks) | `backend/process/pipeline/ingestion.py` |
| Comparison wizard (UI) | `frontend/src/components/workspace/ComparePanel.jsx` |
| Reports page (ad-hoc uploads) | `backend/process/reports_engine.py` |
| Comparison endpoint (no chat) | `backend/process/views.py` — `run_comparison_view` |
| What a question asks for | `backend/process/intent.py` |
| Chat router 1 | `backend/process/views.py` — `chat_thread` |
| Chat router 2 | `backend/process/pipeline/query.py` — `query_rag` |
| Back-fill commands | `backend/process/management/commands/` |
