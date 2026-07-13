import React from 'react';
import './BeforeAfter.css';

const ROWS = [
  {
    topic: 'Starting point',
    before: 'A pile of notes, emails, and opinions with no clear structure',
    after: 'A shared decision brief with context, constraints, and options in one place',
  },
  {
    topic: "Who's involved",
    before: 'Unclear. People find out later and push back',
    after: 'Stakeholders identified upfront, aligned on what they care about',
  },
  {
    topic: 'How options get evaluated',
    before: 'Gut feel, loudest voice, or whoever made the deck',
    after: 'A scorecard built from your actual criteria, transparent and repeatable',
  },
  {
    topic: 'Time to a clear path',
    before: 'Days of back-and-forth, often no resolution',
    after: 'One focused session. Clear recommendation with tradeoffs visible',
  },
  {
    topic: 'What you walk away with',
    before: 'A decision that nobody fully owns',
    after: 'A documented decision with rationale your team can actually stand behind',
  },
];

export default function BeforeAfter() {
  return (
    <section className="before-after">
      <div className="ba-inner">
        <div className="ba-header">
          <p className="ba-eyebrow">The difference</p>
          <h2 className="ba-heading">What changes when you use Jaspen.</h2>
        </div>

        <div className="ba-table">
          <div className="ba-col-headers">
            <div className="ba-col-label ba-col-label--topic" />
            <div className="ba-col-label ba-col-label--before">
              <span className="ba-label-pill ba-label-pill--before">Without Jaspen</span>
            </div>
            <div className="ba-col-label ba-col-label--after">
              <span className="ba-label-pill ba-label-pill--after">With Jaspen</span>
            </div>
          </div>

          {ROWS.map((row, i) => (
            <div key={i} className="ba-row">
              <div className="ba-cell ba-cell--topic">{row.topic}</div>
              <div className="ba-cell ba-cell--before">
                <i className="fa-solid fa-xmark ba-icon ba-icon--before" aria-hidden="true" />
                <span>{row.before}</span>
              </div>
              <div className="ba-cell ba-cell--after">
                <i className="fa-solid fa-check ba-icon ba-icon--after" aria-hidden="true" />
                <span>{row.after}</span>
              </div>
            </div>
          ))}
        </div>
      </div>
    </section>
  );
}
