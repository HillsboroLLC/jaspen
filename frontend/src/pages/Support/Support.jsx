// =====================================================
// File: src/pages/Support/Support.jsx
// =====================================================
import React from 'react';
import './support.css'; // reuses Terms styles for identical layout

const Support = () => {
  return (
    <div className="support-container">
      <div className="support-content">
        <h1>Support – Gridd Sudoku</h1>

        <div className="support-meta">
          <p>
            <strong>Effective Date:</strong> September 15, 2025<br />
            <strong>Last Updated:</strong> September 15, 2025
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
            <li>Email: <a href="mailto:hello@jaspen.ai">hello@jaspen.ai</a></li>
            <li>Website: <a href="https://jaspen.ai" target="_blank" rel="noopener noreferrer">jaspen.ai</a></li>
            <li>Address: 4030 Wake Forest Road, STE 349, Raleigh, NC 27609, USA</li>
          </ul>
        </section>

        <section className="support-section">
          <h2>Common Topics</h2>

          <h3>Billing</h3>
          <ul>
            <li>Receipts and invoices</li>
            <li>In-app purchases and refunds (via Apple App Store)</li>
            <li>Managing subscriptions</li>
          </ul>

          <h3>Account</h3>
          <ul>
            <li>Access issues and password resets</li>
            <li>Data export and deletion requests</li>
            <li>Device or progress sync</li>
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
            <li>Your device and OS version</li>
            <li>App version (from settings/about)</li>
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
              This Support page was last updated on September 15, 2025. Please check back for updates.
            </em>
          </p>
        </div>
      </div>
    </div>
  );
};

export default Support;
