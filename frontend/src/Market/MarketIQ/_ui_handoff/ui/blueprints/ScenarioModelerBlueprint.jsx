/**
 * ScenarioModelerBlueprint.jsx — Scenarios tab main content
 *
 * Shows:
 *  - Info banner (navy) explaining scenario modeling
 *  - Three scenario columns: Baseline (with current data), Scenario A, Scenario B
 *  - Run / Adopt buttons per scenario
 *  - Bottom actions: Reset All to Baseline, Run All Scenarios
 *  - Hint banner at bottom
 *
 * INTEGRATION: replace mockBaseline with real baseline data.
 * INTEGRATION: wire onRun, onAdopt, onResetAll, onRunAll to your real handlers.
 */
import React from 'react';
import Button from '../components/Button';

// ---- Mock Data ----
const mockBaseline = {
  npv: '\u2014',
  irr: '\u2014',
  payback: '\u2014',
  score: 46,
};

export default function ScenarioModelerBlueprint({
  // INTEGRATION: accept these as props
  baseline = mockBaseline,
  onRun,
  onAdopt,
  onResetAll,
  onRunAll,
}) {
  return (
    <div>
      {/* Info banner */}
      <div
        style={{
          background: 'var(--miq-navy)',
          color: 'rgba(255,255,255,0.8)',
          padding: '16px 20px',
          fontSize: 'var(--miq-text-base)',
          lineHeight: 1.5,
          marginBottom: '24px',
        }}
      >
        Adjust key levers to model different scenarios. Run scenarios individually or all at once to
        see projected impact on your AI Agent score.
      </div>

      {/* Scenario columns */}
      <div className="miq-scenario-cols" style={{ marginBottom: '24px' }}>

        {/* Baseline */}
        <div className="miq-scenario-col">
          <div className="miq-scenario-header">
            Baseline
            <span className="miq-scenario-badge">Current</span>
          </div>
          <div className="miq-scenario-body">
            {/* INTEGRATION: replace with real baseline fields */}
            <div className="miq-scenario-field">
              <span style={{ color: 'var(--miq-navy)' }}>NPV</span>
              <span style={{ color: 'var(--miq-gray-500)', fontWeight: 500 }}>{baseline.npv}</span>
            </div>
            <div className="miq-scenario-field">
              <span style={{ color: 'var(--miq-navy)' }}>IRR</span>
              <span style={{ color: 'var(--miq-gray-500)', fontWeight: 500 }}>{baseline.irr}</span>
            </div>
            <div className="miq-scenario-field">
              <span style={{ color: 'var(--miq-navy)' }}>Payback</span>
              <span style={{ color: 'var(--miq-gray-500)', fontWeight: 500 }}>{baseline.payback}</span>
            </div>
            <div
              style={{
                textAlign: 'center',
                paddingTop: '16px',
                borderTop: '1px solid var(--miq-border)',
                marginTop: '8px',
              }}
            >
              <div style={{ fontSize: 'var(--miq-text-sm)', color: 'var(--miq-gray-500)' }}>
                AI Agent Score
              </div>
              <div style={{ fontSize: '2rem', fontWeight: 700, color: 'var(--miq-navy)' }}>
                {baseline.score}
              </div>
              <div style={{ fontSize: 'var(--miq-text-sm)', color: 'var(--miq-gray-500)' }}>
                Current Score
              </div>
            </div>
          </div>
        </div>

        {/* Scenario A */}
        <div className="miq-scenario-col">
          <div className="miq-scenario-header">Scenario A</div>
          <div className="miq-scenario-body" style={{ minHeight: '180px' }}>
            {/* INTEGRATION: render editable fields here when scenario is configured */}
          </div>
          <div className="miq-scenario-actions">
            <Button variant="outline" size="sm" icon="fa-solid fa-play" onClick={() => onRun?.('A')}>
              Run
            </Button>
            <Button variant="outline" size="sm" icon="fa-solid fa-check" onClick={() => onAdopt?.('A')}>
              Adopt
            </Button>
          </div>
        </div>

        {/* Scenario B */}
        <div className="miq-scenario-col">
          <div className="miq-scenario-header">Scenario B</div>
          <div className="miq-scenario-body" style={{ minHeight: '180px' }}>
            {/* INTEGRATION: render editable fields here when scenario is configured */}
          </div>
          <div className="miq-scenario-actions">
            <Button variant="outline" size="sm" icon="fa-solid fa-play" onClick={() => onRun?.('B')}>
              Run
            </Button>
            <Button variant="outline" size="sm" icon="fa-solid fa-check" onClick={() => onAdopt?.('B')}>
              Adopt
            </Button>
          </div>
        </div>
      </div>

      {/* Bottom actions */}
      <div style={{ display: 'flex', gap: '12px', justifyContent: 'center', marginBottom: '20px' }}>
        <Button variant="outline" icon="fa-solid fa-rotate-left" onClick={onResetAll}>
          Reset All to Baseline
        </Button>
        <Button variant="primary" icon="fa-solid fa-play" onClick={onRunAll}>
          Run All Scenarios
        </Button>
      </div>

      {/* Hint */}
      <div
        style={{
          background: 'var(--miq-navy)',
          color: 'rgba(255,255,255,0.7)',
          padding: '14px 20px',
          fontSize: 'var(--miq-text-sm)',
          lineHeight: 1.5,
        }}
      >
        Adjust values in Scenario A and B, then click &ldquo;Run&rdquo; to see projected impact.
        <br />
        After running, click &ldquo;Adopt&rdquo; to apply that scenario as your current analysis.
      </div>
    </div>
  );
}
