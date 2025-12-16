from django.db import models
import uuid

class Thread(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=255)
    created_at = models.DateTimeField(auto_now_add=True)
    parent = models.ForeignKey(
        'self', 
        on_delete=models.CASCADE, 
        null=True, 
        blank=True, 
        related_name='sub_threads'
    )

    def __str__(self):
        return self.name

class Document(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    thread = models.ForeignKey(Thread, on_delete=models.CASCADE, related_name='documents')
    file = models.FileField(upload_to='pdfs/')
    filename = models.CharField(max_length=255, blank=True)
    uploaded_at = models.DateTimeField(auto_now_add=True)
    is_processed = models.BooleanField(default=False) # To track if vectorization is done

    def save(self, *args, **kwargs):
        if not self.filename:
            self.filename = self.file.name
        super().save(*args, **kwargs)

# OPTIONAL: To save chat history in the DB
class ChatMessage(models.Model):
    thread = models.ForeignKey(Thread, on_delete=models.CASCADE, related_name='messages')
    role = models.CharField(max_length=10, choices=[('user', 'User'), ('ai', 'AI')])
    content = models.TextField()
    timestamp = models.DateTimeField(auto_now_add=True)
    
    # AI response metadata (only for AI messages)
    sources = models.JSONField(default=list, blank=True)  # List of source strings
    chunks = models.JSONField(default=list, blank=True)   # List of chunk objects with text, source, page, similarity
    confidence = models.FloatField(null=True, blank=True)  # Confidence percentage 0-100
    confidence_label = models.CharField(max_length=20, blank=True, default='')  # HIGH/MEDIUM/LOW