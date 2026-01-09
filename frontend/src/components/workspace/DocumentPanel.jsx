import { useRef } from 'react';
import {
  FileText,
  Upload,
  Trash2,
  FileUp,
  Loader2,
  FolderOpen,
  Sparkles
} from 'lucide-react';
import './DocumentPanel.css';

function DocumentCard({ document, onDelete, onSummarize, isUploading = false }) {
  return (
    <div className={`document-card ${isUploading ? 'document-card--uploading' : ''}`}>
      <div className="document-card__icon">
        {isUploading ? <Loader2 size={18} className="animate-spin" /> : <FileText size={18} />}
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
              {document.is_inherited && (
                <span className="document-card__badge">Inherited</span>
              )}
              <span>{document.source_thread || 'Current thread'}</span>
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

  const handleFileChange = (e) => {
    const file = e.target.files[0];
    if (file) {
      // Strict PDF check
      if (file.type === 'application/pdf' || file.name.toLowerCase().endsWith('.pdf')) {
        onUpload(file);
      } else {
        alert('Only PDF files are supported');
      }
      e.target.value = '';
    }
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
            {isUploading ? uploadStatus || 'Uploading...' : 'Upload PDF'}
          </span>
          {!isUploading && <span className="document-panel__upload-hint">or drag and drop</span>}
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
          accept="application/pdf,.pdf"
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
            Upload a PDF to start asking questions
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
    </aside>
  );
}

export default DocumentPanel;
