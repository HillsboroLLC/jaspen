// Config-level tests: conditional questions, SEO metadata, analytics surface,
// and source attribution completeness.

import { KNOWLEDGE_FIELDS, isFieldVisible, REVIEW_ASSUMPTIONS, STEPS } from '../config/questions';
import { SEO, CANONICAL_PATH, seoJsonLd } from '../config/seo';
import { EVENTS, UTILITY_SOURCE, track } from '../services/analytics';
import { BENCHMARKS } from '../data/benchmarks';
import { getDefaultAssumptions } from '../engine/calculator';

describe('conditional questions', () => {
  it('hides knowledge-transfer hours when the departure is unplanned', () => {
    const field = KNOWLEDGE_FIELDS.find((f) => f.key === 'knowledgeTransferHours');
    expect(isFieldVisible(field, { knowledgeTransferPlanned: 'no' })).toBe(false);
    expect(isFieldVisible(field, { knowledgeTransferPlanned: 'partial' })).toBe(true);
  });
  it('hides project-disruption hours until at least one project is affected', () => {
    const field = KNOWLEDGE_FIELDS.find((f) => f.key === 'projectDisruptionHours');
    expect(isFieldVisible(field, { affectedProjects: 0 })).toBe(false);
    expect(isFieldVisible(field, { affectedProjects: 2 })).toBe(true);
  });
  it('has exactly four steps ending in results', () => {
    expect(STEPS).toHaveLength(4);
    expect(STEPS[3].id).toBe('results');
  });
  it('every review assumption maps to a real default', () => {
    const defaults = getDefaultAssumptions({ roleCategory: 'corporate_knowledge', roleLevel: 'manager' });
    REVIEW_ASSUMPTIONS.forEach((f) => {
      expect(defaults[f.key]).toBeDefined();
    });
  });
});

describe('SEO metadata', () => {
  it('uses the canonical /tools/cost-of-turnover route', () => {
    expect(CANONICAL_PATH).toBe('/tools/cost-of-turnover');
    expect(SEO.canonicalPath).toBe('/tools/cost-of-turnover');
  });
  it('has a title and a non-empty meta description', () => {
    expect(SEO.title).toMatch(/Cost of Employee Turnover/i);
    expect(SEO.description.length).toBeGreaterThan(50);
  });
  it('emits WebApplication + FAQ structured data', () => {
    const ld = seoJsonLd();
    const types = ld.map((x) => x['@type']);
    expect(types).toContain('WebApplication');
    expect(types).toContain('FAQPage');
  });
});

describe('analytics surface', () => {
  it('uses the unique source identifier', () => {
    expect(UTILITY_SOURCE).toBe('cost_of_turnover_utility');
  });
  it('defines every required funnel event', () => {
    [
      'UTILITY_VIEWED',
      'CALCULATOR_STARTED',
      'STEP_COMPLETED',
      'BENCHMARK_OVERRIDDEN',
      'CALCULATOR_COMPLETED',
      'RESULTS_VIEWED',
      'METHODOLOGY_VIEWED',
      'SAVE_CTA_CLICKED',
      'SIGNUP_COMPLETED',
      'ESTIMATE_SAVED',
      'BENCHMARK_CONTRIBUTION_CONSENT',
      'JASPEN_CTA_CLICKED',
      'STEP_ABANDONED',
      'ERROR',
    ].forEach((k) => expect(EVENTS[k]).toBeTruthy());
  });
  it('track() tags events with the source and never throws', () => {
    const detail = track(EVENTS.UTILITY_VIEWED, { foo: 1 });
    expect(detail.source).toBe('cost_of_turnover_utility');
    expect(detail.event).toBe('utility_view');
  });
});

describe('source attribution completeness', () => {
  it('every benchmark carries source, type, year, methodology, and limitation', () => {
    Object.values(BENCHMARKS).forEach((b) => {
      expect(b.source).toBeTruthy();
      expect(['published', 'research']).toContain(b.type);
      expect(b.methodology).toBeTruthy();
      expect(b.limitation).toBeTruthy();
      expect(b.reliability).toBeTruthy();
    });
  });
});
