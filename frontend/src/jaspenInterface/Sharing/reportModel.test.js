import { applyPresentation, buildReportModel } from './reportModel';

const bid = (name, score, label, extra = {}) => ({
  project_name: name,
  jaspen_score: score,
  decision_kit: 'rfp_bid',
  recommendation: { label },
  executive_summary: `${name} is the case. Second sentence. Third sentence.`,
  scoring_rubric: {
    status: 'approved',
    criteria: [
      { key: 'win', label: 'Win probability', weight: 0.6 },
      { key: 'delivery', label: 'Delivery capacity', weight: 0.4 },
      { key: 'surety_confirmation', label: 'Surety / bond confirmation', gate: true, weight: 0 },
    ],
  },
  dimensions: {
    win: { score: 70, confidence: 'medium', rationale: 'Based on past jobs.' },
    delivery: { score: 45, confidence: 'assumed', rationale: 'No staffing data yet.', what_would_improve: 'Share crew availability for the bid window.' },
  },
  ...extra,
});

const snapshot = {
  context: { strategy_objective: 'speed', decision_kit: 'rfp_bid', data_sources: ['salesforce'] },
  scorecards: [
    bid('CDOT bridge rehab', 40, 'No-Bid', { gates: [{ key: 'surety_confirmation', label: 'Surety / bond confirmation', status: 'fail' }] }),
    bid('Denver Water pump station', 64, 'Bid', {
      facts: {
        contract_value: { value: 2400000, unit: 'USD', source: 'user' },
        win_probability: { value: 35, unit: 'percent_points', source: 'user' },
        margin_pct: { value: 18, unit: 'percent_points', source: 'assumed' },
      },
      gates: [{ key: 'surety_confirmation', label: 'Surety / bond confirmation', status: 'pass' }],
      metrics: {
        expected_value: { value: 151200, label: 'Expected margin' },
        pursuit_roi: { value: 3.36, label: 'Pursuit ROI' },
      },
    }),
  ],
};

test('features the strongest verdict and keeps numbers from code', () => {
  const model = buildReportModel({ artifactType: 'tradeoff', snapshot, title: 'Q4 bids' });

  expect(model.masthead).toBe('RFP BID / NO-BID DECISION');
  expect(model.featured.name).toBe('Denver Water pump station');
  expect(model.featured.verdict).toBe('Bid');
  expect(model.featured.metrics).toEqual([
    { key: 'expected_value', label: 'Expected margin', value: '$151,200' },
    { key: 'pursuit_roi', label: 'Pursuit ROI', value: '3.36×' },
  ]);
  expect(model.featured.supported).toEqual([
    'Contract Value: $2,400,000',
    'Win Probability: 35%',
    'Must-haves met: Surety / bond confirmation',
  ]);
  expect(model.featured.assumptions).toEqual(['Margin: 18% (assumed)']);
  expect(model.standings.map((s) => s.name)).toEqual(['Denver Water pump station', 'CDOT bridge rehab']);
  expect(model.standings[1].failedGates).toEqual(['Surety / bond confirmation']);
});

test('context tags show objective, kit and data sources actually used', () => {
  const model = buildReportModel({ artifactType: 'tradeoff', snapshot, title: '' });
  expect(model.tags).toEqual([
    { kind: 'Objective', label: 'Speed to Market' },
    { kind: 'Decision Kit', label: 'RFP response' },
    { kind: 'Data', label: 'Salesforce' },
  ]);
});

test('case strength splits weight between stated facts and assumptions', () => {
  const model = buildReportModel({ artifactType: 'tradeoff', snapshot, title: '' });
  expect(model.strength).toEqual({ score: 64, initialScore: null, verifiedShare: 60, raiseConfidence: ['Delivery capacity'] });
  expect(model.change[0]).toEqual({
    label: 'Delivery capacity',
    evidence: 'none',
    score: 45,
    detail: 'Carries 40% of the decision.',
    strengthen: 'Share crew availability for the bid window.',
  });
});

