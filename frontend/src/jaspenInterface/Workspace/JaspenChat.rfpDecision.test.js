import fs from 'fs';
import path from 'path';

describe('single RFP scorecard decision actions', () => {
  const source = fs.readFileSync(path.resolve(__dirname, 'JaspenChat.jsx'), 'utf8');

  it('mounts the shared decision recorder directly on an RFP scorecard', () => {
    expect(source).toContain("import RecordDecisionPanel from './RecordDecisionPanel'");
    expect(source).toContain('result?.decision_kit');
    expect(source).toContain('<RecordDecisionPanel');
    expect(source).toContain('alternatives={[title]}');
    expect(source).toContain('decisionKit={result.decision_kit}');
  });

  it('routes plan builds through the shared universal decision confirmation', () => {
    expect(source).toContain("import { useExecutionPlanBuild } from './useExecutionPlanBuild'");
    expect(source).toContain('generateExecutionPlan(tid');
    expect(source).toContain('{executionPlanDecisionDialog}');
    expect(source).not.toContain('Jaspen.generateAiWbs');
  });
});
