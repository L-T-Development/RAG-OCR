import { useState, useEffect, useCallback } from 'react';
import { useNavigate } from 'react-router-dom';
import { useTheme } from '../context/ThemeContext';
import { api } from '../services/api';
import {
  ArrowLeft,
  Cpu,
  Moon,
  Sun,
  Monitor,
  CheckCircle,
  XCircle,
  AlertCircle,
  Loader2,
  Save
} from 'lucide-react';
import './Settings.css';

export function Settings() {
  const navigate = useNavigate();
  const { theme, setTheme } = useTheme();
  
  const [modelPath, setModelPath] = useState('');
  const [modelStatus, setModelStatus] = useState(null);
  const [isLoading, setIsLoading] = useState(true);
  const [isSaving, setIsSaving] = useState(false);
  const [saveMessage, setSaveMessage] = useState(null);

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
      }
    } catch (error) {
      setSaveMessage({ type: 'error', text: 'Network error. Please try again.' });
    } finally {
      setIsSaving(false);
    }
  };

  const getStatusIndicator = () => {
    if (isLoading) return 'warning';
    if (modelStatus?.loaded) return 'success';
    return 'error';
  };

  const getStatusText = () => {
    if (isLoading) return 'Loading...';
    if (modelStatus?.loaded) return 'Model loaded and ready';
    return modelStatus?.error || 'Model not configured';
  };

  return (
    <div className="settings-page">
      <header className="settings-page__header">
        <button className="settings-page__back" onClick={() => navigate(-1)}>
          <ArrowLeft size={20} />
        </button>
        <h1 className="settings-page__title">Settings</h1>
      </header>

      <div className="settings-page__content">
        {/* Model Configuration */}
        <section className="settings-section">
          <div className="settings-section__header">
            <div className="settings-section__icon">
              <Cpu size={20} />
            </div>
            <div>
              <h2 className="settings-section__title">Embedding Model</h2>
              <p className="settings-section__description">Configure the AI model for document embeddings</p>
            </div>
          </div>
          
          <div className="settings-section__content">
            <div className="status-card">
              <div className={`status-card__indicator status-card__indicator--${getStatusIndicator()}`} />
              <div className="status-card__content">
                <div className="status-card__title">Model Status</div>
                <div className="status-card__text">{getStatusText()}</div>
              </div>
              {isLoading && <Loader2 size={18} className="animate-spin" />}
            </div>

            <div className="settings-form__group">
              <label className="settings-form__label">Model Path</label>
              <div className="settings-form__input-wrapper">
                <input
                  type="text"
                  className="settings-form__input"
                  placeholder="Enter path to embedding model folder..."
                  value={modelPath}
                  onChange={(e) => setModelPath(e.target.value)}
                />
                <button
                  className="settings-btn settings-btn--primary"
                  onClick={handleSave}
                  disabled={isSaving || !modelPath.trim()}
                >
                  {isSaving ? <Loader2 size={16} className="animate-spin" /> : <Save size={16} />}
                  Save
                </button>
              </div>
              <p className="settings-form__hint">
                Path to local SentenceTransformer model (e.g., all-MiniLM-L6-v2)
              </p>
            </div>

            {saveMessage && (
              <div className={`settings-alert settings-alert--${saveMessage.type}`}>
                {saveMessage.type === 'success' ? <CheckCircle size={18} /> : <XCircle size={18} />}
                {saveMessage.text}
              </div>
            )}
          </div>
        </section>

        {/* Appearance */}
        <section className="settings-section">
          <div className="settings-section__header">
            <div className="settings-section__icon">
              <Sun size={20} />
            </div>
            <div>
              <h2 className="settings-section__title">Appearance</h2>
              <p className="settings-section__description">Customize the look and feel</p>
            </div>
          </div>
          
          <div className="settings-section__content">
            <div className="settings-form__group">
              <label className="settings-form__label">Theme</label>
              <div className="theme-toggle-group">
                <button
                  className={`theme-option ${theme === 'light' ? 'theme-option--active' : ''}`}
                  onClick={() => setTheme('light')}
                >
                  <div className="theme-option__icon">
                    <Sun size={20} />
                  </div>
                  <span className="theme-option__label">Light</span>
                </button>
                <button
                  className={`theme-option ${theme === 'dark' ? 'theme-option--active' : ''}`}
                  onClick={() => setTheme('dark')}
                >
                  <div className="theme-option__icon">
                    <Moon size={20} />
                  </div>
                  <span className="theme-option__label">Dark</span>
                </button>
              </div>
            </div>
          </div>
        </section>
      </div>
    </div>
  );
}

export default Settings;