test('case strength keeps the evidence-adjusted score primary and only exposes a different initial assessment', () => {
  const adjusted = buildReportModel({
    artifactType: 'scorecard',
    snapshot: { scorecard: bid('Denver', 52, 'Bid with conditions', { initial_jaspen_score: 71 }) },
    title: 'Denver',
  });
  expect(adjusted.strength).toMatchObject({ score: 52, initialScore: 71 });

  const unchanged = buildReportModel({
    artifactType: 'scorecard',
    snapshot: { scorecard: bid('Denver', 52, 'Bid with conditions', { initial_jaspen_score: 52 }) },
    title: 'Denver',
  });
  expect(unchanged.strength).toMatchObject({ score: 52, initialScore: 52 });
});

test('carries production guidance: exposure and recommended moves', () => {
  const withGuidance = {
    scorecard: bid('Denver', 64, 'Bid', {
      top_risks: [{ risk: 'Crew overlap with the Q4 job. More detail.', mitigation: 'Line up a subcontractor crew.' }, 'Steel price swings'],
      recommendations: [{ action: 'Lock a steel quote', expected_impact: 'High', effort: 'Low' }, 'Confirm crew plan'],
    }),
  };
  const model = buildReportModel({ artifactType: 'scorecard', snapshot: withGuidance, title: 'Denver' });
  expect(model.exposure.risks).toEqual([
    { risk: 'Crew overlap with the Q4 job.', mitigation: 'Line up a subcontractor crew.' },
    { risk: 'Steel price swings', mitigation: '' },
  ]);
  expect(model.exposure.moves).toEqual([
    { text: 'Lock a steel quote', chips: ['Impact: High', 'Effort: Low'] },
    { text: 'Confirm crew plan', chips: [] },
  ]);
});

test('a score shared by every weak criterion is shown once', () => {
  const same = { scorecard: bid('X', 50, 'Bid', { dimensions: {
    win: { score: 45, confidence: 'assumed' }, delivery: { score: 45, confidence: 'low' },
  } }) };
  const model = buildReportModel({ artifactType: 'scorecard', snapshot: same, title: 'X' });
  expect(model.sharedChangeScore).toBe(45);
  expect(model.change.map((c) => c.evidence)).toEqual(['none', 'weak']);

  const different = { scorecard: bid('X', 50, 'Bid', { dimensions: {
    win: { score: 40, confidence: 'high' }, delivery: { score: 45, confidence: 'assumed' },
  } }) };
  const model2 = buildReportModel({ artifactType: 'scorecard', snapshot: different, title: 'X' });
  expect(model2.sharedChangeScore).toBeNull();
  expect(model2.change.find((c) => c.label === 'Win probability').evidence).toBe('strong');
});

test('production sections appear only when the scorecard has content for them', () => {
  const rich = { scorecard: bid('Denver', 64, 'Bid', {
    executive_summary: 'First paragraph.\n\nSecond paragraph.',
    key_insights: ['Margin is healthy', { summary: 'Client relationship is new' }],
    financial_impact: { roi_opportunity: '$151K', _numeric: { x: 1 } },
    npv_irr_analysis: { npv: 120000, assumptions: { discount_rate: '8%' } },
    decision_framework: { recommendation: 'Proceed with conditions', key_question: 'Can we staff it?' },
    ai_insights: [{ file_name: 'pipeline.csv', summary: 'Two similar bids won last year' }],
    assumptions: ['Crew available in Q4', 'Steel prices hold'],
  }) };
  const model = buildReportModel({ artifactType: 'scorecard', snapshot: rich, title: 'Denver' });
  expect(model.executive).toEqual(['First paragraph.', 'Second paragraph.']);
  expect(model.drivers).toEqual(['Margin is healthy', 'Client relationship is new']);
  expect(model.breakdown.map((r) => r.label)).toEqual(['Win probability', 'Delivery capacity']);
  expect(model.financials).toEqual([
    { title: 'Financial impact', rows: [{ label: 'Roi Opportunity', value: '$151K' }] },
    { title: 'NPV & IRR', rows: [{ label: 'Npv', value: '120,000' }, { label: 'Assumptions: Discount Rate', value: '8%' }] },
  ]);
  expect(model.framework).toEqual([
    { label: 'Recommendation', value: 'Proceed with conditions' },
    { label: 'Key Question', value: 'Can we staff it?' },
  ]);
  expect(model.insights).toEqual([{ source: 'pipeline.csv', text: 'Two similar bids won last year' }]);
  expect(model.sharpen).toEqual(['Crew available in Q4', 'Steel prices hold']);

  const bare = buildReportModel({ artifactType: 'scorecard', snapshot: { scorecard: { project_name: 'X', jaspen_score: 50 } }, title: 'X' });
  expect([bare.executive, bare.drivers, bare.financials, bare.framework, bare.insights, bare.sharpen]).toEqual([[], [], [], [], [], []]);
});

