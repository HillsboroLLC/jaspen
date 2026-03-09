import React from 'react';
import './privacy.css';

const Privacy = () => {
  return (
    <div className="privacy-container">
      <div className="privacy-content">
        <h1>Privacy Policy for Jaspen</h1>

        <div className="policy-meta">
          <p><strong>Effective Date:</strong> September 15, 2025<br />
          <strong>Last Updated:</strong> March 9, 2026</p>
        </div>

        <section className="policy-section">
          <h2>Introduction</h2>
          <p>Sekki LLC d/b/a Jaspen ("Jaspen," "we," "our," or "us") provides strategy scoring, scenario planning, and execution workflow tools. This Privacy Policy explains how we collect, use, and protect information when you use Jaspen.</p>
          <p>By using Jaspen, you agree to this Privacy Policy.</p>
        </section>

        <section className="policy-section">
          <h2>Information We Collect</h2>

          <h3>Account Information</h3>
          <ul>
            <li>Name, email address, and authentication details</li>
            <li>Subscription and billing plan metadata</li>
          </ul>

          <h3>Workspace Data</h3>
          <ul>
            <li>Project descriptions, chat inputs, scorecards, scenarios, and readiness data</li>
            <li>Uploaded files, notes, and model outputs associated with your workspace</li>
          </ul>

          <h3>Usage and Technical Data</h3>
          <ul>
            <li>Device/browser metadata, timestamps, request logs, and error diagnostics</li>
            <li>Feature usage needed for reliability, security, and product improvement</li>
          </ul>
        </section>

        <section className="policy-section">
          <h2>How We Use Information</h2>
          <ul>
            <li>Provide and improve strategy scoring, readiness, and execution features</li>
            <li>Authenticate users and secure accounts</li>
            <li>Operate subscriptions, billing, and support workflows</li>
            <li>Detect abuse, enforce terms, and comply with legal obligations</li>
          </ul>
        </section>

        <section className="policy-section">
          <h2>Billing and Third-Party Services</h2>
          <p>We use trusted service providers for critical functionality. For example, billing and subscription payments may be processed by Stripe. We only share data necessary for those services to operate.</p>
        </section>

        <section className="policy-section">
          <h2>Data Retention</h2>
          <p>We retain workspace and account data for as long as needed to provide the service, meet legal obligations, resolve disputes, and enforce agreements.</p>
        </section>

        <section className="policy-section">
          <h2>Your Choices</h2>
          <ul>
            <li>You can update account information in your profile and workspace settings</li>
            <li>You can request support for data access or deletion</li>
            <li>You can stop using the service at any time</li>
          </ul>
        </section>

        <section className="policy-section">
          <h2>Security</h2>
          <p>We use reasonable administrative, technical, and organizational safeguards to protect data. No method of transmission or storage is completely secure, but we continuously improve controls and monitoring.</p>
        </section>

        <section className="policy-section">
          <h2>Changes to This Policy</h2>
          <p>We may update this Privacy Policy periodically. Material updates will be reflected by the "Last Updated" date and, when appropriate, additional notice.</p>
        </section>

        <section className="policy-section">
          <h2>Contact Information</h2>
          <p>If you have privacy questions, contact us:</p>
          <div className="contact-info">
            <p><strong>Sekki LLC d/b/a Jaspen</strong><br />
            Email: hello@jaspen.ai<br />
            Website: <a href="https://jaspen.ai" target="_blank" rel="noopener noreferrer">https://jaspen.ai</a><br />
            Address: 4030 Wake Forest Road, STE 349, Raleigh, NC 27609, USA</p>
          </div>
        </section>

        <hr className="policy-divider" />

        <div className="policy-footer">
          <p><em>This Privacy Policy was last updated on March 9, 2026.</em></p>
        </div>
      </div>
    </div>
  );
};

export default Privacy;
