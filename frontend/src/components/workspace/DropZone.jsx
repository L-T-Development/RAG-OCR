import { useState, useEffect, useCallback } from 'react';
import { FileUp, FileWarning, FileText, FileSpreadsheet, File, FileImage } from 'lucide-react';
import './DropZone.css';

// Supported file extensions
const SUPPORTED_EXTENSIONS = ['.pdf', '.xlsx', '.xls', '.docx', '.jpg', '.jpeg', '.png', '.bmp', '.tiff', '.tif'];

export function DropZone({ onDrop, disabled = false }) {
  const [isDragging, setIsDragging] = useState(false);
  const [isError, setIsError] = useState(false);
  const [errorMessage, setErrorMessage] = useState('');

  const isValidFile = (file) => {
    const ext = '.' + file.name.toLowerCase().split('.').pop();
    return SUPPORTED_EXTENSIONS.includes(ext);
  };

  const handleDragEnter = useCallback((e) => {
    e.preventDefault();
    e.stopPropagation();
    if (disabled) return;
    
    // Check if dragged item is a file
    if (e.dataTransfer.items && e.dataTransfer.items.length > 0) {
      setIsDragging(true);
      setIsError(false);
    }
  }, [disabled]);

  const handleDragLeave = useCallback((e) => {
    e.preventDefault();
    e.stopPropagation();
    
    // Only close if leaving the window
    if (e.relatedTarget === null || !document.body.contains(e.relatedTarget)) {
      setIsDragging(false);
      setIsError(false);
    }
  }, []);

  const handleDragOver = useCallback((e) => {
    e.preventDefault();
    e.stopPropagation();
  }, []);

  const handleDrop = useCallback((e) => {
    e.preventDefault();
    e.stopPropagation();
    setIsDragging(false);
    
    if (disabled) return;

    const files = e.dataTransfer.files;
    if (files.length === 0) return;

    const file = files[0];
    
    // Check if file is supported
    if (!isValidFile(file)) {
      setIsError(true);
      setErrorMessage(`Only ${SUPPORTED_EXTENSIONS.join(', ')} files are supported`);
      setTimeout(() => {
        setIsError(false);
        setErrorMessage('');
      }, 3000);
      return;
    }

    setIsError(false);
    setErrorMessage('');
    onDrop(file);
  }, [disabled, onDrop]);

  useEffect(() => {
    // Add global listeners
    window.addEventListener('dragenter', handleDragEnter);
    window.addEventListener('dragleave', handleDragLeave);
    window.addEventListener('dragover', handleDragOver);
    window.addEventListener('drop', handleDrop);

    return () => {
      window.removeEventListener('dragenter', handleDragEnter);
      window.removeEventListener('dragleave', handleDragLeave);
      window.removeEventListener('dragover', handleDragOver);
      window.removeEventListener('drop', handleDrop);
    };
  }, [handleDragEnter, handleDragLeave, handleDragOver, handleDrop]);

  if (!isDragging && !isError) return null;

  return (
    <div className={`drop-zone-overlay ${isError ? 'drop-zone-overlay--error' : ''}`}>
      <div className="drop-zone-overlay__content">
        <div className="drop-zone-overlay__icon">
          {isError ? <FileWarning size={36} /> : <FileUp size={36} />}
        </div>
        <h2 className="drop-zone-overlay__title">
          {isError ? 'Invalid File Type' : 'Drop Document Here'}
        </h2>
        <p className="drop-zone-overlay__text">
          {isError 
            ? errorMessage || 'Only PDF, Excel, and Word files are supported'
            : 'Release to upload your document for AI analysis'
          }
        </p>
        {!isError && (
          <div className="drop-zone-overlay__badge">
            <FileText size={14} />
            <FileSpreadsheet size={14} />
            <File size={14} />
            <FileImage size={14} />
            PDF, Excel, Word, Images
          </div>
        )}
      </div>
    </div>
  );
}

export default DropZone;
