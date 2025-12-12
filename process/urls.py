from django.urls import path
from . import views

urlpatterns = [
    path('', views.home, name='home'),
    path('api/create-thread/', views.create_thread, name='create_thread'),
    path('api/list-threads/', views.list_threads, name='list_threads'),
    path('api/upload/<str:thread_id>/', views.upload_file, name='upload_file'),
    path('api/files/<str:thread_id>/', views.get_thread_files, name='get_thread_files'),
    
    # The AI Chat Endpoint
    path('api/chat/<str:thread_id>/', views.chat_thread, name='chat_thread'),
]