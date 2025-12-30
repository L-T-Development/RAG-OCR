import { useState, useEffect, useCallback } from 'react';
import { useNavigate } from 'react-router-dom';
import { api } from '../services/api';
import './Settings.css';

function Settings() {
  const navigate = useNavigate();
  const [modelPath, setModelPath] = useState('');
  const [modelStatus, setModelStatus] = useState(null);
  const [isLoading, setIsLoading] = useState(true);
  const [isSaving, setIsSaving] = useState(false);
  const [isValidating, setIsValidating] = useState(false);
  const [validationResult, setValidationResult] = useState(null);
  const [saveMessage, setSaveMessage] = useState(null);

  // Fetch model status on mount
  const fetchModelStatus = useCallback(async () => {
    try {
      setIsLoading(true);
      const result = await api.getModelStatus();
      if (result.ok) {
        setModelStatus(result.data);
        if (result.data.saved_path) {
          setModelPath(result.data.saved_path);
        } else if (result.data.path) {
          setModelPath(result.data.path);
        }
      }
    } catch (error) {
      console.error('Failed to fetch model status:', error);
    } finally {
      setIsLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchModelStatus();
  }, [fetchModelStatus]);

  // Validate path when it changes (with debounce)
  useEffect(() => {
    if (!modelPath.trim()) {
      setValidationResult(null);
      return;
    }

    const timer = setTimeout(async () => {
      setIsValidating(true);
      try {
        const result = await api.validateModelPath(modelPath);
        setValidationResult(result.data);
      } catch (error) {
        setValidationResult({ valid: false, error: 'Failed to validate path' });
      } finally {
        setIsValidating(false);
      }
    }, 500);

    return () => clearTimeout(timer);
  }, [modelPath]);

  const handleSave = async () => {
    if (!modelPath.trim()) {
      setSaveMessage({ type: 'error', text: 'Please enter a model path' });
      return;
    }

    setIsSaving(true);
    setSaveMessage(null);

    try {
      const result = await api.configureModel(modelPath);
      if (result.ok && result.data.status?.loaded) {
        setSaveMessage({ type: 'success', text: 'Model configured successfully!' });
        setModelStatus(result.data.status);
      } else {
        setSaveMessage({ 
          type: 'error', 
          text: result.data.error || result.data.status?.error || 'Failed to configure model'
        });
        if (result.data.status) {
          setModelStatus(result.data.status);
        }
      }
    } catch (error) {
      setSaveMessage({ type: 'error', text: 'Failed to save configuration' });
    } finally {
      setIsSaving(false);
    }
  };

  const getStatusColor = () => {
    if (!modelStatus) return 'gray';
    if (modelStatus.loaded) return 'green';
    if (modelStatus.error) return 'red';
    return 'orange';
  };

  const getStatusText = () => {
    if (!modelStatus) return 'Unknown';
    if (modelStatus.loaded) return 'Connected';
    if (modelStatus.error) return 'Error';
    return 'Not Configured';
  };

  return (
    <div className="settings-page">
      <div className="settings-header">
        <button className="back-btn" onClick={() => navigate(-1)}>
          ← Back
        </button>
        <h1>⚙️ Settings</h1>
      </div>

      <div className="settings-content">
        {/* Model Status Card */}
        <div className="settings-card">
          <h2>🤖 Embedding Model Status</h2>
          
          {isLoading ? (
            <div className="loading-indicator">Loading...</div>
          ) : (
            <div className="status-section">
              <div className="status-indicator">
                <span 
                  className="status-dot" 
                  style={{ backgroundColor: getStatusColor() }}
                />
                <span className="status-text">{getStatusText()}</span>
              </div>

              {modelStatus && (
                <div className="status-details">
                  <div className="status-row">
                    <span className="label">Device:</span>
                    <span className="value">{modelStatus.device?.toUpperCase() || 'N/A'}</span>
                  </div>
                  {modelStatus.path && (
                    <div className="status-row">
                      <span className="label">Current Path:</span>
                      <span className="value path">{modelStatus.path}</span>
                    </div>
                  )}
                  {modelStatus.load_time && (
                    <div className="status-row">
                      <span className="label">Load Time:</span>
                      <span className="value">{modelStatus.load_time}s</span>
                    </div>
                  )}
                  {modelStatus.error && (
                    <div className="status-row error">
                      <span className="label">Error:</span>
                      <span className="value">{modelStatus.error}</span>
                    </div>
                  )}
                </div>
              )}
            </div>
          )}
        </div>

        {/* Model Configuration Card */}
        <div className="settings-card">
          <h2>📁 Configure Model Path</h2>
          <p className="description">
            Enter the path to your embedding model directory (e.g., all-MiniLM-L6-v2).
            The directory should contain <code>config.json</code> and model weight files.
          </p>

          <div className="input-group">
            <label htmlFor="modelPath">Model Directory Path:</label>
            <div className="input-with-status">
              <input
                id="modelPath"
                type="text"
                value={modelPath}
                onChange={(e) => setModelPath(e.target.value)}
                placeholder="C:\path\to\models\all-MiniLM-L6-v2"
                disabled={isSaving}
              />
              {isValidating && <span className="validating">Validating...</span>}
            </div>
            
            {validationResult && !isValidating && (
              <div className={`validation-result ${validationResult.valid ? 'valid' : 'invalid'}`}>
                {validationResult.valid ? (
                  <span>✅ Valid model directory</span>
                ) : (
                  <span>❌ {validationResult.error}</span>
                )}
              </div>
            )}
          </div>

          <div className="button-group">
            <button 
              className="save-btn"
              onClick={handleSave}
              disabled={isSaving || isValidating || !modelPath.trim()}
            >
              {isSaving ? 'Saving...' : 'Save & Load Model'}
            </button>
            <button 
              className="refresh-btn"
              onClick={fetchModelStatus}
              disabled={isLoading}
            >
              🔄 Refresh Status
            </button>
          </div>

          {saveMessage && (
            <div className={`save-message ${saveMessage.type}`}>
              {saveMessage.text}
            </div>
          )}
        </div>

        {/* Help Card */}
        <div className="settings-card help-card">
          <h2>ℹ️ Help</h2>
          <div className="help-content">
            <h3>Where to get the model?</h3>
            <p>
              Download the <strong>all-MiniLM-L6-v2</strong> model from Hugging Face:
            </p>
            <code className="download-link">
              https://huggingface.co/sentence-transformers/all-MiniLM-L6-v2
            </code>
            
            <h3>Required files in the model directory:</h3>
            <ul>
              <li><code>config.json</code> - Model configuration</li>
              <li><code>model.safetensors</code> or <code>pytorch_model.bin</code> - Model weights</li>
              <li><code>tokenizer.json</code> - Tokenizer file</li>
              <li><code>vocab.txt</code> - Vocabulary file</li>
            </ul>

            <h3>Example paths:</h3>
            <ul>
              <li>Windows: <code>C:\Models\all-MiniLM-L6-v2</code></li>
              <li>Linux/Mac: <code>/home/user/models/all-MiniLM-L6-v2</code></li>
            </ul>
          </div>
        </div>
      </div>
    </div>
  );
}

export default Settings;
