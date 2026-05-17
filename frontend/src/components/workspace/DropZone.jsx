import { useState, useEffect, useCallback } from 'react';
import { FileUp, FileWarning, FileText, FileSpreadsheet, File, FileImage } from 'lucide-react';

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

    if (e.dataTransfer.items && e.dataTransfer.items.length > 0) {
      setIsDragging(true);
      setIsError(false);
    }
  }, [disabled]);

  const handleDragLeave = useCallback((e) => {
    e.preventDefault();
    e.stopPropagation();

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
    <div
      className={`fixed inset-0 z-50 flex items-center justify-center
        ${isError
          ? 'bg-red-500/10 border-4 border-dashed border-red-500'
          : 'bg-white/90 border-4 border-dashed border-primary'
        }`}
    >
      <div className="flex flex-col items-center gap-4 text-center px-8 py-10 rounded-2xl bg-white/80 shadow-[var(--shadow-lg)] max-w-sm w-full mx-4">
        <div
          className={`flex items-center justify-center w-16 h-16 rounded-full
            ${isError ? 'bg-red-100 text-red-500' : 'bg-primary-light text-primary'}`}
        >
          {isError ? <FileWarning size={36} /> : <FileUp size={36} />}
        </div>

        <h2 className={`text-xl font-bold m-0 ${isError ? 'text-red-600' : 'text-[var(--color-text-primary)]'}`}>
          {isError ? 'Invalid File Type' : 'Drop Document Here'}
        </h2>

        <p className={`text-sm m-0 leading-relaxed ${isError ? 'text-red-500' : 'text-[var(--color-text-muted)]'}`}>
          {isError
            ? errorMessage || 'Only PDF, Excel, and Word files are supported'
            : 'Release to upload your document for AI analysis'
          }
        </p>

        {!isError && (
          <div className="flex items-center gap-2 px-4 py-2 rounded-full bg-[var(--color-bg-secondary)] border border-[var(--color-border)] text-sm text-[var(--color-text-secondary)]">
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
