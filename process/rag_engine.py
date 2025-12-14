import chromadb
import fitz  # PyMuPDF
from sentence_transformers import SentenceTransformer
import requests
import json

from .eval_utils import (
    answer_relevance,
    context_precision,
    faithfulness,
)

# --- CONFIGURATION ---
CHROMA_PATH = "./local_chroma_db"
EMBED_MODEL = "all-MiniLM-L6-v2"
OLLAMA_API = "http://localhost:11434/api/generate"
LLM_MODEL = "llama3.2"

# Retrieval tuning (SAFE DEFAULTS)
CANDIDATE_K = 20
SIMILARITY_THRESHOLD = 0.55
MAX_FINAL_CHUNKS = 5

# Initialize components
chroma_client = chromadb.PersistentClient(path=CHROMA_PATH)
collection = chroma_client.get_or_create_collection(name="rag_knowledge_base")
embed_model = SentenceTransformer(EMBED_MODEL)

print("TOTAL CHUNKS IN DB:", collection.count())


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
    embeddings = embed_model.encode(text_chunks).tolist()

    collection.add(
        documents=text_chunks,
        embeddings=embeddings,
        metadatas=metadatas,
        ids=ids
    )

    print("[RAG] Added to Vector DB successfully.")
    return len(text_chunks)
print("AFTER INSERT, TOTAL CHUNKS:", collection.count())


# ---------------- QUERY RAG ----------------
def query_rag(query_text, current_thread_id, parent_thread_id=None):
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
    query_vec = embed_model.encode([query_text]).tolist()

    results = collection.query(
        query_embeddings=query_vec,
        n_results=CANDIDATE_K,
        # wher
    )

    docs = results.get("documents", [[]])[0]
    metas = results.get("metadatas", [[]])[0]
    dists = results.get("distances", [[]])[0]

    print(f"[RAG] Retrieved {len(docs)} candidate chunks")
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


    # # --- SIMILARITY FILTERING ---
    # filtered_chunks = []

    # for doc, meta, dist in zip(docs, metas, dists):
    #     similarity = 1 - dist

    #     if similarity >= SIMILARITY_THRESHOLD:
    #         filtered_chunks.append((doc, meta, similarity))
    # filtered_chunks.sort(key=lambda x: x[2], reverse=True)

    # final_chunks = filtered_chunks[:MAX_FINAL_CHUNKS]

    # print(f"[RAG] Final chunks after filtering: {len(final_chunks)}")

    # --- GUARDRAIL ---
    if len(final_chunks) < 2:
        return {
            "answer": "I don't know based on the uploaded documents.",
            "sources": []
        }

    # --- CONTEXT ASSEMBLY ---
    context_text = ""
    sources = []
    used_docs = []

    for doc, meta, sim in final_chunks:
        source_str = f"{meta['source']} (Page {meta['page']})"
        context_text += f"--- Source: {source_str} ---\n{doc}\n\n"
        sources.append(source_str)
        used_docs.append(doc)

    # --- LLM CALL ---
    system_prompt = """
You are a helpful assistant.
Answer strictly from the provided context.
If the answer is not present, say "I don't know".
"""

    payload = {
        "model": LLM_MODEL,
        "prompt": f"Context:\n{context_text}\nUser Query: {query_text}",
        "system": system_prompt,
        "stream": False,
        "temperature": 0.1,
    }

    try:
        response = requests.post(OLLAMA_API, json=payload).json()
        answer = response.get("response", "Error: No response from LLM.")

        # --- EVALUATION ---
        rel_score, _ = answer_relevance(embed_model, query_text, answer)
        ctx_precision = context_precision(embed_model, query_text, used_docs)
        faithfulness_score = faithfulness(answer, used_docs, embed_model)

        confidence = (
            (rel_score * 0.4) +
            (faithfulness_score * 0.4) +
            (ctx_precision * 0.2)
        ) * 100

        label = "HIGH" if confidence >= 75 else "MEDIUM" if confidence >= 50 else "LOW"

        print("\n========== RAG EVALUATION ==========")
        print(f"Answer Relevance : {round(rel_score, 3)}")
        print(f"Context Precision: {round(ctx_precision, 3)}")
        print(f"Faithfulness     : {round(faithfulness_score, 3)}")
        print(f"Retrieved Chunks : {len(final_chunks)}")
        print("----------------------------------")
        print(f"Confidence       : {int(confidence)}% ({label})")
        print("==================================\n")

        return {
            "answer": answer,
            "sources": list(set(sources))
        }

    except Exception as e:
        return {
            "answer": f"Error connecting to Ollama: {str(e)}",
            "sources": []
        }


# ---------------- DELETE ----------------
def delete_from_chroma(doc_id=None, thread_id=None):
    if not doc_id and not thread_id:
        return False

    where_filter = {}
    if doc_id:
        where_filter["doc_id"] = str(doc_id)
    if thread_id:
        where_filter["thread_id"] = str(thread_id)

    try:
        collection.delete(where=where_filter)
        return True
    except Exception as e:
        print("Delete error:", e)
        return False



