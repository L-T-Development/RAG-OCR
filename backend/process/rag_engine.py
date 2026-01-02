import chromadb
import fitz  # PyMuPDF
from sentence_transformers import SentenceTransformer
import requests
import json
import os
import time
import psutil
import threading
import re

# Optional CUDA support
try:
    import torch
    CUDA_AVAILABLE = torch.cuda.is_available()
except ImportError:
    CUDA_AVAILABLE = False

from .eval_utils import (
    answer_relevance,
    context_precision,
    faithfulness,
)

# --- CONFIGURATION ---
CHROMA_PATH = "./local_chroma_db"
OLLAMA_API = "http://localhost:11434/api/generate"
LLM_MODEL = "llama3.2:1b"

# Retrieval tuning (SAFE DEFAULTS)
CANDIDATE_K = 10
SIMILARITY_THRESHOLD = 0.55
MAX_FINAL_CHUNKS = 5

# ChromaDB batch size limit (default is 5461)
CHROMA_BATCH_SIZE = 5000

# Disable ChromaDB telemetry (PostHog)
os.environ["ANONYMIZED_TELEMETRY"] = "False"

# Initialize ChromaDB (always available)
chroma_client = chromadb.PersistentClient(path=CHROMA_PATH)
collection = chroma_client.get_or_create_collection(name="rag_knowledge_base")


class EmbeddingModelManager:
    """
    Singleton manager for embedding model with lazy loading and configurable path.
    Model is only loaded when needed and can be reloaded with a different path.
    """
    _instance = None
    _lock = threading.Lock()
    
    def __new__(cls):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._initialized = False
        return cls._instance
    
    def __init__(self):
        if self._initialized:
            return
        self._model = None
        self._model_path = None
        self._device = "cuda" if CUDA_AVAILABLE else "cpu"
        self._status = {
            "loaded": False,
            "path": None,
            "error": None,
            "device": self._device
        }
        self._initialized = True
        
        if CUDA_AVAILABLE:
            print(f"[RAG] CUDA Available: {torch.cuda.get_device_name(0)}")
            print(f"[RAG] CUDA Memory: {torch.cuda.get_device_properties(0).total_memory / 1024**3:.1f} GB")
        else:
            print("[RAG] Running on CPU (CUDA not available)")
    
    def _get_model_path_from_db(self):
        """Get model path from database configuration"""
        try:
            from .models import AppConfig
            return AppConfig.get_value('embedding_model_path', None)
        except Exception as e:
            print(f"[RAG] Could not read model path from DB: {e}")
            return None
    
    def _get_default_model_path(self):
        """Get default model path (legacy support)"""
        base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        return os.path.join(base_dir, "models", "all-MiniLM-L6-v2")
    
    def load_model(self, model_path=None, force_reload=False):
        """
        Load the embedding model from specified path.
        
        Args:
            model_path: Path to the model directory. If None, tries DB config then default.
            force_reload: If True, reloads even if already loaded.
        
        Returns:
            bool: True if model loaded successfully
        """
        with self._lock:
            # Determine which path to use
            if model_path is None:
                model_path = self._get_model_path_from_db()
            
            if model_path is None:
                model_path = self._get_default_model_path()
            
            # Check if we need to reload
            if self._model is not None and self._model_path == model_path and not force_reload:
                return True
            
            # Validate path exists
            if not os.path.exists(model_path):
                self._status = {
                    "loaded": False,
                    "path": model_path,
                    "error": f"Model path does not exist: {model_path}",
                    "device": self._device
                }
                print(f"[RAG] ERROR: Model path does not exist: {model_path}")
                return False
            
            # Check for required model files
            required_files = ["config.json"]
            missing_files = [f for f in required_files if not os.path.exists(os.path.join(model_path, f))]
            if missing_files:
                self._status = {
                    "loaded": False,
                    "path": model_path,
                    "error": f"Invalid model directory. Missing files: {missing_files}",
                    "device": self._device
                }
                print(f"[RAG] ERROR: Invalid model directory. Missing: {missing_files}")
                return False
            
            try:
                print(f"[RAG] Loading embedding model from: {model_path}")
                start_time = time.time()
                
                # Unload previous model to free memory
                if self._model is not None:
                    del self._model
                    self._model = None
                    if CUDA_AVAILABLE:
                        torch.cuda.empty_cache()
                
                self._model = SentenceTransformer(model_path, device=self._device)
                self._model_path = model_path
                
                load_time = time.time() - start_time
                self._status = {
                    "loaded": True,
                    "path": model_path,
                    "error": None,
                    "device": self._device,
                    "load_time": round(load_time, 2)
                }
                
                print(f"[RAG] ✓ Embedding model loaded on {self._device.upper()} in {load_time:.2f}s")
                return True
                
            except Exception as e:
                self._status = {
                    "loaded": False,
                    "path": model_path,
                    "error": str(e),
                    "device": self._device
                }
                print(f"[RAG] ERROR loading model: {e}")
                return False
    
    def get_model(self):
        """
        Get the embedding model, loading it if necessary.
        
        Returns:
            SentenceTransformer or None if not available
        """
        if self._model is None:
            self.load_model()
        return self._model
    
    def get_status(self):
        """Get current model status"""
        return self._status.copy()
    
    def is_ready(self):
        """Check if model is loaded and ready"""
        return self._model is not None
    
    def encode(self, texts):
        """
        Encode texts to embeddings.
        
        Args:
            texts: List of strings to encode
            
        Returns:
            List of embeddings
            
        Raises:
            RuntimeError if model not loaded
        """
        model = self.get_model()
        if model is None:
            raise RuntimeError("Embedding model not loaded. Please configure model path in Settings.")
        return model.encode(texts)


