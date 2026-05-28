import os

# ── Paths & URLs ──────────────────────────────────────────────────────────────
# Honor RAGOCR_DATA_DIR (set by the standalone Electron launcher) so vector
# storage lives in the user's writable data folder rather than the bundled
# app directory. Falls back to a local folder for dev/docker.
_data_root = os.environ.get("RAGOCR_DATA_DIR")
if _data_root:
    CHROMA_PATH = os.path.join(_data_root, "local_chroma_db")
    BM25_INDEX_PATH = os.path.join(_data_root, "local_chroma_db", "bm25_index.pkl")
else:
    CHROMA_PATH = "./local_chroma_db"
    BM25_INDEX_PATH = "./local_chroma_db/bm25_index.pkl"
_OLLAMA_BASE = os.environ.get("OLLAMA_API_BASE", "http://localhost:11434")
OLLAMA_API = f"{_OLLAMA_BASE}/api/generate"
OLLAMA_EMBED_API = f"{_OLLAMA_BASE}/api/embeddings"   # legacy single-text
OLLAMA_EMBED_BATCH_API = f"{_OLLAMA_BASE}/api/embed"  # batch (Ollama ≥ 0.1.26)
OLLAMA_TAGS_API = f"{_OLLAMA_BASE}/api/tags"

# ── Default models ────────────────────────────────────────────────────────────
DEFAULT_LLM_MODEL = "llama3.1:8b"
DEFAULT_EMBEDDING_PROVIDER = "ollama"
DEFAULT_OLLAMA_EMBEDDING_MODEL = "nomic-embed-text.v1.5:latest"

# ── Retrieval tuning ──────────────────────────────────────────────────────────
CANDIDATE_K = 10
MAX_FINAL_CHUNKS = 5
CHROMA_BATCH_SIZE = 5000
EMBEDDING_BATCH_SIZE = 8

# ── Disable ChromaDB telemetry ────────────────────────────────────────────────
os.environ["ANONYMIZED_TELEMETRY"] = "False"

# ── Available LLM models ──────────────────────────────────────────────────────
AVAILABLE_LLM_MODELS = {
    "llama3.2:1b": {
        "name": "Llama 3.2 1B",
        "title": "Efficient",
        "description": (
            "Optimized for speed and low memory usage. Perfect for quick responses "
            "on limited hardware."
        ),
        "tier": "efficient",
    },
    "phi3:3.8b": {
        "name": "Phi-3 3.8B",
        "title": "Balanced",
        "description": (
            "Microsoft's powerful small model with excellent reasoning. Ideal balance "
            "of speed and accuracy for RAG tasks."
        ),
        "tier": "balanced",
    },
    "llama3.1:8b": {
        "name": "Llama 3.1 8B",
        "title": "Performance (Best)",
        "description": (
            "Maximum accuracy and reasoning capability. Best for complex queries "
            "and detailed analysis."
        ),
        "tier": "performance",
    },
}

_TIER_ORDER = {"efficient": 0, "balanced": 1, "performance": 2}


# ── LLM model helpers ─────────────────────────────────────────────────────────

def get_current_llm_model():
    try:
        from process.models import AppConfig
        return AppConfig.get_value("llm_model", DEFAULT_LLM_MODEL)
    except Exception:
        return DEFAULT_LLM_MODEL


def set_llm_model(model_name):
    try:
        from process.models import AppConfig
        if not model_name or not isinstance(model_name, str):
            return {"success": False, "error": "Model name is required"}
        AppConfig.set_value("llm_model", model_name.strip())
        return {"success": True, "model": model_name.strip()}
    except Exception as e:
        return {"success": False, "error": str(e)}


def get_llm_models_list():
    current = get_current_llm_model()
    models = [
        {
            "id": mid,
            "name": cfg["name"],
            "title": cfg["title"],
            "description": cfg["description"],
            "tier": cfg["tier"],
            "selected": mid == current,
        }
        for mid, cfg in AVAILABLE_LLM_MODELS.items()
    ]
    models.sort(key=lambda x: _TIER_ORDER.get(x["tier"], 99))
    return models
