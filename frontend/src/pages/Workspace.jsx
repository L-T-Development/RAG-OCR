import { useState, useEffect, useCallback } from 'react';
import { useNavigate } from 'react-router-dom';
import { Sidebar, ChatArea, DocumentPanel, DropZone } from '../components/workspace';
import { CategorySelector } from '../components/workspace/CategorySelector';
import { Navigation } from '../components/shared/Navigation';
import { api } from '../services/api';
import { X, MessageSquare, FolderPlus } from 'lucide-react';

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
  
  // Category selector state
  const [showCategorySelector, setShowCategorySelector] = useState(false);
  const [pendingFile, setPendingFile] = useState(null);

  // Fetch threads on mount
  useEffect(() => {
    fetchThreads();
  }, []);

  // Helper function to recursively find a thread at any nesting level
  const findThreadById = useCallback((threadList, id) => {
    if (!threadList || !id) return null;
    for (const thread of threadList) {
      if (thread.id === id) return thread;
      if (thread.sub_threads && thread.sub_threads.length > 0) {
        const found = findThreadById(thread.sub_threads, id);
        if (found) return found;
      }
    }
    return null;
  }, []);

  // Auto-select last used thread on mount (works for any nesting level)
  useEffect(() => {
    const lastThreadId = localStorage.getItem('lastThreadId');
    const lastThreadName = localStorage.getItem('lastThreadName');
    
    if (lastThreadId && threads.length > 0 && !currentThreadId) {
      const thread = findThreadById(threads, lastThreadId);
      if (thread) {
        // Thread exists at any level - restore it
        console.log('[Workspace] Restoring thread:', thread.name, 'ID:', thread.id);
        handleSelectThread(thread.id, thread.name || lastThreadName);
      } else {
        console.log('[Workspace] Saved thread not found, clearing localStorage');
        localStorage.removeItem('lastThreadId');
        localStorage.removeItem('lastThreadName');
      }
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [threads.length]); // Only trigger when threads are first loaded

  const fetchThreads = async () => {
    try {
      const data = await api.listThreads();
      setThreads(data.threads || []);
    } catch (e) {
      console.error('Error fetching threads:', e);
    }
  };

  const handleSelectThread = async (threadId, threadName, parentId = null) => {
    console.log('[Workspace] Selecting thread:', { threadId, threadName, parentId });
    
    setCurrentThreadId(threadId);
    setCurrentThreadName(threadName);
    
    // Save to localStorage for persistence across refreshes
    localStorage.setItem('lastThreadId', threadId);
    localStorage.setItem('lastThreadName', threadName);
    
    // Load documents
    try {
      const data = await api.getThreadFiles(threadId);
      console.log('[Workspace] Loaded documents:', data.files?.length || 0);
      setDocuments(data.files || []);
    } catch (e) {
      console.error('Error fetching files:', e);
      setDocuments([]);
    }

    // Load chat history
    try {
      const data = await api.getChatHistory(threadId);
      console.log('[Workspace] Loaded chat history:', data.messages?.length || 0, 'messages');
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
      console.error('Error fetching chat history:', e);
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
        
        // Clear localStorage if this was the active thread
        localStorage.removeItem('lastThreadId');
        localStorage.removeItem('lastThreadName');
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

  const handleUpload = async (file, category = 'other') => {
    if (!currentThreadId) {
      // No thread selected - use quick upload to create one
      await handleQuickUpload(file, category);
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
      const { ok, data } = await api.uploadFile(currentThreadId, file, category);
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

  const handleQuickUpload = async (file, category = 'other') => {
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
      const { ok, data } = await api.quickUpload(file, category);
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
    // Show category selector before upload
    setPendingFile(file);
    setShowCategorySelector(true);
  }, []);

  const handleCategorySelect = async (category) => {
    setShowCategorySelector(false);
    
    if (pendingFile) {
      if (currentThreadId) {
        await handleUpload(pendingFile, category);
      } else {
        await handleQuickUpload(pendingFile, category);
      }
      setPendingFile(null);
    }
  };

  const handleCategoryCancel = () => {
    setShowCategorySelector(false);
    setPendingFile(null);
  };

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
    <div className="flex flex-col h-screen bg-[var(--color-bg-secondary)]">
      <Navigation />
      <div className="flex flex-1 overflow-hidden pt-14">
        <Sidebar
          threads={threads}
          currentThreadId={currentThreadId}
          onSelectThread={handleSelectThread}
          onCreateThread={handleCreateThread}
          onCreateSubThread={handleCreateSubThread}
          onDeleteThread={handleDeleteThread}
          onOpenSettings={() => navigate('/settings')}
        />

        <main className="flex flex-1 overflow-hidden">
          <ChatArea
            threadId={currentThreadId}
            threadName={currentThreadName}
            messages={messages}
            documents={documents}
            onSendMessage={handleSendMessage}
            onUploadClick={() => document.querySelector('[data-upload-btn]')?.click()}
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
      </div>

      <DropZone onDrop={handleDrop} disabled={isUploading} />

      {showCategorySelector && pendingFile && (
        <CategorySelector
          fileName={pendingFile.name}
          onSelect={handleCategorySelect}
          onCancel={handleCategoryCancel}
        />
      )}

      {/* Create Thread Dialog */}
      {showCreateDialog && (
        <>
          <div
            className="fixed inset-0 bg-black/50 z-40"
            onClick={() => setShowCreateDialog(false)}
          />
          <div className="fixed top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2 z-50 w-full max-w-md bg-[var(--color-bg-primary)] rounded-xl shadow-xl p-6 flex flex-col gap-4">
            <button
              className="absolute top-4 right-4 p-1 rounded-lg text-[var(--color-text-muted)] hover:bg-[var(--color-bg-hover)] hover:text-[var(--color-text-primary)] transition-colors"
              onClick={() => setShowCreateDialog(false)}
            >
              <X size={18} />
            </button>

            <div className="flex items-center justify-center w-12 h-12 rounded-xl bg-primary-light text-primary">
              {createDialogParentId ? <FolderPlus size={24} /> : <MessageSquare size={24} />}
            </div>

            <h2 className="text-lg font-semibold text-[var(--color-text-primary)]">
              {createDialogParentId ? 'Create Sub-Thread' : 'Create New Thread'}
            </h2>

            <p className="text-sm text-[var(--color-text-secondary)]">
              {createDialogParentId
                ? 'Sub-threads inherit documents from the parent thread.'
                : 'Start a new conversation thread to organize your documents.'}
            </p>

            <div className="flex flex-col gap-1.5">
              <label className="text-sm font-medium text-[var(--color-text-primary)]">Thread Name</label>
              <input
                className="w-full px-3 py-2 rounded-lg border border-[var(--color-border)] bg-[var(--color-bg-secondary)] text-[var(--color-text-primary)] text-sm focus:outline-none focus:ring-2 focus:ring-primary"
                type="text"
                placeholder="Enter a name for your thread..."
                value={newThreadName}
                onChange={(e) => setNewThreadName(e.target.value)}
                onKeyDown={(e) => e.key === 'Enter' && newThreadName.trim() && submitCreateThread()}
                autoFocus
              />
            </div>

            <div className="flex gap-2 justify-end pt-1">
              <button
                className="px-4 py-2 rounded-lg text-sm font-medium text-[var(--color-text-secondary)] bg-[var(--color-bg-tertiary)] hover:bg-[var(--color-bg-hover)] transition-colors"
                onClick={() => setShowCreateDialog(false)}
              >
                Cancel
              </button>
              <button
                className="px-4 py-2 rounded-lg text-sm font-medium text-white bg-primary hover:bg-primary-hover disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
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
