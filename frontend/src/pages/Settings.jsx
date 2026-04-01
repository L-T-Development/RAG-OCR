import { useState, useEffect, useCallback } from 'react';
import { useNavigate } from 'react-router-dom';
import { useTheme } from '../context/ThemeContext';
import { Navigation } from '../components/shared/Navigation';
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
  Save,
  Zap,
  Scale,
  Sparkles,
} from 'lucide-react';
import './Settings.css';

export function Settings() {
  const navigate = useNavigate();
  const { theme, setTheme } = useTheme();

  // Embedding model state
  const [embeddingProvider, setEmbeddingProvider] = useState('sentence-transformers');
  const [ollamaModel, setOllamaModel] = useState('nomic-embed-text.v1.5:latest');
  const [modelPath, setModelPath] = useState('');
  const [modelStatus, setModelStatus] = useState(null);
  const [isLoading, setIsLoading] = useState(true);
  const [isSaving, setIsSaving] = useState(false);
  const [saveMessage, setSaveMessage] = useState(null);

  // LLM model state
  const [llmModels, setLlmModels] = useState([]);
  const [currentLLM, setCurrentLLM] = useState('');
  const [isLoadingLLM, setIsLoadingLLM] = useState(true);
  const [isSwitchingLLM, setIsSwitchingLLM] = useState(false);
  const [llmMessage, setLlmMessage] = useState(null);

  const fetchModelStatus = useCallback(async () => {
    try {
      setIsLoading(true);
      const result = await api.getModelStatus();
      if (result.ok) {
        setModelStatus(result.data);
        
        // Set provider type
        const provider = result.data.provider || 'sentence-transformers';
        setEmbeddingProvider(provider);
        
        // Set model path or name based on provider
        if (provider === 'ollama') {
          const configuredModel = result.data.ollama_model || 'nomic-embed-text.v1.5:latest';
          setOllamaModel(
            configuredModel === 'nomic-embed-text'
              ? 'nomic-embed-text.v1.5:latest'
              : configuredModel
          );
        } else {
          if (result.data.saved_path) {
            setModelPath(result.data.saved_path);
          } else if (result.data.path) {
            setModelPath(result.data.path);
          } else {
            setModelPath('models/all-MiniLM-L6-v2');
          }
        }
      }
    } catch (error) {
      console.error('Failed to fetch model status:', error);
      setModelPath('models/all-MiniLM-L6-v2');
    } finally {
      setIsLoading(false);
    }
  }, []);

  const fetchLLMModels = useCallback(async () => {
    try {
      setIsLoadingLLM(true);
      const result = await api.getLLMModels();
      if (result.ok) {
        setLlmModels(result.data.models || []);
        setCurrentLLM(result.data.current || '');
      }
    } catch (error) {
      console.error('Failed to fetch LLM models:', error);
    } finally {
      setIsLoadingLLM(false);
    }
  }, []);

  useEffect(() => {
    fetchModelStatus();
    fetchLLMModels();
  }, [fetchModelStatus, fetchLLMModels]);

  const handleSelectLLM = async (modelId) => {
    if (modelId === currentLLM || isSwitchingLLM) return;

    setIsSwitchingLLM(true);
    setLlmMessage(null);

    try {
      const result = await api.selectLLMModel(modelId);
      if (result.ok) {
        setCurrentLLM(modelId);
        setLlmModels(
          result.data.models ||
            llmModels.map((m) => ({
              ...m,
              selected: m.id === modelId,
            }))
        );
        setLlmMessage({
          type: 'success',
          text: 'LLM model switched successfully!',
        });
      } else {
        setLlmMessage({
          type: 'error',
          text: result.data.error || 'Failed to switch model',
        });
      }
    } catch (error) {
      setLlmMessage({
        type: 'error',
        text: 'Network error. Please try again.',
      });
    } finally {
      setIsSwitchingLLM(false);
    }
  };

  const handleSave = async () => {
    const model = embeddingProvider === 'ollama' ? ollamaModel : modelPath;
    
    if (!model.trim()) {
      setSaveMessage({ 
        type: 'error', 
        text: embeddingProvider === 'ollama' ? 'Please enter an Ollama model name' : 'Please enter a model path' 
      });
      return;
    }

    setIsSaving(true);
    setSaveMessage(null);

    try {
      const result = await api.configureEmbeddingProvider(embeddingProvider, model);
      if (result.ok && result.data.status?.loaded) {
        setSaveMessage({
          type: 'success',
          text: `${embeddingProvider === 'ollama' ? 'Ollama' : 'Embedding'} model configured successfully!`,
        });
        setModelStatus(result.data.status);
      } else {
        setSaveMessage({
          type: 'error',
          text:
            result.data.error ||
            result.data.status?.error ||
            'Failed to configure model',
        });
      }
    } catch (error) {
      setSaveMessage({
        type: 'error',
        text: 'Network error. Is Ollama running?' + (embeddingProvider === 'ollama' ? ' (http://localhost:11434)' : ''),
      });
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
      <Navigation />
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
              <p className="settings-section__description">
                Configure the AI model for document embeddings
              </p>
            </div>
          </div>

          <div className="settings-section__content">
            <div className="status-card">
              <div
                className={`status-card__indicator status-card__indicator--${getStatusIndicator()}`}
              />
              <div className="status-card__content">
                <div className="status-card__title">Model Status</div>
                <div className="status-card__text">{getStatusText()}</div>
                {modelStatus?.provider && (
                  <div className="status-card__text" style={{fontSize: '0.75rem', opacity: 0.7, marginTop: '4px'}}>
                    Provider: {modelStatus.provider === 'ollama' ? 'Ollama (nomic-embed-text.v1.5:latest, 768 dims, 8K context)' : 'SentenceTransformers (384 dims, 256 tokens)'}
                  </div>
                )}
              </div>
              {isLoading && <Loader2 size={18} className="animate-spin" />}
            </div>

            <div className="settings-form__group">
              <label className="settings-form__label">Embedding Provider</label>
              <div className="provider-selector">
                <button
                  className={`provider-btn ${embeddingProvider === 'sentence-transformers' ? 'provider-btn--active' : ''}`}
                  onClick={() => setEmbeddingProvider('sentence-transformers')}
                  disabled={isSaving}
                >
                  <Monitor size={16} />
                  <span>Local (SentenceTransformers)</span>
                  <span className="provider-badge">Fast</span>
                </button>
                <button
                  className={`provider-btn ${embeddingProvider === 'ollama' ? 'provider-btn--active' : ''}`}
                  onClick={() => setEmbeddingProvider('ollama')}
                  disabled={isSaving}
                >
                  <Sparkles size={16} />
                  <span>Ollama (nomic-embed-text.v1.5:latest)</span>
                  <span className="provider-badge">Better Quality</span>
                </button>
              </div>
              <p className="settings-form__hint">
                {embeddingProvider === 'ollama' 
                  ? '✨ Ollama provides 768-dim embeddings with 8K context - better for technical documents, part numbers, and long table rows. Requires Ollama running.'
                  : '⚡ Local model is faster and works offline - good for general documents with shorter text.'}
              </p>
            </div>

            {embeddingProvider === 'sentence-transformers' ? (
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
                    {isSaving ? (
                      <Loader2 size={16} className="animate-spin" />
                    ) : (
                      <Save size={16} />
                    )}
                    Save
                  </button>
                </div>
                <p className="settings-form__hint">
                  Relative path from project root (e.g., models/all-MiniLM-L6-v2) or absolute path.
                </p>
              </div>
            ) : (
              <div className="settings-form__group">
                <label className="settings-form__label">Ollama Model</label>
                <div className="settings-form__input-wrapper">
                  <input
                    type="text"
                    className="settings-form__input"
                    placeholder="nomic-embed-text.v1.5:latest"
                    value={ollamaModel}
                    onChange={(e) => setOllamaModel(e.target.value)}
                  />
                  <button
                    className="settings-btn settings-btn--primary"
                    onClick={handleSave}
                    disabled={isSaving || !ollamaModel.trim()}
                  >
                    {isSaving ? (
                      <Loader2 size={16} className="animate-spin" />
                    ) : (
                      <Save size={16} />
                    )}
                    Apply
                  </button>
                </div>
                <p className="settings-form__hint">
                  Ollama model name (e.g., nomic-embed-text.v1.5:latest). Run 'ollama pull nomic-embed-text.v1.5:latest' first.
                </p>
              </div>
            )}

            {saveMessage && (
              <div
                className={`settings-alert settings-alert--${saveMessage.type}`}
              >
                {saveMessage.type === 'success' ? (
                  <CheckCircle size={18} />
                ) : (
                  <XCircle size={18} />
                )}
                {saveMessage.text}
              </div>
            )}
          </div>
        </section>

        {/* LLM Model Selection */}
        <section className="settings-section">
          <div className="settings-section__header">
            <div className="settings-section__icon">
              <Sparkles size={20} />
            </div>
            <div>
              <h2 className="settings-section__title">LLM Model</h2>
              <p className="settings-section__description">
                Select the AI model for chat and summarization
              </p>
            </div>
          </div>

          <div className="settings-section__content">
            {isLoadingLLM ? (
              <div className="status-card">
                <Loader2 size={18} className="animate-spin" />
                <div className="status-card__content">
                  <div className="status-card__text">
                    Loading available models...
                  </div>
                </div>
              </div>
            ) : (
              <>
                <div className="settings-form__group">
                  <label className="settings-form__label">Choose Model</label>
                  <div className="llm-model-grid">
                    {llmModels.map((model) => (
                      <button
                        key={model.id}
                        className={`llm-model-card ${
                          model.id === currentLLM
                            ? 'llm-model-card--active'
                            : ''
                        } ${isSwitchingLLM ? 'llm-model-card--disabled' : ''}`}
                        onClick={() => handleSelectLLM(model.id)}
                        disabled={isSwitchingLLM}
                      >
                        <div className="llm-model-card__header">
                          <div
                            className={`llm-model-card__icon llm-model-card__icon--${model.tier}`}
                          >
                            {model.tier === 'efficient' && <Zap size={20} />}
                            {model.tier === 'balanced' && <Scale size={20} />}
                            {model.tier === 'performance' && (
                              <Sparkles size={20} />
                            )}
                          </div>
                          {model.id === currentLLM && (
                            <div className="llm-model-card__badge">
                              <CheckCircle size={14} />
                              Active
                            </div>
                          )}
                        </div>
                        <div className="llm-model-card__title">
                          {model.title}
                        </div>
                        <div className="llm-model-card__name">{model.name}</div>
                        <div className="llm-model-card__description">
                          {model.description}
                        </div>
                        {isSwitchingLLM && model.id !== currentLLM && (
                          <div className="llm-model-card__loading">
                            <Loader2 size={16} className="animate-spin" />
                          </div>
                        )}
                      </button>
                    ))}
                  </div>
                </div>

                {llmMessage && (
                  <div
                    className={`settings-alert settings-alert--${llmMessage.type}`}
                  >
                    {llmMessage.type === 'success' ? (
                      <CheckCircle size={18} />
                    ) : (
                      <XCircle size={18} />
                    )}
                    {llmMessage.text}
                  </div>
                )}
              </>
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
              <p className="settings-section__description">
                Customize the look and feel
              </p>
            </div>
          </div>

          <div className="settings-section__content">
            <div className="settings-form__group">
              <label className="settings-form__label">Theme</label>
              <div className="theme-toggle-group">
                <button
                  className={`theme-option ${
                    theme === 'light' ? 'theme-option--active' : ''
                  }`}
                  onClick={() => setTheme('light')}
                >
                  <div className="theme-option__icon">
                    <Sun size={20} />
                  </div>
                  <span className="theme-option__label">Light</span>
                </button>
                <button
                  className={`theme-option ${
                    theme === 'dark' ? 'theme-option--active' : ''
                  }`}
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
