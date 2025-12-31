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
  X
} from 'lucide-react';
import './ChatArea.css';

// Confidence Ring Component
function ConfidenceRing({ confidence, label }) {
  // Calculate confidence score (0-100)
  // Backend may return as decimal (0-1) or percentage (0-100)
  let score = 0;
  if (typeof confidence === 'number') {
    // If confidence > 1, it's already a percentage
    score = confidence > 1 ? Math.round(confidence) : Math.round(confidence * 100);
  }
  // Clamp to 0-100 range
  score = Math.max(0, Math.min(100, score));
  
  // SVG circle parameters
  const radius = 18;
  const circumference = 2 * Math.PI * radius;
  const strokeDashoffset = circumference - (score / 100) * circumference;
  
  // Color based on confidence level
  const getColor = (score) => {
    if (score >= 70) return 'var(--color-success)';
    if (score >= 40) return 'var(--color-warning)';
    return 'var(--color-error)';
  };

  return (
    <div className="confidence-ring" title={`Confidence: ${score}% ${label ? `(${label})` : ''}`}>
      <svg width="44" height="44" viewBox="0 0 44 44">
        {/* Background circle */}
        <circle
          cx="22"
          cy="22"
          r={radius}
          fill="none"
          stroke="var(--color-bg-tertiary)"
          strokeWidth="3"
        />
        {/* Progress circle */}
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
            transition: 'stroke-dashoffset 0.5s ease-out'
          }}
        />
      </svg>
      <span className="confidence-ring__value">{score}%</span>
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
    <div className={`sources-panel ${isExpanded ? 'sources-panel--expanded' : ''}`}>
      <button 
        className="sources-panel__toggle"
        onClick={() => setIsExpanded(!isExpanded)}
      >
        <BookOpen size={14} />
        <span>Sources ({sources?.length || 0})</span>
        {isExpanded ? <ChevronUp size={14} /> : <ChevronDown size={14} />}
      </button>
      
      {isExpanded && (
        <div className="sources-panel__content">
          {sources && sources.length > 0 && (
            <div className="sources-panel__section">
              <div className="sources-panel__section-title">Referenced Documents</div>
              <div className="sources-panel__tags">
                {sources.map((source, idx) => (
                  <span key={idx} className="sources-panel__tag">
                    <FileText size={12} />
                    {typeof source === 'string' ? source : source.filename || source.name || `Source ${idx + 1}`}
                  </span>
                ))}
              </div>
            </div>
          )}
          
          {chunks && chunks.length > 0 && (
            <div className="sources-panel__section">
              <div className="sources-panel__section-title">Relevant Passages</div>
              <div className="sources-panel__chunks">
                {chunks.slice(0, 3).map((chunk, idx) => (
                  <div key={idx} className="sources-panel__chunk">
                    <div className="sources-panel__chunk-header">
                      <span className="sources-panel__chunk-label">Passage {idx + 1}</span>
                      {chunk.score && (
                        <span className="sources-panel__chunk-score">
                          {Math.round(chunk.score * 100)}% match
                        </span>
                      )}
                    </div>
                    <p className="sources-panel__chunk-text">
                      {typeof chunk === 'string' 
                        ? chunk.slice(0, 200) 
                        : (chunk.text || chunk.content || '').slice(0, 200)}
                      {(typeof chunk === 'string' ? chunk.length : (chunk.text || chunk.content || '').length) > 200 && '...'}
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
  // Calculate UI-level confidence if not provided by backend
  const getConfidence = () => {
    if (message.confidence !== undefined && message.confidence !== null) {
      return message.confidence;
    }
    // Heuristic calculation
    const contentLength = (message.content || '').length;
    const sourceCount = (message.sources || []).length;
    const chunkCount = (message.chunks || []).length;
    
    let score = 0.3; // Base confidence
    if (contentLength > 100) score += 0.2;
    if (contentLength > 300) score += 0.1;
    if (sourceCount > 0) score += 0.2;
    if (chunkCount > 0) score += 0.2;
    
    return Math.min(score, 1);
  };

  return (
    <div className={`message message--${isUser ? 'user' : 'assistant'}`}>
      <div className="message__avatar">
        {isUser ? <User size={18} /> : <Bot size={18} />}
      </div>
      <div className="message__content">
        <div className="message__bubble">
          {isUser ? (
            <p>{message.content}</p>
          ) : (
            <div className="message__markdown">
              <ReactMarkdown remarkPlugins={[remarkGfm]}>
                {message.content}
              </ReactMarkdown>
            </div>
          )}
        </div>
        
        {/* Sources Panel - Only for assistant messages */}
        {!isUser && (
          <SourcesPanel 
            sources={message.sources} 
            chunks={message.chunks}
          />
        )}
        
        <div className="message__meta">
          <span>{message.timestamp || 'Just now'}</span>
        </div>
      </div>
      
      {/* Confidence Ring - Only for assistant messages */}
      {!isUser && (
        <div className="message__confidence">
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
    <div className="message message--assistant">
      <div className="message__avatar">
        <Bot size={18} />
      </div>
      <div className="message__content">
        <div className="message__bubble message__loading">
          <div className="message__loading-dot"></div>
          <div className="message__loading-dot"></div>
          <div className="message__loading-dot"></div>
        </div>
      </div>
    </div>
  );
}

function EmptyChat({ onSuggestionClick }) {
  const suggestions = [
    "Summarize this document",
    "What are the key points?",
    "Find specific information",
    "Compare sections"
  ];

  return (
    <div className="chat-area__empty">
      <div className="chat-area__empty-icon">
        <Sparkles size={36} />
      </div>
      <h2 className="chat-area__empty-title">Start a conversation</h2>
      <p className="chat-area__empty-text">
        Upload a PDF document and ask questions about its content. 
        The AI will analyze and provide answers based on the document.
      </p>
      <div className="chat-area__empty-suggestions">
        {suggestions.map((suggestion, idx) => (
          <button
            key={idx}
            className="chat-area__suggestion"
            onClick={() => onSuggestionClick(suggestion)}
          >
            {suggestion}
          </button>
        ))}
      </div>
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
  disabled = false
}) {
  const [inputValue, setInputValue] = useState('');
  const [selectedFiles, setSelectedFiles] = useState([]);
  const [showFilePicker, setShowFilePicker] = useState(false);
  const [fileFilterText, setFileFilterText] = useState('');
  const messagesEndRef = useRef(null);
  const textareaRef = useRef(null);

  // Auto-scroll to bottom on new messages
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages, isLoading]);

  // Auto-resize textarea
  useEffect(() => {
    if (textareaRef.current) {
      textareaRef.current.style.height = 'auto';
      textareaRef.current.style.height = `${textareaRef.current.scrollHeight}px`;
    }
  }, [inputValue]);

  // Handle @ key to open file picker
  const handleInputChange = (e) => {
    const value = e.target.value;
    setInputValue(value);
    
    // Check for @ trigger
    const lastAtPos = value.lastIndexOf('@');
    if (lastAtPos !== -1 && (lastAtPos === 0 || value[lastAtPos - 1] === ' ')) {
      const filterText = value.slice(lastAtPos + 1);
      if (!filterText.includes(' ')) {
        setFileFilterText(filterText);
        setShowFilePicker(true);
        return;
      }
    }
    setShowFilePicker(false);
  };

  // Filter documents based on @ search
  const filteredDocs = documents.filter(doc => 
    doc.name.toLowerCase().includes(fileFilterText.toLowerCase())
  );

  // Select file from @ picker
  const handleSelectFile = (doc) => {
    // Add to selected files if not already selected
    if (!selectedFiles.find(f => f.id === doc.id)) {
      setSelectedFiles(prev => [...prev, doc]);
    }
    
    // Remove @ and filter text from input
    const lastAtPos = inputValue.lastIndexOf('@');
    const newValue = inputValue.slice(0, lastAtPos).trimEnd();
    setInputValue(newValue);
    setShowFilePicker(false);
    setFileFilterText('');
    textareaRef.current?.focus();
  };

  // Remove selected file
  const handleRemoveFile = (docId) => {
    setSelectedFiles(prev => prev.filter(f => f.id !== docId));
  };

  const handleSubmit = (e) => {
    e?.preventDefault();
    if (!inputValue.trim() || isLoading || disabled) return;
    
    // Build query with @filename tags for selected files
    // Backend expects @filename.pdf in the query text itself
    let query = inputValue.trim();
    if (selectedFiles.length > 0) {
      const fileTags = selectedFiles.map(f => `@${f.name}`).join(' ');
      query = `${fileTags} ${query}`;
    }
    
    onSendMessage(query);
    setInputValue('');
    setSelectedFiles([]);
    
    // Reset textarea height
    if (textareaRef.current) {
      textareaRef.current.style.height = 'auto';
    }
  };

  const handleKeyDown = (e) => {
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
      <div className="chat-area">
        <div className="chat-area__no-thread">
          <div className="chat-area__no-thread-icon">
            <MessageSquare size={28} />
          </div>
          <h2 className="chat-area__no-thread-title">No thread selected</h2>
          <p className="chat-area__no-thread-text">
            Select or create a thread to start chatting
          </p>
        </div>
      </div>
    );
  }

  return (
    <div className="chat-area">
      <header className="chat-area__header">
        <div className="chat-area__header-left">
          <div>
            <h1 className="chat-area__title">{threadName || 'Chat'}</h1>
            <div className="chat-area__subtitle">
              <FileText size={12} />
              {messages.length} messages
            </div>
          </div>
        </div>
        <div className="chat-area__header-actions">
          {documents.length > 0 && onSummarizeThread && (
            <button
              className="chat-area__action-btn"
              onClick={onSummarizeThread}
              disabled={isSummarizing}
              title="Summarize all documents"
            >
              {isSummarizing ? <Loader2 size={16} className="animate-spin" /> : <FileSearch size={16} />}
              <span>Summarize</span>
            </button>
          )}
          <Link to="/compare" className="chat-area__nav-btn">
            <GitCompare size={18} />
            <span>Compare</span>
          </Link>
        </div>
      </header>

      <div className="chat-area__messages">
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
            <div ref={messagesEndRef} />
          </>
        )}
      </div>

      <div className="chat-area__input-container">
        {/* Selected Files Indicator */}
        {selectedFiles.length > 0 && (
          <div className="chat-area__selected-files">
            {selectedFiles.map(file => (
              <span key={file.id} className="chat-area__selected-file">
                <FileText size={12} />
                {file.name}
                <button 
                  className="chat-area__selected-file-remove"
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
          <div className="chat-area__file-picker">
            <div className="chat-area__file-picker-header">
              <FileText size={14} />
              <span>Select document {fileFilterText && `(filtering: "${fileFilterText}")`}</span>
            </div>
            <div className="chat-area__file-picker-list">
              {filteredDocs.length > 0 ? (
                filteredDocs.map(doc => (
                  <button
                    key={doc.id}
                    className="chat-area__file-picker-item"
                    onClick={() => handleSelectFile(doc)}
                  >
                    <FileText size={14} />
                    <span>{doc.name}</span>
                  </button>
                ))
              ) : (
                <div className="chat-area__file-picker-empty">
                  No documents match "{fileFilterText}"
                </div>
              )}
            </div>
          </div>
        )}
        {showFilePicker && documents.length === 0 && (
          <div className="chat-area__file-picker">
            <div className="chat-area__file-picker-empty">
              No documents uploaded yet. Upload a PDF first.
            </div>
          </div>
        )}

        <form onSubmit={handleSubmit} className="chat-area__input-wrapper">
          <textarea
            ref={textareaRef}
            className="chat-area__input"
            placeholder="Ask a question... Type @ to reference a document"
            value={inputValue}
            onChange={handleInputChange}
            onKeyDown={handleKeyDown}
            disabled={disabled || isLoading}
            rows={1}
          />
          <div className="chat-area__input-actions">
            <button
              type="button"
              className="chat-area__upload-btn"
              onClick={onUploadClick}
              disabled={disabled}
              title="Upload PDF"
            >
              <Paperclip size={20} />
            </button>
            <button
              type="submit"
              className="chat-area__send-btn"
              disabled={!inputValue.trim() || isLoading || disabled}
              title="Send message"
            >
              <Send size={18} />
            </button>
          </div>
        </form>
        <p className="chat-area__input-hint">
          Press Enter to send • @ to mention a document • Shift+Enter for new line
        </p>
      </div>
    </div>
  );
}

export default ChatArea;
