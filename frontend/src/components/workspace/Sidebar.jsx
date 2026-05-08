import { useState, useEffect } from 'react';
import { Link, useLocation } from 'react-router-dom';
import {
  Plus,
  MessageSquare,
  ChevronRight,
  Trash2,
  FileText,
  Upload,
  LayoutDashboard,
  GitCompare,
  BarChart3,
  HelpCircle,
  User,
  Settings,
  Sparkles,
  FolderOpen,
  Home,
  ExternalLink,
} from 'lucide-react';
import './Sidebar.css';

/* ── Recursive Thread Item ── */
function ThreadItem({
  thread,
  isActive,
  onSelect,
  onCreateSub,
  onDelete,
  expandedThreads,
  onToggleExpand,
  level = 0,
  parentId = null,
}) {
  const hasChildren = thread.sub_threads && thread.sub_threads.length > 0;
  const isExpanded = expandedThreads.has(thread.id);
  const isCurrentActive = isActive === thread.id;

  return (
    <div className="thread-item" style={{ '--nest-level': level }}>
      <div
        className={`thread-item__header${isCurrentActive ? ' thread-item__header--active' : ''}${level > 0 ? ' thread-item__header--nested' : ''}`}
        onClick={() => onSelect(thread.id, thread.name, parentId)}
        style={{ paddingLeft: `${14 + level * 16}px` }}
      >
        <span
          className={`thread-item__expand${!hasChildren ? ' thread-item__expand--hidden' : ''}${isExpanded ? ' thread-item__expand--rotated' : ''}`}
          onClick={(e) => {
            e.stopPropagation();
            onToggleExpand(thread.id);
          }}
        >
          <ChevronRight size={13} />
        </span>

        <div className="thread-item__icon">
          {level === 0 ? <MessageSquare size={14} /> : <FileText size={13} />}
        </div>

        <div className="thread-item__content">
          <div className="thread-item__name">{thread.name}</div>
          {hasChildren && (
            <div className="thread-item__meta">
              {thread.sub_threads.length} sub-thread{thread.sub_threads.length > 1 ? 's' : ''}
            </div>
          )}
        </div>

        <div className="thread-item__actions">
          <button
            className="thread-item__action-btn"
            onClick={(e) => { e.stopPropagation(); onCreateSub(thread.id); }}
            title="Create sub-thread"
          >
            <Plus size={13} />
          </button>
          <button
            className="thread-item__action-btn thread-item__action-btn--danger"
            onClick={(e) => { e.stopPropagation(); onDelete(thread.id); }}
            title="Delete thread"
          >
            <Trash2 size={13} />
          </button>
        </div>
      </div>

      {hasChildren && isExpanded && (
        <div className="thread-item__children">
          {thread.sub_threads.map((sub) => (
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

/* ── Main Sidebar ── */
export function Sidebar({
  threads = [],
  currentThreadId,
  onSelectThread,
  onCreateThread,
  onCreateSubThread,
  onDeleteThread,
  onOpenSettings,
  onUploadDocument,
}) {
  const location = useLocation();
  const [expandedThreads, setExpandedThreads] = useState(new Set());

  const toggleExpand = (threadId) => {
    setExpandedThreads((prev) => {
      const next = new Set(prev);
      next.has(threadId) ? next.delete(threadId) : next.add(threadId);
      return next;
    });
  };

  const findThreadPath = (threads, targetId, path = []) => {
    for (const thread of threads) {
      if (thread.id === targetId) return [...path, thread.id];
      if (thread.sub_threads?.length) {
        const found = findThreadPath(thread.sub_threads, targetId, [...path, thread.id]);
        if (found) return found;
      }
    }
    return null;
  };

  useEffect(() => {
    if (currentThreadId && threads.length > 0) {
      const path = findThreadPath(threads, currentThreadId);
      if (path && path.length > 1) {
        setExpandedThreads((prev) => {
          const next = new Set(prev);
          path.slice(0, -1).forEach((id) => next.add(id));
          return next;
        });
      }
    }
  }, [currentThreadId, threads]);

  const isActive = (path) => location.pathname === path;

  return (
    <aside className="sidebar">
      {/* ── Brand ── */}
      <div className="sidebar__brand">
        <div className="sidebar__brand-icon">
          <Sparkles size={16} />
        </div>
        <div className="sidebar__brand-info">
          <span className="sidebar__brand-name">Enterprise OCR</span>
          <span className="sidebar__brand-sub">Intelligent RAG</span>
        </div>
      </div>

      {/* ── Upload Document Button ── */}
      <div className="sidebar__upload">
        <button className="sidebar__upload-btn" onClick={onUploadDocument || onCreateThread}>
          <Upload size={15} />
          Upload Document
        </button>
      </div>

      {/* ── Page Navigation ── */}
      <nav className="sidebar__nav">
        <Link to="/" className={`sidebar__nav-item${isActive('/') ? ' sidebar__nav-item--active' : ''}`}>
          <Home size={17} />
          <span>Home</span>
        </Link>
        <a
          className="sidebar__nav-item"
          href="http://localhost:8080/"
          target="_blank"
          rel="noreferrer"
        >
          <ExternalLink size={17} />
          <span>Preview</span>
        </a>
        <Link to="/workspace" className={`sidebar__nav-item${isActive('/workspace') ? ' sidebar__nav-item--active' : ''}`}>
          <LayoutDashboard size={17} />
          <span>Dashboard</span>
        </Link>
        <Link to="/compare" className={`sidebar__nav-item${isActive('/compare') ? ' sidebar__nav-item--active' : ''}`}>
          <GitCompare size={17} />
          <span>Compare</span>
        </Link>
        <Link to="/reports" className={`sidebar__nav-item${isActive('/reports') ? ' sidebar__nav-item--active' : ''}`}>
          <BarChart3 size={17} />
          <span>Reports</span>
        </Link>
      </nav>

      {/* ── Thread Section Divider ── */}
      <div className="sidebar__section-header">
        <span>Threads</span>
        <button className="sidebar__new-btn" onClick={onCreateThread} title="New thread">
          <Plus size={14} />
        </button>
      </div>

      {/* ── Thread List ── */}
      <div className="sidebar__threads">
        {threads.length === 0 ? (
          <div className="sidebar__empty">
            <div className="sidebar__empty-icon">
              <FolderOpen size={20} />
            </div>
            <p className="sidebar__empty-text">No threads yet</p>
            <p className="sidebar__empty-hint">Create a thread to start chatting</p>
          </div>
        ) : (
          threads.map((thread) => (
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
          ))
        )}
      </div>

      {/* ── Footer ── */}
      <div className="sidebar__footer">
        <Link to="/settings" className="sidebar__footer-item">
          <Settings size={16} />
          <span>Settings</span>
        </Link>
        <button className="sidebar__footer-item" onClick={onOpenSettings}>
          <HelpCircle size={16} />
          <span>Help Center</span>
        </button>
        <button className="sidebar__footer-item">
          <User size={16} />
          <span>Account</span>
        </button>
      </div>
    </aside>
  );
}

export default Sidebar;
