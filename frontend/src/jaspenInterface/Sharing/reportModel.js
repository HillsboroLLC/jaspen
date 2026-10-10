// Turns a frozen share snapshot into the content of the one-pager report.
// Every number shown comes from code-owned fields on the snapshot (score,
// metrics, gates, rubric weights). Wording is derived here and may be
// replaced by the owner's presentation edits, but numbers never are.

export const REPORT_SECTIONS = [
  { key: 'strength', label: 'How strong is the case?' },
  { key: 'standings', label: 'Where each option stands' },
  { key: 'featured', label: 'The strongest case' },
  { key: 'change', label: 'What could change the answer' },
  { key: 'takeaways', label: 'What leadership should know' },
  { key: 'criteria', label: 'The criteria you approved' },
  { key: 'next_step', label: 'Next step' },
];

export const DEFAULT_COLORS = { accent: '#A0036C', ink: '#1B2342', tint: '#EEF5F7' };

const OBJECTIVE_LABELS = {
  balanced: 'Balanced',
  cost: 'Cost Optimization',
  speed: 'Speed to Market',
  growth: 'Growth',
};

const KIT_LABELS = {
  rfp_bid: 'RFP response',
  rfp_vendor_selection: 'RFP vendor selection',
};

const KIT_MASTHEADS = {
  rfp_bid: 'RFP BID / NO-BID DECISION',
  rfp_vendor_selection: 'RFP VENDOR SELECTION',
};

const DATA_SOURCE_LABELS = {
  jira: 'Jira',
  salesforce: 'Salesforce',
  snowflake: 'Snowflake',
  smartsheet: 'Smartsheet',
};

const humanize = (key) => String(key || '')
  .replace(/_/g, ' ')
  .replace(/\b\w/g, (c) => c.toUpperCase())
  .replace(/\bPct\b/, '')
  .trim();

const firstSentences = (text, count = 1) => {
  const clean = String(text || '').replace(/\s+/g, ' ').trim();
  if (!clean) return '';
  const parts = clean.match(/[^.!?]+[.!?]+(\s|$)/g) || [clean];
  return parts.slice(0, count).join('').trim();
};

export const cardName = (card) => {
  const overrides = card?.display_overrides || {};
  return String(overrides.title || card?.project_name || card?.name || card?.label || 'Option').trim();
};

export const cardScore = (card) => {
  const value = card?.jaspen_score ?? card?.score;
  return Number.isFinite(Number(value)) ? Math.round(Number(value)) : null;
};

const money = (value) => {
  const n = Number(value);
  if (!Number.isFinite(n)) return String(value);
  return n.toLocaleString('en-US', { style: 'currency', currency: 'USD', maximumFractionDigits: 0 });
};

const ISO_DATE = /^\d{4}-\d{2}-\d{2}$/;

const formatDate = (value) => {
  const [y, m, d] = String(value).split('-').map(Number);
  return new Date(y, m - 1, d).toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' });
};

// Model summaries often just restate the score; the report already shows it.
const restatesScore = (text) => /\bscores?\s+\d+\s*\/\s*100\b|\b\d+\s*\/\s*100\b/i.test(String(text || ''));

export const formatFactValue = (fact) => {
  const value = fact?.value;
  const unit = String(fact?.unit || '').toLowerCase();
  if (typeof value === 'string' && ISO_DATE.test(value)) return formatDate(value);
  if (unit === 'usd') return money(value);
  if (unit === 'percent_points' || unit === 'percent') return `${value}%`;
  if (unit && Number.isFinite(Number(value))) return `${value} ${unit}`;
  return String(value);
};

const formatMetric = (key, metric) => {
  const value = metric?.value;
  if (value === null || value === undefined || value === '') return null;
  const n = Number(value);
  if (/roi|ratio/i.test(key)) return Number.isFinite(n) ? `${n.toFixed(n >= 10 ? 1 : 2).replace(/\.?0+$/, '')}×` : String(value);
  if (/value|margin|cost|price|revenue|per_/i.test(key)) return money(value);
  return String(value);
};

