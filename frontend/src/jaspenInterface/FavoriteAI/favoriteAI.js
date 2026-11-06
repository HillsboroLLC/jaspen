export const BRAINSTORM_PROMPT = `Help me think rigorously about this decision before I evaluate it in Jaspen. Explore meaningfully different options, challenge how I have framed the decision, and ask focused questions when they would improve the thinking. Help me clarify the decision, objectives, criteria, priorities, constraints, assumptions, available evidence, risks, trade-offs, and open questions as applicable.

When I say I am ready to return to Jaspen, prepare a comprehensive, well-organized summary that I can paste into Jaspen. Include the decision, objectives, options, criteria and priorities, constraints, assumptions, evidence, risks, trade-offs, and open questions that emerged, omitting sections that do not apply. Include a recommendation only if one is supported, and present it as advice rather than a decision made for me.

Keep the summary factual. Clearly distinguish information I stated, information verified from a named source, estimates, and assumptions or inferences. Do not label something verified unless a source or direct evidence supports it.`;

export const PROVIDERS = {
  chatgpt: {
    id: 'chatgpt',
    name: 'ChatGPT',
    url: 'https://chatgpt.com/',
  },
  claude: {
    id: 'claude',
    name: 'Claude',
    url: 'https://claude.ai/new',
  },
  gemini: {
    id: 'gemini',
    name: 'Gemini',
    url: 'https://gemini.google.com/app',
  },
  copilot: {
    id: 'copilot',
    name: 'Copilot',
    url: 'https://copilot.microsoft.com/',
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
  const next = String(addition || '');
  if (!current.trim()) return next.trimStart();
  if (!next.trim()) return current;
  return `${current.trimEnd()}\n\n${next.trimStart()}`;
}
