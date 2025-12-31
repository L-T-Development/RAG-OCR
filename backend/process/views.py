from django.shortcuts import render, get_object_or_404
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.db.models import Q
from .models import Thread, Document, ChatMessage, AppConfig
from django.views.decorators.http import require_http_methods
from .rag_engine import (
    process_pdf, query_rag, delete_from_chroma, summarize_document, 
    get_thread_documents_summary, get_model_status, configure_model_path, 
    validate_model_path, extract_pdf_title
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
@csrf_exempt
def upload_file(request, thread_id):
    if request.method == 'POST' and request.FILES.get('file'):
        thread = get_object_or_404(Thread, id=thread_id)
        uploaded_file = request.FILES['file']
        
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
            
            chunk_count = process_pdf(
                file_path=doc.file.path, 
                doc_id=doc.id, 
                thread_id=thread.id,
                parent_id=p_id,
                filename=doc.filename
            )
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


# --- Quick Upload: Auto-creates thread named after PDF ---
@csrf_exempt
def quick_upload(request):
    """
    Upload a PDF and automatically create a thread named after the document.
    Used for drag & drop upload when no thread is selected.
    """
    if request.method != 'POST':
        return JsonResponse({'error': 'POST method required'}, status=405)
    
    if not request.FILES.get('file'):
        return JsonResponse({'error': 'No file sent'}, status=400)
    
    uploaded_file = request.FILES['file']
    
    # Check if it's a PDF
    if not uploaded_file.name.lower().endswith('.pdf'):
        return JsonResponse({'error': 'Only PDF files are supported'}, status=400)
    
    try:
        # Save file temporarily to extract title
        with tempfile.NamedTemporaryFile(delete=False, suffix='.pdf') as tmp:
            for chunk in uploaded_file.chunks():
                tmp.write(chunk)
            tmp_path = tmp.name
        
        # Extract title for thread name
        thread_name = extract_pdf_title(tmp_path)
        
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
        
        # Process the PDF (vectorize it)
        result = process_pdf(
            file_path=doc.file.path,
            doc_id=str(doc.id),
            thread_id=str(thread.id),
            parent_id=None,
            filename=doc.filename
        )
        
        # Mark as processed
        doc.is_processed = True
        doc.save()
        
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
        # Helper to get all descendant IDs
        def get_all_descendant_ids(t):
            ids = [t.id]
            for child in t.sub_threads.all():
                ids.extend(get_all_descendant_ids(child))
            return ids

        all_ids = get_all_descendant_ids(thread)
        
        # Delete from Chroma for each thread
        for t_id in all_ids:
            delete_from_chroma(thread_id=t_id)

        # 2. Delete from SQL (Cascade will handle children and documents)
        thread.delete()
        
        return JsonResponse({'message': 'Thread and associated data deleted successfully'})
    except Exception as e:
        import traceback
        traceback.print_exc()
        return JsonResponse({'error': f'Delete failed: {str(e)}'}, status=500)

@csrf_exempt
@require_http_methods(["DELETE"])
def delete_document(request, doc_id):
    try:
        doc = get_object_or_404(Document, id=doc_id)
        
        # 1. Delete from Chroma
        delete_from_chroma(doc_id=doc.id)
         #2 delete file from disk
        if doc.file:
            doc.file.delete(save=False)
        # 2. Delete from SQL
        doc.delete()
        
        return JsonResponse({'message': 'Document deleted successfully'})
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
    - result: comparison result (only when status=completed)
    - error: error message (only when status=failed)
    """
    print(f"[COMPARE] Status check for job {job_id}")
    
    job = get_comparison_status(job_id)
    
    if not job:
        return JsonResponse({"error": "Job not found"}, status=404)
    
    return JsonResponse(job)


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
            return JsonResponse(result, status=500)
        
        result["filename"] = doc.filename
        return JsonResponse(result)
        
    except Exception as e:
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
