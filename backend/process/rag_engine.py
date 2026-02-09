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
import sqlite3

# Excel and Word document support
import openpyxl
from docx import Document as DocxDocument

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
TABLES_DB_PATH = "./tables.db"
OLLAMA_API = "http://localhost:11434/api/generate"
DEFAULT_LLM_MODEL = "llama3.1:8b"

# Available LLM models configuration
AVAILABLE_LLM_MODELS = {
    "llama3.2:1b": {
        "name": "Llama 3.2 1B",
        "title": "Efficient",
        "description": "Optimized for speed and low memory usage. Perfect for quick responses on limited hardware. Uses minimal resources while maintaining good quality output.",
        "tier": "efficient"
    },
    "phi3:3.8b": {
        "name": "Phi-3 3.8B",
        "title": "Balanced",
        "description": "Microsoft's powerful small model with excellent reasoning. Ideal balance of speed and accuracy for RAG tasks. Strong instruction-following capabilities.",
        "tier": "balanced"
    },
    "llama3.1:8b": {
        "name": "Llama 3.1 8B",
        "title": "Performance (Best)",
        "description": "Maximum accuracy and reasoning capability. Best for complex queries and detailed analysis. Recommended when quality is the top priority.",
        "tier": "performance"
    }
}


def get_current_llm_model():
    """Get the currently configured LLM model from database or return default."""
    try:
        from .models import AppConfig
        model = AppConfig.get_value('llm_model', DEFAULT_LLM_MODEL)
        # Validate model exists in available models
        if model not in AVAILABLE_LLM_MODELS:
            return DEFAULT_LLM_MODEL
        return model
    except Exception as e:
        print(f"[RAG] Could not read LLM model from DB: {e}")
        return DEFAULT_LLM_MODEL


def set_llm_model(model_name):
    """Set the LLM model in database."""
    try:
        from .models import AppConfig
        if model_name not in AVAILABLE_LLM_MODELS:
            return {"success": False, "error": f"Invalid model: {model_name}"}
        AppConfig.set_value('llm_model', model_name)
        return {"success": True, "model": model_name}
    except Exception as e:
        return {"success": False, "error": str(e)}


def get_llm_models_list():
    """Get list of available LLM models with their configurations."""
    current_model = get_current_llm_model()
    models = []
    for model_id, config in AVAILABLE_LLM_MODELS.items():
        models.append({
            "id": model_id,
            "name": config["name"],
            "title": config["title"],
            "description": config["description"],
            "tier": config["tier"],
            "selected": model_id == current_model
        })
    # Sort by tier: efficient -> balanced -> performance
    tier_order = {"efficient": 0, "balanced": 1, "performance": 2}
    models.sort(key=lambda x: tier_order.get(x["tier"], 99))
    return models

# Retrieval tuning (SAFE DEFAULTS)
CANDIDATE_K = 10
SIMILARITY_THRESHOLD = 0.55
MAX_FINAL_CHUNKS = 5

# ChromaDB batch size limit (default is 5461)
CHROMA_BATCH_SIZE = 5000

# Embedding batch size for faster processing
EMBEDDING_BATCH_SIZE = 128  # Process 128 chunks at a time for optimal GPU usage

# Disable ChromaDB telemetry (PostHog)
os.environ["ANONYMIZED_TELEMETRY"] = "False"

# Initialize ChromaDB (always available)
chroma_client = chromadb.PersistentClient(path=CHROMA_PATH)
collection = chroma_client.get_or_create_collection(name="rag_knowledge_base")


# ---------------- TABLE DATABASE MANAGEMENT ----------------
# Using Django ORM instead of raw SQL for better integration
# Note: ExtractedTable model is defined in models.py


def classify_table_type(headers, rows, row_count, column_count):
    """
    Classify table type for retrieval strategy.
    Returns: 'key_value', 'single_row', 'single_cell', or 'multi_row'
    """
    if row_count <= 0:
        return 'single_cell'

    if row_count == 1 and column_count == 1:
        return 'single_cell'

    # Key-value detection: 2 columns, labels in first column
    if column_count == 2 and row_count <= 10:
        if headers and len(headers) == 2:
            first_col = [str(row[0]).strip() for row in rows if row]
            # Check if first column looks like keys/parameters
            if any(kw in ' '.join(first_col).lower() for kw in ['parameter', 'property', 'specification', 'attribute', 'field', 'name', 'type']):
                return 'key_value'

    if row_count <= 2:
        return 'single_row'

    return 'multi_row'


def generate_searchable_text(headers, rows, table_type):
    """Generate rich searchable text for SQL FTS."""
    parts = []

    # Add headers
    if headers:
        parts.append(' '.join(str(h) for h in headers if h))

    # Add all cell values
    for row in rows:
        if row:
            parts.append(' '.join(str(cell) for cell in row if cell))

    # For key-value tables, create explicit key=value pairs
    if table_type == 'key_value' and len(rows) > 0:
        for row in rows:
            if len(row) >= 2 and row[0] and row[1]:
                parts.append(f"{row[0]}={row[1]}")
                parts.append(f"{row[0]} is {row[1]}")

    return ' '.join(parts)


def store_table(table_id, doc_id, thread_id, parent_id, source, page, table_index,
                headers, row_count, column_count, table_data):
    """Store a table using Django ORM with normalized structure."""
    from .models import ExtractedTable, TableRow, TableCell, Thread

    try:
        rows = table_data[1:] if len(table_data) > 1 else []
        table_type = classify_table_type(headers, rows, row_count, column_count)
        searchable_text = generate_searchable_text(headers, rows, table_type)

        # Get thread instance
        try:
            thread = Thread.objects.get(id=thread_id)
            parent_thread = Thread.objects.get(id=parent_id) if parent_id else None
        except Thread.DoesNotExist:
            print(f"[RAG] ERROR: Thread {thread_id} not found")
            return

        # Create or update table metadata
        table, created = ExtractedTable.objects.update_or_create(
            id=table_id,
            defaults={
                'doc_id': doc_id,
                'thread': thread,
                'parent_thread': parent_thread,
                'source': source,
                'page': page,
                'table_index': table_index,
                'row_count': row_count,
                'column_count': column_count,
                'table_type': table_type,
                'searchable_text': searchable_text,
            }
        )

        # Delete existing rows if updating
        if not created:
            table.rows.all().delete()

        # Store headers as first row
        if headers and any(headers):
            header_row = TableRow.objects.create(
                table=table,
                row_index=0,
                is_header=True
            )

            for col_idx, header_value in enumerate(headers):
                TableCell.objects.create(
                    row=header_row,
                    column_index=col_idx,
                    column_name=str(header_value) if header_value else '',
                    value=str(header_value) if header_value else '',
                    is_key=False
                )

        # Store data rows
        # table_data includes headers at index 0, so data rows start at index 1
        if len(table_data) > 1:
            data_rows = table_data[1:]
        elif len(table_data) == 1 and not headers:
            # Single row table without headers
            data_rows = table_data
        else:
            data_rows = []

        start_row_idx = 1 if headers else 0

        for row_offset, row_data in enumerate(data_rows):
            if not row_data or not isinstance(row_data, (list, tuple)):
                continue

            row_idx = start_row_idx + row_offset
            data_row = TableRow.objects.create(
                table=table,
                row_index=row_idx,
                is_header=False
            )

            # Determine if first column is a key (for key-value tables)
            is_kv_table = table_type == 'key_value'

            for col_idx, cell_value in enumerate(row_data):
                if col_idx >= column_count:
                    break

                # Ensure column name is never None
                if headers and col_idx < len(headers) and headers[col_idx]:
                    col_name = str(headers[col_idx])
                else:
                    col_name = f'Column {col_idx}'

                TableCell.objects.create(
                    row=data_row,
                    column_index=col_idx,
                    column_name=col_name,
                    value=str(cell_value) if cell_value else '',
                    is_key=(is_kv_table and col_idx == 0)  # First column in key-value tables
                )

        # Silently store - logging happens at page batch level

    except Exception as e:
        print(f"[RAG] ERROR storing table {table_id}: {e}")
        import traceback
        traceback.print_exc()


