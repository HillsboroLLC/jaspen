import React, { useEffect, useMemo, useState } from 'react';
import { Link } from 'react-router-dom';
import Seo from '../../shared/components/Seo';
import { useAuth } from '../../shared/auth/AuthContext';
import { createAnalytics } from '../../tools/shared/createAnalytics';
import ThinkingPowerCheckout from './ThinkingPowerCheckout';
import {
  FOUNDER_CAMPAIGNS,
  FOUNDER_CREDITS,
  FOUNDER_GUARANTEE_QUALIFIER,
  FOUNDER_PRICE,
  FOUNDER_PROJECT_ESTIMATE,
  FOUNDER_TECHNICAL_GUARANTEE,
  FOUNDER_VARIABILITY_NOTE,
  SHARED_FAQ,
  SHARED_OFFER_DISCLOSURES,
  SHARED_OFFER_ITEMS,
  SHARED_DECISION_RECORD,
  SHARED_WORKFLOW,
  getFounderCampaign,
} from './founderCampaigns';
import './FounderCampaignPage.css';

function structuredData(campaign) {
  return {
    '@context': 'https://schema.org',
    '@type': 'Product',
    name: `The Jaspen Advantage for ${campaign.eyebrow.replace(/^For /, '')}`,
    description: campaign.seo.description,
    brand: { '@type': 'Brand', name: 'Jaspen' },
    offers: {
      '@type': 'Offer',
      price: String(FOUNDER_PRICE),
      priceCurrency: 'USD',
      url: `https://jaspen.ai${campaign.path}`,
    },
  };
}

function ArrowIcon() {
  return <span aria-hidden="true">→</span>;
}

function CheckIcon() {
  return <span className="fc-check" aria-hidden="true">✓</span>;
}

function PrimaryButton({ campaign, onClick, variant = 'primary', showPrice = false }) {
  return (
    <button
      type="button"
      className={`fc-button fc-button--${variant}`}
      data-campaign={campaign.id}
      data-cta="jaspen-advantage-checkout"
      onClick={onClick}
    >
      {campaign.primaryCta}{showPrice ? ` · $${FOUNDER_PRICE}` : ''} <ArrowIcon />
    </button>
  );
}

function CampaignHeader({ campaign, onCta }) {
  return (
    <header className="fc-header">
      <div className="fc-container fc-header__inner">
        <Link to="/" className="fc-brand" aria-label="Jaspen home">Jaspen</Link>
        <nav className="fc-header__nav" aria-label="Campaign navigation">
          <a href="#workflow">How it works</a>
          <a href="#jaspen-advantage">The Jaspen Advantage</a>
          <button type="button" className="fc-button fc-button--nav" onClick={onCta}>
            Get The Jaspen Advantage
          </button>
        </nav>
      </div>
    </header>
  );
}

function Hero({ campaign, onCta }) {
  return (
    <section className="fc-hero">
      <div className="fc-container fc-hero__grid">
        <div className="fc-hero__copy">
          <p className="fc-eyebrow"><span aria-hidden="true" />{campaign.eyebrow}</p>
          <h1>{campaign.heroTitle}</h1>
          <p className="fc-hero__body">{campaign.heroBody}</p>
          <p className="fc-hero__callout">{campaign.heroCallout}</p>
          <div className="fc-hero__actions">
            <div className="fc-hero__cta-stack">
              <PrimaryButton campaign={campaign} onClick={onCta} showPrice />
              <span>$999 once. No subscription required.</span>
            </div>
          </div>
        </div>

        <aside className="fc-hero-offer" aria-labelledby="fc-hero-offer-title">
          <p className="fc-hero-offer__eyebrow">The Jaspen Advantage</p>
          <h2 id="fc-hero-offer-title">300,000 Thinking Power credits</h2>
          <ul>
            <li><CheckIcon /><span>Approximately {FOUNDER_PROJECT_ESTIMATE}</span></li>
            <li><CheckIcon /><span>No subscription required</span></li>
            <li><CheckIcon /><span>Compare up to 30 projects in one focused session</span></li>
            <li><CheckIcon /><span>Personal credits remain available until used</span></li>
            <li><CheckIcon /><span>Downloadable decision assets</span></li>
          </ul>
          <PrimaryButton campaign={campaign} onClick={onCta} showPrice />
          <p className="fc-hero-offer__price-note">$999 once. No subscription required.</p>
          <p className="fc-hero-offer__disclosure">
            Individual, non-transferable use. No auto renewal or monthly replenishment.
          </p>
        </aside>
      </div>
    </section>
  );
}

