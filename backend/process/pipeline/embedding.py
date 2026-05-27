import threading
import time

import numpy as np
import requests

from .config import (
    DEFAULT_OLLAMA_EMBEDDING_MODEL,
    OLLAMA_EMBED_API,
    OLLAMA_EMBED_BATCH_API,
    EMBEDDING_BATCH_SIZE,
)


# ── Ollama embedding provider ─────────────────────────────────────────────────

class OllamaEmbeddingProvider:
    """
    Calls Ollama for embeddings.

    Batch path  (Ollama ≥ 0.1.26): POST /api/embed   {"input": [...]}
    Fallback    (all versions):     POST /api/embeddings {"prompt": "..."}  (one at a time)

    The batch path is tried first; on the first failure it is permanently disabled for
    this session so subsequent calls don't waste time retrying a missing endpoint.
    """

    def __init__(self, model_name=DEFAULT_OLLAMA_EMBEDDING_MODEL):
        self.model_name  = model_name
        self._single_url = OLLAMA_EMBED_API
        self._batch_url  = OLLAMA_EMBED_BATCH_API
        self._batch_ok   = True   # optimistic — flipped to False on first failure
        self._dim        = self._probe_dimension()

    def _probe_dimension(self):
        """Get actual embedding dimension from a single test call."""
        # Try batch endpoint first (returns "embeddings" key)
        try:
            r = requests.post(
                self._batch_url,
                json={"model": self.model_name, "input": ["test"]},
                timeout=15,
            )
            if r.status_code == 200:
                embs = r.json().get("embeddings", [])
                if embs and embs[0]:
                    return len(embs[0])
        except Exception:
            pass

        # Legacy single endpoint (returns "embedding" key)
        try:
            r = requests.post(
                self._single_url,
                json={"model": self.model_name, "prompt": "test"},
                timeout=15,
            )
            if r.status_code == 200:
                emb = r.json().get("embedding", [])
                if emb:
                    self._batch_ok = False  # batch probe failed, disable it
                    return len(emb)
        except requests.exceptions.RequestException as e:
            print(f"[EMBED] Warning: Cannot reach Ollama: {e}")

        self._batch_ok = False
        return 768 if "nomic" in self.model_name.lower() else 384

    # nomic-embed-text context = 8192 tokens.
    # Technical PDFs (numbers, codes, units) average ~2 chars/token → 8000 chars ≈ 4000 tokens, safely within limit.
    _MAX_CHARS = 8_000

    def _sanitize(self, texts):
        """Replace empty strings and truncate texts that exceed the model context window."""
        result = []
        for t in texts:
            if not t or not t.strip():
                result.append(" ")
            elif len(t) > self._MAX_CHARS:
                result.append(t[:self._MAX_CHARS])
            else:
                result.append(t)
        return result

    def _encode_batch(self, texts):
        """Single HTTP call for a list of texts via /api/embed."""
        safe_texts = self._sanitize(texts)
        r = requests.post(
            self._batch_url,
            json={"model": self.model_name, "input": safe_texts},
            timeout=max(30, len(texts) * 2),
        )
        if r.status_code != 200:
            try:
                detail = r.json()
            except Exception:
                detail = r.text[:200]
            raise RuntimeError(f"HTTP {r.status_code}: {detail}")
        embs = r.json().get("embeddings", [])
        if len(embs) != len(texts):
            raise RuntimeError(f"Expected {len(texts)} embeddings, got {len(embs)}")
        return embs

    def _encode_single(self, text):
        """Fallback: one HTTP call per text via /api/embeddings."""
        safe = text[:self._MAX_CHARS] if text and len(text) > self._MAX_CHARS else (text or " ")
        r = requests.post(
            self._single_url,
            json={"model": self.model_name, "prompt": safe},
            timeout=30,
        )
        if r.status_code == 200:
            emb = r.json().get("embedding", [])
            return emb if emb else [0.0] * self._dim
        return [0.0] * self._dim

    def encode(self, texts, batch_size=EMBEDDING_BATCH_SIZE, show_progress_bar=False):
        if isinstance(texts, str):
            texts = [texts]

        all_embeddings = []
        for i in range(0, len(texts), batch_size):
            chunk = texts[i : i + batch_size]

            if self._batch_ok:
                try:
                    all_embeddings.extend(self._encode_batch(chunk))
                    continue
                except Exception as e:
                    err = str(e)
                    if "context length" in err.lower():
                        # One text in this batch is too long — embed each text individually
                        # and keep batch mode enabled for future chunks
                        print(f"[EMBED] Context limit hit, retrying {len(chunk)} texts one-by-one")
                        for text in chunk:
                            try:
                                emb = self._encode_batch([text])[0]
                            except Exception:
                                emb = self._encode_single(text)
                            all_embeddings.append(emb)
                        continue
                    # Any other error: disable batch for the rest of this document
                    print(f"[EMBED] Batch endpoint unavailable ({err}), switching to single-call mode")
                    self._batch_ok = False

            # Single-call fallback
            for text in chunk:
                try:
                    all_embeddings.append(self._encode_single(text))
                except Exception:
                    all_embeddings.append([0.0] * self._dim)

        return np.array(all_embeddings)

    def get_dimension(self):
        return self._dim

    def get_sentence_embedding_dimension(self):
        return self._dim