def get_table_by_id(table_id):
    """Retrieve a table by its ID using Django ORM."""
    from .models import ExtractedTable

    try:
        table = ExtractedTable.objects.get(id=table_id)
        return table.to_dict()
    except ExtractedTable.DoesNotExist:
        return None


def get_tables_by_doc(doc_id):
    """Retrieve all tables for a document using Django ORM."""
    from .models import ExtractedTable

    tables = ExtractedTable.objects.filter(doc_id=doc_id).order_by('page', 'table_index')
    return [table.to_dict() for table in tables]


def delete_tables(doc_id=None, thread_id=None):
    """Delete tables using Django ORM by doc_id or thread_id."""
    from .models import ExtractedTable

    if not doc_id and not thread_id:
        return False

    if doc_id:
        deleted_count, _ = ExtractedTable.objects.filter(doc_id=doc_id).delete()
    elif thread_id:
        deleted_count, _ = ExtractedTable.objects.filter(thread_id=thread_id).delete()

    print(f"[RAG] Deleted {deleted_count} tables via Django ORM")
    return True


# Django ORM handles table initialization via migrations
# No need for manual initialization


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
        """Get default model path (returns relative path for portability)"""
        # Return relative path - will be resolved to absolute when loading
        return "models/all-MiniLM-L6-v2"

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

            # Convert relative paths to absolute
            if model_path and not os.path.isabs(model_path):
                # Get project root (two levels up from backend/process/)
                backend_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
                project_root = os.path.dirname(backend_dir)
                model_path = os.path.normpath(os.path.join(project_root, model_path))
                print(f"[RAG] Resolved relative path to: {model_path}")

            # Check if we need to reload
            if self._model is not None and self._model_path == model_path and not force_reload:
                return True

            # Check if it's a HuggingFace model name (allow auto-download)
            is_hf_model = '/' in model_path or (not os.path.isabs(model_path) and not os.path.exists(model_path))

            # Validate local path exists (skip for HuggingFace model names)
            if not is_hf_model and not os.path.exists(model_path):
                self._status = {
                    "loaded": False,
                    "path": model_path,
                    "error": f"Model path does not exist: {model_path}",
                    "device": self._device
                }
                print(f"[RAG] ERROR: Model path does not exist: {model_path}")
                return False

            # Check for required model files (skip for HuggingFace model names)
            if not is_hf_model:
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

                print(f"[RAG] [OK] Embedding model loaded on {self._device.upper()} in {load_time:.2f}s")
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
        Encode texts to embeddings with batch processing optimization.

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

        # Optimize with batch processing for large documents
        if len(texts) > EMBEDDING_BATCH_SIZE:
            return model.encode(texts, batch_size=EMBEDDING_BATCH_SIZE, show_progress_bar=False)
        else:
            return model.encode(texts, show_progress_bar=False)


# Global singleton instance
model_manager = EmbeddingModelManager()

# Model will auto-initialize on first use through Django's AppConfig ready() method


def get_model_status():
    """Get the current embedding model status"""
    return model_manager.get_status()


def configure_model_path(path):
    """
    Configure and load the embedding model from a new path.

    Args:
        path: Path to the model directory (can be relative or absolute)

    Returns:
        dict with status information
    """
    # Normalize path - convert backslashes to forward slashes for portability
    path = path.replace('\\', '/')
    
    # Save to database (save as-is, will be resolved when loading)
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
    metadatas = []
    ids = []
    table_count = 0
    chunk_count = 0
    total_pages = len(doc)

    print(f"[RAG] Processing {total_pages} pages...")

    for page_num, page in enumerate(doc):
        # Extract text chunks
        text = page.get_text()
        chunks = smart_chunk_text(text)
        chunk_count += len(chunks)

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
            for table in tables:
                table_id = f"{doc_id}_{page_num}_table_{table['index']}"

                # Store full table in tables.db
                store_table(
                    table_id=table_id,
                    doc_id=doc_id,
                    thread_id=thread_id,
                    parent_id=parent_id,
                    source=filename,
                    page=page_num + 1,
                    table_index=table['index'],
                    headers=table['headers'],
                    row_count=table['row_count'],
                    column_count=table['column_count'],
                    table_data=table['data']
                )
                table_count += 1

                # For single-instance tables, ALSO embed in ChromaDB
                rows = table['data'][1:] if len(table['data']) > 1 else []
                table_type = classify_table_type(table['headers'], rows, table['row_count'], table['column_count'])

                if table_type in ['key_value', 'single_row', 'single_cell']:
                    # Create semantic text representation
                    table_text = f"Table {table['index'] + 1} on page {page_num + 1}:\n"
                    if table['headers']:
                        table_text += "Headers: " + ", ".join(str(h) for h in table['headers'] if h) + "\n"

                    for row in rows[:5]:  # Limit to first 5 rows
                        if row:
                            table_text += " | ".join(str(cell) for cell in row if cell) + "\n"

                    # Add to text chunks for embedding
                    chunk_id = f"{doc_id}_{page_num}_table_{table['index']}_text"
                    text_chunks.append(table_text)
                    ids.append(chunk_id)
                    metadatas.append({
                        "doc_id": str(doc_id),
                        "thread_id": str(thread_id),
                        "parent_id": str(parent_id) if parent_id else "none",
                        "source": filename,
                        "page": page_num + 1,
                        "type": "table_text",
                        "table_id": table_id
                    })

        # Print progress every 100 pages
        if (page_num + 1) % 100 == 0 or (page_num + 1) == total_pages:
            print(f"[RAG] Progress: {page_num + 1}/{total_pages} pages | {chunk_count} chunks | {table_count} tables")

    if not text_chunks:
        print("[RAG] No valid text chunks found.")
        return {"text_chunks": 0, "table_chunks": table_count}

    print(f"[RAG] Embedding {len(text_chunks)} chunks...")
    embed_start = time.time()
    embeddings = model_manager.encode(text_chunks).tolist()
    embed_time = time.time() - embed_start
    print(f"[RAG] ✓ Embedded in {embed_time:.2f}s")

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

    db_time = time.time() - db_start
    end_time = time.time()

    print(f"[RAG] ✓ Completed in {end_time - start_time:.1f}s | {len(text_chunks)} chunks + {table_count} tables stored")
    return {"text_chunks": len(text_chunks), "table_chunks": table_count}


