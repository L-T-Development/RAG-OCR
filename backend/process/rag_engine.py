# ── Compatibility shim ────────────────────────────────────────────────────────
# All logic now lives in process/pipeline/. This file re-exports the full
# public API so that views.py and apps.py continue to work unchanged.

from .pipeline import (
    # constants (apps.py reads these as rag_engine.CONSTANT)
    CHROMA_PATH,
    OLLAMA_API,
    OLLAMA_EMBED_API,
    DEFAULT_LLM_MODEL,
    DEFAULT_EMBEDDING_PROVIDER,
    DEFAULT_OLLAMA_EMBEDDING_MODEL,
    CANDIDATE_K,
    MAX_FINAL_CHUNKS,
    CHROMA_BATCH_SIZE,
    EMBEDDING_BATCH_SIZE,
    AVAILABLE_LLM_MODELS,
    CUDA_AVAILABLE,

    # LLM model helpers
    get_current_llm_model,
    set_llm_model,
    get_llm_models_list,

    # Embedding model manager (apps.py calls rag_engine.model_manager directly)
    OllamaEmbeddingProvider,
    EmbeddingModelManager,
    model_manager,
    get_model_status,
    configure_embedding_provider,
    configure_model_path,
    validate_model_path,
    get_reembed_status,
    reembed_collection,

    # Storage
    get_collection,
    delete_from_chroma,

    # Table utilities
    classify_table_type,
    generate_searchable_text,
    store_table,
    delete_tables,
    get_ancestor_ids,
    extract_search_terms,
    search_tables,
    compare_tables,
    cross_doc_search,

    # Ingestion
    smart_chunk_text,
    process_document,
    process_pdf,
    process_excel,
    process_word,
    process_image,
    extract_pdf_title,

    # Query
    extract_file_filter,
    query_rag,

    # Summary
    summarize_document,
    get_thread_documents_summary,
)

# Alias used by some views
get_all_ancestor_thread_ids = get_ancestor_ids