function UrgencyBar() {
  return (
    <section className="fc-urgency" aria-label="Campaign message">
      <div className="fc-container fc-urgency__inner">
        <strong>RANK THEM.</strong>
        <span>Before you fund it, rank it.</span>
        <span>Bring the possibilities. Leave with an order.</span>
      </div>
    </section>
  );
}

function MomentAndOutcome({ campaign }) {
  return (
    <section className="fc-section fc-section--moment">
      <div className="fc-container fc-two-up">
        <article className="fc-copy-panel">
          <p className="fc-kicker">The decision moment</p>
          <h2>{campaign.momentTitle}</h2>
          <p>{campaign.momentBody}</p>
        </article>
        <article className="fc-copy-panel fc-copy-panel--accent">
          <p className="fc-kicker">The outcome</p>
          <h2>{campaign.outcomeTitle}</h2>
          <p>{campaign.outcomeBody}</p>
        </article>
      </div>
    </section>
  );
}

function Workflow({ campaign }) {
  const workflow = campaign.workflow || SHARED_WORKFLOW.map((step) => step.title);
  return (
    <section className="fc-section" id="workflow">
      <div className="fc-container">
        <div className="fc-section-heading">
          <p className="fc-kicker">How it works</p>
          <h2>From inputs to a decision the room can follow.</h2>
          <p>Jaspen supports the judgment process without taking ownership of the decision away from you.</p>
        </div>
        {campaign.workflow ? (
          <ol className="fc-flow-list">
            {workflow.map((step, index) => (
              <li key={step}><span>{index + 1}</span><p>{step}</p></li>
            ))}
          </ol>
        ) : (
          <ol className="fc-workflow-grid">
            {SHARED_WORKFLOW.map((step, index) => (
              <li key={step.title}>
                <span>{String(index + 1).padStart(2, '0')}</span>
                <h3>{step.title}</h3>
                <p>{step.detail}</p>
              </li>
            ))}
          </ol>
        )}
      </div>
    </section>
  );
}

function Criteria({ campaign }) {
  if (!campaign.criteria) return null;
  return (
    <section className="fc-section fc-section--tint">
      <div className="fc-container fc-criteria">
        <div>
          <p className="fc-kicker">A context-aware rubric</p>
          <h2>{campaign.criteriaTitle}</h2>
          <p>{campaign.criteriaIntro}</p>
        </div>
        <ul className="fc-chip-list">
          {campaign.criteria.map((criterion) => <li key={criterion}>{criterion}</li>)}
        </ul>
      </div>
    </section>
  );
}

function DecisionRecord() {
  return (
    <section className="fc-section fc-decision-record">
      <div className="fc-container fc-decision-record__inner">
        <div>
          <p className="fc-kicker">Decision memory</p>
          <h2>What Jaspen becomes</h2>
          <p>
            Every time someone uses Jaspen, they create a structured record of how the decision was made, not just the final answer.
          </p>
        </div>
        <ul>
          {SHARED_DECISION_RECORD.map((item) => (
            <li key={item}><CheckIcon /><span>{item}</span></li>
          ))}
        </ul>
      </div>
    </section>
  );
}

function UsesAndAssets({ campaign }) {
  return (
    <section className="fc-section">
      <div className="fc-container fc-two-up fc-two-up--lists">
        <div>
          <p className="fc-kicker">Use it for</p>
          <h2>Real decisions with competing claims on attention and resources.</h2>
          <ul className="fc-use-grid">
            {campaign.useCases.map((item) => <li key={item}>{item}</li>)}
          </ul>
        </div>
        <div className="fc-leave-card">
          <p className="fc-kicker">What you leave with</p>
          <h2>Decision intelligence you can present, retain, and revisit.</h2>
          <ul>
            {campaign.leaveWith.map((item) => (
              <li key={item}><CheckIcon /><span>{item}</span></li>
            ))}
          </ul>
        </div>
      </div>
    </section>
  );
}

