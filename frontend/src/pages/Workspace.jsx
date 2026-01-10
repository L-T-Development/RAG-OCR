import { useState, useEffect, useCallback } from 'react';
import { useNavigate } from 'react-router-dom';
import { Sidebar, ChatArea, DocumentPanel, DropZone } from '../components/workspace';
import { Navigation } from '../components/shared/Navigation';
import { api } from '../services/api';
import { X, MessageSquare, FolderPlus } from 'lucide-react';
import './Workspace.css';

export function Workspace() {
  const navigate = useNavigate();
  
  // Thread state
  const [threads, setThreads] = useState([]);
  const [currentThreadId, setCurrentThreadId] = useState(null);
  const [currentThreadName, setCurrentThreadName] = useState('');
  
  // Chat state
  const [messages, setMessages] = useState([]);
  const [isLoading, setIsLoading] = useState(false);
  
  // Document state
  const [documents, setDocuments] = useState([]);
  const [isUploading, setIsUploading] = useState(false);
  const [uploadProgress, setUploadProgress] = useState(0);
  const [uploadStatus, setUploadStatus] = useState('');
  const [isSummarizing, setIsSummarizing] = useState(false);
  
  // UI state
  const [showCreateDialog, setShowCreateDialog] = useState(false);
  const [createDialogParentId, setCreateDialogParentId] = useState(null);
  const [newThreadName, setNewThreadName] = useState('');

  // Fetch threads on mount
  useEffect(() => {
    fetchThreads();
  }, []);

  const fetchThreads = async () => {
    try {
      const data = await api.listThreads();
      setThreads(data.threads || []);
    } catch (e) {
      console.error('Error fetching threads:', e);
    }
  };

  const handleSelectThread = async (threadId, threadName, parentId = null) => {
    setCurrentThreadId(threadId);
    setCurrentThreadName(threadName);
    
    // Load documents
    try {
      const data = await api.getThreadFiles(threadId);
      setDocuments(data.files || []);
    } catch (e) {
      console.error('Error fetching files:', e);
      setDocuments([]);
    }

    // Load chat history
    try {
      const data = await api.getChatHistory(threadId);
      const formattedMessages = (data.messages || []).map((msg, idx) => ({
        id: msg.id || `msg-${idx}`,
        role: msg.role === 'ai' ? 'assistant' : msg.role,
        content: msg.content,
        sources: msg.sources || [],
        chunks: msg.chunks || [],
        confidence: msg.confidence,
        confidence_label: msg.confidence_label || '',
        timestamp: msg.timestamp
      }));
      setMessages(formattedMessages);
    } catch (e) {
      setMessages([]);
    }
  };

  const handleCreateThread = () => {
    setCreateDialogParentId(null);
    setNewThreadName('');
    setShowCreateDialog(true);
  };

  const handleCreateSubThread = (parentId) => {
    setCreateDialogParentId(parentId);
    setNewThreadName('');
    setShowCreateDialog(true);
  };

  const submitCreateThread = async () => {
    if (!newThreadName.trim()) return;
    
    try {
      const data = await api.createThread(newThreadName.trim(), createDialogParentId);
      await fetchThreads();
      handleSelectThread(data.id, data.name, createDialogParentId);
      setShowCreateDialog(false);
      setNewThreadName('');
    } catch (e) {
      console.error('Error creating thread:', e);
    }
  };

  const handleDeleteThread = async (threadId) => {
    if (!window.confirm('Delete this thread and all its contents?')) return;
    
    try {
      await api.deleteThread(threadId);
      await fetchThreads();
      
      if (currentThreadId === threadId) {
        setCurrentThreadId(null);
        setCurrentThreadName('');
        setMessages([]);
        setDocuments([]);
      }
    } catch (e) {
      console.error('Error deleting thread:', e);
    }
  };

  const handleSendMessage = async (content) => {
    if (!currentThreadId || !content.trim()) return;
    
    // Add user message immediately
    const userMessage = {
      id: Date.now(),
      role: 'user',
      content: content.trim(),
      timestamp: new Date().toLocaleTimeString()
    };
    setMessages(prev => [...prev, userMessage]);
    setIsLoading(true);

    try {
      const response = await api.sendMessage(currentThreadId, content.trim());
      
      const assistantMessage = {
        id: Date.now() + 1,
        role: 'assistant',
        content: response.answer || response.error || 'No response',
        sources: response.sources || [],
        chunks: response.chunks || [],
        confidence: response.confidence,
        confidence_label: response.confidence_label || '',
        timestamp: new Date().toLocaleTimeString()
      };
      setMessages(prev => [...prev, assistantMessage]);

      // Auto-rename thread if it's the first message and thread has generic name
      if (messages.length === 0 && currentThreadName.startsWith('New Thread')) {
        const shortName = content.trim().slice(0, 50) + (content.length > 50 ? '...' : '');
        // Could call API to rename thread here
      }
    } catch (e) {
      console.error('Error sending message:', e);
      const errorMessage = {
        id: Date.now() + 1,
        role: 'assistant',
        content: 'Sorry, there was an error processing your request.',
        timestamp: new Date().toLocaleTimeString()
      };
      setMessages(prev => [...prev, errorMessage]);
    } finally {
      setIsLoading(false);
    }
  };

  const handleUpload = async (file) => {
    if (!currentThreadId) {
      // No thread selected - use quick upload to create one
      await handleQuickUpload(file);
      return;
    }

    setIsUploading(true);
    setUploadProgress(10);
    setUploadStatus('Uploading...');

    // Progress animation to 20% during upload
    const progressInterval = setInterval(() => {
      setUploadProgress(prev => {
        if (prev >= 20) return prev;
        return prev + 2;
      });
    }, 100);

    try {
      const { ok, data } = await api.uploadFile(currentThreadId, file);
      clearInterval(progressInterval);
      
      if (ok) {
        setUploadProgress(50);
        setUploadStatus('Processing document...');
        await new Promise(resolve => setTimeout(resolve, 400));
        
        setUploadProgress(80);
        setUploadStatus('Embedding text...');
        await new Promise(resolve => setTimeout(resolve, 400));
        
        setUploadProgress(100);
        setUploadStatus('Upload complete!');
        
        const filesData = await api.getThreadFiles(currentThreadId);
        setDocuments(filesData.files || []);
        
        // Clear status after delay
        setTimeout(() => {
          setUploadStatus('');
          setUploadProgress(0);
        }, 2000);
      } else {
        clearInterval(progressInterval);
        alert('Upload failed: ' + (data.error || 'Unknown error'));
        setUploadStatus('');
        setUploadProgress(0);
      }
    } catch (e) {
      clearInterval(progressInterval);
      alert('Upload failed: Network error');
      setUploadStatus('');
      setUploadProgress(0);
    } finally {
      setIsUploading(false);
    }
  };

  const handleQuickUpload = async (file) => {
    setIsUploading(true);
    setUploadProgress(10);
    setUploadStatus('Uploading...');

    // Progress animation to 20% during upload
    const progressInterval = setInterval(() => {
      setUploadProgress(prev => {
        if (prev >= 20) return prev;
        return prev + 2;
      });
    }, 100);

    try {
      const { ok, data } = await api.quickUpload(file);
      clearInterval(progressInterval);
      
      if (ok && data.thread) {
        setUploadProgress(50);
        setUploadStatus('Processing document...');
        await new Promise(resolve => setTimeout(resolve, 400));
        
        setUploadProgress(80);
        setUploadStatus('Embedding text...');
        await new Promise(resolve => setTimeout(resolve, 400));
        
        setUploadProgress(100);
        setUploadStatus('Upload complete!');
        
        await fetchThreads();
        handleSelectThread(data.thread.id, data.thread.name);
        
        setTimeout(() => {
          setUploadStatus('');
          setUploadProgress(0);
        }, 2000);
      } else {
        clearInterval(progressInterval);
        alert('Upload failed: ' + (data.error || 'Unknown error'));
        setUploadStatus('');
        setUploadProgress(0);
      }
    } catch (e) {
      clearInterval(progressInterval);
      alert('Upload failed: Network error');
      setUploadStatus('');
      setUploadProgress(0);
    } finally {
      setIsUploading(false);
    }
  };

  const handleDeleteDocument = async (docId) => {
    if (!window.confirm('Delete this document?')) return;
    
    try {
      const { ok } = await api.deleteDocument(docId);
      if (ok) {
        const filesData = await api.getThreadFiles(currentThreadId);
        setDocuments(filesData.files || []);
      }
    } catch (e) {
      console.error('Error deleting document:', e);
    }
  };

  const handleDrop = useCallback((file) => {
    if (currentThreadId) {
      handleUpload(file);
    } else {
      handleQuickUpload(file);
    }
  }, [currentThreadId]);

  // Document Summary Handlers
  const handleSummarizeThread = async () => {
    if (!currentThreadId) return;
    
    setIsSummarizing(true);
    try {
      const { ok, data } = await api.summarizeThread(currentThreadId);
      if (ok && data.summary) {
        const summaryMessage = {
          id: Date.now(),
          role: 'assistant',
          content: `**📄 Thread Summary**\n\n${data.summary}`,
          sources: data.documents || [],
          timestamp: new Date().toLocaleTimeString()
        };
        setMessages(prev => [...prev, summaryMessage]);
      } else {
        alert('Summary failed: ' + (data.error || 'Unknown error'));
      }
    } catch (e) {
      console.error('Summary error:', e);
      alert('Failed to generate summary');
    } finally {
      setIsSummarizing(false);
    }
  };

  const handleSummarizeDocument = async (docId) => {
    setIsSummarizing(true);
    try {
      const { ok, data } = await api.summarizeDocument(docId);
      if (ok && data.summary) {
        const doc = documents.find(d => d.id === docId);
        const summaryMessage = {
          id: Date.now(),
          role: 'assistant',
          content: `**📄 Document Summary: ${doc?.name || 'Document'}**\n\n${data.summary}`,
          sources: [doc?.name || 'Document'],
          timestamp: new Date().toLocaleTimeString()
        };
        setMessages(prev => [...prev, summaryMessage]);
      } else {
        alert('Summary failed: ' + (data.error || 'Unknown error'));
      }
    } catch (e) {
      console.error('Summary error:', e);
      alert('Failed to generate summary');
    } finally {
      setIsSummarizing(false);
    }
  };

  return (
    <div className="workspace">
      <Sidebar
        threads={threads}
        currentThreadId={currentThreadId}
        onSelectThread={handleSelectThread}
        onCreateThread={handleCreateThread}
        onCreateSubThread={handleCreateSubThread}
        onDeleteThread={handleDeleteThread}
        onOpenSettings={() => navigate('/settings')}
      />
      
      <main className="workspace__main">
        <ChatArea
          threadId={currentThreadId}
          threadName={currentThreadName}
          messages={messages}
          documents={documents}
          onSendMessage={handleSendMessage}
          onUploadClick={() => document.querySelector('.document-panel__upload-btn')?.click()}
          onSummarizeThread={handleSummarizeThread}
          onSummarizeDocument={handleSummarizeDocument}
          isLoading={isLoading}
          isSummarizing={isSummarizing}
          disabled={!currentThreadId}
        />
        
        <DocumentPanel
          documents={documents}
          onUpload={handleUpload}
          onDelete={handleDeleteDocument}
          onSummarize={handleSummarizeDocument}
          disabled={!currentThreadId}
          isUploading={isUploading}
          uploadProgress={uploadProgress}
          uploadStatus={uploadStatus}
        />
      </main>

      <DropZone onDrop={handleDrop} disabled={isUploading} />

      {/* Create Thread Dialog - Improved */}
      {showCreateDialog && (
        <>
          <div 
            className="dialog-backdrop"
            onClick={() => setShowCreateDialog(false)}
          />
          <div className="dialog">
            <button 
              className="dialog__close"
              onClick={() => setShowCreateDialog(false)}
            >
              <X size={18} />
            </button>
            
            <div className="dialog__icon">
              {createDialogParentId ? <FolderPlus size={24} /> : <MessageSquare size={24} />}
            </div>
            
            <h2 className="dialog__title">
              {createDialogParentId ? 'Create Sub-Thread' : 'Create New Thread'}
            </h2>
            
            <p className="dialog__description">
              {createDialogParentId 
                ? 'Sub-threads inherit documents from the parent thread.'
                : 'Start a new conversation thread to organize your documents.'
              }
            </p>
            
            <div className="dialog__field">
              <label className="dialog__label">Thread Name</label>
              <input
                className="dialog__input"
                type="text"
                placeholder="Enter a name for your thread..."
                value={newThreadName}
                onChange={(e) => setNewThreadName(e.target.value)}
                onKeyDown={(e) => e.key === 'Enter' && newThreadName.trim() && submitCreateThread()}
                autoFocus
              />
            </div>
            
            <div className="dialog__actions">
              <button
                className="dialog__btn dialog__btn--secondary"
                onClick={() => setShowCreateDialog(false)}
              >
                Cancel
              </button>
              <button
                className="dialog__btn dialog__btn--primary"
                onClick={submitCreateThread}
                disabled={!newThreadName.trim()}
              >
                {createDialogParentId ? 'Create Sub-Thread' : 'Create Thread'}
              </button>
            </div>
          </div>
        </>
      )}
    </div>
  );
}

export default Workspace;
