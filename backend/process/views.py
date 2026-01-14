from django.shortcuts import render, get_object_or_404
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.db.models import Q
from .models import Thread, Document, ChatMessage, AppConfig
from django.views.decorators.http import require_http_methods
from .rag_engine import (
    process_pdf, process_document, query_rag, delete_from_chroma, summarize_document,
    get_thread_documents_summary, get_model_status, configure_model_path,
    validate_model_path, extract_pdf_title, get_llm_models_list,
    get_current_llm_model, set_llm_model
)
import json
import os
import time
import tempfile
from process.document_compare import (
    compare_pdfs,
    compare_docx,
    compare_excels,
    create_comparison_job,
    get_comparison_status
)

from process.llm_summary import summarize_diff

# Reports Engine imports
from process.reports_engine import (
    create_report_job,
    get_report_job_status,
    get_report_excel_bytes,
    get_file_columns,
    get_file_columns_with_preview,
    get_column_preview,
    create_single_pdf_job,
    AdvancedComparator,
    MultiPDFComparator,
    SinglePDFComparator
)

def home(request):
    return render(request, 'home.html')
def compare_page(request):
    return render(request, "compare.html")


# --- Thread Creation (Same as before) ---
@csrf_exempt
def create_thread(request):
    if request.method == 'POST':
        data = json.loads(request.body)
        name = data.get('name')
        parent_id = data.get('parent_id')

        parent_thread = None
        if parent_id:
            try:
                parent_thread = Thread.objects.get(id=parent_id)
                if parent_thread.parent:
                    return JsonResponse({'error': 'Max nesting level reached'}, status=400)
            except Thread.DoesNotExist:
                return JsonResponse({'error': 'Parent not found'}, status=404)

        thread = Thread.objects.create(name=name, parent=parent_thread)
        return JsonResponse({
            'id': str(thread.id),
            'name': thread.name,
            'parent_id': str(parent_thread.id) if parent_thread else None
        })

# --- List Threads (Same as before) ---
def list_threads(request):
    parents = Thread.objects.filter(parent__isnull=True).prefetch_related('sub_threads')
    data = []
    for p in parents:
        data.append({
            'id': str(p.id),
            'name': p.name,
            'sub_threads': [{'id': str(s.id), 'name': s.name} for s in p.sub_threads.all()]
        })
    return JsonResponse({'threads': data})

# --- Upload File (UPDATED WITH AI VECTORIZATION) ---
# Supported file types for RAG chat
SUPPORTED_EXTENSIONS = ['.pdf', '.xlsx', '.xls', '.docx']

@csrf_exempt
def upload_file(request, thread_id):
    if request.method == 'POST' and request.FILES.get('file'):
        thread = get_object_or_404(Thread, id=thread_id)
        uploaded_file = request.FILES['file']

        # Check file type
        ext = os.path.splitext(uploaded_file.name)[1].lower()
        if ext not in SUPPORTED_EXTENSIONS:
            return JsonResponse({
                'error': f'Unsupported file type. Supported: {", ".join(SUPPORTED_EXTENSIONS)}'
            }, status=400)

        # 1. Save to SQL Database (Django)
        doc = Document.objects.create(
            thread=thread,
            file=uploaded_file,
            filename=uploaded_file.name
        )

        # 2. Process for Vector Database (ChromaDB)
        try:
            # We need the parent ID to tag the vector for access control
            p_id = thread.parent.id if thread.parent else None

            # Store file path before processing
            file_path = doc.file.path

            chunk_count = process_document(
                file_path=file_path,
                doc_id=doc.id,
                thread_id=thread.id,
                parent_id=p_id,
                filename=doc.filename
            )

            # Delete physical file after successful vectorization
            try:
                if os.path.exists(file_path):
                    os.remove(file_path)
                    print(f"[STORAGE] Deleted file after processing: {file_path}")
            except Exception as delete_error:
                print(f"[STORAGE] Warning: Could not delete file {file_path}: {delete_error}")

            return JsonResponse({
                'message': 'File uploaded and vectorized successfully',
                'filename': doc.filename,
                'chunk_count': chunk_count
            })
        except Exception as e:
            # If vectorization fails, you might want to delete the SQL doc or log the error
            return JsonResponse({'error': f'Vectorization failed: {str(e)}'}, status=500)

    return JsonResponse({'error': 'No file sent'}, status=400)