# ---------------- EXCEL INGESTION ----------------
def process_excel(file_path, doc_id, thread_id, parent_id, filename):
    """
    Process Excel files (.xlsx, .xls) for RAG.
    Extracts text from all sheets and embeds it.
    """
    # Ensure model is loaded
    if not model_manager.is_ready():
        model_manager.load_model()

    if not model_manager.is_ready():
        raise RuntimeError("Embedding model not configured. Please set model path in Settings.")

    start_time = time.time()
    print(f"\n[RAG] Processing Excel: {filename} (Doc ID: {doc_id})")

    try:
        workbook = openpyxl.load_workbook(file_path, data_only=True)
    except Exception as e:
        print(f"[RAG] Error loading Excel file: {e}")
        raise RuntimeError(f"Failed to load Excel file: {e}")

    text_chunks = []
    metadatas = []
    ids = []
    table_count = 0
    chunk_count = 0

    for sheet_idx, sheet_name in enumerate(workbook.sheetnames):
        sheet = workbook[sheet_name]
        print(f"[RAG] Processing sheet: {sheet_name}")

        # Collect all text from the sheet
        sheet_text = []
        rows_data = []
        headers = None

        for row_idx, row in enumerate(sheet.iter_rows(values_only=True)):
            if not any(cell is not None for cell in row):
                continue  # Skip empty rows

            row_values = [str(cell) if cell is not None else "" for cell in row]
            rows_data.append(row_values)

            if row_idx == 0:
                headers = row_values

            # Build text representation
            row_text = " | ".join(str(cell) for cell in row if cell is not None)
            if row_text.strip():
                sheet_text.append(row_text)

        # Store as table in tables.db if it looks like structured data
        if len(rows_data) > 1 and headers:
            table_id = f"{doc_id}_sheet_{sheet_idx}_table_0"
            column_count = len(headers) if headers else len(rows_data[0]) if rows_data else 0

            store_table(
                table_id=table_id,
                doc_id=doc_id,
                thread_id=thread_id,
                parent_id=parent_id,
                source=filename,
                page=sheet_idx + 1,
                table_index=0,
                headers=headers,
                row_count=len(rows_data) - 1,
                column_count=column_count,
                table_data=rows_data
            )
            table_count += 1

        # Chunk the sheet text
        full_text = f"Sheet: {sheet_name}\n" + "\n".join(sheet_text)
        chunks = smart_chunk_text(full_text)
        chunk_count += len(chunks)

        for i, chunk in enumerate(chunks):
            chunk_id = f"{doc_id}_sheet_{sheet_idx}_{i}"
            text_chunks.append(chunk)
            ids.append(chunk_id)

            metadatas.append({
                "doc_id": str(doc_id),
                "thread_id": str(thread_id),
                "parent_id": str(parent_id) if parent_id else "none",
                "source": filename,
                "page": sheet_idx + 1,
                "sheet_name": sheet_name,
                "type": "excel_text"
            })

    workbook.close()

    if not text_chunks:
        print("[RAG] No valid text chunks found in Excel.")
        return {"text_chunks": 0, "table_chunks": table_count}

    print(f"[RAG] Embedding {len(text_chunks)} chunks...")
    embed_start = time.time()
    embeddings = model_manager.encode(text_chunks).tolist()
    embed_time = time.time() - embed_start
    print(f"[RAG] ✓ Embedded in {embed_time:.2f}s")

    # Batch insert
    total_chunks = len(text_chunks)
    if total_chunks <= CHROMA_BATCH_SIZE:
        collection.add(
            documents=text_chunks,
            embeddings=embeddings,
            metadatas=metadatas,
            ids=ids
        )
    else:
        for i in range(0, total_chunks, CHROMA_BATCH_SIZE):
            end_idx = min(i + CHROMA_BATCH_SIZE, total_chunks)
            collection.add(
                documents=text_chunks[i:end_idx],
                embeddings=embeddings[i:end_idx],
                metadatas=metadatas[i:end_idx],
                ids=ids[i:end_idx]
            )

    end_time = time.time()
    print(f"[RAG] ✓ Excel completed in {end_time - start_time:.1f}s | {len(text_chunks)} chunks + {table_count} tables stored")
    return {"text_chunks": len(text_chunks), "table_chunks": table_count}


# ---------------- WORD DOCUMENT INGESTION ----------------
def process_word(file_path, doc_id, thread_id, parent_id, filename):
    """
    Process Word documents (.docx) for RAG.
    Extracts text from paragraphs and tables.
    """
    # Ensure model is loaded
    if not model_manager.is_ready():
        model_manager.load_model()

    if not model_manager.is_ready():
        raise RuntimeError("Embedding model not configured. Please set model path in Settings.")

    start_time = time.time()
    print(f"\n[RAG] Processing Word: {filename} (Doc ID: {doc_id})")

    try:
        doc = DocxDocument(file_path)
    except Exception as e:
        print(f"[RAG] Error loading Word file: {e}")
        raise RuntimeError(f"Failed to load Word file: {e}")

    text_chunks = []
    metadatas = []
    ids = []
    table_count = 0
    chunk_count = 0

    # Extract text from paragraphs
    paragraphs_text = []
    for para in doc.paragraphs:
        if para.text.strip():
            paragraphs_text.append(para.text.strip())

    full_text = "\n\n".join(paragraphs_text)
    chunks = smart_chunk_text(full_text)
    chunk_count += len(chunks)

    for i, chunk in enumerate(chunks):
        chunk_id = f"{doc_id}_para_{i}"
        text_chunks.append(chunk)
        ids.append(chunk_id)

        metadatas.append({
            "doc_id": str(doc_id),
            "thread_id": str(thread_id),
            "parent_id": str(parent_id) if parent_id else "none",
            "source": filename,
            "page": 1,
            "type": "word_text"
        })

    # Extract tables from Word document
    for table_idx, table in enumerate(doc.tables):
        rows_data = []
        headers = None

        for row_idx, row in enumerate(table.rows):
            row_values = [cell.text.strip() for cell in row.cells]
            rows_data.append(row_values)

            if row_idx == 0:
                headers = row_values

        if len(rows_data) > 0:
            table_id = f"{doc_id}_table_{table_idx}"
            column_count = len(headers) if headers else len(rows_data[0]) if rows_data else 0

            store_table(
                table_id=table_id,
                doc_id=doc_id,
                thread_id=thread_id,
                parent_id=parent_id,
                source=filename,
                page=1,
                table_index=table_idx,
                headers=headers,
                row_count=len(rows_data) - 1 if headers else len(rows_data),
                column_count=column_count,
                table_data=rows_data
            )
            table_count += 1

            # Create text representation for embedding
            table_text = f"Table {table_idx + 1}:\n"
            if headers:
                table_text += "Headers: " + ", ".join(str(h) for h in headers if h) + "\n"

            for row in rows_data[1:6]:  # First 5 data rows
                table_text += " | ".join(str(cell) for cell in row if cell) + "\n"

            chunk_id = f"{doc_id}_table_{table_idx}_text"
            text_chunks.append(table_text)
            ids.append(chunk_id)
            metadatas.append({
                "doc_id": str(doc_id),
                "thread_id": str(thread_id),
                "parent_id": str(parent_id) if parent_id else "none",
                "source": filename,
                "page": 1,
                "type": "word_table",
                "table_id": table_id
            })

    if not text_chunks:
        print("[RAG] No valid text chunks found in Word document.")
        return {"text_chunks": 0, "table_chunks": table_count}

    print(f"[RAG] Embedding {len(text_chunks)} chunks...")
    embed_start = time.time()
    embeddings = model_manager.encode(text_chunks).tolist()
    embed_time = time.time() - embed_start
    print(f"[RAG] ✓ Embedded in {embed_time:.2f}s")

    # Batch insert
    total_chunks = len(text_chunks)
    if total_chunks <= CHROMA_BATCH_SIZE:
        collection.add(
            documents=text_chunks,
            embeddings=embeddings,
            metadatas=metadatas,
            ids=ids
        )
    else:
        for i in range(0, total_chunks, CHROMA_BATCH_SIZE):
            end_idx = min(i + CHROMA_BATCH_SIZE, total_chunks)
            collection.add(
                documents=text_chunks[i:end_idx],
                embeddings=embeddings[i:end_idx],
                metadatas=metadatas[i:end_idx],
                ids=ids[i:end_idx]
            )

    end_time = time.time()
    print(f"[RAG] ✓ Word completed in {end_time - start_time:.1f}s | {len(text_chunks)} chunks + {table_count} tables stored")
    return {"text_chunks": len(text_chunks), "table_chunks": table_count}


