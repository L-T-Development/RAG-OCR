import { useState } from 'react';
import {
  Plus,
  MessageSquare,
  ChevronRight,
  Trash2,
  MoreHorizontal,
  FolderOpen,
  Settings,
  FileText,
  Sparkles
} from 'lucide-react';
import './Sidebar.css';

function ThreadItem({ 
  thread, 
  isActive, 
  activeSubId,
  onSelect, 
  onCreateSub, 
  onDelete,
  expanded,
  onToggleExpand
}) {
  const hasChildren = thread.sub_threads && thread.sub_threads.length > 0;

  return (
    <div className="thread-item">
      <div 
        className={`thread-item__header ${isActive && !activeSubId ? 'thread-item__header--active' : ''}`}
        onClick={() => onSelect(thread.id, thread.name)}
      >
        <span 
          className={`thread-item__expand ${hasChildren ? '' : 'thread-item__expand--hidden'} ${expanded ? 'thread-item__expand--rotated' : ''}`}
          onClick={(e) => {
            e.stopPropagation();
            onToggleExpand(thread.id);
          }}
        >
          <ChevronRight size={14} />
        </span>
        
        <div className="thread-item__icon">
          <MessageSquare size={16} />
        </div>
        
        <div className="thread-item__content">
          <div className="thread-item__name">{thread.name}</div>
          <div className="thread-item__meta">
            {hasChildren && (
              <span>{thread.sub_threads.length} sub-thread{thread.sub_threads.length > 1 ? 's' : ''}</span>
            )}
          </div>
        </div>
        
        <div className="thread-item__actions">
          <button
            className="thread-item__action-btn"
            onClick={(e) => {
              e.stopPropagation();
              onCreateSub(thread.id);
            }}
            title="Create sub-thread"
          >
            <Plus size={14} />
          </button>
          <button
            className="thread-item__action-btn thread-item__action-btn--danger"
            onClick={(e) => {
              e.stopPropagation();
              onDelete(thread.id);
            }}
            title="Delete thread"
          >
            <Trash2 size={14} />
          </button>
        </div>
      </div>
      
      {hasChildren && expanded && (
        <div className="thread-item__children">
          {thread.sub_threads.map(sub => (
            <div
              key={sub.id}
              className={`subthread-item ${activeSubId === sub.id ? 'subthread-item--active' : ''}`}
              onClick={() => onSelect(sub.id, sub.name, thread.id)}
            >
              <span className="subthread-item__icon">
                <FileText size={14} />
              </span>
              <span className="subthread-item__name">{sub.name}</span>
              <div className="subthread-item__actions">
                <button
                  className="thread-item__action-btn thread-item__action-btn--danger"
                  onClick={(e) => {
                    e.stopPropagation();
                    onDelete(sub.id);
                  }}
                  title="Delete sub-thread"
                >
                  <Trash2 size={14} />
                </button>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

export function Sidebar({
  threads = [],
  currentThreadId,
  onSelectThread,
  onCreateThread,
  onCreateSubThread,
  onDeleteThread,
  onOpenSettings
}) {
  const [expandedThreads, setExpandedThreads] = useState(new Set());

  const toggleExpand = (threadId) => {
    setExpandedThreads(prev => {
      const next = new Set(prev);
      if (next.has(threadId)) {
        next.delete(threadId);
      } else {
        next.add(threadId);
      }
      return next;
    });
  };

  // Find if current thread is a sub-thread
  let activeParentId = null;
  let activeSubId = null;
  
  for (const thread of threads) {
    if (thread.id === currentThreadId) {
      activeParentId = thread.id;
      break;
    }
    if (thread.sub_threads) {
      const sub = thread.sub_threads.find(s => s.id === currentThreadId);
      if (sub) {
        activeParentId = thread.id;
        activeSubId = sub.id;
        break;
      }
    }
  }

  // Auto-expand parent if sub-thread is selected
  if (activeParentId && activeSubId && !expandedThreads.has(activeParentId)) {
    setExpandedThreads(prev => new Set([...prev, activeParentId]));
  }

  return (
    <aside className="sidebar">
      <div className="sidebar__header">
        <div className="sidebar__logo">
          <div className="sidebar__logo-icon">
            <Sparkles size={18} />
          </div>
          <span className="sidebar__logo-text">RAG-OCR</span>
        </div>
      </div>

      <div className="sidebar__new-thread">
        <button className="sidebar__new-thread-btn" onClick={onCreateThread}>
          <Plus size={16} />
          New Thread
        </button>
      </div>

      <div className="sidebar__threads">
        {threads.length === 0 ? (
          <div className="sidebar__empty">
            <div className="sidebar__empty-icon">
              <FolderOpen size={24} />
            </div>
            <div className="sidebar__empty-text">No threads yet</div>
            <div className="sidebar__empty-hint">Create a thread to start chatting</div>
          </div>
        ) : (
          <>
            <div className="sidebar__section-title">Your Threads</div>
            {threads.map(thread => (
              <ThreadItem
                key={thread.id}
                thread={thread}
                isActive={activeParentId === thread.id}
                activeSubId={activeSubId}
                expanded={expandedThreads.has(thread.id)}
                onToggleExpand={toggleExpand}
                onSelect={onSelectThread}
                onCreateSub={onCreateSubThread}
                onDelete={onDeleteThread}
              />
            ))}
          </>
        )}
      </div>

      <div className="sidebar__footer">
        <button className="sidebar__footer-btn" onClick={onOpenSettings}>
          <Settings size={16} />
          Settings
        </button>
      </div>
    </aside>
  );
}

export default Sidebar;
