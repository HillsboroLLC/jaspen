import React, { useState } from 'react';
import { createAnalytics } from '../../tools/shared/createAnalytics';
import EnterpriseInvestmentCalculator from './EnterpriseInvestmentCalculator';
import ExecutivePartnershipRequest from './ExecutivePartnershipRequest';
import {
  LIMITED_TIME_300K_PROJECT_ESTIMATE_SHORT,
  THINKING_POWER_PROJECT_ESTIMATES,
  THINKING_POWER_VARIABILITY_NOTE,
} from '../../shared/billing/thinkingPowerEstimates';
import './PricingVariantB.css';

const analytics = createAnalytics('homepage_pricing');

const PLANS = [
  {
    key: 'free',
    name: 'Free',
    monthly: 0,
    annual: 0,
    seats: '1 seat',
    allowance: '300 credits/month',
    projectEstimate: THINKING_POWER_PROJECT_ESTIMATES.free,
    tagline: 'Run a confidence check on something you are weighing.',
    cta: 'Sign up',
    href: '/?auth=1',
    featured: false,
  },
  {
    key: 'starter',
    name: 'Starter',
    monthly: 7,
    annual: 6,
    seats: '1 seat',
    allowance: '1,000 credits/month',
    projectEstimate: THINKING_POWER_PROJECT_ESTIMATES.starter,
    tagline: 'For the decisions you work through on your own.',
    cta: 'Start free',
    href: '/?auth=1',
    featured: false,
  },
  {
    key: 'essential',
    name: 'Essential',
    monthly: 39,
    annual: 32,
    seats: '1 seat',
    allowance: '7,000 credits/month',
    projectEstimate: THINKING_POWER_PROJECT_ESTIMATES.essential,
    tagline: 'For consequential decisions where confidence needs to be grounded in evidence.',
    cta: 'Start Free',
    href: '/?auth=1',
    featured: true,
  },
  {
    key: 'team',
    name: 'Team',
    monthly: 129,
    annual: 107,
    seats: '3 seats included',
    allowance: '29,000 shared credits/month',
    projectEstimate: THINKING_POWER_PROJECT_ESTIMATES.team,
    tagline: 'One shared rubric, so competing options can finally be compared.',
    cta: 'Start free',
    href: '/?auth=1',
    featured: false,
  },
  {
    key: 'business',
    name: 'Business',
    monthly: 299,
    annual: 249,
    seats: '5 seats included',
    allowance: '80,000 shared credits/month',
    projectEstimate: THINKING_POWER_PROJECT_ESTIMATES.business,
    tagline: 'Decision confidence across a team, with the reasoning preserved when work changes hands.',
    cta: 'Start with Business',
    href: '/?auth=1',
    featured: false,
  },
];

