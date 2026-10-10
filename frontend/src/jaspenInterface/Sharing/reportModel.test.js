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
    delivery: { score: 45, confidence: 'assumed', rationale: 'No staffing data yet.' },
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
    'Surety / bond confirmation met',
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
  expect(model.strength).toEqual({ score: 64, verifiedShare: 60 });
  expect(model.change[0]).toEqual({
    label: 'Delivery capacity',
    detail: 'No staffing data yet. It carries 40% of the decision.',
  });
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
