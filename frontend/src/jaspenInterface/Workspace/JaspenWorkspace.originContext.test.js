import fs from 'fs';
import path from 'path';

const workspaceSource = fs.readFileSync(path.join(__dirname, 'JaspenWorkspace.jsx'), 'utf8');
const clientSource = fs.readFileSync(path.join(__dirname, 'JaspenClient.jsx'), 'utf8');

test('workspace chat sends origin context built from its existing bundle', () => {
  expect(workspaceSource).toContain("surface: 'workspace'");
  expect(workspaceSource).toContain('viewContext.origin = _workspaceOriginFromBundle(bundle');
  expect(workspaceSource).toContain('bundle?.thread?.name');
  expect(workspaceSource).toContain("message?.role === 'user' || message?.sender === 'user'");
  expect(workspaceSource).toContain('maxRequestLen = 200');
  expect(workspaceSource).toContain('scorecardName: viewContext.active_scorecard_name || ctx.scorecard_name || displayTitle');
  expect(workspaceSource).toContain('`/new?sid=${encodeURIComponent(sessionId)}`');
});

test('unified workspace chat no longer sends legacy prompt fields', () => {
  const chatMethod = clientSource.slice(
    clientSource.indexOf('async chat({'),
    clientSource.indexOf('async convoStart({'),
  );

  expect(chatMethod).not.toContain('systemPrompt');
  expect(chatMethod).not.toContain('docType');
  expect(chatMethod).not.toContain('detailed');
  expect(chatMethod).not.toContain('phase:');
});

test('workspace presentation tool refreshes the open canvas without a reload', () => {
  expect(workspaceSource).toContain("m.tool === 'update_workspace_presentation'");
  expect(workspaceSource).toContain('a?.result?.updated_scorecard');
  expect(workspaceSource).toContain('setSnapshot(updated)');
  expect(workspaceSource).toContain('setOverrides(updated.display_overrides)');
});

test('workspace chat identifies the one-pager layout and its editable presentation slots', () => {
  expect(workspaceSource).toContain("viewContext.workspace_layout = onePagerMode ? 'one-pager' : 'classic'");
  expect(workspaceSource).toContain('viewContext.presentation_text_slots = [');
  expect(workspaceSource).toContain("'headline', 'summary', 'featured_question'");
  expect(workspaceSource).toContain("viewContext.presentation_color_slots = ['accent', 'ink', 'tint']");
});