# import chromadb
# import fitz  # PyMuPDF
# from sentence_transformers import SentenceTransformer
# import requests
# import json

# from .eval_utils import (
#     answer_relevance,
#     context_precision,
#     faithfulness,
    
# )

# # --- CONFIGURATION ---
# CHROMA_PATH = "./local_chroma_db"
# EMBED_MODEL = "all-MiniLM-L6-v2"  # Fast, lightweight model
# OLLAMA_API = "http://localhost:11434/api/generate"
# LLM_MODEL = "llama3.2"  # Ensure you have this pulled in Ollama

# CANDIDATE_K = 8
# SIMILARITY_THRESHOLD = 0.72
# MAX_FINAL_CHUNKS = 5


# # Initialize components once (Singleton pattern for speed)
# chroma_client = chromadb.PersistentClient(path=CHROMA_PATH)
# collection = chroma_client.get_or_create_collection(name="rag_knowledge_base")
# embed_model = SentenceTransformer(EMBED_MODEL)
# print("TOTAL CHUNKS IN DB:", collection.count())

# def smart_chunk_text(text, max_words=200, overlap=40):
#     """
#     Splits text into fixed-size word chunks with overlap.
#     This improves retrieval precision and faithfulness.
#     """
#     words = text.split()
#     chunks = []
#     start = 0

#     while start < len(words):
#         end = start + max_words
#         chunk = " ".join(words[start:end])

#         if len(chunk.strip()) > 50:
#             chunks.append(chunk)

#         start = end - overlap

#     return chunks




# def process_pdf(file_path, doc_id, thread_id, parent_id, filename):
#     """
#     Reads PDF -> Chunks -> Embeds -> Stores in Vector DB
#     """
#     print(f"\n[RAG] Processing PDF: {filename} (Doc ID: {doc_id})")
#     doc = fitz.open(file_path)
#     text_chunks = []
#     metadatas = []
#     ids = []
    
#     print(f"[RAG] Total Pages: {len(doc)}")

#     for page_num, page in enumerate(doc):
#         text = page.get_text()
#         # Clean and split text (Simple chunking for speed)
#         # You can make this more complex with LangChain splitters if needed
#         chunks = smart_chunk_text(text)

        
#         print(f"[RAG] Page {page_num+1}: Found {len(chunks)} chunks")
        
#         for i, chunk in enumerate(chunks):
#             chunk_id = f"{doc_id}_{page_num}_{i}"
#             text_chunks.append(chunk)
#             ids.append(chunk_id)
#             print(f"  -> Chunk {i}: {chunk[:50]}...")
            
#             # Store hierarchy info in metadata for filtering later
#             metadatas.append({
#                 "doc_id": str(doc_id),
#                 "thread_id": str(thread_id),
#                 "parent_id": str(parent_id) if parent_id else "none",
#                 "source": filename,
#                 "page": page_num + 1
#             })

#     if text_chunks:
#         print(f"[RAG] Embedding {len(text_chunks)} chunks...")
#         # Batch embedding (Fastest method)
#         embeddings = embed_model.encode(text_chunks).tolist()
#         print("[RAG] Embeddings generated.")
        
#         print(f"[RAG] Adding to Vector DB (Collection: {collection.name})...")
        
#         collection.add(
#             documents=text_chunks,
#             embeddings=embeddings,
#             metadatas=metadatas,
#             ids=ids
#         )
#         print("[RAG] Added to Vector DB successfully.")
#     else:
#         print("[RAG] No valid text chunks found to process.")
    
#     return len(text_chunks)



# def query_rag(query_text, current_thread_id, parent_thread_id=None):
#     print(">>> query_rag CALLED")
#     print(">>> current_thread_id:", current_thread_id)
#     print(">>> parent_thread_id:", parent_thread_id)

#     """
#     Searches vectors with Hierarchical Isolation and asks LLM.
#     """

#     # --- 1. ACCESS CONTROL FILTER ---
#     if parent_thread_id:
#         where_filter = {
#             "$or": [
#                 {"thread_id": {"$eq": str(current_thread_id)}},
#                 {"thread_id": {"$eq": str(parent_thread_id)}}
#             ]
#         }
#     else:
#         where_filter = {"thread_id": {"$eq": str(current_thread_id)}}

#     print(f"[RAG] Filter: {where_filter}")

#     # --- 2. VECTOR SEARCH ---
#     print("[RAG] Generating query embedding...")
#     query_vec = embed_model.encode([query_text]).tolist()

#     print("[RAG] Searching Vector DB...")

#     # results = collection.query(
#     #     query_embeddings=query_vec,
#     #     n_results=3,
#     #     where=where_filter
#     # )

#     CANDIDATE_K = 8

#     results = collection.query(
#         query_embeddings=query_vec,
#         n_results=CANDIDATE_K,
#         where=where_filter )
    
