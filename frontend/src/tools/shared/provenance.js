// =====================================================
// Shared provenance vocabulary for Jaspen public utilities.
// Preserves the three-way distinction used across every calculator:
//   - published  Published Benchmark  — directly measured/published by an
//                authoritative organization for the same or a closely matching
//                variable.
//   - research   Research-Based Estimate — derived through documented
//                methodology from credible published sources where no direct
//                benchmark exists for the exact variable.
//   - org        Your Inputs — values the user supplied or modified.
// =====================================================

export const PROVENANCE = {
  PUBLISHED: 'published',
  RESEARCH: 'research',
  ORG: 'org',
};

export const PROVENANCE_LABEL = {
  published: 'Published Benchmark',
  research: 'Research-Based Estimate',
  org: 'Your Inputs',
};

// Reliability tiers (shown in the methodology panel).
export const RELIABILITY = {
  A_PRIMARY: 'A — Primary source',
  B_PROXY: 'B — Research-based proxy',
  C_SECONDARY: 'C — Secondary citation',
};
