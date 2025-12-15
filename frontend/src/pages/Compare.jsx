import { useState } from 'react';
import { Link } from 'react-router-dom';
import { api } from '../services/api';
import './Compare.css';

function Compare() {
  const [oldFile, setOldFile] = useState(null);
  const [newFile, setNewFile] = useState(null);
  const [status, setStatus] = useState('');
  const [output, setOutput] = useState('Upload two versions of the same document to generate a comparison.');
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
        setStatus('Comparison completed successfully.');
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
      <div className="compare-container">
        <div className="compare-header">
          <h2>
            <i className="fa-solid fa-code-compare"></i> Document Comparison
          </h2>
          <Link to="/" className="btn btn-primary" style={{ fontSize: '0.8rem' }}>
            <i className="fa-solid fa-arrow-left" style={{ marginRight: '6px' }}></i>
            Back to Workspace
          </Link>
        </div>

        <div className="file-row">
          <div className="file-box">
            <label>Old Version</label>
            <input
              type="file"
              id="oldFile"
              accept=".pdf,.docx,.xlsx"
              onChange={(e) => setOldFile(e.target.files[0])}
              style={{ display: 'none' }}
            />
            <div className="btn" onClick={() => document.getElementById('oldFile').click()}>
              Choose File
            </div>
            <div className="file-name-display">{oldFile ? oldFile.name : 'No file selected'}</div>
          </div>

          <div className="file-box">
            <label>New Version</label>
            <input
              type="file"
              id="newFile"
              accept=".pdf,.docx,.xlsx"
              onChange={(e) => setNewFile(e.target.files[0])}
              style={{ display: 'none' }}
            />
            <div className="btn" onClick={() => document.getElementById('newFile').click()}>
              Choose File
            </div>
            <div className="file-name-display">{newFile ? newFile.name : 'No file selected'}</div>
          </div>
        </div>

        <button
          className="action-btn"
          onClick={handleCompare}
          disabled={!validateFiles() || isLoading}
        >
          {isLoading ? (
            <>
              <i className="fa-solid fa-spinner fa-spin" style={{ marginRight: '8px' }}></i>
              Processing...
            </>
          ) : (
            'Generate Comparison'
          )}
        </button>

        {status && <div className="status">{status}</div>}

        <div className="output">
          {output && (
            <div className="summary">
              <strong>Summary:</strong>
              <br />
              {output}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

export default Compare;