# Global singleton instance
model_manager = EmbeddingModelManager()


def get_model_status():
    """Get the current embedding model status"""
    return model_manager.get_status()


def configure_model_path(path):
    """
    Configure and load the embedding model from a new path.
    
    Args:
        path: Path to the model directory
        
    Returns:
        dict with status information
    """
    # Save to database
    try:
        from .models import AppConfig
        AppConfig.set_value('embedding_model_path', path)
    except Exception as e:
        return {
            "success": False,
            "error": f"Failed to save configuration: {e}"
        }
    
    # Load the model
    success = model_manager.load_model(path, force_reload=True)
    status = model_manager.get_status()
    
    return {
        "success": success,
        "status": status
    }


def validate_model_path(path):
    """
    Validate if a path contains a valid embedding model.
    
    Args:
        path: Path to validate
        
    Returns:
        dict with validation result
    """
    if not path:
        return {"valid": False, "error": "Path is empty"}
    
    if not os.path.exists(path):
        return {"valid": False, "error": "Path does not exist"}
    
    if not os.path.isdir(path):
        return {"valid": False, "error": "Path is not a directory"}
    
    # Check for required model files
    required_files = ["config.json"]
    optional_files = ["model.safetensors", "pytorch_model.bin", "tf_model.h5"]
    
    missing_required = [f for f in required_files if not os.path.exists(os.path.join(path, f))]
    if missing_required:
        return {"valid": False, "error": f"Missing required files: {missing_required}"}
    
    # Check if at least one model file exists
    has_model_file = any(os.path.exists(os.path.join(path, f)) for f in optional_files)
    if not has_model_file:
        return {"valid": False, "error": "No model weights file found (safetensors, bin, or h5)"}
    
    return {"valid": True, "error": None}


# ---------------- SMART CHUNKING ----------------
def smart_chunk_text(text, max_words=200, overlap=40):
    """
    Context-preserving chunking with overlap.
    Improves faithfulness and retrieval precision.
    """
    words = text.split()
    chunks = []
    start = 0

    while start < len(words):
        end = start + max_words
        chunk = " ".join(words[start:end])

        if len(chunk.strip()) > 50:
            chunks.append(chunk)

        start = end - overlap

    return chunks


