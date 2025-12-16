import { useState, useEffect } from 'react';
import Navbar from '../components/Navbar';
import Sidebar from '../components/Sidebar';
import ChatArea from '../components/ChatArea';
import FilesPanel from '../components/FilesPanel';
import { api } from '../services/api';
import './Home.css';

function Home() {
  const [threads, setThreads] = useState([]);
  const [currentThreadId, setCurrentThreadId] = useState(null);
  const [currentThreadName, setCurrentThreadName] = useState('');
  const [messages, setMessages] = useState([]);
  const [files, setFiles] = useState([]);
  const [isLoading, setIsLoading] = useState(false);
  const [isSummarizing, setIsSummarizing] = useState(false);
  const [isUploading, setIsUploading] = useState(false);

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

  const handleSelectThread = async (threadId, threadName) => {
    setCurrentThreadId(threadId);
    setCurrentThreadName(threadName);
    
    // Load files
    try {
      const data = await api.getThreadFiles(threadId);
      setFiles(data.files || []);
    } catch (e) {
      console.error('Error fetching files:', e);
    }

    // Load chat history
    try {
      const data = await api.getChatHistory(threadId);
      setMessages(data.messages || []);
    } catch (e) {
      setMessages([]);
    }
  };

  const handleCreateThread = async (name, parentId) => {
    try {
      await api.createThread(name, parentId);
      fetchThreads();
    } catch (e) {
      alert('Failed to create thread');
    }
  };

  const handleDeleteThread = async (threadId) => {
    if (!window.confirm('Delete this thread? All documents inside will be removed.')) return;
    
    try {
      const { ok, data } = await api.deleteThread(threadId);
      if (ok) {
        if (currentThreadId === threadId) {
          setCurrentThreadId(null);
          setCurrentThreadName('');
          setFiles([]);
          setMessages([]);
        }
        fetchThreads();
      } else {
        alert('Failed: ' + (data.error || 'Unknown error'));
      }
    } catch (e) {
      alert('Server error deleting thread');
    }
  };

  const handleSendMessage = async (query) => {
    if (!currentThreadId) return;
    
    // Add user message
    setMessages(prev => [...prev, { role: 'user', content: query }]);
    setIsLoading(true);

    try {
      const data = await api.sendMessage(currentThreadId, query);
      setMessages(prev => [...prev, {
        role: 'ai',
        content: data.answer || data.response || 'No response',
        sources: data.sources || [],
        chunks: data.chunks || [],
        confidence: data.confidence,
        confidence_label: data.confidence_label
      }]);
    } catch (e) {
      setMessages(prev => [...prev, {
        role: 'ai',
        content: 'Error connecting to AI service.'
      }]);
    } finally {
      setIsLoading(false);
    }
  };

  const handleSummarize = async (threadId) => {
    if (!threadId) return;
    
    setIsSummarizing(true);
    try {
      const { ok, data } = await api.summarizeThread(threadId);
      if (ok && data.summary) {
        // Add summary as an AI message in the chat
        setMessages(prev => [...prev, {
          role: 'ai',
          content: `📄 **Document Summary**\n\n${data.summary}\n\n_Summarized ${data.documents_count || 0} document(s) with ${data.total_chunks || 0} chunks._`,
          sources: data.documents || []
        }]);
      } else {
        setMessages(prev => [...prev, {
          role: 'ai',
          content: data.error || 'No documents found to summarize.'
        }]);
      }
    } catch (e) {
      setMessages(prev => [...prev, {
        role: 'ai',
        content: 'Error generating summary. Please try again.'
      }]);
    } finally {
      setIsSummarizing(false);
    }
  };

  const handleUpload = async (file) => {
    if (!currentThreadId) return;
    
    setIsUploading(true);
    try {
      const { ok, data } = await api.uploadFile(currentThreadId, file);
      if (ok) {
        alert(`Upload Successful!\nFile processed into ${data.chunk_count || '?'} chunks.`);
        const filesData = await api.getThreadFiles(currentThreadId);
        setFiles(filesData.files || []);
      } else {
        alert('Upload failed: ' + (data.error || 'Unknown error'));
      }
    } catch (e) {
      alert('Upload failed: Network error');
    } finally {
      setIsUploading(false);
    }
  };

  const handleDeleteFile = async (docId) => {
    if (!window.confirm('Delete this document?')) return;
    
    try {
      const { ok, data } = await api.deleteDocument(docId);
      if (ok) {
        const filesData = await api.getThreadFiles(currentThreadId);
        setFiles(filesData.files || []);
      } else {
        alert('Failed: ' + (data.error || 'Unknown error'));
      }
    } catch (e) {
      alert('Server error deleting document');
    }
  };

  return (
    <div className="home-container">
      <Navbar />
      <div className="app-container">
        <Sidebar
          threads={threads}
          currentThreadId={currentThreadId}
          onSelectThread={handleSelectThread}
          onCreateThread={handleCreateThread}
          onDeleteThread={handleDeleteThread}
        />
        <ChatArea
          threadId={currentThreadId}
          threadName={currentThreadName}
          messages={messages}
          onSendMessage={handleSendMessage}
          onSummarize={handleSummarize}
          isLoading={isLoading}
          isSummarizing={isSummarizing}
          disabled={!currentThreadId}
        />
        <FilesPanel
          files={files}
          onUpload={handleUpload}
          onDeleteFile={handleDeleteFile}
          disabled={!currentThreadId}
          isUploading={isUploading}
        />
      </div>
    </div>
  );
}

export default Home;
