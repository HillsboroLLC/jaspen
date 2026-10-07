import fs from 'fs';
import path from 'path';

const source = fs.readFileSync(path.join(__dirname, 'JaspenChat.jsx'), 'utf8');

test('Discovery presents objective, Decision Kit, and honest Data Context separately', () => {
  const objectiveBlock = source.slice(source.indexOf('const renderObjectiveTags'), source.indexOf('const renderDecisionKitTags'));
  expect(objectiveBlock).not.toContain('RFP');
  expect(source).toContain('<span className="jas-objective-tags-label">Decision Kit</span>');
  expect(source).toContain("{ id: 'jira_sync', label: 'Jira' }");
  expect(source).toContain("{ id: 'salesforce_insights', label: 'Salesforce' }");
  expect(source).toContain("{ id: 'snowflake_insights', label: 'Snowflake' }");
  expect(source).toContain('disabled={!isConnected}');
});

test('active objective and RFP kit render in the upper-right context', () => {
  expect(source).toContain('className="jas-context-right"');
  expect(source).toContain('Session objective:');
  expect(source).toContain('Active Decision Kit: RFP');
  expect(source).toContain('isRfpDecision(decisionKit)');
  expect(source).toContain('new Set([...usedContextSourceIds, ...activeContextSourceIds])');
  expect(source).toContain('connectedDataSources.filter((src) => usedIds.has(src.id))');
});