# ---------------- UNIVERSAL DOCUMENT PROCESSOR ----------------
def process_document(file_path, doc_id, thread_id, parent_id, filename):
    """
    Universal document processor that handles PDF, Excel, and Word files.
    Automatically detects file type and calls the appropriate processor.
    """
    ext = os.path.splitext(filename)[1].lower()

    if ext == '.pdf':
        return process_pdf(file_path, doc_id, thread_id, parent_id, filename)
    elif ext in ['.xlsx', '.xls']:
        return process_excel(file_path, doc_id, thread_id, parent_id, filename)
    elif ext == '.docx':
        return process_word(file_path, doc_id, thread_id, parent_id, filename)
    else:
        raise ValueError(f"Unsupported file type: {ext}. Supported: .pdf, .xlsx, .xls, .docx")


def detect_table_query_intent(query_text):
    """
    Detect if query is asking for table/spec/numeric data.
    Returns True if table lookup should be prioritized.
    """
    query_lower = query_text.lower()

    # Keywords that strongly indicate table lookup
    table_keywords = [
        'table', 'specification', 'spec', 'parameter', 'value', 'property',
        'attribute', 'dimension', 'measurement', 'characteristic', 'feature',
        'configuration', 'setting', 'rating', 'capacity', 'range', 'limit',
        'requirement', 'criteria', 'threshold', 'tolerance', 'standard',
        'available', 'availability', 'stock', 'part', 'nsn', 'model', 'code',
        'number', 'serial', 'item', 'component', 'product'
    ]

    # Question patterns for data lookup
    data_patterns = [
        r'what\s+(is|are)\s+the\s+\w+',
        r'how\s+much',
        r'how\s+many',
        r'show\s+me',
        r'list\s+the',
        r'find\s+the',
        r'get\s+the',
        r'is\s+it\s+available',
        r'is\s+there',
        r'do\s+you\s+have'
    ]

    # Part number / alphanumeric code patterns (e.g., 410A223100000, ABC-123-XYZ)
    code_patterns = [
        r'\b\d{5,}\b',  # Long numeric codes (5+ digits)
        r'\b[A-Z0-9]{6,}\b',  # Alphanumeric codes (6+ chars)
        r'\b\d+[A-Z]+\d+\b',  # Mixed digit-letter-digit
        r'\b[A-Z]+\d+[A-Z]*\d*\b',  # Letter-digit combinations
        r'\b\w+[-_]\w+[-_]\w+\b'  # Hyphen/underscore separated codes
    ]

    has_table_keyword = any(kw in query_lower for kw in table_keywords)
    has_data_pattern = any(re.search(pattern, query_lower) for pattern in data_patterns)
    has_code_pattern = any(re.search(pattern, query_text, re.IGNORECASE) for pattern in code_patterns)

    is_table_query = has_table_keyword or has_data_pattern or has_code_pattern

    if has_code_pattern:
        print(f"[RAG] Detected code/part number pattern in query - triggering table search")

    return is_table_query


def extract_file_filter(query_text):
    """
    Extract @filename from query if present.
    Supports: .pdf, .xlsx, .xls, .docx
    Handles filenames with spaces (e.g., @test doc 1.pdf)
    Returns (clean_query, filename or None)
    """
    # Match any supported file type - handles filenames with spaces
    # Pattern: @ followed by anything until .ext (where ext is pdf/xlsx/xls/docx)
    match = re.search(r'@(.+?\.(pdf|xlsx|xls|docx))(?:\s|$)', query_text, re.IGNORECASE)

    if not match:
        return query_text, None

    filename = match.group(1).strip()
    # Remove the @filename from query
    cleaned_query = re.sub(r'@' + re.escape(filename), '', query_text, flags=re.IGNORECASE).strip()
    return cleaned_query, filename


