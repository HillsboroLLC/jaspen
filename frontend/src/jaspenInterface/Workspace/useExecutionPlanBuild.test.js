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
    expect(shared).toContain('skip_plan_decision_confirm');
    expect(shared).toContain("overriding Jaspen&apos;s No-Bid recommendation");
    expect(shared).toContain("execution_plan_generation_failed");

    const executionPlan = fs.readFileSync(path.join(srcRoot, 'ExecutionPlan', 'ExecutionPlan.jsx'), 'utf8');
    expect(executionPlan).toContain('executionPlanFailure');
    expect(executionPlan).toContain('role="alert"');
    expect(executionPlan).toContain('Retry');
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
