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
    tagline: 'Test Jaspen on a real decision.',
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
    tagline: 'Keep going with light personal use.',
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
    tagline: 'When the decision has real consequences, Essential is built for you.',
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
    tagline: 'Align your team, execute with clarity.',
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
    tagline: 'Bring a team together around clearer decisions, stronger execution, and reasoning that does not disappear when work changes hands.',
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

const ADVISORY_OFFERINGS = [
  {
    key: 'executive_decision_intensive',
    title: 'Executive Decision Intensive',
    price: '$25,000',
    qualifier: 'Flat fee',
    description: 'For an executive or leadership team working through one consequential strategic decision.',
    included: [
      `300,000 AI-powered usage credits (${LIMITED_TIME_300K_PROJECT_ESTIMATE_SHORT})`,
      'One 90-minute virtual Executive Decision Intensive',
      'Session facilitated by Jaspen’s Founder or a designated Customer Success Partner',
      'Tailored preparation and information guidance before the session',
      'Decision framing and prompt development',
      'Assumption and evidence challenge',
      'Risk, decision criteria, and tradeoff guidance',
      'Interpretation of Jaspen analysis and recommendations',
      'Executive-ready decision artifacts generated through Jaspen',
    ],
    delivery: 'This is a complete, structured decision engagement. Preparation, decision framing, evidence and assumption challenge, guided analysis, and executive-ready outputs are brought together to evaluate one consequential decision end-to-end.',
    engagement: 'executive_decision_intensive',
  },
  {
    key: 'strategic_advisor_partnership',
    title: 'Strategic Advisor Partnership',
    price: '$100,000',
    qualifier: 'Flat fee',
    description: 'For organizations evaluating multiple high-value opportunities and deciding where leadership attention, capital, and organizational capacity can create the greatest value.',
    includedIntro: `Includes 300,000 AI-powered usage credits (${LIMITED_TIME_300K_PROJECT_ESTIMATE_SHORT}) and five Executive Decision Intensives, with the full decision advisory process applied to each, plus:`,
    included: [
      'Ongoing strategic context carried across engagements',
      'Cross-decision dependency and tradeoff analysis',
      'Financial opportunity prioritization',
      'Portfolio and initiative prioritization',
      'Comparison of competing uses of capital and organizational capacity',
      'Identification of where leadership attention may create the greatest value',
      'Portfolio-level executive synthesis',
      'One 90-minute Executive Portfolio Review',
    ],
    delivery: 'Sessions are facilitated by Jaspen’s Founder or a designated Customer Success Partner, with strategic context carried forward to help leadership compare consequential decisions and determine where to place its bets across the portfolio.',
    engagement: 'strategic_advisor_partnership',
    featured: true,
  },
];

const ADVISORY_COMPARISON = [
  { label: 'Investment',                      intensive: '$25,000 flat fee',                                              partnership: '$100,000 flat fee' },
  { label: 'Best for',                        intensive: 'One consequential strategic decision',                          partnership: 'Multiple high-value decisions or priority areas' },
  { label: 'Executive Decision Intensives',   intensive: '1',                                                             partnership: '5' },
  { label: 'Session duration',                intensive: '90 minutes',                                                    partnership: '90 minutes each' },
  { label: 'Delivery',                        intensive: 'Virtual',                                                       partnership: 'Virtual' },
  { label: 'AI-powered usage credits',        intensive: `300,000 (${LIMITED_TIME_300K_PROJECT_ESTIMATE_SHORT})`,        partnership: `300,000 (${LIMITED_TIME_300K_PROJECT_ESTIMATE_SHORT})` },
  { label: 'Tailored preparation guidance',   intensive: 'Included',                                                      partnership: 'Included before each intensive' },
  { label: 'Decision framing',                intensive: 'Included',                                                      partnership: 'Included' },
  { label: 'Prompt development',              intensive: 'Included',                                                      partnership: 'Included' },
  { label: 'Assumption challenge',            intensive: 'Included',                                                      partnership: 'Included' },
  { label: 'Evidence and tradeoff guidance',  intensive: 'Included',                                                      partnership: 'Included' },
  { label: 'Financial opportunity prioritization', intensive: 'Applied to the defined decision when relevant',            partnership: 'Included across the agreed decisions or priorities' },
  { label: 'Portfolio prioritization',        intensive: 'Not included unless the defined decision is a portfolio decision', partnership: 'Included' },
  { label: 'Executive-ready Jaspen artifacts', intensive: 'Included',                                                     partnership: 'Included' },
  { label: 'Facilitator',                     intensive: 'Founder or designated Customer Success Partner',                partnership: 'Founder or designated Customer Success Partner' },
  { label: 'Direct checkout',                 intensive: 'No',                                                            partnership: 'No' },
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
                <p className="pvb-card-name">{offering.title}</p>
                <p className="pvb-advisory-price">
                  <strong>{offering.price}</strong>
                  <span className="pvb-advisory-qualifier">{offering.qualifier}</span>
                </p>
                <p className="pvb-advisory-desc">{offering.description}</p>
                <p className="pvb-advisory-included-label">Included</p>
                {offering.includedIntro && <p className="pvb-advisory-desc">{offering.includedIntro}</p>}
                <ul className="pvb-advisory-list">
                  {offering.included.map(item => <li key={item}>{item}</li>)}
                </ul>
                <p className="pvb-advisory-delivery">{offering.delivery}</p>
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
