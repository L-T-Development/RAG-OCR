import { useRef } from 'react';
import './FilesPanel.css';

function FilesPanel({ files, onUpload, onDeleteFile, disabled, isUploading }) {
  const fileInputRef = useRef(null);

  const handleFileChange = (e) => {
    const file = e.target.files[0];
    if (file) {
      onUpload(file);
      e.target.value = '';
    }
  };

  return (
    <aside className="files-panel">
      <div className="files-header">
        <span>Documents</span>
        <button
          className="btn-icon"
          title="Upload PDF"
          onClick={() => fileInputRef.current?.click()}
          disabled={disabled}
        >
          <i className="fa-solid fa-cloud-arrow-up" style={{ fontSize: '1.1rem' }}></i>
        </button>
        <input
          type="file"
          ref={fileInputRef}
          accept="application/pdf,.pdf"
          onChange={handleFileChange}
          style={{ display: 'none' }}
        />
      </div>

      <div className="file-list">
        {isUploading && (
          <div className="file-card uploading">
            <i className="fa-solid fa-spinner fa-spin file-icon"></i>
            <div className="file-info">
              <div className="file-name">Uploading...</div>
            </div>
          </div>
        )}

        {!disabled && files.length === 0 && !isUploading ? (
          <div className="empty-files">No documents uploaded</div>
        ) : disabled ? (
          <div className="empty-files">No thread selected</div>
        ) : (
          files.map(file => (
            <div key={file.id} className="file-card">
              <i className="fa-solid fa-file-pdf file-icon"></i>
              <div className="file-info">
                <div className="file-name" title={file.name}>
                  {file.name}
                  {file.is_inherited && (
                    <span className="inherited-tag" title={`Inherited from ${file.source_thread}`}>
                      Parent
                    </span>
                  )}
                </div>
                <div className="file-origin">
                  {file.is_inherited ? `Inherited: ${file.source_thread}` : 'Current Thread'}
                </div>
              </div>
              {!file.is_inherited && (
                <button
                  className="btn-icon delete-btn"
                  onClick={() => onDeleteFile(file.id)}
                  title="Delete"
                >
                  <i className="fa-solid fa-trash"></i>
                </button>
              )}
            </div>
          ))
        )}
      </div>
    </aside>
  );
}

export default FilesPanel;
