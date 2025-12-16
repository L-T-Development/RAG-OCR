import chromadb
import fitz  # PyMuPDF
from sentence_transformers import SentenceTransformer
import requests
import json
import os
import time
import psutil
import torch

from .eval_utils import (
    answer_relevance,
    context_precision,
    faithfulness,
)

# --- CONFIGURATION ---
CHROMA_PATH = "./local_chroma_db"
# Use local offline model path instead of downloading from HuggingFace
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
EMBED_MODEL = os.path.join(BASE_DIR, "models", "all-MiniLM-L6-v2")
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

# Initialize components
chroma_client = chromadb.PersistentClient(path=CHROMA_PATH)
collection = chroma_client.get_or_create_collection(name="rag_knowledge_base")

# Initialize embedding model with CUDA support

device = "cuda" if torch.cuda.is_available() else "cpu"
embed_model = SentenceTransformer(EMBED_MODEL, device=device)

if torch.cuda.is_available():
    print(f"[RAG] CUDA Available: {torch.cuda.get_device_name(0)}")
    print(f"[RAG] CUDA Memory: {torch.cuda.get_device_properties(0).total_memory / 1024**3:.1f} GB")
print(f"[RAG] Embedding model loaded on: {device.upper()}")

# print("TOTAL CHUNKS IN DB:", collection.count())


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
    start_time = time.time()
    process = psutil.Process()
    start_memory = process.memory_info().rss / 1024 / 1024  # MB
    start_cpu = process.cpu_percent(interval=0.1)
    
    print(f"\n[RAG] Processing PDF: {filename} (Doc ID: {doc_id})")
    doc = fitz.open(file_path)

    text_chunks = []
    metadatas = []
    ids = []

    print(f"[RAG] Total Pages: {len(doc)}")

    for page_num, page in enumerate(doc):
        text = page.get_text()
        chunks = smart_chunk_text(text)

        print(f"[RAG] Page {page_num + 1}: Found {len(chunks)} chunks")

        for i, chunk in enumerate(chunks):
            chunk_id = f"{doc_id}_{page_num}_{i}"
            text_chunks.append(chunk)
            ids.append(chunk_id)

            metadatas.append({
                "doc_id": str(doc_id),
                "thread_id": str(thread_id),
                "parent_id": str(parent_id) if parent_id else "none",
                "source": filename,
                "page": page_num + 1
            })

    if not text_chunks:
        print("[RAG] No valid chunks found.")
        return 0

    print(f"[RAG] Embedding {len(text_chunks)} chunks...")
    embed_start = time.time()
    embeddings = embed_model.encode(text_chunks).tolist()
    embed_time = time.time() - embed_start
    print(f"[RAG] Embedding completed in {embed_time:.2f}s")

    # Batch insert to handle large documents (ChromaDB has ~5461 limit per add())
    db_start = time.time()
    total_chunks = len(text_chunks)
    
    if total_chunks <= CHROMA_BATCH_SIZE:
        # Single batch insert
        collection.add(
            documents=text_chunks,
            embeddings=embeddings,
            metadatas=metadatas,
            ids=ids
        )
        print(f"[RAG] Inserted {total_chunks} chunks in single batch")
    else:
        # Multiple batch inserts
        for i in range(0, total_chunks, CHROMA_BATCH_SIZE):
            end_idx = min(i + CHROMA_BATCH_SIZE, total_chunks)
            batch_docs = text_chunks[i:end_idx]
            batch_embeds = embeddings[i:end_idx]
            batch_metas = metadatas[i:end_idx]
            batch_ids = ids[i:end_idx]
            
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
    return len(text_chunks)
print("AFTER INSERT, TOTAL CHUNKS:", collection.count())


# ---------------- QUERY RAG ----------------
def query_rag(query_text, current_thread_id, parent_thread_id=None):
    start_time = time.time()
    process = psutil.Process()
    start_memory = process.memory_info().rss / 1024 / 1024  # MB
    
    print("\n>>> query_rag CALLED")
    print(">>> current_thread_id:", current_thread_id)
    print(">>> parent_thread_id:", parent_thread_id)

    # --- ACCESS CONTROL ---
    if parent_thread_id:
        where_filter = {
            "$or": [
                {"thread_id": {"$eq": str(current_thread_id)}},
                {"thread_id": {"$eq": str(parent_thread_id)}}
            ]
        }
    else:
        where_filter = {"thread_id": {"$eq": str(current_thread_id)}}

    print("[RAG] Filter:", where_filter)

    # --- VECTOR SEARCH ---
    embed_start = time.time()
    query_vec = embed_model.encode([query_text]).tolist()
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

    # --- DISTANCE-BASED FILTERING (Chroma-safe) ---
    MAX_DISTANCE_THRESHOLD = 1.0  # lower = more similar

    filtered_chunks = []

    for doc, meta, dist in zip(docs, metas, dists):
        if dist <= MAX_DISTANCE_THRESHOLD:
            filtered_chunks.append((doc, meta, dist))

# sort by best match (lowest distance first)
    filtered_chunks.sort(key=lambda x: x[2])
    final_chunks = filtered_chunks[:MAX_FINAL_CHUNKS]
    print(f"[RAG] Final chunks after filtering: {len(final_chunks)}")


    

    # --- GUARDRAIL ---
    if len(final_chunks) < 2:
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
    system_prompt = """
You are a helpful assistant.
Answer strictly from the provided context.
If the answer is not present, say "I don't know" dont halucinate.
"""

    payload = {
        "model": LLM_MODEL,
        "prompt": f"Context:\n{context_text}\nUser Query: {query_text}",
        "system": system_prompt,
        "stream": False,
        "temperature": 0,
        "options": {
            "num_gpu": 99,        # Offload all layers to GPU (99 = auto-detect max)
            "num_thread": 8,      # CPU threads for non-GPU operations
            "num_ctx": 4096,      # Context window size
        },
        "keep_alive": "5m",     # Keep model in GPU memory for 5 minutes
    }

    try:
        llm_start = time.time()
        response = requests.post(OLLAMA_API, json=payload).json()
        llm_time = time.time() - llm_start
        answer = response.get("response", "Error: No response from LLM.")

        # --- EVALUATION ---
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
                "num_gpu": 99,
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


