import { useState, useEffect, useRef } from 'react';
import { Navigation } from '../components/shared/Navigation';
import { api } from '../services/api';
import './Reports.css';

function Reports() {
  // State for source file
  const [sourceFile, setSourceFile] = useState(null);
  const [columns, setColumns] = useState([]);
  const [selectedColumn, setSelectedColumn] = useState('');
  const [loadingColumns, setLoadingColumns] = useState(false);
  
  // State for PDF files
  const [pdfFiles, setPdfFiles] = useState([]);
  
  // Options
  const [useOcr, setUseOcr] = useState(false);
  
  // Job tracking
  const [jobId, setJobId] = useState(null);
  const [jobStatus, setJobStatus] = useState(null);
  const [progress, setProgress] = useState(0);
  const [progressMessage, setProgressMessage] = useState('');
  const [progressLogs, setProgressLogs] = useState([]);
  const [isProcessing, setIsProcessing] = useState(false);
  
  // Results
  const [result, setResult] = useState(null);
  const [error, setError] = useState('');
  
  // View state
  const [activeTab, setActiveTab] = useState('found');
  const [searchTerm, setSearchTerm] = useState('');
  
  const pollingRef = useRef(null);

  // Cleanup polling on unmount
  useEffect(() => {
    return () => {
      if (pollingRef.current) {
        clearInterval(pollingRef.current);
      }
    };
  }, []);

  // Handle source file upload - extract columns
  const handleSourceFileChange = async (e) => {
    const file = e.target.files[0];
    if (!file) return;
    
    setSourceFile(file);
    setColumns([]);
    setSelectedColumn('');
    setError('');
    setLoadingColumns(true);
    
    try {
      const { ok, data } = await api.getColumnsFromFile(file);
      
      if (ok && data.columns) {
        setColumns(data.columns);
        if (data.columns.length > 0) {
          setSelectedColumn(data.columns[0]);
        }
      } else {
        setError(data.error || 'Failed to extract columns');
      }
    } catch (err) {
      setError('Network error: Could not connect to server');
    } finally {
      setLoadingColumns(false);
    }
  };

  // Handle PDF files selection
  const handlePdfFilesChange = (e) => {
    const files = Array.from(e.target.files);
    setPdfFiles(prev => [...prev, ...files]);
  };

  // Remove a PDF file
  const removePdfFile = (index) => {
    setPdfFiles(prev => prev.filter((_, i) => i !== index));
  };

  // Start comparison
  const handleStartComparison = async () => {
    if (!sourceFile || !selectedColumn || pdfFiles.length === 0) {
      setError('Please select a source file, column, and at least one PDF');
      return;
    }
    
    setError('');
    setResult(null);
    setIsProcessing(true);
    setProgress(0);
    setProgressMessage('Starting...');
    setProgressLogs([]);
    setJobStatus('pending');
    
    try {
      const { ok, data } = await api.startMultiPdfComparison(
        sourceFile,
        selectedColumn,
        pdfFiles,
        useOcr
      );
      
      if (ok && data.job_id) {
        setJobId(data.job_id);
        pollJobStatus(data.job_id);
      } else {
        setError(data.error || 'Failed to start comparison');
        setIsProcessing(false);
      }
    } catch (err) {
      setError('Network error: Could not start comparison');
      setIsProcessing(false);
    }
  };

  // Poll for job status
  const pollJobStatus = (id) => {
    pollingRef.current = setInterval(async () => {
      try {
        const { ok, data } = await api.getReportStatus(id);
        
        if (!ok) {
          clearInterval(pollingRef.current);
          setError('Failed to fetch job status');
          setIsProcessing(false);
          return;
        }
        
        setJobStatus(data.status);
        setProgress(data.progress || 0);
        setProgressMessage(data.progress_message || '');
        
        // Update logs if available
        if (data.logs && data.logs.length > 0) {
          setProgressLogs(data.logs);
        }
        
        if (data.status === 'completed') {
          clearInterval(pollingRef.current);
          setResult(data.result);
          setIsProcessing(false);
        } else if (data.status === 'failed') {
          clearInterval(pollingRef.current);
          setError(data.error || 'Comparison failed');
          setIsProcessing(false);
        }
      } catch (err) {
        clearInterval(pollingRef.current);
        setError('Polling error');
        setIsProcessing(false);
      }
    }, 2000);
  };

  // Reset form
  const handleReset = () => {
    setSourceFile(null);
    setColumns([]);
    setSelectedColumn('');
    setPdfFiles([]);
    setResult(null);
    setError('');
    setJobId(null);
    setJobStatus(null);
    setProgress(0);
    setProgressMessage('');
    setProgressLogs([]);
  };

  // Filter results based on search
  const filteredFound = result?.all_found 
    ? Object.entries(result.all_found).filter(([key]) => 
        key.toLowerCase().includes(searchTerm.toLowerCase())
      )
    : [];
  
  const filteredNotFound = result?.not_found
    ? result.not_found.filter(item => 
        item.toLowerCase().includes(searchTerm.toLowerCase())
      )
    : [];

  return (
    <div className="reports-page">
      <Navigation />
      
      {/* Background Effects */}
      <div className="reports-bg-gradient"></div>
      <div className="reports-bg-grid"></div>

      <div className="reports-content">
        {/* Header */}
        <div className="reports-header">
          <div className="reports-badge">
            <i className="fa-solid fa-chart-bar"></i>
            <span>Multi-PDF Comparator</span>
          </div>
          <h1 className="reports-title">Reports & Analysis</h1>
          <p className="reports-subtitle">
            Compare values from Excel/PDF against multiple PDF documents
          </p>
        </div>

        {/* Main Content */}
        <div className="reports-main">
          {/* Left Panel - Configuration */}
          <div className="reports-config-panel">
            <div className="config-card">
              <h3>
                <i className="fa-solid fa-file-excel"></i>
                Source File
              </h3>
              <p className="config-desc">
                Upload Excel, PDF, or Image with values to search
              </p>
              
              <input
                type="file"
                id="sourceFile"
                accept=".xlsx,.xls,.pdf,.png,.jpg,.jpeg"
                onChange={handleSourceFileChange}
                style={{ display: 'none' }}
              />
              <button
                className="upload-btn"
                onClick={() => document.getElementById('sourceFile').click()}
                disabled={isProcessing}
              >
                <i className="fa-solid fa-cloud-arrow-up"></i>
                {sourceFile ? 'Change File' : 'Select File'}
              </button>
              
              {sourceFile && (
                <div className="file-info">
                  <i className="fa-solid fa-file"></i>
                  <span>{sourceFile.name}</span>
                </div>
              )}
              
              {loadingColumns && (
                <div className="loading-columns">
                  <i className="fa-solid fa-spinner fa-spin"></i>
                  <span>Extracting columns...</span>
                </div>
              )}
              
              {columns.length > 0 && (
                <div className="column-select">
                  <label>Select Column to Compare:</label>
                  <select
                    value={selectedColumn}
                    onChange={(e) => setSelectedColumn(e.target.value)}
                    disabled={isProcessing}
                  >
                    {columns.map((col, idx) => (
                      <option key={idx} value={col}>{col}</option>
                    ))}
                  </select>
                </div>
              )}
            </div>

            <div className="config-card">
              <h3>
                <i className="fa-solid fa-file-pdf"></i>
                Target PDFs
              </h3>
              <p className="config-desc">
                Upload PDF files to search in (can select multiple)
              </p>
              
              <input
                type="file"
                id="pdfFiles"
                accept=".pdf"
                multiple
                onChange={handlePdfFilesChange}
                style={{ display: 'none' }}
              />
              <button
                className="upload-btn"
                onClick={() => document.getElementById('pdfFiles').click()}
                disabled={isProcessing}
              >
                <i className="fa-solid fa-plus"></i>
                Add PDF Files
              </button>
              
              {pdfFiles.length > 0 && (
                <div className="pdf-list">
                  {pdfFiles.map((file, idx) => (
                    <div key={idx} className="pdf-item">
                      <i className="fa-solid fa-file-pdf"></i>
                      <span>{file.name}</span>
                      <button
                        className="remove-btn"
                        onClick={() => removePdfFile(idx)}
                        disabled={isProcessing}
                      >
                        <i className="fa-solid fa-times"></i>
                      </button>
                    </div>
                  ))}
                </div>
              )}
            </div>

            <div className="config-card">
              <h3>
                <i className="fa-solid fa-cog"></i>
                Options
              </h3>
              
              <label className="checkbox-option">
                <input
                  type="checkbox"
                  checked={useOcr}
                  onChange={(e) => setUseOcr(e.target.checked)}
                  disabled={isProcessing}
                />
                <span>Enable OCR (for scanned documents)</span>
              </label>
            </div>

            <div className="action-buttons">
              <button
                className="start-btn"
                onClick={handleStartComparison}
                disabled={isProcessing || !sourceFile || !selectedColumn || pdfFiles.length === 0}
              >
                {isProcessing ? (
                  <>
                    <i className="fa-solid fa-spinner fa-spin"></i>
                    Processing...
                  </>
                ) : (
                  <>
                    <i className="fa-solid fa-play"></i>
                    Start Comparison
                  </>
                )}
              </button>
              
              <button
                className="reset-btn"
                onClick={handleReset}
                disabled={isProcessing}
              >
                <i className="fa-solid fa-rotate-left"></i>
                Reset
              </button>
            </div>

            {error && (
              <div className="error-message">
                <i className="fa-solid fa-circle-exclamation"></i>
                <span>{error}</span>
              </div>
            )}

            {isProcessing && (
              <div className="progress-section">
                <div className="progress-header">
                  <span className="progress-label">
                    {jobStatus === 'pending' ? 'Starting...' : 'Processing'}
                  </span>
                  <span className="progress-percentage">{progress}%</span>
                </div>
                <div className="progress-bar">
                  <div 
                    className="progress-fill"
                    style={{ width: `${progress}%` }}
                  ></div>
                </div>
                <p className="progress-message">{progressMessage}</p>
                
                {progressLogs.length > 0 && (
                  <div className="progress-logs">
                    <div className="progress-logs-header">
                      <i className="fa-solid fa-terminal"></i>
                      <span>Processing Log</span>
                    </div>
                    {progressLogs.slice(-10).map((log, idx) => (
                      <div key={idx} className="log-entry">{log}</div>
                    ))}
                  </div>
                )}
              </div>
            )}
          </div>

          {/* Right Panel - Results */}
          <div className="reports-results-panel">
            {!result && !isProcessing && (
              <div className="no-results">
                <i className="fa-solid fa-chart-pie"></i>
                <h3>No Results Yet</h3>
                <p>Configure your comparison and click "Start Comparison" to see results</p>
              </div>
            )}

            {result && (
              <>
                {/* Summary Cards */}
                <div className="results-summary">
                  <div className="summary-card total">
                    <div className="summary-icon">
                      <i className="fa-solid fa-list"></i>
                    </div>
                    <div className="summary-content">
                      <span className="summary-value">{result.total_values}</span>
                      <span className="summary-label">Total Values</span>
                    </div>
                  </div>
                  
                  <div className="summary-card found">
                    <div className="summary-icon">
                      <i className="fa-solid fa-check"></i>
                    </div>
                    <div className="summary-content">
                      <span className="summary-value">{result.found_count}</span>
                      <span className="summary-label">Found</span>
                    </div>
                  </div>
                  
                  <div className="summary-card not-found">
                    <div className="summary-icon">
                      <i className="fa-solid fa-times"></i>
                    </div>
                    <div className="summary-content">
                      <span className="summary-value">{result.not_found_count}</span>
                      <span className="summary-label">Not Found</span>
                    </div>
                  </div>
                  
                  <div className="summary-card percentage">
                    <div className="summary-icon">
                      <i className="fa-solid fa-percent"></i>
                    </div>
                    <div className="summary-content">
                      <span className="summary-value">{result.match_percentage}%</span>
                      <span className="summary-label">Match Rate</span>
                    </div>
                  </div>
                </div>

                {/* Download Button */}
                {jobId && (
                  <div className="download-section">
                    <a 
                      href={api.getReportDownloadUrl(jobId)} 
                      className="download-btn"
                      download
                    >
                      <i className="fa-solid fa-download"></i>
                      Download Excel Report
                    </a>
                  </div>
                )}

                {/* Search & Tabs */}
                <div className="results-controls">
                  <div className="search-box">
                    <i className="fa-solid fa-search"></i>
                    <input
                      type="text"
                      placeholder="Search values..."
                      value={searchTerm}
                      onChange={(e) => setSearchTerm(e.target.value)}
                    />
                  </div>
                  
                  <div className="result-tabs">
                    <button
                      className={`tab-btn ${activeTab === 'found' ? 'active' : ''}`}
                      onClick={() => setActiveTab('found')}
                    >
                      <i className="fa-solid fa-check-circle"></i>
                      Found ({result.found_count})
                    </button>
                    <button
                      className={`tab-btn ${activeTab === 'not-found' ? 'active' : ''}`}
                      onClick={() => setActiveTab('not-found')}
                    >
                      <i className="fa-solid fa-times-circle"></i>
                      Not Found ({result.not_found_count})
                    </button>
                  </div>
                </div>

                {/* Results List */}
                <div className="results-list">
                  {activeTab === 'found' && (
                    <>
                      {filteredFound.length === 0 ? (
                        <div className="empty-results">
                          <p>No matching found values</p>
                        </div>
                      ) : (
                        filteredFound.map(([value, pdfLocations], idx) => (
                          <div key={idx} className="result-item found">
                            <div className="result-value">
                              <i className="fa-solid fa-check"></i>
                              <span>{value}</span>
                            </div>
                            <div className="result-locations">
                              {Object.entries(pdfLocations).map(([pdf, pages], pIdx) => (
                                <div key={pIdx} className="location-item">
                                  <span className="pdf-name">{pdf}</span>
                                  <span className="page-numbers">
                                    {Array.isArray(pages) 
                                      ? pages.map(p => `Page ${p}`).join(', ')
                                      : pages}
                                  </span>
                                </div>
                              ))}
                            </div>
                          </div>
                        ))
                      )}
                    </>
                  )}
                  
                  {activeTab === 'not-found' && (
                    <>
                      {filteredNotFound.length === 0 ? (
                        <div className="empty-results">
                          <p>No matching not-found values</p>
                        </div>
                      ) : (
                        filteredNotFound.map((value, idx) => (
                          <div key={idx} className="result-item not-found">
                            <div className="result-value">
                              <i className="fa-solid fa-times"></i>
                              <span>{value}</span>
                            </div>
                          </div>
                        ))
                      )}
                    </>
                  )}
                </div>
              </>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}

export default Reports;
