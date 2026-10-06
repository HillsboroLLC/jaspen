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

  it('shows the server decision-required message and record action path', () => {
    expect(source).toContain("err?.data?.code === 'recorded_advancing_decision_required'");
    expect(source).toContain("err?.data?.action === 'record_decision'");
    expect(source).toContain('opts.executionDecisionRequired.message');
  });
});
