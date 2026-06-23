// Persistence + shared model for the Guided Decision experience.
// Kept framework-agnostic and small so the feature is easy to evolve.

const userKey = (user) => {
  if (user?.id) return `id_${user.id}`;
  if (user?.email) return `email_${String(user.email).toLowerCase()}`;
  return 'anon';
};

// First-login walkthrough completion (the in-product spotlight tour).
export const walkthroughStorageKey = (user) =>
  `jaspen_walkthrough_done_${userKey(user)}`;

export function getWalkthroughDone(user) {
  try {
    return localStorage.getItem(walkthroughStorageKey(user)) === '1';
  } catch {
    return false;
  }
}

export function setWalkthroughDone(user) {
  try {
    localStorage.setItem(walkthroughStorageKey(user), '1');
  } catch {
    /* storage unavailable — non-fatal */
  }
}

// Focus options (Step 1)
export const FOCUS_OPTIONS = [
  {
    id: 'prioritize',
    title: 'Prioritize & Plan',
    icon: 'layer-group',
    examples: ['Prioritize initiatives', 'Allocate resources', 'Build a roadmap'],
  },
  {
    id: 'evaluate',
    title: 'Evaluate & Compare',
    icon: 'scale-balanced',
    examples: ['Evaluate investments', 'Compare options', 'Analyze tradeoffs'],
  },
  {
    id: 'align',
    title: 'Align & Execute',
    icon: 'people-group',
    examples: ['Align stakeholders', 'Improve a process', 'Solve a business challenge'],
  },
];

// Guided questions (Step 2)
export const GUIDED_QUESTIONS = [
  {
    id: 'decision',
    short: 'Decision, problem, or opportunity',
    label: 'What decision, problem, or opportunity are you working through?',
  },
  {
    id: 'options',
    short: 'Options being considered',
    label: 'What options, initiatives, or paths are being considered?',
  },
  {
    id: 'stakeholders',
    short: 'People involved',
    label: 'Who is involved or impacted?',
  },
  {
    id: 'constraints',
    short: 'Constraints',
    label: 'What constraints matter most?',
  },
  {
    id: 'outcome',
    short: 'Desired outcome',
    label: 'What outcome are you hoping to achieve?',
  },
];

export const emptyDraft = () => ({
  focus: null, // one of FOCUS_OPTIONS ids
  focusCustom: '', // free-text situation
  answers: { decision: '', options: '', stakeholders: '', constraints: '', outcome: '' },
});

const focusLabel = (draft) => {
  if (draft.focusCustom.trim()) return draft.focusCustom.trim();
  const f = FOCUS_OPTIONS.find((o) => o.id === draft.focus);
  return f ? f.title : '';
};

// Build the structured prompt shown in Review and handed to the composer.
export function buildStructuredPrompt(draft) {
  const focus = focusLabel(draft);
  const a = draft.answers;
  const sections = [
    ['Decision Context', a.decision || focus],
    ['Potential Options', a.options],
    ['Stakeholders', a.stakeholders],
    ['Constraints', a.constraints],
    ['Desired Outcome', a.outcome],
  ];

  const lines = [];
  if (focus) lines.push(`Focus: ${focus}`, '');
  sections.forEach(([heading, value]) => {
    const v = (value || '').trim();
    if (!v) return; // omit empty sections to keep the summary clean
    lines.push(heading);
    lines.push(v);
    lines.push('');
  });

  return lines.join('\n').trim();
}
