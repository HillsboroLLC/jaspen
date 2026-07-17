import React from 'react';
import { PROVENANCE, PROVENANCE_LABEL } from '../provenance';

// Published Benchmark vs Research-Based Estimate vs Your Inputs. Meaning is
// conveyed by text, not color alone.
export default function ProvenanceBadge({ type, overridden = false }) {
  const resolved = overridden ? PROVENANCE.ORG : type;
  const cls =
    resolved === PROVENANCE.PUBLISHED
      ? 'tool-badge-published'
      : resolved === PROVENANCE.ORG
        ? 'tool-badge-org'
        : 'tool-badge-research';
  return <span className={`tool-badge ${cls}`}>{PROVENANCE_LABEL[resolved]}</span>;
}
