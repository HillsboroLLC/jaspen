import React from 'react';
import './terms.css';

const Terms = () => {
  return (
    <div className="terms-container">
      <div className="terms-content">
        <h1>Terms of Service for Jaspen</h1>

        <div className="terms-meta">
          <p><strong>Effective Date:</strong> September 15, 2025<br />
          <strong>Last Updated:</strong> March 9, 2026</p>
        </div>

        <section className="terms-section">
          <h2>Agreement to Terms</h2>
          <p>These Terms of Service ("Terms") are a legal agreement between you and Jaspen ("Jaspen," "we," "our," or "us") for your use of Jaspen websites, applications, and related services.</p>
          <p>By accessing or using Jaspen, you agree to these Terms.</p>
        </section>

        <section className="terms-section">
          <h2>Description of Service</h2>
          <p>Jaspen provides strategy scoring, readiness workflows, scenario modeling, and execution planning tools for individuals and organizations.</p>
        </section>

        <section className="terms-section">
          <h2>Accounts and Access</h2>
          <ul>
            <li>You are responsible for account credentials and activity under your account</li>
            <li>You must provide accurate registration information</li>
            <li>We may suspend access for misuse, fraud, or security concerns</li>
          </ul>
        </section>

        <section className="terms-section">
          <h2>Billing and Subscriptions</h2>
          <ul>
            <li>Paid plans are billed according to selected pricing and plan terms</li>
            <li>Billing may be processed by third-party providers such as Stripe</li>
            <li>You are responsible for applicable taxes and payment method validity</li>
            <li>Sales-led plans may require signed order forms or separate commercial terms</li>
          </ul>
        </section>

        <section className="terms-section">
          <h2>Acceptable Use</h2>
          <p>You may not use Jaspen to violate law, abuse systems, attempt unauthorized access, interfere with service operation, or submit malicious content.</p>
        </section>

        <section className="terms-section">
          <h2>Intellectual Property</h2>
          <ul>
            <li>Jaspen software, interfaces, and service content are owned by us or our licensors</li>
            <li>You receive a limited, non-exclusive, revocable license to use the service</li>
            <li>You retain rights in your inputs to the extent permitted by law and contract</li>
          </ul>
        </section>

        <section className="terms-section">
          <h2>Service Availability</h2>
          <p>We aim for reliable availability but do not guarantee uninterrupted service. We may modify, suspend, or discontinue features when necessary.</p>
        </section>

        <section className="terms-section">
          <h2>Disclaimers and Limitation of Liability</h2>
          <p className="legal-text">THE SERVICE IS PROVIDED "AS IS" AND "AS AVAILABLE" WITHOUT WARRANTIES OF ANY KIND, EXPRESS OR IMPLIED.</p>
          <p className="legal-text">TO THE MAXIMUM EXTENT PERMITTED BY LAW, JASPEN SHALL NOT BE LIABLE FOR INDIRECT, INCIDENTAL, SPECIAL, CONSEQUENTIAL, OR PUNITIVE DAMAGES, INCLUDING LOSS OF DATA, PROFITS, OR BUSINESS INTERRUPTION.</p>
        </section>

        <section className="terms-section">
          <h2>Termination</h2>
          <p>You may stop using Jaspen at any time. We may suspend or terminate access for violation of these Terms or for security/legal reasons.</p>
        </section>

        <section className="terms-section">
          <h2>Governing Law</h2>
          <p>These Terms are governed by the laws of North Carolina, United States, excluding conflict-of-law rules.</p>
        </section>

        <section className="terms-section">
          <h2>Contact Information</h2>
          <p>If you have questions about these Terms, contact us:</p>
          <div className="contact-info">
            <p><strong>Jaspen</strong><br />
            Email: hello@jaspen.ai (general) or support@jaspen.ai (support)<br />
            Website: <a href="https://jaspen.ai" target="_blank" rel="noopener noreferrer">https://jaspen.ai</a><br />
            Address: 4030 Wake Forest Road, STE 349, Raleigh, NC 27609, USA<br />
            Phone: +1 (704) 488-5799</p>
          </div>
        </section>

        <hr className="terms-divider" />

        <div className="terms-footer">
          <p><em>These Terms of Service were last updated on March 9, 2026.</em></p>
        </div>
      </div>
    </div>
  );
};

export default Terms;
