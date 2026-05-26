import os

# ── Paths & URLs ──────────────────────────────────────────────────────────────
CHROMA_PATH = "./local_chroma_db"
BM25_INDEX_PATH = "./local_chroma_db/bm25_index.pkl"
OLLAMA_API = "http://localhost:11434/api/generate"
OLLAMA_EMBED_API = "http://localhost:11434/api/embeddings"   # legacy single-text
OLLAMA_EMBED_BATCH_API = "http://localhost:11434/api/embed"  # batch (Ollama ≥ 0.1.26)

# ── Default models ────────────────────────────────────────────────────────────
DEFAULT_LLM_MODEL = "llama3.1:8b"
DEFAULT_EMBEDDING_PROVIDER = "ollama"
DEFAULT_OLLAMA_EMBEDDING_MODEL = "nomic-embed-text.v1.5:latest"

# ── Retrieval tuning ──────────────────────────────────────────────────────────
CANDIDATE_K = 10
MAX_FINAL_CHUNKS = 5
CHROMA_BATCH_SIZE = 5000
EMBEDDING_BATCH_SIZE = 32

# ── Disable ChromaDB telemetry ────────────────────────────────────────────────
os.environ["ANONYMIZED_TELEMETRY"] = "False"

# ── CUDA detection ────────────────────────────────────────────────────────────
try:
    import torch as _torch
    CUDA_AVAILABLE = _torch.cuda.is_available()
except ImportError:
    _torch = None
    CUDA_AVAILABLE = False

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
        model = AppConfig.get_value("llm_model", DEFAULT_LLM_MODEL)
        return model if model in AVAILABLE_LLM_MODELS else DEFAULT_LLM_MODEL
    except Exception:
        return DEFAULT_LLM_MODEL


def set_llm_model(model_name):
    try:
        from process.models import AppConfig
        if model_name not in AVAILABLE_LLM_MODELS:
            return {"success": False, "error": f"Invalid model: {model_name}"}
        AppConfig.set_value("llm_model", model_name)
        return {"success": True, "model": model_name}
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
