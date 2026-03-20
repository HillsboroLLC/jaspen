import React from 'react';


function summaryLabel(value, suffix) {
  return `${value}${suffix ? ` ${suffix}` : ''}`.trim();
}


export default function Feedback({
  items,
  summary,
  isLoading,
  query,
  onQueryChange,
  onRefresh,
  valueFilter,
  onValueFilterChange,
  scopedUserLabel,
}) {
  const metrics = summary || {};

  return (
    <section className="jas-admin-subsection">
      <div className="jas-admin-feedback-head">
        <div>
          <h3>Feedback Insights</h3>
          <p className="jas-admin-empty">
            Review assistant message ratings in one place and spot quality drift quickly.
            {scopedUserLabel ? ` Showing feedback for ${scopedUserLabel}.` : ''}
          </p>
        </div>
        <button type="button" className="jas-admin-secondary" onClick={onRefresh} disabled={isLoading}>
          {isLoading ? 'Refreshing...' : 'Refresh'}
        </button>
      </div>

      <div className="jas-admin-feedback-metrics">
        <div className="jas-admin-feedback-metric">
          <strong>{summaryLabel(metrics.total_feedback || 0)}</strong>
          <span>Total ratings</span>
        </div>
        <div className="jas-admin-feedback-metric">
          <strong>{summaryLabel(metrics.up_count || 0)}</strong>
          <span>Thumbs up</span>
        </div>
        <div className="jas-admin-feedback-metric">
          <strong>{summaryLabel(metrics.down_count || 0)}</strong>
          <span>Thumbs down</span>
        </div>
        <div className="jas-admin-feedback-metric">
          <strong>{summaryLabel(metrics.positive_rate || 0, '%')}</strong>
          <span>Positive rate</span>
        </div>
        <div className="jas-admin-feedback-metric">
          <strong>{summaryLabel(metrics.unique_users || 0)}</strong>
          <span>Users represented</span>
        </div>
      </div>

      <div className="jas-admin-feedback-filters">
        <input
          type="text"
          placeholder="Search by user, thread, or message excerpt"
          value={query}
          onChange={(e) => onQueryChange(e.target.value)}
        />
        <select value={valueFilter} onChange={(e) => onValueFilterChange(e.target.value)}>
          <option value="">All ratings</option>
          <option value="up">Thumbs up</option>
          <option value="down">Thumbs down</option>
        </select>
      </div>

      {isLoading && <p className="jas-admin-empty">Loading feedback...</p>}
      {!isLoading && (!items || items.length === 0) && <p className="jas-admin-empty">No feedback recorded yet.</p>}
      {!isLoading && Array.isArray(items) && items.length > 0 && (
        <div className="jas-admin-feedback-list">
          {items.map((item) => (
            <div key={`${item.thread_id}:${item.message_index}:${item.feedback_updated_at || 'feedback'}`} className="jas-admin-feedback-row">
              <div className="jas-admin-feedback-topline">
                <strong>{item.user_email || 'Unknown user'}</strong>
                <span className={`jas-admin-status-badge is-${item.feedback_value === 'up' ? 'connected' : 'disconnected'}`}>
                  {item.feedback_value === 'up' ? 'Thumbs up' : 'Thumbs down'}
                </span>
              </div>
              <div className="jas-admin-feedback-meta">
                <span>{item.session_name || item.thread_id}</span>
                <span>{item.feedback_updated_at ? new Date(item.feedback_updated_at).toLocaleString() : 'n/a'}</span>
              </div>
              <p>{item.message_excerpt || 'No message preview available.'}</p>
            </div>
          ))}
        </div>
      )}
    </section>
  );
}