#     docs = results.get("documents", [[]])[0]
#     metas = results.get("metadatas", [[]])[0]
#     dists = results.get("distances", [[]])[0]

#     print(f"[RAG] Retrieved {len(docs)} candidate chunks")

#     # --- SIMILARITY FILTERING ---
#     filtered_chunks = []

#     for doc, meta, dist in zip(docs, metas, dists):
#         similarity = 1 - dist
#         if similarity >= SIMILARITY_THRESHOLD:
#             filtered_chunks.append((doc, meta, similarity))

#     final_chunks = filtered_chunks[:MAX_FINAL_CHUNKS]

#     print(f"[RAG] Final chunks after filtering: {len(final_chunks)}")

 


#     # retrieved_chunks = results["documents"][0] if results["documents"] else []
#     # print(f"[RAG] Found {len(retrieved_chunks)} relevant chunks.")

#     # 🔒 SAFETY GUARD (prevents hallucination)
#     if len(retrieved_chunks) < 2:
#         return {
#             "answer": "I don't know based on the uploaded documents.",
#             "sources": [],
#             "evaluation": {
#                 "reason": "Low retrieval confidence"
#             }
#         }

#     # --- 3. CONTEXT ASSEMBLY ---
#     context_text = ""
#     sources = []

#     for i, doc in enumerate(retrieved_chunks):
#         meta = results["metadatas"][0][i]
#         source_str = f"{meta['source']} (Page {meta['page']})"
#         context_text += f"--- Source: {source_str} ---\n{doc}\n\n"
#         sources.append(source_str)
#         print(f"  -> Context {i+1}: {doc[:100]}... (Source: {source_str})")

#     # --- 4. LLM GENERATION ---
#     system_prompt = """
#     You are a helpful assistant. Use the provided Context to answer the User Query.
#     - Answer only from the provided context.
#     - Cite the sources.
#     - If the answer is not present, say "I don't know".
#     """

#     prompt = f"Context:\n{context_text}\nUser Query: {query_text}"
#     print(f"[RAG] Sending to LLM (Model: {LLM_MODEL})...")

#     payload = {
#         "model": LLM_MODEL,
#         "prompt": prompt,
#         "system": system_prompt,
#         "stream": False,
#         "temperature": 0.1,
#     }

#     try:
#         response = requests.post(OLLAMA_API, json=payload).json()
#         answer = response.get("response", "Error: No response from LLM.")
#         print(f"[RAG] LLM Response: {answer[:100]}...")

#         # ---------------- EVALUATION ----------------

#         rel_score, rel_ok = answer_relevance(
#             embed_model, query_text, answer
#         )

#         ctx_precision = context_precision(
#             embed_model, query_text, retrieved_chunks
#         )

#         faithfulness_score = faithfulness(
#             answer, retrieved_chunks,embed_model
#         )

        

#         confidence_score = (
#             (rel_score * 0.4) +
#             (faithfulness_score * 0.4) +
#             (ctx_precision * 0.2)
#         ) * 100

#         confidence_label = (
#             "HIGH" if confidence_score >= 75
#             else "MEDIUM" if confidence_score >= 50
#             else "LOW"
#         )

#         print("\n========== RAG EVALUATION ==========")
#         print(f"Answer Relevance : {round(rel_score, 3)}")
#         print(f"Context Precision: {round(ctx_precision, 3)}")
#         print(f"Faithfulness     : {round(faithfulness_score, 3)}")
#         print(f"Retrieved Chunks : {len(retrieved_chunks)}")
#         print("----------------------------------")
#         print(f"Confidence       : {int(round(confidence_score))}% ({confidence_label})")
#         print("==================================\n")

    
#         return {
#             "answer": answer,
#             "sources": list(set(sources)),
            
#         }

#     except Exception as e:
#         print(f"[RAG] Error: {e}")
#         return {
#             "answer": f"Error connecting to Ollama: {str(e)}",
#             "sources": [],
#             "evaluation": {
#                 "error": "LLM call failed"
#             }
#         }



# def delete_from_chroma(doc_id=None, thread_id=None):
#     """
#     Deletes vectors from ChromaDB based on doc_id or thread_id.
#     """
#     if not doc_id and not thread_id:
#         return 0

#     where_filter = {}
#     if doc_id:
#         where_filter["doc_id"] = str(doc_id)
    
#     # If thread_id is provided, we might want to delete everything for that thread
#     # NOTE: In a recursive delete scenario, you might call this for each doc, 
#     # or you could try to delete by thread_id if your metadata supports it.
#     # Our metadata has 'thread_id', so we can use that.
#     if thread_id:
#         where_filter["thread_id"] = str(thread_id)

#     # Perform deletion
#     try:
#         # ChromaDB delete expects a 'where' clause matching metadata
#         collection.delete(where=where_filter)
#         return True
#     except Exception as e:
#         print(f"Error deleting from Chroma: {e}")
#         return False