# --- Get Files List (Same as before) ---
def get_thread_files(request, thread_id):
    current_thread = get_object_or_404(Thread, id=thread_id)
    if current_thread.parent:
        docs = Document.objects.filter(Q(thread=current_thread) | Q(thread=current_thread.parent)).order_by('-uploaded_at')
    else:
        docs = Document.objects.filter(thread=current_thread).order_by('-uploaded_at')

    file_list = [{
        'id': str(d.id),
        'name': d.filename,
        'url': d.file.url,
        'is_inherited': d.thread.id != current_thread.id,
        'source_thread': d.thread.name
    } for d in docs]

    return JsonResponse({'files': file_list, 'thread_name': current_thread.name})


def extract_document_title(file_path, filename):
    """Extract title from document based on file type."""
    ext = os.path.splitext(filename)[1].lower()
    
    if ext == '.pdf':
        return extract_pdf_title(file_path)
    elif ext in ['.xlsx', '.xls']:
        # Use filename without extension for Excel
        return os.path.splitext(filename)[0]
    elif ext == '.docx':
        # Try to extract title from Word document
        try:
            from docx import Document as DocxDocument
            doc = DocxDocument(file_path)
            # Use first heading or paragraph as title
            for para in doc.paragraphs:
                if para.text.strip():
                    title = para.text.strip()[:100]  # Limit length
                    return title if title else os.path.splitext(filename)[0]
            return os.path.splitext(filename)[0]
        except:
            return os.path.splitext(filename)[0]
    else:
        return os.path.splitext(filename)[0]


# --- Quick Upload: Auto-creates thread named after document ---
@csrf_exempt
def quick_upload(request):
    """
    Upload a document and automatically create a thread named after it.
    Used for drag & drop upload when no thread is selected.
    Supports PDF, Excel (.xlsx, .xls), and Word (.docx) files.
    """
    if request.method != 'POST':
        return JsonResponse({'error': 'POST method required'}, status=405)

    if not request.FILES.get('file'):
        return JsonResponse({'error': 'No file sent'}, status=400)

    uploaded_file = request.FILES['file']

    # Check if it's a supported file type
    ext = os.path.splitext(uploaded_file.name)[1].lower()
    if ext not in SUPPORTED_EXTENSIONS:
        return JsonResponse({
            'error': f'Unsupported file type. Supported: {", ".join(SUPPORTED_EXTENSIONS)}'
        }, status=400)

    try:
        # Save file temporarily to extract title
        with tempfile.NamedTemporaryFile(delete=False, suffix=ext) as tmp:
            for chunk in uploaded_file.chunks():
                tmp.write(chunk)
            tmp_path = tmp.name

        # Extract title for thread name
        thread_name = extract_document_title(tmp_path, uploaded_file.name)

        # Create the thread
        thread = Thread.objects.create(name=thread_name, parent=None)

        # Reset file position for upload
        uploaded_file.seek(0)

        # Create document record
        doc = Document.objects.create(
            thread=thread,
            file=uploaded_file,
            filename=uploaded_file.name
        )

        # Store file path before processing
        file_path = doc.file.path

        # Process the document (vectorize it)
        result = process_document(
            file_path=file_path,
            doc_id=str(doc.id),
            thread_id=str(thread.id),
            parent_id=None,
            filename=doc.filename
        )

        # Mark as processed
        doc.is_processed = True
        doc.save()

        # Delete physical file after successful vectorization
        try:
            if os.path.exists(file_path):
                os.remove(file_path)
                print(f"[STORAGE] Deleted file after processing: {file_path}")
        except Exception as delete_error:
            print(f"[STORAGE] Warning: Could not delete file {file_path}: {delete_error}")

        # Clean up temp file
        os.unlink(tmp_path)

        return JsonResponse({
            'thread': {
                'id': str(thread.id),
                'name': thread.name,
                'parent_id': None
            },
            'document': {
                'id': str(doc.id),
                'name': doc.filename,
                'url': doc.file.url
            },
            'chunks': result if isinstance(result, dict) else {'text_chunks': result, 'table_chunks': 0}
        })

    except Exception as e:
        # Clean up temp file on error
        if 'tmp_path' in locals():
            try:
                os.unlink(tmp_path)
            except:
                pass
        return JsonResponse({'error': str(e)}, status=500)


