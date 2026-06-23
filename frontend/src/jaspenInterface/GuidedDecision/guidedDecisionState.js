// Persistence + shared model for the Guided Decision experience.
// Kept framework-agnostic and small so the feature is easy to evolve.

const userKey = (user) => {
  if (user?.id) return `id_${user.id}`;
  if (user?.email) return `email_${String(user.email).toLowerCase()}`;
  return 'anon';
};

export const firstRunStorageKey = (user) =>
  `jaspen_guided_firstrun_dismissed_${userKey(user)}`;

export function getFirstRunDismissed(user) {
  try {
    return localStorage.getItem(firstRunStorageKey(user)) === '1';
  } catch {
    return false;
  }
}

export function setFirstRunDismissed(user) {
  try {
    localStorage.setItem(firstRunStorageKey(user), '1');
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

// Context capture methods (Step 2)
export const METHOD_OPTIONS = [
  {
    id: 'speak',
    title: 'Speak naturally',
    description: 'Explain your situation in your own words.',
    icon: 'microphone',
  },
  {
    id: 'type',
    title: 'Type your thoughts',
    description: 'Share whatever information you have.',
    icon: 'keyboard',
  },
  {
    id: 'guided',
    title: 'Answer a few guided questions',
    description: 'Jaspen will help organize the important details.',
    icon: 'wand-magic-sparkles',
  },
];

// Guided questions (Step 3)
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
  method: null, // one of METHOD_OPTIONS ids
  contextText: '', // for speak / type
  answers: { decision: '', options: '', stakeholders: '', constraints: '', outcome: '' },
});

// Whether the guided (5-question) refine step is part of this flow.
export const flowHasRefineStep = (draft) => draft.method === 'guided';

const focusLabel = (draft) => {
  if (draft.focusCustom.trim()) return draft.focusCustom.trim();
  const f = FOCUS_OPTIONS.find((o) => o.id === draft.focus);
  return f ? f.title : '';
};

// Build the structured prompt shown in Review and handed to the composer.
export function buildStructuredPrompt(draft) {
  const sections = [];
  const focus = focusLabel(draft);

  if (draft.method === 'guided') {
    const a = draft.answers;
    sections.push(['Decision Context', a.decision || focus]);
    sections.push(['Potential Options', a.options]);
    sections.push(['Stakeholders', a.stakeholders]);
    sections.push(['Constraints', a.constraints]);
    sections.push(['Desired Outcome', a.outcome]);
  } else {
    // speak / type — a single narrative blob plus the chosen focus framing
    sections.push(['Decision Context', draft.contextText || focus]);
  }

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