def extract_search_terms(query_text):
    """
    Industry-ready extraction of search terms from queries.
    Handles:
    - Part numbers: '410A800000000', 410A223100000, ABC-123-XYZ
    - Part names: 'ROLLER ASSEMBLY', "BALATA SHEET", NOSE PUSHING CYLINDER

    NOTE: This function should be called AFTER extract_file_filter()
    so that @filename is already removed from the query.
    - Various query formats: "Find X", "Is X available?", "Does document have X?"

    Returns dict with:
    - 'codes': List of part numbers/codes (alphanumeric identifiers)
    - 'names': List of part names (descriptive text)
    - 'keywords': List of other meaningful keywords
    """
    result = {
        'codes': [],
        'names': [],
        'keywords': []
    }

    print(f"\n[EXTRACT] === Extracting search terms from: '{query_text}' ===")

    # Common stop words and query words to ignore
    stop_words = {
        'is', 'it', 'there', 'the', 'in', 'a', 'an', 'and', 'or', 'for', 'to', 'of', 'on', 'at',
        'find', 'get', 'show', 'list', 'does', 'do', 'has', 'have', 'this', 'that', 'available',
        'document', 'documents', 'part', 'number', 'name', 'if', 'can', 'you', 'me', 'what',
        'where', 'which', 'how', 'many', 'much', 'are', 'was', 'were', 'been', 'be', 'being',
        'search', 'look', 'looking', 'check', 'checking', 'tell', 'give', 'please', 'could',
        'would', 'should', 'want', 'need', 'item', 'items', 'component', 'components',
        'with', 'from', 'about', 'into', 'any', 'all', 'some', 'whether', 'contains', 'contain'
    }

    # =====================================================
    # STEP 1: Extract QUOTED text (highest priority)
    # This captures both part names AND part numbers in quotes
    # =====================================================

    # Pattern for single or double quoted strings (can contain spaces)
    quoted_pattern = r"['\"]([^'\"]+)['\"]"
    quoted_matches = re.findall(quoted_pattern, query_text)

    for match in quoted_matches:
        match = match.strip()
        if len(match) >= 2:
            # Determine if it's a code or a name
            # Codes: mostly alphanumeric, no spaces, contains digits
            # Names: contains spaces or all letters
            if ' ' in match:
                # Multi-word = part name
                result['names'].append(match)
                print(f"[EXTRACT] Quoted PART NAME: '{match}'")
            elif re.search(r'\d', match):
                # Contains digits = likely a code
                result['codes'].append(match)
                print(f"[EXTRACT] Quoted CODE: '{match}'")
            elif match.isupper() and len(match) >= 3:
                # All uppercase letters = could be abbreviation/code
                result['codes'].append(match)
                print(f"[EXTRACT] Quoted ABBREVIATION: '{match}'")
            else:
                # Treat as name
                result['names'].append(match)
                print(f"[EXTRACT] Quoted NAME: '{match}'")

    # Remove quoted portions from query for further processing
    clean_query = re.sub(quoted_pattern, ' ', query_text)

    # =====================================================
    # STEP 2: Extract PART NUMBERS/CODES (unquoted)
    # =====================================================

    # Pattern: Long numeric codes (5+ digits)
    numeric_matches = re.findall(r'\b(\d{5,})\b', clean_query)
    for match in numeric_matches:
        if match not in result['codes']:
            result['codes'].append(match)
            print(f"[EXTRACT] Numeric CODE: '{match}'")

    # Pattern: Alphanumeric starting with digits (like 410A800000000)
    alpha_num_matches = re.findall(r'\b(\d+[A-Za-z]+\d+[A-Za-z0-9]*)\b', clean_query)
    for match in alpha_num_matches:
        if match not in result['codes'] and len(match) >= 5:
            result['codes'].append(match)
            print(f"[EXTRACT] Alphanumeric CODE: '{match}'")

    # Pattern: Alphanumeric starting with letters (like ABC123456)
    letter_num_matches = re.findall(r'\b([A-Za-z]+\d+[A-Za-z0-9]*)\b', clean_query)
    for match in letter_num_matches:
        if match not in result['codes'] and len(match) >= 5:
            if match.lower() not in stop_words:
                result['codes'].append(match)
                print(f"[EXTRACT] Letter-num CODE: '{match}'")

    # Pattern: Hyphen/underscore separated (like ABC-123-XYZ)
    hyphen_matches = re.findall(r'\b([A-Za-z0-9]+[-_][A-Za-z0-9]+(?:[-_][A-Za-z0-9]+)*)\b', clean_query)
    for match in hyphen_matches:
        if match not in result['codes'] and len(match) >= 5:
            result['codes'].append(match)
            print(f"[EXTRACT] Hyphenated CODE: '{match}'")

    # =====================================================
    # STEP 3: Extract PART NAMES (unquoted multi-word UPPERCASE)
    # Common in industrial documents: "ROLLER ASSEMBLY", "BALATA SHEET"
    # =====================================================

    # Pattern: 2-4 consecutive UPPERCASE words
    uppercase_phrase_pattern = r'\b([A-Z][A-Z]+(?:\s+[A-Z][A-Z]+){1,3})\b'
    uppercase_matches = re.findall(uppercase_phrase_pattern, clean_query)
    for match in uppercase_matches:
        # Filter out if it's just stop words
        words = match.split()
        meaningful_words = [w for w in words if w.lower() not in stop_words]
        if len(meaningful_words) >= 1:
            if match not in result['names']:
                result['names'].append(match)
                print(f"[EXTRACT] Uppercase PART NAME: '{match}'")

    # =====================================================
    # STEP 4: Extract remaining meaningful KEYWORDS
    # =====================================================

    # Split and clean
    tokens = clean_query.split()
    for token in tokens:
        # Clean punctuation
        cleaned = re.sub(r"['\",?!.:;()]", "", token)

        # Skip if too short, is stop word, or already captured
        if len(cleaned) < 3:
            continue
        if cleaned.lower() in stop_words:
            continue
        if cleaned in result['codes'] or cleaned in result['names']:
            continue

        # Check if it looks like a code
        if re.search(r'\d', cleaned) and len(cleaned) >= 5:
            if cleaned not in result['codes']:
                result['codes'].append(cleaned)
                print(f"[EXTRACT] Token CODE: '{cleaned}'")
        elif cleaned.isupper() and len(cleaned) >= 3:
            # Single uppercase word (could be abbreviation)
            if cleaned not in result['keywords']:
                result['keywords'].append(cleaned)
                print(f"[EXTRACT] Uppercase KEYWORD: '{cleaned}'")
        elif len(cleaned) >= 4:
            # Regular keyword
            if cleaned.lower() not in result['keywords']:
                result['keywords'].append(cleaned.lower())
                print(f"[EXTRACT] KEYWORD: '{cleaned}'")

    print(f"[EXTRACT] === Results ===")
    print(f"[EXTRACT] Codes: {result['codes']}")
    print(f"[EXTRACT] Names: {result['names']}")
    print(f"[EXTRACT] Keywords: {result['keywords']}")

    return result