test('an older saved layout keeps its order and gains new sections', () => {
  const model = buildReportModel({ artifactType: 'tradeoff', snapshot, title: '' });
  const view = applyPresentation(model, { layout: { order: ['standings', 'strength', 'featured', 'change', 'exposure', 'takeaways', 'criteria', 'next_step'] } });
  expect(view.order.slice(0, 3)).toEqual(['standings', 'strength', 'executive']);
  expect(view.order).toHaveLength(15);
});

test('every criterion carries what would help, and "None" reads as satisfied', () => {
  const card = { scorecard: bid('X', 60, 'Bid', { dimensions: {
    win: { score: 75, confidence: 'medium', what_would_improve: 'Name the incumbent.' },
    delivery: { score: 90, confidence: 'high', what_would_improve: 'None' },
  } }) };
  const model = buildReportModel({ artifactType: 'scorecard', snapshot: card, title: 'X' });
  const byLabel = Object.fromEntries(model.breakdown.map((r) => [r.label, r]));
  expect(byLabel['Win probability']).toMatchObject({ help: 'Name the incumbent.', satisfied: false });
  expect(byLabel['Delivery capacity']).toMatchObject({ help: '', satisfied: true });
});

test('branding defaults can be replaced by the owner', () => {
  const model = buildReportModel({ artifactType: 'tradeoff', snapshot, title: '' });
  expect(model.defaults).toMatchObject({ brand_name: 'JASPEN', report_label: 'RFP BID / NO-BID DECISION', company_name: '' });
  const view = applyPresentation(model, { text: { brand_name: 'Acme Builders', company_name: 'Acme Builders LLC' } });
  expect(view.text.brand_name).toBe('Acme Builders');
  expect(view.text.report_label).toBe('RFP BID / NO-BID DECISION');
});

test('the strongest case lists key facts as label/value pairs', () => {
  const model = buildReportModel({ artifactType: 'tradeoff', snapshot, title: '' });
  expect(model.featured.keyFacts).toEqual([
    { label: 'Contract Value', value: '$2,400,000' },
    { label: 'Win Probability', value: '35%' },
  ]);
  expect(model.featured.mustHavesMet).toEqual(['Surety / bond confirmation']);
});

test('criteria separate weighted criteria from must-haves', () => {
  const model = buildReportModel({ artifactType: 'tradeoff', snapshot, title: '' });
  expect(model.rubricApproved).toBe(true);
  expect(model.criteria).toEqual({
    weighted: [{ label: 'Win probability', weight: 60 }, { label: 'Delivery capacity', weight: 40 }],
    mustHaves: ['Surety / bond confirmation'],
  });
});

test('a long thread name is not used as the headline', () => {
  const model = buildReportModel({ artifactType: 'tradeoff', snapshot, title: "We're a construction firm deciding which bids" });
  expect(model.defaults.headline).toBe('Which option should we choose?');
});

