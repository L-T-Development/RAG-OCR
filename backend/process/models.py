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


class AppConfig(models.Model):
    """Singleton model for application configuration including model paths"""
    key = models.CharField(max_length=100, unique=True, primary_key=True)
    value = models.TextField()
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Application Configuration"
        verbose_name_plural = "Application Configurations"

    def __str__(self):
        return f"{self.key}: {self.value[:50]}"

    @classmethod
    def get_value(cls, key, default=None):
        """Get a config value by key"""
        try:
            return cls.objects.get(key=key).value
        except cls.DoesNotExist:
            return default

    @classmethod
    def set_value(cls, key, value):
        """Set a config value by key"""
        obj, created = cls.objects.update_or_create(
            key=key,
            defaults={'value': value}
        )
        return obj


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