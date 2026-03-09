// =====================================================
// File: src/pages/Support/Support.jsx
// =====================================================
import React from 'react';
import './support.css'; // reuses Terms styles for identical layout

const Support = () => {
  return (
    <div className="support-container">
      <div className="support-content">
        <h1>Support for Jaspen</h1>

        <div className="support-meta">
          <p>
            <strong>Effective Date:</strong> September 15, 2025<br />
            <strong>Last Updated:</strong> March 9, 2026
          </p>
        </div>

        <section className="support-section">
          <h2>How can we help?</h2>
          <p>
            Find answers, report issues, or contact our team. For legal docs, see{' '}
            <a href="/pages/terms">Terms of Service</a> and{' '}
            <a href="/pages/privacy">Privacy Policy</a>.
          </p>
        </section>

        <section className="support-section">
          <h2>Contact Options</h2>
          <ul>
            <li>Support: <a href="mailto:support@jaspen.ai">support@jaspen.ai</a></li>
            <li>General: <a href="mailto:hello@jaspen.ai">hello@jaspen.ai</a></li>
            <li>Website: <a href="https://jaspen.ai" target="_blank" rel="noopener noreferrer">jaspen.ai</a></li>
            <li>Address: 4030 Wake Forest Road, STE 349, Raleigh, NC 27609, USA</li>
          </ul>
        </section>

        <section className="support-section">
          <h2>Common Topics</h2>

          <h3>Billing</h3>
          <ul>
            <li>Receipts and invoices</li>
            <li>Subscription plan changes and renewals</li>
            <li>Managing subscriptions</li>
          </ul>

          <h3>Account</h3>
          <ul>
            <li>Access issues and password resets</li>
            <li>Data export and deletion requests</li>
            <li>Workspace and session access</li>
          </ul>

          <h3>Technical</h3>
          <ul>
            <li>Crashes or performance problems</li>
            <li>Feature requests and feedback</li>
            <li>Bug reports (include device, OS, steps to reproduce)</li>
          </ul>
        </section>

        <section className="support-section">
          <h2>Submit a Request</h2>
          <p>When emailing support, include:</p>
          <ul>
            <li>Your account email</li>
            <li>Device/browser and operating system</li>
            <li>Steps to reproduce the issue and screenshots if possible</li>
          </ul>
        </section>

        <section className="support-section">
          <h2>Response Times</h2>
          <ul>
            <li>Business hours: Mon–Fri, 9am–5pm ET</li>
            <li>Typical first response: within 2 business days</li>
          </ul>
        </section>

        <hr className="support-divider" />

        <div className="support-footer">
          <p>
            <em>
              This Support page was last updated on March 9, 2026.
            </em>
          </p>
        </div>
      </div>
    </div>
  );
};

export default Support;
