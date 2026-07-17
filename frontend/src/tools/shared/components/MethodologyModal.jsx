import React, { useEffect, useRef } from 'react';
import { PROVENANCE_LABEL } from '../provenance';

// "How We Built These Estimates" — accessible modal. Generic across utilities:
// pass a title, version line, intro, principles, benchmark rows, and notes.
export default function MethodologyModal({
  open,
  onClose,
  title = 'How We Built These Estimates',
  versionLine,
  intro,
  principles = [],
  benchmarks = [],
  notes = [],
}) {
  const closeRef = useRef(null);

  useEffect(() => {
    if (!open) return undefined;
    const onKey = (e) => {
      if (e.key === 'Escape') onClose();
    };
    document.addEventListener('keydown', onKey);
    if (closeRef.current) closeRef.current.focus();
    return () => document.removeEventListener('keydown', onKey);
  }, [open, onClose]);

  if (!open) return null;

  return (
    <div
      className="tool-modal-overlay"
      role="presentation"
      onMouseDown={(e) => {
        if (e.target === e.currentTarget) onClose();
      }}
    >
      <div className="tool-modal" role="dialog" aria-modal="true" aria-labelledby="tool-method-title">
        <button ref={closeRef} type="button" className="tool-modal-close" aria-label="Close" onClick={onClose}>
          ×
        </button>
        <h2 id="tool-method-title">{title}</h2>
        {versionLine ? <p>{versionLine}</p> : null}
        {intro ? <p>{intro}</p> : null}

        {principles.length > 0 ? (
          <>
            <h3>The approach</h3>
            <ul>
              {principles.map((p) => (
                <li key={p.title}>
                  <strong>{p.title}</strong>
                  {p.body ? ` — ${p.body}` : ''}
                </li>
              ))}
            </ul>
          </>
        ) : null}

        {benchmarks.length > 0 ? (
          <>
            <h3>Benchmarks and sources</h3>
            <div className="tool-scroll-x">
              <table className="tool-table" style={{ fontSize: '0.82rem' }}>
                <thead>
                  <tr>
                    <th>Variable</th>
                    <th>Default</th>
                    <th>Type</th>
                    <th>Source / year</th>
                    <th>Limitation</th>
                  </tr>
                </thead>
                <tbody>
                  {benchmarks.map((b) => (
                    <tr key={b.id}>
                      <td>
                        {b.variable}
                        {b.segment ? (
                          <>
                            <br />
                            <span style={{ color: '#8791a6' }}>{b.segment}</span>
                          </>
                        ) : null}
                      </td>
                      <td>{b.displayValue != null ? b.displayValue : `${b.value ?? ''}${b.unit ? ` ${b.unit}` : ''}`}</td>
                      <td>{PROVENANCE_LABEL[b.type] || b.type}</td>
                      <td>
                        {b.source}
                        {b.year ? ` (${b.year})` : ''}
                        {b.sourceUrl ? (
                          <>
                            <br />
                            <a href={b.sourceUrl} target="_blank" rel="noopener noreferrer">
                              source
                            </a>
                          </>
                        ) : null}
                      </td>
                      <td>{b.limitation}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </>
        ) : null}

        {notes.length > 0 ? (
          <>
            <h3>Limitations and assumptions</h3>
            <ul>
              {notes.map((n, i) => (
                // eslint-disable-next-line react/no-array-index-key
                <li key={i}>{n}</li>
              ))}
            </ul>
          </>
        ) : null}
      </div>
    </div>
  );
}
