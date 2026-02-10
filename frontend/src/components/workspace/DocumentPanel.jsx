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
  FileImage
} from 'lucide-react';
import { CategorySelector } from './CategorySelector';
import './DocumentPanel.css';

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

// Get category color
function getCategoryColor(category) {
  const cat = DOCUMENT_CATEGORIES.find(c => c.value === category);
  return cat?.color || '#6b7280';
}

// Get category badge
function getCategoryBadge(category, label) {
  const color = getCategoryColor(category);
  return (
    <span 
      className="document-card__category-badge" 
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

// Get icon based on file type with colors
function getFileIcon(filename) {
  const ext = filename?.toLowerCase().split('.').pop();
  if (ext === 'pdf') return <FileText size={18} style={{ color: '#ef4444' }} />; // Red
  if (ext === 'xlsx' || ext === 'xls') return <FileSpreadsheet size={18} style={{ color: '#10b981' }} />; // Green
  if (ext === 'docx') return <File size={18} style={{ color: '#3b82f6' }} />; // Blue
  if (ext === 'jpg' || ext === 'jpeg' || ext === 'png' || ext === 'bmp' || ext === 'tiff' || ext === 'tif') return <FileImage size={18} style={{ color: '#f59e0b' }} />; // Orange
  return <FileText size={18} />;
}

function DocumentCard({ document, onDelete, onSummarize, isUploading = false }) {
  return (
    <div className={`document-card ${isUploading ? 'document-card--uploading' : ''}`}>
      <div className="document-card__icon">
        {isUploading ? <Loader2 size={18} className="animate-spin" /> : getFileIcon(document.name)}
      </div>
      <div className="document-card__info">
        <div className="document-card__name" title={document.name}>
          {document.name}
        </div>
        <div className="document-card__meta">
          {isUploading ? (
            <span>Processing...</span>
          ) : (
            <>
              {document.category && getCategoryBadge(document.category, document.category_label)}
              {document.is_inherited && (
                <span className="document-card__badge">Inherited</span>
              )}
            </>
          )}
        </div>
        {isUploading && (
          <div className="document-card__progress">
            <div 
              className="document-card__progress-bar" 
              style={{ width: '60%' }}
            />
          </div>
        )}
      </div>
      {!isUploading && (
        <div className="document-card__actions">
          {onSummarize && (
            <button
              className="document-card__action-btn document-card__action-btn--summarize"
              onClick={() => onSummarize(document.id)}
              title="Summarize document"
            >
              <Sparkles size={14} />
            </button>
          )}
          {!document.is_inherited && (
            <button
              className="document-card__action-btn"
              onClick={() => onDelete(document.id)}
              title="Delete document"
            >
              <Trash2 size={14} />
            </button>
          )}
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
      // Check if file extension is supported
      const ext = '.' + file.name.toLowerCase().split('.').pop();
      if (SUPPORTED_EXTENSIONS.includes(ext)) {
        // Show category selection modal
        setSelectedFile(file);
        setShowCategoryModal(true);
        
        // Auto-detect category from filename
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
    <aside className="document-panel">
      <div className="document-panel__header">
        <h2 className="document-panel__title">
          <FileText size={16} />
          Documents
        </h2>
        {documents.length > 0 && (
          <span className="document-panel__count">{documents.length}</span>
        )}
      </div>

      <div className="document-panel__upload">
        <button
          className="document-panel__upload-btn"
          onClick={() => fileInputRef.current?.click()}
          disabled={disabled || isUploading}
        >
          <div className="document-panel__upload-icon">
            {isUploading ? <Loader2 size={20} className="animate-spin" /> : <Upload size={20} />}
          </div>
          <span className="document-panel__upload-text">
            {isUploading ? uploadStatus || 'Uploading...' : 'Upload Document'}
          </span>
          {!isUploading && <span className="document-panel__upload-hint">PDF, Excel, Word, or Images</span>}
        </button>
        {isUploading && uploadProgress > 0 && (
          <div className="document-panel__progress">
            <div className="document-panel__progress-bar">
              <div 
                className="document-panel__progress-fill" 
                style={{ width: `${uploadProgress}%` }}
              />
            </div>
            <span className="document-panel__progress-text">{uploadProgress}%</span>
          </div>
        )}
        <input
          ref={fileInputRef}
          type="file"
          accept=".pdf,.xlsx,.xls,.docx,.jpg,.jpeg,.png,.bmp,.tiff,.tif,application/pdf,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet,application/vnd.ms-excel,application/vnd.openxmlformats-officedocument.wordprocessingml.document,image/*"
          onChange={handleFileChange}
          style={{ display: 'none' }}
        />
      </div>

      {documents.length === 0 && !isUploading ? (
        <div className="document-panel__empty">
          <div className="document-panel__empty-icon">
            <FolderOpen size={24} />
          </div>
          <div className="document-panel__empty-title">No documents yet</div>
          <div className="document-panel__empty-text">
            Upload PDF, Excel, Word, or Image files to start
          </div>
        </div>
      ) : (
        <div className="document-panel__list">
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
