// Decision Style Assessment — CONTENT LAYER (separated from presentation).
//
// This module holds the seven questions, their answer options, and the
// provisional style taxonomy. It contains no rendering and no scoring math, so
// copy and taxonomy can be edited here without touching the component, and so
// the next phase can replace the taxonomy or the `signals` weighting without
// reworking the UI.
//
// Design rules honored here (Jaspen product philosophy):
//   - No numeric grade, no "good/bad at deciding" language, no personality test.
//   - Questions describe OBSERVABLE decision behaviors, not identity.
//   - Intuitive ("gut") approaches are treated as legitimate, never careless.
//   - Structured selections only (no free text); "Not applicable" where a
//     question may genuinely not apply.
//
// `signals` on each option is a light, provisional affinity toward one or more
// style keys. It is deliberately simple (not a validated instrument) and exists
// only so the placeholder result feels responsive. The real Decision Profile
// framework will replace it. Values are relative weights, never shown to users.

// ── Provisional style taxonomy (placeholders for review) ──────────────────
// Keep keys stable; names/blurbs are easy to swap. `blurb` is the single
// recognizable sentence shown in the partial result. It never ranks the user,
// never compares them to Jaspen, and never implies one style is superior.
export const STYLES = {
  evidence_builder: {
    key: 'evidence_builder',
    name: 'Evidence Builder',
    blurb:
      'You tend to feel most comfortable committing once you have enough information to explain why the decision makes sense.',
  },
  fast_mover: {
    key: 'fast_mover',
    name: 'Fast Mover',
    blurb:
      'You tend to read a situation quickly and act, trusting that momentum and a clear instinct will carry the decision.',
  },
  thoughtful_explorer: {
    key: 'thoughtful_explorer',
    name: 'Thoughtful Explorer',
    blurb:
      'You tend to open up several possibilities before settling, giving each option a genuine look before you choose.',
  },
  consensus_seeker: {
    key: 'consensus_seeker',
    name: 'Consensus Seeker',
    blurb:
      'You tend to decide with others in mind, weighing perspectives so the choice holds up for everyone it touches.',
  },
  practical_optimizer: {
    key: 'practical_optimizer',
    name: 'Practical Optimizer',
    blurb:
      'You tend to balance instinct and information, moving efficiently toward a choice that simply works.',
  },
  reflective_analyzer: {
    key: 'reflective_analyzer',
    name: 'Reflective Analyzer',
    blurb:
      'You tend to think decisions through carefully and revisit them later, learning from how they turned out.',
  },
};

// Ordering used for stable tie-breaks and for any UI that lists styles.
export const STYLE_ORDER = [
  'evidence_builder',
  'reflective_analyzer',
  'thoughtful_explorer',
  'practical_optimizer',
  'consensus_seeker',
  'fast_mover',
];

// What the *full* Decision Profile will cover. Shown as a teaser on the partial
// result — it indicates value without revealing the interpretation.
export const FULL_PROFILE_INCLUDES = [
  'How this style tends to show up in real decisions',
  'A natural strength it gives you',
  'Something worth keeping an eye on',
  'How Jaspen can support the way you already decide',
  'A short reflection prompt to try on your next decision',
];

