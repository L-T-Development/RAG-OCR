import json
import time

import requests

from .config import OLLAMA_API, get_current_llm_model
from .storage import get_collection


def summarize_document(doc_id=None, thread_id=None, long_response=False):
    """
    Generate an LLM summary of a document or all documents in a thread.
    Dynamically scales prompt and chunk sampling to document size.
    `long_response=True` forces a comprehensive, longer summary regardless of size.
    """
    if not doc_id and not thread_id:
        return {"error": "Either doc_id or thread_id is required"}

    where = {}
    if doc_id:
        where["doc_id"] = str(doc_id)
    elif thread_id:
        where["thread_id"] = str(thread_id)

    try:
        results = get_collection().get(where=where, include=["documents", "metadatas"])
        docs  = results.get("documents", [])
        metas = results.get("metadatas", [])

        if not docs:
            return {"summary": "No documents found to summarize.", "chunk_count": 0, "sources": []}

        sources  = list({f"{m['source']} (Page {m['page']})" for m in metas if m})
        max_page = max((m.get("page", 1) for m in metas if m), default=1)
        total    = len(docs)

        # Scale sampling + prompt to document size
        if total < 300:
            scale, limit, word_limit, detail, timeout = "Small", total, "150-250", "concise", 60
            sample = docs
        elif total < 1500:
            scale, limit, word_limit, detail, timeout = "Medium", 30, "300-500", "detailed", 120
            step   = max(1, total // limit)
            sample = docs[::step][:limit]
        else:
            scale, limit, word_limit, detail, timeout = "Large", 40, "600-1000", "comprehensive", 180
            step   = max(1, total // limit)
            sample = docs[::step][:limit]

        # Long-response mode: upgrade word target + detail label + extend timeout
        if long_response:
            word_limit = "1200-2000"
            detail = "comprehensive and thorough"
            timeout = max(timeout, 240)
            num_predict = 3072
        else:
            num_predict = None

        valid = [c for c in sample if c and c.strip()]
        if not valid:
            return {"error": "No valid content chunks for summarization"}

        max_chars = {"Small": 4000, "Medium": 5000, "Large": 4500}[scale]
        combined  = "\n\n".join(valid)
        if len(combined) > max_chars:
            combined = combined[:max_chars] + "\n... (truncated)"

        system = f"""You are a document summarization expert.
Generate a {detail} summary of the content below.

INSTRUCTIONS:
- Identify the main topic/purpose of the document
- List key points and important information
- Highlight critical data, dates, or numbers
- Use bullet points for clarity
- Target length: {word_limit} words

FORMAT:
📄 **Document Overview ({scale} Document):**
[Overview of the {max_page}-page document]

📌 **Key Points:**
- Point 1
- Point 2

📊 **Important Details:**
[Specific data, dates, or critical information]

💡 **Summary:**
[Concluding summary]
"""
        prompt = (
            f"Document Content ({len(sample)} sections):\n{combined}\n\n"
            f"Provide a {detail} summary:"
        )

        options = {"num_thread": 8, "num_ctx": 8192}
        if num_predict is not None:
            options["num_predict"] = num_predict

        t0 = time.time()
        http_r = requests.post(
            OLLAMA_API,
            json={
                "model": get_current_llm_model(),
                "prompt": prompt,
                "system": system,
                "stream": False,
                "temperature": 0.3,
                "options": options,
                "keep_alive": "5m",
            },
            timeout=timeout,
        )

        if http_r.status_code != 200:
            return {"error": f"Ollama returned HTTP {http_r.status_code}: {http_r.text}"}

        try:
            resp = http_r.json()
        except json.JSONDecodeError as e:
            return {"error": f"Invalid JSON from Ollama: {e}"}

        if "error" in resp:
            return {"error": f"Ollama error: {resp['error']}"}

        return {
            "summary": resp.get("response", "Unable to generate summary."),
            "chunk_count": total,
            "sources": sources[:10],
            "processing_time": round(time.time() - t0, 2),
            "scale": scale,
        }

    except requests.exceptions.Timeout:
        return {"error": "LLM timeout — document may be too large, try again"}
    except requests.exceptions.ConnectionError:
        return {"error": "Cannot connect to Ollama. Make sure it is running."}
    except Exception as e:
        return {"error": str(e)}


def get_thread_documents_summary(thread_id):
    """
    Return a lightweight overview of all documents in a thread (no LLM call).
    Groups ChromaDB metadata by doc_id to count pages and chunks.
    """
    try:
        results = get_collection().get(
            where={"thread_id": str(thread_id)},
            include=["metadatas"],
        )
        metas = results.get("metadatas", [])

        docs_info: dict = {}
        for m in metas:
            did = m.get("doc_id", "unknown")
            if did not in docs_info:
                docs_info[did] = {"filename": m.get("source", "Unknown"), "pages": set(), "chunk_count": 0}
            docs_info[did]["pages"].add(m.get("page", 0))
            docs_info[did]["chunk_count"] += 1

        documents = [
            {
                "doc_id": did,
                "filename": info["filename"],
                "total_pages": len(info["pages"]),
                "chunk_count": info["chunk_count"],
            }
            for did, info in docs_info.items()
        ]

        return {
            "thread_id": str(thread_id),
            "document_count": len(documents),
            "documents": documents,
            "total_chunks": len(metas),
        }
    except Exception as e:
        return {"error": str(e)}