@csrf_exempt
def chat_thread(request, thread_id):
    if request.method == 'POST':
        start_time = time.perf_counter()

        try:
            data = json.loads(request.body)
            query = data.get('query')

            if not query:
                return JsonResponse({'error': 'Query is required'}, status=400)

            thread = get_object_or_404(Thread, id=thread_id)
            parent_id = thread.parent.id if thread.parent else None

            # Save user message
            ChatMessage.objects.create(
                thread=thread,
                role='user',
                content=query
            )

            # Run RAG
            result = query_rag(
                query,
                current_thread_id=thread.id,
                parent_thread_id=parent_id
            )
            processing_time = round(time.perf_counter() - start_time, 3)
            print(f"[API] Chat processing time: {processing_time}s")

            answer = result.get('answer') or result.get('response') or ""
            sources = result.get('sources', [])
            chunks = result.get('chunks', [])
            confidence = result.get('confidence', 0)
            confidence_label = result.get('confidence_label', '')

            # Save AI message with metadata
            ChatMessage.objects.create(
                thread=thread,
                role='ai',
                content=answer,
                sources=sources,
                chunks=chunks,
                confidence=confidence,
                confidence_label=confidence_label
            )

            # Ensure all data is JSON serializable
            response_data = {
                "answer": answer,
                "sources": sources,
                "chunks": chunks,
                "confidence": confidence,
                "confidence_label": confidence_label,
                "processing_time_seconds": processing_time
            }

            return JsonResponse(response_data)

        except Exception as e:
            print(f"[ERROR] Chat endpoint error: {type(e).__name__}: {str(e)}")
            import traceback
            traceback.print_exc()
            return JsonResponse({'error': str(e)}, status=500)

    return JsonResponse({'error': 'Method not allowed'}, status=405)


def get_chat_history(request, thread_id):
    messages = ChatMessage.objects.filter(
        thread_id=thread_id
    ).order_by("timestamp")

    return JsonResponse({
        "messages": [
            {
                "role": m.role,
                "content": m.content,
                "sources": m.sources if m.role == 'ai' else [],
                "chunks": m.chunks if m.role == 'ai' else [],
                "confidence": m.confidence if m.role == 'ai' else None,
                "confidence_label": m.confidence_label if m.role == 'ai' else ''
            }
            for m in messages
        ]
    })


# --- Delete Endpoints ---

@csrf_exempt
@require_http_methods(["DELETE"])
def delete_thread(request, thread_id):
    try:
        thread = get_object_or_404(Thread, id=thread_id)

        # 1. Collect all threads to be deleted (including self and children)
        def get_all_descendant_ids(t):
            ids = [t.id]
            for child in t.sub_threads.all():
                ids.extend(get_all_descendant_ids(child))
            return ids

        all_thread_ids = get_all_descendant_ids(thread)

        # 2. Delete all PDF files from disk for documents in these threads
        from .models import Document
        docs_to_delete = Document.objects.filter(thread_id__in=all_thread_ids)
        deleted_files = []
        for doc in docs_to_delete:
            if doc.file:
                try:
                    file_path = doc.file.path
                    doc.file.delete(save=False)  # Delete file from disk
                    deleted_files.append(file_path)
                except Exception as file_err:
                    print(f"[DELETE] Warning: Could not delete file {doc.filename}: {file_err}")

        print(f"[DELETE] Deleted {len(deleted_files)} PDF files from disk")

        # 3. Delete from Chroma for each thread
        for t_id in all_thread_ids:
            delete_from_chroma(thread_id=t_id)

        # 4. Delete from SQL (Cascade will handle children, documents, and chat messages)
        thread.delete()

        return JsonResponse({
            'message': 'Thread and associated data deleted successfully',
            'deleted_files': len(deleted_files),
            'deleted_threads': len(all_thread_ids)
        })
    except Exception as e:
        import traceback
        traceback.print_exc()
        return JsonResponse({'error': f'Delete failed: {str(e)}'}, status=500)

@csrf_exempt
@require_http_methods(["DELETE"])
def delete_document(request, doc_id):
    try:
        doc = get_object_or_404(Document, id=doc_id)
        filename = doc.filename

        # 1. Delete from Chroma (vector database)
        delete_from_chroma(doc_id=doc.id)
        print(f"[DELETE] Removed document {filename} from Chroma")

        # 2. Delete file from disk
        if doc.file:
            try:
                file_path = doc.file.path
                doc.file.delete(save=False)
                print(f"[DELETE] Deleted file from disk: {file_path}")
            except Exception as file_err:
                print(f"[DELETE] Warning: Could not delete file: {file_err}")

        # 3. Delete from SQL database
        doc.delete()
        print(f"[DELETE] Removed document {filename} from database")

        return JsonResponse({
            'message': 'Document deleted successfully',
            'filename': filename
        })
    except Exception as e:
        import traceback
        traceback.print_exc()
        return JsonResponse({'error': f'Delete failed: {str(e)}'}, status=500)

