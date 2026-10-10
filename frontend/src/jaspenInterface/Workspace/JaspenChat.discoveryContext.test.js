import fs from 'fs';
import path from 'path';

const source = fs.readFileSync(path.join(__dirname, 'JaspenChat.jsx'), 'utf8');
const clientSource = fs.readFileSync(path.join(__dirname, 'JaspenClient.jsx'), 'utf8');

test('Discovery presents objective, Decision Kit, and honest Data Context separately', () => {
  const objectiveBlock = source.slice(source.indexOf('const renderObjectiveTags'), source.indexOf('const renderDecisionKitTags'));
  expect(objectiveBlock).not.toContain('RFP');
  expect(source).toContain('<span className="jas-objective-tags-label">Decision Kit</span>');
  expect(source).toContain("{ id: 'jira_sync', label: 'Jira' }");
  expect(source).toContain("{ id: 'salesforce_insights', label: 'Salesforce' }");
  expect(source).toContain("{ id: 'snowflake_insights', label: 'Snowflake' }");
  expect(source).toContain('disabled={!isConnected}');
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
  expect(source).toContain('new Set([...usedContextSourceIds, ...activeContextSourceIds])');
  expect(source).toContain('connectedDataSources.filter((src) => usedIds.has(src.id))');
});
