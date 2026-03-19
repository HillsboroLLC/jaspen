import React from 'react';
import './SkeletonLoader.css';

function SkeletonBlock({ width = '100%', height = 16, style = {}, className = '' }) {
  return (
    <div
      className={`jas-skeleton ${className}`.trim()}
      style={{ width, height, ...style }}
      aria-hidden="true"
    />
  );
}

export function ScoreDashboardSkeleton() {
  return (
    <div className="jas-skeleton-score-dashboard" aria-label="Loading scorecard">
      <div className="jas-skeleton-score-toolbar">
        <div className="jas-skeleton-stack" style={{ flex: 1 }}>
          <SkeletonBlock width={120} height={12} />
          <SkeletonBlock width="48%" height={28} />
        </div>
        <SkeletonBlock width={144} height={40} />
      </div>
      <div className="jas-skeleton-score-grid">
        <SkeletonBlock height={220} />
        <SkeletonBlock height={220} />
      </div>
      <div className="jas-skeleton-card-grid">
        <SkeletonBlock height={150} />
        <SkeletonBlock height={150} />
      </div>
      <SkeletonBlock height={280} />
    </div>
  );
}

export function ScenarioModelerSkeleton() {
  return (
    <div className="jas-skeleton-scenario" aria-label="Loading scenario modeler">
      <div className="jas-skeleton-scenario-header">
        <div className="jas-skeleton-stack" style={{ flex: 1 }}>
          <SkeletonBlock width={110} height={12} />
          <SkeletonBlock width="42%" height={26} />
        </div>
        <SkeletonBlock width={180} height={40} />
      </div>
      <div className="jas-skeleton-rail-grid">
        <SkeletonBlock height={360} />
        <SkeletonBlock height={360} />
        <SkeletonBlock height={360} />
      </div>
      <SkeletonBlock height={72} />
    </div>
  );
}

export function ExecutionPanelSkeleton() {
  return (
    <div className="jas-skeleton-execution" aria-label="Loading execution plan">
      <div className="jas-skeleton-panel-header">
        <div className="jas-skeleton-stack" style={{ flex: 1 }}>
          <SkeletonBlock width={90} height={12} />
          <SkeletonBlock width="34%" height={28} />
          <SkeletonBlock width="52%" height={16} />
        </div>
        <SkeletonBlock width={180} height={42} />
      </div>
      <SkeletonBlock height={160} />
      <div className="jas-skeleton-table">
        {Array.from({ length: 4 }).map((_, idx) => (
          <div key={idx} className="jas-skeleton-table-row">
            <SkeletonBlock height={52} />
            <SkeletonBlock height={52} />
            <SkeletonBlock height={52} />
            <SkeletonBlock height={52} />
          </div>
        ))}
      </div>
    </div>
  );
}

export default SkeletonBlock;
