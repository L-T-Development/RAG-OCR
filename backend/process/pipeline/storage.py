import re

import chromadb

from .config import CHROMA_PATH

# ── ChromaDB client (module-level singleton) ──────────────────────────────────
_chroma_client = chromadb.PersistentClient(path=CHROMA_PATH)
_collection_cache: dict = {}
_DEFAULT_COLLECTION = "rag_knowledge_base"


def _safe_suffix(value: str) -> str:
    return re.sub(r"[^a-zA-Z0-9_-]", "_", str(value).lower())


def get_collection():
    """
    Return the active ChromaDB collection.
    Collection name encodes (provider, dimension) so switching embedding
    providers never mixes vectors from different spaces.
    """
    from .embedding import model_manager

    status = model_manager.get_status()
    provider = status.get("provider") or "sentence-transformers"
    dimension = model_manager.get_embedding_dimension()

    # Keep backward-compat name for the original sentence-transformers 384-dim space.
    if provider == "sentence-transformers" and dimension == 384:
        name = _DEFAULT_COLLECTION
    else:
        name = f"{_DEFAULT_COLLECTION}_{_safe_suffix(provider)}_{dimension}"

    if name not in _collection_cache:
        _collection_cache[name] = _chroma_client.get_or_create_collection(name=name)
        print(f"[DB] Collection: {name}")

    return _collection_cache[name]


def delete_from_chroma(doc_id=None, thread_id=None):
    """Delete all vectors (and their tables) for a document or thread."""
    if not doc_id and not thread_id:
        return False

    where: dict = {}
    if doc_id:
        where["doc_id"] = str(doc_id)
    if thread_id:
        where["thread_id"] = str(thread_id)

    try:
        get_collection().delete(where=where)
        from .tables import delete_tables
        delete_tables(doc_id=doc_id, thread_id=thread_id)
        from .bm25 import bm25_index
        bm25_index.delete(doc_id=doc_id, thread_id=thread_id)
        from process.mentions import delete_for
        delete_for(doc_id=doc_id, thread_id=thread_id)
        return True
    except Exception as e:
        print(f"[DB] Delete error: {e}")
        return False