const FEATURES = [
  {
    category: 'Credits & capacity',
    rows: [
      { label: 'Monthly credits',            sub: 'Resets each billing cycle',         free: '300',     starter: '1,000',   essential: '7,000',  team: '29,000',      business: '80,000'    },
      { label: 'Approximate project evaluations', sub: 'Varies with each evaluation',  free: THINKING_POWER_PROJECT_ESTIMATES.free, starter: THINKING_POWER_PROJECT_ESTIMATES.starter, essential: THINKING_POWER_PROJECT_ESTIMATES.essential, team: THINKING_POWER_PROJECT_ESTIMATES.team, business: THINKING_POWER_PROJECT_ESTIMATES.business },
      { label: 'Credits shared across team', sub: 'Pool drawn from one balance',        free: false,     starter: false,     essential: false,    team: true,          business: true        },
      { label: 'Buy additional credits',     sub: 'Top up any time mid-cycle',          free: true,      starter: true,      essential: true,     team: true,          business: true        },
    ],
  },
  {
    category: 'Workspace & seats',
    rows: [
      { label: 'Seats included',             sub: '',                                   free: '1',       starter: '1',       essential: '1',      team: '3',           business: '5'         },
      { label: 'Additional seats',           sub: 'Pay as you grow',                    free: false,     starter: false,     essential: false,    team: '+$25/seat',   business: 'Up to 10 users' },
      { label: 'Shared team workspace',      sub: '',                                   free: false,     starter: false,     essential: false,    team: true,          business: true        },
      { label: 'Scorecard export',           sub: 'PDF download',                       free: true,      starter: true,      essential: true,     team: true,          business: true        },
    ],
  },
  {
    category: 'AI models',
    rows: [
      { label: 'Pluto',                      sub: 'Fastest, lowest credit burn',        free: true,      starter: true,      essential: true,     team: true,          business: true        },
      { label: 'Orbit',                      sub: 'Deeper reasoning, moderate burn',    free: true,      starter: true,      essential: true,     team: true,          business: true        },
      { label: 'Titan',                      sub: 'Highest depth, highest burn',        free: true,      starter: true,      essential: true,     team: true,          business: true        },
    ],
  },
  {
    category: 'Support',
    rows: [
      { label: 'Community support',          sub: '',                                   free: true,      starter: true,      essential: true,     team: true,          business: true        },
      { label: 'Priority support',           sub: '',                                   free: false,     starter: false,     essential: false,    team: true,          business: true        },
      { label: 'Dedicated success manager',  sub: '',                                   free: false,     starter: false,     essential: false,    team: false,         business: true        },
    ],
  },
];

// Advisory engagements are quoted at a flat fee and never sold through
// checkout — every CTA opens the Executive Partnership Request, which reaches
// partnerships@jaspen.ai. A form rather than a mailto, so a request is
// captured even when the visitor has no mail client registered.

const ADVISORY_CTA_NOTE = 'Engagements are accepted based on fit, capacity, and decision readiness.';

// Both offers are framed by what the buyer receives, not by how long anyone
// spends. The previous copy led with "one 90-minute virtual Intensive", which
// invited a reader to divide the fee by the hours and price a calendar. That is
// the wrong unit for an offer whose whole premise is the consequence of the
// decision, so session logistics moved to `logistics` and render below the
// deliverables.
//
// The impact bands are guidance, not gates. "Best suited for" is deliberate
// wording: a smaller decision carrying unusual complexity or exposure is still
// worth taking, and the published figure is positioning rather than a
// qualification rule.
const ADVISORY_OFFERINGS = [
  {
    key: 'executive_decision_intensive',
    title: 'Executive Decision Intensive',
    price: '$25,000',
    qualifier: 'Flat fee',
    lead: 'Decision assurance before a consequential commitment.',
    band: 'Best suited for decisions carrying roughly $10M or more in financial, strategic, or operational consequence.',
    description: 'An independent review of a decision your team has already developed. Jaspen separates what is evidenced from what is assumed, and we pressure test what the recommendation is resting on, before resources are committed. Confirming the direction is a legitimate result. So is finding that it does not hold.',
    includedLabel: 'You receive',
    included: [
      'An Evidence and Assumption Profile of the decision, showing what share of it is evidenced and what share is assumed',
      'A ranked assumption register, each entry carrying its power to change the answer',
      'The evidence that would resolve the top assumptions, and what obtaining it would take',
      'A trade-off analysis across the options under consideration, on one shared rubric',
      'A Decision Record your organization keeps, which updates as assumptions resolve',
    ],
    logistics: 'Delivered as one 90-minute virtual session facilitated by Jaspen’s Founder or a designated Customer Success Partner, with tailored preparation guidance beforehand. Jaspen access and AI capacity are included throughout the engagement.',
    engagement: 'executive_decision_intensive',
  },
  {
    key: 'strategic_advisor_partnership',
    title: 'Strategic Advisor Partnership',
    price: '$100,000',
    qualifier: 'Flat fee',
    lead: 'Decision assurance across a planning or capital cycle.',
    band: 'Best suited for multiple interconnected decisions, or a full planning or capital cycle, carrying roughly $50M or more in aggregate consequence.',
    // The load-bearing sentence. Without it this reads as a volume discount on
    // the Intensive, and a buyer comparing four Intensives against it has no
    // reason to prefer this. Everything listed below is a property of the set
    // of decisions, which is why a single engagement structurally cannot
    // deliver any of it.
    description: 'Five reviews is not the product. The product is what only appears across decisions: where one assumption underpins several initiatives, how much of your committed capital is evidenced rather than assumed, and whether your organization’s confidence is running ahead of its evidence.',
    includedLabel: 'You receive',
    includedIntro: 'Everything in the Intensive, applied across the cycle, plus:',
    included: [
      'Shared assumptions traced across initiatives, so one failure is visible everywhere it lands',
      'Aggregate assumption exposure across the portfolio, not decision by decision',
      'Where confidence is running ahead of the evidence supporting it',
      'One rubric applied across the cycle, so competing submissions are genuinely comparable',
      'Sequencing guidance on what needs resolving before the organization commits further',
      'Decision Records retained across the cycle, with outcomes tracked as they arrive',
    ],
    logistics: 'Delivered across five 90-minute virtual sessions and a portfolio review, facilitated by Jaspen’s Founder or a designated Customer Success Partner, with strategic context carried forward between them. Jaspen access and AI capacity are included throughout the engagement.',
    engagement: 'strategic_advisor_partnership',
    featured: true,
  },
];

