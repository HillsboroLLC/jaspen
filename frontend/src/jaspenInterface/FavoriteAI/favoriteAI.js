export const BRAINSTORM_PROMPT = `Help me think rigorously about this decision before I evaluate it in Jaspen. Explore meaningfully different alternatives, surface the assumptions behind each one, identify missing information and gaps, and challenge the way I have framed the decision. Point out important trade-offs and risks, and identify the evidence that would most change the answer. Ask focused questions when they would improve the thinking.

Close with a short, paste-ready summary for Jaspen that includes the options considered, key assumptions, open questions, and a recommendation if you have one. Keep that closing summary factual, and distinguish what I told you from what you inferred.`;

export const PROVIDERS = {
  chatgpt: {
    id: 'chatgpt',
    name: 'ChatGPT',
    url: 'https://chatgpt.com/',
    color: 'currentColor',
  },
  claude: {
    id: 'claude',
    name: 'Claude',
    url: 'https://claude.ai/new',
    color: '#D97757',
  },
  gemini: {
    id: 'gemini',
    name: 'Gemini',
    url: 'https://gemini.google.com/app',
    color: '#8E75B2',
  },
  copilot: {
    id: 'copilot',
    name: 'Copilot',
    url: 'https://copilot.microsoft.com/',
    color: 'currentColor',
  },
};

export const PROVIDER_IDS = Object.keys(PROVIDERS);

const cleanItems = (items) => Array.from(new Set(
  (Array.isArray(items) ? items : [])
    .map((item) => String(item || '').trim())
    .filter(Boolean)
));

export function normalizeProjectSummary(summary = {}) {
  return {
    title: String(summary.title || '').trim(),
    options: cleanItems(summary.options),
    openQuestions: cleanItems(summary.openQuestions),
  };
}

export function formatProjectSummary(summary) {
  const normalized = normalizeProjectSummary(summary);
  const sections = [];

  if (normalized.title) sections.push(`Title: ${normalized.title}`);
  if (normalized.options.length > 0) {
    sections.push(`Options:\n${normalized.options.map((option) => `- ${option}`).join('\n')}`);
  }
  if (normalized.openQuestions.length > 0) {
    sections.push(`Open questions:\n${normalized.openQuestions.map((question) => `- ${question}`).join('\n')}`);
  }

  return sections.join('\n');
}

export function buildCopiedPrompt(summary, includeProjectSummary) {
  if (!includeProjectSummary) return BRAINSTORM_PROMPT;
  const projectText = formatProjectSummary(summary);
  return projectText
    ? `${BRAINSTORM_PROMPT}\n\nProject summary from Jaspen:\n${projectText}`
    : BRAINSTORM_PROMPT;
}

export function labelReturnedThinking(providerId, text) {
  const provider = PROVIDERS[providerId] || PROVIDERS.chatgpt;
  return `Ideas from my ${provider.name} brainstorm:\n\n${String(text || '').trim()}`;
}

export function appendComposerDraft(currentDraft, addition) {
  const current = String(currentDraft || '');
  const next = String(addition || '').trim();
  if (!current.trim()) return next;
  if (!next) return current;
  return `${current.trimEnd()}\n\n${next}`;
}
