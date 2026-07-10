import React from 'react';
import './StarterDecisionChips.css';

export const STARTER_DECISIONS = [
  {
    id: 'job-offer',
    label: 'Accept a Job Offer',
    prompt: `Fictional example — edit anything.

Decision: I need to decide whether to accept a new job offer or remain in my current role.

Current role:
- Title: Operations Program Manager
- Base salary: $120,000
- Annual bonus target: 10%
- Office requirement: one office day per week
- Commute: approximately 20 minutes each way
- The role feels stable, but advancement has become limited.

New offer:
- Title: Senior Operations Program Manager
- Base salary: $145,000
- Annual bonus target: 15%
- Office requirement: three office days per week
- Commute: approximately 50 minutes each way
- The role offers greater leadership exposure and stronger promotion potential.
- The new company recently completed a reorganization, so there may be some uncertainty around priorities and team stability.

Values and trade-offs:
- Compensation matters, but I do not want to optimize only for salary.
- I value flexibility, career growth, stability, manager quality, commute burden, and long-term optionality.
- I want to understand whether the career upside and compensation justify the added commute, reduced flexibility, and reorganization risk.

People and evidence:
- I would want to understand the likely manager quality, the stability of the reorganized team, and whether promotion paths are real or just implied.
- The strongest evidence I have right now is the written offer, current compensation, office requirements, commute estimates, and what I know about each company's stability.
- Stakeholders and domain experts whose input could matter include my current manager, the recruiter, the potential new manager, and people who have worked through similar reorganizations.
- The decision process has a clear sequence: compare the written offer and current role, confirm manager expectations, understand the reorganization risk, then decide before the offer deadline next week.
- The main dependency is whether the new manager and leadership team can explain the promotion path and how settled the reorganized team really is.

Decision options:
- Accept the new offer
- Remain in the current role

Help me prepare this decision. Use the information provided, label assumptions, and ask the single highest-value missing question if more context is needed.`,
  },
  {
    id: 'start-business',
    label: 'Grow My Business',
    prompt: `Fictional example — edit anything.

Decision: I run an independent operations consulting business and need to decide which growth move to prioritize next.

Business context:
- Business: independent operations consultant
- Current annual revenue: approximately $180,000
- Current average monthly capacity: about 90% utilized
- Current pricing: $4,500 per project
- Strongest clients have indicated they would likely accept higher pricing.
- The referral pipeline is healthy but inconsistent.
- I currently handle delivery, sales, and administration myself.

Goal:
- Increase profit without materially reducing quality or creating an unsustainable workload.

Options:
1. Raise project pricing from $4,500 to $5,500
2. Hire a part-time contractor for $3,000 per month
3. Invest $2,500 per month in customer acquisition

People and evidence:
- The strongest evidence I have right now is current revenue, current utilization, project pricing, client feedback on pricing tolerance, and the quality of the referral pipeline.
- The main operating constraint is founder capacity because I currently handle delivery, sales, and administration.
- If I choose a growth move, I need a practical sequence that protects delivery quality while testing impact quickly.
- Stakeholders and domain experts whose input could matter include my strongest clients, a trusted contractor, and an advisor who understands consulting pricing.
- The workflow today runs from referral lead to sales call to project delivery to admin follow-up, with every handoff currently owned by me.
- A reasonable timeline would be to choose one move this month, run it for one quarter, and review profit, capacity, and client experience before expanding the approach.

Help me prepare this decision. Use the information provided, label assumptions, and ask the single highest-value missing question if more context is needed.`,
  },
  {
    id: 'quarterly-investments',
    label: "Prioritize Next Quarter's Investments",
    prompt: `Fictional example — edit anything.

Decision: Our leadership team needs to prioritize next quarter's major investments.

Constraint:
- Available budget: $1.2 million
- Organizational capacity: only two major initiatives next quarter

Options:
1. Customer-service automation
   - Cost: $450,000
   - Expected annual savings: $700,000
   - Implementation timeline: six months
   - Moderate change-management risk

2. Manufacturing-line upgrade
   - Cost: $800,000
   - Expected annual savings: $1.1 million
   - Implementation timeline: nine months
   - High operational dependency risk

3. New-market expansion
   - Cost: $600,000
   - Expected first-year revenue: $1.4 million
   - Higher uncertainty
   - Requires new regulatory and sales capabilities

4. Cybersecurity modernization
   - Cost: $500,000
   - Limited direct revenue
   - Reduces a significant identified operational risk
   - Implementation timeline: four months

People and evidence:
- The leadership team includes finance, operations, customer service, IT/security, manufacturing, and sales.
- The strongest evidence available is the budget limit, cost estimates, expected savings or revenue, implementation timelines, risk profile, and current capacity constraint.
- The main system constraint is that only two major initiatives can run next quarter without overloading the organization.
- The decision needs to produce a clear next-quarter sequence, not just a ranked list.
- The workflow runs from leadership prioritization to budget approval, initiative owners, implementation teams, and quarterly operating review.
- Key dependencies include manufacturing downtime windows, security risk timing, sales readiness for new-market expansion, and change-management capacity.

Help me prepare this decision. Use the information provided, label assumptions, and ask the single highest-value missing question if more context is needed.`,
  },
];

export default function StarterDecisionChips({ onSelect }) {
  return (
    <div className="starter-decisions" aria-label="Example decisions">
      <p className="starter-decisions-label">Not sure where to begin? Try an example decision.</p>
      <div className="starter-decisions-list">
        {STARTER_DECISIONS.map((item) => (
          <button
            key={item.id}
            type="button"
            className="starter-decision-chip"
            onClick={() => onSelect(item)}
          >
            {item.label}
          </button>
        ))}
      </div>
    </div>
  );
}
