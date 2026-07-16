import React from 'react';

// Expandable source / methodology detail for a benchmark. Keeps the source,
// year, methodology, limitation, and reliability available without crowding the
// main workflow.
export default function SourceDetail({ benchmark, onOpen }) {
  if (!benchmark) return null;
  return (
    <details className="cot-source" onToggle={(e) => e.currentTarget.open && onOpen && onOpen()}>
      <summary>Source and methodology</summary>
      <dl className="cot-source-body">
        <dt>Source</dt>
        <dd>
          {benchmark.source}
          {benchmark.year ? ` · ${benchmark.year}` : ''}
          {benchmark.sourceUrl ? (
            <>
              {' — '}
              <a href={benchmark.sourceUrl} target="_blank" rel="noopener noreferrer">
                view source
              </a>
            </>
          ) : null}
        </dd>
        <dt>Methodology</dt>
        <dd>{benchmark.methodology}</dd>
        <dt>Limitation</dt>
        <dd>{benchmark.limitation}</dd>
        <dt>Reliability</dt>
        <dd>
          {benchmark.reliability}
          {benchmark.status ? ` · Status: ${benchmark.status}` : ''}
        </dd>
      </dl>
    </details>
  );
}