function FounderOffer({ campaign, onCta }) {
  return (
    <section className="fc-section fc-offer" id="jaspen-advantage">
      <div className="fc-container">
        <div className="fc-offer__heading">
          <div>
            <p className="fc-kicker">The Jaspen Advantage</p>
            <h2>Enough Thinking Power to keep doing the work.</h2>
          </div>
          <p>
            A limited launch offer for individual, self-directed work inside Jaspen. No monthly subscription and no automatic renewal.
          </p>
        </div>

        <div className="fc-offer__grid">
          {SHARED_OFFER_ITEMS.map((item) => (
            <article key={item.label}>
              <strong>{item.value}</strong>
              <h3>{item.label}</h3>
              <p>{item.detail}</p>
            </article>
          ))}
        </div>

        <p className="fc-estimate-note">{FOUNDER_VARIABILITY_NOTE}</p>

        <div className="fc-offer__checkout">
          <div>
            <span className="fc-offer__price">${FOUNDER_PRICE}</span>
            <span className="fc-offer__price-label">one-time Jaspen Advantage price</span>
          </div>
          <ul>
            <li>{FOUNDER_CREDITS} non-expiring usage credits</li>
            <li>Approximately {FOUNDER_PROJECT_ESTIMATE}</li>
            <li>No Essential subscription required</li>
            <li>Downloadable decision assets</li>
          </ul>
          <PrimaryButton campaign={campaign} onClick={onCta} variant="invert" />
        </div>

        <div className="fc-disclosures" aria-label="Jaspen Advantage disclosures">
          <h3>Before you purchase</h3>
          <ul>
            {SHARED_OFFER_DISCLOSURES.map((item) => <li key={item}>{item}</li>)}
          </ul>
        </div>
      </div>
    </section>
  );
}

function CreditComparison() {
  return (
    <section className="fc-section fc-section--tint">
      <div className="fc-container fc-comparison">
        <div>
          <p className="fc-kicker">Credit capacity comparison</p>
          <h2>More room to evaluate without a monthly clock.</h2>
          <p>
            Essential currently includes 7,000 monthly credits for $39. At that allowance,
            300,000 credits is about 42.9 months of credit capacity, or $1,671 at current
            monthly pricing. The Jaspen Advantage is $999 once, about $672 less for the
            credit capacity alone, before considering differences in plan features.
          </p>
        </div>
        <div className="fc-comparison__facts" aria-label="Credit comparison facts">
          <span><strong>300,000</strong> non-expiring credits</span>
          <span><strong>~42.9</strong> Essential monthly allowances</span>
          <span><strong>~40%</strong> lower credit-capacity cost</span>
        </div>
      </div>
    </section>
  );
}

function InputQuality() {
  return (
    <section className="fc-section">
      <div className="fc-container fc-input-quality">
        <p className="fc-kicker">Better context creates sharper guidance</p>
        <h2>Bring the information the decision actually depends on.</h2>
        <p>
          Give Jaspen a clear objective, the options in scope, real constraints, available
          evidence, known assumptions, and the criteria that matter. Complete inputs usually
          support a more efficient evaluation. Attachments, deeper analysis, follow-up, and
          revisions use more credits.
        </p>
      </div>
    </section>
  );
}

function Guarantee() {
  return (
    <section className="fc-section fc-section--compact">
      <div className="fc-container fc-guarantee">
        <p className="fc-kicker">Narrow technical guarantee</p>
        <h2>{FOUNDER_TECHNICAL_GUARANTEE}</h2>
        <p>{FOUNDER_GUARANTEE_QUALIFIER}</p>
      </div>
    </section>
  );
}

function Faq({ campaign }) {
  return (
    <section className="fc-section fc-section--tint">
      <div className="fc-container">
        <div className="fc-section-heading">
          <p className="fc-kicker">Questions</p>
          <h2>What to know before you start.</h2>
        </div>
        <div className="fc-faq-grid">
          {[...campaign.faq, ...SHARED_FAQ].map((item) => (
            <article key={item.q}>
              <h3>{item.q}</h3>
              <p>{item.a}</p>
            </article>
          ))}
        </div>
      </div>
    </section>
  );
}