# ── Embedding model manager (Ollama-only) ────────────────────────────────────

class EmbeddingModelManager:
    """Thread-safe singleton for the active Ollama embedding model."""

    _instance = None
    _init_lock = threading.Lock()

    def __new__(cls):
        if cls._instance is None:
            with cls._init_lock:
                if cls._instance is None:
                    inst = super().__new__(cls)
                    inst._model = None
                    inst._model_name = None
                    inst._op_lock = threading.Lock()
                    inst._status = {
                        "loaded": False,
                        "provider": "ollama",
                        "model": None,
                        "error": None,
                        "device": "api",
                    }
                    cls._instance = inst
        return cls._instance

    # ── DB helpers ────────────────────────────────────────────────────────────

    def _db_get(self, key, default=None):
        try:
            from process.models import AppConfig
            return AppConfig.get_value(key, default)
        except Exception:
            return default

    def _db_set(self, key, value):
        try:
            from process.models import AppConfig
            AppConfig.set_value(key, value)
        except Exception:
            pass

    # ── Load ──────────────────────────────────────────────────────────────────

    def load_model(self, model_path=None, provider_type=None, force_reload=False):
        """Load or reload the Ollama embedding model."""
        with self._op_lock:
            model_name = (
                model_path
                or self._db_get("ollama_embedding_model", DEFAULT_OLLAMA_EMBEDDING_MODEL)
                or DEFAULT_OLLAMA_EMBEDDING_MODEL
            )
            if self._model and self._model_name == model_name and not force_reload:
                return True
            try:
                t = time.time()
                self._model = OllamaEmbeddingProvider(model_name)
                self._model_name = model_name
                self._status = {
                    "loaded": True,
                    "provider": "ollama",
                    "model": model_name,
                    "path": OLLAMA_EMBED_API,
                    "error": None,
                    "device": "api",
                    "load_time": round(time.time() - t, 2),
                }
                print(f"[EMBED] Ollama ready: {model_name} (dim={self._model.get_dimension()})")
                return True
            except Exception as e:
                self._status = {
                    "loaded": False,
                    "provider": "ollama",
                    "model": model_name,
                    "error": str(e),
                    "device": "api",
                }
                print(f"[EMBED] Ollama load error: {e}")
                return False

    # ── Encode ────────────────────────────────────────────────────────────────

    def get_model(self):
        if self._model is None:
            self.load_model()
        return self._model

    def is_ready(self):
        return self._model is not None

    def get_status(self):
        return self._status.copy()

    def encode(self, texts):
        model = self.get_model()
        if model is None:
            raise RuntimeError("Embedding model not loaded. Make sure Ollama is running.")
        return model.encode(texts, batch_size=EMBEDDING_BATCH_SIZE)

    def get_embedding_dimension(self):
        model = self.get_model()
        if model is None:
            return 768
        return int(model.get_dimension())


# ── Singleton ─────────────────────────────────────────────────────────────────
model_manager = EmbeddingModelManager()


# ── Re-embed job state ────────────────────────────────────────────────────────

_reembed_state: dict = {
    "running": False,
    "total": 0,
    "done": 0,
    "error": None,
    "old_model": None,
    "new_model": None,
}
_reembed_lock = threading.Lock()


def get_reembed_status() -> dict:
    with _reembed_lock:
        return dict(_reembed_state)


