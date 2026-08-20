# RAG-OCR

A document RAG (Retrieval-Augmented Generation) pipeline for technical manuals: ingest PDFs / Excel / Word / images, embed via Ollama, retrieve via hybrid vector + BM25, answer with a local LLM. Also supports multi-PDF column comparison and per-row OR-matching (e.g. "is each spare from `spares.pdf` mentioned in `manual.pdf`?").

## Deployment options

| Mode | Bundle | When to use |
|---|---|---|
| **Docker** | [`docker-offline-package/ragocr-docker-*.tar.gz`](docker-offline-package/) | Server / shared machine where Docker + Compose are available |
| **Standalone .exe** | [`standalone-launcher/dist/RAG-OCR-Standalone.tar.gz`](standalone-launcher/) | Single Windows desktop without Docker. Bundles Python + JRE + backend + frontend |

Both require **Ollama** running on the host (`localhost:11434`) with at least one embedding model and one chat model pulled. See [DOCKER_DEPLOYMENT.md](DOCKER_DEPLOYMENT.md) for Docker specifics.

> **Documentation map:** [HOW_IT_WORKS.md](HOW_IT_WORKS.md) explains the mechanism —
> ingestion, retrieval, and the comparison engines. [MEMORY.md](MEMORY.md) is the
> status record for the document-comparison work: which phases are done, what is
> planned, the regression baselines, and the known caveats.

## Requirements