def search_tables_directly(query_text, thread_id, file_filter=None):
    """
    Industry-ready SQL-based table search.
    Handles part numbers, part names, and various query formats.
    Returns ALL matching tables without limits.
    """
    from .models import ExtractedTable
    from django.db.models import Q

    print(f"\n[DEBUG-SQL-SEARCH] === search_tables_directly() ===")
    print(f"[DEBUG-SQL-SEARCH] Query: {query_text}")

    # Build base filter
    base_query = ExtractedTable.objects.filter(thread_id=thread_id)
    if file_filter:
        base_query = base_query.filter(source=file_filter)
        print(f"[DEBUG-SQL-SEARCH] File Filter: {file_filter}")

    # Extract search terms using smart extractor
    terms = extract_search_terms(query_text)

    tables = None
    q_objects = Q()

    # =========================================================
    # PRIORITY 1: Search for CODES (part numbers, alphanumeric IDs)
    # These are the most specific and should match exactly
    # =========================================================
    if terms['codes']:
        print(f"[DEBUG-SQL-SEARCH] Searching for codes: {terms['codes']}")
        for code in terms['codes']:
            q_objects |= Q(searchable_text__icontains=code)
        tables = base_query.filter(q_objects).distinct()
        if tables.exists():
            print(f"[DEBUG-SQL-SEARCH] ✓ Found {tables.count()} tables with codes")
            # Return early if we have good code matches
            results = []
            for table in tables:
                result = table.to_dict()
                result['source_type'] = 'sql_search'
                results.append(result)
                print(f"[DEBUG-SQL-SEARCH]   {table.id} | {table.source} | Page {table.page}")
            return results

    # =========================================================
    # PRIORITY 2: Search for PART NAMES (multi-word descriptive names)
    # =========================================================
    if terms['names']:
        print(f"[DEBUG-SQL-SEARCH] Searching for part names: {terms['names']}")
        q_objects = Q()
        for name in terms['names']:
            q_objects |= Q(searchable_text__icontains=name)
        tables = base_query.filter(q_objects).distinct()
        if tables.exists():
            print(f"[DEBUG-SQL-SEARCH] ✓ Found {tables.count()} tables with part names")
            results = []
            for table in tables:
                result = table.to_dict()
                result['source_type'] = 'sql_search'
                results.append(result)
                print(f"[DEBUG-SQL-SEARCH]   {table.id} | {table.source} | Page {table.page}")
            return results

    # =========================================================
    # PRIORITY 3: Search for KEYWORDS (fallback)
    # =========================================================
    if terms['keywords']:
        print(f"[DEBUG-SQL-SEARCH] Searching for keywords: {terms['keywords']}")
        q_objects = Q()
        for keyword in terms['keywords']:
            q_objects |= Q(searchable_text__icontains=keyword)
        tables = base_query.filter(q_objects).distinct()
        if tables.exists():
            print(f"[DEBUG-SQL-SEARCH] ✓ Found {tables.count()} tables with keywords")

    # =========================================================
    # PRIORITY 4: If nothing found, return all tables
    # =========================================================
    if tables is None or not tables.exists():
        print(f"[DEBUG-SQL-SEARCH] No specific matches, returning all tables")
        tables = base_query.all()

    print(f"[DEBUG-SQL-SEARCH] Final result: {tables.count()} matching tables")

    # Convert to dict format
    results = []
    for table in tables:
        result = table.to_dict()
        result['source_type'] = 'sql_search'
        results.append(result)
        print(f"[DEBUG-SQL-SEARCH]   {table.id} | {table.source} | Page {table.page}")

    return results


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

    # --- QUERY INTENT DETECTION ---
    is_table_query = detect_table_query_intent(query_text)
    print(f"[RAG] Table query intent: {is_table_query}")

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
    print(f"\n[DEBUG-RETRIEVAL] Vector Search Starting...")
    print(f"[DEBUG-RETRIEVAL] Filter: {where_filter}")
    print(f"[DEBUG-RETRIEVAL] Candidate K: {CANDIDATE_K}")

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
    print(f"\n[DEBUG-RETRIEVAL] ChromaDB Results:")
    for i, (doc, meta, dist) in enumerate(zip(docs, metas, dists)):
        print(f"  [{i}] Distance: {dist:.4f} | Source: {meta.get('source', 'N/A')} | Page: {meta.get('page', 'N/A')} | Type: {meta.get('type', 'text')}")
        print(f"      Preview: {doc[:100]}...")


    # MAX_DISTANCE_THRESHOLD = 2.0 if file_filter else 1.0


    # filtered_chunks = []

    # for doc, meta, dist in zip(docs, metas, dists):
    #     if dist <= MAX_DISTANCE_THRESHOLD:
    #         filtered_chunks.append((doc, meta, dist))

    # sort by best match (lowest distance first)

    # --- DISTANCE-BASED FILTERING (adaptive & file-safe) ---
    print(f"\n[DEBUG-RETRIEVAL] Distance Filtering Starting...")
    filtered_chunks = []
    if dists:
        best_distance = dists[0]  # Chroma returns sorted distances
        RELATIVE_MARGIN = 0.35 if file_filter else 0.25
        MAX_ABSOLUTE_CAP = 2.2 if file_filter else 1.2
        print(f"[DEBUG-RETRIEVAL] Best Distance: {best_distance:.4f}")
        print(f"[DEBUG-RETRIEVAL] Relative Margin: {RELATIVE_MARGIN}")
        print(f"[DEBUG-RETRIEVAL] Absolute Cap: {MAX_ABSOLUTE_CAP}")
        print(f"[DEBUG-RETRIEVAL] Threshold: {best_distance * (1 + RELATIVE_MARGIN):.4f}")

        for idx, (doc, meta, dist) in enumerate(zip(docs, metas, dists)):
            passed = (
                dist <= best_distance * (1 + RELATIVE_MARGIN)
                and dist <= MAX_ABSOLUTE_CAP
            )
            print(f"[DEBUG-RETRIEVAL]   Chunk {idx}: dist={dist:.4f} | passed={passed}")
            if passed:
                filtered_chunks.append((doc, meta, dist))

