import React, { useState } from 'react';
import './PricingVariantB.css';

const PLANS = [
  {
    key: 'free',
    name: 'Free',
    monthly: 0,
    annual: 0,
    seats: '1 seat',
    tagline: 'Explore ideas without commitment.',
    cta: 'Sign up',
    href: '/?auth=1',
    featured: false,
  },
  {
    key: 'essential',
    name: 'Essential',
    monthly: 39,
    annual: 32,
    seats: '1 seat',
    tagline: 'Turn ideas into clear decisions.',
    cta: 'Start free',
    href: '/?auth=1',
    featured: true,
  },
  {
    key: 'team',
    name: 'Team',
    monthly: 129,
    annual: 107,
    seats: '3 seats included',
    tagline: 'Align your team, execute with clarity.',
    cta: 'Start free',
    href: '/?auth=1',
    featured: false,
  },
  {
    key: 'enterprise',
    name: 'Enterprise',
    monthly: 299,
    annual: 249,
    seats: '5 seats included',
    tagline: 'Decision-making at org scale.',
    cta: 'Start free',
    href: '/?auth=1',
    featured: false,
  },
];

const FEATURES = [
  {
    category: 'Credits & capacity',
    rows: [
      { label: 'Monthly credits',            sub: 'Resets each billing cycle',         free: '1,000',   essential: '7,000',  team: '29,000',      enterprise: '80,000'    },
      { label: 'Credits shared across team', sub: 'Pool drawn from one balance',        free: false,     essential: false,    team: true,          enterprise: true        },
      { label: 'Buy additional credits',     sub: 'Top up any time mid-cycle',          free: true,      essential: true,     team: true,          enterprise: true        },
    ],
  },
  {
    category: 'Workspace & seats',
    rows: [
      { label: 'Seats included',             sub: '',                                   free: '1',       essential: '1',      team: '3',           enterprise: '5'         },
      { label: 'Additional seats',           sub: 'Pay as you grow',                    free: false,     essential: false,    team: '+$25/seat',   enterprise: '+$30/seat' },
      { label: 'Shared team workspace',      sub: '',                                   free: false,     essential: false,    team: true,          enterprise: true        },
      { label: 'Scorecard export',           sub: 'PDF download',                       free: true,      essential: true,     team: true,          enterprise: true        },
    ],
  },
  {
    category: 'AI models',
    rows: [
      { label: 'Pluto',                      sub: 'Fast — lowest credit burn',          free: true,      essential: true,     team: true,          enterprise: true        },
      { label: 'Orbit',                      sub: 'Deeper reasoning — moderate burn',   free: true,      essential: true,     team: true,          enterprise: true        },
      { label: 'Titan',                      sub: 'Highest depth — highest burn',       free: true,      essential: true,     team: true,          enterprise: true        },
    ],
  },
  {
    category: 'Support',
    rows: [
      { label: 'Community support',          sub: '',                                   free: true,      essential: true,     team: true,          enterprise: true        },
      { label: 'Priority support',           sub: '',                                   free: false,     essential: false,    team: true,          enterprise: true        },
      { label: 'Dedicated success manager',  sub: '',                                   free: false,     essential: false,    team: false,         enterprise: true        },
    ],
  },
];

function Cell({ value }) {
  if (value === true)  return <i className="fa-solid fa-check pvb-check" aria-label="Included" />;
  if (value === false) return <span className="pvb-dash" aria-label="Not included">—</span>;
  return <span className="pvb-cell-text">{value}</span>;
}

export default function PricingVariantB({ onOpenModal }) {
  const [isAnnual, setIsAnnual] = useState(false);
  const [compareOpen, setCompareOpen] = useState(false);

  return (
    <section className="pvb-section" id="pricing-variant-b">

      {/* ── Header ── */}
      <div className="pvb-header">
        <h2>Plans for every stage</h2>
        <p className="pvb-subhead">All models available on every plan. You move up when you need more capacity.</p>
        <div className="pvb-billing-toggle">
          <span className={!isAnnual ? 'pvb-toggle-label is-active' : 'pvb-toggle-label'}>Monthly</span>
          <button
            type="button"
            role="switch"
            aria-checked={isAnnual}
            className={`pvb-toggle-track ${isAnnual ? 'is-on' : ''}`}
            onClick={() => setIsAnnual(v => !v)}
          >
            <span className="pvb-toggle-thumb" />
          </button>
          <span className={isAnnual ? 'pvb-toggle-label is-active' : 'pvb-toggle-label'}>
            Annual <em className="pvb-save-chip">Save 17%</em>
          </span>
        </div>
      </div>

      {/* ── Plan cards ── */}
      <div className="pvb-cards-row">
        {PLANS.map(plan => {
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
                <p className="pvb-billed-note">Billed annually · {plan.seats}</p>
              )}
              {(!isAnnual || price === 0) && (
                <p className="pvb-billed-note">{plan.seats}</p>
              )}
              <p className="pvb-card-tagline">{plan.tagline}</p>
              <button
                type="button"
                className={`pvb-card-cta jaspen-btn ${plan.featured ? 'jaspen-btn-primary' : 'jaspen-btn-outline'}`}
                onClick={() => onOpenModal?.('signup', 'free')}
              >
                {plan.cta}
              </button>
            </div>
          );
        })}
      </div>

      {/* ── Compare plans accordion ── */}
      <div className="pvb-compare-accordion">
        <button
          type="button"
          className="pvb-compare-toggle"
          onClick={() => setCompareOpen(v => !v)}
          aria-expanded={compareOpen}
        >
          <span>Compare plans</span>
          <i className={`fa-solid fa-chevron-down pvb-compare-chevron${compareOpen ? ' is-open' : ''}`} aria-hidden="true" />
        </button>

        {compareOpen && (
          <div className="pvb-table-wrap">
            <table className="pvb-table">
              <thead>
                <tr>
                  <th className="pvb-th-label">Key features</th>
                  {PLANS.map(p => (
                    <th key={p.key} className={`pvb-th-plan ${p.featured ? 'is-featured' : ''}`}>
                      <button type="button" className={`pvb-compare-pill ${p.featured ? 'is-featured' : ''}`} onClick={() => onOpenModal?.('signup', 'free')}>{p.cta}</button>
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {FEATURES.map(section => (
                  <React.Fragment key={section.category}>
                    <tr className="pvb-category-row">
                      <td colSpan={5}>{section.category}</td>
                    </tr>
                    {section.rows.map(row => (
                      <tr key={row.label} className="pvb-feature-row">
                        <td className="pvb-feature-label">
                          {row.label}
                          {row.sub && <span className="pvb-feature-sub">{row.sub}</span>}
                        </td>
                        {PLANS.map(plan => (
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
      </div>

      {isAnnual && <p className="pvb-annual-note">* Per-month price shown. Charged as one annual payment.</p>}
      <p className="pvb-addons-note">
        Mid-cycle top-ups: <a href="/pages/pricing#credits">3,000 credits for $10 · 8,000 for $25 · 18,000 for $50</a>
      </p>

    </section>
  );
}