// Rows compare what the two engagements produce, not how they are staffed or
// how long they run. The removed "Session duration" and "Executive Decision
// Intensives: 1 / 5" rows were the load-bearing problem: a table that counts
// sessions teaches a reader to divide the fee by the hours, which is the one
// comparison neither offer should invite. Logistics live on the cards, below
// the deliverables.
const ADVISORY_COMPARISON = [
  { label: 'Investment',                      intensive: '$25,000 flat fee',                                              partnership: '$100,000 flat fee' },
  { label: 'Best suited for',                 intensive: 'One consequential commitment, roughly $10M+ in consequence',    partnership: 'A planning or capital cycle, roughly $50M+ in aggregate' },
  { label: 'Decision scope',                  intensive: 'One decision and the options under it',                         partnership: 'Every decision in the cycle, and the relationships between them' },
  { label: 'Evidence and assumption profile', intensive: 'For the decision',                                              partnership: 'For each decision, and aggregated across the portfolio' },
  { label: 'Assumption register',             intensive: 'Ranked by power to change the answer',                          partnership: 'Ranked, plus assumptions traced where they recur across initiatives' },
  { label: 'Evidence roadmap',                intensive: 'What would resolve the top assumptions',                        partnership: 'What to resolve, and in what order, before committing further' },
  { label: 'Recommendation sensitivity',      intensive: 'What could change the ranking of these options',                partnership: 'What could change the ranking within and across decisions' },
  { label: 'Confidence calibration',          intensive: 'Not available from a single decision',                          partnership: 'Whether organizational confidence is running ahead of the evidence' },
  { label: 'Shared rubric',                   intensive: 'Applied to this decision',                                      partnership: 'Applied across the cycle, so submissions are comparable' },
  { label: 'Decision Records retained',       intensive: 'One, with outcomes tracked as they arrive',                     partnership: 'Across the cycle, with outcomes tracked as they arrive' },
  { label: 'AI-powered usage credits',        intensive: `300,000 (${LIMITED_TIME_300K_PROJECT_ESTIMATE_SHORT})`,        partnership: `300,000 (${LIMITED_TIME_300K_PROJECT_ESTIMATE_SHORT})` },
  { label: 'Facilitator',                     intensive: 'Founder or designated Customer Success Partner',                partnership: 'Founder or designated Customer Success Partner' },
  { label: 'Next step',                       intensive: 'Request a Consultation',                                        partnership: 'Request a Consultation' },
];

