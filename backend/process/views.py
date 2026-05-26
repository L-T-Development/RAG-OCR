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
    get_current_llm_model, set_llm_model,
    get_reembed_status, reembed_collection, get_collection,
)
import json
import os
import time
import tempfile
import uuid
import io
import threading
import logging

logger = logging.getLogger(__name__)


def _server_error(e, context="Internal server error"):
    """Log the real exception server-side, return a generic message to the client."""
    logger.error("%s: %s", context, e, exc_info=True)
    return JsonResponse({"error": context}, status=500)
from typing import Optional
from datetime import datetime
from django.db import connection
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
    get_multi_pdf_columns_with_preview,
    get_column_preview,
    create_single_pdf_job,
    AdvancedComparator,
    MultiPDFComparator,
    SinglePDFComparator
)

# Table Search Engine imports
from process.table_search_engine import search_in_pdf, get_pdf_table_info, compare_structured_sources
import re

# Keep source files by default because table comparison/search uses pdfplumber on disk paths.
RETAIN_UPLOADED_FILES = os.getenv('RETAIN_UPLOADED_FILES', 'true').lower() == 'true'

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
                # Removed nesting level restriction - now supports unlimited nesting
            except Thread.DoesNotExist:
                return JsonResponse({'error': 'Parent not found'}, status=404)

        thread = Thread.objects.create(name=name, parent=parent_thread)
        return JsonResponse({
            'id': str(thread.id),
            'name': thread.name,
            'parent_id': str(parent_thread.id) if parent_thread else None
        })

# --- List Threads (UPDATED FOR UNLIMITED NESTING) ---
def list_threads(request):
    def serialize_thread(thread):
        """Recursively serialize thread with all nested sub-threads"""
        return {
            'id': str(thread.id),
            'name': thread.name,
            'sub_threads': [serialize_thread(sub) for sub in thread.sub_threads.all()]
        }
    
    parents = Thread.objects.filter(parent__isnull=True)
    data = [serialize_thread(p) for p in parents]
    return JsonResponse({'threads': data})

# --- Upload File (UPDATED WITH AI VECTORIZATION) ---
# Supported file types for RAG chat
SUPPORTED_EXTENSIONS = ['.pdf', '.xlsx', '.xls', '.docx', '.jpg', '.jpeg', '.png', '.bmp', '.tiff', '.tif']


def _ingest_background(file_path, doc_id, thread_id, parent_id, filename):
    """Run document ingestion in a background thread, updating progress in DB."""
    try:
        process_document(
            file_path=file_path,
            doc_id=doc_id,
            thread_id=thread_id,
            parent_id=parent_id,
            filename=filename,
        )
        Document.objects.filter(id=doc_id).update(is_processed=True)
        if not RETAIN_UPLOADED_FILES:
            try:
                if os.path.exists(file_path):
                    os.remove(file_path)
                    print(f"[STORAGE] Deleted file after processing: {file_path}")
            except Exception as delete_error:
                print(f"[STORAGE] Warning: Could not delete file {file_path}: {delete_error}")
    except Exception as e:
        Document.objects.filter(id=doc_id).update(
            status='error',
            error_message=str(e)[:1000],
        )
    finally:
        connection.close()

@csrf_exempt
def upload_file(request, thread_id):
    if request.method == 'POST' and request.FILES.get('file'):
        thread = get_object_or_404(Thread, id=thread_id)
        uploaded_file = request.FILES['file']
        category = request.POST.get('category', 'other')  # Get category from request

        # Check file type
        ext = os.path.splitext(uploaded_file.name)[1].lower()
        if ext not in SUPPORTED_EXTENSIONS:
            return JsonResponse({
                'error': f'Unsupported file type. Supported: {", ".join(SUPPORTED_EXTENSIONS)}'
            }, status=400)

        # 1. Save to SQL Database (Django) with category
        doc = Document.objects.create(
            thread=thread,
            file=uploaded_file,
            filename=uploaded_file.name,
            category=category
        )

        # 2. Kick off ingestion in a background thread
        p_id = thread.parent.id if thread.parent else None
        file_path = doc.file.path

        doc.status = 'pending'
        doc.progress = 0
        doc.progress_detail = 'Queued for processing…'
        doc.save(update_fields=['status', 'progress', 'progress_detail'])

        t = threading.Thread(
            target=_ingest_background,
            args=(file_path, doc.id, thread.id, p_id, doc.filename),
            daemon=True,
        )
        t.start()

        return JsonResponse({
            'message': 'File uploaded — processing in background',
            'filename': doc.filename,
            'doc_id': str(doc.id),
            'status': 'pending',
        })

    return JsonResponse({'error': 'No file sent'}, status=400)

# --- Helper: Get All Ancestor Thread IDs ---
def get_ancestor_thread_ids(thread):
    """Recursively get all ancestor thread IDs (parent, grandparent, etc.)"""
    ancestor_ids = []
    current = thread
    while current.parent:
        ancestor_ids.append(current.parent.id)
        current = current.parent
    return ancestor_ids

