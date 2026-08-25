import { useRef, useState } from 'react';
import {
  FileText,
  Upload,
  Trash2,
  FileUp,
  Loader2,
  FolderOpen,
  Sparkles,
  FileSpreadsheet,
  File,
  Tag,
  FileImage,
  Edit3,
  Save,
  X,
  ChevronDown,
  ChevronRight,
  Clock,
  MessageSquare, GitCompare } from 'lucide-react';
import { CategorySelector } from './CategorySelector';
import { api } from '../../services/api';

// Supported file extensions for chat
const SUPPORTED_EXTENSIONS = ['.pdf', '.xlsx', '.xls', '.docx', '.jpg', '.jpeg', '.png', '.bmp', '.tiff', '.tif'];

// Document categories
const DOCUMENT_CATEGORIES = [
  { value: 'mrls', label: '🔧 MRLS - Maintenance Repair', color: '#ef4444' },
  { value: 'ispl', label: '📋 ISPL - Spare Parts List', color: '#3b82f6' },
  { value: 'manual', label: '📖 Manual - User Guide', color: '#10b981' },
  { value: 'catalog', label: '📚 Catalog - Parts Catalog', color: '#f59e0b' },
  { value: 'specification', label: '📐 Specification - Tech Specs', color: '#8b5cf6' },
  { value: 'drawing', label: '🎨 Drawing - Engineering', color: '#06b6d4' },
  { value: 'other', label: '📄 Other - General Document', color: '#6b7280' },
];

function getCategoryColor(category) {
  const cat = DOCUMENT_CATEGORIES.find(c => c.value === category);
  return cat?.color || '#6b7280';
}

function getCategoryBadge(category, label) {
  const color = getCategoryColor(category);
  return (
    <span
      className="inline-flex items-center gap-1 px-1.5 py-0.5 rounded text-[10px] font-medium"
      style={{
        backgroundColor: `${color}15`,
        color: color,
        border: `1px solid ${color}30`
      }}
    >
      <Tag size={10} />
      {label || category}
    </span>
  );
}

function getFileIcon(filename) {
  const ext = filename?.toLowerCase().split('.').pop();
  if (ext === 'pdf') return <FileText size={18} style={{ color: '#ef4444' }} />;
  if (ext === 'xlsx' || ext === 'xls') return <FileSpreadsheet size={18} style={{ color: '#10b981' }} />;
  if (ext === 'docx') return <File size={18} style={{ color: '#3b82f6' }} />;
  if (ext === 'jpg' || ext === 'jpeg' || ext === 'png' || ext === 'bmp' || ext === 'tiff' || ext === 'tif')
    return <FileImage size={18} style={{ color: '#f59e0b' }} />;
  return <FileText size={18} />;
}

