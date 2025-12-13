from django.shortcuts import render, get_object_or_404
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.db.models import Q
from .models import Thread, Document
from django.views.decorators.http import require_http_methods
from .rag_engine import process_pdf, query_rag, delete_from_chroma  # Import our engine
import json

def home(request):
    return render(request, 'home.html')

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
            
            process_pdf(
                file_path=doc.file.path, 
                doc_id=doc.id, 
                thread_id=thread.id,
                parent_id=p_id,
                filename=doc.filename
            )
            return JsonResponse({'message': 'File uploaded and vectorized successfully', 'filename': doc.filename})
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

# --- AI Chat / Search Endpoint (NEW) ---
@csrf_exempt
def chat_thread(request, thread_id):
    if request.method == 'POST':
        try:
            data = json.loads(request.body)
            query = data.get('query')
            
            thread = get_object_or_404(Thread, id=thread_id)
            parent_id = thread.parent.id if thread.parent else None

            # Execute RAG Logic
            result = query_rag(query, current_thread_id=thread.id, parent_thread_id=parent_id)
            
            return JsonResponse(result)
        except Exception as e:
            return JsonResponse({'error': str(e)}, status=500)
            
    return JsonResponse({'error': 'Method not allowed'}, status=405)

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
        
        # 2. Delete from SQL
        doc.delete()
        
        return JsonResponse({'message': 'Document deleted successfully'})
    except Exception as e:
        import traceback
        traceback.print_exc()
        return JsonResponse({'error': f'Delete failed: {str(e)}'}, status=500)