#comparison
@csrf_exempt
def compare_documents(request):
    """
    NON-BLOCKING document comparison endpoint.
    Submits comparison to background worker and returns immediately with job_id.
    """
    print("\n" + "="*60)
    print("[COMPARE] Document comparison request received")

    if request.method != "POST":
        print("[COMPARE] ERROR: Invalid method:", request.method)
        return JsonResponse({"error": "POST method required"}, status=405)

    old_file = request.FILES.get("old_file")
    new_file = request.FILES.get("new_file")

    print(f"[COMPARE] Old file: {old_file.name if old_file else 'None'}")
    print(f"[COMPARE] New file: {new_file.name if new_file else 'None'}")

    if not old_file or not new_file:
        print("[COMPARE] ERROR: Missing files")
        return JsonResponse({"error": "Both files are required"}, status=400)

    old_ext = os.path.splitext(old_file.name)[1].lower()
    new_ext = os.path.splitext(new_file.name)[1].lower()

    print(f"[COMPARE] File extensions: {old_ext} vs {new_ext}")

    if old_ext != new_ext:
        print("[COMPARE] ERROR: Extension mismatch")
        return JsonResponse({"error": "Files must be of same type"}, status=400)

    # Validate file type
    supported_types = [".pdf", ".docx", ".xlsx"]
    if old_ext not in supported_types:
        print(f"[COMPARE] ERROR: Unsupported file type: {old_ext}")
        return JsonResponse({"error": f"Unsupported file type. Supported: {', '.join(supported_types)}"}, status=400)

    try:
        # Save temp files
        print("[COMPARE] Saving temporary files...")
        with tempfile.NamedTemporaryFile(delete=False, suffix=old_ext) as f_old:
            f_old.write(old_file.read())
            old_path = f_old.name
            print(f"[COMPARE] Old file saved to: {old_path}")

        with tempfile.NamedTemporaryFile(delete=False, suffix=new_ext) as f_new:
            f_new.write(new_file.read())
            new_path = f_new.name
            print(f"[COMPARE] New file saved to: {new_path}")

        # Create background job and return immediately (KEY CHANGE - non-blocking!)
        job_id = create_comparison_job(
            old_path=old_path,
            new_path=new_path,
            old_filename=old_file.name,
            new_filename=new_file.name,
            file_ext=old_ext
        )

        print(f"[COMPARE] ✓ Job {job_id} created and submitted to background worker")
        print("="*60 + "\n")

        # Return immediately with job identifier (HTTP 202 Accepted)
        return JsonResponse({
            "job_id": job_id,
            "status": "pending",
            "message": "Comparison job submitted. Use /api/compare/status/<job_id>/ to check progress."
        }, status=202)

    except Exception as e:
        print(f"[COMPARE] ERROR: {type(e).__name__}: {str(e)}")
        import traceback
        traceback.print_exc()
        return JsonResponse({"error": str(e)}, status=500)


def compare_status(request, job_id):
    """
    Check status of a background comparison job.

    GET /api/compare/status/<job_id>/

    Returns:
    - status: pending | processing | completed | failed
    - progress: 0-100
    - result: Page-wise comparison summary (only when status=completed)
    - error: error message (only when status=failed)
    
    NOTE: Use /api/compare/pages/<job_id>/?page=N for actual page content
    """
    print(f"[COMPARE] Status check for job {job_id}")

    job = get_comparison_status(job_id)

    if not job:
        return JsonResponse({"error": "Job not found"}, status=404)

    # If completed, return page-wise summary (no massive lines array)
    if job.get("status") == "completed" and "result" in job:
        result = job["result"]
    return JsonResponse(job)





def compare_page_detail(request, job_id, page_num):
    """
    Get detailed line-by-line comparison for a specific page.
    
    GET /api/compare/page/<job_id>/<page_num>/
    
    Returns:
    - page_num: The requested page number
    - old_line_count: Number of lines in old document page
    - new_line_count: Number of lines in new document page  
    - diff: Line-by-line difference data
    - page_status: Overall page status (equal, modified, added, removed)
    """
    if request.method != "GET":
        return JsonResponse({"error": "GET method required"}, status=405)
    
    if page_num < 1:
        return JsonResponse({"error": "Page number must be positive"}, status=400)
    
    try:
        from .document_compare import get_page_detail_comparison
        result = get_page_detail_comparison(job_id, page_num)
        
        if "error" in result:
            return JsonResponse(result, status=404 if "not found" in result["error"].lower() else 400)
        
        return JsonResponse(result)
        
    except Exception as e:
        return JsonResponse({"error": str(e)}, status=500)


# ---------------- DOCUMENT SUMMARY ENDPOINTS ----------------

