import { useState } from 'react';
import { Link } from 'react-router-dom';
import { api } from '../services/api';
import './Compare.css';

function Compare() {
  const [oldFile, setOldFile] = useState(null);
  const [newFile, setNewFile] = useState(null);
  const [status, setStatus] = useState('');
  const [output, setOutput] = useState('');
  const [isLoading, setIsLoading] = useState(false);

  const validateFiles = () => {
    if (!oldFile || !newFile) return false;
    const ext1 = oldFile.name.split('.').pop();
    const ext2 = newFile.name.split('.').pop();
    return ext1 === ext2;
  };

  const handleCompare = async () => {
    if (!validateFiles()) {
      setStatus('Files must be of the same type.');
      return;
    }

    setIsLoading(true);
    setStatus('Processing...');
    setOutput('');

    try {
      const { ok, data } = await api.compareDocuments(oldFile, newFile);
      
      if (ok) {
        setOutput(data.summary || 'No summary available.');
        setStatus(`Comparison completed in ${data.processing_time_seconds}s`);
      } else {
        setStatus(data.error || 'Comparison failed.');
      }
    } catch (e) {
      setStatus('Network error: Could not connect to comparison service.');
      setOutput('');
    } finally {
      setIsLoading(false);
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
            <i className={`fa-solid ${status.includes('completed') ? 'fa-circle-check' : status.includes('Processing') ? 'fa-spinner fa-spin' : 'fa-circle-info'}`}></i>
            {status}
          </div>
        )}

        {/* Output */}
        {output && (
          <div className="compare-output">
            <div className="output-header">
              <i className="fa-solid fa-rectangle-list"></i>
              <h3>Comparison Results</h3>
            </div>
            <pre className="output-content">{output}</pre>
          </div>
        )}
      </div>
    </div>
  );
}

export default Compare;

