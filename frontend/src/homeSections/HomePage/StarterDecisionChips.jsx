import React from 'react';
import './StarterDecisionChips.css';

export const STARTER_DECISIONS = [
  {
    id: 'growth-investments',
    label: 'Prioritize Growth Investments',
    prompt: `Decision:
Our executive leadership team needs to decide which growth opportunities should receive investment over the next 18 months.

Constraints:
- Available growth capital: $8 million
- Commercial leadership can support no more than two major growth initiatives at the same time
- The company expects each approved initiative to contribute measurable revenue within 18 months
- Leadership prefers opportunities with a credible path to at least a 15% return on invested capital

Options:

1. Expand into the Canadian market
   - Required investment: $3.2 million
   - Expected first-year revenue: $5.5 million
   - Expected first-year EBITDA contribution: $900,000
   - Estimated time to launch: nine months
   - Requires regulatory approvals, a local sales team, and two distribution partners
   - Revenue forecast confidence: moderate

2. Launch a premium product line
   - Required investment: $2.4 million
   - Expected first-year revenue: $4.2 million
   - Expected first-year EBITDA contribution: $1.1 million
   - Estimated time to launch: six months
   - Uses the existing customer base and distribution network
   - Consumer demand has only been tested through a limited pilot
   - Revenue forecast confidence: moderate to low

3. Acquire a regional competitor
   - Purchase price: $6.5 million
   - Expected acquired annual revenue: $9 million
   - Expected annual EBITDA: $1.4 million
   - Estimated integration cost: $1 million
   - Estimated synergy opportunity: $700,000 annually
   - Customer concentration risk: the top three customers represent 48% of revenue
   - Due-diligence confidence: moderate

4. Build a direct-to-consumer channel
   - Required investment: $1.8 million
   - Expected first-year revenue: $2.8 million
   - Expected first-year EBITDA loss: $300,000
   - Expected break-even point: month 22
   - Creates access to first-party customer data
   - Requires new fulfillment, digital marketing, and customer-service capabilities
   - Revenue forecast confidence: low

People and evidence:
- Stakeholders include Strategy, Finance, Sales, Marketing, Operations, Legal, Technology, and the executive leadership team.
- Available evidence includes investment requirements, revenue and EBITDA estimates, launch timelines, market research, integration assumptions, customer concentration, and current organizational capacity.
- The company has strong domestic brand awareness but limited international operating experience.
- Sales and marketing leadership can support only one major market-entry initiative while also maintaining the core business.
- The acquisition and Canadian expansion would compete for the same executive sponsor and finance resources.

Desired outcome:
Recommend which opportunities should be pursued, deferred, or rejected. Provide a clear sequence for the next 18 months, explain the most important tradeoffs, identify assumptions that materially affect the recommendation, and highlight what evidence should be validated before final approval.

Help me prepare this decision. Use the information provided, label assumptions clearly, and ask the single highest-value missing question if more context is needed.`,
  },
  {
    id: 'transformation-portfolio',
    label: 'Sequence Transformation Initiatives',
    prompt: `Decision:
Our transformation office needs to determine which enterprise initiatives should begin this year and how they should be sequenced.

Constraints:
- Available transformation budget: $12 million
- The organization can support no more than three major implementations this year
- The enterprise technology team has capacity for approximately 18,000 project hours
- The finance, supply-chain, and HR teams cannot each support more than one major transformation at a time
- Leadership expects at least $6 million in annualized benefits from the approved portfolio

Options:

1. ERP modernization
   - Estimated cost: $7.5 million
   - Expected annual savings: $2.2 million
   - Implementation timeline: 18 months
   - Technology effort: approximately 11,000 hours
   - Requires significant finance, procurement, and operations participation
   - Current ERP has increasing support and reliability risk
   - Benefits confidence: high

2. Supply-chain planning transformation
   - Estimated cost: $3.8 million
   - Expected annual savings: $3.1 million
   - Implementation timeline: 12 months
   - Technology effort: approximately 5,500 hours
   - Expected inventory reduction: $8 million
   - Depends on improved product and customer data
   - Benefits confidence: moderate

3. Enterprise data platform
   - Estimated cost: $4.6 million
   - Expected direct annual savings: $900,000
   - Estimated decision-quality and productivity benefit: $2 million annually
   - Implementation timeline: 14 months
   - Technology effort: approximately 8,000 hours
   - Creates a foundation for advanced analytics and AI use cases
   - Benefits confidence: moderate to low

4. Customer-service automation
   - Estimated cost: $2.1 million
   - Expected annual savings: $2.6 million
   - Implementation timeline: seven months
   - Technology effort: approximately 3,500 hours
   - Expected reduction in average handling time: 22%
   - Moderate employee adoption and customer-experience risk
   - Benefits confidence: high

5. HR operating-model redesign
   - Estimated cost: $1.4 million
   - Expected annual savings: $1.7 million
   - Implementation timeline: nine months
   - Technology effort: approximately 1,500 hours
   - Requires role consolidation and changes to shared services
   - High change-management sensitivity
   - Benefits confidence: moderate

People and evidence:
- Stakeholders include the Transformation Office, Finance, Technology, Supply Chain, Customer Service, HR, Procurement, and business-unit leaders.
- Available evidence includes estimated costs, annualized benefits, resource requirements, implementation timelines, technology capacity, organizational dependencies, and confidence in the business cases.
- The ERP modernization and supply-chain transformation both require heavy finance and operations participation.
- The enterprise data platform would improve the long-term value of the supply-chain and customer-service initiatives but produces fewer immediate direct savings.
- Leadership wants a portfolio that balances near-term EBITDA improvement with long-term capability building.

Desired outcome:
Recommend which initiatives should start this year, which should be sequenced later, and which should be deferred. Build a realistic implementation sequence that respects budget, technology capacity, and functional bandwidth. Explain the tradeoffs between immediate financial value, strategic enablement, and execution risk.

Help me prepare this decision. Use the information provided, distinguish evidence from assumptions, and ask the single highest-value missing question if more context is needed.`,
  },
  {
    id: 'acquisition-target',
    label: 'Compare Acquisition Targets',
    prompt: `Decision:
Our corporate development team needs to recommend which acquisition target should advance to final due diligence and negotiation.

Constraints:
- Maximum available purchase consideration: $40 million
- The company can complete and integrate only one acquisition during the next 12 months
- Leadership requires a credible path to at least $5 million in annual EBITDA contribution within three years
- The transaction should not increase total leverage above 4.0 times EBITDA
- Integration resources are limited because the company is already completing an ERP implementation

Options:

1. Target Alpha: regional services provider
   - Indicative purchase price: $28 million
   - Annual revenue: $34 million
   - Current EBITDA: $4.2 million
   - Expected annual cost synergies: $1.3 million
   - Expected annual revenue synergies: $900,000 by year three
   - Customer retention rate: 91%
   - Top five customers represent 44% of revenue
   - Integration complexity: moderate
   - Management team is willing to remain for two years

2. Target Beta: technology-enabled competitor
   - Indicative purchase price: $39 million
   - Annual revenue: $22 million
   - Current EBITDA: $2.6 million
   - Revenue growth: 24% annually
   - Expected annual cost synergies: $600,000
   - Proprietary technology could reduce internal development costs by approximately $3 million
   - Top five customers represent 27% of revenue
   - Integration complexity: high
   - Two key founders are expected to leave after the transaction

3. Target Gamma: adjacent-market distributor
   - Indicative purchase price: $24 million
   - Annual revenue: $41 million
   - Current EBITDA: $3.8 million
   - Expected annual cost synergies: $1.8 million
   - Cross-selling opportunity estimated at $6 million in annual revenue by year three
   - Gross margins are eight percentage points below our current business
   - Integration complexity: low to moderate
   - Requires entry into two unfamiliar state regulatory environments

4. Target Delta: specialized consulting firm
   - Indicative purchase price: $18 million
   - Annual revenue: $16 million
   - Current EBITDA: $3.1 million
   - Recurring revenue: 38%
   - Expected annual cost synergies: $400,000
   - Could accelerate the company's advisory-services strategy by approximately two years
   - Revenue depends heavily on 12 senior partners
   - Integration complexity: moderate
   - Employee retention risk is high without a significant earnout

People and evidence:
- Stakeholders include Corporate Development, Strategy, Finance, Legal, Operations, Technology, HR, and the executive leadership team.
- Available evidence includes indicative valuations, historical financials, customer concentration, projected synergies, management-retention expectations, integration complexity, and preliminary legal and commercial due diligence.
- Target Beta provides the strongest technology capability but would use nearly all available capital.
- Target Gamma offers the strongest immediate synergy potential but introduces lower margins and regulatory complexity.
- The existing ERP implementation limits the organization's ability to absorb a highly complex integration.
- The final recommendation must consider both standalone economics and strategic fit.

Desired outcome:
Recommend which target should advance, which should remain as a backup, and which should be removed from consideration. Explain valuation, strategic fit, integration risk, synergy credibility, and the assumptions that most influence the recommendation. Identify the highest-priority diligence questions before a binding offer is made.

Help me prepare this decision. Use the information provided, label assumptions clearly, and ask the single highest-value missing question if more context is needed.`,
  },
  {
    id: 'capital-allocation',
    label: 'Allocate Capital Across Business Units',
    prompt: `Decision:
Executive leadership must allocate next year's capital budget across multiple business units competing for limited investment funding.

Constraints:
- Total available capital budget: $25 million
- Total requested funding exceeds $41 million.
- Leadership wants to maximize long-term enterprise value while maintaining financial discipline.
- Capital allocation should balance growth, operational efficiency, customer experience, and enterprise risk reduction.

Business unit requests:

1. Manufacturing
   - Requested investment: $9.5 million
   - New production equipment
   - Expected annual savings: $4.8 million
   - Expected throughput increase: 16%
   - Implementation timeline: 14 months

2. Sales & Marketing
   - Requested investment: $6.2 million
   - New digital customer acquisition platform
   - Expected annual revenue increase: $11.2 million
   - Expected customer acquisition cost reduction: 18%
   - Moderate forecasting uncertainty

3. Information Technology
   - Requested investment: $8.4 million
   - Enterprise technology modernization
   - Expected annual productivity improvements: $3.5 million
   - Improves cybersecurity posture and long-term scalability
   - Benefits realized over multiple years

4. Supply Chain
   - Requested investment: $7.1 million
   - Warehouse automation and logistics optimization
   - Expected annual savings: $5.3 million
   - Expected inventory reduction: $9 million
   - Requires ERP integration

5. Human Resources
   - Requested investment: $3.8 million
   - Workforce development and leadership capability program
   - Limited direct financial return
   - Expected employee retention improvement: 9%
   - Supports multiple enterprise transformation initiatives

People and evidence:
- Stakeholders include Finance, Strategy, Operations, Technology, Commercial Leadership, Human Resources, Supply Chain, and the Executive Leadership Team.
- Available evidence includes requested funding, projected financial impact, strategic alignment, implementation timelines, execution risk, organizational dependencies, expected business outcomes, and confidence in supporting business cases.
- Several business units compete for the same implementation resources and executive sponsorship.

Desired outcome:
Recommend how capital should be allocated across business units, identify which requests should receive full funding, partial funding, or be deferred, explain the tradeoffs, preserve the reasoning behind each allocation decision, and recommend an implementation sequence that maximizes enterprise value.

Help me prepare this decision. Use the information provided, clearly distinguish evidence from assumptions, and ask only the single highest-value missing question if additional information would materially improve the recommendation.`,
  },
  {
    id: 'midyear-reallocation',
    label: 'Reallocate Midyear Funding',
    prompt: `Decision:
Midyear performance is below plan, and the executive team needs to reallocate funding across the enterprise portfolio while protecting the company's most important strategic commitments.

Constraints:
- Forecasted annual EBITDA is now $9 million below plan
- Leadership must identify at least $6 million in cash savings or deferred spending this year
- The company has already spent $11.5 million across the current portfolio
- Canceling or pausing initiatives may create termination costs, stranded investment, or delayed benefits
- Technology and operations teams are operating above planned capacity

Current portfolio:

1. Pricing optimization program
   - Full-year budget: $3.4 million
   - Spend to date: $1.8 million
   - Expected annual EBITDA benefit: $7 million
   - Current delivery status: on schedule
   - Expected benefit start: next quarter
   - Remaining implementation risk: moderate
   - Estimated pause cost: $500,000

2. New distribution center
   - Full-year budget: $12 million
   - Spend to date: $5.5 million
   - Expected annual logistics savings: $4.2 million
   - Current delivery status: three months behind schedule
   - Expected benefit start: 15 months from now
   - Estimated cancellation and contractual cost: $2.1 million
   - Operational dependency risk: high

3. Customer loyalty platform
   - Full-year budget: $4.8 million
   - Spend to date: $2 million
   - Expected annual incremental gross profit: $3 million
   - Current delivery status: on schedule
   - Customer adoption assumptions are not yet validated
   - Estimated pause cost: $300,000
   - Benefit confidence: low to moderate

4. Cybersecurity remediation
   - Full-year budget: $2.7 million
   - Spend to date: $1.2 million
   - Limited direct financial return
   - Addresses three high-severity audit findings
   - Two findings must be resolved within six months
   - Estimated pause cost: minimal
   - Operational and regulatory risk of delay: high

5. Sales-force expansion
   - Full-year budget: $5.2 million
   - Spend to date: $1 million
   - Expected annual revenue contribution: $11 million
   - Expected annual EBITDA contribution: $2.4 million
   - New-hire productivity is currently 20% below plan
   - Hiring can be slowed with minimal contractual cost
   - Benefit confidence: moderate to low

6. Finance-process automation
   - Full-year budget: $1.9 million
   - Spend to date: $600,000
   - Expected annual savings: $1.5 million
   - Implementation timeline remaining: five months
   - Depends on technology resources currently supporting the distribution-center program
   - Estimated pause cost: $150,000
   - Benefit confidence: high

People and evidence:
- Stakeholders include the CEO, CFO, Strategy, Finance, Operations, Technology, Sales, Customer Experience, Security, and initiative owners.
- Available evidence includes approved budgets, spend to date, expected financial benefits, current delivery status, termination costs, timing of benefits, risk exposure, and confidence in each business case.
- The pricing program and finance automation have the strongest near-term EBITDA potential.
- The distribution-center program has the highest sunk cost and contractual exposure but will not generate benefits this year.
- Cybersecurity remediation is tied to known audit findings and cannot be evaluated solely on direct financial return.
- Leadership needs to identify what to continue, reduce, pause, or stop while maintaining a credible long-term strategy.

Desired outcome:
Recommend a revised portfolio that releases at least $6 million in current-year cash. Specify which initiatives should continue as planned, receive reduced funding, be paused, or be stopped. Quantify the expected financial impact where possible, explain the major tradeoffs, and identify any consequences that leadership must explicitly accept.

Help me prepare this decision. Use the information provided, separate evidence from assumptions, and ask the single highest-value missing question if more context is needed.`,
  },
  {
    id: 'quarterly-investments',
    label: "Prioritize Next Quarter's Investments",
    prompt: `Decision: Our leadership team needs to prioritize next quarter's major investments.

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
  {
    id: 'strategic-initiatives',
    label: 'Compare Strategic Initiatives',
    prompt: `Decision:
The executive leadership team needs to determine which strategic initiatives should be approved during the upcoming annual planning cycle.

Constraints:
- Available strategic investment budget: $18 million
- Leadership can actively sponsor only four enterprise initiatives at one time.
- Technology and operations teams are already committed at approximately 75% capacity.
- Every approved initiative must demonstrate measurable business value within 24 months.

Strategic initiatives:

1. Enterprise AI Enablement
   - Estimated investment: $4.2 million
   - Expected annual productivity savings: $5.8 million
   - Implementation timeline: 15 months
   - Requires enterprise data modernization
   - Moderate employee adoption risk

2. Customer Experience Transformation
   - Estimated investment: $5.6 million
   - Expected annual revenue increase: $9.4 million
   - Expected customer retention improvement: 6%
   - Implementation timeline: 18 months
   - Depends on CRM modernization and marketing automation

3. Supply Chain Optimization
   - Estimated investment: $3.8 million
   - Expected annual savings: $6.1 million
   - Expected inventory reduction: $11 million
   - Implementation timeline: 12 months
   - Moderate implementation complexity

4. Manufacturing Automation
   - Estimated investment: $6.8 million
   - Expected annual labor savings: $4.7 million
   - Expected throughput increase: 18%
   - Implementation timeline: 20 months
   - High operational dependency during installation

5. Cybersecurity Resilience Program
   - Estimated investment: $2.7 million
   - Limited direct financial return
   - Eliminates several high-risk audit findings
   - Implementation timeline: 10 months
   - Regulatory compliance deadline within 12 months

People and evidence:
- Stakeholders include Strategy, Finance, Operations, Technology, Commercial Leadership, HR, Security, and the Executive Leadership Team.
- Available evidence includes investment estimates, projected financial benefits, implementation timelines, strategic alignment, execution risk, organizational readiness, resource requirements, dependencies, and confidence in available forecasts.
- Multiple initiatives compete for the same executive sponsors, technology resources, and implementation teams.

Desired outcome:
Recommend which initiatives should move forward this planning cycle, which should be deferred, explain the major tradeoffs, preserve the reasoning behind each recommendation, and recommend a realistic execution sequence.

Help me prepare this decision. Use the information provided, distinguish assumptions from evidence, and ask the single highest-value missing question if additional information would materially improve the recommendation.`,
  },
  {
    id: 'technology-investments',
    label: 'Prioritize Technology Investments',
    prompt: `Decision:
Technology leadership must determine which technology investments should be funded during the upcoming fiscal year.

Constraints:
- Available technology investment budget: $9.5 million
- Internal technology teams can support only three major implementations simultaneously.
- Critical production systems cannot experience more than eight hours of planned downtime per quarter.
- Leadership expects technology investments to balance operational resilience, cybersecurity, efficiency, and long-term business growth.

Technology investments:

1. ERP Modernization
   - Estimated investment: $5.8 million
   - Expected annual operating savings: $3.1 million
   - Implementation timeline: 18 months
   - High organizational impact
   - Requires extensive finance and supply chain participation

2. Enterprise Data Platform
   - Estimated investment: $3.6 million
   - Enables AI initiatives and advanced analytics
   - Expected productivity improvements: $2.4 million annually
   - Implementation timeline: 14 months
   - Moderate implementation complexity

3. Cybersecurity Modernization
   - Estimated investment: $2.4 million
   - Eliminates multiple critical security findings
   - Improves cyber insurance eligibility
   - Limited direct financial return
   - Regulatory deadline within nine months

4. Customer Self-Service Platform
   - Estimated investment: $2.8 million
   - Expected annual call-center savings: $2.1 million
   - Expected customer satisfaction improvement: 11%
   - Implementation timeline: eight months
   - Moderate change-management effort

5. Infrastructure Cloud Migration
   - Estimated investment: $4.1 million
   - Expected annual infrastructure savings: $1.9 million
   - Improves scalability and disaster recovery
   - Implementation timeline: 16 months
   - Moderate operational risk during migration

People and evidence:
- Stakeholders include Technology, Finance, Operations, Security, Customer Experience, Enterprise Architecture, Procurement, and Executive Leadership.
- Available evidence includes projected costs, financial benefits, implementation timelines, cybersecurity exposure, operational dependencies, resource availability, strategic alignment, and confidence in supporting estimates.
- Several initiatives compete for the same technology architects, implementation partners, and executive sponsors.

Desired outcome:
Recommend which technology investments should be approved, deferred, or phased over multiple years. Explain important tradeoffs, identify implementation dependencies, preserve the reasoning behind each recommendation, and recommend an achievable implementation roadmap.

Help me prepare this decision. Use the available information, separate assumptions from evidence, and ask only the single highest-value missing question if additional context would improve the recommendation.`,
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
