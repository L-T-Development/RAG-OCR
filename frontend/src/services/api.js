const API_BASE = '/api';

export const api = {
  // Threads
  async listThreads() {
    const res = await fetch(`${API_BASE}/list-threads/`);
    return res.json();
  },

  async createThread(name, parentId = null) {
    const res = await fetch(`${API_BASE}/create-thread/`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ name, parent_id: parentId })
    });
    return res.json();
  },

  async deleteThread(threadId) {
    const res = await fetch(`${API_BASE}/delete-thread/${threadId}/`, {
      method: 'DELETE'
    });
    return { ok: res.ok, data: await res.json() };
  },

  // Files
  async getThreadFiles(threadId) {
    const res = await fetch(`${API_BASE}/files/${threadId}/`);
    return res.json();
  },

  async uploadFile(threadId, file) {
    const formData = new FormData();
    formData.append('file', file);
    const res = await fetch(`${API_BASE}/upload/${threadId}/`, {
      method: 'POST',
      body: formData
    });
    return { ok: res.ok, data: await res.json() };
  },

  async deleteDocument(docId) {
    const res = await fetch(`${API_BASE}/delete-document/${docId}/`, {
      method: 'DELETE'
    });
    return { ok: res.ok, data: await res.json() };
  },

  // Chat
  async getChatHistory(threadId) {
    const res = await fetch(`${API_BASE}/chat/history/${threadId}/`);
    if (!res.ok) return { messages: [] };
    return res.json();
  },

  async sendMessage(threadId, query) {
    const res = await fetch(`${API_BASE}/chat/${threadId}/`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ query })
    });
    return res.json();
  },

  // Compare
  async compareDocuments(oldFile, newFile) {
    const formData = new FormData();
    formData.append('old_file', oldFile);
    formData.append('new_file', newFile);
    const res = await fetch(`${API_BASE}/compare-documents/`, {
      method: 'POST',
      body: formData
    });
    return { ok: res.ok, data: await res.json() };
  }
};
