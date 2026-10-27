// Turns a frozen share snapshot into the content of the one-pager report.
// Every number shown comes from code-owned fields on the snapshot (score,
// metrics, gates, rubric weights). Wording is derived here and may be
// replaced by the owner's presentation edits, but numbers never are.

export const REPORT_SECTIONS = [
  { key: 'strength', label: 'How strong is the case?' },
  { key: 'executive', label: 'Executive summary' },
  { key: 'standings', label: 'Where each option stands' },
  { key: 'featured', label: 'The strongest case' },
  { key: 'drivers', label: 'What drove this score' },
  { key: 'breakdown', label: 'How each criterion scored' },
  { key: 'change', label: 'Where it’s weak, and how to make it stronger' },
  { key: 'exposure', label: 'Risks, mitigations and next moves' },
  { key: 'financials', label: 'Financial picture' },
  { key: 'framework', label: 'Decision framework' },
  { key: 'insights', label: 'Insights from your data' },
  { key: 'sharpen', label: 'What would sharpen this score' },
  { key: 'takeaways', label: 'What leadership should know' },
  { key: 'criteria', label: 'The criteria you approved' },
  { key: 'next_step', label: 'Next step' },
];

export const DEFAULT_COLORS = { accent: '#A0036C', ink: '#1B2342', tint: '#EEF5F7' };

const HEX_COLOR = /^#[0-9a-f]{6}$/i;

// The same readability rule the server applies to presentation colors:
// white text on the accent needs a 4.5:1 contrast ratio.
export const readableOnWhite = (hex) => {
  const linear = [1, 3, 5].map((i) => {
    const c = parseInt(hex.slice(i, i + 2), 16) / 255;
    return c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4;
  });
  const luminance = 0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2];
  return 1.05 / (luminance + 0.05) >= 4.5;
};

// The lightest darker version of a color that passes the rule above, keeping
// its hue, so an owner who picks a brand color too light to read gets the
// nearest shade that works instead of a dead end.
export const closestReadableShade = (hex) => {
  if (!HEX_COLOR.test(String(hex || ''))) return null;
  if (readableOnWhite(hex)) return hex.toUpperCase();
  const channels = [1, 3, 5].map((i) => parseInt(hex.slice(i, i + 2), 16));
  for (let factor = 0.99; factor > 0; factor -= 0.01) {
    const shade = `#${channels
      .map((c) => Math.round(c * factor).toString(16).padStart(2, '0'))
      .join('')}`.toUpperCase();
    if (readableOnWhite(shade)) return shade;
  }
  return '#000000';
};

// A brand color set from chat lives on the card's display_overrides. It colors
// the one-pager unless the report has its own accent.
const cardAccent = (card) => {
  const value = String(card?.display_overrides?.accent_color || card?._accent_color || '').trim();
  return HEX_COLOR.test(value) && readableOnWhite(value) ? value.toUpperCase() : null;
};

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

const numericValue = (value) => {
  if (value === null || value === undefined || value === '') return null;
  const numeric = Number(value);
  return Number.isFinite(numeric) ? numeric : null;
};

export const cardScore = (card) => {
  const value = card?.jaspen_score ?? card?.score;
  const numeric = numericValue(value);
  return numeric === null ? null : Math.round(numeric);
};

