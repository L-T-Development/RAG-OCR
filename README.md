
# RAG-OCR

RAG-OCR is a compact, production-minded reference for a Retrieval-Augmented Generation (RAG) pipeline built around OCR'd documents. It supports ingestion, embedding, retrieval, document comparison, and LLM-backed generation.

## Key Capabilities

- Ingest and process PDFs and other document types.
- Store and query embeddings in a local ChromaDB (`backend/local_chroma_db`).
- Use a local sentence-transformer for embeddings (`backend/models/all-MiniLM-L6-v2`).
- LLM generation via a local API (e.g., Ollama) or remote LLMs.
- Document comparison and difference summarization.

## Requirements

- Python 3.10+
- Node.js 18+ (frontend)
- See `requirements.txt` for full Python dependencies.

Use a virtual environment (venv, virtualenv, or conda).


## Local LLM (Ollama) — recommended setup

This project is tested with local LLM services such as Ollama. Below are practical steps and recommended environment variables to make the integration explicit and configurable.

1) Install Ollama

Download and install from the official site:

https://ollama.com/download

After installation verify it is available on your PATH:

```bash
ollama --version
```

2) Pull a model (one-time)

Example:

```bash
ollama pull llama3.2:1b
```

3) Run/test the model

Quick smoke test:

```bash
ollama run llama3.2:1b
```


## Quick Start (Development)

Clone and install:

```bash
git clone https://github.com/L-T-Development/RAG-OCR.git
cd RAG-OCR
```

Backend (Python):

```bash
python -m venv .venv
# macOS / Linux
source .venv/bin/activate
# Windows PowerShell
.\.venv\Scripts\Activate.ps1
# Windows CMD
.venv\Scripts\activate.bat
pip install -r requirements.txt
cd backend
python manage.py migrate
python manage.py runserver 0.0.0.0:8000
```

Frontend (separate terminal):

```bash
cd frontend
npm install
npm run dev
```

The React dev server proxies API requests to `http://localhost:8000` by default.

## Frontend notes

- Location: `frontend/` (React + Vite).
- If you see CORS errors, install and enable `django-cors-headers` in `backend/ragocr/settings.py`.

```bash
pip install django-cors-headers
```

Adjust proxy settings in `frontend/vite.config.js` if needed.

## Project Structure

Top-level repository tree (concise):

```
.
├── Jenkinsfile
├── pipeline.yaml
├── README.md
├── requirements.txt
├── backend/
│   ├── manage.py
│   ├── db.sqlite3
│   ├── local_chroma_db/
│   ├── models/
│   │   └── all-MiniLM-L6-v2/
│   ├── process/
│   │   ├── rag_engine.py
│   │   ├── document_compare.py
│   │   ├── llm_summary.py
│   │   ├── views.py
│   │   └── models.py
│   └── ragocr/
│       ├── settings.py
│       └── urls.py
├── frontend/
│   ├── index.html
│   ├── package.json
│   ├── vite.config.js
│   └── src/
│       ├── App.jsx
│       └── components/
└── docs/ (optional)
```

Key backend files:

- `backend/process/rag_engine.py` — ingestion, embedding, retrieval, generation
- `backend/process/document_compare.py` — document diff tools
- `backend/process/views.py` — public API endpoints used by the frontend

Use this tree to quickly locate the main flow: ingest -> embed -> index -> query.

## Models, DB, and Config

- Embedding model (local): `backend/models/all-MiniLM-L6-v2`.
- Chroma DB location: `backend/local_chroma_db`.
- LLM endpoint: default `http://localhost:11434/api/generate` (see `backend/process/rag_engine.py`).

API endpoints: defined in `backend/process/views.py` and routed in `backend/urls.py`.

## Development Tips

- Re-ingest documents after changing embedding models or tokenization.
- Tune `CHROMA_BATCH_SIZE` and `SIMILARITY_THRESHOLD` in `backend/process/rag_engine.py` for retrieval behavior.
- Ensure the LLM service used for generation is reachable; update `OLLAMA_API` if necessary.

## Troubleshooting

- Missing model files: populate `backend/models/all-MiniLM-L6-v2` or adjust code to download models.
- Chroma DB issues: back up and remove `backend/local_chroma_db` to re-create the DB if indexing fails.
- LLM unreachable: check local LLM service and firewall settings; confirm `OLLAMA_API` URL.

## Tests & CI

There are no automated tests included. The `pipeline.yaml` contains basic lint/test steps for CI.


File references:

- `backend/` — backend code
- `frontend/` — frontend code
- `requirements.txt` — Python dependencies


