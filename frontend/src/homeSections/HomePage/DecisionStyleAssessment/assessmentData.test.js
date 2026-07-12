import {
  QUESTIONS,
  QUESTION_COUNT,
  STYLES,
  STYLE_ORDER,
  FULL_PROFILE_INCLUDES,
  LEAD_SOURCE,
} from './assessmentData';

describe('assessment content', () => {
  it('has no more than seven questions', () => {
    expect(QUESTIONS.length).toBeLessThanOrEqual(7);
    expect(QUESTION_COUNT).toBe(QUESTIONS.length);
  });

  it('gives every question a prompt and at least two options', () => {
    for (const q of QUESTIONS) {
      expect(typeof q.prompt).toBe('string');
      expect(q.prompt.length).toBeGreaterThan(0);
      expect(q.options.length).toBeGreaterThanOrEqual(2);
    }
  });

  it('uses globally-unique question ids and option ids', () => {
    const qIds = QUESTIONS.map((q) => q.id);
    expect(new Set(qIds).size).toBe(qIds.length);

    const optIds = QUESTIONS.flatMap((q) => q.options.map((o) => o.id));
    expect(new Set(optIds).size).toBe(optIds.length);
  });

  it('question 4 offers the non-overlapping alternative ranges plus Not applicable', () => {
    const q4 = QUESTIONS[3];
    const labels = q4.options.map((o) => o.label);
    expect(labels).toEqual(
      expect.arrayContaining(['1–2', '3–5', 'More than 5', 'Not applicable'])
    );
    // "None" is phrased as a full sentence; assert its presence loosely.
    expect(labels.some((l) => l.startsWith('None'))).toBe(true);
  });

  it('marks every "Not applicable" option as carrying no style signal', () => {
    for (const q of QUESTIONS) {
      for (const o of q.options) {
        if (o.label === 'Not applicable') {
          expect(o.signals).toEqual({});
        }
      }
    }
  });

  it('only ever points option signals at real styles', () => {
    for (const q of QUESTIONS) {
      for (const o of q.options) {
        for (const key of Object.keys(o.signals || {})) {
          expect(STYLES[key]).toBeDefined();
        }
      }
    }
  });

  it('keeps the style taxonomy and ordering in sync', () => {
    expect(new Set(STYLE_ORDER)).toEqual(new Set(Object.keys(STYLES)));
    for (const key of STYLE_ORDER) {
      expect(STYLES[key].name).toBeTruthy();
      expect(STYLES[key].blurb).toBeTruthy();
    }
  });

  it('never uses a numeric grade or judgmental "good/bad at" language in blurbs', () => {
    for (const key of STYLE_ORDER) {
      const blurb = STYLES[key].blurb.toLowerCase();
      expect(blurb).not.toMatch(/\bscore\b|\bgrade\b|better than|worse than|good at|bad at/);
    }
  });

  it('exposes the profile teaser and the distinct lead source', () => {
    expect(FULL_PROFILE_INCLUDES.length).toBeGreaterThan(0);
    expect(LEAD_SOURCE).toBe('decision-style-assessment');
    expect(LEAD_SOURCE.length).toBeLessThanOrEqual(80); // backend field limit
  });
});
