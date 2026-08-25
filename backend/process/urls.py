from django.urls import path
from . import views


# API URLs only - Frontend is served by React/Vite
urlpatterns = [
    # Legacy HTML views (can be removed once fully migrated to React)
    # path('', views.home, name='home'),
    # path("compare/", views.compare_page, name="compare"),

    # API Endpoints
    path('api/create-thread/', views.create_thread, name='create_thread'),
    path('api/list-threads/', views.list_threads, name='list_threads'),
    path('api/upload/<str:thread_id>/', views.upload_file, name='upload_file'),
    path('api/quick-upload/', views.quick_upload, name='quick_upload'),
    path('api/files/<str:thread_id>/', views.get_thread_files, name='get_thread_files'),

    path("api/chat/history/<uuid:thread_id>/", views.get_chat_history),

    # The AI Chat Endpoint
    path('api/chat/<str:thread_id>/', views.chat_thread, name='chat_thread'),

    # Delete Endpoints
    path('api/delete-thread/<str:thread_id>/', views.delete_thread, name='delete_thread'),
    path('api/delete-document/<str:doc_id>/', views.delete_document, name='delete_document'),
    
    # Document Metadata & Progress Endpoints
    path('api/documents/<str:doc_id>/progress/', views.document_progress, name='document_progress'),
    path('api/documents/<str:doc_id>/metadata/', views.document_metadata, name='document_metadata'),
    path('api/documents/<str:doc_id>/link-version/', views.link_document_version, name='link_version'),
    path('api/documents/<str:doc_id>/versions/', views.document_version_history, name='version_history'),

    path("api/compare-documents/", views.compare_documents),
    path("api/compare/status/<str:job_id>/", views.compare_status),
    path("api/comparison/confirm-match/", views.confirm_comparison_match, name="confirm_comparison_match"),
    path("api/field-schema/", views.field_schema_view, name="field_schema"),
    path("api/documents/<str:doc_id>/extraction/", views.document_extraction_view, name="document_extraction"),
    path("api/comparison/run/", views.run_comparison_view, name="run_comparison"),
    path("api/decisions/export/", views.export_decisions_view, name="export_decisions"),
    path("api/decisions/import/", views.import_decisions_view, name="import_decisions"),
    path("api/decisions/backup/", views.backup_data_view, name="backup_data"),
    path("api/documents/<str:doc_id>/columns/", views.document_columns, name="document_columns"),

    # Document Summary Endpoints
    path('api/summarize/thread/<str:thread_id>/', views.summarize_thread_documents, name='summarize_thread'),
    path('api/summarize/document/<str:doc_id>/', views.summarize_single_document, name='summarize_document'),
    path('api/thread-info/<str:thread_id>/', views.get_thread_info, name='thread_info'),

    # Model Configuration Endpoints
    path('api/model/status/', views.model_status, name='model_status'),
    path('api/model/configure/', views.model_configure, name='model_configure'),
    path('api/model/validate/', views.model_validate, name='model_validate'),
    path('api/model/reembed-status/', views.reembed_status, name='reembed_status'),
    path('api/embedding/configure/', views.embedding_provider_configure, name='embedding_provider_configure'),
    path('api/config/', views.get_app_config, name='app_config'),

    # LLM Model Selection Endpoints
    path('api/llm/models/', views.llm_models_list, name='llm_models_list'),
    path('api/llm/select/', views.llm_model_select, name='llm_model_select'),

    # Ollama installed models
    path('api/ollama/models/', views.ollama_models_list, name='ollama_models_list'),

    # ==================== REPORTS / COMPARATOR ENDPOINTS ====================
    path('api/reports/columns/', views.get_columns_from_file, name='get_columns'),
    path('api/reports/column-preview/', views.get_column_preview_view, name='column_preview'),
    path('api/reports/multi-pdf-columns/', views.get_multi_pdf_columns_preview, name='multi_pdf_columns'),
    path('api/reports/compare/', views.start_multi_pdf_comparison, name='multi_pdf_compare'),
    path('api/reports/compare-single/', views.start_single_pdf_comparison, name='single_pdf_compare'),
    path('api/reports/status/<str:job_id>/', views.get_report_status, name='report_status'),
    path('api/reports/quick-compare/', views.quick_column_compare, name='quick_compare'),
    path('api/reports/download/<str:job_id>/', views.download_report, name='download_report'),
]
