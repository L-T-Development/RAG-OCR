import { useState, useRef, useEffect } from 'react';
import './ChatArea.css';

function ChatArea({ threadId, threadName, messages, onSendMessage, onSummarize, isLoading, isSummarizing, disabled }) {
  const [input, setInput] = useState('');
  // const [selectedChunks, setSelectedChunks] = useState(null);
  const [expandedSources, setExpandedSources] = useState(new Set());
  const messagesEndRef = useRef(null);
  const [showFileDropdown, setShowFileDropdown] = useState(false);
  const [threadFiles, setThreadFiles] = useState([]);

  const scrollToBottom = () => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  };

  useEffect(() => {
    scrollToBottom();
  }, [messages]);

   /* ---------------- @ FILE HELPERS ---------------- */

  // Detect active "@token" at cursor end

  const fetchThreadFiles = async () => {
    if (!threadId) return;
    try {
      const res = await fetch(`/api/files/${threadId}/`);

      const data = await res.json();
      setThreadFiles(data.files || []);
    } catch (err) {
      console.error("Failed to fetch thread files", err);
    }
  };

  const handleSend = () => {
    if (!input.trim() || disabled) return;
    onSendMessage(input);
    setInput('');
    setShowFileDropdown(false);
  };

  const handleKeyPress = (e) => {
    if (e.key === 'Enter') handleSend();
  };

  const handleSummarize = () => {
    if (threadId && onSummarize) {
      onSummarize(threadId);
    }
  };

  const toggleChunkExpansion = (index) => {
    const newSet = new Set(expandedSources);
    if (newSet.has(index)) {
      newSet.delete(index);
    } else {
      newSet.add(index);
    }
    setExpandedSources(newSet);
  };

//   const fetchThreadFiles = async () => {
//   if (!threadId) return;
//   try {
//     const res = await fetch(`/thread/${threadId}/documents`);
//     const data = await res.json();
//     setThreadFiles(data.documents || []);
//   } catch (err) {
//     console.error("Failed to fetch thread files", err);
//   }
// };

//   // Detect active @token at the end of input
//   const getActiveAtToken = (text) => {
//     const match = text.match(/@([^\s]*)$/);
//     return match ? match[1] : null;
// };


  return (
    <main className="chat-area">
      <div className="chat-header">
        <span>{threadName || 'Select a Thread'}</span>
        {threadId && (
          <button 
            className="btn-summarize"
            onClick={handleSummarize}
            disabled={isSummarizing || disabled}
            title="Generate AI summary of all documents in this thread"
          >
            {isSummarizing ? (
              <>
                <i className="fa-solid fa-circle-notch fa-spin"></i>
                <span>Summarizing...</span>
              </>
            ) : (
              <>
                <i className="fa-solid fa-wand-magic-sparkles"></i>
                <span>Summarize Docs</span>
              </>
            )}
          </button>
        )}
      </div>

      <div className="messages-box">
        {!threadName ? (
          <div className="empty-state">
            <i className="fa-regular fa-comments"></i>
            <p>Select a thread to start chatting.</p>
          </div>
        ) : messages.length === 0 ? (
          <div className="message ai">
            <div className="bubble">
              Hello! I'm ready to answer questions about documents in this thread.
            </div>
          </div>
        ) : (
          messages.map((msg, idx) => (
            <div key={idx} className={`message ${msg.role}`}>
              <div className="bubble">
                <span dangerouslySetInnerHTML={{ __html: msg.content.replace(/\n/g, '<br>') }} />
                
                {/* Confidence Score Badge */}
                {msg.confidence !== undefined && msg.role === 'ai' && (
                  <div className="confidence-badge">
                    <span className={`confidence-label ${msg.confidence_label?.toLowerCase() || 'unknown'}`}>
                      {msg.confidence_label || 'N/A'}
                    </span>
                    <span className="confidence-value">{msg.confidence}%</span>
                  </div>
                )}
                
                {/* Source Citations with Chunks */}
                {msg.chunks && msg.chunks.length > 0 && (
                  <div className="source-section">
                    <strong>Sources:</strong>
                    <div className="chunks-list">
                      {msg.chunks.map((chunk, chunkIdx) => (
                        <div key={chunkIdx} className="chunk-item">
                          <div 
                            className="chunk-header"
                            onClick={() => toggleChunkExpansion(idx * 100 + chunkIdx)}
                          >
                            <i className={`fa-solid fa-chevron-${expandedSources.has(idx * 100 + chunkIdx) ? 'down' : 'right'}`}></i>
                            <span className="source-name">{chunk.source}</span>
                            <span className="source-page">p. {chunk.page}</span>
                          </div>
                          
                          {expandedSources.has(idx * 100 + chunkIdx) && (
                            <div className="chunk-content">
                              {chunk.text}
                            </div>
                          )}
                        </div>
                      ))}
                    </div>
                  </div>
                )}

                {/* Fallback for old source format */}
                {(!msg.chunks || msg.chunks.length === 0) && msg.sources && msg.sources.length > 0 && (
                  <div className="source-citation">
                    <strong>Sources:</strong>{' '}
                    {msg.sources.map((s, i) => (
                      <span key={i} className="source-item">{s}</span>
                    ))}
                  </div>
                )}
              </div>
            </div>
          ))
        )}
        
        {isLoading && (
          <div className="message ai">
            <div className="bubble loading">
              <i className="fa-solid fa-circle-notch fa-spin"></i> Thinking...
            </div>
          </div>
        )}
        <div ref={messagesEndRef} />
      </div>
      {showFileDropdown && (
  <div className="file-dropdown">
  {threadFiles.length === 0 ? (
    <div className="file-option">No files found</div>
  ) : (
    threadFiles.map((file, idx) => (
      <div
        key={idx}
        className="file-option"
        onClick={() => {
          setInput(prev =>
            prev.replace(/@.*/, `@${file.name} `)
          );
          setShowFileDropdown(false);
        }}
      >
        📄 {file.name}
      </div>
    ))
  )}
</div>

)}


      <div className="input-area">
        <input
          type="text"
          className="chat-input"
          placeholder="Ask about the documents..."
          value={input}

          onChange={(e) => {
            const value = e.target.value;
            setInput(value);
            console.log("INPUT:", value, "THREAD:", threadId);

            if (value.includes('@')) {
              fetchThreadFiles();
              setShowFileDropdown(true);
            }
            else {
              setShowFileDropdown(false);
  }
}}


          onKeyPress={handleKeyPress}
          disabled={disabled}
        />
        <button
          className="btn btn-primary"
          onClick={handleSend}
          disabled={disabled || !input.trim()}
          style={{ width: '45px', height: '40px' }}
        >
          <i className="fa-solid fa-paper-plane"></i>
        </button>
      </div>
    </main>
  );
}

export default ChatArea;