function DocumentCard({ document, onDelete, onSummarize, isUploading = false }) {
  const [isExpanded, setIsExpanded] = useState(false);
  const [isEditing, setIsEditing] = useState(false);
  const [metadata, setMetadata] = useState({
    tags: document.tags || [],
    notes: document.notes || '',
    version: document.version || '',
    revision_date: document.revision_date || ''
  });
  const [newTag, setNewTag] = useState('');
  const [isSaving, setIsSaving] = useState(false);

  const handleSaveMetadata = async () => {
    setIsSaving(true);
    try {
      const result = await api.updateDocumentMetadata(document.id, metadata);
      if (result.ok) {
        setIsEditing(false);
      }
    } catch (error) {
      console.error('Failed to save metadata:', error);
      alert('Failed to save metadata');
    } finally {
      setIsSaving(false);
    }
  };

  const handleAddTag = () => {
    if (newTag.trim() && !metadata.tags?.includes(newTag.trim())) {
      setMetadata(prev => ({ ...prev, tags: [...(prev.tags || []), newTag.trim()] }));
      setNewTag('');
    }
  };

  const handleRemoveTag = (tagToRemove) => {
    setMetadata(prev => ({ ...prev, tags: prev.tags?.filter(t => t !== tagToRemove) || [] }));
  };

  return (
    <div
      className={`rounded-lg border transition-colors
        ${isUploading ? 'border-[var(--color-border-light)] opacity-70' : 'border-[var(--color-border)]'}
        ${isExpanded ? 'border-[var(--color-border-focus)]' : ''}
        bg-[var(--color-bg-secondary)]`}
    >
      {/* Main row */}
      <div
        className="flex items-center gap-2 p-2.5 cursor-pointer group"
        onClick={() => !isUploading && setIsExpanded(!isExpanded)}
      >
        {/* Expand chevron */}
        <button className="flex-shrink-0 text-[var(--color-text-muted)] hover:text-[var(--color-text-primary)] transition-colors">
          {isExpanded ? <ChevronDown size={16} /> : <ChevronRight size={16} />}
        </button>

        {/* File icon */}
        <div className="flex-shrink-0">
          {isUploading ? <Loader2 size={18} className="animate-spin text-primary" /> : getFileIcon(document.name)}
        </div>

        {/* Info */}
        <div className="flex-1 min-w-0">
          <div
            className="text-xs font-medium text-[var(--color-text-primary)] truncate"
            title={document.name}
          >
            {document.name}
          </div>
          <div className="flex items-center flex-wrap gap-1 mt-0.5">
            {isUploading ? (
              <span className="text-[10px] text-[var(--color-text-muted)]">Processing...</span>
            ) : (
              <>
                {document.category && getCategoryBadge(document.category, document.category_label)}
                {metadata.version && (
                  <span className="inline-flex items-center gap-0.5 text-[10px] text-[var(--color-text-muted)]" title="Version">
                    <Clock size={10} />
                    {metadata.version}
                  </span>
                )}
                {metadata.tags?.length > 0 && (
                  <span className="inline-flex items-center gap-0.5 text-[10px] text-[var(--color-text-muted)]" title={metadata.tags.join(', ')}>
                    <Tag size={10} />
                    {metadata.tags.length}
                  </span>
                )}
                {document.is_inherited && (
                  <span className="inline-flex items-center px-1.5 py-0.5 rounded text-[10px] bg-[var(--color-bg-tertiary)] text-[var(--color-text-muted)]">
                    Inherited
                  </span>
                )}
              </>
            )}
          </div>
          {isUploading && (
            <div className="mt-1.5 h-1 rounded-full bg-[var(--color-bg-tertiary)] overflow-hidden">
              <div className="h-full w-3/5 rounded-full bg-primary transition-all" />
            </div>
          )}
        </div>

        {/* Action buttons */}
        {!isUploading && (
          <div
            className="flex items-center gap-0.5 opacity-0 group-hover:opacity-100 transition-opacity flex-shrink-0"
            onClick={(e) => e.stopPropagation()}
          >
            {onSummarize && (
              <button
                className="flex items-center justify-center w-6 h-6 rounded hover:bg-primary-light hover:text-primary text-[var(--color-text-muted)] transition-colors"
                onClick={() => onSummarize(document.id)}
                title="Summarize document"
              >
                <Sparkles size={14} />
              </button>
            )}
            {!document.is_inherited && (
              <button
                className="flex items-center justify-center w-6 h-6 rounded hover:bg-red-100 hover:text-red-500 text-[var(--color-text-muted)] transition-colors"
                onClick={() => onDelete(document.id)}
                title="Delete document"
              >
                <Trash2 size={14} />
              </button>
            )}
          </div>
        )}
      </div>

      {/* Metadata panel */}
      {isExpanded && !isUploading && (
        <div
          className="border-t border-[var(--color-border)] p-3 bg-[var(--color-bg-primary)] rounded-b-lg"
          onClick={(e) => e.stopPropagation()}
        >
          {/* Metadata header */}
          <div className="flex items-center justify-between mb-3">
            <h4 className="text-xs font-semibold text-[var(--color-text-secondary)] uppercase tracking-wider m-0">
              Document Metadata
            </h4>
            {!isEditing ? (
              <button
                className="flex items-center gap-1 px-2 py-0.5 rounded text-xs text-[var(--color-text-secondary)] hover:bg-[var(--color-bg-hover)] transition-colors cursor-pointer border-0 bg-transparent"
                onClick={() => setIsEditing(true)}
                title="Edit metadata"
              >
                <Edit3 size={14} />
                Edit
              </button>
            ) : (
              <div className="flex items-center gap-1">
                <button
                  className="flex items-center gap-1 px-2 py-0.5 rounded text-xs bg-primary hover:bg-primary-hover text-white transition-colors cursor-pointer border-0 disabled:opacity-50"
                  onClick={handleSaveMetadata}
                  disabled={isSaving}
                  title="Save changes"
                >
                  {isSaving ? <Loader2 size={14} className="animate-spin" /> : <Save size={14} />}
                  Save
                </button>
                <button
                  className="flex items-center justify-center w-6 h-6 rounded text-[var(--color-text-muted)] hover:bg-[var(--color-bg-hover)] hover:text-[var(--color-text-primary)] transition-colors cursor-pointer border-0 bg-transparent"
                  onClick={() => {
                    setIsEditing(false);
                    setMetadata({
                      tags: document.tags || [],
                      notes: document.notes || '',
                      version: document.version || '',
                      revision_date: document.revision_date || ''
                    });
                  }}
                  title="Cancel"
                >
                  <X size={14} />
                </button>
              </div>
            )}
          </div>

          {/* Version field */}
          <div className="mb-3">
            <label className="flex items-center gap-1 text-[10px] font-semibold uppercase tracking-wider text-[var(--color-text-muted)] mb-1">
              <Clock size={12} /> Version
            </label>
            {isEditing ? (
              <input
                type="text"
                value={metadata.version}
                onChange={(e) => setMetadata(prev => ({ ...prev, version: e.target.value }))}
                placeholder="e.g., v1.0, Rev A"
                className="w-full text-xs px-2 py-1.5 rounded border border-[var(--color-border)] bg-[var(--color-bg-secondary)] text-[var(--color-text-primary)] placeholder:text-[var(--color-text-muted)] focus:outline-none focus:border-[var(--color-border-focus)]"
              />
            ) : (
              <span className="text-xs text-[var(--color-text-secondary)]">
                {metadata.version || 'Not set'}
              </span>
            )}
          </div>

          {/* Tags field */}
          <div className="mb-3">
            <label className="flex items-center gap-1 text-[10px] font-semibold uppercase tracking-wider text-[var(--color-text-muted)] mb-1">
              <Tag size={12} /> Tags
            </label>
            <div className="flex flex-wrap gap-1">
              {metadata.tags?.map((tag, idx) => (
                <span
                  key={idx}
                  className="inline-flex items-center gap-0.5 px-1.5 py-0.5 rounded-full bg-[var(--color-bg-tertiary)] text-[10px] text-[var(--color-text-secondary)]"
                >
                  {tag}
                  {isEditing && (
                    <button
                      onClick={() => handleRemoveTag(tag)}
                      className="ml-0.5 hover:text-red-500 transition-colors cursor-pointer border-0 bg-transparent p-0 flex items-center"
                    >
                      <X size={10} />
                    </button>
                  )}
                </span>
              ))}
              {isEditing && (
                <div className="flex items-center gap-1 mt-1 w-full">
                  <input
                    type="text"
                    value={newTag}
                    onChange={(e) => setNewTag(e.target.value)}
                    onKeyPress={(e) => e.key === 'Enter' && handleAddTag()}
                    placeholder="Add tag..."
                    className="flex-1 text-xs px-2 py-1 rounded border border-[var(--color-border)] bg-[var(--color-bg-secondary)] text-[var(--color-text-primary)] placeholder:text-[var(--color-text-muted)] focus:outline-none focus:border-[var(--color-border-focus)]"
                  />
                  <button
                    onClick={handleAddTag}
                    className="flex items-center justify-center w-6 h-6 rounded bg-primary hover:bg-primary-hover text-white text-sm font-bold cursor-pointer border-0"
                  >
                    +
                  </button>
                </div>
              )}
            </div>
          </div>

          {/* Notes field */}
          <div>
            <label className="flex items-center gap-1 text-[10px] font-semibold uppercase tracking-wider text-[var(--color-text-muted)] mb-1">
              <MessageSquare size={12} /> Notes
            </label>
            {isEditing ? (
              <textarea
                value={metadata.notes}
                onChange={(e) => setMetadata(prev => ({ ...prev, notes: e.target.value }))}
                placeholder="Add notes or comments about this document..."
                className="w-full text-xs px-2 py-1.5 rounded border border-[var(--color-border)] bg-[var(--color-bg-secondary)] text-[var(--color-text-primary)] placeholder:text-[var(--color-text-muted)] focus:outline-none focus:border-[var(--color-border-focus)] resize-none leading-relaxed"
                rows={3}
              />
            ) : (
              <span className="text-xs text-[var(--color-text-secondary)] leading-relaxed whitespace-pre-wrap">
                {metadata.notes || 'No notes'}
              </span>
            )}
          </div>
        </div>
      )}
    </div>
  );
}

