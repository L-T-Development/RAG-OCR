import { useState, useEffect, useRef } from 'react';
import { Link } from 'react-router-dom';
import { api } from '../services/api';
import './Compare.css';

function Compare() {
  const [oldFile, setOldFile] = useState(null);
  const [newFile, setNewFile] = useState(null);
  const [status, setStatus] = useState('');
  const [diffResult, setDiffResult] = useState(null);
  const [isLoading, setIsLoading] = useState(false);
  const [jobId, setJobId] = useState(null);
  const [showOnlyChanges, setShowOnlyChanges] = useState(false);
  const [uploadProgress, setUploadProgress] = useState(0);
  const [currentPage, setCurrentPage] = useState(1);
  const [itemsPerPage] = useState(100); // Show 100 lines per page
  const [pageInput, setPageInput] = useState('1');
  
  const pollingTimerRef = useRef(null);

  // Cleanup polling on component unmount
  useEffect(() => {
    return () => {
      if (pollingTimerRef.current) {
        clearInterval(pollingTimerRef.current);
        pollingTimerRef.current = null;
      }
    };
  }, []);

  const validateFiles = () => {
    if (!oldFile || !newFile) return false;
    const ext1 = oldFile.name.split('.').pop().toLowerCase();
    const ext2 = newFile.name.split('.').pop().toLowerCase();
    return ext1 === ext2;
  };

  const handleCompare = async () => {
    if (!validateFiles()) {
      setStatus('Files must be of the same type.');
      return;
    }

    // Clear any existing polling before starting new comparison
    if (pollingTimerRef.current) {
      clearInterval(pollingTimerRef.current);
      pollingTimerRef.current = null;
    }

    setIsLoading(true);
    setStatus('Uploading files...');
    setDiffResult(null);
    setUploadProgress(0);
    setCurrentPage(1);
    setPageInput('1');

    // Simulate upload progress
    const progressInterval = setInterval(() => {
      setUploadProgress(prev => {
        if (prev >= 90) return prev;
        return prev + 10;
      });
    }, 300);

    try {
      const { ok, data } = await api.compareDocuments(oldFile, newFile);
      clearInterval(progressInterval);
      setUploadProgress(100);
      
      if (ok && data.job_id) {
        // Backend returned job_id, start polling
        setJobId(data.job_id);
        setStatus('Processing documents...');
        pollComparisonStatus(data.job_id);
      } else if (ok && data.diff) {
        // Synchronous response (fallback)
        setDiffResult(data.diff);
        setStatus(`Comparison completed in ${data.processing_time_seconds}s`);
        setIsLoading(false);
      } else {
        setStatus(data.error || 'Comparison failed.');
        setIsLoading(false);
      }
    } catch (e) {
      setStatus('Network error: Could not connect to comparison service.');
      setDiffResult(null);
      setIsLoading(false);
    }
  };

  const pollComparisonStatus = (jobId) => {
    pollingTimerRef.current = setInterval(async () => {
      try {
        const res = await api.getComparisonStatus(jobId);

        if (!res.ok) {
          if (pollingTimerRef.current) {
            clearInterval(pollingTimerRef.current);
            pollingTimerRef.current = null;
          }
          setIsLoading(false);
          setStatus('Failed to fetch comparison status');
          return;
        }

        const job = res.data;

        // Update status with progress if available
        if (job.progress) {
          setStatus(`Processing documents... ${job.progress}%`);
        }

        if (job.status === 'completed') {
          if (pollingTimerRef.current) {
            clearInterval(pollingTimerRef.current);
            pollingTimerRef.current = null;
          }
          setDiffResult(job.result?.diff);
          const processingTime = job.result?.processing_time_seconds || 0;
          setStatus(`Comparison completed in ${processingTime.toFixed(2)}s`);
          setIsLoading(false);
        } else if (job.status === 'failed') {
          if (pollingTimerRef.current) {
            clearInterval(pollingTimerRef.current);
            pollingTimerRef.current = null;
          }
          setIsLoading(false);
          setStatus(job.error || 'Comparison failed');
        }
      } catch (err) {
        if (pollingTimerRef.current) {
          clearInterval(pollingTimerRef.current);
          pollingTimerRef.current = null;
        }
        setIsLoading(false);
        setStatus('Polling error');
      }
    }, 1500);
  };

  const getStatusIcon = (status) => {
    switch(status) {
      case 'added': return 'fa-plus';
      case 'removed': return 'fa-minus';
      case 'modified': return 'fa-pen';
      default: return 'fa-equals';
    }
  };

  const filteredLines = diffResult?.lines?.filter(line => 
    showOnlyChanges ? line.status !== 'equal' : true
  ) || [];

  // Pagination logic
  const totalPages = Math.ceil(filteredLines.length / itemsPerPage);
  const startIndex = (currentPage - 1) * itemsPerPage;
  const endIndex = startIndex + itemsPerPage;
  const currentLines = filteredLines.slice(startIndex, endIndex);

  const handlePageChange = (newPage) => {
    if (newPage >= 1 && newPage <= totalPages) {
      setCurrentPage(newPage);
      setPageInput(newPage.toString());
    }
  };

  const handlePageInputChange = (e) => {
    setPageInput(e.target.value);
  };

  const handlePageInputSubmit = () => {
    const page = parseInt(pageInput, 10);
    if (!isNaN(page) && page >= 1 && page <= totalPages) {
      setCurrentPage(page);
    } else {
      setPageInput(currentPage.toString());
    }
  };

  const handlePageInputKeyDown = (e) => {
    if (e.key === 'Enter') {
      handlePageInputSubmit();
    }
  };

  return (
    <div className="compare-page">
      {/* Background Effects */}
      <div className="compare-bg-gradient"></div>
      <div className="compare-bg-grid"></div>
      
      {/* Navigation */}
      <nav className="compare-nav">
        <Link to="/" className="compare-nav-brand">
          <div className="compare-logo-icon">
            <i className="fa-solid fa-cube"></i>
          </div>
          <span className="compare-logo-text">RAG<span className="compare-logo-accent">OCR</span></span>
        </Link>
        <div className="compare-nav-actions">
          <Link to="/workspace" className="compare-nav-btn">
            <i className="fa-solid fa-message"></i>
            <span>Workspace</span>
          </Link>
          <Link to="/" className="compare-nav-btn primary">
            <i className="fa-solid fa-house"></i>
            <span>Home</span>
          </Link>
        </div>
      </nav>

      <div className="compare-content">
        {/* Header */}
        <div className="compare-header">
          <div className="compare-badge">
            <i className="fa-solid fa-code-compare"></i>
            <span>Document Analysis</span>
          </div>
          <h1 className="compare-title">Compare Documents</h1>
          <p className="compare-subtitle">Upload two versions of the same document to see what changed</p>
        </div>

        {/* Upload Section */}
        <div className="compare-upload-section">
          <div className="file-upload-card">
            <div className="upload-icon old">
              <i className="fa-solid fa-file-circle-minus"></i>
            </div>
            <h3>Old Version</h3>
            <p>The original document</p>
            <input
              type="file"
              id="oldFile"
              accept=".pdf,.docx,.xlsx"
              onChange={(e) => setOldFile(e.target.files[0])}
              style={{ display: 'none' }}
            />
            <button 
              className="upload-btn"
              onClick={() => document.getElementById('oldFile').click()}
            >
              <i className="fa-solid fa-cloud-arrow-up"></i>
              Choose File
            </button>
            {oldFile && (
              <div className="file-selected">
                <i className="fa-solid fa-file"></i>
                <span>{oldFile.name}</span>
              </div>
            )}
          </div>

          <div className="compare-arrow">
            <i className="fa-solid fa-arrows-left-right"></i>
          </div>

          <div className="file-upload-card">
            <div className="upload-icon new">
              <i className="fa-solid fa-file-circle-plus"></i>
            </div>
            <h3>New Version</h3>
            <p>The updated document</p>
            <input
              type="file"
              id="newFile"
              accept=".pdf,.docx,.xlsx"
              onChange={(e) => setNewFile(e.target.files[0])}
              style={{ display: 'none' }}
            />
            <button 
              className="upload-btn"
              onClick={() => document.getElementById('newFile').click()}
            >
              <i className="fa-solid fa-cloud-arrow-up"></i>
              Choose File
            </button>
            {newFile && (
              <div className="file-selected">
                <i className="fa-solid fa-file"></i>
                <span>{newFile.name}</span>
              </div>
            )}
          </div>
        </div>

        {/* Supported Formats */}
        <div className="supported-formats">
          <span>Supported:</span>
          <div className="format-badge"><i className="fa-solid fa-file-pdf"></i> PDF</div>
          <div className="format-badge"><i className="fa-solid fa-file-word"></i> DOCX</div>
          <div className="format-badge"><i className="fa-solid fa-file-excel"></i> XLSX</div>
        </div>

        {/* Compare Button */}
        <button
          className="compare-action-btn"
          onClick={handleCompare}
          disabled={!validateFiles() || isLoading}
        >
          {isLoading ? (
            <>
              <i className="fa-solid fa-spinner fa-spin"></i>
              <span>Analyzing Documents...</span>
            </>
          ) : (
            <>
              <i className="fa-solid fa-magnifying-glass-chart"></i>
              <span>Generate Comparison</span>
            </>
          )}
        </button>

        {/* Status */}
        {status && (
          <div className={`compare-status ${status.includes('completed') ? 'success' : ''}`}>
            <i className={`fa-solid ${status.includes('completed') ? 'fa-circle-check' : status.includes('Processing') || status.includes('Uploading') ? 'fa-spinner fa-spin' : 'fa-circle-info'}`}></i>
            {status}
          </div>
        )}

        {/* Upload Progress Bar */}
        {isLoading && uploadProgress > 0 && uploadProgress < 100 && (
          <div className="compare-progress">
            <div className="compare-progress-bar">
              <div className="compare-progress-fill" style={{ width: `${uploadProgress}%` }}></div>
            </div>
            <span className="compare-progress-text">{uploadProgress}%</span>
          </div>
        )}

        {/* Output */}
        {diffResult && (
          <div className="compare-output">
            <div className="output-header">
              <div className="output-header-left">
                <i className="fa-solid fa-rectangle-list"></i>
                <h3>Line-by-Line Comparison</h3>
              </div>
              <label className="toggle-changes">
                <input 
                  type="checkbox" 
                  checked={showOnlyChanges} 
                  onChange={(e) => setShowOnlyChanges(e.target.checked)}
                />
                <span>Show only changes</span>
              </label>
            </div>
            
            {/* Stats Summary */}
            <div className="diff-stats">
              <div className="stat-item equal">
                <i className="fa-solid fa-equals"></i>
                <span>{diffResult.stats?.equal || 0} Unchanged</span>
              </div>
              <div className="stat-item added">
                <i className="fa-solid fa-plus"></i>
                <span>{diffResult.stats?.added || 0} Added</span>
              </div>
              <div className="stat-item modified">
                <i className="fa-solid fa-pen"></i>
                <span>{diffResult.stats?.modified || 0} Modified</span>
              </div>
              <div className="stat-item removed">
                <i className="fa-solid fa-minus"></i>
                <span>{diffResult.stats?.removed || 0} Removed</span>
              </div>
              <div className="stat-item total">
                <i className="fa-solid fa-list-ol"></i>
                <span>{diffResult.total_lines || 0} Total Lines</span>
              </div>
            </div>

            {/* Pagination Controls */}
            {totalPages > 1 && (
              <div className="diff-pagination">
                <button 
                  className="pagination-btn"
                  onClick={() => handlePageChange(currentPage - 1)}
                  disabled={currentPage === 1}
                >
                  <i className="fa-solid fa-chevron-left"></i>
                  Previous
                </button>
                
                <div className="pagination-info">
                  <span>Page</span>
                  <input
                    type="text"
                    className="pagination-input"
                    value={pageInput}
                    onChange={handlePageInputChange}
                    onKeyDown={handlePageInputKeyDown}
                    onBlur={handlePageInputSubmit}
                  />
                  <span>of {totalPages}</span>
                  <span className="pagination-meta">({filteredLines.length} lines total)</span>
                </div>
                
                <button 
                  className="pagination-btn"
                  onClick={() => handlePageChange(currentPage + 1)}
                  disabled={currentPage === totalPages}
                >
                  Next
                  <i className="fa-solid fa-chevron-right"></i>
                </button>
              </div>
            )}

            {/* Unified Diff View */}
            <div className="diff-unified">
              {currentLines.length > 0 ? (
                currentLines.map((line, idx) => (
                  <div key={idx} className={`diff-line ${line.status}`}>
                    <span className="diff-line-number">{line.line}</span>
                    <span className="diff-line-status">
                      <i className={`fa-solid ${getStatusIcon(line.status)}`}></i>
                    </span>
                    <span className="diff-line-content">
                      {line.status === 'modified' ? (
                        <span className="modified-content">
                          <span className="old-value">{line.old_text}</span>
                          <i className="fa-solid fa-arrow-right"></i>
                          <span className="new-value">{line.new_text}</span>
                        </span>
                      ) : (
                        <span>{line.text}</span>
                      )}
                    </span>
                  </div>
                ))
              ) : (
                <div className="no-changes">
                  <i className="fa-solid fa-check-circle"></i>
                  <span>{showOnlyChanges ? 'No changes to display.' : 'No differences found between the documents.'}</span>
                </div>
              )}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

export default Compare;