# Fallback: always ensure at least 1 chunk if any results exist
    if not filtered_chunks and docs:
        print(f"[DEBUG-RETRIEVAL] No chunks passed filter, using fallback (1 chunk)")
        filtered_chunks = list(zip(docs, metas, dists))[:1]  # At least 1 chunk

    filtered_chunks.sort(key=lambda x: x[2])
    final_chunks = filtered_chunks[:MAX_FINAL_CHUNKS]

    # Ensure at least 1 chunk if any documents were retrieved
    if not final_chunks and docs:
        print(f"[DEBUG-RETRIEVAL] Empty final_chunks, using fallback (1 chunk)")
        final_chunks = list(zip(docs, metas, dists))[:1]

    print(f"[RAG] Final chunks after filtering: {len(final_chunks)}")
    print(f"[DEBUG-RETRIEVAL] Final Chunk IDs: {[meta.get('source', 'N/A') + ':' + str(meta.get('page', 'N/A')) for _, meta, _ in final_chunks]}")

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
        chunk_info = {
            "text": doc,
            "source": meta['source'],
            "page": meta['page'],
            "similarity_score": round(float(1 - sim), 3),
            "type": "text"
        }

        chunks_with_metadata.append(chunk_info)

    # --- DUAL RETRIEVAL STRATEGY ---

    # SQL table search for table queries
    print(f"\n[DEBUG-RETRIEVAL] === SQL TABLE SEARCH ===")
    print(f"[DEBUG-RETRIEVAL] Is Table Query: {is_table_query}")
    sql_tables = []
    if is_table_query:
        print("[RAG] Executing SQL table search...")
        print(f"[DEBUG-RETRIEVAL] Query Text: '{query_text}'")
        print(f"[DEBUG-RETRIEVAL] Thread ID: {current_thread_id}")
        print(f"[DEBUG-RETRIEVAL] File Filter: {file_filter}")
        sql_tables = search_tables_directly(query_text, current_thread_id, file_filter)
        print(f"[RAG] Found {len(sql_tables)} tables via SQL search")

    # Add ALL SQL tables to response (no limits, no reranking)
    print(f"\n[DEBUG-RETRIEVAL] === ADDING SQL TABLES ===")
    print(f"[DEBUG-RETRIEVAL] Total Tables: {len(sql_tables)}")

    for idx, table in enumerate(sql_tables):
        table_info = {
            "type": "table",
            "table_id": table['id'],
            "source": table['source'],
            "page": table['page'],
            "table_index": table['table_index'],
            "table_data": {
                "headers": table['headers'],
                "row_count": table['row_count'],
                "column_count": table['column_count'],
                "data": table['data']
            },
            "table_type": table.get('table_type', 'unknown'),
            "has_structured_data": True,
            "similarity_score": 0.0,
            "retrieval_source": table.get('source_type', 'unknown')
        }
        chunks_with_metadata.append(table_info)
        print(f"[DEBUG-RETRIEVAL]   [{idx+1}] {table['id']}: {table['row_count']}x{table['column_count']} | {table.get('table_type')}")

    # --- INTELLIGENT QUERY RESPONSE FOR SQL TABLE HITS ---
    if sql_tables:
        print(f"\n[RAG] SQL table search found {len(sql_tables)} results")

        # Detect query intent: Is this a QUESTION or a FIND/LOCATE request?
        query_lower = query_text.lower().strip()

        # Question indicators - needs intelligent answer
        question_patterns = [
            'is ', 'are ', 'does ', 'do ', 'what ', 'which ', 'how ', 'why ', 'when ', 'where ',
            'can ', 'could ', 'should ', 'would ', 'will ', 'has ', 'have ', 'was ', 'were ',
            'tell me', 'explain', 'describe', 'compare', 'difference', 'correct', 'right',
            'specifications', 'spec', 'torque', 'material', 'install', 'replace', 'procedure',
            'compatible', 'alternate', 'cross-reference', 'service', 'maintenance', 'limit'
        ]

        # Find/Locate indicators - just show locations
        find_patterns = [
            'find ', 'locate ', 'show me where', 'where is', 'where are', 'where can i find',
            'list all', 'show all', 'get all'
        ]

        is_question = any(query_lower.startswith(p) or p in query_lower for p in question_patterns)
        is_find_only = any(query_lower.startswith(p) for p in find_patterns)

        # If it ends with '?' it's likely a question
        if query_text.strip().endswith('?'):
            is_question = True

        print(f"[RAG] Query Analysis - Is Question: {is_question}, Is Find Only: {is_find_only}")

        # Build table locations for reference
        table_locations = []
        for table in sql_tables:
            location = f"{table['source']} (Page {table['page']}, Table {table['table_index']})"
            table_locations.append(location)

        location_text = "\n".join(f"• {loc}" for loc in table_locations)

        # --- INTELLIGENT ANSWER MODE ---
        if is_question and not is_find_only:
            print(f"[RAG] Generating intelligent answer using LLM...")

            # Extract search terms for context
            search_terms = extract_search_terms(query_text)
            all_terms = search_terms['codes'] + search_terms['names'] + search_terms['keywords']

            # Build rich context from table data with SMART ROW MATCHING
            table_context = ""
            exact_matches = []  # Rows that EXACTLY match the search term
            partial_matches = []  # Rows that contain the term but aren't exact

            for idx, table in enumerate(sql_tables[:5]):  # Limit to 5 tables for context
                headers = table.get('headers', [])
                data = table.get('data', [])
                source_info = f"{table['source']} (Page {table['page']})"

                # Find header indices for common columns
                header_lower = [str(h).lower() for h in headers]
                name_col_idx = None
                for i, h in enumerate(header_lower):
                    if any(x in h for x in ['name', 'designation', 'description', 'item']):
                        name_col_idx = i
                        break

                for row in data:
                    row_text = ' '.join(str(cell) for cell in row)
                    row_text_lower = row_text.lower()

                    for term in all_terms:
                        term_lower = term.lower().strip()

                        # Check for EXACT match (term matches a cell exactly or the item name column)
                        is_exact = False
                        for cell in row:
                            cell_str = str(cell).strip().lower()
                            if cell_str == term_lower:
                                is_exact = True
                                break

                        # Also check if item name column matches exactly
                        if name_col_idx is not None and name_col_idx < len(row):
                            item_name = str(row[name_col_idx]).strip().lower()
                            if item_name == term_lower:
                                is_exact = True

                        if is_exact:
                            exact_matches.append({
                                'term': term,
                                'row': row,
                                'headers': headers,
                                'source': source_info,
                                'match_type': 'EXACT'
                            })
                        elif term_lower in row_text_lower:
                            # Partial match - term is contained but not exact
                            partial_matches.append({
                                'term': term,
                                'row': row,
                                'headers': headers,
                                'source': source_info,
                                'match_type': 'PARTIAL'
                            })

            # Build structured context - prioritize EXACT matches
            if exact_matches:
                table_context += "\n=== EXACT MATCHES (Use these for answering) ===\n"
                seen_rows = set()
                for match in exact_matches:
                    row_key = str(match['row'])
                    if row_key not in seen_rows:
                        seen_rows.add(row_key)
                        table_context += f"\nSearched: '{match['term']}' → EXACT MATCH\n"
                        table_context += f"Source: {match['source']}\n"
                        # Format as key-value pairs for clarity
                        for i, header in enumerate(match['headers']):
                            if i < len(match['row']):
                                table_context += f"  {header}: {match['row'][i]}\n"

            if partial_matches and not exact_matches:
                # Only show partial matches if no exact matches found
                table_context += "\n=== PARTIAL MATCHES (Term found within text) ===\n"
                seen_rows = set()
                for match in partial_matches[:5]:  # Limit partial matches
                    row_key = str(match['row'])
                    if row_key not in seen_rows:
                        seen_rows.add(row_key)
                        table_context += f"\nSearched: '{match['term']}' → PARTIAL MATCH\n"
                        table_context += f"Source: {match['source']}\n"
                        table_context += f"⚠️ WARNING: This row contains '{match['term']}' but may not be an exact match!\n"
                        for i, header in enumerate(match['headers']):
                            if i < len(match['row']):
                                table_context += f"  {header}: {match['row'][i]}\n"

            # If no matches at all, show raw table data
            if not exact_matches and not partial_matches:
                table_context += "\n=== TABLE DATA (No specific matches found) ===\n"
                for idx, table in enumerate(sql_tables[:3]):
                    table_context += f"\nTable from {table['source']} (Page {table['page']}):\n"
                    headers = table.get('headers', [])
                    table_context += f"Headers: {' | '.join(str(h) for h in headers)}\n"
                    for row in table.get('data', [])[:5]:
                        table_context += f"Row: {' | '.join(str(cell) for cell in row)}\n"

            # Build intelligent prompt - OPTIMIZED FOR SMALLER LLMs
            system_prompt = """You are a precise document assistant. Answer questions using ONLY the provided data.

CRITICAL RULES:
1. Use ONLY data from "EXACT MATCHES" section when available
2. If user asks about "SUPPORT ROLLER", find the row where the name is EXACTLY "SUPPORT ROLLER", NOT "SUPPORT ROLLER FIXING" or similar
3. NEVER confuse similar names - "SUPPORT ROLLER" and "SUPPORT ROLLER FIXING BRACKET" are DIFFERENT items
4. Read the data carefully - each row has headers and values
5. If no exact match exists, say "No exact match found for [term]"
6. Be concise and direct"""

            user_prompt = f"""QUESTION: {query_text}

SEARCH TERMS:
- Part Numbers: {search_terms['codes'] if search_terms['codes'] else 'None'}
- Part Names: {search_terms['names'] if search_terms['names'] else 'None'}

{table_context}

Answer the question using ONLY the EXACT MATCH data above.
If the user asks about "X", use ONLY the row where the item name is EXACTLY "X"."""

            current_llm = get_current_llm_model()
            print(f"[RAG] Using LLM model: {current_llm}")
            print(f"[RAG] Exact matches: {len(exact_matches)}, Partial matches: {len(partial_matches)}")

            payload = {
                "model": current_llm,
                "prompt": user_prompt,
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

                # Append source references
                answer += f"\n\n**📍 Source(s):** {len(sql_tables)} table(s)\n{location_text}"

                total_time = time.time() - start_time
                end_memory = process.memory_info().rss / 1024 / 1024

                print(f"[RAG] Intelligent answer generated in {total_time:.2f}s (LLM: {llm_time:.2f}s)")
                print(f"[RAG] Memory: {start_memory:.1f}MB -> {end_memory:.1f}MB")

                return {
                    "answer": answer,
                    "sources": list(set(sources + table_locations)),
                    "chunks": chunks_with_metadata,
                    "confidence": 95.0,
                    "confidence_label": "HIGH",
                    "retrieval_type": "sql_intelligent",
                    "table_count": len(sql_tables)
                }

            except Exception as e:
                print(f"[RAG] LLM error: {e}, falling back to location response")
                # Fall through to location-only response

        # --- LOCATION-ONLY MODE (for find/locate queries or LLM failure) ---
        print(f"[RAG] Returning location-based response")
        answer = f"**Yes** - Found in {len(sql_tables)} table(s):\n\n{location_text}"

        total_time = time.time() - start_time
        end_memory = process.memory_info().rss / 1024 / 1024

        print(f"[RAG] Direct table answer returned in {total_time:.2f}s")
        print(f"[RAG] Memory: {start_memory:.1f}MB -> {end_memory:.1f}MB")

        return {
            "answer": answer,
            "sources": list(set(sources + table_locations)),
            "chunks": chunks_with_metadata,
            "confidence": 100.0,
            "confidence_label": "EXACT_MATCH",
            "retrieval_type": "sql_direct",
            "table_count": len(sql_tables)
        }

    # --- LLM CALL (for ChromaDB text results only) ---
    print(f"\n[RAG] Processing ChromaDB results with LLM evaluation...")
    system_prompt = """You are a precise and helpful document assistant.

INSTRUCTIONS:
- Answer questions ONLY using the provided context
-If the answer is not found in the context, say "I don't know based on the provided documents" dont suggest anything not in the context
- Be concise but thorough in your responses
- Never make up information or hallucinate facts
- Quote relevant parts when appropriate
- Structure longer answers with bullet points for clarity
"""

    current_llm = get_current_llm_model()
    print(f"[RAG] Using LLM model: {current_llm}")

    payload = {
        "model": current_llm,
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
        print(f"Memory Usage     : {start_memory:.1f}MB -> {end_memory:.1f}MB (Diff {end_memory - start_memory:+.1f}MB)")
        print(f"CPU Usage        : {process.cpu_percent(interval=0.1):.1f}%")
        print("==================================\n")

        return {
            "answer": answer,
            "sources": list(set(sources)),
            "chunks": chunks_with_metadata,
            "confidence": round(confidence, 1),
            "confidence_label": label,
            "retrieval_type": "vector_semantic"
        }

    except Exception as e:
        return {
            "answer": f"Error connecting to Ollama: {str(e)}",
            "sources": [],
            "chunks": [],
            "confidence": 0,
            "confidence_label": "ERROR",
            "retrieval_type": "error"
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
        # Delete from ChromaDB
        collection.delete(where=where_filter)

        # Delete from tables.db
        delete_tables(doc_id=doc_id, thread_id=thread_id)

        end_time = time.time()
        end_memory = process.memory_info().rss / 1024 / 1024  # MB
        print(f"[RAG] Delete completed in {end_time - start_time:.3f}s")
        print(f"[RESOURCE] Memory: {start_memory:.1f}MB -> {end_memory:.1f}MB (Diff {end_memory - start_memory:+.1f}MB)")

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

        # Get unique sources and max page to determine size
        sources = list(set(f"{m['source']} (Page {m['page']})" for m in metas if m))
        max_page = max([m.get('page', 1) for m in metas if m] or [1])
        total_chunks = len(docs)

        # --- DYNAMIC SIZING LOGIC ---
        # estimating ~3 chunks per page on average
        if total_chunks < 300:
            # Small Document (< ~100 pages)
            scale = "Small"
            chunk_limit = total_chunks # Use all
            word_limit = "150-250"
            detail_level = "concise"
            max_input_chunks = docs
            timeout_seconds = 60
        elif total_chunks < 1500:
            # Medium Document (~100-500 pages)
            scale = "Medium"
            chunk_limit = 30  # Reduced from 50 for better performance
            word_limit = "300-500"
            detail_level = "detailed"
            timeout_seconds = 120  # Increased timeout
            # Sample uniformly to get coverage
            step = max(1, total_chunks // chunk_limit)
            max_input_chunks = docs[::step][:chunk_limit]
        else:
            # Large Document (500+ pages)
            scale = "Large"
            chunk_limit = 40  # Reduced from 80 for better performance
            word_limit = "600-1000"
            detail_level = "comprehensive and extensive"
            timeout_seconds = 180  # Extended timeout for large docs
            # Sample uniformly
            step = max(1, total_chunks // chunk_limit)
            max_input_chunks = docs[::step][:chunk_limit]

        print(f"[SUMMARY] Document Scale: {scale} (Pages: {max_page}, Chunks: {total_chunks})")
        print(f"[SUMMARY] Generating {detail_level} summary ({word_limit} words) using {len(max_input_chunks)} chunks")

        # Combine selected input chunks with safety checks
        valid_chunks = [chunk for chunk in max_input_chunks if chunk and chunk.strip()]
        if not valid_chunks:
            return {"error": "No valid content chunks found for summarization"}

        combined_text = "\n\n".join(valid_chunks)

        # Limit text length based on document scale to prevent API issues
        if scale == "Small":
            max_chars = 4000
        elif scale == "Medium":
            max_chars = 5000  # Reduced from 6000
        else:  # Large
            max_chars = 4500  # Conservative limit for large docs

        if len(combined_text) > max_chars:
            combined_text = combined_text[:max_chars] + "\n... (truncated for processing)"

        print(f"[SUMMARY] Processing {len(combined_text)} characters of content with {timeout_seconds}s timeout")

        # Generate summary via LLM with dynamic prompt
        system_prompt = f"""You are a document summarization expert.
Generate a {detail_level} summary of the document content provided.

INSTRUCTIONS:
- Identify the main topic/purpose of the document
- List key points and important information
- Highlight any critical data, dates, or numbers
- Keep the summary structured and easy to read
- Use bullet points for clarity
- Target length: {word_limit} words

FORMAT YOUR RESPONSE AS:
📄 **Document Overview ({scale} Document):**
[Overview reflecting the scope of the {max_page}-page document]

📌 **Key Points:**
- Point 1
- Point 2
...

📊 **Important Details:**
[Specific data, dates, or critical information]

💡 **Summary:**
[Concluding summary]
"""

        current_llm = get_current_llm_model()
        print(f"[SUMMARY] Using LLM model: {current_llm}")

        payload = {
            "model": current_llm,
            "prompt": f"Document Content ({len(max_input_chunks)} sections):\n{combined_text}\n\nPlease provide a {detail_level} summary:",
            "system": system_prompt,
            "stream": False,
            "temperature": 0.3,
            "options": {
                "num_thread": 8,  # Reduced threads for stability
                "num_ctx": 8192,  # Reduced context window for faster processing
            },
            "keep_alive": "5m",
        }

        llm_start = time.time()

        # Make the request with adaptive timeout
        http_response = requests.post(OLLAMA_API, json=payload, timeout=timeout_seconds)

        if http_response.status_code != 200:
            return {"error": f"Ollama API returned status {http_response.status_code}: {http_response.text}"}

        try:
            response = http_response.json()
        except json.JSONDecodeError as e:
            return {"error": f"Invalid JSON response from Ollama: {e}"}

        llm_time = time.time() - llm_start

        if "error" in response:
            return {"error": f"Ollama error: {response['error']}"}

        summary = response.get("response", "Unable to generate summary.")

        total_time = time.time() - start_time
        print(f"[SUMMARY] [OK] Summary generated in {total_time:.2f}s (LLM: {llm_time:.2f}s)")

        return {
            "summary": summary,
            "chunk_count": len(docs),
            "sources": sources[:10],
            "processing_time": round(total_time, 2),
            "scale": scale
        }

    except requests.exceptions.Timeout:
        return {"error": f"LLM timeout after {timeout_seconds}s - try again or the document may be too large"}
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


