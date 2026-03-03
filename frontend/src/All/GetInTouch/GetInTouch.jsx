import React from 'react';
import { Link } from 'react-router-dom';
import './GetInTouch.css';

export default function GetInTouch() {
  return (
    <div className="login-page get-in-touch-page">
      <div className="get-in-touch-card">
        <div className="get-in-touch-eyebrow">JASPEN</div>
        <h1 className="get-in-touch-title">Get in touch</h1>
        <p className="get-in-touch-subtext">
          Questions, partnerships, or early access? Reach out and we'll respond soon.
        </p>
        <div className="get-in-touch-actions">
          <a href="mailto:hello@jaspen.ai" className="jaspen-btn jaspen-btn-primary">
            Email us
          </a>
          <Link to="/" className="jaspen-btn jaspen-btn-outline">
            Back to home
          </Link>
        </div>
      </div>
    </div>
  );
}
