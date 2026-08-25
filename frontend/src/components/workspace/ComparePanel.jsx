import { useState, useEffect, useCallback } from 'react';
import { api } from '../../services/api';
import './ComparePanel.css';

/**
 * Compare documents in this thread — without having to phrase a question.
 *
 * Three steps, in the order the decisions actually happen:
 *   1. which documents (the first one picked is the source)
 *   2. what to compare, and — the part that used to be invisible — WHICH REAL COLUMN
 *      that resolves to in each document, editable before anything runs
 *   3. the result, grouped by what needs a decision
 *
 * Step 2 is the point of the whole panel. The engine has always resolved a concept
 * like "part no" to a different real header per document; until now you could only
 * discover its choice by reading the answer. Here you see it first, and change it.
 */

const CONCEPTS = [
  { key: 'part', label: 'Part number' },
  { key: 'drg', label: 'Drawing number' },
  { key: 'nsn', label: 'Stock number (NSN)' },
  { key: 'nomenclature', label: 'Description' },
  { key: 'qty', label: 'Quantity' },
];

// Concept key as typed by a user → canonical field key used by the columns API.
const FIELD_OF = {
  part: 'part_no', drg: 'drawing_no', nsn: 'nsn',
  nomenclature: 'nomenclature', qty: 'qty',
};