export function DocumentPanel({
  documents = [],
  onUpload,
  onDelete,
  onSummarize,
  onCompare,
  disabled = false,
  isUploading = false,
  uploadProgress = 0,
  uploadStatus = ''
}) {
  const fileInputRef = useRef(null);
  const [selectedFile, setSelectedFile] = useState(null);
  const [selectedCategory, setSelectedCategory] = useState('other');
  const [showCategoryModal, setShowCategoryModal] = useState(false);

  const handleFileChange = (e) => {
    const file = e.target.files[0];
    if (file) {
      const ext = '.' + file.name.toLowerCase().split('.').pop();
      if (SUPPORTED_EXTENSIONS.includes(ext)) {
        setSelectedFile(file);
        setShowCategoryModal(true);

        const filename = file.name.toLowerCase();
        if (filename.includes('mrls') || filename.includes('mrl')) {
          setSelectedCategory('mrls');
        } else if (filename.includes('ispl') || filename.includes('isp')) {
          setSelectedCategory('ispl');
        } else if (filename.includes('manual')) {
          setSelectedCategory('manual');
        } else if (filename.includes('catalog')) {
          setSelectedCategory('catalog');
        } else if (filename.includes('spec')) {
          setSelectedCategory('specification');
        } else if (filename.includes('drawing') || filename.includes('dwg')) {
          setSelectedCategory('drawing');
        } else {
          setSelectedCategory('other');
        }
      } else {
        alert(`Unsupported file type. Supported: ${SUPPORTED_EXTENSIONS.join(', ')}`);
      }
      e.target.value = '';
    }
  };

  const handleCategorySelect = (category) => {
    if (selectedFile) {
      onUpload(selectedFile, category);
      setShowCategoryModal(false);
      setSelectedFile(null);
      setSelectedCategory('other');
    }
  };

  const handleCategoryCancel = () => {
    setShowCategoryModal(false);
    setSelectedFile(null);
    setSelectedCategory('other');
  };

  return (
    <aside
      className="flex flex-col h-full border-l border-[var(--color-border)] bg-[var(--color-bg-primary)]"
      style={{ width: 'var(--sidebar-width, 280px)' }}
    >
      {/* Header */}
      <div className="flex items-center justify-between px-4 py-3 border-b border-[var(--color-border)] flex-shrink-0">
        <h2 className="flex items-center gap-1.5 text-sm font-semibold text-[var(--color-text-primary)] m-0">
          <FileText size={16} />
          Documents
        </h2>
        {documents.length > 0 && (
          <span className="flex items-center justify-center w-5 h-5 rounded-full bg-primary text-white text-xs font-semibold">
            {documents.length}
          </span>
        )}
      </div>

      {/* Compare — needs two documents to mean anything */}
      {onCompare && documents.length >= 2 && (
        <div className="px-3 pt-3 flex-shrink-0">
          <button
            className="w-full flex items-center justify-center gap-2 px-3 py-2 rounded-lg bg-primary text-white text-sm font-medium hover:bg-primary-hover transition-colors disabled:opacity-50 cursor-pointer border-none"
            onClick={onCompare}
            disabled={disabled}
            title="Compare a column across these documents"
          >
            <GitCompare size={16} />
            Compare documents
          </button>
        </div>
      )}

      {/* Upload button */}
      <div className="p-3 border-b border-[var(--color-border)] flex-shrink-0">
        <button
          className="w-full flex flex-col items-center justify-center gap-1 px-3 py-3 rounded-lg border-2 border-dashed border-[var(--color-border)] hover:border-primary hover:bg-primary-light/30 text-[var(--color-text-muted)] hover:text-primary transition-colors disabled:opacity-50 disabled:cursor-not-allowed cursor-pointer bg-transparent"
          onClick={() => fileInputRef.current?.click()}
          disabled={disabled || isUploading}
        >
          <div>
            {isUploading ? <Loader2 size={20} className="animate-spin" /> : <Upload size={20} />}
          </div>
          <span className="text-sm font-medium">
            {isUploading ? uploadStatus || 'Uploading...' : 'Upload Document'}
          </span>
          {!isUploading && (
            <span className="text-[10px] opacity-60">PDF, Excel, Word, or Images</span>
          )}
        </button>

        {isUploading && uploadProgress > 0 && (
          <div className="mt-2 flex items-center gap-2">
            <div className="flex-1 h-1.5 rounded-full bg-[var(--color-bg-tertiary)] overflow-hidden">
              <div
                className="h-full rounded-full bg-primary transition-all duration-300"
                style={{ width: `${uploadProgress}%` }}
              />
            </div>
            <span className="text-[10px] text-[var(--color-text-muted)] font-medium flex-shrink-0">
              {uploadProgress}%
            </span>
          </div>
        )}

        <input
          ref={fileInputRef}
          type="file"
          accept=".pdf,.xlsx,.xls,.docx,.jpg,.jpeg,.png,.bmp,.tiff,.tif,application/pdf,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet,application/vnd.ms-excel,application/vnd.openxmlformats-officedocument.wordprocessingml.document,image/*"
          onChange={handleFileChange}
          className="hidden"
        />
      </div>

      {/* Document list */}
      <div className="flex-1 overflow-y-auto p-3">
        {documents.length === 0 && !isUploading ? (
          <div className="flex flex-col items-center justify-center gap-2 py-12 text-center px-4">
            <div className="text-[var(--color-text-muted)] opacity-40">
              <FolderOpen size={24} />
            </div>
            <div className="text-sm font-medium text-[var(--color-text-muted)]">No documents yet</div>
            <div className="text-xs text-[var(--color-text-muted)] opacity-60 leading-relaxed">
              Upload PDF, Excel, Word, or Image files to start
            </div>
          </div>
        ) : (
          <div className="flex flex-col gap-2">
            {isUploading && (
              <DocumentCard
                document={{ name: 'Uploading...', id: 'uploading' }}
                isUploading={true}
              />
            )}
            {documents.map(doc => (
              <DocumentCard
                key={doc.id}
                document={doc}
                onDelete={onDelete}
                onSummarize={onSummarize}
              />
            ))}
          </div>
        )}
      </div>

      {/* Category Selection Modal */}
      {showCategoryModal && selectedFile && (
        <CategorySelector
          fileName={selectedFile.name}
          onSelect={handleCategorySelect}
          onCancel={handleCategoryCancel}
        />
      )}
    </aside>
  );
}

export default DocumentPanel;