// A plain-language verdict. Decision Kit verdicts come from code; general
// decisions get a band from the code-calculated score.
export const verdictFor = (card) => {
  const label = card?.recommendation?.label;
  if (label) return label;
  const score = cardScore(card);
  if (score === null) return 'Not scored';
  if (score >= 70) return 'Strong case';
  if (score >= 50) return 'Promising, with gaps';
  return 'Weak case';
};

const VERDICT_RANK = { Bid: 3, 'Strong case': 3, 'Bid with conditions': 2, 'Promising, with gaps': 2 };

const rubricOf = (card) => card?.scoring_rubric || card?.rubric || {};

const criteriaOf = (card) => {
  const criteria = rubricOf(card).criteria;
  return Array.isArray(criteria) ? criteria.filter((c) => c && c.key) : [];
};

const dimensionsOf = (card) => {
  const dims = card?.dimensions;
  if (!dims || typeof dims !== 'object' || Array.isArray(dims)) return [];
  const weights = Object.fromEntries(criteriaOf(card).map((c) => [c.key, Number(c.weight) || 0]));
  return Object.entries(dims)
    .filter(([, d]) => d && typeof d === 'object')
    .map(([key, d]) => ({
      key,
      label: d.label || criteriaOf(card).find((c) => c.key === key)?.label || humanize(key),
      score: Number(d.score),
      confidence: String(d.confidence || '').toLowerCase(),
      rationale: firstSentences(d.rationale || d.summary || d.reasoning, 1),
      weight: weights[key] ?? (Number(d.weight) || 0),
    }));
};

const assumptionText = (item) => {
  if (typeof item === 'string') return item;
  if (!item || typeof item !== 'object') return '';
  return item.statement || item.assumption || item.text || item.label || item.description || '';
};

const gatesOf = (card) => (Array.isArray(card?.gates) ? card.gates.filter(Boolean) : []);

const gateStatus = (gate) => String(gate?.status || gate?.result || '').toLowerCase();

// A plain-language lead built from code-owned results; the model's own
// summary is used only when it adds reasoning instead of restating a score.
function summaryFor({ featured, featuredName, cards, standings, verify }) {
  if (!featured) return '';
  const verdict = verdictFor(featured).toLowerCase();
  const sentences = [];
  if (cards.length > 1) {
    sentences.push(`We compared ${cards.length} options against the criteria. ${featuredName} is the strongest case: ${verdict}.`);
    const missing = standings.filter((s) => s.failedGates.length).map((s) => s.name);
    if (missing.length) {
      sentences.push(`${missing.join(' and ')} ${missing.length === 1 ? 'misses' : 'miss'} a must-have as things stand.`);
    }
  } else {
    sentences.push(`${featuredName}: ${verdict}.`);
    const reasoning = firstSentences(featured.executive_summary || featured.strategic_rationale, 1);
    if (reasoning && !restatesScore(reasoning)) sentences.push(reasoning);
  }
  if (verify.length) {
    sentences.push(`${verify.length === 1 ? 'One thing is' : `${Math.min(verify.length, 5)} things are`} worth checking before committing.`);
  }
  return sentences.join(' ');
}