# ---------------- PDF INGESTION ----------------
def process_pdf(file_path, doc_id, thread_id, parent_id, filename):
    # Ensure model is loaded
    if not model_manager.is_ready():
        model_manager.load_model()
    
    if not model_manager.is_ready():
        raise RuntimeError("Embedding model not configured. Please set model path in Settings.")
    
    start_time = time.time()
    process = psutil.Process()
    start_memory = process.memory_info().rss / 1024 / 1024  # MB
    start_cpu = process.cpu_percent(interval=0.1)
    
    print(f"\n[RAG] Processing PDF: {filename} (Doc ID: {doc_id})")
    doc = fitz.open(file_path)

    text_chunks = []
    table_chunks = []
    metadatas = []
    table_metadatas = []
    ids = []
    table_ids = []

    print(f"[RAG] Total Pages: {len(doc)}")

    for page_num, page in enumerate(doc):
        # Extract text chunks
        text = page.get_text()
        chunks = smart_chunk_text(text)

        print(f"[RAG] Page {page_num + 1}: Found {len(chunks)} text chunks")

        for i, chunk in enumerate(chunks):
            chunk_id = f"{doc_id}_{page_num}_{i}"
            text_chunks.append(chunk)
            ids.append(chunk_id)

            metadatas.append({
                "doc_id": str(doc_id),
                "thread_id": str(thread_id),
                "parent_id": str(parent_id) if parent_id else "none",
                "source": filename,
                "page": page_num + 1,
                "type": "text"
            })
        
        # Extract tables from the page
        tables = extract_tables_from_page(page)
        if tables:
            print(f"[RAG] Page {page_num + 1}: Found {len(tables)} tables")
            
            for table in tables:
                table_id = f"{doc_id}_{page_num}_table_{table['index']}"
                table_chunks.append(table["text"])
                table_ids.append(table_id)
                
                table_metadatas.append({
                    "doc_id": str(doc_id),
                    "thread_id": str(thread_id),
                    "parent_id": str(parent_id) if parent_id else "none",
                    "source": filename,
                    "page": page_num + 1,
                    "type": "table",
                    "table_data": json.dumps(table["data"]),
                    "row_count": table["row_count"],
                    "column_count": table["column_count"]
                })

    # Combine text and table chunks
    all_chunks = text_chunks + table_chunks
    all_ids = ids + table_ids
    all_metadatas = metadatas + table_metadatas

    if not all_chunks:
        print("[RAG] No valid chunks found.")
        return {"text_chunks": 0, "table_chunks": 0}

    print(f"[RAG] Embedding {len(all_chunks)} chunks ({len(text_chunks)} text + {len(table_chunks)} table)...")
    embed_start = time.time()
    embeddings = model_manager.encode(all_chunks).tolist()
    embed_time = time.time() - embed_start
    print(f"[RAG] Embedding completed in {embed_time:.2f}s")

    # Batch insert to handle large documents (ChromaDB has ~5461 limit per add())
    db_start = time.time()
    total_chunks = len(all_chunks)
    
    if total_chunks <= CHROMA_BATCH_SIZE:
        # Single batch insert
        collection.add(
            documents=all_chunks,
            embeddings=embeddings,
            metadatas=all_metadatas,
            ids=all_ids
        )
        print(f"[RAG] Inserted {total_chunks} chunks in single batch")
    else:
        # Multiple batch inserts
        for i in range(0, total_chunks, CHROMA_BATCH_SIZE):
            end_idx = min(i + CHROMA_BATCH_SIZE, total_chunks)
            batch_docs = all_chunks[i:end_idx]
            batch_embeds = embeddings[i:end_idx]
            batch_metas = all_metadatas[i:end_idx]
            batch_ids = all_ids[i:end_idx]
            
            collection.add(
                documents=batch_docs,
                embeddings=batch_embeds,
                metadatas=batch_metas,
                ids=batch_ids
            )
            print(f"[RAG] Batch {i//CHROMA_BATCH_SIZE + 1}: Inserted chunks {i+1}-{end_idx} ({len(batch_docs)} chunks)")
    
    db_time = time.time() - db_start
    
    end_time = time.time()
    end_memory = process.memory_info().rss / 1024 / 1024  # MB
    end_cpu = process.cpu_percent(interval=0.1)
    
    print("[RAG] Added to Vector DB successfully.")
    print(f"[RESOURCE] Total Time: {end_time - start_time:.2f}s | Embedding: {embed_time:.2f}s | DB Insert: {db_time:.2f}s")
    print(f"[RESOURCE] Memory: {start_memory:.1f}MB → {end_memory:.1f}MB (Δ{end_memory - start_memory:+.1f}MB) | CPU: {end_cpu:.1f}%")
    return {"text_chunks": len(text_chunks), "table_chunks": len(table_chunks)}