def reembed_collection(source_collection, target_collection, old_model: str, new_model: str):
    """
    Copy every chunk from source_collection into target_collection, re-embedding
    each with the currently-loaded model.  Runs in a background thread.
    Rebuilds the BM25 index from the target collection when done.
    """
    global _reembed_state
    with _reembed_lock:
        _reembed_state.update(running=True, total=0, done=0, error=None,
                              old_model=old_model, new_model=new_model)

    PAGE = 200  # chunks per ChromaDB page

    try:
        # --- count total chunks ---
        overview = source_collection.get(limit=1, include=[])
        # ChromaDB doesn't expose count directly; we'll update total as we go

        offset = 0
        while True:
            batch = source_collection.get(
                limit=PAGE,
                offset=offset,
                include=["documents", "metadatas"],
            )
            ids   = batch.get("ids", [])
            texts = batch.get("documents", [])
            metas = batch.get("metadatas", [])

            if not ids:
                break

            with _reembed_lock:
                _reembed_state["total"] += len(ids)

            embeddings = model_manager.encode(texts)

            target_collection.upsert(
                ids=ids,
                documents=texts,
                metadatas=metas,
                embeddings=embeddings.tolist(),
            )

            with _reembed_lock:
                _reembed_state["done"] += len(ids)

            offset += PAGE
            if len(ids) < PAGE:
                break

        # Rebuild BM25 from newly populated collection
        from .bm25 import bm25_index
        bm25_index.rebuild_from_chroma(target_collection)

        with _reembed_lock:
            _reembed_state["running"] = False
        print(f"[EMBED] Re-embed complete: {_reembed_state['done']} chunks migrated")

    except Exception as e:
        with _reembed_lock:
            _reembed_state.update(running=False, error=str(e))
        print(f"[EMBED] Re-embed error: {e}")
    finally:
        try:
            from django.db import connection as _conn
            _conn.close()
        except Exception:
            pass


# ── Config helpers (called by views) ─────────────────────────────────────────

def get_model_status():
    return model_manager.get_status()


def configure_embedding_provider(provider_type, model_path_or_name):
    """
    Load a specific Ollama embedding model and persist the choice.
    Returns reembed_needed=True when the collection dimension changes,
    so the caller can start a background re-embed job.
    """
    try:
        from process.models import AppConfig

        # Capture old state before switching
        old_dim = model_manager.get_embedding_dimension()

        AppConfig.set_value("embedding_provider", "ollama")
        AppConfig.set_value("ollama_embedding_model", model_path_or_name)
        success = model_manager.load_model(model_path_or_name, force_reload=True)

        new_dim = model_manager.get_embedding_dimension()
        reembed_needed = success and (new_dim != old_dim)

        return {
            "success": success,
            "status": model_manager.get_status(),
            "provider": "ollama",
            "model": model_path_or_name,
            "old_dim": old_dim,
            "new_dim": new_dim,
            "reembed_needed": reembed_needed,
        }
    except Exception as e:
        return {"success": False, "error": str(e)}


def configure_model_path(model_name):
    """Alias used by some views — sets the Ollama model name."""
    try:
        from process.models import AppConfig
        old_dim = model_manager.get_embedding_dimension()
        AppConfig.set_value("ollama_embedding_model", model_name)
    except Exception as e:
        return {"success": False, "error": f"Failed to save config: {e}"}
    success = model_manager.load_model(model_name, force_reload=True)
    new_dim = model_manager.get_embedding_dimension()
    return {
        "success": success,
        "status": model_manager.get_status(),
        "old_dim": old_dim,
        "new_dim": new_dim,
        "reembed_needed": success and (new_dim != old_dim),
    }


def validate_model_path(model_name):
    """Check whether the named Ollama model responds correctly."""
    if not model_name:
        return {"valid": False, "error": "Model name is empty"}
    try:
        r = requests.post(
            OLLAMA_EMBED_API,
            json={"model": model_name, "prompt": "test"},
            timeout=15,
        )
        if r.status_code == 200 and r.json().get("embedding"):
            return {"valid": True, "error": None}
        return {"valid": False, "error": f"Ollama returned HTTP {r.status_code}"}
    except requests.exceptions.ConnectionError:
        return {"valid": False, "error": "Cannot connect to Ollama — is it running?"}
    except Exception as e:
        return {"valid": False, "error": str(e)}
