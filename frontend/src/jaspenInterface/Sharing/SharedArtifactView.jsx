import React from 'react';

import ScoreDashboard from '../Workspace/ScoreDashboard';
import TradeoffView from '../Workspace/TradeoffView';

// Renders a frozen share snapshot with the same components the workspace uses,
// in read-only mode, so what is shared looks like the real scorecard/trade-off.
// Used both by the public page and by the owner's pre-share preview.
export default function SharedArtifactView({ artifactType, snapshot }) {
  if (!snapshot || typeof snapshot !== 'object') return null;

  if (artifactType === 'tradeoff') {
    const cards = Array.isArray(snapshot.scorecards) ? snapshot.scorecards : [];
    const summary = snapshot.portfolio_summary;
    return (
      <div className="shared-artifact shared-artifact--tradeoff">
        {summary && (summary.structure || summary.recommended_sequence) && (
          <section className="shared-portfolio-summary" data-workspace-pdf-break>
            <div className="shared-portfolio-summary__kicker">Portfolio recommendation</div>
            {summary.structure && <div className="shared-portfolio-summary__structure">{summary.structure}</div>}
            {summary.recommended_sequence && <p>{summary.recommended_sequence}</p>}
          </section>
        )}
        <TradeoffView
          scorecardSnapshots={cards}
          strategyObjective={snapshot.strategy_objective || undefined}
          flow
          readOnly
        />
      </div>
    );
  }

  const card = snapshot.scorecard;
  if (!card || typeof card !== 'object') return null;
  return (
    <div className="shared-artifact shared-artifact--scorecard">
      <ScoreDashboard analysisResult={card} readOnly />
    </div>
  );
}