# --- Get Files List with Category ---
def get_thread_files(request, thread_id):
    current_thread = get_object_or_404(Thread, id=thread_id)
    
    # Get all ancestor IDs for inheritance
    ancestor_ids = get_ancestor_thread_ids(current_thread)
    
    if ancestor_ids:
        # Include documents from current thread and all ancestors
        docs = Document.objects.filter(
            Q(thread=current_thread) | Q(thread_id__in=ancestor_ids)
        ).order_by('-uploaded_at')
    else:
        docs = Document.objects.filter(thread=current_thread).order_by('-uploaded_at')

    file_list = [{
        'id': str(d.id),
        'name': d.filename,
        'url': d.file.url,
        'category': d.category if hasattr(d, 'category') else 'other',
        'category_label': dict(d.CATEGORY_CHOICES).get(d.category, 'Other') if hasattr(d, 'category') else 'Other',
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
    elif ext in ['.jpg', '.jpeg', '.png', '.bmp', '.tiff', '.tif']:
        # For images, use filename without extension
        return os.path.splitext(filename)[0]
    else:
        return os.path.splitext(filename)[0]


# --- Quick Upload: Auto-creates thread named after document ---
@csrf_exempt
def quick_upload(request):
    """
    Upload a document and automatically create a thread named after it.
    Used for drag & drop upload when no thread is selected.
    Supports PDF, Excel (.xlsx, .xls), Word (.docx), and Image files (.jpg, .png, etc.).
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

        # Get category from request
        category = request.POST.get('category', 'other')

        # Create document record
        doc = Document.objects.create(
            thread=thread,
            file=uploaded_file,
            filename=uploaded_file.name,
            category=category
        )

        # Store file path before processing
        file_path = doc.file.path

        doc.status = 'pending'
        doc.progress = 0
        doc.progress_detail = 'Queued for processing…'
        doc.save(update_fields=['status', 'progress', 'progress_detail'])

        # Clean up temp file (title was already extracted)
        os.unlink(tmp_path)

        # Kick off ingestion in background
        t = threading.Thread(
            target=_ingest_background,
            args=(file_path, doc.id, thread.id, None, doc.filename),
            daemon=True,
        )
        t.start()

        return JsonResponse({
            'thread': {
                'id': str(thread.id),
                'name': thread.name,
                'parent_id': None
            },
            'document': {
                'id': str(doc.id),
                'name': doc.filename,
                'url': doc.file.url,
                'status': 'pending',
            },
            'status': 'pending',
        })

    except Exception as e:
        # Clean up temp file on error
        if 'tmp_path' in locals():
            try:
                os.unlink(tmp_path)
            except:
                pass
        return _server_error(e)


@csrf_exempt
def chat_thread(request, thread_id):
    if request.method == 'POST':
        start_time = time.perf_counter()
        print(f"[DEBUG-ENTRY] chat_thread POST received, thread_id={thread_id}")

        try:
            data = json.loads(request.body)
            query = data.get('query')
            print(f"[DEBUG-ENTRY] Query received: {query[:100] if query else 'NONE'}")

            if not query:
                return JsonResponse({'error': 'Query is required'}, status=400)

            thread = get_object_or_404(Thread, id=thread_id)
            parent_id = thread.parent.id if thread.parent else None

            # Get conversation history for context (last 5 messages)
            recent_messages = ChatMessage.objects.filter(
                thread=thread
            ).order_by('-timestamp')[:5][::-1]  # Get last 5, reverse to chronological
            
            conversation_context = ""
            if recent_messages:
                conversation_context = "\n\n**Recent conversation:**\n"
                for msg in recent_messages:
                    role_label = "User" if msg.role == 'user' else "Assistant"
                    # Truncate long messages for context
                    content = msg.content[:300] + "..." if len(msg.content) > 300 else msg.content
                    conversation_context += f"{role_label}: {content}\n"
                conversation_context += f"User (current): {query}\n"

            # Save user message
            user_msg = ChatMessage.objects.create(
                thread=thread,
                role='user',
                content=query
            )
            print(f"[CHAT] Saved user message ID: {user_msg.id}, thread: {thread.id}")
            print(f"[CHAT] Total messages in thread: {ChatMessage.objects.filter(thread=thread).count()}")

            # Check if query is asking to search in tables
            table_search_result = None
            suggested_questions = []
            query_lower = query.lower()
            
            # Resolve conversation references (this, that, compare, etc.)
            resolved_query = _resolve_conversation_references(query, recent_messages, thread)
            if resolved_query != query:
                print(f"[CONTEXT] Original: {query}")
                print(f"[CONTEXT] Resolved: {resolved_query}")
                query = resolved_query
                query_lower = query.lower()
            
            # Detect conflict detection query
            is_conflict_query = any(keyword in query_lower for keyword in [
                'repeated', 'duplicate', 'conflict', 'inconsistent', 'same nomenclature',
                'different part number', 'different drawing', 'multiple part', 'multiple drawing'
            ])
            
            if is_conflict_query:
                # Detect conflict analysis
                from .table_search_engine import detect_conflicts
                
                docs = Document.objects.filter(thread=thread, filename__iendswith='.pdf')
                
                if docs.count() >= 1:
                    pdf1 = docs.first()
                    pdf2 = docs[1] if docs.count() >= 2 else None
                    
                    try:
                        conflict_result = detect_conflicts(
                            pdf1.file.path,
                            pdf2.file.path if pdf2 else None
                        )
                        
                        if conflict_result.get('found'):
                            # Generate Excel report
                            excel_bytes = generate_conflict_excel(conflict_result)
                            job_id = store_comparison_report('Conflict_Analysis', conflict_result, excel_bytes)
                            
                            # Format conflicts nicely
                            formatted_answer = _format_conflict_response(conflict_result)
                            formatted_answer += f"\n\n---\n\n📥 **[Download Excel Report](/api/reports/download/{job_id}/)**"
                            
                            table_search_result = {
                                'found': True,
                                'answer': formatted_answer,
                                'type': 'conflict_analysis',
                                'report_job_id': job_id
                            }
                    except Exception as e:
                        print(f"[CONFLICT] Error: {e}")
                        import traceback
                        traceback.print_exc()
            
            # Detect comparison query
            is_comparison = any(keyword in query_lower for keyword in [
                'compare', 'comparison', 'difference', 'differences', 'common',
                'not in', 'missing', 'match between', 'vs', 'versus',
                'found or not found', 'present or not', 'present/not', 'between', 'presence of'
            ])

            # Strict assessment mode: if user explicitly asks DRG/part presence between two PDFs,
            # force deterministic comparison flow instead of narrative RAG fallback.
            import re
            pdf_mentions = re.findall(r'([\w\-. ]+\.pdf)', query, re.IGNORECASE)
            strict_assessment_query = (
                len(set(m.strip().lower() for m in pdf_mentions)) >= 2
                and any(t in query_lower for t in ['drg', 'drawing', 'dwg', 'part', 'nsn'])
                and any(t in query_lower for t in ['compare', 'between', 'present', 'found', 'assessment', 'confirm', 'whether'])
            )

            if strict_assessment_query:
                is_comparison = True

            # Assessment-style intent: "confirm whether X is in there or not" across 2 PDFs
            if not is_comparison:
                assessment_terms = [
                    'assessment', 'assess', 'confirm', 'whether', 'in there or not',
                    'found or not', 'present or not', 'exists or not'
                ]
                domain_terms = ['drg', 'drawing', 'dwg', 'part', 'nsn', 'nomenclature']
                if any(t in query_lower for t in assessment_terms) and any(t in query_lower for t in domain_terms):
                    ancestor_ids = get_ancestor_thread_ids(thread)
                    if ancestor_ids:
                        pdf_count = Document.objects.filter(
                            Q(thread=thread) | Q(thread_id__in=ancestor_ids),
                            filename__iendswith='.pdf'
                        ).count()
                    else:
                        pdf_count = Document.objects.filter(thread=thread, filename__iendswith='.pdf').count()
                    if pdf_count >= 2:
                        is_comparison = True
            
            if is_comparison and not table_search_result:
                # Extract comparison details
                comparison_result = _extract_comparison_info(query, thread)

                # Retry once with explicit intent to help natural-language queries route correctly
                if not comparison_result and strict_assessment_query:
                    forced_query = f"Compare DRG present or not between {query}"
                    comparison_result = _extract_comparison_info(forced_query, thread)
                
                if comparison_result:
                    table_search_result = comparison_result
                elif strict_assessment_query:
                    # Do not silently fall back to narrative answer for strict assessment requests
                    table_search_result = {
                        'found': True,
                        'formatted_answer': (
                            "## ❌ Assessment Could Not Be Completed\n\n"
                            "A strict table comparison was requested, but the comparison engine could not resolve both PDFs or DRG columns.\n\n"
                            "### Try this exact format:\n"
                            "`Compare DRG No present or not between @file1.pdf and @file2.pdf`\n\n"
                            "If this still fails, open Sources and verify both PDFs are uploaded in the same thread."
                        )
                    }
            else:
                # Detect table search intent - STRICT: only for explicit part/drawing number queries
                is_table_search = False
                
                # Method 1: Explicit keywords for part/drawing numbers
                explicit_keywords = [
                    'drawing number', 'part number', 'drg number', 'item number',
                    'part no', 'drg no', 'drawing no', 'item no',
                    'p/n:', 'drg:', 'part#', 'drawing#'
                ]
                
                if any(keyword in query_lower for keyword in explicit_keywords):
                    print(f"[QUERY_ROUTING] Detected table search via explicit keyword")
                    is_table_search = True
                
                # Method 2: Explicit patterns like "find part number X" 
                if not is_table_search:
                    import re
                    table_specific_patterns = [
                        r'\b(find|search|look\s+for|get|show|what\s+is)\s+(the\s+)?(part|drawing|drg|item)\s+(number|no|#)',
                        r'\bpart\s+number\s*:',
                        r'\bdrawing\s+number\s*:',
                    ]
                    
                    for pattern in table_specific_patterns:
                        if re.search(pattern, query_lower):
                            print(f"[QUERY_ROUTING] Detected table search via pattern: {pattern}")
                            is_table_search = True
                            break
                
                # Method 3: Query looks like a code (VERY specific)
                # Only match if: has both letters and digits, follows typical part number format
                # Examples: ABC-123, 12A-456B, P/N-12345
                if not is_table_search:
                    code_pattern = r'\b([A-Z]{1,4}[-/]?\d{2,}[A-Z]?|[A-Z]?\d{2,}[-/][A-Z]{1,4})\b'
                    import re
                    potential_codes = re.findall(code_pattern, query, re.IGNORECASE)
                    if potential_codes:
                        print(f"[QUERY_ROUTING] Detected table search via code pattern: {potential_codes}")
                        is_table_search = True
                
                # Log the routing decision
                if is_table_search:
                    print(f"[QUERY_ROUTING] → TABLE SEARCH selected for query: {query[:100]}")
                else:
                    print(f"[QUERY_ROUTING] → RAG SEARCH selected for query: {query[:100]}")
                
                if is_table_search:
                    # Extract search term and type
                    search_term, query_type = _extract_search_info(query)
                    print(f"[TABLE_SEARCH] Detected search - Term: '{search_term}', Type: {query_type}")
                    
                    if search_term:
                        # Get PDF files from thread documents
                        docs = Document.objects.filter(thread=thread, filename__iendswith='.pdf')
                        print(f"[TABLE_SEARCH] Found {docs.count()} PDF(s) in thread")
                        
                        for doc in docs:
                            print(f"[TABLE_SEARCH] Checking {doc.filename}: exists={os.path.exists(doc.file.path)}")
                            if os.path.exists(doc.file.path):
                                try:
                                    print(f"[TABLE_SEARCH] Searching in {doc.filename}...")
                                    search_result = search_in_pdf(doc.file.path, search_term, query_type)
                                    print(f"[TABLE_SEARCH] Result: found={search_result.get('found')}, matches={search_result.get('total_matches', 0)}")
                                    
                                    if search_result.get('found'):
                                        table_search_result = search_result
                                        print(f"[TABLE_SEARCH] Using pdfplumber search results!")
                                        break
                                except Exception as e:
                                    print(f"[TABLE_SEARCH] Error searching {doc.filename}: {e}")
                                    import traceback
                                    traceback.print_exc()
            
            # If table search found results, use that; otherwise use RAG
            if table_search_result and table_search_result.get('found'):
                print(f"[QUERY_ROUTING] Using TABLE SEARCH results")
                answer = _format_table_search_response(table_search_result)
                sources = [{'page': p} for p in table_search_result.get('pages_with_matches', [])]
                chunks = []
                confidence = 0.95
                confidence_label = 'High'
            else:
                # Run standard RAG query (default for all general questions)
                if table_search_result:
                    print(f"[QUERY_ROUTING] Table search found nothing, falling back to RAG")
                else:
                    print(f"[QUERY_ROUTING] Using RAG for semantic search")
                
                result = query_rag(
                    query,
                    current_thread_id=thread.id,
                    parent_thread_id=parent_id,
                    conversation_history=conversation_context
                )
                
                answer = result.get('answer') or result.get('response') or ""
                sources = result.get('sources', [])
                chunks = result.get('chunks', [])
                confidence = result.get('confidence', 0)
                confidence_label = result.get('confidence_label', '')
                suggested_questions = result.get('suggested_questions', [])
            
            processing_time = round(time.perf_counter() - start_time, 3)
            print(f"[API] Chat processing time: {processing_time}s")

            # Save AI message with metadata (including suggested questions)
            ai_msg = ChatMessage.objects.create(
                thread=thread,
                role='ai',
                content=answer,
                sources=sources,
                chunks=chunks,
                confidence=confidence,
                confidence_label=confidence_label
            )
            print(f"[CHAT] Saved AI message ID: {ai_msg.id}")
            print(f"[CHAT] Total messages in DB: {ChatMessage.objects.count()}")

            # Ensure all data is JSON serializable
            response_data = {
                "answer": answer,
                "sources": sources,
                "chunks": chunks,
                "confidence": confidence,
                "confidence_label": confidence_label,
                "processing_time_seconds": processing_time,
                "suggested_questions": suggested_questions  # NotebookLM-style follow-ups
            }

            return JsonResponse(response_data)

        except Exception as e:
            print(f"[ERROR] Chat endpoint error: {type(e).__name__}: {str(e)}")
            import traceback
            traceback.print_exc()
            return _server_error(e)

    return JsonResponse({'error': 'Method not allowed'}, status=405)


def _resolve_conversation_references(query: str, recent_messages, thread) -> str:
    """
    Resolve conversation references like 'this', 'that', 'compare' based on chat history.
    Makes queries context-aware for multi-turn conversations.
    """
    query_lower = query.lower().strip()
    
    # Check if query contains reference words that need context
    reference_patterns = [
        'this', 'that', 'these', 'those', 'them', 'it',
        'compare', 'now compare', 'compare this', 'compare that',
        'with', 'to', 'versus', 'vs', 'against'
    ]
    
    has_reference = any(pattern in query_lower for pattern in reference_patterns)
    
    if not has_reference or not recent_messages:
        return query
    
    # Analyze last few messages to understand context
    last_user_msg = None
    last_ai_msg = None
    
    for msg in reversed(recent_messages):
        if msg.role == 'user' and not last_user_msg:
            last_user_msg = msg
        elif msg.role == 'ai' and not last_ai_msg:
            last_ai_msg = msg
        if last_user_msg and last_ai_msg:
            break
    
    if not last_user_msg:
        return query
    
    # Detect if previous query was a list/extraction query
    prev_query = last_user_msg.content.lower()
    extracted_data_type = None
    source_file = None

    # Parse previous comparison context (column + files) for follow-up shorthand
    previous_column = None
    previous_files = []

    prev_files_at = re.findall(r'@([\w\-. ]+\.pdf)', prev_query, re.IGNORECASE)
    prev_files_plain = re.findall(r'([\w\-. ]+\.pdf)', prev_query, re.IGNORECASE)
    for f in prev_files_at + prev_files_plain:
        f_clean = f.strip()
        if f_clean and f_clean not in previous_files:
            previous_files.append(f_clean)

    col_patterns = [
        r'compare\s+column\s+([a-z0-9\s\./#_-]{2,80}?)\s+(?:between|in|for|with)\b',
        r'compare\s+([a-z0-9\s\./#_-]{2,80}?)\s+(?:between|in|for|with)\b',
    ]
    for p in col_patterns:
        m = re.search(p, prev_query)
        if m:
            candidate = m.group(1).strip(" .:-_")
            candidate = re.sub(r'\s+', ' ', candidate)
            if candidate and candidate not in {'this', 'that', 'these', 'those', 'contents'}:
                previous_column = candidate
                break
    
    # Extract what was listed/searched in previous query
    if 'list' in prev_query or 'show' in prev_query or 'get' in prev_query:
        # Extract data type
        if any(kw in prev_query for kw in ['sr.no', 'sr no', 'serial', 'sl.no']):
            extracted_data_type = 'sr.no'
        elif any(kw in prev_query for kw in ['part', 'part no', 'part number']):
            extracted_data_type = 'part numbers'
        elif any(kw in prev_query for kw in ['drg', 'drawing', 'dwg']):
            extracted_data_type = 'drawing numbers'
        elif any(kw in prev_query for kw in ['nomenclature', 'name', 'designation']):
            extracted_data_type = 'nomenclatures'
        
        # Extract source file using @filename pattern
        file_match = re.search(r'@([\w\-\.]+\.pdf)', prev_query)
        if file_match:
            source_file = file_match.group(1)
    
    # Build context-aware query
    resolved_query = query
    
    # Pattern 0: "compare this column ..." -> reuse previous compared column/files
    if 'compare' in query_lower and 'column' in query_lower and any(ref in query_lower for ref in ['this', 'that']):
        target_file_match = re.search(r'@([\w\-. ]+\.pdf)', query, re.IGNORECASE)
        target_file = target_file_match.group(1).strip() if target_file_match else None

        source_ctx = previous_files[0] if previous_files else None
        if not target_file and len(previous_files) >= 2:
            target_file = previous_files[1]

        # If target not explicit, try to infer another uploaded PDF
        if source_ctx and not target_file:
            ancestor_ids = get_ancestor_thread_ids(thread)
            if ancestor_ids:
                docs_qs = Document.objects.filter(
                    Q(thread=thread) | Q(thread_id__in=ancestor_ids),
                    filename__iendswith='.pdf'
                )
            else:
                docs_qs = Document.objects.filter(thread=thread, filename__iendswith='.pdf')
            alt = docs_qs.exclude(filename__icontains=source_ctx.replace('.pdf', '')).first()
            if alt:
                target_file = alt.filename

        if previous_column and source_ctx and target_file:
            if any(p in query_lower for p in ['any column', 'with contents', 'against contents', 'contents']):
                resolved_query = f"Compare {previous_column} between @{source_ctx} and @{target_file} with contents"
            else:
                resolved_query = f"Compare {previous_column} between @{source_ctx} and @{target_file}"
            return resolved_query

    # Pattern 1: "now compare this to @file.pdf" or "compare this to"
    if 'compare' in query_lower and any(ref in query_lower for ref in ['this', 'that', 'these', 'those']):
        if extracted_data_type and source_file:
            # Find the target file in current query
            target_file_match = re.search(r'@([\w\-\.]+\.pdf)', query)
            
            if target_file_match:
                target_file = target_file_match.group(1)
                resolved_query = f"Compare {extracted_data_type} from @{source_file} with {extracted_data_type} in @{target_file}"
            else:
                # No target file specified, try to infer from uploaded files
                docs = Document.objects.filter(thread=thread, filename__iendswith='.pdf').exclude(filename__icontains=source_file.replace('.pdf', ''))
                if docs.exists():
                    target_file = docs.first().filename
                    resolved_query = f"Compare {extracted_data_type} from @{source_file} with {extracted_data_type} in @{target_file}"
    
    # Pattern 2: "@file.pdf now compare this to" (target first, then reference)
    elif 'compare' in query_lower:
        file_match = re.search(r'@([\w\-\.]+\.pdf)', query)
        if file_match and extracted_data_type and source_file:
            target_file = file_match.group(1)
            resolved_query = f"Compare {extracted_data_type} from @{source_file} with {extracted_data_type} in @{target_file}"
    
    return resolved_query


def _extract_search_info(query: str) -> tuple:
    """
    Extract search term and query type from natural language query.
    Returns: (search_term, query_type)
    """
    query_lower = query.lower()
    
    # Determine query type
    if any(kw in query_lower for kw in ['drawing number', 'drg', 'drg.', 'drawing no']):
        query_type = 'drawing_number'
    elif any(kw in query_lower for kw in ['part number', 'part no', 'p/n', 'item number']):
        query_type = 'part_number'
    else:
        query_type = 'general'
    
    # Extract the search term using patterns
    patterns = [
        r'(?:for|find|search|match|lookup)\s+["\']?([A-Z0-9\-/\.]+)["\']?',
        r'["\']([A-Z0-9\-/\.]+)["\']',
        r'(?:number|no\.?|#)\s*:?\s*([A-Z0-9\-/\.]+)',
        r'\b([A-Z0-9]{5,})\b',  # Alphanumeric code with at least 5 chars
        r'\b(\d{10,})\b',  # Long numeric code
    ]
    
    for pattern in patterns:
        match = re.search(pattern, query, re.IGNORECASE)
        if match:
            return match.group(1).strip(), query_type
    
    # Fallback: take last word if it looks like a code
    words = query.split()
    for word in reversed(words):
        clean_word = word.strip('.,?!\'"')
        if len(clean_word) >= 5 and any(c.isdigit() for c in clean_word):
            return clean_word, query_type
    
    return None, query_type


def _extract_comparison_info(query: str, thread) -> Optional[dict]:
    """
    Extract comparison parameters from natural language query.
    
    Examples:
    - "Compare part numbers in mrls with ispl"
    - "Show differences between mrls and ispl drawing numbers"
    - "What parts are in mrls but not in ispl"
    
    Returns:
        Comparison result dictionary or None
    """
    from .table_search_engine import compare_pdfs
    
    query_lower = query.lower()
    
    # Determine comparison type
    if any(kw in query_lower for kw in [
        'present or not', 'present/not', 'found or not found', 'found or not',
        'similar', 'similarity', 'same', 'assessment', 'assess', 'confirm',
        'whether', 'in there or not', 'exists or not'
    ]):
        comparison_type = 'all'
    elif any(kw in query_lower for kw in ['difference', 'not in', 'missing', 'only in']):
        comparison_type = 'difference'
    elif any(kw in query_lower for kw in ['common', 'both', 'shared', 'in both']):
        comparison_type = 'common'
    elif any(kw in query_lower for kw in ['unique', 'unique to each', 'each']):
        comparison_type = 'unique_both'
    elif 'all' in query_lower or 'complete' in query_lower:
        comparison_type = 'all'
    else:
        # For generic "compare X between A and B" queries, users typically expect
        # full two-way assessment: common + missing on both sides.
        comparison_type = 'all'
    
    # Extract column name
    column_keywords = {
        'part': ['part number', 'part no', 'p/n', 'part'],
        'drg': ['drawing number', 'drg', 'drg no', 'drg. no', 'drawing no', 'dwg'],
        'nomenclature': ['nomenclature', 'name', 'description'],
        'nsn': ['nsn', 'national stock']
    }
    
    column_name = None
    for col_type, keywords in column_keywords.items():
        if any(kw in query_lower for kw in keywords):
            column_name = col_type
            break

    # Generic column parsing for queries like:
    # "compare firm part no between ..." or "compare column unit price ..."
    if not column_name:
        generic_patterns = [
            r'compare\s+column\s+([a-z0-9\s\./#_-]{2,80}?)\s+(?:between|in|for)\b',
            r'compare\s+([a-z0-9\s\./#_-]{2,80}?)\s+(?:between|in|for)\b',
            r'(?:check|assess|confirm)\s+([a-z0-9\s\./#_-]{2,80}?)\s+(?:present|found|between)\b',
        ]
        for pattern in generic_patterns:
            m = re.search(pattern, query_lower)
            if not m:
                continue
            candidate = m.group(1).strip(" .:-_")
            candidate = re.sub(r'\b(present|found|or|not|whether|exists|existence)\b', ' ', candidate)
            candidate = re.sub(r'\s+', ' ', candidate).strip()
            if len(candidate) >= 2 and candidate not in {'the', 'all', 'values', 'value', 'items', 'item'}:
                column_name = candidate
                break
    
    if not column_name:
        column_name = 'part'  # Backward-compatible default

    # Optional cross-column mapping (file1 column -> file2 column)
    # Example: MRLS "manufacturer part no" vs ISPL "drg no"
    column_name_pdf1 = column_name
    column_name_pdf2 = None

    if 'manufacturer part no' in query_lower and any(k in query_lower for k in ['drg', 'drawing', 'dwg']):
        column_name_pdf1 = 'manufacturer part no'
        column_name_pdf2 = 'drg'

    # Natural language mode: compare source column against ANY target column in second file.
    # Examples: "compare this column with contents", "match to any column of other pdf"
    match_any_column_in_pdf2 = any(
        phrase in query_lower
        for phrase in [
            'any column', 'to any column', 'with contents', 'against contents',
            'match in any column', 'compare this column'
        ]
    )
    
    # Get PDFs from thread (including inherited/ancestor docs)
    ancestor_ids = get_ancestor_thread_ids(thread)
    if ancestor_ids:
        docs = Document.objects.filter(
            Q(thread=thread) | Q(thread_id__in=ancestor_ids),
            filename__iendswith='.pdf'
        )
    else:
        docs = Document.objects.filter(thread=thread, filename__iendswith='.pdf')
    
    if docs.count() < 2:
        return None
    
    # Try to identify which PDFs to compare
    # Priority 1: Use categories if they match query keywords
    pdf1_doc = None
    pdf2_doc = None

    # Priority 0: Explicit @filename.pdf references in query
    mentioned_files = re.findall(r'@([\w\-. ]+\.pdf)', query, re.IGNORECASE)
    if len(mentioned_files) < 2:
        # Also support plain filenames without @, e.g. "between ISPL_Vol-I.pdf and ISPL_Vol-II.pdf"
        plain_files = re.findall(r'([\w\-. ]+\.pdf)', query, re.IGNORECASE)
        for pf in plain_files:
            if pf not in mentioned_files:
                mentioned_files.append(pf)
    if len(mentioned_files) >= 2:
        resolved_docs = []
        for mentioned in mentioned_files:
            mentioned_lower = mentioned.strip().lower()
            matched = next((d for d in docs if d.filename.lower() == mentioned_lower), None)
            if not matched:
                matched = next((d for d in docs if mentioned_lower in d.filename.lower()), None)
            if matched and matched not in resolved_docs:
                resolved_docs.append(matched)

        if len(resolved_docs) >= 2:
            pdf1_doc, pdf2_doc = resolved_docs[0], resolved_docs[1]
    
    # Check for category-based matching first
    category_patterns = {
        'mrls': ['mrls', 'mrl', 'maintenance', 'repair'],
        'ispl': ['ispl', 'isp', 'spare', 'parts list'],
        'manual': ['manual', 'handbook', 'guide'],
        'catalog': ['catalog', 'catalogue'],
        'specification': ['spec', 'specification'],
        'drawing': ['drawing', 'dwg']
    }
    
    # Try to find documents by category mentioned in query
    for category, patterns in category_patterns.items():
        if any(p in query_lower for p in patterns):
            matching_docs = [d for d in docs if d.category == category]
            if matching_docs:
                for doc in matching_docs:
                    if not pdf1_doc:
                        pdf1_doc = doc
                    elif not pdf2_doc and doc != pdf1_doc:
                        pdf2_doc = doc
                    if pdf1_doc and pdf2_doc:
                        break
    
    # Priority 2: Match by filename patterns
    if not pdf1_doc or not pdf2_doc:
        for doc in docs:
            filename_lower = doc.filename.lower()
            
            # MRLS patterns
            if not pdf1_doc and any(p in filename_lower for p in ['mrls', 'mrl']):
                pdf1_doc = doc
            # ISPL patterns
            elif not pdf2_doc and any(p in filename_lower for p in ['ispl', 'isp']):
                pdf2_doc = doc
    
    # Priority 3: Use first two PDFs if still not found
    if not pdf1_doc or not pdf2_doc:
        doc_list = list(docs)
        if len(doc_list) >= 2:
            pdf1_doc = pdf1_doc or doc_list[0]
            pdf2_doc = pdf2_doc or doc_list[1] if doc_list[1] != pdf1_doc else (doc_list[2] if len(doc_list) > 2 else None)
    
    if not pdf1_doc or not pdf2_doc:
        return None

    try:
        # Preferred path: compare using persisted structured tables in DB.
        # This is robust even if source files were deleted after vectorization.
        thread_ids = [str(thread.id)] + [str(tid) for tid in get_ancestor_thread_ids(thread)]
        # If categories indicate MRLS/ISPL with mapped columns, align direction explicitly.
        if column_name_pdf2 and pdf1_doc.category == 'ispl' and pdf2_doc.category == 'mrls':
            left_doc, right_doc = pdf2_doc, pdf1_doc
            left_col, right_col = column_name_pdf1, column_name_pdf2
        else:
            left_doc, right_doc = pdf1_doc, pdf2_doc
            left_col, right_col = column_name_pdf1, column_name_pdf2

        result = compare_structured_sources(
            left_doc.filename,
            right_doc.filename,
            left_col,
            column_name_pdf2=right_col,
            match_any_column_in_pdf2=match_any_column_in_pdf2,
            comparison_type=comparison_type,
            doc1_id=str(left_doc.id),
            doc2_id=str(right_doc.id),
            thread_ids=thread_ids,
        )

        # Fallback: if structured tables are unavailable, use file-based comparison.
        if not result.get('found'):
            if os.path.exists(left_doc.file.path) and os.path.exists(right_doc.file.path):
                result = compare_pdfs(
                    left_doc.file.path,
                    right_doc.file.path,
                    left_col,
                    column_name_pdf2=right_col,
                    match_any_column_in_pdf2=match_any_column_in_pdf2,
                    comparison_type=comparison_type,
                )
            else:
                missing_files = []
                if not os.path.exists(left_doc.file.path):
                    missing_files.append(left_doc.filename)
                if not os.path.exists(right_doc.file.path):
                    missing_files.append(right_doc.filename)
                missing_text = ', '.join(missing_files)
                return {
                    'found': True,
                    'formatted_answer': (
                        "## ❌ Assessment Could Not Be Completed\n\n"
                        "Structured tables are not available and source PDF file(s) are missing:\n"
                        f"- {missing_text}\n\n"
                        "Please re-upload and reprocess these files, then run:\n"
                        "`Compare DRG No present or not between @file1.pdf and @file2.pdf`"
                    )
                }
        
        if result.get('found'):
            # Format the result
            result['formatted_answer'] = _format_comparison_response(result)
            
            # Generate Excel report
            excel_bytes = generate_comparison_excel(result)
            job_id = store_comparison_report('Comparison_Report', result, excel_bytes)
            
            # Add download link to formatted answer
            result['formatted_answer'] += f"\n\n---\n\n📥 **[Download Excel Report](/api/reports/download/{job_id}/)**"
            result['report_job_id'] = job_id
            
            return result

        # Structured comparison could not locate requested column(s)
        error_text = result.get('error') if isinstance(result, dict) else None
        if error_text:
            cols1 = ', '.join(result.get('available_columns_pdf1', [])[:20])
            cols2 = ', '.join(result.get('available_columns_pdf2', [])[:20])
            return {
                'found': True,
                'formatted_answer': (
                    "## ❌ Column Not Found for Comparison\n\n"
                    f"Requested column: **{column_name}**\n\n"
                    f"{error_text}\n\n"
                    f"**{pdf1_doc.filename} columns:** {cols1 or 'N/A'}\n\n"
                    f"**{pdf2_doc.filename} columns:** {cols2 or 'N/A'}\n\n"
                    "Try using one of the exact header names above in your query."
                )
            }
    except Exception as e:
        print(f"[COMPARISON] Error: {e}")
        import traceback
        traceback.print_exc()
    
    return None


def _format_comparison_response(comparison_result: dict) -> str:
    """Format comparison results as natural QA-style structured answer."""
    summary = comparison_result.get('summary', '')
    pdf1 = comparison_result.get('pdf1', 'PDF 1')
    pdf2 = comparison_result.get('pdf2', 'PDF 2')
    column = comparison_result.get('column', 'items')
    pdf1_total = comparison_result.get('pdf1_total', 0)
    pdf2_total = comparison_result.get('pdf2_total', 0)
    
    results_data = comparison_result.get('results', {})

    missing_count = results_data.get('in_pdf1_only', {}).get('count', 0)
    common_count = results_data.get('common', {}).get('count', 0)
    verdict = "PASS" if missing_count == 0 else "FAIL"
    
    # Start with clear natural language answer
    response = f"## 📊 QA Comparison: {pdf1} vs {pdf2}\n\n"

    # Assessment verdict (explicit yes/no style)
    response += "### ✅ Assessment Verdict\n\n" if verdict == "PASS" else "### ❌ Assessment Verdict\n\n"
    if verdict == "PASS":
        response += f"**{verdict}:** All {column} values from {pdf1} are present in {pdf2}.\n\n"
    else:
        response += (
            f"**{verdict}:** {missing_count} {column} value(s) from {pdf1} are NOT present in {pdf2}.\n\n"
        )

    if common_count:
        response += f"**Matched in both files:** {common_count}\n\n"

    response += "---\n\n"
    
    # Executive Summary
    response += f"**Column Compared:** {column}\n\n"
    
    # Key Findings
    response += "### 🎯 Key Findings:\n\n"
    
    if 'in_pdf1_only' in results_data:
        missing_count = results_data['in_pdf1_only']['count']
        if missing_count > 0:
            percentage = (missing_count / pdf1_total * 100) if pdf1_total > 0 else 0
            response += f"❌ **{missing_count} items** from {pdf1} are **NOT found** in {pdf2} ({percentage:.1f}%)\n\n"
        else:
            response += f"✅ **All items** from {pdf1} are present in {pdf2}\n\n"
    
    if 'common' in results_data:
        common_count = results_data['common']['count']
        if common_count > 0:
            percentage = (common_count / pdf1_total * 100) if pdf1_total > 0 else 0
            response += f"✅ **{common_count} items** are **common** to both files ({percentage:.1f}%)\n\n"
    
    if 'in_pdf2_only' in results_data:
        extra_count = results_data['in_pdf2_only']['count']
        if extra_count > 0:
            response += f"❌ **{extra_count} items** from {pdf2} are **NOT found** in {pdf1}\n\n"
    
    response += "---\n\n"
    
    # Detailed Missing Items
    if 'in_pdf1_only' in results_data and results_data['in_pdf1_only']['count'] > 0:
        response += f"### ❌ Missing from {pdf2} (found in {pdf1} only)\n\n"
        response += f"**Total Missing:** {results_data['in_pdf1_only']['count']}\n\n"
        
        rows = results_data['in_pdf1_only'].get('rows', [])[:10]
        
        for i, row in enumerate(rows, 1):
            value = row.get('_matched_value', 'N/A')
            page = row.get('_page', 'Unknown')
            
            response += f"**{i}. `{value}`** _(from page {page})_\n"
            
            # Show nomenclature or description if available
            fields = []
            for key, val in row.items():
                if not key.startswith('_') and val and str(val).strip():
                    key_lower = key.lower()
                    if any(kw in key_lower for kw in ['nomenclature', 'designation', 'description', 'name']):
                        fields.append(f"**{key}:** {val}")
            
            if fields:
                response += "   " + " | ".join(fields[:2]) + "\n"
            response += "\n"
        
        if results_data['in_pdf1_only']['count'] > 10:
            response += f"_... and {results_data['in_pdf1_only']['count'] - 10} more missing items_\n\n"
        
        response += "---\n\n"
    
    # Common Items Summary
    if 'common' in results_data and results_data['common']['count'] > 0:
        response += f"### ✅ Common Items (verified in both)\n\n"
        response += f"**Total Verified:** {results_data['common']['count']} items\n\n"
        
        values = results_data['common'].get('values', [])[:20]
        if len(values) <= 10:
            # Show all if <=10
            for v in values:
                response += f"- `{v}`\n"
        else:
            # Show first 5 and indicate more
            for v in values[:5]:
                response += f"- `{v}`\n"
            response += f"\n_... and {results_data['common']['count'] - 5} more verified items_\n"
        
        response += "\n---\n\n"
    
    # Items missing from PDF1 (found only in PDF2)
    if 'in_pdf2_only' in results_data and results_data['in_pdf2_only']['count'] > 0:
        response += f"### ❌ Missing from {pdf1} (found in {pdf2} only)\n\n"
        response += f"**Total Missing:** {results_data['in_pdf2_only']['count']}\n\n"

        rows = results_data['in_pdf2_only'].get('rows', [])[:10]
        if rows:
            for i, row in enumerate(rows, 1):
                value = row.get('_matched_value', 'N/A')
                page = row.get('_page', 'Unknown')
                response += f"**{i}. `{value}`** _(from page {page})_\n"

                fields = []
                for key, val in row.items():
                    if not key.startswith('_') and val and str(val).strip():
                        key_lower = key.lower()
                        if any(kw in key_lower for kw in ['nomenclature', 'designation', 'description', 'name']):
                            fields.append(f"**{key}:** {val}")

                if fields:
                    response += "   " + " | ".join(fields[:2]) + "\n"
                response += "\n"
        else:
            values = results_data['in_pdf2_only'].get('values', [])[:10]
            for v in values:
                response += f"- `{v}`\n"

        if results_data['in_pdf2_only']['count'] > 10:
            response += f"\n_... and {results_data['in_pdf2_only']['count'] - 10} more missing items_\n"
        
        response += "\n---\n\n"
    
    # Recommendations
    response += "### 💡 Quality Check Summary:\n\n"
    
    if 'in_pdf1_only' in results_data and results_data['in_pdf1_only']['count'] > 0:
        response += f"⚠️ **Action Required:** {results_data['in_pdf1_only']['count']} spare parts from {pdf1} need to be verified in {pdf2}\n"
    else:
        response += f"✅ **Quality OK:** All parts are properly cross-referenced\n"
    
    return response


def _format_table_search_response(search_result: dict) -> str:
    """Format table search results as readable text with better structure."""
    # Check if this is a comparison result
    if 'formatted_answer' in search_result:
        return search_result['formatted_answer']
    
    summary = search_result.get('summary_text', '')
    results = search_result.get('results', [])
    search_term = search_result.get('search_term', '')
    query_type = search_result.get('query_type', 'general')
    
    if not results:
        return summary or f"No matches found for '{search_term}'."
    
    # Generate structured response
    total = len(results)
    pages = sorted(set(r.get('page', 0) for r in results if r.get('page')))
    
    response = f"# 🔍 Search Results\n\n"
    response += f"**Search Term:** `{search_term}`\n"
    response += f"**Search Type:** {query_type.replace('_', ' ').title()}\n"
    response += f"**Matches Found:** {total}\n"
    response += f"**Pages:** {', '.join(map(str, pages[:10]))}"
    if len(pages) > 10:
        response += f" ... (+{len(pages) - 10} more)"
    response += "\n\n---\n\n"
    
    # Show detailed results
    for i, result in enumerate(results[:12], 1):
        row_data = result.get('row_data', {})
        page = result.get('page')
        
        response += f"## Match {i}"
        if page:
            response += f" _(Page {page})_"
        response += "\n\n"
        
        # Show relevant fields in a structured way
        important_fields = []
        other_fields = []
        
        for key, value in row_data.items():
            if value and str(value).strip():
                clean_key = key.strip()
                clean_value = str(value).strip()
                
                # Prioritize important columns
                if any(kw in clean_key.lower() for kw in ['part', 'drg', 'drawing', 'nsn', 'nomenclature']):
                    important_fields.append((clean_key, clean_value))
                else:
                    other_fields.append((clean_key, clean_value))
        
        # Display important fields first
        for key, value in important_fields:
            response += f"- **{key}:** `{value}`\n"
        
        # Then show other fields (limit to 5 total)
        for key, value in other_fields[:max(0, 5 - len(important_fields))]:
            response += f"- **{key}:** {value}\n"
        
        response += "\n"
    
    if total > 12:
        response += f"---\n\n_... and {total - 12} more matches_\n\n"
    
    response += "---\n"
    response += "_💡 Tip: Refine your search or ask for specific details about any item!_"
    
    return response


def _format_conflict_response(conflict_result: dict) -> str:
    """Format conflict detection results as natural QA-style answer."""
    summary = conflict_result.get('summary', '')
    part_conflicts = conflict_result.get('part_number_conflicts', [])
    nom_conflicts = conflict_result.get('nomenclature_conflicts', [])
    
    response = summary + "\n"
    
    # Part Number Conflicts (same part with different nomenclatures)
    if part_conflicts:
        response += "\n### ⚠️ Part Number Conflicts\n"
        response += "_Same part number is used for different nomenclatures:_\n\n"
        
        for i, conflict in enumerate(part_conflicts[:15], 1):
            part = conflict['part_number']
            nomenclatures = conflict['nomenclatures']
            sources = conflict['sources']
            
            response += f"**{i}. Part: `{part}`** has {len(nomenclatures)} different nomenclatures:\n"
            
            for j, nom in enumerate(nomenclatures, 1):
                # Find source info for this nomenclature
                source_info = [s for s in sources if s['nomenclature'] == nom]
                if source_info:
                    src = source_info[0]
                    source_text = f"{src['source']}"
                    if 'page' in src:
                        source_text += f" (Page {src['page']})"
                    response += f"   {j}. {nom} _{source_text}_\n"
                else:
                    response += f"   {j}. {nom}\n"
            
            response += "\n"
        
        if len(part_conflicts) > 15:
            response += f"_... and {len(part_conflicts) - 15} more conflicts_\n\n"
    
    # Nomenclature Conflicts (same nomenclature with different parts)
    if nom_conflicts:
        response += "\n### ⚠️ Nomenclature Conflicts\n"
        response += "_Same nomenclature is used for different part numbers:_\n\n"
        
        for i, conflict in enumerate(nom_conflicts[:15], 1):
            nomenclature = conflict['nomenclature']
            parts = conflict['part_numbers']
            sources = conflict['sources']
            
            response += f"**{i}. Nomenclature: \"{nomenclature}\"** has {len(parts)} different parts:\n"
            
            for j, part in enumerate(parts, 1):
                # Find source info for this part
                source_info = [s for s in sources if s['part'] == part]
                if source_info:
                    src = source_info[0]
                    source_text = f"{src['source']}"
                    if 'page' in src:
                        source_text += f" (Page {src['page']})"
                    response += f"   {j}. `{part}` _{source_text}_\n"
                else:
                    response += f"   {j}. `{part}`\n"
            
            response += "\n"
        
        if len(nom_conflicts) > 15:
            response += f"_... and {len(nom_conflicts) - 15} more conflicts_\n\n"
    
    # Add recommendations
    if part_conflicts or nom_conflicts:
        response += "\n---\n\n"
        response += "### 📋 Recommended Actions:\n"
        if part_conflicts:
            response += "- **Part Number Conflicts:** Review and standardize nomenclatures for affected parts\n"
        if nom_conflicts:
            response += "- **Nomenclature Conflicts:** Verify if these are truly different parts or need unique nomenclatures\n"
        response += "\n_💡 These conflicts may indicate data entry errors or actual design variations._"
    
    return response


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
        return _server_error(e, 'Delete failed')

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
        return _server_error(e, 'Delete failed')


# ==================== DOCUMENT METADATA ENDPOINTS ====================

@require_http_methods(["GET"])
def document_progress(request, doc_id):
    """
    Poll the ingestion progress of a single document.
    Returns: {doc_id, status, progress (0-100), progress_detail, error_message}
    """
    try:
        doc = get_object_or_404(Document, id=doc_id)
        return JsonResponse({
            "doc_id":          str(doc.id),
            "filename":        doc.filename,
            "status":          doc.status,
            "progress":        doc.progress,
            "progress_detail": doc.progress_detail,
            "error_message":   "Processing failed" if doc.error_message else None,
        })
    except Exception as e:
        return _server_error(e)


@csrf_exempt
@require_http_methods(["PATCH", "GET"])
def document_metadata(request, doc_id):
    """Update or get document metadata (tags, notes, version, revision_date)"""
    try:
        doc = get_object_or_404(Document, id=doc_id)
        
        if request.method == "GET":
            return JsonResponse({
                'id': str(doc.id),
                'filename': doc.filename,
                'tags': doc.tags or [],
                'notes': doc.notes or '',
                'version': doc.version or '',
                'revision_date': doc.revision_date.isoformat() if doc.revision_date else None,
                'previous_version_id': str(doc.previous_version.id) if doc.previous_version else None,
                'category': doc.category
            })
        
        # PATCH request
        data = json.loads(request.body)
        
        # Update fields if provided
        if 'tags' in data:
            doc.tags = data['tags']  # Expecting a list of strings
        
        if 'notes' in data:
            doc.notes = data['notes']
        
        if 'version' in data:
            doc.version = data['version']
        
        if 'revision_date' in data:
            from django.utils import timezone
            from datetime import datetime
            if data['revision_date']:
                # Parse ISO format date string
                doc.revision_date = datetime.fromisoformat(data['revision_date'].replace('Z', '+00:00'))
            else:
                doc.revision_date = None
        
        doc.save()
        
        return JsonResponse({
            'message': 'Document metadata updated successfully',
            'document': {
                'id': str(doc.id),
                'filename': doc.filename,
                'tags': doc.tags,
                'notes': doc.notes,
                'version': doc.version,
                'revision_date': doc.revision_date.isoformat() if doc.revision_date else None
            }
        })
        
    except json.JSONDecodeError:
        return JsonResponse({'error': 'Invalid JSON'}, status=400)
    except Exception as e:
        import traceback
        traceback.print_exc()
        return _server_error(e, 'Metadata update failed')


@csrf_exempt
@require_http_methods(["POST"])
def link_document_version(request, doc_id):
    """Link this document as a new version of another document"""
    try:
        doc = get_object_or_404(Document, id=doc_id)
        data = json.loads(request.body)
        
        previous_version_id = data.get('previous_version_id')
        if not previous_version_id:
            return JsonResponse({'error': 'previous_version_id is required'}, status=400)
        
        previous_doc = get_object_or_404(Document, id=previous_version_id)
        
        # Link the versions
        doc.previous_version = previous_doc
        doc.save()
        
        return JsonResponse({
            'message': 'Document versions linked successfully',
            'current': str(doc.id),
            'previous': str(previous_doc.id),
            'previous_filename': previous_doc.filename
        })
        
    except json.JSONDecodeError:
        return JsonResponse({'error': 'Invalid JSON'}, status=400)
    except Exception as e:
        import traceback
        traceback.print_exc()
        return _server_error(e, 'Version linking failed')


@csrf_exempt
@require_http_methods(["GET"])
def document_version_history(request, doc_id):
    """Get the version history chain for a document"""
    try:
        doc = get_object_or_404(Document, id=doc_id)
        
        # Build version chain (backwards to oldest)
        versions = []
        current = doc
        visited = set()  # Prevent infinite loops
        
        while current and str(current.id) not in visited:
            visited.add(str(current.id))
            versions.append({
                'id': str(current.id),
                'filename': current.filename,
                'version': current.version or '',
                'revision_date': current.revision_date.isoformat() if current.revision_date else None,
                'uploaded_at': current.uploaded_at.isoformat(),
                'tags': current.tags or [],
                'notes': current.notes or '',
                'is_current': current.id == doc.id
            })
            current = current.previous_version
        
        # Also get newer versions (documents that point to this one)
        newer_versions = Document.objects.filter(previous_version=doc).values(
            'id', 'filename', 'version', 'revision_date', 'uploaded_at', 'tags', 'notes'
        )
        
        newer_list = []
        for newer in newer_versions:
            newer_list.append({
                'id': str(newer['id']),
                'filename': newer['filename'],
                'version': newer['version'] or '',
                'revision_date': newer['revision_date'].isoformat() if newer['revision_date'] else None,
                'uploaded_at': newer['uploaded_at'].isoformat(),
                'tags': newer['tags'] or [],
                'notes': newer['notes'] or '',
                'is_current': False
            })
        
        return JsonResponse({
            'current_document_id': str(doc.id),
            'previous_versions': versions[1:] if len(versions) > 1 else [],  # Exclude current doc
            'newer_versions': newer_list,
            'total_versions': len(versions) + len(newer_list)
        })
        
    except Exception as e:
        import traceback
        traceback.print_exc()
        return _server_error(e, 'Version history retrieval failed')


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
        return _server_error(e)


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
        return _server_error(e)


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
        return _server_error(e)


@csrf_exempt
def summarize_single_document(request, doc_id):
    """Generate an AI summary of a specific document"""
    if request.method != "GET":
        return JsonResponse({"error": "GET method required"}, status=405)

    print(f"\n[API] Summarize single document: {doc_id}")

    try:
        result = summarize_document(doc_id=doc_id)

        if "error" in result:
            print(f"[API] Summarization error: {result['error']}")
            return JsonResponse(result, status=500)

        if not result.get("chunk_count"):
            return JsonResponse({"error": "Document not found or not yet indexed."}, status=404)

        # Attach filename — prefer Django DB, fall back to ChromaDB source metadata
        try:
            doc = Document.objects.get(id=doc_id)
            result["filename"] = doc.filename
        except (Document.DoesNotExist, Exception):
            sources = result.get("sources", [])
            result["filename"] = sources[0].split(" (Page")[0] if sources else "Unknown"

        return JsonResponse(result)

    except Exception as e:
        print(f"[API] Exception in summarize_single_document: {e}")
        import traceback
        traceback.print_exc()
        return _server_error(e)


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
        return _server_error(e)


# ==================== MODEL CONFIGURATION ENDPOINTS ====================

@csrf_exempt
def model_status(request):
    """Get current embedding model status"""
    if request.method != "GET":
        return JsonResponse({"error": "GET method required"}, status=405)

    try:
        status = get_model_status()
        # Also get saved configuration from DB
        provider = AppConfig.get_value('embedding_provider', 'sentence-transformers')
        saved_path = AppConfig.get_value('embedding_model_path', None)
        ollama_model = AppConfig.get_value('ollama_embedding_model', 'nomic-embed-text')
        
        status['saved_path'] = saved_path
        status['provider'] = status.get('provider', provider)
        status['ollama_model'] = ollama_model
        
        return JsonResponse(status)
    except Exception as e:
        return _server_error(e)


@csrf_exempt
def embedding_provider_configure(request):
    """Configure the embedding provider (sentence-transformers or Ollama)"""
    if request.method != "POST":
        return JsonResponse({"error": "POST method required"}, status=405)

    try:
        data = json.loads(request.body)
        provider_type = data.get('provider', '').strip().lower()
        model = data.get('model', '').strip()

        if not provider_type:
            return JsonResponse({"error": "Provider type is required (sentence-transformers or ollama)"}, status=400)

        if not model:
            return JsonResponse({"error": "Model path or name is required"}, status=400)

        from .rag_engine import configure_embedding_provider

        # Snapshot old collection before model switches (dimension may change)
        old_collection = get_collection()
        old_collection_name = old_collection.name

        result = configure_embedding_provider(provider_type, model)

        if result.get('success'):
            reembed_started = False
            if result.get('reembed_needed'):
                new_collection = get_collection()
                if new_collection.name != old_collection_name:
                    old_model = result.get('old_dim', '?')
                    new_model = model
                    t = threading.Thread(
                        target=reembed_collection,
                        args=(old_collection, new_collection, str(old_model), new_model),
                        daemon=True,
                    )
                    t.start()
                    reembed_started = True

            return JsonResponse({
                "message": f"Embedding provider configured successfully: {provider_type}",
                "status": result.get('status', {}),
                "provider": result.get('provider'),
                "model": result.get('model'),
                "reembed_started": reembed_started,
            })
        else:
            return JsonResponse({
                "error": result.get('error', 'Unknown error'),
                "status": result.get('status', {})
            }, status=400)

    except json.JSONDecodeError:
        return JsonResponse({"error": "Invalid JSON"}, status=400)
    except Exception as e:
        return _server_error(e)


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
        return _server_error(e)


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
        return _server_error(e)


def reembed_status(request):
    """Poll the progress of a background re-embed job triggered by a model switch."""
    if request.method != "GET":
        return JsonResponse({"error": "GET method required"}, status=405)
    try:
        state = get_reembed_status()
        pct = 0
        if state["total"] > 0:
            pct = round(state["done"] / state["total"] * 100)
        return JsonResponse({
            "running":   state["running"],
            "total":     state["total"],
            "done":      state["done"],
            "progress":  pct,
            "error":     state["error"],
            "old_model": state["old_model"],
            "new_model": state["new_model"],
        })
    except Exception as e:
        return _server_error(e)


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
        return _server_error(e)


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
        return _server_error(e)


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
        return _server_error(e)


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
        return _server_error(e)


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
        return _server_error(e)


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
        return _server_error(e)


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
def get_multi_pdf_columns_preview(request):
    """
    Get columns and preview from multiple PDFs - merges tables with matching columns.
    
    POST /api/reports/multi-pdf-columns/
    - pdf_files[]: Multiple PDF files to analyze
    - use_ocr: Optional, enable OCR (default: true)
    
    Returns: {"columns": [...], "preview": {"col1": ["val1", ...], ...}}
    """
    if request.method != "POST":
        return JsonResponse({"error": "POST method required"}, status=405)
    
    # Get PDF files
    pdf_files = request.FILES.getlist("pdf_files")
    if not pdf_files or len(pdf_files) == 0:
        return JsonResponse({"error": "At least one PDF file is required"}, status=400)
    
    # Get OCR option (default to True for multi-PDF)
    use_ocr_param = request.POST.get("use_ocr", "true").lower()
    use_ocr = use_ocr_param == "true"
    
    print(f"[MultiPDF Columns] Processing {len(pdf_files)} PDFs with OCR={use_ocr}")
    
    try:
        # Save PDF files temporarily
        pdf_paths = []
        for pdf_file in pdf_files:
            pdf_ext = os.path.splitext(pdf_file.name)[1].lower()
            with tempfile.NamedTemporaryFile(delete=False, suffix=pdf_ext) as f:
                for chunk in pdf_file.chunks():
                    f.write(chunk)
                pdf_paths.append(f.name)
        
        # Get columns with preview - merged across all PDFs
        result = get_multi_pdf_columns_with_preview(pdf_paths, preview_count=10)
        
        # Cleanup temp files
        for pdf_path in pdf_paths:
            try:
                os.unlink(pdf_path)
            except:
                pass
        
        return JsonResponse(result)
        
    except Exception as e:
        import traceback
        traceback.print_exc()
        return _server_error(e)


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
        return _server_error(e)


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
        return _server_error(e)


# In-memory storage for comparison reports
_comparison_reports = {}

def store_comparison_report(report_type: str, result: dict, excel_bytes: bytes) -> str:
    """Store comparison report and return job_id for download."""
    job_id = str(uuid.uuid4())
    _comparison_reports[job_id] = {
        'status': 'completed',
        'created_at': datetime.now().isoformat(),
        'report_type': report_type,
        'result': result,
        'excel_bytes': excel_bytes,
        'filename': f"{report_type}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx"
    }
    return job_id

def generate_comparison_excel(comparison_result: dict) -> bytes:
    """Generate Excel report from comparison results."""
    import openpyxl
    from openpyxl.styles import Font, PatternFill, Alignment
    
    wb = openpyxl.Workbook()
    wb.remove(wb.active)  # Remove default sheet
    
    # Sheet 1: Summary
    summary_sheet = wb.create_sheet("Summary")
    summary_sheet['A1'] = 'Comparison Report'
    summary_sheet['A1'].font = Font(size=16, bold=True)
    
    summary_sheet['A3'] = 'Files Compared:'
    summary_sheet['A3'].font = Font(bold=True)
    summary_sheet['B3'] = comparison_result.get('pdf1', 'File 1')
    summary_sheet['A4'] = ''  
    summary_sheet['B4'] = comparison_result.get('pdf2', 'File 2')
    
    summary_sheet['A6'] = 'Column:'
    summary_sheet['A6'].font = Font(bold=True)
    summary_sheet['B6'] = comparison_result.get('column', 'N/A')
    
    summary_sheet['A8'] = 'Total in File 1:'
    summary_sheet['B8'] = comparison_result.get('pdf1_total', 0)
    summary_sheet['A9'] = 'Total in File 2:'
    summary_sheet['B9'] = comparison_result.get('pdf2_total', 0)
    
    results_data = comparison_result.get('results', {})
    
    row = 11
    if 'in_pdf1_only' in results_data:
        count = results_data['in_pdf1_only']['count']
        summary_sheet[f'A{row}'] = 'Missing from File 2:'
        summary_sheet[f'A{row}'].font = Font(bold=True, color='FF0000')
        summary_sheet[f'B{row}'] = count
        row += 1
    
    if 'common' in results_data:
        count = results_data['common']['count']
        summary_sheet[f'A{row}'] = 'Common (in both):'
        summary_sheet[f'A{row}'].font = Font(bold=True, color='008000')
        summary_sheet[f'B{row}'] = count
        row += 1
    
    if 'in_pdf2_only' in results_data:
        count = results_data['in_pdf2_only']['count']
        summary_sheet[f'A{row}'] = 'Missing from File 1:'
        summary_sheet[f'A{row}'].font = Font(bold=True, color='0000FF')
        summary_sheet[f'B{row}'] = count
    
    # Sheet 2: Missing Items
    if 'in_pdf1_only' in results_data and results_data['in_pdf1_only']['count'] > 0:
        missing_sheet = wb.create_sheet("Missing from File 2")
        missing_sheet['A1'] = f"Items in {comparison_result.get('pdf1')} NOT found in {comparison_result.get('pdf2')}"
        missing_sheet['A1'].font = Font(size=14, bold=True)
        missing_sheet['A1'].fill = PatternFill(start_color='FFCCCC', end_color='FFCCCC', fill_type='solid')
        
        rows = results_data['in_pdf1_only'].get('rows', [])
        if rows:
            # Headers
            headers = [k for k in rows[0].keys() if not k.startswith('_')]
            for col_idx, header in enumerate(headers, 1):
                cell = missing_sheet.cell(row=3, column=col_idx)
                cell.value = header
                cell.font = Font(bold=True)
                cell.fill = PatternFill(start_color='E0E0E0', end_color='E0E0E0', fill_type='solid')
            
            # Data
            for row_idx, row_data in enumerate(rows, 4):
                for col_idx, header in enumerate(headers, 1):
                    missing_sheet.cell(row=row_idx, column=col_idx, value=row_data.get(header, ''))
        else:
            values = results_data['in_pdf1_only'].get('values', [])
            missing_sheet['A3'] = comparison_result.get('column', 'Value')
            missing_sheet['A3'].font = Font(bold=True)
            for row_idx, value in enumerate(values, 4):
                missing_sheet[f'A{row_idx}'] = value

    # Sheet 2B: Missing from File 1 (items only in File 2)
    if 'in_pdf2_only' in results_data and results_data['in_pdf2_only']['count'] > 0:
        missing_sheet_2 = wb.create_sheet("Missing from File 1")
        missing_sheet_2['A1'] = f"Items in {comparison_result.get('pdf2')} NOT found in {comparison_result.get('pdf1')}"
        missing_sheet_2['A1'].font = Font(size=14, bold=True)
        missing_sheet_2['A1'].fill = PatternFill(start_color='CCE5FF', end_color='CCE5FF', fill_type='solid')

        rows = results_data['in_pdf2_only'].get('rows', [])
        if rows:
            headers = [k for k in rows[0].keys() if not k.startswith('_')]
            for col_idx, header in enumerate(headers, 1):
                cell = missing_sheet_2.cell(row=3, column=col_idx)
                cell.value = header
                cell.font = Font(bold=True)
                cell.fill = PatternFill(start_color='E0E0E0', end_color='E0E0E0', fill_type='solid')

            for row_idx, row_data in enumerate(rows, 4):
                for col_idx, header in enumerate(headers, 1):
                    missing_sheet_2.cell(row=row_idx, column=col_idx, value=row_data.get(header, ''))
        else:
            values = results_data['in_pdf2_only'].get('values', [])
            missing_sheet_2['A3'] = comparison_result.get('column', 'Value')
            missing_sheet_2['A3'].font = Font(bold=True)
            for row_idx, value in enumerate(values, 4):
                missing_sheet_2[f'A{row_idx}'] = value
    
    # Sheet 3: Common Items
    if 'common' in results_data and results_data['common']['count'] > 0:
        common_sheet = wb.create_sheet("Common Items")
        common_sheet['A1'] = "Items Found in Both Files"
        common_sheet['A1'].font = Font(size=14, bold=True)
        common_sheet['A1'].fill = PatternFill(start_color='CCFFCC', end_color='CCFFCC', fill_type='solid')
        
        values = results_data['common'].get('values', [])
        common_sheet['A3'] = comparison_result.get('column', 'Value')
        common_sheet['A3'].font = Font(bold=True)
        
        for row_idx, value in enumerate(values, 4):
            common_sheet[f'A{row_idx}'] = value
    
    # Save to bytes
    output = io.BytesIO()
    wb.save(output)
    output.seek(0)
    return output.getvalue()

def generate_conflict_excel(conflict_result: dict) -> bytes:
    """Generate Excel report from conflict detection results."""
    import openpyxl
    from openpyxl.styles import Font, PatternFill
    
    wb = openpyxl.Workbook()
    wb.remove(wb.active)
    
    # Summary Sheet
    summary_sheet = wb.create_sheet("Conflict Summary")
    summary_sheet['A1'] = 'Data Conflict Analysis Report'
    summary_sheet['A1'].font = Font(size=16, bold=True)
    
    summary_sheet['A3'] = 'Total Conflicts Found:'
    summary_sheet['A3'].font = Font(bold=True)
    summary_sheet['B3'] = conflict_result.get('total_conflicts', 0)
    
    part_conflicts = len(conflict_result.get('part_number_conflicts', []))
    nom_conflicts = len(conflict_result.get('nomenclature_conflicts', []))
    
    summary_sheet['A5'] = 'Part Number Conflicts:'
    summary_sheet['B5'] = part_conflicts
    summary_sheet['A6'] = 'Nomenclature Conflicts:'
    summary_sheet['B6'] = nom_conflicts
    
    # Part Number Conflicts Sheet
    if part_conflicts > 0:
        part_sheet = wb.create_sheet("Part Number Conflicts")
        part_sheet['A1'] = 'Same Part Number - Different Nomenclatures'
        part_sheet['A1'].font = Font(size=14, bold=True)
        part_sheet['A1'].fill = PatternFill(start_color='FFCCCC', end_color='FFCCCC', fill_type='solid')
        
        part_sheet['A3'] = 'Part Number'
        part_sheet['B3'] = 'Nomenclature'
        part_sheet['C3'] = 'Source'
        part_sheet['D3'] = 'Page'
        
        for cell in [part_sheet['A3'], part_sheet['B3'], part_sheet['C3'], part_sheet['D3']]:
            cell.font = Font(bold=True)
            cell.fill = PatternFill(start_color='E0E0E0', end_color='E0E0E0', fill_type='solid')
        
        row_idx = 4
        for conflict in conflict_result.get('part_number_conflicts', []):
            part_num = conflict['part_number']
            sources = conflict['sources']
            
            for source in sources:
                part_sheet[f'A{row_idx}'] = part_num
                part_sheet[f'B{row_idx}'] = source['nomenclature']
                part_sheet[f'C{row_idx}'] = source['source']
                part_sheet[f'D{row_idx}'] = source.get('page', 'N/A')
                row_idx += 1
    
    # Nomenclature Conflicts Sheet
    if nom_conflicts > 0:
        nom_sheet = wb.create_sheet("Nomenclature Conflicts")
        nom_sheet['A1'] = 'Same Nomenclature - Different Part Numbers'
        nom_sheet['A1'].font = Font(size=14, bold=True)
        nom_sheet['A1'].fill = PatternFill(start_color='FFFFCC', end_color='FFFFCC', fill_type='solid')
        
        nom_sheet['A3'] = 'Nomenclature'
        nom_sheet['B3'] = 'Part Number'
        nom_sheet['C3'] = 'Source'
        nom_sheet['D3'] = 'Page'
        
        for cell in [nom_sheet['A3'], nom_sheet['B3'], nom_sheet['C3'], nom_sheet['D3']]:
            cell.font = Font(bold=True)
            cell.fill = PatternFill(start_color='E0E0E0', end_color='E0E0E0', fill_type='solid')
        
        row_idx = 4
        for conflict in conflict_result.get('nomenclature_conflicts', []):
            nomenclature = conflict['nomenclature']
            sources = conflict['sources']
            
            for source in sources:
                nom_sheet[f'A{row_idx}'] = nomenclature
                nom_sheet[f'B{row_idx}'] = source['part']
                nom_sheet[f'C{row_idx}'] = source['source']
                nom_sheet[f'D{row_idx}'] = source.get('page', 'N/A')
                row_idx += 1
    
    output = io.BytesIO()
    wb.save(output)
    output.seek(0)
    return output.getvalue()

def download_report(request, job_id):
    """
    Download Excel report for comparisons or conflicts.
    Serves directly from memory, no file saved on disk.
    
    GET /api/reports/download/<job_id>/
    """
    # Check comparison reports first
    report = _comparison_reports.get(job_id)
    
    if not report:
        # Fallback to old report system
        from .reports_engine_merge import get_report_job_status, get_report_excel_bytes
        job = get_report_job_status(job_id)
        
        if not job:
            return JsonResponse({"error": "Report not found"}, status=404)
        
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
    
    # Serve comparison report
    from django.http import HttpResponse
    
    excel_bytes = report.get('excel_bytes')
    if not excel_bytes:
        return JsonResponse({"error": "Report data not available"}, status=404)
    
    filename = report.get('filename', f'Report_{job_id[:8]}.xlsx')
    
    response = HttpResponse(
        excel_bytes,
        content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
    )
    response['Content-Disposition'] = f'attachment; filename="{filename}"'
    return response
