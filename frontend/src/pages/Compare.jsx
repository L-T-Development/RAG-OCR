import { useState, useEffect, useRef } from 'react';
import { Navigation } from '../components/shared/Navigation';
import { api } from '../services/api';

function Compare() {
  const [oldFile, setOldFile] = useState(null);
  const [newFile, setNewFile] = useState(null);
  const [status, setStatus] = useState('');
  const [diffResult, setDiffResult] = useState(null);
  const [isLoading, setIsLoading] = useState(false);
  const [jobId, setJobId] = useState(null);
  const [showOnlyChanges, setShowOnlyChanges] = useState(false);
  const [uploadProgress, setUploadProgress] = useState(0);
  const [currentPage, setCurrentPage] = useState(1);
  const [itemsPerPage] = useState(100);
  const [pageInput, setPageInput] = useState('1');
  const pollingTimerRef = useRef(null);

  useEffect(() => {
    return () => {
      if (pollingTimerRef.current) clearInterval(pollingTimerRef.current);
    };
  }, []);

  const validateFiles = () => {
    if (!oldFile || !newFile) return false;
    return oldFile.name.split('.').pop().toLowerCase() === newFile.name.split('.').pop().toLowerCase();
  };

  const handleCompare = async () => {
    if (!validateFiles()) { setStatus('Files must be of the same type.'); return; }
    if (pollingTimerRef.current) { clearInterval(pollingTimerRef.current); pollingTimerRef.current = null; }
    setIsLoading(true); setStatus('Uploading files...'); setDiffResult(null);
    setUploadProgress(0); setCurrentPage(1); setPageInput('1');
    const prog = setInterval(() => setUploadProgress(p => p >= 90 ? p : p + 10), 300);
    try {
      const { ok, data } = await api.compareDocuments(oldFile, newFile);
      clearInterval(prog); setUploadProgress(100);
      if (ok && data.job_id) { setJobId(data.job_id); setStatus('Processing documents...'); pollComparisonStatus(data.job_id); }
      else if (ok && data.diff) { setDiffResult(data.diff); setStatus(`Comparison completed in ${data.processing_time_seconds}s`); setIsLoading(false); }
      else { setStatus(data.error || 'Comparison failed.'); setIsLoading(false); }
    } catch { clearInterval(prog); setStatus('Network error.'); setDiffResult(null); setIsLoading(false); }
  };

  const pollComparisonStatus = (id) => {
    pollingTimerRef.current = setInterval(async () => {
      try {
        const res = await api.getComparisonStatus(id);
        if (!res.ok) { clearInterval(pollingTimerRef.current); setIsLoading(false); setStatus('Failed to fetch status'); return; }
        const job = res.data;
        if (job.progress) setStatus(`Processing... ${job.progress}%`);
        if (job.status === 'completed') {
          clearInterval(pollingTimerRef.current);
          setDiffResult(job.result?.diff);
          setStatus(`Comparison completed in ${(job.result?.processing_time_seconds || 0).toFixed(2)}s`);
          setIsLoading(false);
        } else if (job.status === 'failed') {
          clearInterval(pollingTimerRef.current); setIsLoading(false); setStatus(job.error || 'Failed');
        }
      } catch { clearInterval(pollingTimerRef.current); setIsLoading(false); setStatus('Polling error'); }
    }, 1500);
  };

  const getStatusIcon = (s) => ({ added:'fa-plus', removed:'fa-minus', modified:'fa-pen' }[s] || 'fa-equals');

  const filteredLines = diffResult?.lines?.filter(l => showOnlyChanges ? l.status !== 'equal' : true) || [];
  const totalPages = Math.ceil(filteredLines.length / itemsPerPage);
  const currentLines = filteredLines.slice((currentPage - 1) * itemsPerPage, currentPage * itemsPerPage);

  const handlePageChange = (p) => { if (p >= 1 && p <= totalPages) { setCurrentPage(p); setPageInput(p.toString()); } };

  const lineColor = { added: 'bg-green-50 border-l-2 border-green-400', removed: 'bg-red-50 border-l-2 border-red-400', modified: 'bg-yellow-50 border-l-2 border-yellow-400', equal: 'border-l-2 border-transparent' };

  return (
    <div className="min-h-screen bg-[var(--color-bg-secondary)] text-[var(--color-text-primary)]">
      <Navigation />

      <div className="max-w-5xl mx-auto px-4 py-8">
        {/* Header */}
        <div className="text-center mb-8">
          <span className="inline-flex items-center gap-2 px-3 py-1 rounded-full bg-primary-light text-primary text-sm font-medium mb-3">
            <i className="fa-solid fa-code-compare"></i> Document Analysis
          </span>
          <h1 className="text-3xl font-bold text-[var(--color-text-primary)] mb-2">Compare Documents</h1>
          <p className="text-[var(--color-text-secondary)]">Upload two versions of the same document to see what changed</p>
        </div>

        {/* Upload Cards */}
        <div className="flex flex-col sm:flex-row gap-4 items-stretch mb-6">
          {/* Old Version */}
          <div className="flex-1 bg-[var(--color-bg-primary)] rounded-xl border border-[var(--color-border)] p-6 flex flex-col items-center gap-3 text-center shadow-sm">
            <div className="w-12 h-12 rounded-xl bg-red-100 text-red-500 flex items-center justify-center text-xl">
              <i className="fa-solid fa-file-circle-minus"></i>
            </div>
            <h3 className="font-semibold text-[var(--color-text-primary)]">Old Version</h3>
            <p className="text-sm text-[var(--color-text-secondary)]">The original document</p>
            <input type="file" id="oldFile" accept=".pdf,.docx,.xlsx" onChange={e => setOldFile(e.target.files[0])} className="hidden" />
            <button className="px-4 py-2 rounded-lg bg-[var(--color-bg-tertiary)] hover:bg-[var(--color-bg-hover)] text-sm font-medium transition-colors" onClick={() => document.getElementById('oldFile').click()}>
              <i className="fa-solid fa-cloud-arrow-up mr-1"></i>Choose File
            </button>
            {oldFile && <div className="text-xs text-[var(--color-text-secondary)] flex items-center gap-1"><i className="fa-solid fa-file"></i>{oldFile.name}</div>}
          </div>

          <div className="flex items-center justify-center text-2xl text-[var(--color-text-muted)]">
            <i className="fa-solid fa-arrows-left-right"></i>
          </div>

          {/* New Version */}
          <div className="flex-1 bg-[var(--color-bg-primary)] rounded-xl border border-[var(--color-border)] p-6 flex flex-col items-center gap-3 text-center shadow-sm">
            <div className="w-12 h-12 rounded-xl bg-green-100 text-green-500 flex items-center justify-center text-xl">
              <i className="fa-solid fa-file-circle-plus"></i>
            </div>
            <h3 className="font-semibold text-[var(--color-text-primary)]">New Version</h3>
            <p className="text-sm text-[var(--color-text-secondary)]">The updated document</p>
            <input type="file" id="newFile" accept=".pdf,.docx,.xlsx" onChange={e => setNewFile(e.target.files[0])} className="hidden" />
            <button className="px-4 py-2 rounded-lg bg-[var(--color-bg-tertiary)] hover:bg-[var(--color-bg-hover)] text-sm font-medium transition-colors" onClick={() => document.getElementById('newFile').click()}>
              <i className="fa-solid fa-cloud-arrow-up mr-1"></i>Choose File
            </button>
            {newFile && <div className="text-xs text-[var(--color-text-secondary)] flex items-center gap-1"><i className="fa-solid fa-file"></i>{newFile.name}</div>}
          </div>
        </div>

        {/* Supported formats */}
        <div className="flex items-center justify-center gap-2 mb-6 text-sm text-[var(--color-text-muted)]">
          <span>Supported:</span>
          {['fa-file-pdf PDF','fa-file-word DOCX','fa-file-excel XLSX'].map(f => {
            const [icon, label] = f.split(' ');
            return <span key={label} className="px-2 py-0.5 rounded-full bg-[var(--color-bg-tertiary)] text-xs"><i className={`fa-solid ${icon} mr-1`}></i>{label}</span>;
          })}
        </div>

        {/* Compare button */}
        <div className="flex justify-center mb-6">
          <button
            className="px-8 py-3 rounded-xl bg-primary text-white font-semibold hover:bg-primary-hover disabled:opacity-50 disabled:cursor-not-allowed transition-colors flex items-center gap-2"
            onClick={handleCompare}
            disabled={!validateFiles() || isLoading}
          >
            {isLoading
              ? <><i className="fa-solid fa-spinner fa-spin"></i>Analyzing Documents...</>
              : <><i className="fa-solid fa-magnifying-glass-chart"></i>Generate Comparison</>}
          </button>
        </div>

        {/* Status */}
        {status && (
          <div className={`flex items-center gap-2 px-4 py-3 rounded-lg mb-4 text-sm ${status.includes('completed') ? 'bg-green-50 text-green-700' : 'bg-[var(--color-bg-tertiary)] text-[var(--color-text-secondary)]'}`}>
            <i className={`fa-solid ${status.includes('completed') ? 'fa-circle-check' : status.includes('Processing') || status.includes('Uploading') ? 'fa-spinner fa-spin' : 'fa-circle-info'}`}></i>
            {status}
          </div>
        )}

        {/* Progress bar */}
        {isLoading && uploadProgress > 0 && uploadProgress < 100 && (
          <div className="flex items-center gap-3 mb-4">
            <div className="flex-1 h-2 bg-[var(--color-bg-tertiary)] rounded-full overflow-hidden">
              <div className="h-full bg-primary rounded-full transition-all" style={{ width: `${uploadProgress}%` }}></div>
            </div>
            <span className="text-xs text-[var(--color-text-muted)] w-8">{uploadProgress}%</span>
          </div>
        )}

        {/* Results */}
        {diffResult && (
          <div className="bg-[var(--color-bg-primary)] rounded-xl border border-[var(--color-border)] shadow-sm overflow-hidden">
            <div className="flex items-center justify-between px-4 py-3 border-b border-[var(--color-border)]">
              <div className="flex items-center gap-2 font-semibold text-[var(--color-text-primary)]">
                <i className="fa-solid fa-rectangle-list text-primary"></i>
                Line-by-Line Comparison
              </div>
              <label className="flex items-center gap-2 text-sm text-[var(--color-text-secondary)] cursor-pointer">
                <input type="checkbox" checked={showOnlyChanges} onChange={e => setShowOnlyChanges(e.target.checked)} className="rounded" />
                Show only changes
              </label>
            </div>

            {/* Stats */}
            <div className="grid grid-cols-2 sm:grid-cols-5 divide-x divide-[var(--color-border)] border-b border-[var(--color-border)] text-center text-sm">
              {[
                { label:'Unchanged', val: diffResult.stats?.equal||0, icon:'fa-equals', cls:'text-[var(--color-text-muted)]' },
                { label:'Added',     val: diffResult.stats?.added||0, icon:'fa-plus',   cls:'text-green-600' },
                { label:'Modified',  val: diffResult.stats?.modified||0, icon:'fa-pen', cls:'text-yellow-600' },
                { label:'Removed',   val: diffResult.stats?.removed||0, icon:'fa-minus', cls:'text-red-600' },
                { label:'Total',     val: diffResult.total_lines||0, icon:'fa-list-ol', cls:'text-primary' },
              ].map(s => (
                <div key={s.label} className="py-3 px-2">
                  <div className={`text-lg font-bold ${s.cls}`}>{s.val}</div>
                  <div className="text-xs text-[var(--color-text-muted)]">{s.label}</div>
                </div>
              ))}
            </div>

            {/* Pagination */}
            {totalPages > 1 && (
              <div className="flex items-center justify-between px-4 py-2 border-b border-[var(--color-border)] text-sm">
                <button className="px-3 py-1 rounded-lg bg-[var(--color-bg-tertiary)] hover:bg-[var(--color-bg-hover)] disabled:opacity-40 transition-colors flex items-center gap-1" onClick={() => handlePageChange(currentPage-1)} disabled={currentPage===1}>
                  <i className="fa-solid fa-chevron-left"></i>Previous
                </button>
                <div className="flex items-center gap-1 text-[var(--color-text-secondary)]">
                  <span>Page</span>
                  <input className="w-10 text-center border border-[var(--color-border)] rounded px-1 py-0.5" value={pageInput} onChange={e=>setPageInput(e.target.value)} onKeyDown={e=>e.key==='Enter'&&handlePageChange(parseInt(pageInput))} onBlur={()=>handlePageChange(parseInt(pageInput))} />
                  <span>of {totalPages}</span>
                  <span className="text-[var(--color-text-muted)]">({filteredLines.length} lines)</span>
                </div>
                <button className="px-3 py-1 rounded-lg bg-[var(--color-bg-tertiary)] hover:bg-[var(--color-bg-hover)] disabled:opacity-40 transition-colors flex items-center gap-1" onClick={() => handlePageChange(currentPage+1)} disabled={currentPage===totalPages}>
                  Next<i className="fa-solid fa-chevron-right"></i>
                </button>
              </div>
            )}

            {/* Diff lines */}
            <div className="divide-y divide-[var(--color-border)] font-mono text-xs max-h-[600px] overflow-y-auto">
              {currentLines.length > 0 ? currentLines.map((line, idx) => (
                <div key={idx} className={`flex items-start gap-2 px-3 py-1.5 ${lineColor[line.status] || ''}`}>
                  <span className="w-8 shrink-0 text-right text-[var(--color-text-muted)] select-none">{line.line}</span>
                  <span className="w-4 shrink-0 text-center"><i className={`fa-solid ${getStatusIcon(line.status)}`}></i></span>
                  <span className="flex-1 break-all">
                    {line.status === 'modified' ? (
                      <span className="flex flex-wrap items-center gap-1">
                        <span className="text-red-600 line-through">{line.old_text}</span>
                        <i className="fa-solid fa-arrow-right text-[var(--color-text-muted)]"></i>
                        <span className="text-green-600">{line.new_text}</span>
                      </span>
                    ) : <span>{line.text}</span>}
                  </span>
                </div>
              )) : (
                <div className="flex items-center justify-center gap-2 py-8 text-[var(--color-text-muted)]">
                  <i className="fa-solid fa-check-circle text-green-500"></i>
                  {showOnlyChanges ? 'No changes to display.' : 'No differences found.'}
                </div>
              )}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

export default Compare;