const initialCardScore = (card) => {
  const value = card?.initial_jaspen_score;
  const numeric = numericValue(value);
  return numeric === null ? null : Math.round(numeric);
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
  if (value === null || value === undefined || value === '') return null;
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

// The scorecard writes "None" when nothing more is needed for a criterion.
const NO_ADVICE = /^(none|n\/a|na|nothing|no further action( needed)?)\.?$/i;

const dimensionsOf = (card) => {
  const dims = card?.dimensions;
  if (!dims || typeof dims !== 'object' || Array.isArray(dims)) return [];
  const weights = Object.fromEntries(criteriaOf(card).map((c) => [c.key, Number(c.weight) || 0]));
  return Object.entries(dims)
    .filter(([, d]) => d && typeof d === 'object')
    .map(([key, d]) => ({
      key,
      label: d.label || criteriaOf(card).find((c) => c.key === key)?.label || humanize(key),
      score: numericValue(d.score),
      confidence: String(d.confidence || '').toLowerCase(),
      rationale: firstSentences(d.rationale || d.summary || d.reasoning, 1),
      improve: NO_ADVICE.test(String(d.what_would_improve ?? '').trim()) ? '' : firstSentences(d.what_would_improve || d.improvement || d.how_to_improve, 1),
      satisfied: NO_ADVICE.test(String(d.what_would_improve ?? '').trim()) && String(d.what_would_improve ?? '').trim() !== '',
      weight: weights[key] ?? (Number(d.weight) || 0),
      gate: Boolean(criteriaOf(card).find((c) => c.key === key)?.gate),
    }));
};

const assumptionText = (item) => {
  if (typeof item === 'string') return item;
  if (!item || typeof item !== 'object') return '';
  return item.statement || item.assumption || item.text || item.label || item.description || '';
};

// Flattens a scorecard object (financial impact, valuation, framework…) into
// readable label/value rows. Only plain values are shown; nested detail
// stays in "See how this was scored".
const plainValue = (value) => {
  if (value === null || value === undefined || value === '') return null;
  if (typeof value === 'number') return Number.isFinite(value) ? value.toLocaleString('en-US') : null;
  if (typeof value === 'boolean') return value ? 'Yes' : 'No';
  if (typeof value === 'string') return value.trim() || null;
  if (Array.isArray(value)) {
    const parts = value.map((item) => (typeof item === 'object' && item ? (item.text || item.title || item.description || item.label) : item))
      .map(plainValue).filter(Boolean);
    return parts.length ? parts.join('; ') : null;
  }
  return null;
};

export const flattenRows = (obj) => {
  if (!obj || typeof obj !== 'object' || Array.isArray(obj)) return [];
  const rows = [];
  Object.entries(obj).forEach(([key, value]) => {
    if (key.startsWith('_')) return;
    const direct = plainValue(value);
    if (direct !== null) {
      rows.push({ label: humanize(key), value: direct });
      return;
    }
    if (value && typeof value === 'object' && !Array.isArray(value)) {
      Object.entries(value).forEach(([innerKey, inner]) => {
        if (innerKey.startsWith('_')) return;
        const innerValue = plainValue(inner);
        if (innerValue !== null) rows.push({ label: `${humanize(key)}: ${humanize(innerKey)}`, value: innerValue });
      });
    }
  });
  return rows;
};

const textOf = (entry) => {
  if (typeof entry === 'string') return entry.trim();
  if (!entry || typeof entry !== 'object') return '';
  return String(entry.summary || entry.title || entry.description || entry.text || entry.insight?.insight_text || '').trim();
};

const riskText = (item) => {
  if (typeof item === 'string') return item;
  if (!item || typeof item !== 'object') return '';
  return item.risk || item.text || item.title || item.description || '';
};

const recommendationOf = (item) => {
  if (typeof item === 'string') return { text: item, chips: [] };
  if (!item || typeof item !== 'object') return null;
  const text = item.action || item.title || item.recommendation || item.description || item.text || '';
  const chips = [['Impact', item.expected_impact], ['Effort', item.effort], ['Timing', item.timeline]]
    .filter(([, value]) => value)
    .map(([label, value]) => `${label}: ${value}`);
  return text ? { text, chips } : null;
};

const evidenceLevel = (d) => {
  if (!d.confidence || d.confidence === 'assumed' || d.confidence === 'none') return 'none';
  if (d.confidence === 'high') return 'strong';
  return 'weak';
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

  // Share snapshots carry `facts`; the live card in Workspace keeps them in
  // its canonical decision state.
  const facts = Object.entries(featured?.facts || featured?.decision_state?.facts || {})
    .filter(([, f]) => f && typeof f === 'object' && f.value !== null && f.value !== undefined && f.value !== '');
  const passedGates = gatesOf(featured).filter((g) => gateStatus(g) === 'pass').map(gateLabel);
  const keyFacts = facts
    .filter(([, f]) => String(f?.source || 'user').toLowerCase() !== 'assumed')
    .map(([key, f]) => ({ label: f.label || humanize(key), value: formatFactValue(f) }));
  const supported = [
    ...keyFacts.map((f) => `${f.label}: ${f.value}`),
    ...(passedGates.length ? [`Must-haves met: ${passedGates.join(', ')}`] : []),
  ];
  const assumptions = [
    ...(Array.isArray(featured?.assumptions) ? featured.assumptions.map((a) => firstSentences(assumptionText(a), 1)) : []),
    ...facts
      .filter(([, f]) => String(f?.source || '').toLowerCase() === 'assumed')
      .map(([key, f]) => `${f.label || humanize(key)}: ${formatFactValue(f)} (assumed)`),
  ].filter(Boolean).slice(0, 4);
  const allDims = dimensionsOf(featured);
  // Must-haves are pass/fail checks, not weighted scores.
  const dims = allDims.filter((d) => !d.gate);
  const isAssumed = (d) => d.confidence === 'assumed' || d.confidence === 'low';
  const weak = dims
    .filter((d) => isAssumed(d) || (Number.isFinite(d.score) && d.score < 60))
    .sort((a, b) => (b.weight - a.weight) || (a.score - b.score));
  const verify = [
    ...gatesOf(featured)
      .filter((g) => ['unknown', 'pending'].includes(gateStatus(g)))
      .map((g) => `${g.label || humanize(g.key)} is not confirmed yet`),
    ...weak.filter(isAssumed).slice(0, 3).map((d) => d.label),
  ];

  const metrics = Object.entries(featured?.metrics || {})
    .map(([key, metric]) => ({ key, label: metric?.label || humanize(key), value: formatMetric(key, metric) }))
    .filter((m) => m.value);

  const totalWeight = dims.reduce((sum, d) => sum + (d.weight || 0), 0);
  const verifiedWeight = dims
    .filter((d) => d.confidence && !['assumed', 'low'].includes(d.confidence))
    .reduce((sum, d) => sum + (d.weight || 0), 0);
  const verifiedShare = totalWeight > 0 ? Math.round((verifiedWeight / totalWeight) * 100) : null;

  // Production's "Improve next" advice travels with each weak criterion,
  // labeled by how much evidence stands behind it.
  const change = weak.slice(0, 3).map((d) => ({
    label: d.label,
    evidence: evidenceLevel(d),
    score: Number.isFinite(d.score) ? Math.round(d.score) : null,
    // The full reasoning lives in "How each criterion scored"; this is the
    // short priority list of what to fix first.
    detail: d.weight ? `Carries ${Math.round(d.weight * 100)}% of the decision.` : '',
    strengthen: d.improve,
  }));
  const changeScores = [...new Set(change.map((c) => c.score).filter((v) => v !== null))];
  const sharedChangeScore = change.length > 1 && changeScores.length === 1 && change.every((c) => c.score !== null)
    ? changeScores[0]
    : null;
  const raiseConfidence = weak.filter(isAssumed).slice(0, 3).map((d) => d.label);

  const exposure = {
    risks: (featured?.top_risks || featured?.risks || [])
      .map((r) => ({
        risk: firstSentences(riskText(r), 1),
        mitigation: typeof r === 'object' && r ? firstSentences(r.mitigation || r.mitigation_plan || r.response || '', 1) : '',
      }))
      .filter((r) => r.risk)
      .slice(0, 4),
    moves: (featured?.recommendations || []).map(recommendationOf).filter(Boolean).slice(0, 3),
  };

  // Production scorecard sections, carried over when they have content.
  const executive = String(featured?.executive_summary || featured?.executive_narrative || '')
    .split(/\n\n+/).map((p) => p.trim()).filter(Boolean);
  const keyInsights = Array.isArray(featured?.key_insights)
    ? featured.key_insights
    : (typeof featured?.key_insights === 'string' ? [featured.key_insights] : []);
  const drivers = [...new Set(keyInsights.map(textOf).filter(Boolean))].slice(0, 5);
  const breakdown = dims.map((d) => ({
    label: d.label,
    weight: d.weight ? Math.round(d.weight * 100) : null,
    score: Number.isFinite(d.score) ? Math.round(d.score) : null,
    evidence: evidenceLevel(d),
    rationale: d.rationale,
    help: d.improve,
    satisfied: d.satisfied,
  })).sort((a, b) => (b.weight || 0) - (a.weight || 0));
  const GATE_STATUS_LABELS = { pass: 'Passed', fail: 'Failed', unknown: 'Not confirmed', pending: 'Not confirmed' };
  const mustHaveRows = gatesOf(featured).map((g) => ({
    label: gateLabel(g),
    status: GATE_STATUS_LABELS[gateStatus(g)] || 'Not confirmed',
    tone: gateStatus(g) === 'pass' ? 'strong' : gateStatus(g) === 'fail' ? 'none' : 'weak',
  }));
  const financials = [
    ['Financial impact', featured?.financial_impact],
    ['Investment analysis', featured?.investment_analysis],
    ['NPV & IRR', featured?.npv_irr_analysis],
    ['Valuation', featured?.valuation],
    ['Before', featured?.before_after_financials?.before],
    ['After', featured?.before_after_financials?.after],
  ].map(([title, obj]) => ({ title, rows: flattenRows(obj).slice(0, 8) })).filter((g) => g.rows.length);
  const framework = flattenRows(featured?.decision_framework || featured?.strategic_decision_framework).slice(0, 10);
  const insights = (Array.isArray(featured?.ai_insights) ? featured.ai_insights : [])
    .map((entry) => ({ source: String(entry?.file_name || entry?.insight?.file_name || '').trim(), text: textOf(entry) }))
    .filter((item) => item.text).slice(0, 5);
  const sharpen = (Array.isArray(featured?.assumptions) ? featured.assumptions : [])
    .map(assumptionText).map((t) => String(t).trim()).filter(Boolean);

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
    brand_name: 'JASPEN',
    report_label: KIT_MASTHEADS[kit] || 'DECISION REPORT',
    tagline: 'Evidence. Assumptions. Trade-offs.',
    company_name: '',
    next_step_title: verify.length
      ? `Next step: check ${verify.length === 1 ? 'one thing' : `${Math.min(verify.length, 5)} things`}, then decide.`
      : 'Next step: record the decision.',
    next_step_body: verify.length
      ? `${verify.slice(0, 3).join('. ')}. Then record the decision so the plan can be built.`
      : 'Record the decision in Jaspen so the execution plan can be built from it.',
  };

  const accent = artifactType === 'scorecard' ? cardAccent(featured) : null;

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
      keyFacts,
      mustHavesMet: passedGates,
      assumptions,
      verify,
      metrics,
    } : null,
    strength: featured ? {
      score: cardScore(featured),
      initialScore: initialCardScore(featured),
      verifiedShare,
      raiseConfidence,
    } : null,
    change,
    sharedChangeScore,
    exposure,
    executive,
    drivers,
    breakdown,
    mustHaveRows,
    financials,
    framework,
    insights,
    sharpen,
    takeaways,
    numbersNote: 'How the numbers work: figures are calculated from your inputs; criterion scores are Jaspen’s assessment. Confidence does not mean correctness. Please review your data for accuracy.',
    criteria: {
      weighted: weighted.map((c) => ({ label: c.label || humanize(c.key), weight: Math.round((Number(c.weight) || 0) * 100) })),
      mustHaves: mustHaves.map((c) => c.label || humanize(c.key)),
    },
    defaults,
    baseColors: accent ? { accent } : {},
  };
}

// Owner edits win for wording, colors and layout; numbers stay derived.
export function applyPresentation(model, presentation = {}) {
  const text = { ...model.defaults, ...(presentation.text || {}) };
  const colors = { ...DEFAULT_COLORS, ...(model.baseColors || {}), ...(presentation.colors || {}) };
  const layout = presentation.layout || {};
  const known = REPORT_SECTIONS.map((section) => section.key);
  const saved = Array.isArray(layout.order) ? layout.order.filter((key) => known.includes(key)) : [];
  // Sections added after an owner saved a layout slot into their default place.
  const order = saved.length
    ? known.reduce((acc, key) => {
      if (acc.includes(key)) return acc;
      const index = known.indexOf(key);
      const before = known.slice(0, index).reverse().find((k) => acc.includes(k));
      const at = before ? acc.indexOf(before) + 1 : 0;
      return [...acc.slice(0, at), key, ...acc.slice(at)];
    }, saved)
    : known;
  const hidden = new Set(layout.hidden || []);
  return {
    text,
    colors,
    order,
    hidden,
    evidenceVariant: layout.evidence_variant === 'compact' ? 'compact' : 'detailed',
  };
}
