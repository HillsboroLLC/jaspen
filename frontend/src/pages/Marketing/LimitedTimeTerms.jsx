import React from 'react';
import { Link } from 'react-router-dom';
import Seo from '../../shared/components/Seo';
import PublicJaspenHeader from '../../homeSections/HomePage/PublicJaspenHeader';
import './LimitedTimeTerms.css';

function LimitedTimeTerms() {
  return (
    <>
      <PublicJaspenHeader />
      <Seo
        title="Limited-Time Offer Terms and Conditions"
        description="Review the AI limitations, user responsibilities, technical assurance, refund terms, warranties, and liability terms for Jaspen’s limited-time offer."
        canonicalPath="/limited-time/terms-and-conditions"
      />
      <main className="lt-terms">
        <div className="lt-terms__content">
          <header className="lt-terms__header">
            <p>Limited-time offer</p>
            <h1>Terms and Conditions</h1>
            <span>Last updated: August 2, 2026</span>
            <div className="lt-terms__policy-links">
              <Link to="/pages/terms">Terms of Service</Link>
              <Link to="/pages/privacy">Privacy Policy</Link>
            </div>
          </header>

          <section>
            <h2>AI-Generated Outputs and Scoring</h2>
            <p>Jaspen uses artificial intelligence and automated analytical methods to generate scores, evaluations, recommendations, summaries, comparisons, plans, and other outputs (“Outputs”).</p>
            <p>Outputs are generated based primarily on the information, instructions, assumptions, criteria, documents, and other content submitted or selected by the user (“User Inputs”). Jaspen does not independently verify the completeness, accuracy, legality, currency, or reliability of User Inputs. Incomplete, inaccurate, misleading, outdated, or biased User Inputs may produce incomplete, inaccurate, misleading, outdated, or biased Outputs.</p>
            <p>Artificial intelligence and automated systems are probabilistic and may make mistakes. Outputs may contain factual errors, omissions, inconsistencies, inappropriate recommendations, or content that does not reflect the user’s circumstances. Scores represent an automated evaluation based on the available User Inputs and selected criteria. They are not objective facts, certifications, guarantees, or predictions of future performance.</p>
            <p>Jaspen does not guarantee the accuracy, completeness, reliability, usefulness, suitability, or results of any Output. Users are responsible for reviewing and independently validating Outputs before relying upon, sharing, publishing, implementing, or using them.</p>
          </section>

          <section>
            <h2>User Responsibility and Decision-Making</h2>
            <p>Jaspen is a decision-support tool and does not make decisions on the user’s behalf. The user retains sole responsibility for:</p>
            <ol>
              <li>The accuracy and completeness of User Inputs;</li>
              <li>Selecting appropriate evaluation criteria and assumptions;</li>
              <li>Reviewing and validating Outputs;</li>
              <li>Determining whether an Output is appropriate for its intended purpose;</li>
              <li>Obtaining any necessary professional or subject-matter-expert review; and</li>
              <li>All decisions, actions, omissions, communications, and results arising from use of the Service or Outputs.</li>
            </ol>
            <p>Outputs must not be treated as a substitute for professional legal, financial, accounting, medical, employment, regulatory, safety, or other specialized advice. Users must not rely exclusively on Jaspen for decisions that could materially affect a person’s legal rights, employment, health, safety, finances, eligibility, or access to essential services.</p>
            <p>To the maximum extent permitted by applicable law, Jaspen and its owner, Hillsboro Row LLC, will not be liable for losses, claims, damages, penalties, liabilities, or adverse outcomes resulting from inaccurate User Inputs, AI-generated errors, reliance on Outputs, or decisions made using the Service.</p>
          </section>

          <section id="technical-assurance">
            <h2>Technical Assurance</h2>
            <p>Jaspen stands behind the operation of its paid Service. If a Covered Technical Failure occurs, Jaspen will make commercially reasonable efforts to correct it. If Jaspen is unable to correct the Covered Technical Failure within ten business days after receiving all information reasonably needed to investigate it, the customer will be eligible for a refund of the amount paid for the affected initial purchase.</p>
            <p>A “Covered Technical Failure” means a reproducible technical defect attributable to Jaspen that materially prevents the customer from accessing or using a paid core feature represented as included with the purchased offer.</p>
            <p>To qualify:</p>
            <ol>
              <li>The customer must report the issue to <a href="mailto:support@jaspen.ai">support@jaspen.ai</a> within 30 calendar days after the original purchase;</li>
              <li>The report must include sufficient information to reproduce and investigate the issue;</li>
              <li>The customer must reasonably cooperate with troubleshooting efforts; and</li>
              <li>Jaspen must be given the opportunity to correct the issue before a refund is requested or initiated.</li>
            </ol>
            <p>Covered Technical Failures do not include:</p>
            <ul>
              <li>Dissatisfaction with, disagreement with, or lack of a desired outcome from an Output;</li>
              <li>AI-generated errors, omissions, scoring results, recommendations, or differences in phrasing;</li>
              <li>Inaccurate, incomplete, or incompatible User Inputs;</li>
              <li>User error or failure to follow instructions;</li>
              <li>Unsupported devices, browsers, integrations, configurations, or uses;</li>
              <li>Internet, hardware, software, or third-party service failures outside Jaspen’s reasonable control;</li>
              <li>Scheduled maintenance or brief service interruptions;</li>
              <li>Beta, preview, experimental, or expressly unsupported features;</li>
              <li>Failure to use the Service; or</li>
              <li>A change in the customer’s needs, expectations, business circumstances, or purchasing decision.</li>
            </ul>
            <p>If a refund is issued, it will be returned to the original payment method. The associated purchase, access rights, and unused credits may be canceled or deactivated. Except for the Technical Assurance and refunds required by applicable law, all purchases are final and nonrefundable.</p>
          </section>

          <section>
            <h2>No Satisfaction or Outcome-Based Refunds</h2>
            <p>Because Jaspen provides immediate access to non-returnable digital services, consumes computing resources during use, and enables users to generate and download Outputs that cannot be returned, Jaspen does not provide refunds based on satisfaction, usage levels, changed circumstances, or the achievement of any particular personal, operational, strategic, or financial result.</p>
            <p>Jaspen does not guarantee that use of the Service will produce revenue, savings, approval, consensus, funding, promotion, successful implementation, or any other particular outcome.</p>
          </section>

          <section>
            <h2>Disclaimer of Warranties</h2>
            <p>Except for the express Technical Assurance stated above, the Service and Outputs are provided “as is” and “as available.” To the maximum extent permitted by applicable law, Jaspen disclaims all express, implied, and statutory warranties, including warranties of merchantability, fitness for a particular purpose, accuracy, title, noninfringement, availability, and results.</p>
            <p>Jaspen does not warrant that the Service will be uninterrupted, entirely secure, or error-free, or that every defect will be corrected.</p>
          </section>

          <section>
            <h2>Limitation of Liability</h2>
            <p>To the maximum extent permitted by applicable law, Jaspen, Hillsboro Row LLC, and their owners, officers, employees, contractors, affiliates, and service providers will not be liable for indirect, incidental, special, exemplary, punitive, or consequential damages, or for lost profits, revenue, business opportunities, goodwill, data, or anticipated savings arising from or related to the Service, Outputs, or these Terms.</p>
            <p>To the maximum extent permitted by applicable law, the total aggregate liability of Jaspen and Hillsboro Row LLC for all claims arising from or relating to the Service, Outputs, or these Terms will not exceed the amount actually paid by the customer to Jaspen during the twelve months preceding the event giving rise to the claim.</p>
            <p>Nothing in these Terms excludes or limits liability that cannot lawfully be excluded or limited.</p>
          </section>
        </div>
      </main>
    </>
  );
}

export default LimitedTimeTerms;