def extract_file_filter(query_text):
    """
    Extract @filename from query if present.
    Returns (clean_query, filename or None)
    """
    match = re.search(r'@([^@]+?\.pdf)', query_text, re.IGNORECASE)

    if not match:
        return query_text, None

    filename = match.group(1).strip()
    cleaned_query = query_text.replace(f"@{filename}", "").strip()
    return cleaned_query, filename

# ---------------- QUERY RAG ----------------
def query_rag(query_text, current_thread_id, parent_thread_id=None):
    # Ensure model is loaded
    if not model_manager.is_ready():
        model_manager.load_model()
    
    if not model_manager.is_ready():
        return {
            "answer": "Embedding model not configured. Please set model path in Settings.",
            "sources": [],
            "chunks": [],
            "confidence": 0,
            "confidence_label": "ERROR"
        }
    
    start_time = time.time()
    process = psutil.Process()
    start_memory = process.memory_info().rss / 1024 / 1024  # MB
    
    print("\n>>> query_rag CALLED")
    print(">>> current_thread_id:", current_thread_id)
    print(">>> parent_thread_id:", parent_thread_id)

    # --- FILE SCOPE FILTER (@filename) ---
    query_text, file_filter = extract_file_filter(query_text)
    conditions = []

    if file_filter:
        print(f"[RAG] File scoped query detected: {file_filter}")

    # --- ACCESS CONTROL ---
    if parent_thread_id:
        base_filter = {
            "$or": [
                {"thread_id": {"$eq": str(current_thread_id)}},
                {"thread_id": {"$eq": str(parent_thread_id)}}
            ]
        }
    else:
        base_filter = {"thread_id": {"$eq": str(current_thread_id)}}
    if file_filter:
        where_filter = {
        "$and": [
            base_filter,
            {"source": {"$eq": file_filter}}
        ]
    }
    else:
        where_filter = base_filter
    print("[RAG] Filter:", where_filter)

    # --- VECTOR SEARCH ---
    embed_start = time.time()
    query_vec = model_manager.encode([query_text]).tolist()
    embed_time = time.time() - embed_start
    
    search_start = time.time()
    results = collection.query(
        query_embeddings=query_vec,
        n_results=CANDIDATE_K,
        where=where_filter
    )
    search_time = time.time() - search_start

    docs = results.get("documents", [[]])[0]
    metas = results.get("metadatas", [[]])[0]
    dists = results.get("distances", [[]])[0]

    print(f"[RAG] Retrieved {len(docs)} candidate chunks in {search_time:.3f}s")
    print(f"[RAG] Query embedding time: {embed_time:.3f}s")
    print("Distances:", dists)

  
    # MAX_DISTANCE_THRESHOLD = 2.0 if file_filter else 1.0


    # filtered_chunks = []

    # for doc, meta, dist in zip(docs, metas, dists):
    #     if dist <= MAX_DISTANCE_THRESHOLD:
    #         filtered_chunks.append((doc, meta, dist))

    # sort by best match (lowest distance first)

    # --- DISTANCE-BASED FILTERING (adaptive & file-safe) ---
    filtered_chunks = []
    if dists:
        best_distance = dists[0]  # Chroma returns sorted distances
        RELATIVE_MARGIN = 0.35 if file_filter else 0.25
        MAX_ABSOLUTE_CAP = 2.2 if file_filter else 1.2
        for doc, meta, dist in zip(docs, metas, dists):
            if (
                dist <= best_distance * (1 + RELATIVE_MARGIN)
                and dist <= MAX_ABSOLUTE_CAP
        ):
                filtered_chunks.append((doc, meta, dist))

