import { useState, useRef, useEffect } from 'react';
import { Link } from 'react-router-dom';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import {
  Send,
  Paperclip,
  User,
  Bot,
  MessageSquare,
  FileText,
  Sparkles,
  ChevronDown,
  ChevronUp,
  BookOpen,
  GitCompare,
  FileSearch,
  Loader2,
  X,
} from 'lucide-react';

// Confidence Ring Component
function ConfidenceRing({ confidence, label }) {
  let score = 0;
  if (typeof confidence === 'number') {
    score =
      confidence > 1 ? Math.round(confidence) : Math.round(confidence * 100);
  }
  score = Math.max(0, Math.min(100, score));

  const radius = 18;
  const circumference = 2 * Math.PI * radius;
  const strokeDashoffset = circumference - (score / 100) * circumference;

  const getColor = (score) => {
    if (score >= 70) return 'var(--color-success)';
    if (score >= 40) return 'var(--color-warning)';
    return 'var(--color-error)';
  };

  return (
    <div
      className="relative flex items-center justify-center w-11 h-11 flex-shrink-0"
      title={`Confidence: ${score}% ${label ? `(${label})` : ''}`}
    >
      <svg width="44" height="44" viewBox="0 0 44 44">
        <circle
          cx="22"
          cy="22"
          r={radius}
          fill="none"
          stroke="var(--color-bg-tertiary)"
          strokeWidth="3"
        />
        <circle
          cx="22"
          cy="22"
          r={radius}
          fill="none"
          stroke={getColor(score)}
          strokeWidth="3"
          strokeLinecap="round"
          strokeDasharray={circumference}
          strokeDashoffset={strokeDashoffset}
          style={{
            transform: 'rotate(-90deg)',
            transformOrigin: '50% 50%',
            transition: 'stroke-dashoffset 0.5s ease-out',
          }}
        />
      </svg>
      <span className="absolute text-[10px] font-semibold text-[var(--color-text-primary)]">
        {score}%
      </span>
    </div>
  );
}

