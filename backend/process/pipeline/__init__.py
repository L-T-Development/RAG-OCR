# Public API — everything rag_engine.py (and apps.py) needs to import.

from .config import (
    CHROMA_PATH,
    BM25_INDEX_PATH,
    OLLAMA_API,
    OLLAMA_EMBED_API,
    OLLAMA_EMBED_BATCH_API,
    DEFAULT_LLM_MODEL,
    DEFAULT_EMBEDDING_PROVIDER,
    DEFAULT_OLLAMA_EMBEDDING_MODEL,
    CANDIDATE_K,
    MAX_FINAL_CHUNKS,
    CHROMA_BATCH_SIZE,
    EMBEDDING_BATCH_SIZE,
    AVAILABLE_LLM_MODELS,
    get_current_llm_model,
    set_llm_model,
    get_llm_models_list,
)

from .embedding import (
    OllamaEmbeddingProvider,
    EmbeddingModelManager,
    model_manager,
    get_model_status,
    configure_embedding_provider,
    configure_model_path,
    validate_model_path,
    get_reembed_status,
    reembed_collection,
)

from .bm25 import bm25_index

from .storage import (
    get_collection,
    delete_from_chroma,
)

from .tables import (
    classify_table_type,
    generate_searchable_text,
    store_table,
    delete_tables,
    get_ancestor_ids,
    extract_search_terms,
    search_tables,
    compare_tables,
    cross_doc_search,
    extract_column_values,
    compare_columns,
    compare_columns_multi,
)

from .ingestion import (
    smart_chunk_text,
    process_document,
    process_pdf,
    process_excel,
    process_word,
    process_image,
    extract_pdf_title,
)

from .query import (
    extract_file_filter,
    query_rag,
)

from .summary import (
    summarize_document,
    get_thread_documents_summary,
)

__all__ = [
    # config
    "CHROMA_PATH", "BM25_INDEX_PATH", "OLLAMA_API", "OLLAMA_EMBED_API", "OLLAMA_EMBED_BATCH_API",
    "bm25_index",
    "DEFAULT_LLM_MODEL", "DEFAULT_EMBEDDING_PROVIDER",
    "DEFAULT_OLLAMA_EMBEDDING_MODEL",
    "CANDIDATE_K", "MAX_FINAL_CHUNKS", "CHROMA_BATCH_SIZE", "EMBEDDING_BATCH_SIZE",
    "AVAILABLE_LLM_MODELS",
    "get_current_llm_model", "set_llm_model", "get_llm_models_list",
    # embedding
    "OllamaEmbeddingProvider", "EmbeddingModelManager", "model_manager",
    "get_model_status", "configure_embedding_provider", "configure_model_path",
    "validate_model_path", "get_reembed_status", "reembed_collection",
    # storage
    "get_collection", "delete_from_chroma",
    # tables
    "classify_table_type", "generate_searchable_text", "store_table", "delete_tables",
    "get_ancestor_ids", "extract_search_terms", "search_tables",
    "compare_tables", "cross_doc_search", "extract_column_values", "compare_columns",
    "compare_columns_multi",
    # ingestion
    "smart_chunk_text", "process_document", "process_pdf", "process_excel",
    "process_word", "process_image", "extract_pdf_title",
    # query
    "extract_file_filter", "query_rag",
    # summary
    "summarize_document", "get_thread_documents_summary",
]