# Fallback: never allow empty context if results exist
    if not filtered_chunks and docs:
        filtered_chunks = list(zip(docs, metas, dists))[:2]

    filtered_chunks.sort(key=lambda x: x[2])
    final_chunks = filtered_chunks[:MAX_FINAL_CHUNKS]
    print(f"[RAG] Final chunks after filtering: {len(final_chunks)}")

    # --- GUARDRAIL ---
    if len(final_chunks) < 1:
        
        return {
            "answer": "I don't know based on the uploaded documents.",
            "sources": [],
            "chunks": [],
            "confidence": 0,
            "confidence_label": "LOW"
        }

    # --- CONTEXT ASSEMBLY ---
    context_text = ""
    sources = []
    used_docs = []
    chunks_with_metadata = []

    for doc, meta, sim in final_chunks:
        source_str = f"{meta['source']} (Page {meta['page']})"
        context_text += f"--- Source: {source_str} ---\n{doc}\n\n"
        sources.append(source_str)
        used_docs.append(doc)
        
        # Store chunk with metadata for frontend
        chunks_with_metadata.append({
            "text": doc,
            "source": meta['source'],
            "page": meta['page'],
            "similarity_score": round(float(1 - sim), 3)  # Convert to Python float for JSON
        })

    # --- LLM CALL ---
    system_prompt = """You are a precise and helpful document assistant.

INSTRUCTIONS:
- Answer questions ONLY using the provided context
- Be concise but thorough in your responses
- If the answer is not found in the context, say "I don't know based on the provided documents"
- Never make up information or hallucinate facts
- Quote relevant parts when appropriate
- Structure longer answers with bullet points for clarity
"""

    payload = {
        "model": LLM_MODEL,
        "prompt": f"Context:\n{context_text}\nUser Query: {query_text}",
        "system": system_prompt,
        "stream": False,
        "temperature": 0,
        "options": {
            "num_thread": 8,
            "num_ctx": 4096,
        },
        "keep_alive": "5m",
    }

    try:
        llm_start = time.time()
        response = requests.post(OLLAMA_API, json=payload).json()
        llm_time = time.time() - llm_start
        answer = response.get("response", "Error: No response from LLM.")

        # --- EVALUATION ---
        embed_model = model_manager.get_model()
        eval_start = time.time()
        rel_score, _ = answer_relevance(embed_model, query_text, answer)
        ctx_precision = context_precision(embed_model, query_text, used_docs)
        faithfulness_score = faithfulness(answer, used_docs, embed_model)
        eval_time = time.time() - eval_start

        # Convert numpy floats to Python floats for JSON serialization
        rel_score = float(rel_score)
        ctx_precision = float(ctx_precision)
        faithfulness_score = float(faithfulness_score)

        confidence = (
            (rel_score * 0.4) +
            (faithfulness_score * 0.4) +
            (ctx_precision * 0.2)
        ) * 100

        label = "HIGH" if confidence >= 75 else "MEDIUM" if confidence >= 50 else "LOW"
        
        end_time = time.time()
        total_time = end_time - start_time
        end_memory = process.memory_info().rss / 1024 / 1024  # MB

        print("\n========== RAG EVALUATION ==========")
        print(f"Answer Relevance : {round(rel_score, 3)}")
        print(f"Context Precision: {round(ctx_precision, 3)}")
        print(f"Faithfulness     : {round(faithfulness_score, 3)}")
        print(f"Retrieved Chunks : {len(final_chunks)}")
        print("----------------------------------")
        print(f"Confidence       : {int(confidence)}% ({label})")
        print("=========== PERFORMANCE ============")
        print(f"Total Time       : {total_time:.2f}s")
        print(f"  ├─ Embedding   : {embed_time:.3f}s")
        print(f"  ├─ Search      : {search_time:.3f}s")
        print(f"  ├─ LLM Call    : {llm_time:.2f}s")
        print(f"  └─ Evaluation  : {eval_time:.3f}s")
        print(f"Memory Usage     : {start_memory:.1f}MB → {end_memory:.1f}MB (Δ{end_memory - start_memory:+.1f}MB)")
        print(f"CPU Usage        : {process.cpu_percent(interval=0.1):.1f}%")
        print("==================================\n")

        return {
            "answer": answer,
            "sources": list(set(sources)),
            "chunks": chunks_with_metadata,
            "confidence": round(confidence, 1),
            "confidence_label": label
        }

    except Exception as e:
        return {
            "answer": f"Error connecting to Ollama: {str(e)}",
            "sources": [],
            "chunks": [],
            "confidence": 0,
            "confidence_label": "ERROR"
        }