// ── The seven questions ───────────────────────────────────────────────────
// `type` is advisory for the UI (all render as a single-select group of
// buttons/radios). `options[].signals` maps option -> provisional style
// affinity. "Not applicable" options carry no signals.
export const QUESTIONS = [
  {
    id: 'q1_instinct_vs_research',
    type: 'scale',
    prompt: 'When an important decision comes up, where do you naturally start?',
    help: 'There is no better end of this scale — both instinct and information are useful.',
    options: [
      { id: 'q1_a', label: 'With my gut read of the situation', signals: { fast_mover: 2 } },
      { id: 'q1_b', label: 'Instinct first, then I check a few facts', signals: { practical_optimizer: 2, fast_mover: 1 } },
      { id: 'q1_c', label: 'An even mix of instinct and information', signals: { consensus_seeker: 3, practical_optimizer: 1 } },
      { id: 'q1_d', label: 'Research first, guided by instinct', signals: { evidence_builder: 2, thoughtful_explorer: 1 } },
      { id: 'q1_e', label: 'By gathering information before I lean either way', signals: { evidence_builder: 2, reflective_analyzer: 1 } },
    ],
  },
  {
    id: 'q2_confidence',
    type: 'scale',
    prompt: 'Once you have made an important decision, how settled do you usually feel?',
    options: [
      { id: 'q2_a', label: 'I often keep weighing it afterward', signals: { reflective_analyzer: 2, thoughtful_explorer: 1 } },
      { id: 'q2_b', label: 'I sometimes keep weighing it', signals: { reflective_analyzer: 1 } },
      { id: 'q2_c', label: 'It varies from decision to decision', signals: { practical_optimizer: 1 } },
      { id: 'q2_d', label: 'I usually feel settled', signals: { practical_optimizer: 1, evidence_builder: 1 } },
      { id: 'q2_e', label: 'I almost always feel settled and move on', signals: { fast_mover: 2 } },
    ],
  },
  {
    id: 'q3_documenting',
    type: 'frequency',
    prompt: 'After you decide something important, how often do you write down why?',
    options: [
      { id: 'q3_a', label: 'Never', signals: { fast_mover: 2 } },
      { id: 'q3_b', label: 'Rarely', signals: { fast_mover: 1 } },
      { id: 'q3_c', label: 'Sometimes', signals: { practical_optimizer: 1 } },
      { id: 'q3_d', label: 'Often', signals: { evidence_builder: 1, reflective_analyzer: 1 } },
      { id: 'q3_e', label: 'Almost always', signals: { evidence_builder: 2 } },
      { id: 'q3_na', label: 'Not applicable', signals: {} },
    ],
  },
  {
    // Required ranged question. Ranges are contiguous and non-overlapping.
    id: 'q4_alternatives',
    type: 'range',
    prompt: 'On a typical important decision, how many real alternatives do you seriously weigh?',
    options: [
      { id: 'q4_none', label: 'None — I usually already know the option I want', signals: { fast_mover: 2 } },
      { id: 'q4_1_2', label: '1–2', signals: { practical_optimizer: 2 } },
      { id: 'q4_3_5', label: '3–5', signals: { thoughtful_explorer: 2, evidence_builder: 1 } },
      { id: 'q4_5_plus', label: 'More than 5', signals: { thoughtful_explorer: 2, reflective_analyzer: 1 } },
      { id: 'q4_na', label: 'Not applicable', signals: {} },
    ],
  },
  {
    id: 'q5_explain_later',
    type: 'scale',
    prompt:
      'If someone asked weeks later why you chose what you did, how easily could you explain your reasoning?',
    options: [
      { id: 'q5_a', label: "I'd find it hard to reconstruct", signals: { fast_mover: 2 } },
      { id: 'q5_b', label: 'With some effort', signals: { practical_optimizer: 1 } },
      { id: 'q5_c', label: 'Reasonably well', signals: { practical_optimizer: 1, thoughtful_explorer: 1 } },
      { id: 'q5_d', label: 'Easily', signals: { evidence_builder: 1, reflective_analyzer: 1 } },
      { id: 'q5_e', label: 'I could walk through it step by step', signals: { evidence_builder: 2 } },
      { id: 'q5_na', label: 'Not applicable', signals: {} },
    ],
  },
  {
    id: 'q6_what_would_change',
    type: 'scale',
    prompt:
      'When you decide, how clear are you about what new information would change your mind?',
    options: [
      { id: 'q6_a', label: 'I rarely think about that', signals: { fast_mover: 2 } },
      { id: 'q6_b', label: 'Occasionally', signals: { practical_optimizer: 1 } },
      { id: 'q6_c', label: 'Sometimes', signals: { thoughtful_explorer: 1 } },
      { id: 'q6_d', label: 'Often', signals: { evidence_builder: 1, thoughtful_explorer: 1 } },
      { id: 'q6_e', label: "I'm usually very clear on it", signals: { evidence_builder: 2, reflective_analyzer: 1 } },
      { id: 'q6_na', label: 'Not applicable', signals: {} },
    ],
  },
  {
    id: 'q7_reflection',
    type: 'frequency',
    prompt: 'How often do you look back on past decisions to see how they turned out?',
    options: [
      { id: 'q7_a', label: 'Never', signals: { fast_mover: 1 } },
      { id: 'q7_b', label: 'Rarely', signals: {} },
      { id: 'q7_c', label: 'Sometimes', signals: { practical_optimizer: 1 } },
      { id: 'q7_d', label: 'Often', signals: { reflective_analyzer: 1 } },
      { id: 'q7_e', label: 'Almost always', signals: { reflective_analyzer: 2 } },
    ],
  },
];

export const QUESTION_COUNT = QUESTIONS.length;

// The lead-capture source for this experience. Distinct from the scorecard
// magnet so the backend's normalized (email + source) uniqueness treats it as
// its own funnel. Confirmed to fit the existing endpoint (source <= 80 chars).
export const LEAD_SOURCE = 'decision-style-assessment';