// Sources Panel Component
function SourcesPanel({ sources, chunks }) {
  const [isExpanded, setIsExpanded] = useState(false);

  if ((!sources || sources.length === 0) && (!chunks || chunks.length === 0)) {
    return null;
  }

  return (
    <div className="mt-2 rounded-md border border-[var(--color-border)] overflow-hidden text-sm">
      <button
        className="w-full flex items-center gap-2 px-3 py-2 bg-[var(--color-bg-secondary)] hover:bg-[var(--color-bg-hover)] text-[var(--color-text-secondary)] transition-colors cursor-pointer border-0 text-left"
        onClick={() => setIsExpanded(!isExpanded)}
      >
        <BookOpen size={14} />
        <span className="flex-1">Sources ({sources?.length || 0})</span>
        {isExpanded ? <ChevronUp size={14} /> : <ChevronDown size={14} />}
      </button>

      {isExpanded && (
        <div className="p-3 bg-[var(--color-bg-primary)] flex flex-col gap-3">
          {sources && sources.length > 0 && (
            <div>
              <div className="text-xs font-semibold uppercase tracking-wider text-[var(--color-text-muted)] mb-2">
                Referenced Documents
              </div>
              <div className="flex flex-wrap gap-1.5">
                {sources.map((source, idx) => (
                  <span
                    key={idx}
                    className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full bg-[var(--color-bg-secondary)] border border-[var(--color-border)] text-xs text-[var(--color-text-secondary)]"
                  >
                    <FileText size={12} />
                    {typeof source === 'string'
                      ? source
                      : source.filename || source.name || `Source ${idx + 1}`}
                  </span>
                ))}
              </div>
            </div>
          )}

          {chunks && chunks.length > 0 && (
            <div>
              <div className="text-xs font-semibold uppercase tracking-wider text-[var(--color-text-muted)] mb-2">
                Relevant Passages
              </div>
              <div className="flex flex-col gap-2">
                {chunks.slice(0, 3).map((chunk, idx) => (
                  <div
                    key={idx}
                    className="p-2 rounded-md bg-[var(--color-bg-secondary)] border border-[var(--color-border-light)]"
                  >
                    <div className="flex items-center justify-between mb-1">
                      <span className="text-xs font-medium text-[var(--color-text-secondary)]">
                        Passage {idx + 1}
                      </span>
                      {chunk.score && (
                        <span className="text-xs text-[var(--color-text-muted)]">
                          {Math.round(chunk.score * 100)}% match
                        </span>
                      )}
                    </div>
                    <p className="text-xs text-[var(--color-text-secondary)] leading-relaxed m-0">
                      {typeof chunk === 'string'
                        ? chunk.slice(0, 200)
                        : (chunk.text || chunk.content || '').slice(0, 200)}
                      {(typeof chunk === 'string'
                        ? chunk.length
                        : (chunk.text || chunk.content || '').length) > 200 &&
                        '...'}
                    </p>
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

function Message({ message, isUser }) {
  const getConfidence = () => {
    if (message.confidence !== undefined && message.confidence !== null) {
      return message.confidence;
    }
    const contentLength = (message.content || '').length;
    const sourceCount = (message.sources || []).length;
    const chunkCount = (message.chunks || []).length;

    let score = 0.3;
    if (contentLength > 100) score += 0.2;
    if (contentLength > 300) score += 0.1;
    if (sourceCount > 0) score += 0.2;
    if (chunkCount > 0) score += 0.2;

    return Math.min(score, 1);
  };

  return (
    <div className={`flex gap-3 px-4 py-3 ${isUser ? 'flex-row-reverse' : 'flex-row'}`}>
      {/* Avatar */}
      <div
        className={`flex-shrink-0 flex items-center justify-center w-8 h-8 rounded-full text-white text-sm
          ${isUser ? 'bg-[var(--color-message-user)]' : 'bg-[var(--color-bg-tertiary)] text-[var(--color-text-secondary)]'}`}
      >
        {isUser ? <User size={18} /> : <Bot size={18} />}
      </div>

      {/* Content */}
      <div className={`flex flex-col gap-1 max-w-[75%] ${isUser ? 'items-end' : 'items-start'}`}>
        <div
          className={`px-4 py-2.5 rounded-2xl text-sm leading-relaxed
            ${isUser
              ? 'bg-[var(--color-message-user)] text-[var(--color-message-user-text)] rounded-br-sm'
              : 'bg-[var(--color-message-assistant)] text-[var(--color-message-assistant-text)] rounded-bl-sm'
            }`}
        >
          {isUser ? (
            <p className="m-0">{message.content}</p>
          ) : (
            <div className="prose-chat">
              <ReactMarkdown remarkPlugins={[remarkGfm]}>
                {message.content}
              </ReactMarkdown>
            </div>
          )}
        </div>

        {!isUser && (
          <SourcesPanel sources={message.sources} chunks={message.chunks} />
        )}

        {/* Suggested Questions - NotebookLM style */}
        {!isUser && message.suggested_questions && message.suggested_questions.length > 0 && (
          <div className="message__suggested-questions">
            <div className="suggested-questions__header">
              <Sparkles size={14} />
              <span>Suggested questions</span>
            </div>
            <div className="suggested-questions__list">
              {message.suggested_questions.map((question, idx) => (
                <button
                  key={idx}
                  className="suggested-question__item"
                  onClick={() => {
                    setInputValue(question);
                    textareaRef.current?.focus();
                  }}
                  title="Click to ask this question"
                >
                  {question}
                </button>
              ))}
            </div>
          </div>
        )}

        <div className="message__meta">
          <span>{message.timestamp || 'Just now'}</span>
        </div>
      </div>

      {/* Confidence Ring - only for assistant */}
      {!isUser && (
        <div className="flex-shrink-0 self-start mt-1">
          <ConfidenceRing
            confidence={getConfidence()}
            label={message.confidence_label}
          />
        </div>
      )}
    </div>
  );
}

function LoadingMessage() {
  return (
    <div className="flex gap-3 px-4 py-3">
      <div className="flex-shrink-0 flex items-center justify-center w-8 h-8 rounded-full bg-[var(--color-bg-tertiary)] text-[var(--color-text-secondary)]">
        <Bot size={18} />
      </div>
      <div className="flex items-center gap-1.5 px-4 py-3 rounded-2xl rounded-bl-sm bg-[var(--color-message-assistant)]">
        <div className="loading-dot"></div>
        <div className="loading-dot"></div>
        <div className="loading-dot"></div>
      </div>
    </div>
  );
}

function EmptyChat({ onSuggestionClick }) {
  return (
    <div className="flex flex-col items-center justify-center h-full gap-4 px-8 text-center">
      <div className="flex items-center justify-center w-16 h-16 rounded-2xl bg-primary-light text-primary">
        <Sparkles size={36} />
      </div>
      <h2 className="text-xl font-semibold text-[var(--color-text-primary)] m-0">
        Start a conversation
      </h2>
      <p className="text-sm text-[var(--color-text-muted)] leading-relaxed max-w-sm m-0">
        Upload documents (PDF, Excel, or Word) and ask questions about their
        content. The AI will analyze and provide answers based on your
        documents.
      </p>
    </div>
  );
}

export function ChatArea({
  threadId,
  threadName,
  messages = [],
  documents = [],
  onSendMessage,
  onUploadClick,
  onSummarizeThread,
  onSummarizeDocument,
  isLoading = false,
  isSummarizing = false,
  disabled = false,
}) {
  const [inputValue, setInputValue] = useState('');
  const [selectedFiles, setSelectedFiles] = useState([]);
  const [showFilePicker, setShowFilePicker] = useState(false);
  const [fileFilterText, setFileFilterText] = useState('');
  const [selectedIndex, setSelectedIndex] = useState(0);
  const messagesContainerRef = useRef(null);
  const textareaRef = useRef(null);

  useEffect(() => {
    if (messagesContainerRef.current) {
      messagesContainerRef.current.scrollTop =
        messagesContainerRef.current.scrollHeight;
    }
  }, [messages, isLoading]);

  useEffect(() => {
    if (textareaRef.current) {
      textareaRef.current.style.height = 'auto';
      textareaRef.current.style.height = `${textareaRef.current.scrollHeight}px`;
    }
  }, [inputValue]);

  const handleInputChange = (e) => {
    const value = e.target.value;
    setInputValue(value);

    const lastAtPos = value.lastIndexOf('@');
    if (lastAtPos !== -1 && (lastAtPos === 0 || value[lastAtPos - 1] === ' ')) {
      const filterText = value.slice(lastAtPos + 1);
      if (!filterText.includes(' ')) {
        setFileFilterText(filterText);
        setShowFilePicker(true);
        setSelectedIndex(0);
        return;
      }
    }
    setShowFilePicker(false);
  };

  const filteredDocs = documents.filter((doc) =>
    doc.name.toLowerCase().includes(fileFilterText.toLowerCase())
  );

  const handleSelectFile = (doc) => {
    // Insert @filename directly into the input text
    if (!selectedFiles.find((f) => f.id === doc.id)) {
      setSelectedFiles((prev) => [...prev, doc]);
    }
    const lastAtPos = inputValue.lastIndexOf('@');
    const beforeAt = inputValue.slice(0, lastAtPos);
    const afterAt = inputValue.slice(lastAtPos + 1 + fileFilterText.length);
    const newValue = `${beforeAt}@${doc.name} ${afterAt}`;
    
    setInputValue(newValue);
    setShowFilePicker(false);
    setFileFilterText('');
    textareaRef.current?.focus();
  };

  const handleRemoveFile = (docId) => {
    setSelectedFiles((prev) => prev.filter((f) => f.id !== docId));
  };

  const handleSubmit = (e) => {
    e?.preventDefault();
    if (!inputValue.trim() || isLoading || disabled) return;

    // Send query as-is (already contains @filename tags in the text)
    const query = inputValue.trim();

    onSendMessage(query);
    setInputValue('');
    setSelectedFiles([]);

    if (textareaRef.current) {
      textareaRef.current.style.height = 'auto';
    }
  };

  const handleKeyDown = (e) => {
    if (showFilePicker && filteredDocs.length > 0) {
      if (e.key === 'ArrowDown') {
        e.preventDefault();
        setSelectedIndex((prev) => (prev + 1) % filteredDocs.length);
        return;
      }
      if (e.key === 'ArrowUp') {
        e.preventDefault();
        setSelectedIndex(
          (prev) => (prev - 1 + filteredDocs.length) % filteredDocs.length
        );
        return;
      }
      if (e.key === 'Enter') {
        e.preventDefault();
        handleSelectFile(filteredDocs[selectedIndex]);
        return;
      }
      if (e.key === 'Escape') {
        setShowFilePicker(false);
        return;
      }
    }

    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleSubmit();
    }
    if (e.key === 'Escape' && showFilePicker) {
      setShowFilePicker(false);
    }
  };

  const handleSuggestionClick = (suggestion) => {
    setInputValue(suggestion);
    textareaRef.current?.focus();
  };

  if (!threadId) {
    return (
      <div className="flex flex-col flex-1 items-center justify-center bg-[var(--color-bg-primary)] gap-4 text-center px-8">
        <div className="flex items-center justify-center w-14 h-14 rounded-2xl bg-[var(--color-bg-secondary)] text-[var(--color-text-muted)]">
          <MessageSquare size={28} />
        </div>
        <h2 className="text-lg font-semibold text-[var(--color-text-primary)] m-0">
          No thread selected
        </h2>
        <p className="text-sm text-[var(--color-text-muted)] m-0">
          Select or create a thread to start chatting
        </p>
        <div className="mt-2">
          <Link
            to="/reports"
            className="inline-flex items-center gap-2 px-4 py-2 bg-primary hover:bg-primary-hover text-white rounded-lg no-underline text-sm font-medium transition-colors"
          >
            <FileSearch size={18} />
            <span>Go to Reports</span>
          </Link>
        </div>
      </div>
    );
  }

  return (
    <div className="flex flex-col flex-1 min-h-0 bg-[var(--color-bg-primary)]">
      {/* Header */}
      <header className="flex items-center justify-between px-5 py-3 border-b border-[var(--color-border)] bg-[var(--color-bg-primary)] flex-shrink-0">
        <div className="flex items-center gap-3">
          <div>
            <h1 className="text-base font-semibold text-[var(--color-text-primary)] m-0">
              {threadName || 'Chat'}
            </h1>
            <div className="flex items-center gap-1 text-xs text-[var(--color-text-muted)] mt-0.5">
              <FileText size={12} />
              {messages.length} messages
            </div>
          </div>
        </div>
        <div className="flex items-center gap-2">
          {documents.length > 0 && onSummarizeThread && (
            <button
              className="flex items-center gap-1.5 px-3 py-1.5 rounded-md text-sm text-[var(--color-text-secondary)] border border-[var(--color-border)] hover:bg-[var(--color-bg-hover)] transition-colors disabled:opacity-50 disabled:cursor-not-allowed cursor-pointer bg-transparent"
              onClick={onSummarizeThread}
              disabled={isSummarizing}
              title="Summarize all documents"
            >
              {isSummarizing ? (
                <Loader2 size={16} className="animate-spin" />
              ) : (
                <FileSearch size={16} />
              )}
              <span>Summarize</span>
            </button>
          )}
        </div>
      </header>

      {/* Messages */}
      <div
        className="flex-1 overflow-y-auto py-4"
        ref={messagesContainerRef}
      >
        {messages.length === 0 ? (
          <EmptyChat onSuggestionClick={handleSuggestionClick} />
        ) : (
          <>
            {messages.map((msg, idx) => (
              <Message
                key={msg.id || idx}
                message={msg}
                isUser={msg.role === 'user'}
              />
            ))}
            {isLoading && <LoadingMessage />}
          </>
        )}
      </div>

      <div className="chat-area__input-container">
          {/* Selected Files Indicator */}
        {selectedFiles.length > 0 && (
          <div className="flex flex-wrap gap-1.5 mb-2">
            {selectedFiles.map((file) => (
              <span
                key={file.id}
                className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full bg-primary-light text-primary text-xs font-medium"
              >
                <FileText size={12} />
                {file.name}
                <button
                  className="ml-0.5 hover:text-primary-hover transition-colors cursor-pointer border-0 bg-transparent p-0 flex items-center"
                  onClick={() => handleRemoveFile(file.id)}
                >
                  <X size={12} />
                </button>
              </span>
            ))}
          </div>
        )}

        {/* @ File Picker */}
        {showFilePicker && documents.length > 0 && (
          <div className="mb-2 rounded-lg border border-[var(--color-border)] bg-[var(--color-bg-primary)] shadow-[var(--shadow-md)] overflow-hidden">
            <div className="flex items-center gap-2 px-3 py-2 border-b border-[var(--color-border)] text-xs text-[var(--color-text-muted)] bg-[var(--color-bg-secondary)]">
              <FileText size={14} />
              <span>
                Select document{' '}
                {fileFilterText && `(filtering: "${fileFilterText}")`}
              </span>
            </div>
            <div className="max-h-48 overflow-y-auto">
              {filteredDocs.length > 0 ? (
                filteredDocs.map((doc, idx) => (
                  <button
                    key={doc.id}
                    className={`w-full flex items-center gap-2 px-3 py-2 text-sm text-left cursor-pointer border-0 transition-colors
                      ${idx === selectedIndex
                        ? 'bg-primary-light text-primary'
                        : 'bg-transparent text-[var(--color-text-primary)] hover:bg-[var(--color-bg-hover)]'
                      }`}
                    onClick={() => handleSelectFile(doc)}
                  >
                    <FileText size={14} />
                    <span>{doc.name}</span>
                  </button>
                ))
              ) : (
                <div className="px-3 py-3 text-sm text-[var(--color-text-muted)] text-center">
                  No documents match "{fileFilterText}"
                </div>
              )}
            </div>
          </div>
        )}
        {showFilePicker && documents.length === 0 && (
          <div className="mb-2 rounded-lg border border-[var(--color-border)] bg-[var(--color-bg-primary)] shadow-[var(--shadow-md)]">
            <div className="px-3 py-3 text-sm text-[var(--color-text-muted)] text-center">
              No documents uploaded yet. Upload a PDF first.
            </div>
          </div>
        )}

        {/* Input wrapper */}
        <form
          onSubmit={handleSubmit}
          className="flex items-end gap-2 p-2 rounded-xl border border-[var(--color-border)] bg-[var(--color-bg-secondary)] focus-within:border-[var(--color-border-focus)] transition-colors"
        >
          <textarea
            ref={textareaRef}
            className="flex-1 resize-none bg-transparent border-0 outline-none text-sm text-[var(--color-text-primary)] placeholder:text-[var(--color-text-muted)] leading-relaxed max-h-40 py-1 px-1"
            placeholder="Ask a question... Type @ to reference a document"
            value={inputValue}
            onChange={handleInputChange}
            onKeyDown={handleKeyDown}
            disabled={disabled || isLoading}
            rows={1}
          />
          <div className="flex items-center gap-1 flex-shrink-0 pb-0.5">
            <button
              type="button"
              className="flex items-center justify-center w-8 h-8 rounded-lg text-[var(--color-text-muted)] hover:text-[var(--color-text-primary)] hover:bg-[var(--color-bg-hover)] transition-colors disabled:opacity-40 disabled:cursor-not-allowed cursor-pointer border-0 bg-transparent"
              onClick={onUploadClick}
              disabled={disabled}
              title="Upload Document (PDF, Excel, Word)"
            >
              <Paperclip size={20} />
            </button>
            <button
              type="submit"
              className="flex items-center justify-center w-8 h-8 rounded-lg bg-primary hover:bg-primary-hover text-white transition-colors disabled:opacity-40 disabled:cursor-not-allowed cursor-pointer border-0"
              disabled={!inputValue.trim() || isLoading || disabled}
              title="Send message"
            >
              <Send size={18} />
            </button>
          </div>
        </form>

        <p className="text-xs text-[var(--color-text-muted)] text-center mt-1.5 mb-0">
          Press Enter to send &bull; @ to mention a document &bull; Shift+Enter for new line
        </p>
        <p className="text-xs text-[var(--color-text-muted)] text-center mt-0.5 mb-0 opacity-60">
          Developed by L&T with Mag13
        </p>
      </div>
    </div>
  );
}

export default ChatArea;