# ---------------- DELETE ----------------
def delete_from_chroma(doc_id=None, thread_id=None):
    start_time = time.time()
    process = psutil.Process()
    start_memory = process.memory_info().rss / 1024 / 1024  # MB
    
    if not doc_id and not thread_id:
        return False

    where_filter = {}
    if doc_id:
        where_filter["doc_id"] = str(doc_id)
    if thread_id:
        where_filter["thread_id"] = str(thread_id)

    try:
        collection.delete(where=where_filter)
        
        end_time = time.time()
        end_memory = process.memory_info().rss / 1024 / 1024  # MB
        print(f"[RAG] Delete completed in {end_time - start_time:.3f}s")
        print(f"[RESOURCE] Memory: {start_memory:.1f}MB → {end_memory:.1f}MB (Δ{end_memory - start_memory:+.1f}MB)")
        
        return True
    except Exception as e:
        print("Delete error:", e)
        return False


# ---------------- DOCUMENT SUMMARY ----------------
def summarize_document(doc_id=None, thread_id=None):
    """
    Generate a summary of document(s) in the RAG system.
    Can summarize a specific document or all documents in a thread.
    """
    start_time = time.time()
    print(f"\n[SUMMARY] Generating document summary...")
    print(f"[SUMMARY] doc_id: {doc_id}, thread_id: {thread_id}")
    
    # Build filter
    where_filter = {}
    if doc_id:
        where_filter["doc_id"] = str(doc_id)
    elif thread_id:
        where_filter["thread_id"] = str(thread_id)
    else:
        return {"error": "Either doc_id or thread_id is required"}
    
    try:
        # Get all chunks for the document/thread
        results = collection.get(
            where=where_filter,
            include=["documents", "metadatas"]
        )
        
        docs = results.get("documents", [])
        metas = results.get("metadatas", [])
        
        if not docs:
            return {
                "summary": "No documents found to summarize.",
                "chunk_count": 0,
                "sources": []
            }
        
        print(f"[SUMMARY] Found {len(docs)} chunks to summarize")
        
        # Get unique sources
        sources = list(set(f"{m['source']} (Page {m['page']})" for m in metas if m))
        
        # Combine text (limit to first 15 chunks for reasonable LLM context)
        combined_text = "\n\n".join(docs[:15])
        
        # Generate summary via LLM
        system_prompt = """You are a document summarization expert. 
Generate a comprehensive yet concise summary of the document content provided.

INSTRUCTIONS:
- Identify the main topic/purpose of the document
- List key points and important information
- Highlight any critical data, dates, or numbers
- Keep the summary structured and easy to read
- Use bullet points for clarity
- Limit to 200-300 words

FORMAT YOUR RESPONSE AS:
📄 **Document Overview:**
[Brief 1-2 sentence overview]

📌 **Key Points:**
- Point 1
- Point 2
- Point 3

📊 **Important Details:**
[Any specific data, dates, or critical information]

💡 **Summary:**
[2-3 sentence concluding summary]
"""

        payload = {
            "model": LLM_MODEL,
            "prompt": f"Document Content:\n{combined_text}\n\nPlease provide a comprehensive summary:",
            "system": system_prompt,
            "stream": False,
            "temperature": 0.3,
            "options": {
                "num_thread": 8,
                "num_ctx": 4096,
            },
            "keep_alive": "5m",
        }
        
        llm_start = time.time()
        response = requests.post(OLLAMA_API, json=payload, timeout=60).json()
        llm_time = time.time() - llm_start
        
        summary = response.get("response", "Unable to generate summary.")
        
        total_time = time.time() - start_time
        print(f"[SUMMARY] ✓ Summary generated in {total_time:.2f}s (LLM: {llm_time:.2f}s)")
        
        return {
            "summary": summary,
            "chunk_count": len(docs),
            "sources": sources[:10],  # Limit sources shown
            "processing_time": round(total_time, 2)
        }
        
    except requests.exceptions.Timeout:
        return {"error": "LLM timeout - document may be too large"}
    except requests.exceptions.ConnectionError:
        return {"error": "Cannot connect to Ollama. Make sure it's running."}
    except Exception as e:
        print(f"[SUMMARY] Error: {e}")
        return {"error": str(e)}


