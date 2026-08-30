import React from 'react';
import './BeforeAfter.css';

// Every previous row was a claim any AI tool could make, and none of them
// mentioned evidence. The first three carry the Decision Confidence spine, and
// the last two keep what was already working: defensibility, and reasoning that
// outlives the person who did it.
const ROWS = [
  {
    topic: 'What the numbers mean',
    before: 'Assumed figures and evidenced figures look identical on the page',
    after: 'Every input carries its evidence grade, so you can tell them apart',
  },
  {
    topic: 'Where confidence comes from',
    before: 'From how well the case is argued',
    after: 'From what the evidence supports. Thin support cannot contribute as if it were strong',
  },
  {
    topic: 'What you know before committing',
    before: 'That the plan looks strong',
    after: 'How much of it is evidenced, how much is assumed, and where that leaves you exposed',
  },
  {
    topic: 'When someone asks why',
    before: 'The answer is seniority, momentum, or whoever built the deck',
    after: 'The answer is the criteria, the weights, the evidence behind each, and the math',
  },
  {
    topic: 'Six months later',
    before: "The reasoning lives in one person's memory",
    after: 'The record holds what you decided, what you assumed, and what actually happened',
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
