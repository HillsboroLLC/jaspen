import React, { useState } from 'react';
import './FAQSection.css';

// Content reflects the CURRENT product and pricing (credit-based plans, the
// decision-intelligence methodology). Every answer is grounded in the repo:
// pricing from PricingVariantB, "connectors never gate" from the Constitution
// (Art. 13/14), "you make the call" from Art. 4. Keep answers short and free
// of em dashes.
export default function FAQSection() {
  const faqs = [
    {
      q: 'What is Jaspen, exactly?',
      a: <>
        <p>Jaspen is a decision-intelligence tool. You paste your notes, emails, or data; it interviews you about the decision, scores your options against criteria you own, and turns the result into an execution plan.</p>
        <p>The AI judges the evidence, but code does the math. That means the score is reproducible and every part of it is inspectable.</p>
      </>
    },
    {
      q: 'How is this different from ChatGPT, Claude, or Gemini?',
      a: <>
        <p>A raw AI chat writes the numbers itself, so they shift when you re-ask or reword. Jaspen caps confidence to the evidence, computes every score in code, and shows the breakdown behind it. Same inputs, same answer, every time.</p>
        <p>It is built to produce a decision you can defend, not a confident guess.</p>
      </>
    },
    {
      q: 'What is a credit, and how many will I need?',
      a: <>
        <p>Credits are how you pay for AI work as you go. Every plan includes a monthly allotment that resets each cycle: Free 1,000, Essential 7,000, Team 29,000 shared, and Enterprise 80,000 shared.</p>
        <p>How fast they burn depends on which model you pick. You can top up any time: 3,000 credits for $10, 8,000 for $25, or 18,000 for $50.</p>
      </>
    },
    {
      q: 'Do I have to connect Salesforce, Snowflake, or Jira to use it?',
      a: <>
        <p>No. Jaspen gives you the full methodology and an honest score with no connectors at all.</p>
        <p>Connecting data does not unlock the product. It only raises confidence on the dimensions that data supports. You are never blocked from a decision for lack of a connector.</p>
      </>
    },
    {
      q: 'Is the Free plan just a trial?',
      a: <>
        <p>No. Free is a real plan with 1,000 credits every month, not a countdown. It is meant for working a real decision end to end before you decide to pay.</p>
      </>
    },
    {
      q: 'Which model should I use: Pluto, Orbit, or Titan?',
      a: <>
        <p>All three are available on every plan. Pluto is fastest and burns the fewest credits. Orbit reasons more deeply at a moderate burn. Titan goes deepest and burns the most.</p>
        <p>Start on Pluto and move up when a decision needs more depth.</p>
      </>
    },
    {
      q: 'Does Jaspen make the decision for me?',
      a: <>
        <p>No, and it is designed not to. Jaspen prepares the decision, meaning the evidence, the trade-offs, and a recommendation you can inspect. You make the call.</p>
        <p>It will also tell you honestly when an option is weak instead of talking you into it.</p>
      </>
    },
    {
      q: 'Who is Jaspen for?',
      a: <>
        <p>People who own hard, cross-functional calls and have to defend them: operators, strategy and transformation leads, project managers, founders, and consultants.</p>
        <p>The same method works for an individual choice or a boardroom portfolio without changing how it thinks.</p>
      </>
    },
    {
      q: 'Can I cancel or change plans anytime?',
      a: <>
        <p>Yes. You can upgrade, downgrade, or cancel your subscription at any time from your Account settings.</p>
      </>
    },
  ];

  const [open, setOpen] = useState(null);

  return (
    <section className="faq" id="faq">
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
