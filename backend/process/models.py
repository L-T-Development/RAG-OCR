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
    CATEGORY_CHOICES = [
        ('mrls', 'MRLS - Maintenance Repair Level Schedule'),
        ('ispl', 'ISPL - Illustrated Spare Parts List'),
        ('manual', 'Manual - User/Technical Manual'),
        ('catalog', 'Catalog - Parts Catalog'),
        ('specification', 'Specification - Technical Specs'),
        ('drawing', 'Drawing - Engineering Drawing'),
        ('other', 'Other - General Document'),
    ]
    
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    thread = models.ForeignKey(Thread, on_delete=models.CASCADE, related_name='documents')
    file = models.FileField(upload_to='pdfs/')
    filename = models.CharField(max_length=255, blank=True)
    category = models.CharField(max_length=50, choices=CATEGORY_CHOICES, default='other', blank=True)
    uploaded_at = models.DateTimeField(auto_now_add=True)
    is_processed = models.BooleanField(default=False) # To track if vectorization is done
    
    # Document metadata and organization
    tags = models.JSONField(default=list, blank=True)  # List of custom tags: ["Revision A", "Q1-2026", "Approved"]
    notes = models.TextField(blank=True, default='')  # User annotations/comments
    version = models.CharField(max_length=50, blank=True, default='')  # e.g., "v1.0", "Rev A", "2026-Q1"
    revision_date = models.DateTimeField(null=True, blank=True)  # When this version was published
    previous_version = models.ForeignKey(
        'self', 
        on_delete=models.SET_NULL, 
        null=True, 
        blank=True, 
        related_name='next_versions'
    )  # Link to previous document version

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


class ExtractedTable(models.Model):
    """
    Normalized table structure for efficient querying.
    Each table has metadata, with rows and cells stored separately.
    """
    TABLE_TYPE_CHOICES = [
        ('key_value', 'Key-Value Table'),
        ('single_row', 'Single Row Table'),
        ('single_cell', 'Single Cell Table'),
        ('multi_row', 'Multi-Row Table'),
    ]
    
    id = models.CharField(max_length=255, primary_key=True)
    doc_id = models.UUIDField(db_index=True)
    thread = models.ForeignKey(Thread, on_delete=models.CASCADE, related_name='tables', db_index=True)
    parent_thread = models.ForeignKey(
        Thread, 
        on_delete=models.SET_NULL, 
        null=True, 
        blank=True,
        related_name='inherited_tables'
    )
    
    # Location metadata
    source = models.CharField(max_length=500, db_index=True)
    page = models.IntegerField()
    table_index = models.IntegerField()
    
    # Table structure
    row_count = models.IntegerField(default=0)
    column_count = models.IntegerField(default=0)
    
    # Classification and search
    table_type = models.CharField(max_length=20, choices=TABLE_TYPE_CHOICES, db_index=True)
    searchable_text = models.TextField(db_index=True)
    
    # Timestamps
    created_at = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        ordering = ['doc_id', 'page', 'table_index']
        indexes = [
            models.Index(fields=['thread', 'table_type']),
            models.Index(fields=['source', 'page']),
            models.Index(fields=['doc_id', 'page']),
        ]
    
    def __str__(self):
        return f"{self.source} - Page {self.page} - Table {self.table_index} ({self.table_type})"
    
    @classmethod
    def search_by_keywords(cls, keywords, thread_id, source_filter=None):
        """Search tables by keywords using Django ORM."""
        from django.db.models import Q
        
        query = Q(thread_id=thread_id)
        
        if source_filter:
            query &= Q(source=source_filter)
        
        keyword_query = Q()
        for keyword in keywords:
            if len(keyword) > 3:
                keyword_query |= Q(searchable_text__icontains=keyword)
        
        if keyword_query:
            query &= keyword_query
        
        return cls.objects.filter(query).prefetch_related('rows__cells')
    
    @classmethod
    def search_in_cells(cls, keywords, thread_id, source_filter=None):
        """
        Search directly in table cells for precise matching.
        Particularly effective for single-instance tables.
        """
        from django.db.models import Q
        
        # Find tables that have cells matching keywords
        cell_query = Q()
        for keyword in keywords:
            if len(keyword) > 2:  # Lower threshold for cell search
                cell_query |= Q(rows__cells__value__icontains=keyword)
        
        base_query = Q(thread_id=thread_id)
        if source_filter:
            base_query &= Q(source=source_filter)
        
        if cell_query:
            base_query &= cell_query
        
        # Use distinct() to avoid duplicates from multiple matching cells
        return cls.objects.filter(base_query).prefetch_related('rows__cells').distinct()
    
    @classmethod
    def search_key_value(cls, key_term, thread_id, source_filter=None):
        """
        Search for key-value pairs in key_value type tables.
        Returns tables where the key column matches the search term.
        """
        from django.db.models import Q
        
        query = Q(
            thread_id=thread_id,
            table_type='key_value',
            rows__cells__is_key=True,
            rows__cells__value__icontains=key_term
        )
        
        if source_filter:
            query &= Q(source=source_filter)
        
        return cls.objects.filter(query).prefetch_related('rows__cells').distinct()
    
    @classmethod
    def get_colocated_tables(cls, thread_id, source_page_pairs):
        """Get tables from same pages as retrieved text chunks."""
        from django.db.models import Q
        
        if not source_page_pairs:
            return cls.objects.none()
        
        query = Q(thread_id=thread_id)
        
        page_query = Q()
        for source, page in source_page_pairs:
            page_query |= Q(source=source, page=page)
        
        query &= page_query
        
        return cls.objects.filter(query).prefetch_related('rows__cells')
    
    def to_dict(self):
        """Convert to dictionary with full table data."""
        rows = self.rows.all().order_by('row_index')
        
        headers = []
        data = []
        
        for row in rows:
            cells = row.cells.all().order_by('column_index')
            row_data = [cell.value for cell in cells]
            
            if row.is_header:
                headers = row_data
            else:
                data.append(row_data)
        
        # Reconstruct full table_data format
        table_data = [headers] + data if headers else data
        
        return {
            "id": self.id,
            "source": self.source,
            "page": self.page,
            "table_index": self.table_index,
            "headers": headers,
            "row_count": self.row_count,
            "column_count": self.column_count,
            "data": table_data,
            "table_type": self.table_type,
        }


class TableRow(models.Model):
    """Individual row in a table."""
    table = models.ForeignKey(ExtractedTable, on_delete=models.CASCADE, related_name='rows')
    row_index = models.IntegerField()
    is_header = models.BooleanField(default=False)
    
    class Meta:
        ordering = ['table', 'row_index']
        unique_together = [['table', 'row_index']]
        indexes = [
            models.Index(fields=['table', 'row_index']),
        ]
    
    def __str__(self):
        return f"{self.table.id} - Row {self.row_index}"


class TableCell(models.Model):
    """Individual cell in a table row."""
    row = models.ForeignKey(TableRow, on_delete=models.CASCADE, related_name='cells')
    column_index = models.IntegerField()
    column_name = models.CharField(max_length=255, blank=True)
    value = models.TextField(blank=True)
    
    # For efficient key-value lookups
    is_key = models.BooleanField(default=False, db_index=True)
    
    class Meta:
        ordering = ['row', 'column_index']
        unique_together = [['row', 'column_index']]
        indexes = [
            models.Index(fields=['row', 'column_index']),
            models.Index(fields=['is_key', 'value']),
        ]
    
    def __str__(self):
        return f"{self.row.table.id} - Row {self.row.row_index} - Col {self.column_index}: {self.value[:50]}"