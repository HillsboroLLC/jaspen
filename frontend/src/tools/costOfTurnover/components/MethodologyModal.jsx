import React, { useEffect, useRef } from 'react';
import { BENCHMARKS, METHODOLOGY_VERSION, BENCHMARK_VERSION } from '../data/benchmarks';

// "How We Built These Estimates" — accessible modal. Every source, year,
// methodology, limitation, and benchmark type is available here without
// crowding the main workflow.
export default function MethodologyModal({ open, onClose }) {
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

  const rows = Object.values(BENCHMARKS);

  return (
    <div
      className="cot-modal-overlay"
      role="presentation"
      onMouseDown={(e) => {
        if (e.target === e.currentTarget) onClose();
      }}
    >
      <div className="cot-modal" role="dialog" aria-modal="true" aria-labelledby="cot-method-title">
        <button ref={closeRef} type="button" className="cot-modal-close" aria-label="Close" onClick={onClose}>
          ×
        </button>
        <h2 id="cot-method-title">How We Built These Estimates</h2>
        <p>
          Methodology v{METHODOLOGY_VERSION} · Benchmark library v{BENCHMARK_VERSION}. This utility
          estimates potential costs — it does not predict exact outcomes.
        </p>

        <h3>The approach</h3>
        <ul>
          <li>
            <strong>Standard turnover costs use published benchmarks where available</strong> — SHRM
            (cost per hire, time to fill), BLS (wages, loaded-cost multiplier), Gallup (time to full
            productivity). These are direct measurements.
          </li>
          <li>
            <strong>Knowledge and context costs use documented research-based estimates</strong>{' '}
            where no direct benchmark exists. We derive them from the strongest published evidence
            (APQC, McKinsey, Panopto, Gartner, PMI) and document the derivation.
          </li>
          <li>Every assumption is visible, and every editable assumption can be changed by you.</li>
          <li>The result is an estimate, not a prediction.</li>
          <li>
            Validate material estimates with your HR, Finance, or other appropriate business
            partners before acting on them.
          </li>
        </ul>

        <h3>Avoiding double-counting</h3>
        <p>
          Context rediscovery counts only hours incremental to, and outside, the ramp-up window, so
          it is not double-counted with the ramp-up productivity gap. Subtotals are display
          groupings and are never re-added into the total.
        </p>

        <h3>Sources and benchmark types</h3>
        <div className="cot-scroll-x">
          <table className="cot-source-table">
            <thead>
              <tr>
                <th>Variable</th>
                <th>Value</th>
                <th>Type</th>
                <th>Source / year</th>
                <th>Limitation</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((b) => (
                <tr key={b.id}>
                  <td>{b.variable}<br /><span style={{ color: '#8791a6' }}>{b.segment}</span></td>
                  <td>
                    {b.value}
                    {b.unit ? ` ${b.unit}` : ''}
                  </td>
                  <td>{b.type === 'published' ? 'Published Benchmark' : 'Research-Based Estimate'}</td>
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
      </div>
    </div>
  );
}
