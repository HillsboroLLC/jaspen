import React from 'react';
import './terms.css';

const Terms = () => {
  return (
    <div className="terms-container">
      <div className="terms-content">
        <h1>Terms of Service</h1>

        <div className="terms-meta">
          <p><strong>Effective Date:</strong> March 1, 2026<br />
          <strong>Last Updated:</strong> March 1, 2026</p>
        </div>

        <section className="terms-section">
          <h2>Agreement to Terms</h2>
          <p>These Terms of Service ("Terms") constitute a legally binding agreement between you ("User," "you," or "your") and Hillsboro LLC ("Company," "we," "us," or "our") regarding your use of the Jaspen web application and related services (the "Service").</p>
          <p>By accessing or using Jaspen, you agree to be bound by these Terms. If you do not agree, do not use the Service.</p>
        </section>

        <section className="terms-section">
          <h2>Description of Service</h2>
          <p>Jaspen is an AI-powered strategy scorecard platform that provides:</p>
          <ul>
            <li>Conversational AI-driven project and business analysis</li>
            <li>Market IQ scoring and strategy scorecards</li>
            <li>Scenario modeling and comparison tools</li>
            <li>Financial projection and risk assessment</li>
            <li>Project management dashboard (available on select plans)</li>
            <li>Session history and analysis queue management</li>
          </ul>
        </section>

        <section className="terms-section">
          <h2>User Accounts</h2>
          <p>To access the Service, you must create an account through our supported authentication methods. You are responsible for:</p>
          <ul>
            <li>Maintaining the confidentiality of your account credentials</li>
            <li>All activities that occur under your account</li>
            <li>Providing accurate and current registration information</li>
            <li>Notifying us immediately of any unauthorized access</li>
          </ul>
        </section>

        <section className="terms-section">
          <h2>Subscription Plans and Billing</h2>
          <p>Jaspen offers multiple subscription tiers:</p>
          <ul>
            <li><strong>Free:</strong> Limited monthly credits for basic analysis</li>
            <li><strong>Essential:</strong> Expanded credits and access to PM Dashboard</li>
            <li><strong>Team:</strong> Higher credit allocation for collaborative use</li>
            <li><strong>Enterprise:</strong> Custom credit allocation and dedicated support</li>
          </ul>
          <p>Paid subscriptions are billed monthly through Stripe. You may cancel at any time; cancellation takes effect at the end of your current billing period. Refunds are not provided for partial billing periods.</p>
        </section>

        <section className="terms-section">
          <h2>Credits and Usage</h2>
          <p>The Service operates on a credit-based system. Each analysis, scoring session, and AI interaction consumes credits from your monthly allocation. Unused credits do not roll over between billing periods unless otherwise specified in your plan terms.</p>
          <p>Additional credit packs may be purchased separately. Credit packs are consumed after your monthly allocation is exhausted and do not expire at the end of the billing period.</p>
        </section>

        <section className="terms-section">
          <h2>AI-Generated Content</h2>
          <p>Jaspen uses artificial intelligence to generate analysis, scores, projections, and recommendations. You acknowledge that:</p>
          <ul>
            <li>AI-generated outputs are analytical tools, not professional business, financial, or legal advice</li>
            <li>Outputs are based on the information you provide and may not account for all relevant factors</li>
            <li>Scores, projections, and recommendations should be independently verified before making business decisions</li>
            <li>The Company does not guarantee the accuracy, completeness, or suitability of any AI-generated content</li>
          </ul>
          <div className="legal-text">
            AI outputs are provided "as is" for informational purposes only. You should consult qualified professionals before making significant business or financial decisions based on Jaspen analysis.
          </div>
        </section>

        <section className="terms-section">
          <h2>Intellectual Property</h2>
          <h3>Your Content</h3>
          <p>You retain all rights to the data, information, and materials you provide to Jaspen ("User Content"). By using the Service, you grant us a limited, non-exclusive license to process your User Content solely for the purpose of providing the Service.</p>
          <h3>AI Outputs</h3>
          <p>You may use AI-generated outputs (scores, analyses, reports) for your internal business purposes. The underlying AI models, algorithms, and platform remain the intellectual property of Hillsboro LLC.</p>
          <h3>Platform</h3>
          <p>All aspects of the Jaspen platform, including its design, code, features, and documentation, are the property of Hillsboro LLC and are protected by intellectual property laws.</p>
        </section>

        <section className="terms-section">
          <h2>Acceptable Use</h2>
          <h3>You May:</h3>
          <ul>
            <li>Use the Service for legitimate business analysis and strategy development</li>
            <li>Share outputs with your team and stakeholders</li>
            <li>Integrate insights from Jaspen into your business planning</li>
          </ul>
          <h3>You May Not:</h3>
          <ul>
            <li>Attempt to reverse-engineer, decompile, or extract the AI models</li>
            <li>Use the Service to generate harmful, fraudulent, or misleading content</li>
            <li>Resell, sublicense, or redistribute the Service or its outputs</li>
            <li>Circumvent usage limits, credit systems, or access controls</li>
            <li>Use automated tools to scrape or bulk-access the Service</li>
            <li>Violate any applicable laws or regulations through your use of the Service</li>
          </ul>
        </section>

        <section className="terms-section">
          <h2>Data Handling</h2>
          <p>Your project data, strategy information, and session history are handled in accordance with our <a href="/pages/privacy">Privacy Policy</a>. We implement industry-standard security measures to protect your data. We do not sell your data to third parties.</p>
        </section>

        <section className="terms-section">
          <h2>Limitation of Liability</h2>
          <p>To the maximum extent permitted by law, Hillsboro LLC shall not be liable for any indirect, incidental, special, consequential, or punitive damages arising from your use of or inability to use the Service. Our total liability shall not exceed the amount you paid for the Service in the twelve months preceding the claim.</p>
        </section>

        <section className="terms-section">
          <h2>Disclaimer of Warranties</h2>
          <p>The Service is provided "as is" and "as available" without warranties of any kind, whether express or implied, including but not limited to implied warranties of merchantability, fitness for a particular purpose, and non-infringement.</p>
        </section>

        <section className="terms-section">
          <h2>Termination</h2>
          <p>We may suspend or terminate your access to the Service at any time for violation of these Terms or for any reason with reasonable notice. You may terminate your account at any time by contacting us or through your account settings.</p>
          <p>Upon termination, your right to use the Service ceases immediately. We may retain certain data as required by law or for legitimate business purposes, as described in our Privacy Policy.</p>
        </section>

        <section className="terms-section">
          <h2>Changes to Terms</h2>
          <p>We may update these Terms from time to time. Material changes will be communicated through the Service or via email. Continued use of the Service after changes take effect constitutes acceptance of the revised Terms.</p>
        </section>

        <section className="terms-section">
          <h2>Governing Law</h2>
          <p>These Terms are governed by the laws of the State of North Carolina, without regard to its conflict of law provisions. Any disputes shall be resolved in the courts of North Carolina.</p>
        </section>

        <hr className="terms-divider" />

        <section className="terms-section">
          <h2>Contact Information</h2>
          <div className="contact-info">
            <p><strong>Hillsboro LLC</strong><br />
            Email: <a href="mailto:hello@jaspen.ai">hello@jaspen.ai</a><br />
            Website: <a href="https://jaspen.ai" target="_blank" rel="noopener noreferrer">jaspen.ai</a></p>
          </div>
        </section>

        <div className="terms-footer">
          <p>Thank you for using Jaspen. These terms help us provide you with reliable, high-quality AI-powered strategy tools.</p>
        </div>
      </div>
    </div>
  );
};

export default Terms;