test('strength comes first by default', () => {
  const model = buildReportModel({ artifactType: 'tradeoff', snapshot, title: '' });
  expect(applyPresentation(model).order[0]).toBe('strength');
});

test('summary and reasons say what decides each option instead of restating scores', () => {
  const restating = { ...snapshot, scorecards: snapshot.scorecards.map((c) => ({ ...c, executive_summary: `${c.project_name} scores ${c.jaspen_score}/100 based on the information currently available.` })) };
  const model = buildReportModel({ artifactType: 'tradeoff', snapshot: restating, title: '' });
  expect(model.defaults.summary).toBe('We compared 2 options against the criteria. Denver Water pump station is the strongest case: bid. CDOT bridge rehab misses a must-have as things stand. One thing is worth checking before committing.');
  expect(model.standings[0].why).toBe('Expected margin $151,200, calculated by Jaspen.');
  expect(model.standings.map((s) => s.why).join(' ')).not.toMatch(/\/100/);
});

test('dates read as dates', () => {
  const dated = { scorecard: { project_name: 'X', jaspen_score: 60, facts: { submission_due: { value: '2026-11-20', source: 'user' } } } };
  const model = buildReportModel({ artifactType: 'scorecard', snapshot: dated, title: 'X' });
  expect(model.featured.supported).toEqual(['Submission Due: Nov 20, 2026']);
});

test('general decisions without a kit get a plain-language verdict band', () => {
  const model = buildReportModel({
    artifactType: 'scorecard',
    snapshot: { scorecard: { project_name: 'Kiosk', jaspen_score: 45 } },
    title: 'Kiosk',
  });
  expect(model.masthead).toBe('DECISION REPORT');
  expect(model.featured.verdict).toBe('Weak case');
  expect(model.defaults.headline).toBe('Should we pursue Kiosk?');
});

test('presentation edits change wording, colors and layout only', () => {
  const model = buildReportModel({ artifactType: 'tradeoff', snapshot, title: '' });
  const view = applyPresentation(model, {
    text: { headline: 'Which bids this quarter?' },
    colors: { accent: '#0F6E77' },
    layout: { hidden: ['takeaways'], evidence_variant: 'compact' },
  });
  expect(view.text.headline).toBe('Which bids this quarter?');
  expect(view.text.summary).toBe(model.defaults.summary);
  expect(view.colors).toEqual({ accent: '#0F6E77', ink: '#1B2342', tint: '#EEF5F7' });
  expect(view.hidden.has('takeaways')).toBe(true);
  expect(view.evidenceVariant).toBe('compact');
  expect(model.featured.metrics[0].value).toBe('$151,200');
});

test('a brand color set from chat colors the one-pager unless the report has its own accent', () => {
  const card = (overrides) => ({ scorecard: bid('Denver', 64, 'Bid', { display_overrides: overrides }) });
  const accentFor = (snap, presentation) => (
    applyPresentation(buildReportModel({ artifactType: 'scorecard', snapshot: snap, title: 'X' }), presentation).colors.accent
  );

  expect(accentFor(card({ accent_color: '#0a66c2' }))).toBe('#0A66C2');
  expect(accentFor({ scorecard: bid('Denver', 64, 'Bid', { _accent_color: '#0A66C2' }) })).toBe('#0A66C2');
  expect(accentFor(card({ accent_color: '#0a66c2' }), { colors: { accent: '#0F6E77' } })).toBe('#0F6E77');
  // Unreadable or malformed colors keep the default.
  expect(accentFor(card({ accent_color: '#ffff00' }))).toBe('#A0036C');
  expect(accentFor(card({ accent_color: 'blue' }))).toBe('#A0036C');
  // A share snapshot carries the color in presentation and renders the same.
  expect(accentFor({ scorecard: bid('Denver', 64, 'Bid') }, { colors: { accent: '#0A66C2' } })).toBe('#0A66C2');
});
