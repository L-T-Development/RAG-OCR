import { useState, useEffect, useRef } from 'react';
import { Navigation } from '../components/shared/Navigation';
import { api } from '../services/api';

function Reports() {
  const [comparisonMode, setComparisonMode] = useState('multi');
  const [sourceFile, setSourceFile] = useState(null);
  const [sourceFileId, setSourceFileId] = useState(null);
  const [columns, setColumns] = useState([]);
  const [columnPreview, setColumnPreview] = useState(null);
  const [selectedColumn, setSelectedColumn] = useState('');
  const [loadingColumns, setLoadingColumns] = useState(false);
  const [loadingPreview, setLoadingPreview] = useState(false);
  const [showPreview, setShowPreview] = useState(false);
  const [pdfFiles, setPdfFiles] = useState([]);
  const [singlePdfFile, setSinglePdfFile] = useState(null);
  const [jobId, setJobId] = useState(null);
  const [jobStatus, setJobStatus] = useState(null);
  const [progress, setProgress] = useState(0);
  const [progressMessage, setProgressMessage] = useState('');
  const [progressLogs, setProgressLogs] = useState([]);
  const [isProcessing, setIsProcessing] = useState(false);
  const [result, setResult] = useState(null);
  const [error, setError] = useState('');
  const [activeTab, setActiveTab] = useState('found');
  const [searchTerm, setSearchTerm] = useState('');
  const pollingRef = useRef(null);

  useEffect(() => () => { if (pollingRef.current) clearInterval(pollingRef.current); }, []);

  const handleSourceFileChange = async (e) => {
    const file = e.target.files[0];
    if (!file) return;
    setSourceFile(file); setSourceFileId(null); setColumns([]); setColumnPreview(null);
    setSelectedColumn(''); setError(''); setLoadingColumns(true); setShowPreview(false);
    try {
      const { ok, data } = await api.getColumnsFromFile(file);
      if (ok && data.columns) { setColumns(data.columns); setSourceFileId(data.file_id); }
      else setError(data.error || 'Failed to extract columns');
    } catch { setError('Network error'); }
    finally { setLoadingColumns(false); }
  };

  const fetchColumnPreview = async (col) => {
    if (!sourceFileId) { setError('Please re-upload the source file'); return; }
    setLoadingPreview(true); setColumnPreview(null); setSelectedColumn(col); setShowPreview(true);
    try {
      const { ok, data } = await api.getColumnPreview(sourceFileId, col);
      if (ok) setColumnPreview(data); else setError(data.error || 'Failed to load preview');
    } catch { setError('Failed to load preview'); }
    finally { setLoadingPreview(false); }
  };

  const pollJobStatus = (id) => {
    pollingRef.current = setInterval(async () => {
      try {
        const { ok, data } = await api.getReportStatus(id);
        if (!ok) { clearInterval(pollingRef.current); setError('Failed to fetch status'); setIsProcessing(false); return; }
        setJobStatus(data.status); setProgress(data.progress || 0); setProgressMessage(data.progress_message || '');
        if (data.logs?.length > 0) setProgressLogs(data.logs);
        if (data.status === 'completed') { clearInterval(pollingRef.current); setResult(data.result); setIsProcessing(false); }
        else if (data.status === 'failed') { clearInterval(pollingRef.current); setError(data.error || 'Failed'); setIsProcessing(false); }
      } catch { clearInterval(pollingRef.current); setError('Polling error'); setIsProcessing(false); }
    }, 60000);
  };

  const handleStartComparison = async () => {
    if (!sourceFile || !selectedColumn) { setError('Please select a source file and column'); return; }
    setError(''); setResult(null); setIsProcessing(true); setProgress(0);
    setProgressMessage('Starting...'); setProgressLogs([]); setJobStatus('pending');
    try {
      const fn = comparisonMode === 'single'
        ? () => api.startSinglePdfComparison(sourceFile, selectedColumn, singlePdfFile, false)
        : () => api.startMultiPdfComparison(sourceFile, selectedColumn, pdfFiles, false);
      const { ok, data } = await fn();
      if (ok && data.job_id) { setJobId(data.job_id); pollJobStatus(data.job_id); }
      else { setError(data.error || 'Failed to start'); setIsProcessing(false); }
    } catch { setError('Network error'); setIsProcessing(false); }
  };

  const handleReset = () => {
    setSourceFile(null); setSourceFileId(null); setColumns([]); setColumnPreview(null);
    setSelectedColumn(''); setPdfFiles([]); setSinglePdfFile(null); setResult(null);
    setError(''); setJobId(null); setJobStatus(null); setProgress(0);
    setProgressMessage(''); setProgressLogs([]); setShowPreview(false);
  };

  const foundData = result?.all_found || result?.found || {};
  const filteredFound = Object.entries(foundData).filter(([k]) => k.toLowerCase().includes(searchTerm.toLowerCase()));
  const filteredNotFound = (result?.not_found || []).filter(i => i.toLowerCase().includes(searchTerm.toLowerCase()));

  const btnBase = 'px-3 py-2 rounded-lg text-sm font-medium transition-colors flex items-center gap-2';
  const uploadBtn = `${btnBase} bg-primary text-white hover:bg-primary-hover disabled:opacity-50 disabled:cursor-not-allowed`;
  const cardCls = 'bg-[var(--color-bg-primary)] rounded-xl border border-[var(--color-border)] p-4 shadow-sm';

  return (
    <div className="min-h-screen bg-[var(--color-bg-secondary)] text-[var(--color-text-primary)]">
      <Navigation />

      <div className="max-w-6xl mx-auto px-4 pt-20 pb-6">
        {/* Header */}
        <div className="text-center mb-6">
          <span className="inline-flex items-center gap-2 px-3 py-1 rounded-full bg-purple-100 text-purple-700 text-sm font-medium mb-3">
            <i className="fa-solid fa-chart-bar"></i> PDF Comparator
          </span>
          <h1 className="text-3xl font-bold mb-2">Reports & Analysis</h1>
          <p className="text-[var(--color-text-secondary)] mb-4">Compare values from Excel/PDF against PDF documents</p>
          {/* Mode toggle */}
          <div className="inline-flex rounded-lg border border-[var(--color-border)] overflow-hidden">
            {['single','multi'].map(m => (
              <button key={m} className={`px-5 py-2 text-sm font-medium transition-colors flex items-center gap-2 ${comparisonMode===m?'bg-primary text-white':'bg-[var(--color-bg-primary)] text-[var(--color-text-secondary)] hover:bg-[var(--color-bg-hover)]'}`} onClick={() => setComparisonMode(m)} disabled={isProcessing}>
                <i className={`fa-solid ${m==='single'?'fa-file-pdf':'fa-copy'}`}></i>
                {m==='single'?'Single PDF':'Multi-PDF'}
              </button>
            ))}
          </div>
        </div>

        <div className="grid grid-cols-1 lg:grid-cols-[340px_1fr] gap-6">
          {/* LEFT – Config */}
          <div className="flex flex-col gap-4">
            {/* Source file */}
            <div className={cardCls}>
              <h3 className="font-semibold mb-1 flex items-center gap-2"><i className="fa-solid fa-file-excel text-green-600"></i>Source File</h3>
              <p className="text-xs text-[var(--color-text-muted)] mb-3">Upload Excel, PDF, or Image with values to search</p>
              <input type="file" id="sourceFile" accept=".xlsx,.xls,.pdf,.png,.jpg,.jpeg" onChange={handleSourceFileChange} className="hidden" />
              <button className={uploadBtn} onClick={() => document.getElementById('sourceFile').click()} disabled={isProcessing}>
                <i className="fa-solid fa-cloud-arrow-up"></i>{sourceFile ? 'Change File' : 'Select File'}
              </button>
              {sourceFile && <div className="mt-2 text-xs text-[var(--color-text-secondary)] flex items-center gap-1"><i className="fa-solid fa-file"></i>{sourceFile.name}</div>}
              {loadingColumns && <div className="mt-2 text-xs text-[var(--color-text-muted)] flex items-center gap-2"><i className="fa-solid fa-spinner fa-spin"></i>Extracting columns...</div>}

              {/* Column list */}
              {columns.length > 0 && !selectedColumn && (
                <div className="mt-3">
                  <p className="text-xs font-medium text-[var(--color-text-secondary)] mb-2">Available Columns (click to preview):</p>
                  <div className="flex flex-col gap-1 max-h-48 overflow-y-auto">
                    {columns.map((col, idx) => (
                      <button key={idx} className="flex items-center justify-between px-3 py-2 rounded-lg text-sm bg-[var(--color-bg-secondary)] hover:bg-[var(--color-bg-hover)] text-left transition-colors disabled:opacity-50" onClick={() => fetchColumnPreview(col)} disabled={isProcessing||loadingPreview}>
                        <span className="flex items-center gap-2"><i className="fa-solid fa-table-columns text-primary"></i>{col}</span>
                        <i className="fa-solid fa-chevron-right text-[var(--color-text-muted)]"></i>
                      </button>
                    ))}
                  </div>
                </div>
              )}

              {/* Preview panel */}
              {selectedColumn && showPreview && (
                <div className="mt-3 rounded-lg bg-[var(--color-bg-secondary)] border border-[var(--color-border)] overflow-hidden">
                  <div className="flex items-center justify-between px-3 py-2 border-b border-[var(--color-border)]">
                    <button className="text-xs text-primary hover:underline flex items-center gap-1" onClick={() => { setSelectedColumn(''); setShowPreview(false); setColumnPreview(null); }} disabled={isProcessing}>
                      <i className="fa-solid fa-arrow-left"></i>Back
                    </button>
                    <span className="text-xs font-medium text-[var(--color-text-primary)]">{selectedColumn}</span>
                    {columnPreview?.total_count > 0 && <span className="text-xs text-[var(--color-text-muted)]">{columnPreview.total_count} values</span>}
                  </div>
                  <div className="p-3">
                    {loadingPreview ? <div className="text-xs text-center text-[var(--color-text-muted)] py-2"><i className="fa-solid fa-spinner fa-spin mr-1"></i>Loading...</div> : (
                      <>
                        <p className="text-xs text-[var(--color-text-muted)] mb-2"><i className="fa-solid fa-eye mr-1"></i>Sample values:</p>
                        <div className="grid grid-cols-2 gap-1">
                          {columnPreview?.preview?.map((v, i) => (
                            <div key={i} className="flex items-center gap-1 text-xs bg-[var(--color-bg-primary)] rounded px-2 py-1">
                              <span className="text-[var(--color-text-muted)] w-4 shrink-0">{i+1}.</span>
                              <span className="truncate text-[var(--color-text-secondary)]">{v}</span>
                            </div>
                          )) || <p className="text-xs text-[var(--color-text-muted)]">No preview available</p>}
                        </div>
                      </>
                    )}
                  </div>
                  <div className="px-3 pb-3">
                    <button className={`${uploadBtn} w-full justify-center`} onClick={() => setShowPreview(false)} disabled={isProcessing||loadingPreview}>
                      <i className="fa-solid fa-check"></i>Use This Column{columnPreview?.total_count > 0 && ` (${columnPreview.total_count} values)`}
                    </button>
                  </div>
                </div>
              )}

              {selectedColumn && !showPreview && (
                <div className="mt-2 flex items-center gap-2 px-3 py-2 rounded-lg bg-green-50 border border-green-200 text-sm">
                  <i className="fa-solid fa-check-circle text-green-600"></i>
                  <span className="flex-1 font-medium text-green-800 truncate">{selectedColumn}</span>
                  <button className="text-xs text-primary hover:underline" onClick={() => setSelectedColumn('')} disabled={isProcessing}>Change</button>
                </div>
              )}
            </div>

            {/* PDF target */}
            <div className={cardCls}>
              <h3 className="font-semibold mb-1 flex items-center gap-2"><i className="fa-solid fa-file-pdf text-red-500"></i>{comparisonMode==='single'?'Target PDF':'Target PDFs'}</h3>
              <p className="text-xs text-[var(--color-text-muted)] mb-3">{comparisonMode==='single'?'Upload a single PDF to search in':'Upload multiple PDFs to search in'}</p>

              {comparisonMode==='single' ? (
                <>
                  <input type="file" id="singlePdf" accept=".pdf" onChange={e => setSinglePdfFile(e.target.files[0])} className="hidden" />
                  <button className={uploadBtn} onClick={() => document.getElementById('singlePdf').click()} disabled={isProcessing}>
                    <i className="fa-solid fa-cloud-arrow-up"></i>{singlePdfFile?'Change PDF':'Select PDF'}
                  </button>
                  {singlePdfFile && (
                    <div className="mt-2 flex items-center gap-2 text-xs text-[var(--color-text-secondary)]">
                      <i className="fa-solid fa-file-pdf text-red-400"></i>
                      <span className="flex-1 truncate">{singlePdfFile.name}</span>
                      <button className="text-[var(--color-text-muted)] hover:text-error" onClick={() => setSinglePdfFile(null)} disabled={isProcessing}><i className="fa-solid fa-times"></i></button>
                    </div>
                  )}
                </>
              ) : (
                <>
                  <input type="file" id="pdfFiles" accept=".pdf" multiple onChange={e => setPdfFiles(p => [...p, ...Array.from(e.target.files)])} className="hidden" />
                  <button className={uploadBtn} onClick={() => document.getElementById('pdfFiles').click()} disabled={isProcessing}>
                    <i className="fa-solid fa-plus"></i>Add PDF Files
                  </button>
                  {pdfFiles.length > 0 && (
                    <div className="mt-2 flex flex-col gap-1 max-h-40 overflow-y-auto">
                      {pdfFiles.map((f, i) => (
                        <div key={i} className="flex items-center gap-2 text-xs text-[var(--color-text-secondary)]">
                          <i className="fa-solid fa-file-pdf text-red-400"></i>
                          <span className="flex-1 truncate">{f.name}</span>
                          <button className="text-[var(--color-text-muted)] hover:text-error" onClick={() => setPdfFiles(p => p.filter((_,j) => j!==i))} disabled={isProcessing}><i className="fa-solid fa-times"></i></button>
                        </div>
                      ))}
                    </div>
                  )}
                </>
              )}
            </div>

            {/* Actions */}
            <div className="flex gap-2">
              <button
                className={`flex-1 py-2.5 rounded-xl font-semibold text-sm transition-colors flex items-center justify-center gap-2 ${isProcessing||!sourceFile||!selectedColumn||(comparisonMode==='single'?!singlePdfFile:pdfFiles.length===0)?'bg-[var(--color-bg-tertiary)] text-[var(--color-text-muted)] cursor-not-allowed':'bg-primary text-white hover:bg-primary-hover'}`}
                onClick={handleStartComparison}
                disabled={isProcessing||!sourceFile||!selectedColumn||(comparisonMode==='single'?!singlePdfFile:pdfFiles.length===0)}
              >
                {isProcessing ? <><i className="fa-solid fa-spinner fa-spin"></i>Processing...</> : <><i className="fa-solid fa-play"></i>Start Comparison</>}
              </button>
              <button className="px-4 py-2.5 rounded-xl border border-[var(--color-border)] text-sm hover:bg-[var(--color-bg-hover)] transition-colors flex items-center gap-1.5" onClick={handleReset} disabled={isProcessing}>
                <i className="fa-solid fa-rotate-left"></i>Reset
              </button>
            </div>

            {error && <div className="flex items-start gap-2 px-3 py-2 rounded-lg bg-red-50 border border-red-200 text-red-700 text-sm"><i className="fa-solid fa-circle-exclamation mt-0.5 shrink-0"></i><span>{error}</span></div>}

            {isProcessing && (
              <div className={cardCls}>
                <div className="flex justify-between text-sm mb-1">
                  <span className="text-[var(--color-text-secondary)]">{jobStatus==='pending'?'Starting...':'Processing'}</span>
                  <span className="font-medium text-primary">{progress}%</span>
                </div>
                <div className="h-2 bg-[var(--color-bg-tertiary)] rounded-full overflow-hidden mb-2">
                  <div className="h-full bg-primary rounded-full transition-all" style={{ width:`${progress}%` }}></div>
                </div>
                <p className="text-xs text-[var(--color-text-muted)]">{progressMessage}</p>
                {progressLogs.length > 0 && (
                  <div className="mt-3 bg-gray-900 rounded-lg p-3 max-h-32 overflow-y-auto">
                    <p className="text-xs text-gray-400 mb-1 flex items-center gap-1"><i className="fa-solid fa-terminal"></i>Log</p>
                    {progressLogs.slice(-10).map((log, i) => <div key={i} className="text-xs text-green-400 font-mono">{log}</div>)}
                  </div>
                )}
              </div>
            )}
          </div>

          {/* RIGHT – Results */}
          <div>
            {!result && !isProcessing && (
              <div className="flex flex-col items-center justify-center h-64 text-[var(--color-text-muted)]">
                <i className="fa-solid fa-chart-pie text-5xl mb-4 opacity-20"></i>
                <h3 className="font-semibold text-[var(--color-text-primary)] mb-1">No Results Yet</h3>
                <p className="text-sm">Configure your comparison and click "Start Comparison"</p>
              </div>
            )}

            {result && (
              <div className="flex flex-col gap-4">
                {/* Summary cards */}
                <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
                  {[
                    { label:'Total Values',  val: result.total_values||0, icon:'fa-list', cls:'text-primary bg-primary-light' },
                    { label:'Found',         val: result.found_count ?? Object.keys(foundData).length, icon:'fa-check', cls:'text-green-700 bg-green-50' },
                    { label:'Not Found',     val: result.not_found_count ?? (result.not_found?.length||0), icon:'fa-times', cls:'text-red-700 bg-red-50' },
                    { label:'Match Rate',    val: `${result.match_percentage ?? (result.total_values>0?Math.round(Object.keys(foundData).length/result.total_values*100):0)}%`, icon:'fa-percent', cls:'text-purple-700 bg-purple-50' },
                  ].map(s => (
                    <div key={s.label} className={`rounded-xl p-4 flex items-center gap-3 ${s.cls}`}>
                      <i className={`fa-solid ${s.icon} text-xl opacity-80`}></i>
                      <div>
                        <div className="text-xl font-bold">{s.val}</div>
                        <div className="text-xs opacity-70">{s.label}</div>
                      </div>
                    </div>
                  ))}
                </div>

                {/* Download */}
                {jobId && (
                  <a href={api.getReportDownloadUrl(jobId)} className="inline-flex items-center gap-2 px-4 py-2 rounded-lg bg-green-600 text-white text-sm font-medium hover:bg-green-700 transition-colors w-fit" download>
                    <i className="fa-solid fa-download"></i>Download Excel Report
                  </a>
                )}

                {/* Search + tabs */}
                <div className="flex flex-col sm:flex-row gap-3">
                  <div className="flex items-center gap-2 px-3 py-2 rounded-lg border border-[var(--color-border)] bg-[var(--color-bg-primary)] flex-1">
                    <i className="fa-solid fa-search text-[var(--color-text-muted)]"></i>
                    <input className="flex-1 bg-transparent text-sm outline-none text-[var(--color-text-primary)]" placeholder="Search values..." value={searchTerm} onChange={e => setSearchTerm(e.target.value)} />
                  </div>
                  <div className="flex rounded-lg border border-[var(--color-border)] overflow-hidden">
                    {[['found','fa-check-circle',`Found (${Object.keys(foundData).length})`],['not-found','fa-times-circle',`Not Found (${result.not_found?.length||0})`]].map(([id,icon,label]) => (
                      <button key={id} className={`px-4 py-2 text-sm font-medium flex items-center gap-1.5 transition-colors ${activeTab===id?'bg-primary text-white':'bg-[var(--color-bg-primary)] text-[var(--color-text-secondary)] hover:bg-[var(--color-bg-hover)]'}`} onClick={() => setActiveTab(id)}>
                        <i className={`fa-solid ${icon}`}></i>{label}
                      </button>
                    ))}
                  </div>
                </div>

                {/* Results list */}
                <div className="bg-[var(--color-bg-primary)] rounded-xl border border-[var(--color-border)] divide-y divide-[var(--color-border)] max-h-[600px] overflow-y-auto shadow-sm">
                  {activeTab === 'found' && (
                    filteredFound.length === 0
                      ? <div className="py-8 text-center text-[var(--color-text-muted)] text-sm">No matching found values</div>
                      : filteredFound.map(([value, locs], idx) => (
                        <div key={idx} className="flex flex-col gap-1 px-4 py-3">
                          <div className="flex items-center gap-2 text-sm font-medium text-green-700"><i className="fa-solid fa-check"></i>{value}</div>
                          <div className="flex flex-wrap gap-1 ml-5">
                            {Array.isArray(locs)
                              ? locs.map((p,i) => <span key={i} className="text-xs px-2 py-0.5 rounded-full bg-green-50 text-green-700">{p}</span>)
                              : Object.entries(locs).map(([pdf,pages],i) => (
                                <div key={i} className="text-xs text-[var(--color-text-secondary)]">
                                  <span className="font-medium">{pdf}:</span> {Array.isArray(pages)?pages.map(p=>typeof p==='number'?`Page ${p}`:p).join(', '):pages}
                                </div>
                              ))}
                          </div>
                        </div>
                      ))
                  )}
                  {activeTab === 'not-found' && (
                    filteredNotFound.length === 0
                      ? <div className="py-8 text-center text-[var(--color-text-muted)] text-sm">No matching not-found values</div>
                      : filteredNotFound.map((v, idx) => (
                        <div key={idx} className="flex items-center gap-2 px-4 py-3 text-sm text-red-700">
                          <i className="fa-solid fa-times"></i>{v}
                        </div>
                      ))
                  )}
                </div>
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}

export default Reports;
