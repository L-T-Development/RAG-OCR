import { useState, useEffect, useCallback } from 'react';
import { useNavigate } from 'react-router-dom';
import { useTheme } from '../context/ThemeContext';
import { Navigation } from '../components/shared/Navigation';
import { api } from '../services/api';
import {
  ArrowLeft, Cpu, Moon, Sun,
  CheckCircle, XCircle, Loader2, Save, Sparkles, RefreshCw,
} from 'lucide-react';

export function Settings() {
  const navigate = useNavigate();
  const { theme, setTheme } = useTheme();

  // Ollama model list (shared by both sections)
  const [ollamaModels, setOllamaModels] = useState([]);
  const [isLoadingModels, setIsLoadingModels] = useState(true);

  // Embedding
  const [embeddingModel, setEmbeddingModel] = useState('');
  const [modelStatus, setModelStatus] = useState(null);
  const [isLoadingStatus, setIsLoadingStatus] = useState(true);
  const [isSaving, setIsSaving] = useState(false);
  const [saveMessage, setSaveMessage] = useState(null);

  // LLM
  const [currentLLM, setCurrentLLM] = useState('');
  const [selectedLLM, setSelectedLLM] = useState('');
  const [isSwitchingLLM, setIsSwitchingLLM] = useState(false);
  const [llmMessage, setLlmMessage] = useState(null);

  const fetchOllamaModels = useCallback(async () => {
    setIsLoadingModels(true);
    try {
      const result = await api.getOllamaModels();
      if (result.ok) {
        setOllamaModels(result.data.models || []);
      }
    } catch (error) {
      console.error('Failed to fetch Ollama models:', error);
    } finally {
      setIsLoadingModels(false);
    }
  }, []);

  const fetchModelStatus = useCallback(async () => {
    setIsLoadingStatus(true);
    try {
      const result = await api.getModelStatus();
      if (result.ok) {
        setModelStatus(result.data);
        const configured = result.data.ollama_model || '';
        setEmbeddingModel(configured);
      }
    } catch (error) {
      console.error('Failed to fetch model status:', error);
    } finally {
      setIsLoadingStatus(false);
    }
  }, []);

  const fetchLLMCurrent = useCallback(async () => {
    try {
      const result = await api.getLLMModels();
      if (result.ok) {
        const cur = result.data.current || '';
        setCurrentLLM(cur);
        setSelectedLLM(cur);
      }
    } catch (error) {
      console.error('Failed to fetch current LLM:', error);
    }
  }, []);

  useEffect(() => {
    fetchOllamaModels();
    fetchModelStatus();
    fetchLLMCurrent();
  }, [fetchOllamaModels, fetchModelStatus, fetchLLMCurrent]);

  const handleSaveEmbedding = async () => {
    if (!embeddingModel) {
      setSaveMessage({ type: 'error', text: 'Please select an embedding model' });
      return;
    }
    setIsSaving(true);
    setSaveMessage(null);
    try {
      const result = await api.configureEmbeddingProvider('ollama', embeddingModel);
      if (result.ok && result.data.status?.loaded) {
        setSaveMessage({ type: 'success', text: 'Embedding model configured successfully!' });
        setModelStatus(result.data.status);
      } else {
        setSaveMessage({ type: 'error', text: result.data.error || result.data.status?.error || 'Failed to configure model' });
      }
    } catch {
      setSaveMessage({ type: 'error', text: 'Network error. Is Ollama running? (http://localhost:11434)' });
    } finally {
      setIsSaving(false);
    }
  };

  const handleSwitchLLM = async () => {
    if (!selectedLLM || selectedLLM === currentLLM || isSwitchingLLM) return;
    setIsSwitchingLLM(true);
    setLlmMessage(null);
    try {
      const result = await api.selectLLMModel(selectedLLM);
      if (result.ok) {
        setCurrentLLM(selectedLLM);
        setLlmMessage({ type: 'success', text: 'LLM model switched successfully!' });
      } else {
        setLlmMessage({ type: 'error', text: result.data?.error || 'Failed to switch model' });
      }
    } catch {
      setLlmMessage({ type: 'error', text: 'Network error. Please try again.' });
    } finally {
      setIsSwitchingLLM(false);
    }
  };

  const getStatusIndicator = () => {
    if (isLoadingStatus) return 'warning';
    if (modelStatus?.loaded) return 'success';
    return 'error';
  };

  const getStatusText = () => {
    if (isLoadingStatus) return 'Loading...';
    if (modelStatus?.loaded) return 'Model loaded and ready';
    return modelStatus?.error || 'Model not configured';
  };

  const indicatorCls = {
    success: 'bg-green-500 shadow-[0_0_8px_#10b981]',
    error: 'bg-red-500',
    warning: 'bg-yellow-500 animate-pulse',
  }[getStatusIndicator()];

  const selectCls = 'flex-1 px-3 py-2 text-sm text-[var(--color-text-primary)] bg-[var(--color-bg-secondary)] border border-[var(--color-border)] rounded-lg focus:outline-none focus:border-[var(--color-border-focus)] focus:ring-2 focus:ring-blue-100 transition-colors disabled:opacity-60';

  const saveBtnCls = 'px-4 py-2 text-sm font-medium bg-primary text-white rounded-lg hover:bg-primary-hover disabled:opacity-50 disabled:cursor-not-allowed inline-flex items-center gap-1.5 transition-colors';

  const alertCls = (type) => `p-4 rounded-lg text-sm flex items-center gap-2 mt-4 border ${type === 'success' ? 'bg-green-50 text-green-800 border-green-500' : 'bg-red-50 text-red-800 border-red-500'}`;

  const sectionCls = 'bg-[var(--color-bg-primary)] border border-[var(--color-border)] rounded-xl mb-5 overflow-hidden';
  const sectionHeaderCls = 'px-5 py-4 border-b border-[var(--color-border)] flex items-center gap-3';
  const sectionIconCls = 'w-9 h-9 bg-primary-light rounded-lg flex items-center justify-center text-primary shrink-0';

  const modelDropdown = (value, onChange, placeholder) => (
    isLoadingModels ? (
      <div className="flex-1 flex items-center gap-2 px-3 py-2 text-sm text-[var(--color-text-muted)] bg-[var(--color-bg-secondary)] border border-[var(--color-border)] rounded-lg">
        <Loader2 size={14} className="animate-spin" />
        Loading models from Ollama...
      </div>
    ) : ollamaModels.length === 0 ? (
      <div className="flex-1 px-3 py-2 text-sm text-red-500 bg-[var(--color-bg-secondary)] border border-red-300 rounded-lg">
        No models found — is Ollama running?
      </div>
    ) : (
      <select className={selectCls} value={value} onChange={e => onChange(e.target.value)}>
        {!value && <option value="">{placeholder}</option>}
        {ollamaModels.map(m => (
          <option key={m} value={m}>{m}</option>
        ))}
      </select>
    )
  );

  return (
    <div className="min-h-screen bg-[var(--color-bg-secondary)] text-[var(--color-text-primary)]">
      <Navigation />

      <header className="mt-14 bg-[var(--color-bg-primary)] border-b border-[var(--color-border)] px-6 py-4 flex items-center gap-4">
        <button
          className="w-10 h-10 flex items-center justify-center bg-[var(--color-bg-secondary)] border border-[var(--color-border)] rounded-lg text-[var(--color-text-secondary)] hover:bg-[var(--color-bg-hover)] hover:text-[var(--color-text-primary)] transition-colors"
          onClick={() => navigate(-1)}
        >
          <ArrowLeft size={20} />
        </button>
        <h1 className="text-xl font-semibold text-[var(--color-text-primary)]">Settings</h1>
        <button
          className="ml-auto w-9 h-9 flex items-center justify-center text-[var(--color-text-muted)] hover:text-[var(--color-text-primary)] transition-colors"
          onClick={() => { fetchOllamaModels(); fetchModelStatus(); fetchLLMCurrent(); }}
          title="Refresh model list"
        >
          <RefreshCw size={16} className={isLoadingModels ? 'animate-spin' : ''} />
        </button>
      </header>

      <div className="max-w-3xl mx-auto px-6 py-6">

        {/* ── Embedding Model ────────────────────────────────────── */}
        <section className={sectionCls}>
          <div className={sectionHeaderCls}>
            <div className={sectionIconCls}><Cpu size={20} /></div>
            <div>
              <h2 className="text-base font-semibold text-[var(--color-text-primary)]">Embedding Model</h2>
              <p className="text-sm text-[var(--color-text-muted)]">Model used to embed documents into the vector store</p>
            </div>
          </div>

          <div className="p-5">
            {/* Status card */}
            <div className="flex items-center gap-4 p-4 bg-[var(--color-bg-secondary)] rounded-lg mb-4">
              <div className={`w-3 h-3 rounded-full shrink-0 ${indicatorCls}`} />
              <div className="flex-1">
                <div className="text-sm font-medium text-[var(--color-text-primary)]">Model Status</div>
                <div className="text-xs text-[var(--color-text-muted)]">{getStatusText()}</div>
                {modelStatus?.loaded && modelStatus?.ollama_model && (
                  <div className="text-xs text-[var(--color-text-muted)] mt-1 opacity-70">
                    Active: {modelStatus.ollama_model}
                  </div>
                )}
              </div>
              {isLoadingStatus && <Loader2 size={18} className="animate-spin" />}
            </div>

            <div className="mb-5">
              <label className="block text-sm font-medium text-[var(--color-text-secondary)] mb-2">Select Embedding Model</label>
              <div className="flex gap-2">
                {modelDropdown(embeddingModel, setEmbeddingModel, '— choose a model —')}
                <button
                  className={saveBtnCls}
                  onClick={handleSaveEmbedding}
                  disabled={isSaving || !embeddingModel || isLoadingModels}
                >
                  {isSaving ? <Loader2 size={16} className="animate-spin" /> : <Save size={16} />}
                  Apply
                </button>
              </div>
              <p className="text-xs text-[var(--color-text-muted)] mt-1">
                Typical choice: <code className="bg-[var(--color-bg-tertiary)] px-1 rounded">nomic-embed-text:latest</code>. The model must already be pulled in Ollama.
              </p>
            </div>

            {saveMessage && (
              <div className={alertCls(saveMessage.type)}>
                {saveMessage.type === 'success' ? <CheckCircle size={18} /> : <XCircle size={18} />}
                {saveMessage.text}
              </div>
            )}
          </div>
        </section>

        {/* ── LLM / Reasoning Model ─────────────────────────────── */}
        <section className={sectionCls}>
          <div className={sectionHeaderCls}>
            <div className={sectionIconCls}><Sparkles size={20} /></div>
            <div>
              <h2 className="text-base font-semibold text-[var(--color-text-primary)]">Reasoning Model</h2>
              <p className="text-sm text-[var(--color-text-muted)]">Model used for chat, Q&amp;A, and summarization</p>
            </div>
          </div>

          <div className="p-5">
            {currentLLM && (
              <div className="flex items-center gap-3 p-3 bg-[var(--color-bg-secondary)] rounded-lg mb-4 text-sm">
                <CheckCircle size={16} className="text-green-500 shrink-0" />
                <span className="text-[var(--color-text-muted)]">Active:</span>
                <code className="text-[var(--color-text-primary)] font-medium">{currentLLM}</code>
              </div>
            )}

            <div className="mb-5">
              <label className="block text-sm font-medium text-[var(--color-text-secondary)] mb-2">Select Reasoning Model</label>
              <div className="flex gap-2">
                {modelDropdown(selectedLLM, setSelectedLLM, '— choose a model —')}
                <button
                  className={saveBtnCls}
                  onClick={handleSwitchLLM}
                  disabled={isSwitchingLLM || !selectedLLM || selectedLLM === currentLLM || isLoadingModels}
                >
                  {isSwitchingLLM ? <Loader2 size={16} className="animate-spin" /> : <Save size={16} />}
                  Apply
                </button>
              </div>
              <p className="text-xs text-[var(--color-text-muted)] mt-1">
                Any model installed in Ollama can be used. Larger models are slower but more accurate.
              </p>
            </div>

            {llmMessage && (
              <div className={alertCls(llmMessage.type)}>
                {llmMessage.type === 'success' ? <CheckCircle size={18} /> : <XCircle size={18} />}
                {llmMessage.text}
              </div>
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
