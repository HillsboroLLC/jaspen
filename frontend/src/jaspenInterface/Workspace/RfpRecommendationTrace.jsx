import React from 'react';


export default function RfpRecommendationTrace({ recommendation, decisionKitVersion }) {
  if (!recommendation || typeof recommendation !== 'object') return null;
  const trace = Array.isArray(recommendation.trace) ? recommendation.trace : [];
  return (
    <div className="jas-scorecard-bottom-cols" data-testid="kit-recommendation-trace">
      <div>
        <p className="jas-scorecard-bottom-col-label">Jaspen recommendation</p>
        <p className="jas-scorecard-rec-text">{recommendation.label || 'Recommendation pending'}</p>
        {trace.length > 0 && (
          <p className="jas-scorecard-risk-item">
            {trace.map((step) => `${step.step}: ${step.value ?? step.status ?? ''} (${step.effect})`).join(' · ')}
            {` · kit v${recommendation.kit_version || decisionKitVersion || ''}`}
          </p>
        )}
      </div>
    </div>
  );
}
