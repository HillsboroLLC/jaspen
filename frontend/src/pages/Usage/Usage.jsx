import React from 'react';
import './Usage.css';

const Usage = () => {
  return (
    <div className="usage-container">
      <div className="usage-content">
        <h1>Usage Policy</h1>

        <div className="usage-meta">
          <p><strong>Effective Date:</strong> March 1, 2026<br />
          <strong>Last Updated:</strong> March 1, 2026</p>
        </div>

        <section className="usage-section">
          <h2>Purpose and Scope</h2>
          <p>This Usage Policy outlines the guidelines for using the Jaspen AI-powered strategy scorecard platform. It applies to all users across all subscription plans and is designed to ensure fair, responsible, and effective use of the Service.</p>
        </section>

        <section className="usage-section">
          <h2>Acceptable Use of AI Features</h2>
          <p>Jaspen's AI features are designed for legitimate business analysis. Acceptable uses include:</p>
          <ul>
            <li>Analyzing business projects, products, and market opportunities</li>
            <li>Generating strategy scorecards and market IQ assessments</li>
            <li>Running scenario models to evaluate business decisions</li>
            <li>Creating financial projections and risk assessments</li>
            <li>Using the PM Dashboard for project planning and management</li>
            <li>Exporting and sharing analysis results with stakeholders</li>
          </ul>
        </section>

        <section className="usage-section">
          <h2>Prohibited Content and Activities</h2>
          <p>The following uses of Jaspen are prohibited:</p>
          <ul>
            <li><strong>Illegal Activities:</strong> Using the Service to plan, facilitate, or promote any illegal activity</li>
            <li><strong>Fraudulent Analysis:</strong> Deliberately providing false information to generate misleading scores or projections intended to deceive others</li>
            <li><strong>Harmful Content:</strong> Inputting content that promotes violence, discrimination, or harassment</li>
            <li><strong>System Abuse:</strong> Attempting to manipulate, overload, or disrupt the Service through automated scripts, bots, or excessive requests</li>
            <li><strong>Circumvention:</strong> Bypassing credit limits, access controls, plan restrictions, or security measures</li>
            <li><strong>Unauthorized Access:</strong> Accessing other users' sessions, data, or accounts without permission</li>
            <li><strong>Competitive Extraction:</strong> Systematically extracting data or AI capabilities to build a competing product</li>
          </ul>
        </section>

        <section className="usage-section">
          <h2>Credit System</h2>
          <p>Jaspen operates on a credit-based usage model:</p>
          <ul>
            <li><strong>Monthly Allocation:</strong> Each plan includes a set number of monthly credits that reset at the start of each billing cycle</li>
            <li><strong>Credit Consumption:</strong> AI-powered conversations, analysis sessions, and scoring operations consume credits</li>
            <li><strong>Rollover:</strong> Unused monthly credits do not roll over to subsequent billing periods</li>
            <li><strong>Credit Packs:</strong> Additional credits may be purchased as one-time packs, which are consumed after your monthly allocation is depleted</li>
            <li><strong>Visibility:</strong> Your remaining credits are always visible in the application sidebar</li>
          </ul>
        </section>

        <section className="usage-section">
          <h2>Rate Limits and Fair Use</h2>
          <p>To ensure a quality experience for all users, the following guidelines apply:</p>
          <ul>
            <li>Requests are subject to reasonable rate limits based on your subscription plan</li>
            <li>Excessive automated requests or bulk operations may be throttled</li>
            <li>Concurrent session limits may apply depending on your plan tier</li>
            <li>Enterprise plans may have custom rate limits negotiated separately</li>
          </ul>
          <p>We reserve the right to adjust rate limits to maintain platform stability and performance.</p>
        </section>

        <section className="usage-section">
          <h2>Data Input Guidelines</h2>
          <p>When providing information to Jaspen for analysis:</p>
          <ul>
            <li><strong>Accuracy:</strong> Provide accurate and honest information for the most reliable analysis results</li>
            <li><strong>Sensitivity:</strong> Avoid including personally identifiable information (PII) of third parties unless necessary for the analysis</li>
            <li><strong>Confidentiality:</strong> You are responsible for ensuring you have the right to share any proprietary or confidential information you input</li>
            <li><strong>File Uploads:</strong> Uploaded files must comply with size limits and supported formats as specified in the application</li>
          </ul>
        </section>

        <section className="usage-section">
          <h2>Output Disclaimer</h2>
          <div className="usage-callout">
            Jaspen's AI-generated outputs — including strategy scorecards, market IQ scores, financial projections, and scenario analyses — are analytical tools designed to support your decision-making. They are not substitutes for professional business, financial, legal, or investment advice.
          </div>
          <p>You should:</p>
          <ul>
            <li>Independently verify all AI-generated data, projections, and recommendations</li>
            <li>Consult qualified professionals for significant business decisions</li>
            <li>Understand that scores and projections are based on the information you provide and may not account for all relevant factors</li>
            <li>Not rely solely on Jaspen outputs for critical financial or strategic commitments</li>
          </ul>
        </section>

        <section className="usage-section">
          <h2>Plan-Specific Features</h2>
          <p>Certain features are available only on specific subscription plans:</p>
          <ul>
            <li><strong>PM Dashboard:</strong> Available on Essential, Team, and Enterprise plans</li>
            <li><strong>Advanced Scenario Modeling:</strong> Full modeling capabilities available on paid plans</li>
            <li><strong>Knowledge Base:</strong> Available on Team and Enterprise plans</li>
            <li><strong>Priority Support:</strong> Available on Enterprise plans</li>
          </ul>
          <p>Attempting to access plan-restricted features without the appropriate subscription is not permitted.</p>
        </section>

        <section className="usage-section">
          <h2>Enforcement</h2>
          <p>Violations of this Usage Policy may result in:</p>
          <ul>
            <li>Warning notification and request to modify behavior</li>
            <li>Temporary suspension of access to the Service</li>
            <li>Permanent termination of your account</li>
            <li>Forfeiture of remaining credits and prepaid subscriptions</li>
          </ul>
          <p>We aim to address issues fairly and proportionally. Where possible, we will provide notice before taking enforcement action.</p>
        </section>

        <section className="usage-section">
          <h2>Reporting Concerns</h2>
          <p>If you encounter misuse of the platform or have concerns about another user's behavior, please contact us. We take all reports seriously and investigate promptly.</p>
        </section>

        <hr className="usage-divider" />

        <section className="usage-section">
          <h2>Contact</h2>
          <div className="contact-info">
            <p><strong>Hillsboro LLC</strong><br />
            Email: <a href="mailto:hello@jaspen.ai">hello@jaspen.ai</a><br />
            Website: <a href="https://jaspen.ai" target="_blank" rel="noopener noreferrer">jaspen.ai</a></p>
          </div>
        </section>

        <div className="usage-footer">
          <p>This policy helps us maintain a high-quality, reliable platform for all Jaspen users.</p>
        </div>
      </div>
    </div>
  );
};

export default Usage;