@csrf_exempt
def summarize_thread_documents(request, thread_id):
    """Generate an AI summary of all documents in a thread"""
    if request.method != "GET":
        return JsonResponse({"error": "GET method required"}, status=405)

    print(f"\n[API] Summarize thread documents: {thread_id}")

    try:
        thread = get_object_or_404(Thread, id=thread_id)

        # Get document names from DB
        documents = Document.objects.filter(thread=thread)
        doc_names = [doc.filename for doc in documents]

        result = summarize_document(thread_id=thread.id)

        if "error" in result:
            return JsonResponse(result, status=500)

        # Add extra info
        result["documents"] = doc_names
        result["documents_count"] = len(doc_names)
        result["total_chunks"] = result.get("chunk_count", 0)

        return JsonResponse(result)

    except Exception as e:
        return JsonResponse({"error": str(e)}, status=500)


@csrf_exempt
def summarize_single_document(request, doc_id):
    """Generate an AI summary of a specific document"""
    if request.method != "GET":
        return JsonResponse({"error": "GET method required"}, status=405)

    print(f"\n[API] Summarize single document: {doc_id}")

    try:
        doc = get_object_or_404(Document, id=doc_id)
        result = summarize_document(doc_id=doc.id)

        if "error" in result:
            print(f"[API] Summarization error: {result['error']}")
            return JsonResponse(result, status=500)

        result["filename"] = doc.filename
        return JsonResponse(result)

    except Exception as e:
        print(f"[API] Exception in summarize_single_document: {e}")
        import traceback
        traceback.print_exc()
        return JsonResponse({"error": str(e)}, status=500)


def get_thread_info(request, thread_id):
    """Get metadata about documents in a thread (no LLM call)"""
    if request.method != "GET":
        return JsonResponse({"error": "GET method required"}, status=405)

    try:
        thread = get_object_or_404(Thread, id=thread_id)
        result = get_thread_documents_summary(thread.id)

        if "error" in result:
            return JsonResponse(result, status=500)

        result["thread_name"] = thread.name
        return JsonResponse(result)

    except Exception as e:
        return JsonResponse({"error": str(e)}, status=500)


# ==================== MODEL CONFIGURATION ENDPOINTS ====================

@csrf_exempt
def model_status(request):
    """Get current embedding model status"""
    if request.method != "GET":
        return JsonResponse({"error": "GET method required"}, status=405)

    try:
        status = get_model_status()
        # Also get saved path from DB
        saved_path = AppConfig.get_value('embedding_model_path', None)
        status['saved_path'] = saved_path
        return JsonResponse(status)
    except Exception as e:
        return JsonResponse({"error": str(e)}, status=500)


@csrf_exempt
def model_configure(request):
    """Configure the embedding model path"""
    if request.method != "POST":
        return JsonResponse({"error": "POST method required"}, status=405)

    try:
        data = json.loads(request.body)
        path = data.get('path', '').strip()

        if not path:
            return JsonResponse({"error": "Model path is required"}, status=400)

        # Normalize path (handle both forward and back slashes)
        path = os.path.normpath(path)

        # Configure and load the model
        result = configure_model_path(path)

        if result.get('success'):
            return JsonResponse({
                "message": "Model configured successfully",
                "status": result.get('status', {})
            })
        else:
            return JsonResponse({
                "error": result.get('error', 'Unknown error'),
                "status": result.get('status', {})
            }, status=400)

    except json.JSONDecodeError:
        return JsonResponse({"error": "Invalid JSON"}, status=400)
    except Exception as e:
        return JsonResponse({"error": str(e)}, status=500)


@csrf_exempt
def model_validate(request):
    """Validate a model path without loading it"""
    if request.method != "POST":
        return JsonResponse({"error": "POST method required"}, status=405)

    try:
        data = json.loads(request.body)
        path = data.get('path', '').strip()

        if not path:
            return JsonResponse({"valid": False, "error": "Path is required"})

        # Normalize path
        path = os.path.normpath(path)

        result = validate_model_path(path)
        return JsonResponse(result)

    except json.JSONDecodeError:
        return JsonResponse({"error": "Invalid JSON"}, status=400)
    except Exception as e:
        return JsonResponse({"error": str(e)}, status=500)


@csrf_exempt
def get_app_config(request):
    """Get all app configuration values"""
    if request.method != "GET":
        return JsonResponse({"error": "GET method required"}, status=405)

    try:
        configs = AppConfig.objects.all()
        config_dict = {c.key: c.value for c in configs}
        return JsonResponse({"config": config_dict})
    except Exception as e:
        return JsonResponse({"error": str(e)}, status=500)


