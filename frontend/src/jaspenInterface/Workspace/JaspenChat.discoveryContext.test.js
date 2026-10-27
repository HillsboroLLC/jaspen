import fs from 'fs';
import path from 'path';

const source = fs.readFileSync(path.join(__dirname, 'JaspenChat.jsx'), 'utf8');
const clientSource = fs.readFileSync(path.join(__dirname, 'JaspenClient.jsx'), 'utf8');
const connectorStateSource = fs.readFileSync(path.join(__dirname, 'connectorContextState.js'), 'utf8');
const connectorChipSource = fs.readFileSync(path.join(__dirname, 'ConnectorContextChip.jsx'), 'utf8');

test('Discovery presents objective, Decision Kit, and honest Data Context separately', () => {
  const objectiveBlock = source.slice(source.indexOf('const renderObjectiveTags'), source.indexOf('const renderDecisionKitTags'));
  expect(objectiveBlock).not.toContain('RFP');
  expect(source).toContain('<span className="jas-objective-tags-label">Decision Kit</span>');
  expect(source).toContain("{ id: 'jira_sync', label: 'Jira' }");
  expect(source).toContain("{ id: 'salesforce_insights', label: 'Salesforce' }");
  expect(source).toContain("{ id: 'snowflake_insights', label: 'Snowflake' }");
  expect(connectorChipSource).toContain('jas-connector-status-dot');
  expect(connectorStateSource).toContain('Connect ${label} in Data Sources');
});

test('batch scoring failure keeps an explicit Retry action', () => {
  expect(source).toContain("actionLabel: 'Retry'");
  expect(source).toContain('scoreQueueError: Boolean');
  expect(source).toContain('canRetryScoreQueue');
  expect(source).toContain('void refreshBundle(activeThreadId)');
});

test('queued scoring persists one named option per request', () => {
  expect(source).toContain('for (const item of items)');
  expect(source).toContain('await Jaspen.scoreNext(tid, item.name)');
  expect(source).toContain('await refreshBundle(tid)');
  expect(source).not.toContain('await Jaspen.scoreBatch(tid)');
  expect(clientSource).toContain("postJSON(endpoints.scoreNext(threadId), { name }");
});

test('active objective and RFP kit render in the upper-right context', () => {
  expect(source).toContain('className="jas-context-right"');
  expect(source).toContain('Session objective:');
  expect(source).toContain('Active Decision Kit: RFP');
  expect(source).toContain('isRfpDecision(decisionKit)');
  expect(source).toContain('new Set([...usedContextSourceIds])');
  expect(source).toContain('connectedDataSources.filter((src) => usedIds.has(src.id))');
});

test('Jira is available but never auto-selected and the session chip controls prompt inclusion', () => {
  expect(source).not.toContain('defaultActive:');
  expect(source).not.toContain('dataContextDefaultsAppliedRef');
  expect(source).toContain('dataContextConnectorIds: Array.isArray(options.dataContextConnectorIds)');
  expect(source).toContain('dataContextConnectorIds: successfulContextIds');
  expect(clientSource).toContain('data_context_connector_ids: Array.isArray(data_context_connector_ids)');
});

test('failed context is excluded from the AI connector list and visible marker', () => {
  expect(source).toContain("!String(contextSourceData[id] || '').startsWith('__error__')");
  expect(source).toContain('const selectedContextLabels = successfulContextIds');
  expect(source).toContain('dataContextConnectorIds: successfulContextIds');
});

test('blank and switched sessions clear per-session kit context and progress state', () => {
  expect(source).toContain('const [activePill, setActivePill] = useState(null)');
  expect(source).toContain('setDecisionKitSuggestion(null)');
  expect(source).toContain('setActiveContextSourceIds(new Set())');
  expect(source).toContain('setUsedContextSourceIds(new Set())');
  expect(source).toContain('setThreadWbs(null)');
  expect(source).toContain("hasConversationMessages\n                      ? 'discovery'\n                      : null");
});

test('new and switched sessions clear every scorecard id before building view context', () => {
  const newSessionBlock = source.slice(
    source.indexOf('const handleNewAnalysis'),
    source.indexOf("useEffect(() => {\n    if (!analysisResult) return;", source.indexOf('const handleNewAnalysis')),
  );
  const switchSessionBlock = source.slice(
    source.indexOf('const handleSelectAnalysis'),
    source.indexOf('const result =', source.indexOf('const handleSelectAnalysis')),
  );

  for (const block of [newSessionBlock, switchSessionBlock]) {
    expect(block).toContain('setSelectedScorecardId(null)');
    expect(block).toContain('setActiveSnapshotId(null)');
    expect(block).toContain('setBaselineScorecardId(null)');
    expect(block).toContain('setBundleCurrentScorecard(null)');
    expect(block).toContain('setBundleBaselineScorecard(null)');
    expect(block).toContain('setScoreVariants([])');
    expect(block).toContain("setSelectedVariantId('baseline')");
    expect(block).toContain('setResultA(null)');
    expect(block).toContain('setResultB(null)');
    expect(block).toContain('setResultC(null)');
  }
  expect(source).toContain("active_scorecard_id: String(effectiveSelectedScorecardId || activeScorecardId || '').trim() || undefined");
});

test('model kit classification is offered as a one-click suggestion', () => {
  expect(source).toContain('This looks like an RFP — use the');
  expect(source).toContain('decisionKitSuggestion.kit');
});
