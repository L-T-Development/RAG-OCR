import { useState, useRef, useEffect } from 'react';
import './ChatArea.css';

function ChatArea({ threadId, threadName, messages, onSendMessage, onSummarize, isLoading, isSummarizing, disabled }) {
  const [input, setInput] = useState('');
  const messagesEndRef = useRef(null);

  const scrollToBottom = () => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  };

  useEffect(() => {
    scrollToBottom();
  }, [messages]);

  const handleSend = () => {
    if (!input.trim() || disabled) return;
    onSendMessage(input);
    setInput('');
  };

  const handleKeyPress = (e) => {
    if (e.key === 'Enter') handleSend();
  };

  const handleSummarize = () => {
    if (threadId && onSummarize) {
      onSummarize(threadId);
    }
  };

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
                {msg.sources && msg.sources.length > 0 && (
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

      <div className="input-area">
        <input
          type="text"
          className="chat-input"
          placeholder="Ask about the documents..."
          value={input}
          onChange={e => setInput(e.target.value)}
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