export function ComparePanel({ threadId, documents = [], onClose }) {
  const [selected, setSelected] = useState([]);
  const [concept, setConcept] = useState('part');
  const [mode, setMode] = useState('columns');
  const [columnInfo, setColumnInfo] = useState({});   // docId → /columns/ payload
  const [loadingColumns, setLoadingColumns] = useState(false);
  const [running, setRunning] = useState(false);
  const [result, setResult] = useState(null);
  const [error, setError] = useState('');
  const [tab, setTab] = useState('missing');

  // `name` is what the files endpoint has always returned; `filename` is the
  // newer key. Accept either so the panel does not silently list blank rows.
  const nameOfDoc = (d) => d?.filename || d?.name || '';
  const ready = documents.filter(d => (d.status ?? 'done') === 'done');
  const field = FIELD_OF[concept] || 'part_no';

  const toggle = (id) => {
    setResult(null);
    setSelected(prev => prev.includes(id) ? prev.filter(x => x !== id) : [...prev, id]);
  };

  // Load how each chosen document understands its columns.
  const loadColumns = useCallback(async () => {
    if (selected.length === 0) return;
    setLoadingColumns(true);
    const next = {};
    await Promise.all(selected.map(async (id) => {
      const { ok, data } = await api.getDocumentColumns(id);
      if (ok) next[id] = data;
    }));
    setColumnInfo(next);
    setLoadingColumns(false);
  }, [selected]);

  useEffect(() => { loadColumns(); }, [loadColumns]);

  const pinColumn = async (docId, header) => {
    const { ok, data } = await api.setDocumentColumn(docId, field, header || null);
    if (!ok) { setError(data?.error || 'Could not set that column'); return; }
    setError('');
    setResult(null);
    loadColumns();
  };

  const run = async () => {
    setRunning(true);
    setError('');
    setResult(null);
    const { ok, data } = await api.runComparison({
      threadId, docIds: selected, column: concept, mode,
    });
    setRunning(false);
    if (!ok) { setError(data?.error || 'Comparison failed'); return; }
    setResult(data);
    setTab(data.summary?.kind === 'pairwise' ? 'missing' : 'missing');
  };

  const nameOf = (id) => nameOfDoc(ready.find(d => d.id === id)) || id;

  return (
    <div className="cmp-backdrop" onClick={onClose}>
      <div className="cmp-panel" onClick={e => e.stopPropagation()}>
        <header className="cmp-header">
          <div>
            <h2>Compare documents</h2>
            <p>Same engine as the chat — this just shows you what it decided before it runs.</p>
          </div>
          <button className="cmp-close" onClick={onClose} aria-label="Close">×</button>
        </header>

        <div className="cmp-body">
          {/* ── 1. Documents ─────────────────────────────────────────── */}
          <section className="cmp-step">
            <h3><span className="cmp-num">1</span> Pick documents</h3>
            {ready.length < 2 ? (
              <p className="cmp-empty">
                Upload at least two documents to this thread first.
              </p>
            ) : (
              <>
                <ul className="cmp-docs">
                  {ready.map(doc => (
                    <li key={doc.id}>
                      <label>
                        <input
                          type="checkbox"
                          checked={selected.includes(doc.id)}
                          onChange={() => toggle(doc.id)}
                        />
                        <span className="cmp-doc-name">{nameOfDoc(doc)}</span>
                        <span className="cmp-badge">{doc.category || 'other'}</span>
                        {selected[0] === doc.id && (
                          <span className="cmp-badge cmp-badge-src">source</span>
                        )}
                      </label>
                    </li>
                  ))}
                </ul>
                {selected.length >= 2 && (
                  <p className="cmp-hint">
                    Comparing <strong>{nameOf(selected[0])}</strong> against{' '}
                    {selected.length === 2
                      ? <strong>{nameOf(selected[1])}</strong>
                      : <strong>{selected.length - 1} other documents</strong>}.
                  </p>
                )}
              </>
            )}
          </section>

          {/* ── 2. What, and which real column ───────────────────────── */}
          {selected.length >= 2 && (
            <section className="cmp-step">
              <h3><span className="cmp-num">2</span> What to compare</h3>

              <div className="cmp-controls">
                <label>
                  Concept
                  <select value={concept} onChange={e => { setConcept(e.target.value); setResult(null); }}>
                    {CONCEPTS.map(c => <option key={c.key} value={c.key}>{c.label}</option>)}
                  </select>
                </label>
                <label>
                  Compare against
                  <select value={mode} onChange={e => { setMode(e.target.value); setResult(null); }}>
                    <option value="columns">The same column in each document</option>
                    <option value="mentions">Anywhere in the text (for manuals)</option>
                  </select>
                </label>
              </div>

              {mode === 'columns' && (
                <div className="cmp-cols">
                  <p className="cmp-hint">
                    This is the column each document will actually be read from. Change it
                    if it is wrong — the choice is remembered for that document.
                  </p>
                  {loadingColumns && <p className="cmp-empty">Reading columns…</p>}
                  {!loadingColumns && selected.map(id => {
                    const info = columnInfo[id];
                    const role = info?.roles?.[field];
                    return (
                      <div className="cmp-col-row" key={id}>
                        <span className="cmp-col-doc" title={nameOf(id)}>{nameOf(id)}</span>
                        <select
                          value={role?.header || ''}
                          onChange={e => pinColumn(id, e.target.value)}
                        >
                          <option value="">— not found —</option>
                          {(info?.headers || []).map(h => (
                            <option key={h} value={h}>{h.replace(/\s+/g, ' ')}</option>
                          ))}
                        </select>
                        <span className={`cmp-origin cmp-origin-${role?.origin || 'none'}`}>
                          {role?.origin === 'user' ? 'you set this'
                            : role?.origin === 'schema' ? 'auto'
                            : 'none'}
                        </span>
                      </div>
                    );
                  })}
                  {selected.some(id => !columnInfo[id]?.roles?.[field]?.header) && (
                    <p className="cmp-warn">
                      One or more documents have no column for this concept. Pick the right
                      header above, or switch to “Anywhere in the text”.
                    </p>
                  )}
                </div>
              )}

              <button className="cmp-run" onClick={run} disabled={running}>
                {running ? 'Comparing…' : 'Compare'}
              </button>
            </section>
          )}

          {error && <p className="cmp-error">{error}</p>}

          {/* ── 3. Result ────────────────────────────────────────────── */}
          {result && (
            <section className="cmp-step">
              <h3><span className="cmp-num">3</span> Result</h3>

              {result.warnings?.length > 0 && (
                <div className="cmp-warnbox">
                  <strong>Before trusting this</strong>
                  <ul>{result.warnings.map((w, i) => (
                    <li key={i}>{w.replace(/\*\*/g, '').replace(/`/g, '')}</li>
                  ))}</ul>
                </div>
              )}

              {result.column && (
                <p className="cmp-hint">
                  Column read: <code>{result.column}</code>
                  {result.engine_path === 'file' && (
                    <>
                      {' '}— re-read from the PDF, because the stored tables could not
                      supply this column. That can differ from the columns previewed
                      above; this line is what was actually compared.
                    </>
                  )}
                </p>
              )}

              <Summary summary={result.summary} tab={tab} setTab={setTab} />

              <details className="cmp-full">
                <summary>Full written report</summary>
                <pre>{result.answer}</pre>
              </details>

              {result.report_job_id && (
                <a
                  className="cmp-download"
                  href={`/api/reports/download/${result.report_job_id}/`}
                  download
                >
                  Download Excel report
                </a>
              )}
            </section>
          )}
        </div>
      </div>
    </div>
  );
}

function Summary({ summary, tab, setTab }) {
  if (!summary) return null;

  if (summary.kind === 'pairwise') {
    const tiles = [
      { key: 'missing', label: 'Missing', n: summary.missing.count, tone: 'bad' },
      { key: 'likely', label: 'Written differently', n: summary.likely.count, tone: 'warn' },
      { key: 'modified', label: 'Details differ', n: summary.modified.count, tone: 'warn' },
      { key: 'common', label: 'Matched', n: summary.common.count, tone: 'good' },
      { key: 'extra', label: 'Only in target', n: summary.extra.count, tone: 'muted' },
    ];
    return (
      <>
        <div className="cmp-tiles">
          {tiles.map(t => (
            <button
              key={t.key}
              className={`cmp-tile cmp-${t.tone} ${tab === t.key ? 'is-active' : ''}`}
              onClick={() => setTab(t.key)}
            >
              <span className="cmp-tile-n">{t.n}</span>
              <span className="cmp-tile-l">{t.label}</span>
            </button>
          ))}
        </div>
        <ValueList summary={summary} tab={tab} />
      </>
    );
  }

  // matrix (3+ documents) and mentions share a shape
  const missing = summary.missing_everywhere ?? 0;
  const tiles = summary.kind === 'mentions'
    ? [
        { label: 'Mentioned everywhere', n: summary.mentioned_everywhere, tone: 'good' },
        { label: 'Variant match', n: summary.variant_matches, tone: 'warn' },
        { label: 'Some only', n: summary.partial, tone: 'warn' },
        { label: 'Not mentioned anywhere', n: missing, tone: 'bad' },
      ]
    : [
        { label: 'In every document', n: summary.present_everywhere, tone: 'good' },
        { label: 'In some only', n: summary.partial, tone: 'warn' },
        { label: 'Missing everywhere', n: missing, tone: 'bad' },
      ];
  return (
    <>
      <div className="cmp-tiles">
        {tiles.map(t => (
          <div key={t.label} className={`cmp-tile cmp-${t.tone}`}>
            <span className="cmp-tile-n">{t.n}</span>
            <span className="cmp-tile-l">{t.label}</span>
          </div>
        ))}
      </div>
      {summary.missing_values?.length > 0 && (
        <>
          <h4 className="cmp-listhead">Not found anywhere ({summary.missing_values.length})</h4>
          <ul className="cmp-values">
            {summary.missing_values.slice(0, 200).map(v => <li key={v}><code>{v}</code></li>)}
          </ul>
        </>
      )}
    </>
  );
}

function ValueList({ summary, tab }) {
  if (tab === 'likely') {
    const pairs = summary.likely.pairs || [];
    if (!pairs.length) return <p className="cmp-empty">Nothing in this group.</p>;
    return (
      <table className="cmp-table">
        <thead><tr><th>Source</th><th>Target</th><th>Why</th></tr></thead>
        <tbody>
          {pairs.map((p, i) => (
            <tr key={i}>
              <td><code>{p.pdf1_value}</code></td>
              <td><code>{p.pdf2_value}</code></td>
              <td>{p.reason}</td>
            </tr>
          ))}
        </tbody>
      </table>
    );
  }

  if (tab === 'modified') {
    const items = summary.modified.items || [];
    if (!items.length) return <p className="cmp-empty">Nothing in this group.</p>;
    return (
      <table className="cmp-table">
        <thead><tr><th>Value</th><th>Field</th><th>Source</th><th>Target</th></tr></thead>
        <tbody>
          {items.flatMap(item =>
            item.differences.map((d, j) => (
              <tr key={`${item.value}-${j}`}>
                <td>{j === 0 ? <code>{item.value}</code> : ''}</td>
                <td>{d.field}</td>
                <td>{d.value_a}</td>
                <td>{d.value_b}</td>
              </tr>
            ))
          )}
        </tbody>
      </table>
    );
  }

  const bucket = summary[tab];
  const values = bucket?.values || [];
  if (!values.length) return <p className="cmp-empty">Nothing in this group.</p>;
  return (
    <ul className="cmp-values">
      {values.slice(0, 200).map(v => <li key={v}><code>{v}</code></li>)}
      {values.length > 200 && (
        <li className="cmp-more">…and {values.length - 200} more — see the Excel report</li>
      )}
    </ul>
  );
}
