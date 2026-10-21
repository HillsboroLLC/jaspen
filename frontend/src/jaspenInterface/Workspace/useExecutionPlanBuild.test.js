import fs from 'fs';
import path from 'path';

describe('execution plan build entry points', () => {
  test('all product callers use the shared confirm-and-record hook', () => {
    const srcRoot = path.resolve(__dirname, '..');
    const productFiles = [
      path.join(srcRoot, 'Workspace', 'JaspenChat.jsx'),
      path.join(srcRoot, 'Workspace', 'JaspenWorkspace.jsx'),
      path.join(srcRoot, 'ExecutionPlan', 'ExecutionPlan.jsx'),
    ];
    productFiles.forEach((file) => {
      const source = fs.readFileSync(file, 'utf8');
      expect(source).toContain('generateExecutionPlan');
      expect(source).not.toContain('Jaspen.generateAiWbs');
      expect(source).not.toMatch(/\/api\/v1\/strategy\/threads\/.*\/ai-wbs/);
    });

    const shared = fs.readFileSync(path.join(srcRoot, 'Workspace', 'useExecutionPlanBuild.jsx'), 'utf8');
    expect((shared.match(/Jaspen\.generateAiWbs/g) || [])).toHaveLength(2);
    expect(shared).toContain('record_decision');
    expect(shared).toContain('acknowledged: true');
    expect(shared).not.toContain('skip_plan_decision_confirm');
    expect(shared).not.toMatch(/no\[-\\s\]\?bid/);
    expect(shared).toContain('Build a plan anyway?');
    expect(shared).toContain("Jaspen recommended No-Bid because");
    expect(shared).toContain('Build plan anyway');
    expect(shared).toContain('EXECUTION_PLAN_FAILURE_MESSAGE');
    expect(shared).toContain("Jaspen couldn't finish building this plan — try again. Your existing plan was not changed.");

    const executionPlan = fs.readFileSync(path.join(srcRoot, 'ExecutionPlan', 'ExecutionPlan.jsx'), 'utf8');
    expect(executionPlan).toContain('executionPlanFailure');
    expect(executionPlan).toContain('ExecutionPlanBuildFailure');

    const chat = fs.readFileSync(path.join(srcRoot, 'Workspace', 'JaspenChat.jsx'), 'utf8');
    const workspace = fs.readFileSync(path.join(srcRoot, 'Workspace', 'JaspenWorkspace.jsx'), 'utf8');
    expect(chat).toContain('executionPlanFailure');
    expect(chat).toContain('ScorecardExecutionPlanAction');
    expect(workspace).toContain('executionPlanFailure');
    expect(workspace).toContain('ExecutionPlanBuildFailure');

    // One message per failure: no second toast beside the inline message.
    expect(executionPlan).not.toContain('Could not generate execution plan.');
    expect(chat).not.toContain('Failed to build execution plan.');
    expect(workspace.match(/<ExecutionPlanBuildFailure/g)).toHaveLength(1);
  });

  test('execution workspace suppresses plan counts while authoritative data loads', () => {
    const srcRoot = path.resolve(__dirname, '..');
    const canvas = fs.readFileSync(path.join(srcRoot, 'Workspace', 'JaspenExecutionCanvas.jsx'), 'utf8');
    const workspace = fs.readFileSync(path.join(srcRoot, 'Workspace', 'JaspenWorkspace.jsx'), 'utf8');
    expect(workspace).toContain('loading={loading}');
    expect(canvas).toContain('if (loading)');
    expect(canvas).toContain('Loading execution plan…');
  });
});
