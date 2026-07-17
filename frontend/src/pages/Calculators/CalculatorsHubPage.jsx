import React, { useEffect, useMemo, useState } from 'react';
import { Link } from 'react-router-dom';
import { Search, X } from 'lucide-react';
import MarketingPageLayout from '../Marketing/MarketingPageLayout';
import Seo from '../../shared/components/Seo';
import { createAnalytics } from '../../tools/shared/createAnalytics';
import { AUDIENCE_FILTERS, CALCULATORS, SEO, calculatorsJsonLd } from './calculators';
import './CalculatorsHubPage.css';

const analytics = createAnalytics('calculators_hub');

export default function CalculatorsHubPage() {
  const [audience, setAudience] = useState('All');
  const [query, setQuery] = useState('');

  const visibleCalculators = useMemo(() => {
    const normalizedQuery = query.trim().toLowerCase();
    return CALCULATORS.filter((calculator) => {
      const audienceMatches = audience === 'All' || calculator.audience === audience;
      const searchable = [calculator.title, calculator.description, calculator.audience, calculator.topic].join(' ').toLowerCase();
      return audienceMatches && (!normalizedQuery || searchable.includes(normalizedQuery));
    });
  }, [audience, query]);

  useEffect(() => { analytics.track('calculator_hub_viewed', { calculator_count: CALCULATORS.length }); }, []);
  useEffect(() => {
    if (!query.trim()) return undefined;
    const timer = window.setTimeout(() => {
      analytics.track('calculator_search', { query_length: query.trim().length, match_count: visibleCalculators.length });
    }, 400);
    return () => window.clearTimeout(timer);
  }, [query, visibleCalculators.length]);

  const chooseAudience = (nextAudience) => {
    setAudience(nextAudience);
    analytics.track('calculator_audience_filter_selected', { audience: nextAudience.toLowerCase() });
  };
  const clearFilters = () => {
    setAudience('All');
    setQuery('');
    analytics.track('calculator_filters_cleared');
  };

  return (
    <MarketingPageLayout pageClass="page-calculators">
      <Seo title={SEO.title} description={SEO.description} canonicalPath={SEO.canonicalPath} jsonLd={calculatorsJsonLd()} />

      <section className="calculators-intro" aria-labelledby="calculators-title">
        <p className="calculators-eyebrow">Free calculators</p>
        <h1 id="calculators-title">Make the numbers easier to understand.</h1>
        <p>Explore practical calculators for personal choices and decisions at work.</p>
      </section>

      <section className="calculators-browser" aria-labelledby="calculator-grid-title">
        <h2 id="calculator-grid-title" className="calculators-sr-only">Browse free calculators</h2>
        <div className="calculators-filterbar">
          <div className="calculators-segments" role="group" aria-label="Filter calculators by audience">
            {AUDIENCE_FILTERS.map((filter) => (
              <button key={filter} type="button" className="calculators-segment" aria-pressed={audience === filter} onClick={() => chooseAudience(filter)}>{filter}</button>
            ))}
          </div>
          <label className="calculators-search">
            <span className="calculators-sr-only">Search calculators</span>
            <Search size={17} aria-hidden="true" />
            <input type="search" value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Search calculators" />
          </label>
        </div>

        <p className="calculators-count" aria-live="polite">
          {visibleCalculators.length} {visibleCalculators.length === 1 ? 'calculator' : 'calculators'}
        </p>

        {visibleCalculators.length ? (
          <div className="calculators-grid">
            {visibleCalculators.map((calculator) => {
              const Icon = calculator.icon;
              return (
                <Link key={calculator.route} to={calculator.route} className="calculator-card" onClick={() => analytics.track('calculator_card_clicked', { calculator: calculator.title, audience: calculator.audience.toLowerCase(), route: calculator.route })}>
                  <article>
                    <div className="calculator-card-topline">
                      <span className={`calculator-audience calculator-audience--${calculator.audience.toLowerCase()}`}>{calculator.audience}</span>
                      {calculator.status ? <span className="calculator-status">{calculator.status}</span> : null}
                    </div>
                    <Icon className="calculator-icon" size={25} strokeWidth={1.8} aria-hidden="true" />
                    <h3>{calculator.title}</h3>
                    <p>{calculator.description}</p>
                    <span className="calculator-open" aria-hidden="true">Open calculator →</span>
                  </article>
                </Link>
              );
            })}
          </div>
        ) : (
          <div className="calculators-empty" role="status">
            <X size={24} aria-hidden="true" />
            <h3>No calculators match that search.</h3>
            <p>Try another term or return to the full calculator library.</p>
            <button type="button" onClick={clearFilters}>Clear filters</button>
          </div>
        )}
      </section>

      <section className="calculators-bridge" aria-labelledby="calculators-bridge-title">
        <div>
          <p className="calculators-eyebrow">Beyond the estimate</p>
          <h2 id="calculators-bridge-title">Numbers can clarify the decision. Jaspen helps you think through it.</h2>
          <p>Calculators make assumptions and estimates visible. Jaspen helps you examine the tradeoffs, evidence, and execution behind the choice.</p>
        </div>
        <Link to="/pages/jaspen" className="calculators-bridge-cta" onClick={() => analytics.track('jaspen_product_cta_clicked', { target: 'jaspen_overview', source_page: 'calculators_hub' })}>See how Jaspen works →</Link>
      </section>
    </MarketingPageLayout>
  );
}