# ==================== LLM MODEL SELECTION ENDPOINTS ====================

@csrf_exempt
def llm_models_list(request):
    """Get list of available LLM models"""
    if request.method != "GET":
        return JsonResponse({"error": "GET method required"}, status=405)

    try:
        models = get_llm_models_list()
        current_model = get_current_llm_model()
        return JsonResponse({
            "models": models,
            "current": current_model
        })
    except Exception as e:
        return JsonResponse({"error": str(e)}, status=500)


@csrf_exempt
def llm_model_select(request):
    """Select/switch the LLM model"""
    if request.method != "POST":
        return JsonResponse({"error": "POST method required"}, status=405)

    try:
        data = json.loads(request.body)
        model_id = data.get('model', '').strip()

        if not model_id:
            return JsonResponse({"error": "Model ID is required"}, status=400)

        result = set_llm_model(model_id)

        if result.get('success'):
            return JsonResponse({
                "message": "LLM model switched successfully",
                "model": result.get('model'),
                "models": get_llm_models_list()
            })
        else:
            return JsonResponse({
                "error": result.get('error', 'Unknown error')
            }, status=400)

    except json.JSONDecodeError:
        return JsonResponse({"error": "Invalid JSON"}, status=400)
    except Exception as e:
        return JsonResponse({"error": str(e)}, status=500)


# ==================== REPORTS / COMPARATOR ENDPOINTS ====================

@csrf_exempt
def get_columns_from_file(request):
    """
    Extract column headers from uploaded file (Excel, PDF, Image).
    Fast - only returns column names, no preview.
    
    POST /api/reports/columns/
    Returns: {columns: [...], filename, file_type}
    """
    if request.method != "POST":
        return JsonResponse({"error": "POST method required"}, status=405)
    
    uploaded_file = request.FILES.get("file")
    
    if not uploaded_file:
        return JsonResponse({"error": "File is required"}, status=400)
    
    # Get file extension
    ext = os.path.splitext(uploaded_file.name)[1].lower()
    supported = ['.xlsx', '.xls', '.pdf', '.png', '.jpg', '.jpeg']
    
    if ext not in supported:
        return JsonResponse({
            "error": f"Unsupported file type. Supported: {', '.join(supported)}"
        }, status=400)
    
    try:
        # Save to temp file and store path in session for later preview requests
        with tempfile.NamedTemporaryFile(delete=False, suffix=ext) as f:
            for chunk in uploaded_file.chunks():
                f.write(chunk)
            temp_path = f.name
        
        # Extract columns only (fast)
        columns = get_file_columns(temp_path)
        
        # Store temp path for later preview requests (we'll clean up after comparison)
        # Using a simple in-memory cache
        global _temp_file_cache
        if '_temp_file_cache' not in globals():
            _temp_file_cache = {}
        
        # Generate a file ID
        import hashlib
        file_id = hashlib.md5(f"{uploaded_file.name}_{temp_path}".encode()).hexdigest()[:12]
        _temp_file_cache[file_id] = {
            "path": temp_path,
            "filename": uploaded_file.name,
            "ext": ext
        }
        
        return JsonResponse({
            "columns": columns,
            "filename": uploaded_file.name,
            "file_type": ext,
            "file_id": file_id  # Use this for preview requests
        })
        
    except Exception as e:
        import traceback
        traceback.print_exc()
        return JsonResponse({"error": str(e)}, status=500)


# Temp file cache for preview requests
_temp_file_cache = {}


@csrf_exempt
def get_column_preview_view(request):
    """
    Get preview for a specific column (lazy loading).
    
    POST /api/reports/column-preview/
    - file_id: ID returned from get_columns_from_file
    - column_name: Column to get preview for
    
    Returns: {column, preview: [...], total_count}
    """
    if request.method != "POST":
        return JsonResponse({"error": "POST method required"}, status=405)
    
    try:
        data = json.loads(request.body)
        file_id = data.get("file_id")
        column_name = data.get("column_name")
        
        if not file_id or not column_name:
            return JsonResponse({"error": "file_id and column_name required"}, status=400)
        
        # Get file from cache
        if file_id not in _temp_file_cache:
            return JsonResponse({"error": "File not found. Please re-upload."}, status=404)
        
        file_info = _temp_file_cache[file_id]
        temp_path = file_info["path"]
        
        if not os.path.exists(temp_path):
            del _temp_file_cache[file_id]
            return JsonResponse({"error": "File expired. Please re-upload."}, status=404)
        
        # Get preview for specific column
        result = get_column_preview(temp_path, column_name, preview_count=10)
        
        return JsonResponse(result)
        
    except json.JSONDecodeError:
        return JsonResponse({"error": "Invalid JSON"}, status=400)
    except Exception as e:
        import traceback
        traceback.print_exc()
        return JsonResponse({"error": str(e)}, status=500)


