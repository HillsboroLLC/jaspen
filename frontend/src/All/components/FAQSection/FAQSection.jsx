import React, { useState } from 'react';
import './FAQSection.css';

export default function FAQSection() {
  const faqs = [
    {
      q: 'What exactly is included in Founder Lifetime Access?',
      a: <>
        <p>Founder Lifetime Access includes:</p>
        <ul>
          <li><span className="faq-highlight">All current analysis tools:</span> Market Analysis, Gap Analysis, and SWOT Analysis</li>
          <li><span className="faq-highlight">Unlimited analyses:</span> Create as many reports as you need, forever</li>
          <li><span className="faq-highlight">All future analysis tools:</span> Any new analysis features we build are included</li>
          <li><span className="faq-highlight">Platform enhancements:</span> ML improvements, UI updates, performance upgrades</li>
          <li><span className="faq-highlight">5 simultaneous projects:</span> Work on multiple analyses at once</li>
          <li><span className="faq-highlight">Single-user access:</span> Exclusive access for one user account</li>
        </ul>
      </>
    },
    {
      q: 'How does the 5-project limit work with unlimited analyses?',
      a: <>
        <p>You can have up to 5 projects "in progress" at any given time, but you can create unlimited analyses within those projects. Once you complete a project, you can start a new one.</p>
        <p>Think of it like having 5 active workspaces. Within each workspace, you can run as many Market Analyses, Gap Analyses, and SWOT Analyses as needed. This prevents the platform from being used for commercial licensing while giving you unlimited personal/business use.</p>
      </>
    },
    {
      q: 'Can I upgrade from Essential or Growth to Founder Lifetime later?',
      a: <>
        <p>Yes! You can upgrade to Founder Lifetime at any time. However, the founder pricing of $2,999 is limited-time. After the founder period ends, the lifetime access price increases to $4,999.</p>
        <p>We'll credit any payments you've made toward monthly plans against your lifetime access purchase.</p>
      </>
    },
    {
      q: 'How much can enterprises save vs traditional consulting?',
      a: <>
        <p>Enterprise organizations typically save <span className="faq-highlight">$900K to $1.3M+ annually</span> compared to traditional consulting firms:</p>
        <ul>
          <li><span className="faq-highlight">Market research projects:</span> $150K–$500K each vs unlimited with SEKKI</li>
          <li><span className="faq-highlight">Strategic planning:</span> $300K–$1M vs included in Transform tiers</li>
          <li><span className="faq-highlight">Custom programming:</span> $200K+ vs included in Transform plans</li>
          <li><span className="faq-highlight">Ongoing updates:</span> $100K+ per refresh vs continuous with SEKKI</li>
        </ul>
        <p>Plus, you get execution tools and custom programming, not just expensive reports that sit on shelves.</p>
      </>
    },
    {
      q: "What's the difference between Transform Standard, Premium, and Enterprise?",
      a: <>
        <p><span className="faq-highlight">Transform Standard ($15K/month):</span> 5 seats, 100 credits, basic custom programming (2 tools/month)</p>
        <p><span className="faq-highlight">Transform Premium ($25K/month):</span> 10 seats, 250 credits, advanced custom programming (5 tools/month), quarterly strategy sessions</p>
        <p><span className="faq-highlight">Transform Enterprise ($50K/month):</span> Unlimited seats and credits, dedicated full-time developer, white-glove support, monthly strategy sessions, custom integrations</p>
        <p>All Transform tiers include custom programming tailored to your specific business needs within our SaaS platform scope.</p>
      </>
    },
    {
      q: 'Is there a money-back guarantee?',
      a: <>
        <p>Yes! We offer a <span className="faq-highlight">30-day money-back guarantee</span> for all plans. If you're not completely satisfied with the platform within 30 days of purchase, we'll provide a full refund.</p>
        <p>For Founder Lifetime Access, this gives you a full month to test unlimited analyses and see the value for yourself risk-free.</p>
      </>
    },
    {
      q: 'How quickly can I get started?',
      a: <>
        <p>Immediately! Once you complete your purchase, you'll receive instant access to your SEKKI account. All analysis tools are ready to use right away—no setup, no waiting, no onboarding calls required.</p>
        <p>For Transform enterprise tiers, we'll schedule a brief onboarding call within 24 hours to discuss your custom programming needs.</p>
      </>
    },
    {
      q: 'What if I need more than 5 simultaneous projects?',
      a: <>
        <p>The 5-project limit is designed for individual power users and prevents commercial licensing. If you need more simultaneous projects, consider our Transform enterprise tiers which are designed for organizations with multiple users and unlimited projects.</p>
        <p>Alternatively, you can complete projects and start new ones as needed—there's no limit on total projects over time, just active ones.</p>
      </>
    },
  ];

  const [open, setOpen] = useState(null);

  return (
    <section className="faq" id="contact">
      <div className="container">
        <h2>Frequently Asked Questions</h2>
<div className="faq-container">
  {faqs.map((f, i) => (
    <div className="faq-item" key={i}>
      <button
        className={`faq-question${open === i ? ' active' : ''}`}
        onClick={() => setOpen(open === i ? null : i)}
      >
        {f.q} <i className="fas fa-chevron-down faq-icon"></i>
      </button>

      <div className={`faq-answer${open === i ? ' active' : ''}`}>
        <div className="faq-answer-inner">
          {f.a}
        </div>
      </div>
    </div>
  ))}
</div>
      </div>
    </section>
  );
}
