import React from 'react';
import { PROVENANCE, PROVENANCE_LABEL } from '../data/benchmarks';

// A small, accessible label distinguishing Published Benchmark vs Research-Based
// Estimate vs the user's own input. Meaning is conveyed by text, not color alone.
export default function ProvenanceBadge({ type, overridden = false }) {
  const resolved = overridden ? PROVENANCE.ORG : type;
  const cls =
    resolved === PROVENANCE.PUBLISHED
      ? 'cot-badge-published'
      : resolved === PROVENANCE.ORG
        ? 'cot-badge-org'
        : 'cot-badge-research';
  return <span className={`cot-badge ${cls}`}>{PROVENANCE_LABEL[resolved]}</span>;
}