@csrf_exempt
def start_multi_pdf_comparison(request):
    """
    Start a multi-PDF comparison job.
    
    POST /api/reports/compare/
    - source_file: Excel/PDF file with values to search
    - column_name: Column to extract values from
    - pdf_files[]: List of PDF files to search in
    - use_ocr: Optional, enable OCR (default: false)
    """
    if request.method != "POST":
        return JsonResponse({"error": "POST method required"}, status=405)
    
    # Get source file
    source_file = request.FILES.get("source_file")
    if not source_file:
        return JsonResponse({"error": "Source file is required"}, status=400)
    
    # Get column name
    column_name = request.POST.get("column_name")
    if not column_name:
        return JsonResponse({"error": "Column name is required"}, status=400)
    
    # Get PDF files
    pdf_files = request.FILES.getlist("pdf_files")
    if not pdf_files or len(pdf_files) == 0:
        return JsonResponse({"error": "At least one PDF file is required"}, status=400)
    
    # Get OCR option
    use_ocr = request.POST.get("use_ocr", "false").lower() == "true"
    
    print(f"[Reports] Starting comparison: {source_file.name} ({column_name}) against {len(pdf_files)} PDFs")
    
    try:
        # Save source file
        source_ext = os.path.splitext(source_file.name)[1].lower()
        with tempfile.NamedTemporaryFile(delete=False, suffix=source_ext) as f:
            for chunk in source_file.chunks():
                f.write(chunk)
            source_path = f.name
        
        # Save PDF files
        pdf_paths = []
        pdf_filenames = []
        for pdf_file in pdf_files:
            pdf_ext = os.path.splitext(pdf_file.name)[1].lower()
            with tempfile.NamedTemporaryFile(delete=False, suffix=pdf_ext) as f:
                for chunk in pdf_file.chunks():
                    f.write(chunk)
                pdf_paths.append(f.name)
                pdf_filenames.append(pdf_file.name)
        
        # Create background job
        job_id = create_report_job(
            source_path=source_path,
            source_filename=source_file.name,
            column_name=column_name,
            pdf_paths=pdf_paths,
            pdf_filenames=pdf_filenames,
            use_ocr=use_ocr
        )
        
        return JsonResponse({
            "job_id": job_id,
            "status": "pending",
            "message": "Comparison job submitted. Poll /api/reports/status/<job_id>/ for progress."
        }, status=202)
        
    except Exception as e:
        import traceback
        traceback.print_exc()
        return JsonResponse({"error": str(e)}, status=500)


def get_report_status(request, job_id):
    """
    Check status of a report job.
    
    GET /api/reports/status/<job_id>/
    """
    job = get_report_job_status(job_id)
    
    if not job:
        return JsonResponse({"error": "Job not found"}, status=404)
    
    # Return full job status including logs
    response = {
        "status": job.get("status"),
        "progress": job.get("progress", 0),
        "progress_message": job.get("progress_message", ""),
        "source_file": job.get("source_file"),
        "column_name": job.get("column_name"),
        "pdf_count": job.get("pdf_count"),
        "logs": job.get("logs", [])[-15:],  # Last 15 log entries
    }
    
    if job.get("status") == "completed":
        response["result"] = job.get("result")
    elif job.get("status") == "failed":
        response["error"] = job.get("error")
    
    return JsonResponse(response)


