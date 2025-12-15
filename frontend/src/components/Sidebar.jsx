import { useState } from 'react';
import './Sidebar.css';

function Sidebar({ threads, currentThreadId, onSelectThread, onCreateThread, onDeleteThread }) {
  const [showModal, setShowModal] = useState(false);
  const [newName, setNewName] = useState('');
  const [parentId, setParentId] = useState('');

  const handleCreate = () => {
    if (!newName.trim()) return;
    onCreateThread(newName, parentId || null);
    setNewName('');
    setParentId('');
    setShowModal(false);
  };

  return (
    <aside className="sidebar">
      <div className="sidebar-header">
        <span className="sidebar-title">Threads</span>
        <button className="btn btn-primary" onClick={() => setShowModal(true)} style={{ fontSize: '0.8rem', padding: '6px 12px' }}>
          <i className="fa-solid fa-plus" style={{ marginRight: '4px' }}></i> New
        </button>
      </div>

      <div className="thread-list">
        {threads.map(parent => (
          <div key={parent.id}>
            <div
              className={`thread-item ${currentThreadId === parent.id ? 'active' : ''}`}
              onClick={() => onSelectThread(parent.id, parent.name)}
            >
              <div className="thread-content">
                <span>
                  <i className="fa-solid fa-folder" style={{ color: '#64748b', marginRight: '8px' }}></i>
                  {parent.name}
                </span>
                <i
                  className="fa-solid fa-trash btn-icon actions"
                  onClick={(e) => { e.stopPropagation(); onDeleteThread(parent.id); }}
                  title="Delete Thread"
                ></i>
              </div>
            </div>
            
            {parent.sub_threads.map(sub => (
              <div
                key={sub.id}
                className={`thread-item sub-thread ${currentThreadId === sub.id ? 'active' : ''}`}
                onClick={() => onSelectThread(sub.id, sub.name)}
              >
                <div className="thread-content">
                  <span>
                    <i className="fa-solid fa-turn-up" style={{ transform: 'rotate(90deg)', marginRight: '6px', color: '#cbd5e1' }}></i>
                    {sub.name}
                  </span>
                  <i
                    className="fa-solid fa-trash btn-icon actions"
                    onClick={(e) => { e.stopPropagation(); onDeleteThread(sub.id); }}
                    title="Delete Thread"
                  ></i>
                </div>
              </div>
            ))}
          </div>
        ))}
      </div>

      {/* Create Modal */}
      {showModal && (
        <div className="modal" onClick={() => setShowModal(false)}>
          <div className="modal-content" onClick={e => e.stopPropagation()}>
            <h3>New Thread</h3>
            <input
              type="text"
              placeholder="Thread Name e.g. 'Project Alpha Specs'"
              value={newName}
              onChange={e => setNewName(e.target.value)}
              onKeyPress={e => e.key === 'Enter' && handleCreate()}
            />
            <div className="form-group">
              <label>Parent Thread (Optional):</label>
              <select value={parentId} onChange={e => setParentId(e.target.value)}>
                <option value="">None (Top Level)</option>
                {threads.map(t => (
                  <option key={t.id} value={t.id}>{t.name}</option>
                ))}
              </select>
            </div>
            <div className="modal-actions">
              <button className="btn" onClick={() => setShowModal(false)}>Cancel</button>
              <button className="btn btn-primary" onClick={handleCreate}>Create Thread</button>
            </div>
          </div>
        </div>
      )}
    </aside>
  );
}

export default Sidebar;