function CampaignFooter({ campaign, onCta }) {
  return (
    <>
      <section className="fc-closing">
        <div className="fc-container fc-closing__inner">
          <div>
            <p className="fc-kicker">Be ready for the room</p>
            <h2>{campaign.heroCallout}</h2>
          </div>
          <PrimaryButton campaign={campaign} onClick={onCta} variant="light" />
        </div>
      </section>
      <footer className="fc-footer">
        <div className="fc-container fc-footer__inner">
          <span>© {new Date().getFullYear()} Jaspen</span>
          <nav aria-label="Footer">
            <Link to="/pages/jaspen">About Jaspen</Link>
            <Link to="/pages/privacy">Privacy</Link>
            <Link to="/pages/terms">Terms</Link>
            <Link to="/pages/support">Support</Link>
          </nav>
        </div>
      </footer>
    </>
  );
}

export default function FounderCampaignPage({ campaignKey = 'consultants' }) {
  const campaign = getFounderCampaign(campaignKey);
  const { user } = useAuth();
  const [checkoutOpen, setCheckoutOpen] = useState(false);
  const [checkoutNotice, setCheckoutNotice] = useState('');
  const analytics = useMemo(() => createAnalytics(campaign.id), [campaign.id]);

  useEffect(() => {
    analytics.track('advantage_campaign_viewed', { campaign_id: campaign.id, route: campaign.path });
  }, [analytics, campaign.id, campaign.path]);

  useEffect(() => {
    if (typeof window === 'undefined') return;
    const params = new URLSearchParams(window.location.search || '');
    const checkoutState = params.get('advantage_checkout');
    if (!checkoutState) return;
    if (checkoutState === 'resume' && user) {
      analytics.track('advantage_checkout_started', { campaign_id: campaign.id, resumed: true });
      setCheckoutOpen(true);
    }
    if (checkoutState === 'success') {
      analytics.track('advantage_purchase_completed', { campaign_id: campaign.id });
      setCheckoutNotice('Payment received. Your credits will appear as soon as Stripe confirms the payment.');
    }
    if (checkoutState === 'cancel') {
      setCheckoutNotice('Checkout was canceled. No charge was made.');
    }
    params.delete('advantage_checkout');
    params.delete('session_id');
    const query = params.toString();
    window.history.replaceState({}, '', `${window.location.pathname}${query ? `?${query}` : ''}${window.location.hash || ''}`);
  }, [analytics, campaign.id, user]);

  const openCheckout = () => {
    analytics.track('advantage_primary_cta_clicked', { campaign_id: campaign.id, route: campaign.path });
    analytics.track('advantage_checkout_started', { campaign_id: campaign.id, resumed: false });
    setCheckoutOpen(true);
  };

  return (
    <div className={`fc-page fc-page--${campaign.theme}`} data-campaign-id={campaign.id}>
      <Seo
        title={campaign.seo.title}
        description={campaign.seo.description}
        canonicalPath={campaign.path}
        jsonLd={structuredData(campaign)}
      />
      <CampaignHeader campaign={campaign} onCta={openCheckout} />
      {checkoutNotice && <div className="fc-checkout-notice" role="status">{checkoutNotice}</div>}
      <main>
        <Hero campaign={campaign} onCta={openCheckout} />
        <UrgencyBar />
        <MomentAndOutcome campaign={campaign} />
        <Workflow campaign={campaign} />
        <DecisionRecord />
        <Criteria campaign={campaign} />
        <UsesAndAssets campaign={campaign} />
        <FounderOffer campaign={campaign} onCta={openCheckout} />
        <CreditComparison />
        <InputQuality />
        <Guarantee />
        <Faq campaign={campaign} />
        <CampaignFooter campaign={campaign} onCta={openCheckout} />
      </main>

      {checkoutOpen && (
        <ThinkingPowerCheckout
          campaignId={campaign.id}
          returnPath={campaign.path}
          onClose={() => setCheckoutOpen(false)}
        />
      )}
    </div>
  );
}

export { FOUNDER_CAMPAIGNS };