@csrf_exempt
def quick_column_compare(request):
    """
    Quick synchronous comparison (for small files).
    
    POST /api/reports/quick-compare/
    """
    if request.method != "POST":
        return JsonResponse({"error": "POST method required"}, status=405)
    
    source_file = request.FILES.get("source_file")
    target_file = request.FILES.get("target_file")
    column_name = request.POST.get("column_name")
    use_ocr = request.POST.get("use_ocr", "false").lower() == "true"
    
    if not all([source_file, target_file, column_name]):
        return JsonResponse({
            "error": "source_file, target_file, and column_name are required"
        }, status=400)
    
    try:
        # Save temp files
        source_ext = os.path.splitext(source_file.name)[1].lower()
        target_ext = os.path.splitext(target_file.name)[1].lower()
        
        with tempfile.NamedTemporaryFile(delete=False, suffix=source_ext) as f:
            for chunk in source_file.chunks():
                f.write(chunk)
            source_path = f.name
        
        with tempfile.NamedTemporaryFile(delete=False, suffix=target_ext) as f:
            for chunk in target_file.chunks():
                f.write(chunk)
            target_path = f.name
        
        # Run comparison
        comparator = AdvancedComparator(use_ocr=use_ocr)
        
        # Extract values
        search_values = comparator.extract_values_from_file(source_path, column_name)
        
        if not search_values:
            return JsonResponse({
                "error": f"No values found in column '{column_name}'"
            }, status=400)
        
        # Search in target
        results = comparator.search_values_in_file(target_path, search_values)
        
        # Cleanup
        os.unlink(source_path)
        os.unlink(target_path)
        
        # Prepare response
        total = len(search_values)
        found_count = len(results['found'])
        not_found_count = len(results['not_found'])
        match_pct = (found_count / total * 100) if total > 0 else 0
        
        return JsonResponse({
            "source_file": source_file.name,
            "target_file": target_file.name,
            "column_name": column_name,
            "total_values": total,
            "found_count": found_count,
            "not_found_count": not_found_count,
            "match_percentage": round(match_pct, 2),
            "found": {k: v for k, v in results['found'].items()},
            "not_found": list(results['not_found'])
        })
        
    except Exception as e:
        import traceback
        traceback.print_exc()
        return JsonResponse({"error": str(e)}, status=500)


@csrf_exempt
def start_single_pdf_comparison(request):
    """
    Start a single PDF comparison job with hybrid OCR support.
    For PDFs with mixed text and scanned content.
    
    POST /api/reports/compare-single/
    - source_file: Excel/PDF file with values to search
    - column_name: Column to extract values from
    - pdf_file: Single PDF file to search in
    - use_ocr: Enable OCR for scanned pages (default: true)
    """
    if request.method != "POST":
        return JsonResponse({"error": "POST method required"}, status=405)
    
    source_file = request.FILES.get("source_file")
    if not source_file:
        return JsonResponse({"error": "Source file is required"}, status=400)
    
    column_name = request.POST.get("column_name")
    if not column_name:
        return JsonResponse({"error": "Column name is required"}, status=400)
    
    pdf_file = request.FILES.get("pdf_file")
    if not pdf_file:
        return JsonResponse({"error": "PDF file is required"}, status=400)
    
    use_ocr = request.POST.get("use_ocr", "true").lower() == "true"
    
    print(f"[Reports] Single PDF comparison: {source_file.name} ({column_name}) vs {pdf_file.name}")
    
    try:
        # Save source file
        source_ext = os.path.splitext(source_file.name)[1].lower()
        with tempfile.NamedTemporaryFile(delete=False, suffix=source_ext) as f:
            for chunk in source_file.chunks():
                f.write(chunk)
            source_path = f.name
        
        # Save PDF file
        pdf_ext = os.path.splitext(pdf_file.name)[1].lower()
        with tempfile.NamedTemporaryFile(delete=False, suffix=pdf_ext) as f:
            for chunk in pdf_file.chunks():
                f.write(chunk)
            pdf_path = f.name
        
        # Create and start job
        job_id = create_single_pdf_job(
            source_path=source_path,
            column_name=column_name,
            pdf_path=pdf_path,
            use_ocr=use_ocr
        )
        
        return JsonResponse({
            "job_id": job_id,
            "message": "Single PDF comparison started",
            "source_file": source_file.name,
            "pdf_file": pdf_file.name,
            "column_name": column_name,
            "ocr_enabled": use_ocr
        })
        
    except Exception as e:
        import traceback
        traceback.print_exc()
        return JsonResponse({"error": str(e)}, status=500)


def download_report(request, job_id):
    """
    Download the Excel report for a completed job.
    Serves directly from memory, no file saved on disk.
    
    GET /api/reports/download/<job_id>/
    """
    job = get_report_job_status(job_id)
    
    if not job:
        return JsonResponse({"error": "Job not found"}, status=404)
    
    if job.get('status') != 'completed':
        return JsonResponse({"error": "Report not ready yet"}, status=400)
    
    excel_bytes = get_report_excel_bytes(job_id)
    
    if not excel_bytes:
        return JsonResponse({"error": "Report data not found"}, status=404)
    
    from django.http import HttpResponse
    
    result = job.get('result', {})
    filename = result.get('excel_filename', f'Report_{job_id[:8]}.xlsx')
    
    response = HttpResponse(
        excel_bytes,
        content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
    )
    response['Content-Disposition'] = f'attachment; filename="{filename}"'
    return response