export function buildReportModel({ artifactType, snapshot, title, createdAt }) {
  const cards = artifactType === 'tradeoff'
    ? (Array.isArray(snapshot?.scorecards) ? snapshot.scorecards : [])
    : (snapshot?.scorecard ? [snapshot.scorecard] : []);
  const context = snapshot?.context || {};
  const kit = context.decision_kit || cards.find((c) => c?.decision_kit)?.decision_kit || null;
  const objective = context.strategy_objective || snapshot?.strategy_objective || null;

  const ranked = [...cards].sort((a, b) => {
    const rank = (VERDICT_RANK[verdictFor(b)] || 0) - (VERDICT_RANK[verdictFor(a)] || 0);
    return rank || (cardScore(b) ?? -1) - (cardScore(a) ?? -1);
  });
  const featured = ranked[0] || null;

  const gateLabel = (g) => g.label || humanize(g.key);
  const headlineMetric = (card) => {
    const [key, metric] = Object.entries(card?.metrics || {}).find(([, m]) => m?.value !== null && m?.value !== undefined) || [];
    return key ? `${metric.label || humanize(key)} ${formatMetric(key, metric)}` : '';
  };
  // What decides each option, in words: a failed must-have first, then an
  // unconfirmed one, then the model's reasoning unless it only restates the score.
  const whyFor = (card) => {
    const unknown = gatesOf(card).filter((g) => ['unknown', 'pending'].includes(gateStatus(g))).map(gateLabel);
    const summary = firstSentences(card.executive_summary || card.strategic_rationale || card.executive_narrative, 1);
    const parts = [];
    if (unknown.length) parts.push(`Not confirmed yet: ${unknown.join(', ')}.`);
    if (summary && !restatesScore(summary)) parts.push(summary);
    const metric = headlineMetric(card);
    if (!parts.length && metric) parts.push(`${metric}, calculated by Jaspen.`);
    return parts.join(' ');
  };

  const standings = ranked.map((card) => ({
    name: cardName(card),
    verdict: verdictFor(card),
    score: cardScore(card),
    why: whyFor(card),
    failedGates: gatesOf(card).filter((g) => gateStatus(g) === 'fail').map(gateLabel),
  }));

  const facts = Object.entries(featured?.facts || {});
  const passedGates = gatesOf(featured).filter((g) => gateStatus(g) === 'pass').map(gateLabel);
  const supported = [
    ...facts
      .filter(([, f]) => String(f?.source || 'user').toLowerCase() !== 'assumed')
      .map(([key, f]) => `${f.label || humanize(key)}: ${formatFactValue(f)}`),
    ...(passedGates.length ? [`Must-haves met: ${passedGates.join(', ')}`] : []),
  ];
  const assumptions = [
    ...(Array.isArray(featured?.assumptions) ? featured.assumptions.map((a) => firstSentences(assumptionText(a), 1)) : []),
    ...facts
      .filter(([, f]) => String(f?.source || '').toLowerCase() === 'assumed')
      .map(([key, f]) => `${f.label || humanize(key)}: ${formatFactValue(f)} (assumed)`),
  ].filter(Boolean).slice(0, 4);
  const dims = dimensionsOf(featured);
  const weak = dims
    .filter((d) => d.confidence === 'assumed' || d.confidence === 'low')
    .sort((a, b) => b.weight - a.weight);
  const verify = [
    ...gatesOf(featured)
      .filter((g) => ['unknown', 'pending'].includes(gateStatus(g)))
      .map((g) => `${g.label || humanize(g.key)} is not confirmed yet`),
    ...weak.slice(0, 3).map((d) => d.label),
  ];

  const metrics = Object.entries(featured?.metrics || {})
    .map(([key, metric]) => ({ key, label: metric?.label || humanize(key), value: formatMetric(key, metric) }))
    .filter((m) => m.value);

  const totalWeight = dims.reduce((sum, d) => sum + (d.weight || 0), 0);
  const verifiedWeight = dims
    .filter((d) => d.confidence && !['assumed', 'low'].includes(d.confidence))
    .reduce((sum, d) => sum + (d.weight || 0), 0);
  const verifiedShare = totalWeight > 0 ? Math.round((verifiedWeight / totalWeight) * 100) : null;

  const change = weak.slice(0, 3).map((d) => ({
    label: d.label,
    detail: [d.rationale, d.weight ? `It carries ${Math.round(d.weight * 100)}% of the decision.` : '']
      .filter(Boolean).join(' '),
  }));

  const criteria = criteriaOf(featured);
  const weighted = criteria.filter((c) => !c.gate);
  const mustHaves = criteria.filter((c) => c.gate);
  const rubricApproved = ['approved'].includes(String(rubricOf(featured).status || rubricOf(featured).approval_status || '').toLowerCase());

  const failedCount = standings.filter((s) => s.failedGates.length).length;
  const takeaways = [
    featured && { title: cards.length > 1 ? 'The strongest option' : 'The option', body: `${cardName(featured)} · ${verdictFor(featured)}` },
    failedCount > 0 && { title: `${failedCount === 1 ? 'One option misses' : `${failedCount} options miss`} a must-have`, body: standings.filter((s) => s.failedGates.length).map((s) => s.name).join(', ') },
    change[0] && { title: 'The biggest unknown', body: change[0].label },
    criteria.length > 0 && { title: rubricApproved ? 'Criteria you set' : 'Criteria proposed by Jaspen', body: `${weighted.length} weighted criteria${mustHaves.length ? ` plus ${mustHaves.length} must-have${mustHaves.length > 1 ? 's' : ''}` : ''}.` },
    { title: 'Leadership makes the call', body: 'Jaspen informs. Your team decides.', accent: true },
  ].filter(Boolean);

  const tags = [
    objective && OBJECTIVE_LABELS[objective] && { kind: 'Objective', label: OBJECTIVE_LABELS[objective] },
    kit && { kind: 'Decision Kit', label: KIT_LABELS[kit] || humanize(kit) },
    ...(Array.isArray(context.data_sources) ? context.data_sources : [])
      .map((s) => ({ kind: 'Data', label: DATA_SOURCE_LABELS[String(s).toLowerCase()] || humanize(s) })),
  ].filter(Boolean);

  const featuredName = featured ? cardName(featured) : '';
  const defaults = {
    // Thread names are often the first message, so only a real question is
    // reused as the headline; otherwise the decision question is phrased here.
    headline: artifactType === 'tradeoff'
      ? (String(title || '').trim().endsWith('?') && String(title).length <= 140 ? String(title).trim() : 'Which option should we choose?')
      : `Should we pursue ${featuredName}?`,
    summary: summaryFor({ featured, featuredName, cards, standings, verify }),
    featured_question: featured ? `Should we commit to ${featuredName}?` : '',
    takeaway_title: 'What leadership should know',
    next_step_title: verify.length
      ? `Next step: check ${verify.length === 1 ? 'one thing' : `${Math.min(verify.length, 5)} things`}, then decide.`
      : 'Next step: record the decision.',
    next_step_body: verify.length
      ? `${verify.slice(0, 3).join('. ')}. Then record the decision so the plan can be built.`
      : 'Record the decision in Jaspen so the execution plan can be built from it.',
  };

  return {
    masthead: KIT_MASTHEADS[kit] || 'DECISION REPORT',
    tags,
    preparedOn: createdAt ? new Date(createdAt).toLocaleDateString(undefined, { year: 'numeric', month: 'short', day: 'numeric' }) : '',
    rubricApproved,
    cardCount: cards.length,
    standings,
    featured: featured ? {
      name: featuredName,
      verdict: verdictFor(featured),
      score: cardScore(featured),
      supported,
      assumptions,
      verify,
      metrics,
    } : null,
    strength: featured ? { score: cardScore(featured), verifiedShare } : null,
    change,
    takeaways,
    numbersNote: 'How the numbers work: figures are calculated from your inputs; criterion scores are Jaspen’s assessment. Confidence does not mean correctness. Please review your data for accuracy.',
    criteria: {
      weighted: weighted.map((c) => ({ label: c.label || humanize(c.key), weight: Math.round((Number(c.weight) || 0) * 100) })),
      mustHaves: mustHaves.map((c) => c.label || humanize(c.key)),
    },
    defaults,
  };
}

// Owner edits win for wording, colors and layout; numbers stay derived.
export function applyPresentation(model, presentation = {}) {
  const text = { ...model.defaults, ...(presentation.text || {}) };
  const colors = { ...DEFAULT_COLORS, ...(presentation.colors || {}) };
  const layout = presentation.layout || {};
  const order = Array.isArray(layout.order) && layout.order.length === REPORT_SECTIONS.length
    ? layout.order
    : REPORT_SECTIONS.map((s) => s.key);
  const hidden = new Set(layout.hidden || []);
  return {
    text,
    colors,
    order,
    hidden,
    evidenceVariant: layout.evidence_variant === 'compact' ? 'compact' : 'detailed',
  };
}
