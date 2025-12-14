from django.urls import path
from . import views

urlpatterns = [
    path('', views.home, name='home'),
    path('api/create-thread/', views.create_thread, name='create_thread'),
    path('api/list-threads/', views.list_threads, name='list_threads'),
    path('api/upload/<str:thread_id>/', views.upload_file, name='upload_file'),
    path('api/files/<str:thread_id>/', views.get_thread_files, name='get_thread_files'),
    
    path("api/chat/history/<uuid:thread_id>/", views.get_chat_history),

    # The AI Chat Endpoint
    path('api/chat/<str:thread_id>/', views.chat_thread, name='chat_thread'),

    # Delete Endpoints
    path('api/delete-thread/<str:thread_id>/', views.delete_thread, name='delete_thread'),
    path('api/delete-document/<str:doc_id>/', views.delete_document, name='delete_document'),
]