const AUDIENCE_TABS = [
  { key: 'individuals', label: 'Individuals & Teams' },
  { key: 'business',    label: 'Business & Enterprise' },
  { key: 'advisory',    label: 'Advisory Partnerships' },
];

function Cell({ value }) {
  if (value === true)  return <i className="fa-solid fa-check pvb-check" aria-label="Included" />;
  if (value === false) return <span className="pvb-dash" aria-label="Not included">—</span>;
  return <span className="pvb-cell-text">{value}</span>;
}

export default function PricingVariantB({ onOpenModal }) {
  const [isAnnual, setIsAnnual] = useState(false);
  const [compareOpen, setCompareOpen] = useState(false);
  const [advisoryCompareOpen, setAdvisoryCompareOpen] = useState(false);
  const [requestEngagement, setRequestEngagement] = useState(null);
  const [activeAudience, setActiveAudience] = useState('individuals');
  const isBusinessAudience = activeAudience === 'business';
  const isAdvisoryAudience = activeAudience === 'advisory';
  const individualPlans = PLANS.filter(plan => plan.key !== 'business');
  const visiblePlans = isBusinessAudience ? PLANS.filter(plan => plan.key === 'business') : individualPlans;

  const selectAudience = (audience) => {
    setActiveAudience(audience);
    analytics.track('pricing_audience_tab_selected', { audience });
  };

  const handleTabKeyDown = (event, audience) => {
    if (!['ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(event.key)) return;
    event.preventDefault();
    const index = AUDIENCE_TABS.findIndex(tab => tab.key === audience);
    let nextIndex;
    if (event.key === 'Home') nextIndex = 0;
    else if (event.key === 'End') nextIndex = AUDIENCE_TABS.length - 1;
    else {
      const step = event.key === 'ArrowRight' ? 1 : -1;
      // Wraps in both directions, so the roving focus never dead-ends.
      nextIndex = (index + step + AUDIENCE_TABS.length) % AUDIENCE_TABS.length;
    }
    const nextAudience = AUDIENCE_TABS[nextIndex].key;
    selectAudience(nextAudience);
    document.getElementById(`pricing-tab-${nextAudience}`)?.focus();
  };

  const requestConsultation = (offering) => {
    analytics.track('advisory_consultation_requested', { offering: offering.key });
    // Pre-select whichever engagement they clicked; the form still lets them
    // change it or say they are not sure yet.
    setRequestEngagement(offering.engagement);
  };

  return (
    <section className="pvb-section" id="pricing-variant-b">

      {/* ── Header ── */}
      <div className="pvb-header">
        <h2>Plans for every stage</h2>
        <p className="pvb-subhead">All models available on every plan. You move up when you need more capacity.</p>
        <div className="pvb-audience-tabs" role="tablist" aria-label="Pricing audiences">
          {AUDIENCE_TABS.map(tab => {
            const isSelected = activeAudience === tab.key;
            return (
              <button
                key={tab.key}
                id={`pricing-tab-${tab.key}`}
                type="button"
                role="tab"
                aria-selected={isSelected}
                aria-controls={`pricing-panel-${tab.key}`}
                tabIndex={isSelected ? 0 : -1}
                className={`pvb-audience-tab${isSelected ? ' is-active' : ''}`}
                onClick={() => selectAudience(tab.key)}
                onKeyDown={(event) => handleTabKeyDown(event, tab.key)}
              >
                {tab.label}
              </button>
            );
          })}
        </div>
        {/* Advisory engagements are a flat fee, so a monthly/annual switch
            would be meaningless next to them. */}
        {!isAdvisoryAudience && <div className="pvb-billing-toggle">
          <span className={!isAnnual ? 'pvb-toggle-label is-active' : 'pvb-toggle-label'}>Monthly</span>
          <button
            type="button"
            role="switch"
            aria-checked={isAnnual}
            className={`pvb-toggle-track ${isAnnual ? 'is-on' : ''}`}
            onClick={() => setIsAnnual(value => { const next = !value; analytics.track('billing_interval_selected', { interval: next ? 'annual' : 'monthly' }); return next; })}
          >
            <span className="pvb-toggle-thumb" />
          </button>
          <span className={isAnnual ? 'pvb-toggle-label is-active' : 'pvb-toggle-label'}>
            Annual <em className="pvb-save-chip">Save 17%</em>
          </span>
        </div>}
      </div>

      {isAdvisoryAudience ? (
        <div
          id="pricing-panel-advisory"
          role="tabpanel"
          aria-labelledby="pricing-tab-advisory"
          className="pvb-advisory-panel"
        >
          <div className="pvb-advisory-intro">
            <p className="pvb-advisory-eyebrow">Jaspen Advisory</p>
            <h3>Strategic decisions deserve more than software alone.</h3>
            <p className="pvb-advisory-lead">
              Work virtually with Jaspen’s Founder or a designated Customer Success Partner to frame
              high-impact decisions, strengthen the inputs and prompts used in Jaspen, challenge
              assumptions, and identify where the greatest estimated financial value may be available.
            </p>
            <p className="pvb-advisory-disclosure">
              Advisory engagements are delivered through structured virtual working sessions. Clients
              execute within Jaspen while the Jaspen advisor guides the decision process.
            </p>
          </div>

          <div className="pvb-advisory-cards">
            {ADVISORY_OFFERINGS.map(offering => (
              <div
                key={offering.key}
                className={`pvb-card pvb-advisory-card${offering.featured ? ' is-featured' : ''}`}
              >
                {/* Function first, then who it suits, then price. A reader who
                    meets the fee before the function prices a calendar; one who
                    meets the function first prices a decision. */}
                <p className="pvb-card-name">{offering.title}</p>
                <p className="pvb-advisory-function">{offering.lead}</p>
                <p className="pvb-advisory-band">{offering.band}</p>
                <p className="pvb-advisory-price">
                  <strong>{offering.price}</strong>
                  <span className="pvb-advisory-qualifier">{offering.qualifier}</span>
                </p>
                <p className="pvb-advisory-desc">{offering.description}</p>
                <p className="pvb-advisory-included-label">{offering.includedLabel}</p>
                {/* Sentence-case on purpose. The label style above is built for
                    one or two words, and a full sentence set in uppercase is
                    slower to read at exactly the point the reader is deciding. */}
                {offering.includedIntro && (
                  <p className="pvb-advisory-desc">{offering.includedIntro}</p>
                )}
                <ul className="pvb-advisory-list">
                  {offering.included.map(item => <li key={item}>{item}</li>)}
                </ul>
                {/* Logistics last, and visually quiet. How it is delivered is
                    not what is being bought. */}
                <p className="pvb-advisory-logistics-label">How it is delivered</p>
                <p className="pvb-advisory-delivery">{offering.logistics}</p>
                <button
                  type="button"
                  className={`pvb-card-cta jaspen-btn ${offering.featured ? 'jaspen-btn-primary' : 'jaspen-btn-outline'}`}
                  onClick={() => requestConsultation(offering)}
                >
                  Request a Consultation
                </button>
                <p className="pvb-advisory-cta-note">{ADVISORY_CTA_NOTE}</p>
              </div>
            ))}
          </div>

          {/* The credit estimate above is a planning figure. Every other
              surface that shows these numbers carries this qualifier, and an
              estimate presented without it would read as a commitment. */}
          <p className="pvb-advisory-estimate-note">
            Project evaluation counts are approximate planning estimates, not guaranteed
            quantities. {THINKING_POWER_VARIABILITY_NOTE}
          </p>

          <p className="pvb-advisory-travel-note">
            Virtual delivery is standard. In-person facilitation may be considered when appropriate.
            Approved travel, lodging, transportation, meals, and related expenses are billed
            separately and are not included in the flat fee.
          </p>

          <div className="pvb-compare-accordion">
            <button
              type="button"
              className="pvb-compare-toggle"
              onClick={() => setAdvisoryCompareOpen(v => !v)}
              aria-expanded={advisoryCompareOpen}
              aria-controls="pvb-advisory-compare-panel"
            >
              <span>Compare advisory engagements</span>
              <i className={`fa-solid fa-chevron-down pvb-compare-chevron${advisoryCompareOpen ? ' is-open' : ''}`} aria-hidden="true" />
            </button>

            {advisoryCompareOpen && (
              <div className="pvb-table-wrap" id="pvb-advisory-compare-panel">
                <table className="pvb-table is-advisory">
                  <thead>
                    <tr>
                      <th className="pvb-th-label">Engagement</th>
                      <th className="pvb-th-plan">
                        <span className="pvb-compare-plan-name">Executive Decision Intensive</span>
                      </th>
                      <th className="pvb-th-plan">
                        <span className="pvb-compare-plan-name">Strategic Advisor Partnership</span>
                      </th>
                    </tr>
                  </thead>
                  <tbody>
                    {ADVISORY_COMPARISON.map(row => (
                      <tr key={row.label} className="pvb-feature-row">
                        <td className="pvb-feature-label">{row.label}</td>
                        <td className="pvb-cell"><Cell value={row.intensive} /></td>
                        <td className="pvb-cell"><Cell value={row.partnership} /></td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </div>
        </div>
      ) : (
      <>
      {/* ── Plan cards ── */}
      <div className={`pvb-plan-layout${isBusinessAudience ? ' is-business' : ''}`}>
      <div
        id={`pricing-panel-${activeAudience}`}
        role="tabpanel"
        aria-labelledby={`pricing-tab-${activeAudience}`}
        className={`pvb-cards-row ${isBusinessAudience ? 'is-business' : 'is-individuals'}`}
      >
        {visiblePlans.map(plan => {
          const price = isAnnual ? plan.annual : plan.monthly;
          return (
            <div key={plan.key} className={`pvb-card ${plan.featured ? 'is-featured' : ''}`}>
              {plan.featured && <span className="pvb-popular-badge">Most popular</span>}
              <p className="pvb-card-name">{plan.name}</p>
              <div className="pvb-card-price">
                {price === 0 ? (
                  <strong className="pvb-price-num">Free</strong>
                ) : (
                  <>
                    <span className="pvb-price-dollar">$</span>
                    <strong className="pvb-price-num">{price}</strong>
                    <span className="pvb-price-period">/mo</span>
                  </>
                )}
              </div>
              {isAnnual && price > 0 && (
                <p className="pvb-billed-note">{`$${(price * 12).toLocaleString()} billed annually · ${plan.seats}`}</p>
              )}
              {(!isAnnual || price === 0) && (
                <p className="pvb-billed-note">{plan.seats}</p>
              )}
              <p className="pvb-card-tagline">{plan.tagline}</p>
              <p className="pvb-card-tagline">
                <strong>{plan.allowance}</strong><br />
                {plan.projectEstimate}
              </p>
              {plan.key === 'business' && (
                <p className="pvb-business-seat-note">
                  Five seats are included. The organization owner can add up to five more from Account Billing, for a maximum of 10 total users.
                </p>
              )}
              <button
                type="button"
                className={`pvb-card-cta jaspen-btn ${plan.featured ? 'jaspen-btn-primary' : 'jaspen-btn-outline'}`}
                onClick={() => { analytics.track(plan.key === 'business' ? 'business_cta_clicked' : 'pricing_cta_clicked', { plan: plan.key, interval: isAnnual ? 'annual' : 'monthly' }); onOpenModal?.('signup', 'free'); }}
              >
                {plan.cta}
              </button>
            </div>
          );
        })}
      </div>

      {isBusinessAudience && <aside className="pvb-enterprise-intro">
          <div>
            <p className="pvb-enterprise-eyebrow">Enterprise</p>
            <h3>Need more than 10 seats?</h3>
            <p>Larger teams and organizations may qualify for an annual Enterprise agreement tailored to their deployment.</p>
            <ul>
              <li>Multiple workspaces and business units</li>
              <li>Advanced security, SSO, and governance</li>
              <li>Tailored AI capacity and integrations</li>
              <li>Procurement and deployment support</li>
            </ul>
          </div>
          <button type="button" className="jaspen-btn jaspen-btn-outline" onClick={() => { analytics.track('contact_sales_clicked', { placement: 'business_card' }); document.getElementById('eic-title')?.scrollIntoView({ behavior: 'smooth', block: 'center' }); }}>Contact Sales</button>
        </aside>}
      </div>

      <p className="pvb-plan-note">Estimates are approximate, not guaranteed. {THINKING_POWER_VARIABILITY_NOTE}</p>

      {isBusinessAudience && <div className="pvb-enterprise-calculator-section">
        <EnterpriseInvestmentCalculator billing={isAnnual ? 'annual' : 'monthly'} onOpenModal={onOpenModal} />
      </div>}

      {!isBusinessAudience && (
        <p className="pvb-plan-note">
          Use Essential when you need room to examine evidence, pressure test assumptions, compare tradeoffs, and preserve the reasoning behind decisions that matter.
        </p>
      )}

      {/* ── Compare plans accordion ── */}
      {!isBusinessAudience && <div className="pvb-compare-accordion">
        <button
          type="button"
          className="pvb-compare-toggle"
          onClick={() => setCompareOpen(v => !v)}
          aria-expanded={compareOpen}
          aria-controls="pvb-plans-compare-panel"
        >
          <span>Compare plans</span>
          <i className={`fa-solid fa-chevron-down pvb-compare-chevron${compareOpen ? ' is-open' : ''}`} aria-hidden="true" />
        </button>

        {compareOpen && (
          <div className="pvb-table-wrap" id="pvb-plans-compare-panel">
            <table className="pvb-table">
              <thead>
                <tr>
                  <th className="pvb-th-label">Key features</th>
                  {individualPlans.map(p => (
                    <th key={p.key} className={`pvb-th-plan ${p.featured ? 'is-featured' : ''}`}>
                      <span className="pvb-compare-plan-name">{p.name}</span>
                      <button type="button" className={`pvb-compare-pill ${p.featured ? 'is-featured' : ''}`} onClick={() => onOpenModal?.('signup', 'free')}>{p.cta}</button>
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {FEATURES.map(section => (
                  <React.Fragment key={section.category}>
                    <tr className="pvb-category-row">
                      <td colSpan={individualPlans.length + 1}>{section.category}</td>
                    </tr>
                    {section.rows.map(row => (
                      <tr key={row.label} className="pvb-feature-row">
                        <td className="pvb-feature-label">
                          {row.label}
                          {row.sub && <span className="pvb-feature-sub">{row.sub}</span>}
                        </td>
                        {individualPlans.map(plan => (
                          <td key={plan.key} className={`pvb-cell ${plan.featured ? 'is-featured' : ''}`}>
                            <Cell value={row[plan.key]} />
                          </td>
                        ))}
                      </tr>
                    ))}
                  </React.Fragment>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>}

      {isAnnual && <p className="pvb-annual-note">* Per-month price shown. Charged as one annual payment.</p>}
      {!isBusinessAudience && <p className="pvb-addons-note">
        Mid-cycle top-ups: <a href="#pricing-variant-b">3,000 credits for $10 · 8,000 for $25 · 18,000 for $50</a>
      </p>}
      </>
      )}

      {requestEngagement && (
        <ExecutivePartnershipRequest
          initialEngagement={requestEngagement}
          onClose={() => setRequestEngagement(null)}
        />
      )}

    </section>
  );
}
