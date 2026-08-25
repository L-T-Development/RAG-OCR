// API base URL - proxied through Vite in development
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
      body: JSON.stringify({ name, parent_id: parentId }),
    });
    return res.json();
  },

  async deleteThread(threadId) {
    const res = await fetch(`${API_BASE}/delete-thread/${threadId}/`, {
      method: 'DELETE',
    });
    return { ok: res.ok, data: await res.json() };
  },

  // Decisions a person made — confirmed matches and pinned columns. These are the
  // only things here that cannot be rebuilt by re-uploading a document.
  getDecisionsExportUrl() {
    return `${API_BASE}/decisions/export/`;
  },

  async importDecisions(payload, { dryRun = true, overwrite = false, applySchema = false } = {}) {
    const res = await fetch(`${API_BASE}/decisions/import/`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        payload, dry_run: dryRun, overwrite, apply_schema: applySchema,
      }),
    });
    return { ok: res.ok, data: await res.json() };
  },

  async backupData({ includeMedia = true, includeVectors = true } = {}) {
    const res = await fetch(`${API_BASE}/decisions/backup/`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ include_media: includeMedia, include_vectors: includeVectors }),
    });
    return { ok: res.ok, data: await res.json() };
  },

  // Comparison (the wizard — same engine as chat, without the phrasing)
  async runComparison({ threadId, docIds, column, columnB = null, literal = false, mode = 'columns' }) {
    const res = await fetch(`${API_BASE}/comparison/run/`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        thread_id: threadId, doc_ids: docIds, column,
        column_b: columnB, literal, mode,
      }),
    });
    return { ok: res.ok, data: await res.json() };
  },

  // How one document's columns are understood, and pinning them
  async getDocumentColumns(docId) {
    const res = await fetch(`${API_BASE}/documents/${docId}/columns/`);
    return { ok: res.ok, data: await res.json() };
  },

  async setDocumentColumn(docId, field, header) {
    const res = await fetch(`${API_BASE}/documents/${docId}/columns/`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ field, header }),
    });
    return { ok: res.ok, data: await res.json() };
  },

  async getDocumentExtraction(docId) {
    const res = await fetch(`${API_BASE}/documents/${docId}/extraction/`);
    return { ok: res.ok, data: await res.json() };
  },

  async confirmMatch({ sourceA, sourceB, column, valueA, valueB, threadId = null, note = '' }) {
    const res = await fetch(`${API_BASE}/comparison/confirm-match/`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        source_a: sourceA, source_b: sourceB, column,
        value_a: valueA, value_b: valueB, thread_id: threadId, note,
      }),
    });
    return { ok: res.ok, data: await res.json() };
  },

  // Files
  async getThreadFiles(threadId) {
    if (!threadId || threadId === 'undefined' || threadId === 'null') {
      return { files: [] };
    }
    const res = await fetch(`${API_BASE}/files/${threadId}/`);
    return res.json();
  },

  async uploadFile(threadId, file, category = 'other') {
    const formData = new FormData();
    formData.append('file', file);
    formData.append('category', category);
    const res = await fetch(`${API_BASE}/upload/${threadId}/`, {
      method: 'POST',
      body: formData,
    });
    return { ok: res.ok, data: await res.json() };
  },

  async getDocumentProgress(docId) {
    const res = await fetch(`${API_BASE}/documents/${docId}/progress/`);
    return { ok: res.ok, data: await res.json() };
  },

  async deleteDocument(docId) {
    const res = await fetch(`${API_BASE}/delete-document/${docId}/`, {
      method: 'DELETE',
    });
    return { ok: res.ok, data: await res.json() };
  },

  // Document Metadata
  async getDocumentMetadata(docId) {
    const res = await fetch(`${API_BASE}/documents/${docId}/metadata/`);
    return { ok: res.ok, data: await res.json() };
  },

  async updateDocumentMetadata(docId, metadata) {
    const res = await fetch(`${API_BASE}/documents/${docId}/metadata/`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(metadata),
    });
    return { ok: res.ok, data: await res.json() };
  },

  async linkDocumentVersion(docId, previousVersionId) {
    const res = await fetch(`${API_BASE}/documents/${docId}/link-version/`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ previous_version_id: previousVersionId }),
    });
    return { ok: res.ok, data: await res.json() };
  },

  async getDocumentVersionHistory(docId) {
    const res = await fetch(`${API_BASE}/documents/${docId}/versions/`);
    return { ok: res.ok, data: await res.json() };
  },

  // Quick Upload - auto-creates thread named after PDF
  async quickUpload(file, category = 'other') {
    const formData = new FormData();
    formData.append('file', file);
    formData.append('category', category);
    const res = await fetch(`${API_BASE}/quick-upload/`, {
      method: 'POST',
      body: formData,
    });
    return { ok: res.ok, data: await res.json() };
  },

  // Chat
  async getChatHistory(threadId) {
    if (!threadId || threadId === 'undefined' || threadId === 'null') {
      return { messages: [] };
    }
    const res = await fetch(`${API_BASE}/chat/history/${threadId}/`);
    if (!res.ok) return { messages: [] };
    return res.json();
  },

  async sendMessage(threadId, query, longResponse = false) {
    const res = await fetch(`${API_BASE}/chat/${threadId}/`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ query, long_response: longResponse }),
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
      body: formData,
    });
    return { ok: res.ok, data: await res.json() };
  },

  async getComparisonStatus(jobId) {
    const res = await fetch(`${API_BASE}/compare/status/${jobId}/`);
    return { ok: res.ok, data: await res.json() };
  },

  // Document Summary
  async summarizeThread(threadId, longResponse = false) {
    const q = longResponse ? '?long_response=true' : '';
    const res = await fetch(`${API_BASE}/summarize/thread/${threadId}/${q}`);
    return { ok: res.ok, data: await res.json() };
  },

  async summarizeDocument(docId, longResponse = false) {
    const q = longResponse ? '?long_response=true' : '';
    const res = await fetch(`${API_BASE}/summarize/document/${docId}/${q}`);
    return { ok: res.ok, data: await res.json() };
  },

  async getThreadInfo(threadId) {
    const res = await fetch(`${API_BASE}/thread-info/${threadId}/`);
    return { ok: res.ok, data: await res.json() };
  },

  // Model Configuration
  async getModelStatus() {
    const res = await fetch(`${API_BASE}/model/status/`);
    return { ok: res.ok, data: await res.json() };
  },

  async configureModel(path) {
    const res = await fetch(`${API_BASE}/model/configure/`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ path }),
    });
    return { ok: res.ok, data: await res.json() };
  },

  async configureEmbeddingProvider(provider, model) {
    const res = await fetch(`${API_BASE}/embedding/configure/`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ provider, model }),
    });
    return { ok: res.ok, data: await res.json() };
  },

  async validateModelPath(path) {
    const res = await fetch(`${API_BASE}/model/validate/`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ path }),
    });
    return { ok: res.ok, data: await res.json() };
  },

  async getAppConfig() {
    const res = await fetch(`${API_BASE}/config/`);
    return { ok: res.ok, data: await res.json() };
  },

  // Ollama installed models (live from /api/tags)
  async getOllamaModels() {
    const res = await fetch(`${API_BASE}/ollama/models/`);
    return { ok: res.ok, data: await res.json() };
  },

  // LLM Model Selection
  async getLLMModels() {
    const res = await fetch(`${API_BASE}/llm/models/`);
    return { ok: res.ok, data: await res.json() };
  },

  async selectLLMModel(modelId) {
    const res = await fetch(`${API_BASE}/llm/select/`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ model: modelId }),
    });
    return { ok: res.ok, data: await res.json() };
  },

  // ==================== REPORTS / COMPARATOR ====================

  /**
   * Extract columns from uploaded file (Excel, PDF, Image)
   * Returns column names only (fast). Use getColumnPreview for values.
   */
  async getColumnsFromFile(file) {
    const formData = new FormData();
    formData.append('file', file);
    const res = await fetch(`${API_BASE}/reports/columns/`, {
      method: 'POST',
      body: formData,
    });
    return { ok: res.ok, data: await res.json() };
  },

  /**
   * Get preview values for a specific column (lazy loading)
   * @param {string} fileId - File ID from getColumnsFromFile response
   * @param {string} columnName - Column to get preview for
   * @returns {Promise<{column, preview: string[], total_count: number}>}
   */
  async getColumnPreview(fileId, columnName) {
    const res = await fetch(`${API_BASE}/reports/column-preview/`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ file_id: fileId, column_name: columnName }),
    });
    return { ok: res.ok, data: await res.json() };
  },

  /**
   * Get columns and preview from multiple PDFs - merges tables with matching columns
   * @param {File[]} pdfFiles - Array of PDF files to analyze
   * @param {boolean} useOcr - Enable OCR (default: true)
   * @returns {Promise<{columns: string[], preview: {[column]: string[]}}>}
   */
  async getMultiPdfColumnsPreview(pdfFiles, useOcr = true) {
    const formData = new FormData();
    pdfFiles.forEach(file => {
      formData.append('pdf_files', file);
    });
    formData.append('use_ocr', useOcr.toString());
    
    const res = await fetch(`${API_BASE}/reports/multi-pdf-columns/`, {
      method: 'POST',
      body: formData,
    });
    return { ok: res.ok, data: await res.json() };
  },

  /**
   * Start multi-PDF comparison job
   * @param {File} sourceFile - Excel/PDF with values to search
   * @param {string} columnName - Column to extract values from
   * @param {File[]} pdfFiles - Array of PDF files to search in
   * @param {boolean} useOcr - Enable OCR for scanned documents
   */
  async startMultiPdfComparison(sourceFile, columnName, pdfFiles, useOcr = false) {
    const formData = new FormData();
    formData.append('source_file', sourceFile);
    formData.append('column_name', columnName);
    pdfFiles.forEach(file => {
      formData.append('pdf_files', file);
    });
    formData.append('use_ocr', useOcr.toString());
    
    const res = await fetch(`${API_BASE}/reports/compare/`, {
      method: 'POST',
      body: formData,
    });
    return { ok: res.ok, data: await res.json() };
  },

  /**
   * Start single PDF comparison job (with hybrid OCR support)
   * @param {File} sourceFile - Excel/PDF with values to search
   * @param {string} columnName - Column to extract values from
   * @param {File} pdfFile - Single PDF file to search in
   * @param {boolean} useOcr - Enable hybrid OCR for mixed text/scanned pages
   */
  async startSinglePdfComparison(sourceFile, columnName, pdfFile, useOcr = true) {
    const formData = new FormData();
    formData.append('source_file', sourceFile);
    formData.append('column_name', columnName);
    formData.append('pdf_file', pdfFile);
    formData.append('use_ocr', useOcr.toString());
    
    const res = await fetch(`${API_BASE}/reports/compare-single/`, {
      method: 'POST',
      body: formData,
    });
    return { ok: res.ok, data: await res.json() };
  },

  /**
   * Get status of report job
   */
  async getReportStatus(jobId) {
    const res = await fetch(`${API_BASE}/reports/status/${jobId}/`);
    return { ok: res.ok, data: await res.json() };
  },

  /**
   * Quick synchronous comparison (for small files)
   */
  async quickColumnCompare(sourceFile, targetFile, columnName, useOcr = false) {
    const formData = new FormData();
    formData.append('source_file', sourceFile);
    formData.append('target_file', targetFile);
    formData.append('column_name', columnName);
    formData.append('use_ocr', useOcr.toString());
    
    const res = await fetch(`${API_BASE}/reports/quick-compare/`, {
      method: 'POST',
      body: formData,
    });
    return { ok: res.ok, data: await res.json() };
  },

  /**
   * Get download URL for report
   */
  getReportDownloadUrl(jobId) {
    return `${API_BASE}/reports/download/${jobId}/`;
  },
};
