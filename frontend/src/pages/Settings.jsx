import { useState, useEffect, useCallback } from 'react';
import { useNavigate } from 'react-router-dom';
import { useTheme } from '../context/ThemeContext';
import { Navigation } from '../components/shared/Navigation';
import { api } from '../services/api';
import {
  ArrowLeft, Cpu, Moon, Sun, Monitor,
  CheckCircle, XCircle, Loader2, Save, Zap, Scale, Sparkles,
} from 'lucide-react';

export function Settings() {
  const navigate = useNavigate();
  const { theme, setTheme } = useTheme();

  const [embeddingProvider, setEmbeddingProvider] = useState('sentence-transformers');
  const [ollamaModel, setOllamaModel] = useState('nomic-embed-text.v1.5:latest');
  const [modelPath, setModelPath] = useState('');
  const [modelStatus, setModelStatus] = useState(null);
  const [isLoading, setIsLoading] = useState(true);
  const [isSaving, setIsSaving] = useState(false);
  const [saveMessage, setSaveMessage] = useState(null);

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
        const provider = result.data.provider || 'sentence-transformers';
        setEmbeddingProvider(provider);
        if (provider === 'ollama') {
          const configuredModel = result.data.ollama_model || 'nomic-embed-text.v1.5:latest';
          setOllamaModel(configuredModel === 'nomic-embed-text' ? 'nomic-embed-text.v1.5:latest' : configuredModel);
        } else {
          setModelPath(result.data.saved_path || result.data.path || 'models/all-MiniLM-L6-v2');
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
        setLlmModels(result.data.models || llmModels.map(m => ({ ...m, selected: m.id === modelId })));
        setLlmMessage({ type: 'success', text: 'LLM model switched successfully!' });
      } else {
        setLlmMessage({ type: 'error', text: result.data.error || 'Failed to switch model' });
      }
    } catch {
      setLlmMessage({ type: 'error', text: 'Network error. Please try again.' });
    } finally {
      setIsSwitchingLLM(false);
    }
  };

  const handleSave = async () => {
    const model = embeddingProvider === 'ollama' ? ollamaModel : modelPath;
    if (!model.trim()) {
      setSaveMessage({ type: 'error', text: embeddingProvider === 'ollama' ? 'Please enter an Ollama model name' : 'Please enter a model path' });
      return;
    }
    setIsSaving(true);
    setSaveMessage(null);
    try {
      const result = await api.configureEmbeddingProvider(embeddingProvider, model);
      if (result.ok && result.data.status?.loaded) {
        setSaveMessage({ type: 'success', text: `${embeddingProvider === 'ollama' ? 'Ollama' : 'Embedding'} model configured successfully!` });
        setModelStatus(result.data.status);
      } else {
        setSaveMessage({ type: 'error', text: result.data.error || result.data.status?.error || 'Failed to configure model' });
      }
    } catch {
      setSaveMessage({ type: 'error', text: 'Network error. Is Ollama running?' + (embeddingProvider === 'ollama' ? ' (http://localhost:11434)' : '') });
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

  const indicatorCls = {
    success: 'bg-green-500 shadow-[0_0_8px_#10b981]',
    error: 'bg-red-500',
    warning: 'bg-yellow-500 animate-pulse',
  }[getStatusIndicator()];

  const tierIconCls = {
    efficient: 'bg-gradient-to-br from-green-500 to-green-600',
    balanced: 'bg-gradient-to-br from-blue-500 to-blue-600',
    performance: 'bg-gradient-to-br from-violet-500 to-violet-700',
  };

  const inputCls = 'flex-1 px-3 py-2 text-sm text-[var(--color-text-primary)] bg-[var(--color-bg-secondary)] border border-[var(--color-border)] rounded-lg focus:outline-none focus:border-[var(--color-border-focus)] focus:ring-2 focus:ring-blue-100 placeholder:text-[var(--color-text-muted)] transition-colors';

  const saveBtnCls = 'px-4 py-2 text-sm font-medium bg-primary text-white rounded-lg hover:bg-primary-hover disabled:opacity-50 disabled:cursor-not-allowed inline-flex items-center gap-1.5 transition-colors';

  const alertCls = (type) => `p-4 rounded-lg text-sm flex items-center gap-2 mt-4 border ${type === 'success' ? 'bg-green-50 text-green-800 border-green-500' : 'bg-red-50 text-red-800 border-red-500'}`;

  const sectionCls = 'bg-[var(--color-bg-primary)] border border-[var(--color-border)] rounded-xl mb-5 overflow-hidden';
  const sectionHeaderCls = 'px-5 py-4 border-b border-[var(--color-border)] flex items-center gap-3';
  const sectionIconCls = 'w-9 h-9 bg-primary-light rounded-lg flex items-center justify-center text-primary shrink-0';

  return (
    <div className="min-h-screen bg-[var(--color-bg-secondary)] text-[var(--color-text-primary)]">
      <Navigation />

      <header className="bg-[var(--color-bg-primary)] border-b border-[var(--color-border)] px-6 py-4 flex items-center gap-4">
        <button
          className="w-10 h-10 flex items-center justify-center bg-[var(--color-bg-secondary)] border border-[var(--color-border)] rounded-lg text-[var(--color-text-secondary)] hover:bg-[var(--color-bg-hover)] hover:text-[var(--color-text-primary)] transition-colors"
          onClick={() => navigate(-1)}
        >
          <ArrowLeft size={20} />
        </button>
        <h1 className="text-xl font-semibold text-[var(--color-text-primary)]">Settings</h1>
      </header>

      <div className="max-w-3xl mx-auto px-6 py-6">

        {/* ── Embedding Model ────────────────────────────────────── */}
        <section className={sectionCls}>
          <div className={sectionHeaderCls}>
            <div className={sectionIconCls}><Cpu size={20} /></div>
            <div>
              <h2 className="text-base font-semibold text-[var(--color-text-primary)]">Embedding Model</h2>
              <p className="text-sm text-[var(--color-text-muted)]">Configure the AI model for document embeddings</p>
            </div>
          </div>

          <div className="p-5">
            {/* Status card */}
            <div className="flex items-center gap-4 p-4 bg-[var(--color-bg-secondary)] rounded-lg mb-4">
              <div className={`w-3 h-3 rounded-full shrink-0 ${indicatorCls}`} />
              <div className="flex-1">
                <div className="text-sm font-medium text-[var(--color-text-primary)]">Model Status</div>
                <div className="text-xs text-[var(--color-text-muted)]">{getStatusText()}</div>
                {modelStatus?.provider && (
                  <div className="text-xs text-[var(--color-text-muted)] mt-1 opacity-70">
                    Provider: {modelStatus.provider === 'ollama'
                      ? 'Ollama (nomic-embed-text.v1.5:latest, 768 dims, 8K context)'
                      : 'SentenceTransformers (384 dims, 256 tokens)'}
                  </div>
                )}
              </div>
              {isLoading && <Loader2 size={18} className="animate-spin" />}
            </div>

            {/* Provider selector */}
            <div className="mb-5">
              <label className="block text-sm font-medium text-[var(--color-text-secondary)] mb-2">Embedding Provider</label>
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-2 mb-3">
                {[
                  { id: 'sentence-transformers', icon: <Monitor size={16} />, label: 'Local (SentenceTransformers)', badge: 'Fast' },
                  { id: 'ollama', icon: <Sparkles size={16} />, label: 'Ollama (nomic-embed-text.v1.5:latest)', badge: 'Better Quality' },
                ].map(opt => {
                  const active = embeddingProvider === opt.id;
                  return (
                    <button
                      key={opt.id}
                      className={`flex items-center gap-1.5 px-3 py-2 border-2 rounded-lg text-sm font-medium disabled:opacity-50 disabled:cursor-not-allowed transition-all ${active ? 'bg-primary-light border-primary text-primary' : 'bg-[var(--color-bg-secondary)] border-[var(--color-border)] text-[var(--color-text-secondary)] hover:bg-[var(--color-bg-hover)] hover:border-primary hover:text-[var(--color-text-primary)]'}`}
                      onClick={() => setEmbeddingProvider(opt.id)}
                      disabled={isSaving}
                    >
                      {opt.icon}
                      <span className="truncate">{opt.label}</span>
                      <span className={`ml-auto shrink-0 px-2 py-0.5 rounded text-xs font-semibold ${active ? 'bg-primary text-white' : 'bg-[var(--color-bg-tertiary)] text-[var(--color-text-secondary)]'}`}>{opt.badge}</span>
                    </button>
                  );
                })}
              </div>
              <p className="text-xs text-[var(--color-text-muted)]">
                {embeddingProvider === 'ollama'
                  ? '✨ Ollama provides 768-dim embeddings with 8K context - better for technical documents, part numbers, and long table rows. Requires Ollama running.'
                  : '⚡ Local model is faster and works offline - good for general documents with shorter text.'}
              </p>
            </div>

            {embeddingProvider === 'sentence-transformers' ? (
              <div className="mb-5">
                <label className="block text-sm font-medium text-[var(--color-text-secondary)] mb-2">Model Path</label>
                <div className="flex gap-2">
                  <input type="text" className={inputCls} placeholder="Enter path to embedding model folder..." value={modelPath} onChange={e => setModelPath(e.target.value)} />
                  <button className={saveBtnCls} onClick={handleSave} disabled={isSaving || !modelPath.trim()}>
                    {isSaving ? <Loader2 size={16} className="animate-spin" /> : <Save size={16} />}
                    Save
                  </button>
                </div>
                <p className="text-xs text-[var(--color-text-muted)] mt-1">Relative path from project root (e.g., models/all-MiniLM-L6-v2) or absolute path.</p>
              </div>
            ) : (
              <div className="mb-5">
                <label className="block text-sm font-medium text-[var(--color-text-secondary)] mb-2">Ollama Model</label>
                <div className="flex gap-2">
                  <input type="text" className={inputCls} placeholder="nomic-embed-text.v1.5:latest" value={ollamaModel} onChange={e => setOllamaModel(e.target.value)} />
                  <button className={saveBtnCls} onClick={handleSave} disabled={isSaving || !ollamaModel.trim()}>
                    {isSaving ? <Loader2 size={16} className="animate-spin" /> : <Save size={16} />}
                    Apply
                  </button>
                </div>
                <p className="text-xs text-[var(--color-text-muted)] mt-1">Ollama model name (e.g., nomic-embed-text.v1.5:latest). Run &apos;ollama pull nomic-embed-text.v1.5:latest&apos; first.</p>
              </div>
            )}

            {saveMessage && (
              <div className={alertCls(saveMessage.type)}>
                {saveMessage.type === 'success' ? <CheckCircle size={18} /> : <XCircle size={18} />}
                {saveMessage.text}
              </div>
            )}
          </div>
        </section>

        {/* ── LLM Model ─────────────────────────────────────────── */}
        <section className={sectionCls}>
          <div className={sectionHeaderCls}>
            <div className={sectionIconCls}><Sparkles size={20} /></div>
            <div>
              <h2 className="text-base font-semibold text-[var(--color-text-primary)]">LLM Model</h2>
              <p className="text-sm text-[var(--color-text-muted)]">Select the AI model for chat and summarization</p>
            </div>
          </div>

          <div className="p-5">
            {isLoadingLLM ? (
              <div className="flex items-center gap-4 p-4 bg-[var(--color-bg-secondary)] rounded-lg">
                <Loader2 size={18} className="animate-spin" />
                <div className="text-sm text-[var(--color-text-muted)]">Loading available models...</div>
              </div>
            ) : (
              <>
                <div className="mb-5">
                  <label className="block text-sm font-medium text-[var(--color-text-secondary)] mb-2">Choose Model</label>
                  <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
                    {llmModels.map(model => {
                      const active = model.id === currentLLM;
                      return (
                        <button
                          key={model.id}
                          className={`relative p-4 border-2 rounded-xl text-left transition-all ${active ? 'border-primary bg-primary-light' : 'bg-[var(--color-bg-secondary)] border-[var(--color-border)]'} ${isSwitchingLLM ? 'opacity-70 cursor-not-allowed' : 'cursor-pointer hover:border-[var(--color-text-muted)] hover:-translate-y-0.5 hover:shadow-md'}`}
                          onClick={() => handleSelectLLM(model.id)}
                          disabled={isSwitchingLLM}
                        >
                          <div className="flex justify-between items-start mb-2">
                            <div className={`w-10 h-10 rounded-lg flex items-center justify-center text-white ${tierIconCls[model.tier] || 'bg-gray-500'}`}>
                              {model.tier === 'efficient' && <Zap size={20} />}
                              {model.tier === 'balanced' && <Scale size={20} />}
                              {model.tier === 'performance' && <Sparkles size={20} />}
                            </div>
                            {active && (
                              <div className="flex items-center gap-1 px-2 py-1 bg-green-500 text-white text-xs font-semibold rounded">
                                <CheckCircle size={14} />Active
                              </div>
                            )}
                          </div>
                          <div className="text-base font-semibold text-[var(--color-text-primary)] mb-0.5">{model.title}</div>
                          <div className="text-sm text-[var(--color-text-muted)] mb-2">{model.name}</div>
                          <div className="text-xs text-[var(--color-text-secondary)] leading-relaxed">{model.description}</div>
                          {isSwitchingLLM && !active && (
                            <div className="absolute top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2 bg-white/90 p-4 rounded-lg">
                              <Loader2 size={16} className="animate-spin" />
                            </div>
                          )}
                        </button>
                      );
                    })}
                  </div>
                </div>

                {llmMessage && (
                  <div className={alertCls(llmMessage.type)}>
                    {llmMessage.type === 'success' ? <CheckCircle size={18} /> : <XCircle size={18} />}
                    {llmMessage.text}
                  </div>
                )}
              </>
            )}
          </div>
        </section>

        {/* ── Appearance ────────────────────────────────────────── */}
        <section className={sectionCls}>
          <div className={sectionHeaderCls}>
            <div className={sectionIconCls}><Sun size={20} /></div>
            <div>
              <h2 className="text-base font-semibold text-[var(--color-text-primary)]">Appearance</h2>
              <p className="text-sm text-[var(--color-text-muted)]">Customize the look and feel</p>
            </div>
          </div>

          <div className="p-5">
            <label className="block text-sm font-medium text-[var(--color-text-secondary)] mb-2">Theme</label>
            <div className="flex gap-2">
              {[
                { id: 'light', icon: <Sun size={20} />, label: 'Light' },
                { id: 'dark', icon: <Moon size={20} />, label: 'Dark' },
              ].map(opt => {
                const active = theme === opt.id;
                return (
                  <button
                    key={opt.id}
                    className={`flex-1 p-4 border-2 rounded-lg cursor-pointer text-center transition-colors ${active ? 'border-primary bg-primary-light' : 'bg-[var(--color-bg-secondary)] border-[var(--color-border)] hover:border-[var(--color-text-muted)]'}`}
                    onClick={() => setTheme(opt.id)}
                  >
                    <div className={`w-10 h-10 mx-auto mb-2 rounded-lg flex items-center justify-center transition-colors ${active ? 'bg-primary text-white' : 'bg-[var(--color-bg-primary)] text-[var(--color-text-secondary)]'}`}>
                      {opt.icon}
                    </div>
                    <span className="text-sm font-medium text-[var(--color-text-primary)]">{opt.label}</span>
                  </button>
                );
              })}
            </div>
          </div>
        </section>
      </div>
    </div>
  );
}

export default Settings;
