import chromadb
import fitz  # PyMuPDF
from sentence_transformers import SentenceTransformer
import requests
import json

from .eval_utils import (
    answer_relevance,
    context_precision,
    faithfulness,
    context_recall
)

# --- CONFIGURATION ---
CHROMA_PATH = "./local_chroma_db"
EMBED_MODEL = "all-MiniLM-L6-v2"  # Fast, lightweight model
OLLAMA_API = "http://localhost:11434/api/generate"
LLM_MODEL = "llama3.2"  # Ensure you have this pulled in Ollama

# Initialize components once (Singleton pattern for speed)
chroma_client = chromadb.PersistentClient(path=CHROMA_PATH)
collection = chroma_client.get_or_create_collection(name="rag_knowledge_base")
embed_model = SentenceTransformer(EMBED_MODEL)
print("TOTAL CHUNKS IN DB:", collection.count())


    # rest of your logic


def process_pdf(file_path, doc_id, thread_id, parent_id, filename):
    """
    Reads PDF -> Chunks -> Embeds -> Stores in Vector DB
    """
    print(f"\n[RAG] Processing PDF: {filename} (Doc ID: {doc_id})")
    doc = fitz.open(file_path)
    text_chunks = []
    metadatas = []
    ids = []
    
    print(f"[RAG] Total Pages: {len(doc)}")

    for page_num, page in enumerate(doc):
        text = page.get_text()
        # Clean and split text (Simple chunking for speed)
        # You can make this more complex with LangChain splitters if needed
        chunks = [c.strip() for c in text.split('\n\n') if len(c) > 50]
        
        print(f"[RAG] Page {page_num+1}: Found {len(chunks)} chunks")
        
        for i, chunk in enumerate(chunks):
            chunk_id = f"{doc_id}_{page_num}_{i}"
            text_chunks.append(chunk)
            ids.append(chunk_id)
            print(f"  -> Chunk {i}: {chunk[:50]}...")
            
            # Store hierarchy info in metadata for filtering later
            metadatas.append({
                "doc_id": str(doc_id),
                "thread_id": str(thread_id),
                "parent_id": str(parent_id) if parent_id else "none",
                "source": filename,
                "page": page_num + 1
            })

    if text_chunks:
        print(f"[RAG] Embedding {len(text_chunks)} chunks...")
        # Batch embedding (Fastest method)
        embeddings = embed_model.encode(text_chunks).tolist()
        print("[RAG] Embeddings generated.")
        
        print(f"[RAG] Adding to Vector DB (Collection: {collection.name})...")
        
        collection.add(
            documents=text_chunks,
            embeddings=embeddings,
            metadatas=metadatas,
            ids=ids
        )
        print("[RAG] Added to Vector DB successfully.")
    else:
        print("[RAG] No valid text chunks found to process.")
    
    return len(text_chunks)

# def query_rag(query_text, current_thread_id, parent_thread_id=None):
#     print(">>> query_rag CALLED")
#     print(">>> current_thread_id:", current_thread_id)
#     print(">>> parent_thread_id:", parent_thread_id)
#     """
#     Searches vectors with Hierarchical Isolation and asks LLM.
#     """
    
#     # --- 1. ACCESS CONTROL FILTER ---
#     # If Parent: See only my thread.
#     # If Child: See my thread OR my parent's thread.
    
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
    
#     results = collection.query(
#         query_embeddings=query_vec,
#         n_results=5, # Top 5 relevant chunks
#         where=where_filter
#     )
#     print(f"[RAG] Found {len(results['documents'][0]) if results['documents'] else 0} relevant chunks.")
#     retrieved_chunks = results["documents"][0] if results["documents"] else []


#     # --- 3. CONTEXT ASSEMBLY ---
#     context_text = ""
#     sources = []
    
#     if results['documents']:
#         for i, doc in enumerate(results['documents'][0]):
#             meta = results['metadatas'][0][i]
#             source_str = f"{meta['source']} (Page {meta['page']})"
#             context_text += f"--- Source: {source_str} ---\n{doc}\n\n"
#             sources.append(source_str)
#             print(f"  -> Context {i+1}: {doc[:100]}... (Source: {source_str})")

#     # --- 4. LLM GENERATION ---
#     if not context_text:
#         print("[RAG] No context found. Returning early.")
#         return {"answer": "No relevant documents found in this thread context.", "sources": []}

#     system_prompt = """
#     You are a helpful assistant. Use the provided Context to answer the User Query.
#     - If the user asks for a summary, summarize the context.
#     - If the user asks about a keyword, define it and explain its relationships in the text.
#     - Cite the provided sources.
#     - If the text or context is not present in the provided context, say "I don't know" and dont say anything else.
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

      


#     except Exception as e:
#         answer = f"Error connecting to Ollama: {str(e)}"
#         print(f"[RAG] Error: {e}")

#     return {"answer": answer, "sources": list(set(sources))}


