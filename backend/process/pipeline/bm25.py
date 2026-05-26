"""
BM25 keyword index — runs alongside ChromaDB for hybrid search.

Chunk IDs are shared with ChromaDB so results can be merged via RRF.
The index is persisted to disk as a pickle file and rebuilt automatically
if missing (reads all chunks back from ChromaDB).
"""

import os
import pickle
import re
import threading
from collections import Counter, defaultdict
from math import log

try:
    from rank_bm25 import BM25Okapi
except ImportError:
    class BM25Okapi:
        def __init__(self, corpus: list[list[str]], k1: float = 1.5, b: float = 0.75):
            self.corpus = corpus
            self.k1 = k1
            self.b = b
            self.doc_len = [len(doc) for doc in corpus]
            self.avgdl = sum(self.doc_len) / len(self.doc_len) if self.doc_len else 0.0
            self.df = defaultdict(int)
            for doc in corpus:
                for token in set(doc):
                    self.df[token] += 1
            self.n_docs = len(corpus)

        def get_scores(self, query_tokens: list[str]):
            if not self.corpus or not query_tokens:
                return []

            scores = []
            query_counts = Counter(query_tokens)
            for doc_index, doc in enumerate(self.corpus):
                score = 0.0
                freq = Counter(doc)
                doc_len = self.doc_len[doc_index] or 1
                norm = self.k1 * (1 - self.b + self.b * doc_len / (self.avgdl or 1.0))
                for token, qf in query_counts.items():
                    tf = freq.get(token, 0)
                    if not tf:
                        continue
                    df = self.df.get(token, 0)
                    idf = log((self.n_docs - df + 0.5) / (df + 0.5) + 1.0)
                    score += idf * (tf * (self.k1 + 1.0)) / (tf + norm) * qf
                scores.append(score)
            return scores

from .config import BM25_INDEX_PATH

# ── Tokenizer ─────────────────────────────────────────────────────────────────

_STOP = {
    "the", "a", "an", "in", "on", "at", "to", "of", "for", "is", "are",
    "was", "were", "be", "been", "and", "or", "not", "this", "that", "with",
    "from", "as", "by", "its", "it", "if", "but",
}


def _tokenize(text: str) -> list[str]:
    """Lowercase, split on non-alphanumeric, remove stopwords and short tokens."""
    tokens = re.findall(r"[a-z0-9][a-z0-9._\-]{0,}", text.lower())
    return [t for t in tokens if len(t) >= 2 and t not in _STOP]


# ── BM25 index ────────────────────────────────────────────────────────────────

class BM25Index:
    """
    Thread-safe, disk-persisted BM25 index over document chunks.

    Each entry stores:
        id    — same chunk ID used in ChromaDB
        tokens — tokenized text
        text   — original text (for returning in results)
        meta   — {doc_id, thread_id, source, page, ...}

    Disk format: pickle of {"docs": [...], "id_to_idx": {...}}
    """

    def __init__(self, path: str = BM25_INDEX_PATH):
        self._path = path
        self._lock = threading.Lock()
        self._docs: list[dict] = []
        self._id_to_idx: dict[str, int] = {}
        self._bm25: BM25Okapi | None = None  # rebuilt lazily after mutations
        self._load()

    # ── Persistence ───────────────────────────────────────────────────────────

    def _load(self):
        if not os.path.exists(self._path):
            return
        try:
            with open(self._path, "rb") as f:
                data = pickle.load(f)
            self._docs      = data.get("docs", [])
            self._id_to_idx = data.get("id_to_idx", {})
            print(f"[BM25] Loaded {len(self._docs)} chunks from index")
        except Exception as e:
            print(f"[BM25] Index load error ({e}) — starting fresh")
            self._docs, self._id_to_idx = [], {}

    def _save(self):
        os.makedirs(os.path.dirname(os.path.abspath(self._path)), exist_ok=True)
        try:
            with open(self._path, "wb") as f:
                pickle.dump({"docs": self._docs, "id_to_idx": self._id_to_idx}, f)
        except Exception as e:
            print(f"[BM25] Index save error: {e}")

    def _rebuild_bm25(self):
        if self._docs:
            self._bm25 = BM25Okapi([d["tokens"] for d in self._docs])
        else:
            self._bm25 = None

    # ── Mutation API ──────────────────────────────────────────────────────────

    def add_batch(self, items: list[tuple[str, str, dict]]):
        """
        Add chunks to the index.
        items: [(chunk_id, text, meta), ...]
        Skips IDs that are already indexed.
        """
        with self._lock:
            added = 0
            for chunk_id, text, meta in items:
                if chunk_id in self._id_to_idx:
                    continue
                self._id_to_idx[chunk_id] = len(self._docs)
                self._docs.append({
                    "id":     chunk_id,
                    "tokens": _tokenize(text),
                    "text":   text,
                    "meta":   meta,
                })
                added += 1
            if added:
                self._bm25 = None  # invalidate; rebuilt lazily on next search
                self._save()
        return added

    def delete(self, doc_id: str | None = None, thread_id: str | None = None):
        """Remove all chunks matching doc_id or thread_id."""
        with self._lock:
            if doc_id:
                self._docs = [d for d in self._docs if d["meta"].get("doc_id") != str(doc_id)]
            elif thread_id:
                self._docs = [d for d in self._docs if d["meta"].get("thread_id") != str(thread_id)]
            else:
                return
            self._id_to_idx = {d["id"]: i for i, d in enumerate(self._docs)}
            self._bm25 = None
            self._save()

    def rebuild_from_chroma(self, collection):
        """Rebuild the entire index from a ChromaDB collection (recovery path)."""
        print("[BM25] Rebuilding from ChromaDB...")
        result = collection.get(include=["documents", "metadatas"])
        ids   = result.get("ids",       [])
        docs  = result.get("documents", [])
        metas = result.get("metadatas", [])
        with self._lock:
            self._docs, self._id_to_idx = [], {}
            for chunk_id, text, meta in zip(ids, docs, metas):
                self._id_to_idx[chunk_id] = len(self._docs)
                self._docs.append({
                    "id":     chunk_id,
                    "tokens": _tokenize(text or ""),
                    "text":   text or "",
                    "meta":   meta or {},
                })
            self._bm25 = None
            self._save()
        print(f"[BM25] Rebuilt: {len(self._docs)} chunks")

    # ── Search ────────────────────────────────────────────────────────────────

    def search(
        self,
        query: str,
        thread_ids: set[str] | None = None,
        file_filter: str | None = None,
        top_k: int = 20,
    ) -> list[tuple[str, float, str, dict]]:
        """
        Returns [(chunk_id, bm25_score, text, meta), ...] sorted by score desc.
        Filters by thread_ids (set) and optional file_filter (exact source match).
        """
        with self._lock:
            if not self._docs:
                return []
            if self._bm25 is None:
                self._rebuild_bm25()
            if self._bm25 is None:
                return []

            tokens = _tokenize(query)
            if not tokens:
                return []

            scores = self._bm25.get_scores(tokens)
            results = []
            for doc, score in zip(self._docs, scores):
                if score <= 0:
                    continue
                meta = doc["meta"]
                if thread_ids and meta.get("thread_id") not in thread_ids:
                    continue
                if file_filter and meta.get("source") != file_filter:
                    continue
                results.append((doc["id"], float(score), doc["text"], meta))

            results.sort(key=lambda x: x[1], reverse=True)
            return results[:top_k]

    def __len__(self):
        return len(self._docs)


# ── Singleton ─────────────────────────────────────────────────────────────────
bm25_index = BM25Index()