- **Python 3.12+** (for local dev) — dependencies in [`backend/requirements.txt`](backend/requirements.txt)
- **Node.js 18+** — frontend dev server
- **Java 11+** — required by OpenDataLoader for PDF table extraction (bundled in the standalone build's `runtime/jre/`)
- **Ollama** — https://ollama.com/download
  - `ollama pull nomic-embed-text` (embedding model)
  - `ollama pull llama3.1:8b` (or any reasoning model — selectable in Settings)

## Quick start — local development

```bash
# 1. Backend
python -m venv .venv
.\.venv\Scripts\Activate.ps1   # PowerShell
# or: source .venv/bin/activate # Linux / Mac
pip install -r backend/requirements.txt
cd backend
python manage.py migrate
python manage.py runserver 0.0.0.0:8000
```

```bash
# 2. Frontend (separate terminal)
cd frontend
npm install
npm run dev          # → http://localhost:5173 (proxies /api to :8000)
```

## Project structure

```
.
├── README.md
├── DOCKER_DEPLOYMENT.md
├── docker-compose.yml
├── export-docker.{ps1,sh}        # build the Docker offline bundle
├── backend/
│   ├── requirements.txt          # ← canonical Python dependencies
│   ├── manage.py
│   ├── Dockerfile
│   ├── ragocr/                   # Django project settings + URLs
│   └── process/                  # app code
│       ├── views.py              # REST endpoints
│       ├── models.py             # Thread, Document, ChatMessage, ExtractedTable, AppConfig
│       ├── pipeline/             # ingestion / embedding / retrieval / generation
│       │   ├── config.py         # OLLAMA_API, defaults, batch sizes
│       │   ├── ingestion.py      # ODL + PyMuPDF + Excel + Word + image extraction
│       │   ├── embedding.py      # Ollama embedding provider
│       │   ├── tables.py         # table store + compare_columns(_multi)
│       │   ├── query.py          # query_rag, _gen_compare, _gen_lookup_multi_col
│       │   └── summary.py        # thread/document summaries
│       ├── reports_engine.py     # single-PDF column comparator (Reports page)
│       ├── reports_engine_merge.py  # multi-PDF column comparator
│       ├── document_compare.py   # line-diff comparator (Compare page)
│       └── eval_utils.py         # answer relevance / faithfulness scoring
├── frontend/                     # React + Vite + Tailwind
│   ├── package.json
│   ├── vite.config.js
│   └── src/
│       ├── pages/                # Landing, Workspace, Reports, Compare, Settings
│       ├── components/           # workspace components (Sidebar, ChatArea, DocumentPanel)
│       └── services/api.js       # backend HTTP wrapper
├── standalone-launcher/          # Electron desktop app (no Docker)
│   ├── main.js                   # spawns python backend, opens BrowserWindow
│   ├── provision-runtime.ps1     # downloads Python embed + JRE, installs deps into runtime/
│   ├── patch-runtime.ps1         # quick-patch an installed launcher with the latest backend code
│   └── package.json              # electron + electron-builder
├── electron-launcher/            # Electron Docker-stack manager (alternative deployment)
└── docker-offline-package/       # build output: Docker images + compose + install scripts
```

## Where to look for things

| What you want | Where it lives |
|---|---|
| Python dependencies | `backend/requirements.txt` |
| Django settings + URL routing | `backend/ragocr/settings.py`, `backend/ragocr/urls.py` |
| API endpoints | `backend/process/views.py` (mounted at `/api/`) |
| Ollama URL / batch sizes / default model | `backend/process/pipeline/config.py` |
| Vector store path | `RAGOCR_DATA_DIR/local_chroma_db` (standalone) or `backend/local_chroma_db` (dev) |
| User data in standalone build | `%APPDATA%\RAG-OCR\data\` (sqlite, ChromaDB, uploaded PDFs) |
| Standalone backend logs | `%APPDATA%\RAG-OCR\data\logs\ragocr.log` |
| Frontend → backend proxy | `frontend/vite.config.js` (`/api` → `http://127.0.0.1:8000`) |

## Configuration

Environment variables (read by `backend/ragocr/settings.py` and `backend/process/pipeline/config.py`):

| Var | Default | Purpose |
|---|---|---|
| `DEBUG` | `False` | Django debug mode |
| `ALLOWED_HOSTS` | `localhost,127.0.0.1` | Comma-separated hosts |
| `CORS_ALLOWED_ORIGINS` | `http://localhost:3000,…` | Comma-separated origins |
| `OLLAMA_API_BASE` | `http://localhost:11434` | Ollama HTTP base URL |
| `RAGOCR_DATA_DIR` | unset | When set, sqlite + media + Chroma are relocated here (used by Electron) |
| `RAGOCR_FRONTEND_DIR` | unset | Override for the static SPA path |

## Common operations

```bash
# Build the Docker offline bundle (Windows)
.\export-docker.ps1

# Build the Docker offline bundle (Linux / Mac)
./export-docker.sh

# Build the standalone Electron .exe
cd standalone-launcher
.\provision-runtime.ps1        # one-time: download Python embed + JRE, install deps
npm install                    # one-time
npm run dist:win               # produces dist/win-unpacked/RAG-OCR.exe (+ tar.gz archive)

# Quick-patch an already-installed standalone launcher with current backend code
cd standalone-launcher
.\patch-runtime.ps1 -Target "<path-to-extracted-launcher-folder>"

# Back-fill / refresh the structured table store used by document comparison
# (documents uploaded before the table pass existed, or after an extractor fix).
# PDF-only, no re-embedding, Ollama not needed.
cd backend
python manage.py reextract_tables            # PDFs that have no tables yet
python manage.py reextract_tables --all      # refresh every PDF
python manage.py reextract_tables --source ISPL_MMME --dry-run

# Build the identifier index that lets a spares list be checked against a MANUAL
# ("are all these part numbers mentioned anywhere in it?"). New uploads are
# indexed automatically; run this once for documents uploaded earlier.
python manage.py build_mention_index         # documents not indexed yet
python manage.py build_mention_index --all   # rebuild everything
```

### Teaching the comparison engine a new column name

"Compare part numbers" has to find the right column in each document, and every
document family labels it differently (`Manufacturer's Part No.`, `DS Cat No.`,
`Firms Part No.`, `P/N`, …). The mapping lives in
`backend/process/field_schema.py` and can be extended **without a rebuild** by
dropping a `field_schema.json` next to the data (packaged app:
`%APPDATA%\RAG-OCR\data\field_schema.json`; dev: `backend/field_schema.json`) —
see `backend/field_schema.example.json`. The file is re-read whenever it changes;
`GET /api/field-schema/` shows the schema currently in force and any load error.

## Troubleshooting

- **Backend can't reach Ollama** → ensure Ollama is running (`ollama serve` or via the desktop app). The backend honors `OLLAMA_API_BASE`.
- **OpenDataLoader (ODL) fails / falls back to PyMuPDF** → check Java is on PATH; the standalone build ships `runtime/jre/`. ODL failures on specific pages are logged and the affected pages are routed through PyMuPDF automatically.
- **Embedding HTTP 400 ("input length exceeds context")** → already handled: long chunks are truncated to 8000 chars before being sent to `nomic-embed-text` (see `backend/process/pipeline/embedding.py`).
- **Standalone .exe shows "Internal server error"** → backend stack traces go to `%APPDATA%\RAG-OCR\data\logs\ragocr.log`. Or run `RAG-OCR.exe` from a CMD window to see `[backend]`-prefixed live output.
- **First-time DB error on launch** (`no such table: process_appconfig`) → harmless; the launcher runs migrations before the server, but the auto-init runs in parallel and may race once. Disappears after the first launch.

## License

Internal — see project owner.
