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

    path("api/compare-documents/", views.compare_documents),
    path("api/compare/status/<str:job_id>/", views.compare_status),
    
    # Document Summary Endpoints
    path('api/summarize/thread/<str:thread_id>/', views.summarize_thread_documents, name='summarize_thread'),
    path('api/summarize/document/<str:doc_id>/', views.summarize_single_document, name='summarize_document'),
    path('api/thread-info/<str:thread_id>/', views.get_thread_info, name='thread_info'),
    
    # Model Configuration Endpoints
    path('api/model/status/', views.model_status, name='model_status'),
    path('api/model/configure/', views.model_configure, name='model_configure'),
    path('api/model/validate/', views.model_validate, name='model_validate'),
    path('api/config/', views.get_app_config, name='app_config'),
]