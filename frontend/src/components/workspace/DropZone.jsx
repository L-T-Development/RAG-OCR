import { useState, useEffect, useCallback } from 'react';
import { FileUp, FileWarning, FileText } from 'lucide-react';
import './DropZone.css';

export function DropZone({ onDrop, disabled = false }) {
  const [isDragging, setIsDragging] = useState(false);
  const [isError, setIsError] = useState(false);

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
    
    // Strict PDF check
    if (file.type !== 'application/pdf' && !file.name.toLowerCase().endsWith('.pdf')) {
      setIsError(true);
      setTimeout(() => setIsError(false), 2000);
      return;
    }

    setIsError(false);
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
          {isError ? 'Invalid File Type' : 'Drop PDF Here'}
        </h2>
        <p className="drop-zone-overlay__text">
          {isError 
            ? 'Only PDF files are supported. Please try again with a PDF document.'
            : 'Release to upload your PDF document for AI analysis.'
          }
        </p>
        {!isError && (
          <div className="drop-zone-overlay__badge">
            <FileText size={14} />
            PDF only
          </div>
        )}
      </div>
    </div>
  );
}

export default DropZone;
