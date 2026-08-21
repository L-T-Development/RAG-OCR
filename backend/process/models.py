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
    is_processed = models.BooleanField(default=False)

    # Ingestion progress tracking
    STATUS_CHOICES = [
        ("pending",    "Pending"),
        ("processing", "Processing"),
        ("done",       "Done"),
        ("error",      "Error"),
    ]
    status          = models.CharField(max_length=20, choices=STATUS_CHOICES, default="pending", db_index=True)
    progress        = models.IntegerField(default=0)          # 0-100
    progress_detail = models.CharField(max_length=255, blank=True, default="")
    error_message   = models.TextField(blank=True, default="")
    
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
    caption = models.CharField(max_length=500, blank=True, default="")  # section heading / sheet name
    
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
            "caption": self.caption,
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


class ConfirmedMatch(models.Model):
    """
    A user-confirmed "these are the same item, written differently" pairing
    between two documents' comparison values (e.g. "NAMP-08020000" in one file
    is the same part as "DIC-NAMP-08020000" in another).

    Deterministic matching rules (leading zeros, annotation containment, typo
    tolerance) only catch patterns anticipated in advance; this lets a human
    confirmation stick permanently for whatever they don't catch, without
    re-litigating it on every future comparison of the same two documents.
    """
    source_a = models.CharField(max_length=500, db_index=True)
    source_b = models.CharField(max_length=500, db_index=True)
    # Canonical field key (e.g. "part_no") when the compared column maps to one
    # of the known concepts, else the raw column text the user compared on.
    # Scopes a confirmation to the concept it was made for, so a part-number
    # alias never leaks into a drawing-number comparison of the same files.
    column_key = models.CharField(max_length=255, db_index=True)
    value_a = models.CharField(max_length=255)  # normalized, matches source_a's side
    value_b = models.CharField(max_length=255)  # normalized, matches source_b's side
    note = models.CharField(max_length=500, blank=True, default="")
    thread = models.ForeignKey(Thread, on_delete=models.SET_NULL, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [
            models.Index(fields=['source_a', 'source_b', 'column_key']),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=['source_a', 'source_b', 'column_key', 'value_a', 'value_b'],
                name='unique_confirmed_match',
            )
        ]

    def __str__(self):
        return f"{self.value_a} = {self.value_b} ({self.source_a} vs {self.source_b})"

class DocumentPageText(models.Model):
    """
    Searchable plain text of one page of one document.

    Prose lives only in ChromaDB (as embedded chunks), which cannot answer
    "does the string XL17461 appear in this manual?" — so a spares list could
    only ever be compared against another document's *table columns*. Technical
    manuals mention part numbers in running text, figure callouts and notes, and
    those mentions were invisible to comparison.

    Two forms of the text are stored because PDF extraction drops spaces when a
    cell or line wraps ("BIG LAUNCHER PAD" → "BIG LAUNCHERPAD"): the whitespace-
    collapsed form and the whitespace-free form. Checking a value against both
    recovers those without loosening the match.
    """
    KIND_CHOICES = [('text', 'Prose / paragraph text'), ('table', 'Table cell text')]

    doc_id = models.CharField(max_length=255, db_index=True)
    thread_id = models.CharField(max_length=255, db_index=True)
    parent_thread_id = models.CharField(max_length=255, null=True, blank=True, db_index=True)
    source = models.CharField(max_length=500, db_index=True)
    page = models.IntegerField(default=1)
    kind = models.CharField(max_length=10, choices=KIND_CHOICES, default='text')
    text_norm = models.TextField(blank=True, default='')      # upper-case, single-spaced
    text_nospace = models.TextField(blank=True, default='')   # upper-case, no whitespace
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [models.Index(fields=['doc_id', 'page'])]
        constraints = [
            models.UniqueConstraint(fields=['doc_id', 'page', 'kind'],
                                    name='unique_page_text_per_doc'),
        ]

    def __str__(self):
        return f"{self.source} p{self.page} ({self.kind})"


class IdentifierMention(models.Model):
    """
    One identifier-shaped token (part/drawing/stock number …) as it appears in a
    document, with the page it was seen on.

    This is the index that answers "is every spare in the MRLS mentioned anywhere
    in the manual?" in one query instead of re-parsing PDFs per comparison. It is
    populated from BOTH prose chunks and table cells, so a part mentioned only in
    a paragraph still counts as found.

    Deliberately not a foreign key to Document: ingestion writes these from a
    background thread keyed by the same string doc_id the table store uses.
    """
    KIND_CHOICES = DocumentPageText.KIND_CHOICES

    doc_id = models.CharField(max_length=255, db_index=True)
    thread_id = models.CharField(max_length=255, db_index=True)
    parent_thread_id = models.CharField(max_length=255, null=True, blank=True, db_index=True)
    source = models.CharField(max_length=500, db_index=True)
    value_norm = models.CharField(max_length=255, db_index=True)     # normalize_value()
    value_nospace = models.CharField(max_length=255, db_index=True)  # normalize_value() minus spaces
    value_raw = models.CharField(max_length=255, blank=True, default='')
    page = models.IntegerField(default=1)
    kind = models.CharField(max_length=10, choices=KIND_CHOICES, default='text')
    occurrences = models.IntegerField(default=1)

    class Meta:
        indexes = [
            models.Index(fields=['doc_id', 'value_norm']),
            models.Index(fields=['value_norm']),
            models.Index(fields=['doc_id', 'value_nospace']),
        ]
        constraints = [
            models.UniqueConstraint(fields=['doc_id', 'value_norm', 'page', 'kind'],
                                    name='unique_mention_per_doc_page'),
        ]

    def __str__(self):
        return f"{self.value_norm} @ {self.source} p{self.page}"


class ColumnRole(models.Model):
    """
    A human's decision about which real column of one document holds a concept.

    Header resolution (field_schema) covers every label we have seen, and value
    shape (column_profile) can spot identifier columns but cannot tell a part
    number from a stock number. When both fall short — a new document family, a
    header lost to a bad extraction — the person looking at the document knows the
    answer, and this is where they record it once instead of quoting the header in
    every query.

    Only *user* decisions live here. Schema-derived resolutions are recomputed on
    demand rather than cached, so improving field_schema.json immediately improves
    every document instead of leaving stale rows behind. A row here therefore
    always wins over the schema — that is its entire purpose.
    """
    doc_id = models.CharField(max_length=255, db_index=True)
    source = models.CharField(max_length=500, blank=True, default='')
    thread_id = models.CharField(max_length=255, blank=True, default='', db_index=True)
    # Canonical concept key from field_schema.CANONICAL_FIELDS (e.g. "part_no").
    field = models.CharField(max_length=64, db_index=True)
    # The column header exactly as it appears in the document's tables.
    header_text = models.CharField(max_length=500)
    note = models.CharField(max_length=500, blank=True, default='')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=['doc_id', 'field'], name='unique_column_role_per_doc'),
        ]

    def __str__(self):
        return f"{self.source or self.doc_id}: {self.field} -> {self.header_text}"
