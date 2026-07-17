import React from 'react';

// Expandable source / methodology detail for a benchmark: source, year,
// methodology, limitation, reliability — available without crowding the flow.
export default function SourceDetail({ benchmark, onOpen }) {
  if (!benchmark) return null;
  return (
    <details className="tool-source" onToggle={(e) => e.currentTarget.open && onOpen && onOpen()}>
      <summary>Source and methodology</summary>
      <dl className="tool-source-body">
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
        {benchmark.reliability ? (
          <>
            <dt>Reliability</dt>
            <dd>
              {benchmark.reliability}
              {benchmark.status ? ` · Status: ${benchmark.status}` : ''}
            </dd>
          </>
        ) : null}
      </dl>
    </details>
  );
}
