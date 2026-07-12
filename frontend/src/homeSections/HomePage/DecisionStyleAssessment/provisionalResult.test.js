import { deriveProvisionalStyle, tallyAffinity } from './provisionalResult';
import { STYLES } from './assessmentData';

describe('provisional result mapping', () => {
  it('falls back to a neutral style when there are no answers', () => {
    const { style, isFallback } = deriveProvisionalStyle({});
    expect(isFallback).toBe(true);
    expect(style).toBe(STYLES.practical_optimizer);
  });

  it('falls back when every answer carries no signal (all Not applicable)', () => {
    const answers = { q3_documenting: 'q3_na', q4_alternatives: 'q4_na' };
    const { isFallback } = deriveProvisionalStyle(answers);
    expect(isFallback).toBe(true);
  });

  it('maps research-and-documentation answers to Evidence Builder', () => {
    const answers = {
      q1_instinct_vs_research: 'q1_e', // gather info first
      q3_documenting: 'q3_e', // almost always writes why
      q5_explain_later: 'q5_e', // can walk through step by step
      q6_what_would_change: 'q6_e', // very clear what would change mind
    };
    const { style, isFallback } = deriveProvisionalStyle(answers);
    expect(isFallback).toBe(false);
    expect(style).toBe(STYLES.evidence_builder);
  });

  it('maps quick-gut answers to Fast Mover', () => {
    const answers = {
      q1_instinct_vs_research: 'q1_a', // gut read
      q2_confidence: 'q2_e', // settled, move on
      q3_documenting: 'q3_a', // never writes why
      q4_alternatives: 'q4_none', // already knows the option
    };
    const { style, isFallback } = deriveProvisionalStyle(answers);
    expect(isFallback).toBe(false);
    expect(style).toBe(STYLES.fast_mover);
  });

  it('maps weighing-many-options answers to Thoughtful Explorer', () => {
    const answers = {
      q4_alternatives: 'q4_5_plus', // more than 5
      q6_what_would_change: 'q6_c', // sometimes
    };
    const { style } = deriveProvisionalStyle(answers);
    expect(style).toBe(STYLES.thoughtful_explorer);
  });

  it('maps balanced-consideration answers to Consensus Seeker', () => {
    const answers = {
      q1_instinct_vs_research: 'q1_c',
    };
    const { style } = deriveProvisionalStyle(answers);
    expect(style).toBe(STYLES.consensus_seeker);
  });

  it('can return every named style from the current option mapping', () => {
    const scenarios = {
      evidence_builder: {
        q1_instinct_vs_research: 'q1_e',
        q3_documenting: 'q3_e',
        q5_explain_later: 'q5_e',
      },
      fast_mover: {
        q1_instinct_vs_research: 'q1_a',
        q2_confidence: 'q2_e',
        q3_documenting: 'q3_a',
      },
      thoughtful_explorer: {
        q4_alternatives: 'q4_5_plus',
        q6_what_would_change: 'q6_c',
      },
      consensus_seeker: {
        q1_instinct_vs_research: 'q1_c',
      },
      practical_optimizer: {
        q1_instinct_vs_research: 'q1_b',
        q4_alternatives: 'q4_1_2',
      },
      reflective_analyzer: {
        q2_confidence: 'q2_a',
        q7_reflection: 'q7_e',
      },
    };

    for (const [key, answers] of Object.entries(scenarios)) {
      expect(deriveProvisionalStyle(answers).style).toBe(STYLES[key]);
    }
  });

  it('never returns a numeric score, only a style object shape', () => {
    const { style } = deriveProvisionalStyle({ q1_instinct_vs_research: 'q1_a' });
    expect(Object.keys(style).sort()).toEqual(['blurb', 'key', 'name']);
    expect(style).not.toHaveProperty('score');
  });

  it('is deterministic for identical answers', () => {
    const answers = { q1_instinct_vs_research: 'q1_d', q2_confidence: 'q2_a' };
    expect(deriveProvisionalStyle(answers)).toEqual(deriveProvisionalStyle(answers));
  });

  it('ignores unknown option ids without throwing', () => {
    const totals = tallyAffinity({ qX: 'does_not_exist' });
    const sum = Object.values(totals).reduce((a, b) => a + b, 0);
    expect(sum).toBe(0);
  });
});