def query_rag(query_text, current_thread_id, parent_thread_id=None):
    print(">>> query_rag CALLED")
    print(">>> current_thread_id:", current_thread_id)
    print(">>> parent_thread_id:", parent_thread_id)

    """
    Searches vectors with Hierarchical Isolation and asks LLM.
    """

    # --- 1. ACCESS CONTROL FILTER ---
    if parent_thread_id:
        where_filter = {
            "$or": [
                {"thread_id": {"$eq": str(current_thread_id)}},
                {"thread_id": {"$eq": str(parent_thread_id)}}
            ]
        }
    else:
        where_filter = {"thread_id": {"$eq": str(current_thread_id)}}

    print(f"[RAG] Filter: {where_filter}")

    # --- 2. VECTOR SEARCH ---
    print("[RAG] Generating query embedding...")
    query_vec = embed_model.encode([query_text]).tolist()

    print("[RAG] Searching Vector DB...")

    results = collection.query(
        query_embeddings=query_vec,
        n_results=5,
        where=where_filter
    )

    retrieved_chunks = results["documents"][0] if results["documents"] else []
    print(f"[RAG] Found {len(retrieved_chunks)} relevant chunks.")

    # 🔒 SAFETY GUARD (prevents hallucination)
    if len(retrieved_chunks) < 2:
        return {
            "answer": "I don't know based on the uploaded documents.",
            "sources": [],
            "evaluation": {
                "reason": "Low retrieval confidence"
            }
        }

    # --- 3. CONTEXT ASSEMBLY ---
    context_text = ""
    sources = []

    for i, doc in enumerate(retrieved_chunks):
        meta = results["metadatas"][0][i]
        source_str = f"{meta['source']} (Page {meta['page']})"
        context_text += f"--- Source: {source_str} ---\n{doc}\n\n"
        sources.append(source_str)
        print(f"  -> Context {i+1}: {doc[:100]}... (Source: {source_str})")

    # --- 4. LLM GENERATION ---
    system_prompt = """
    You are a helpful assistant. Use the provided Context to answer the User Query.
    - Answer only from the provided context.
    - Cite the sources.
    - If the answer is not present, say "I don't know".
    """

    prompt = f"Context:\n{context_text}\nUser Query: {query_text}"
    print(f"[RAG] Sending to LLM (Model: {LLM_MODEL})...")

    payload = {
        "model": LLM_MODEL,
        "prompt": prompt,
        "system": system_prompt,
        "stream": False,
        "temperature": 0.1,
    }

    try:
        response = requests.post(OLLAMA_API, json=payload).json()
        answer = response.get("response", "Error: No response from LLM.")
        print(f"[RAG] LLM Response: {answer[:100]}...")

        # ---------------- EVALUATION ----------------

        rel_score, rel_ok = answer_relevance(
            embed_model, query_text, answer
        )

        ctx_precision = context_precision(
            embed_model, query_text, retrieved_chunks
        )

        faithfulness_score = faithfulness(
            answer, retrieved_chunks,embed_model
        )

        

        confidence_score = (
            (rel_score * 0.4) +
            (faithfulness_score * 0.4) +
            (ctx_precision * 0.2)
        ) * 100

        confidence_label = (
            "HIGH" if confidence_score >= 75
            else "MEDIUM" if confidence_score >= 50
            else "LOW"
        )

        print("\n========== RAG EVALUATION ==========")
        print(f"Answer Relevance : {round(rel_score, 3)}")
        print(f"Context Precision: {round(ctx_precision, 3)}")
        print(f"Faithfulness     : {round(faithfulness_score, 3)}")
        print(f"Retrieved Chunks : {len(retrieved_chunks)}")
        print("----------------------------------")
        print(f"Confidence       : {int(round(confidence_score))}% ({confidence_label})")
        print("==================================\n")

        


    
        return {
            "answer": answer,
            "sources": list(set(sources)),
            
        }

    except Exception as e:
        print(f"[RAG] Error: {e}")
        return {
            "answer": f"Error connecting to Ollama: {str(e)}",
            "sources": [],
            "evaluation": {
                "error": "LLM call failed"
            }
        }

















def delete_from_chroma(doc_id=None, thread_id=None):
    """
    Deletes vectors from ChromaDB based on doc_id or thread_id.
    """
    if not doc_id and not thread_id:
        return 0

    where_filter = {}
    if doc_id:
        where_filter["doc_id"] = str(doc_id)
    
    # If thread_id is provided, we might want to delete everything for that thread
    # NOTE: In a recursive delete scenario, you might call this for each doc, 
    # or you could try to delete by thread_id if your metadata supports it.
    # Our metadata has 'thread_id', so we can use that.
    if thread_id:
        where_filter["thread_id"] = str(thread_id)

    # Perform deletion
    try:
        # ChromaDB delete expects a 'where' clause matching metadata
        collection.delete(where=where_filter)
        return True
    except Exception as e:
        print(f"Error deleting from Chroma: {e}")
        return False