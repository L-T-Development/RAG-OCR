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
  onSelect, 
  onCreateSub, 
  onDelete,
  expandedThreads,
  onToggleExpand,
  level = 0,  // Track nesting level
  parentId = null
}) {
  const hasChildren = thread.sub_threads && thread.sub_threads.length > 0;
  const isRootLevel = level === 0;
  const isExpanded = expandedThreads.has(thread.id);
  const isCurrentActive = isActive === thread.id;

  return (
    <div className="thread-item" style={{ '--nest-level': level }}>
      <div 
        className={`thread-item__header ${isCurrentActive ? 'thread-item__header--active' : ''} ${!isRootLevel ? 'thread-item__header--nested' : ''}`}
        onClick={() => onSelect(thread.id, thread.name, parentId)}
        style={{ paddingLeft: `${12 + level * 20}px` }}
      >
        <span 
          className={`thread-item__expand ${hasChildren ? '' : 'thread-item__expand--hidden'} ${isExpanded ? 'thread-item__expand--rotated' : ''}`}
          onClick={(e) => {
            e.stopPropagation();
            onToggleExpand(thread.id);
          }}
        >
          <ChevronRight size={14} />
        </span>
        
        <div className="thread-item__icon">
          {isRootLevel ? <MessageSquare size={16} /> : <FileText size={14} />}
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
      
      {hasChildren && isExpanded && (
        <div className="thread-item__children">
          {thread.sub_threads.map(sub => (
            <ThreadItem
              key={sub.id}
              thread={sub}
              isActive={isActive}
              expandedThreads={expandedThreads}
              onToggleExpand={onToggleExpand}
              onSelect={onSelect}
              onCreateSub={onCreateSub}
              onDelete={onDelete}
              level={level + 1}
              parentId={thread.id}
            />
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

  // Recursively find thread and its parents
  const findThreadPath = (threads, targetId, path = []) => {
    for (const thread of threads) {
      if (thread.id === targetId) {
        return [...path, thread.id];
      }
      if (thread.sub_threads && thread.sub_threads.length > 0) {
        const found = findThreadPath(thread.sub_threads, targetId, [...path, thread.id]);
        if (found) return found;
      }
    }
    return null;
  };

  // Auto-expand all parents of current thread
  const threadPath = findThreadPath(threads, currentThreadId);
  if (threadPath) {
    const parentsToExpand = threadPath.slice(0, -1); // All except the current thread itself
    parentsToExpand.forEach(parentId => {
      if (!expandedThreads.has(parentId)) {
        setExpandedThreads(prev => new Set([...prev, parentId]));
      }
    });
  }

  // Helper to check if a thread is active (recursively)
  const isThreadActive = (thread, currentId) => {
    if (thread.id === currentId) return true;
    if (thread.sub_threads) {
      return thread.sub_threads.some(sub => isThreadActive(sub, currentId));
    }
    return false;
  };

  return (
    <aside className="sidebar">
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
                isActive={currentThreadId}
                expandedThreads={expandedThreads}
                onToggleExpand={toggleExpand}
                onSelect={onSelectThread}
                onCreateSub={onCreateSubThread}
                onDelete={onDeleteThread}
                level={0}
                parentId={null}
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
