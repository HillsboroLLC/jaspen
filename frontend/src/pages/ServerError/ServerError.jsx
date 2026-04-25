import React from 'react';
import { Link } from 'react-router-dom';
import './ServerError.css';

export default function ServerErrorPage() {
  return (
    <div className="server-error-page">
      <div className="server-error-card">
        <p className="server-error-eyebrow">Server Error</p>
        <h1>Something went wrong on our side.</h1>
        <p>
          Jaspen ran into a temporary issue. Please retry in a moment.
        </p>
        <div className="server-error-actions">
          <button type="button" className="server-error-btn server-error-btn-primary" onClick={() => window.location.reload()}>
            Retry
          </button>
          <Link to="/new" className="server-error-btn server-error-btn-secondary">
            Back to workspace
          </Link>
        </div>
      </div>
    </div>
  );
}