def get_thread_documents_summary(thread_id):
    """
    Get a quick overview of all documents in a thread without LLM.
    Returns document list with metadata.
    """
    try:
        results = collection.get(
            where={"thread_id": str(thread_id)},
            include=["metadatas"]
        )
        
        metas = results.get("metadatas", [])
        
        # Group by document
        docs_info = {}
        for m in metas:
            doc_id = m.get("doc_id", "unknown")
            if doc_id not in docs_info:
                docs_info[doc_id] = {
                    "filename": m.get("source", "Unknown"),
                    "pages": set(),
                    "chunk_count": 0
                }
            docs_info[doc_id]["pages"].add(m.get("page", 0))
            docs_info[doc_id]["chunk_count"] += 1
        
        # Format response
        documents = []
        for doc_id, info in docs_info.items():
            documents.append({
                "doc_id": doc_id,
                "filename": info["filename"],
                "total_pages": len(info["pages"]),
                "chunk_count": info["chunk_count"]
            })
        
        return {
            "thread_id": str(thread_id),
            "document_count": len(documents),
            "documents": documents,
            "total_chunks": len(metas)
        }
        
    except Exception as e:
        return {"error": str(e)}


# ---------------- TABLE EXTRACTION ----------------
def extract_tables_from_page(page):
    """
    Extract tables from a PDF page using PyMuPDF's table detection.
    
    Args:
        page: PyMuPDF page object
        
    Returns:
        List of dictionaries containing table data and metadata
    """
    tables = []
    try:
        # Find tables on the page
        tabs = page.find_tables()
        
        for idx, table in enumerate(tabs):
            # Extract table data as list of lists
            table_data = table.extract()
            
            if not table_data or len(table_data) < 2:  # Need at least header + 1 row
                continue
            
            # Convert to structured format
            headers = table_data[0] if table_data else []
            rows = table_data[1:] if len(table_data) > 1 else []
            
            # Create text representation for embedding
            text_repr = f"Table {idx + 1}:\n"
            if headers:
                text_repr += "Columns: " + " | ".join(str(h) for h in headers if h) + "\n"
            for row in rows[:10]:  # Limit rows for text representation
                text_repr += " | ".join(str(cell) for cell in row if cell) + "\n"
            if len(rows) > 10:
                text_repr += f"... and {len(rows) - 10} more rows\n"
            
            tables.append({
                "index": idx,
                "text": text_repr.strip(),
                "data": table_data,
                "headers": headers,
                "row_count": len(rows),
                "column_count": len(headers) if headers else 0
            })
            
    except Exception as e:
        print(f"[RAG] Table extraction error: {e}")
    
    return tables


def extract_pdf_title(file_path):
    """
    Extract a suitable title from a PDF for thread naming.
    Tries: PDF metadata title -> First heading -> First line -> Filename
    
    Args:
        file_path: Path to the PDF file
        
    Returns:
        str: Extracted or generated title
    """
    try:
        doc = fitz.open(file_path)
        
        # 1. Try PDF metadata title
        metadata = doc.metadata
        if metadata and metadata.get("title"):
            title = metadata["title"].strip()
            if len(title) > 5:  # Reasonable title length
                doc.close()
                return title[:100]  # Limit length
        
        # 2. Try to find a heading on the first page
        if len(doc) > 0:
            first_page = doc[0]
            text = first_page.get_text()
            
            if text:
                lines = [l.strip() for l in text.split('\n') if l.strip()]
                
                # Look for a title-like line (short, possibly uppercase)
                for line in lines[:5]:  # Check first 5 non-empty lines
                    # Skip very short or very long lines
                    if 5 < len(line) < 100:
                        # Prefer lines that look like titles
                        if line.isupper() or line.istitle() or len(line) < 50:
                            doc.close()
                            return line[:100]
                
                # Fall back to first meaningful line
                if lines:
                    doc.close()
                    return lines[0][:100]
        
        doc.close()
        
        # 3. Fall back to filename without extension
        basename = os.path.basename(file_path)
        name_without_ext = os.path.splitext(basename)[0]
        # Clean up common filename patterns
        clean_name = re.sub(r'[-_]+', ' ', name_without_ext)
        return clean_name[:100]
        
    except Exception as e:
        print(f"[RAG] Title extraction error: {e}")
        # Ultimate fallback
        basename = os.path.basename(file_path)
        return os.path.splitext(basename)[0][:100]


