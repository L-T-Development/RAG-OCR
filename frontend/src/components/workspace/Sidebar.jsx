import { useState, useEffect } from 'react';
import {
  Plus,
  MessageSquare,
  ChevronRight,
  Trash2,
  FolderOpen,
  Settings,
  FileText,
  Upload,
  Sparkles,
} from 'lucide-react';

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
  const isRootLevel = level === 0;

  return (
    <div>
      <div
        className={`group flex items-center gap-1.5 pr-2 py-1.5 rounded-md cursor-pointer transition-colors select-none
          ${isCurrentActive
            ? 'bg-[var(--color-sidebar-active)] text-[var(--color-sidebar-text)]'
            : 'text-[var(--color-sidebar-text-muted)] hover:bg-[var(--color-sidebar-hover)] hover:text-[var(--color-sidebar-text)]'
          }
          ${!isRootLevel ? 'text-sm' : ''}`}
        style={{ paddingLeft: `${12 + level * 20}px` }}
        onClick={() => onSelect(thread.id, thread.name, parentId)}
      >
        <span
          className={`flex-shrink-0 transition-transform ${hasChildren ? 'opacity-100' : 'opacity-0 pointer-events-none'} ${isExpanded ? 'rotate-90' : ''}`}
          onClick={(e) => {
            e.stopPropagation();
            onToggleExpand(thread.id);
          }}
        >
          <ChevronRight size={13} />
        </span>

        <span className="flex-shrink-0 opacity-70">
          {isRootLevel ? <MessageSquare size={16} /> : <FileText size={14} />}
        </span>

        <div className="flex-1 min-w-0">
          <div className="truncate text-sm font-medium">{thread.name}</div>
          {hasChildren && (
            <div className="text-xs opacity-50">
              {thread.sub_threads.length} sub-thread{thread.sub_threads.length > 1 ? 's' : ''}
            </div>
          )}
        </div>

        <div className="flex items-center gap-0.5 opacity-0 group-hover:opacity-100 transition-opacity flex-shrink-0">
          <button
            className="flex items-center justify-center w-5 h-5 rounded hover:bg-[var(--color-sidebar-border)] transition-colors"
            onClick={(e) => {
              e.stopPropagation();
              onCreateSub(thread.id);
            }}
            title="Create sub-thread"
          >
            <Plus size={12} />
          </button>
          <button
            className="flex items-center justify-center w-5 h-5 rounded hover:bg-red-500/20 hover:text-red-400 transition-colors"
            onClick={(e) => {
              e.stopPropagation();
              onDelete(thread.id);
            }}
            title="Delete thread"
          >
            <Trash2 size={12} />
          </button>
        </div>
      </div>

      {hasChildren && isExpanded && (
        <div>
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
  const [expandedThreads, setExpandedThreads] = useState(new Set());

  const toggleExpand = (threadId) => {
    setExpandedThreads((prev) => {
      const next = new Set(prev);
      next.has(threadId) ? next.delete(threadId) : next.add(threadId);
      return next;
    });
  };

  const findThreadPath = (threadList, targetId, path = []) => {
    for (const thread of threadList) {
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
      const threadPath = findThreadPath(threads, currentThreadId);
      if (threadPath && threadPath.length > 1) {
        const parentsToExpand = threadPath.slice(0, -1);
        setExpandedThreads((prev) => {
          const next = new Set(prev);
          parentsToExpand.forEach((id) => next.add(id));
          return next;
        });
      }
    }
  }, [currentThreadId, threads]);

  return (
    <aside
      className="flex flex-col h-full bg-[var(--color-sidebar-bg)] border-r border-[var(--color-sidebar-border)]"
      style={{ width: 'var(--sidebar-width, 280px)' }}
    >
      <div className="p-3 border-b border-[var(--color-sidebar-border)]">
        <div className="flex items-center gap-2 px-2 py-2 mb-3">
          <div className="flex items-center justify-center w-8 h-8 rounded-md bg-primary text-white">
            <Sparkles size={16} />
          </div>
          <div className="min-w-0">
            <div className="text-sm font-semibold text-[var(--color-sidebar-text)] truncate">Enterprise OCR</div>
            <div className="text-xs text-[var(--color-sidebar-text-muted)]">Intelligent RAG</div>
          </div>
        </div>

        <button
          className="w-full flex items-center justify-center gap-2 px-3 py-2 rounded-md bg-primary hover:bg-primary-hover text-white text-sm font-medium transition-colors cursor-pointer border-0"
          onClick={onUploadDocument || onCreateThread}
        >
          <Upload size={16} />
          Upload Document
        </button>

        <button
          className="w-full flex items-center justify-center gap-2 px-3 py-2 mt-2 rounded-md border border-[var(--color-sidebar-border)] text-sm text-[var(--color-sidebar-text)] hover:bg-[var(--color-sidebar-hover)] transition-colors cursor-pointer bg-transparent"
          onClick={onCreateThread}
        >
          <Plus size={16} />
          New Thread
        </button>
      </div>

      <div className="flex-1 overflow-y-auto p-2">
        {threads.length === 0 ? (
          <div className="flex flex-col items-center justify-center gap-2 py-12 text-center px-4">
            <div className="text-[var(--color-sidebar-text-muted)] opacity-50">
              <FolderOpen size={24} />
            </div>
            <div className="text-sm text-[var(--color-sidebar-text-muted)] font-medium">No threads yet</div>
            <div className="text-xs text-[var(--color-sidebar-text-muted)] opacity-60">Create a thread to start chatting</div>
          </div>
        ) : (
          <>
            <div className="px-2 py-1.5 text-xs font-semibold uppercase tracking-wider text-[var(--color-sidebar-text-muted)] opacity-60 mb-1">
              Your Threads
            </div>
            {threads.map((thread) => (
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

      <div className="p-3 border-t border-[var(--color-sidebar-border)]">
        <button
          className="w-full flex items-center gap-2 px-3 py-2 rounded-md text-sm text-[var(--color-sidebar-text-muted)] hover:bg-[var(--color-sidebar-hover)] hover:text-[var(--color-sidebar-text)] transition-colors cursor-pointer border-0 bg-transparent"
          onClick={onOpenSettings}
        >
          <Settings size={16} />
          <span>Settings</span>
        </button>
      </div>
    </aside>
  );
}

export default Sidebar;
