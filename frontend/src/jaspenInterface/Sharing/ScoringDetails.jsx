import React from 'react';

import { flattenRows } from './reportModel';

const FINANCIAL_GROUPS = [
  ['Financial impact', 'financial_impact'],
  ['Investment analysis', 'investment_analysis'],
  ['Before', 'before_after_financials', 'before'],
  ['After', 'before_after_financials', 'after'],
  ['NPV & IRR', 'npv_irr_analysis'],
  ['Valuation', 'valuation'],
];

const humanize = (value) => String(value || '')
  .replace(/_/g, ' ')
  .replace(/\b\w/g, (letter) => letter.toUpperCase());

const cardName = (card) => (
  card?.display_overrides?.title
  || card?.project_name
  || card?.name
  || card?.label
  || 'Option'
);

const itemText = (item, keys) => {
  if (typeof item === 'string') return item.trim();
  if (!item || typeof item !== 'object') return '';
  const key = keys.find((candidate) => item[candidate]);
  return key ? String(item[key]).trim() : '';
};

const hasValue = (value) => value !== null && value !== undefined && value !== '';

const scoreValue = (value) => {
  if (!hasValue(value)) return null;
  const numeric = Number(value);
  return Number.isFinite(numeric) ? Math.round(numeric) : null;
};

const formatValue = (value, unit) => {
  if (value === null || value === undefined || value === '') return '';
  const display = typeof value === 'number' ? value.toLocaleString('en-US') : String(value);
  if (!unit) return display;
  if (unit === 'percent' || unit === '%') return `${display}%`;
  if (String(unit).toUpperCase() === 'USD') return `$${display}`;
  return `${display} ${unit}`;
};

const sourceLabel = (source) => ({
  conversation: 'Based on what you described',
  connector: 'Jaspen reports drawing on connected data',
  inferred: 'Inferred rather than stated',
  assumed: 'No supporting input identified',
  user: 'Stated by you',
}[String(source || '').toLowerCase()] || humanize(source));

const referenceSource = (reference) => {
  const locator = reference?.locator || {};
  if (reference?.kind === 'attachment') {
    const location = locator.location && typeof locator.location === 'object'
      ? Object.values(locator.location).filter(Boolean).join(' · ')
      : '';
    return [locator.filename || 'Uploaded file', location].filter(Boolean).join(' · ');
  }
  if (reference?.kind === 'connector') {
    return [String(locator.system || 'Connected system').toUpperCase(), locator.field]
      .filter(Boolean).join(' · ');
  }
  return 'From your input';
};

function DetailRows({ rows }) {
  if (!rows.length) return null;
  return (
    <dl className="op-detail-rows">
      {rows.map((row, index) => (
        <React.Fragment key={`${row.label}-${index}`}>
          <dt>{row.label}</dt>
          <dd>{row.value}</dd>
        </React.Fragment>
      ))}
    </dl>
  );
}

function CategoryScores({ card }) {
  const rationale = card.component_rationale && typeof card.component_rationale === 'object'
    ? card.component_rationale : {};
  const rows = Object.entries(card.component_scores || {}).map(([key, value]) => ({
    key,
    label: humanize(key),
    score: scoreValue(value),
    rationale: String(rationale[key] || '').trim(),
  })).filter((row) => row.score !== null);
  if (!rows.length) return null;
  return (
    <section className="op-detail-section" aria-label="Category scores">
      <h3 className="op-detail-heading">Category scores</h3>
      <div className="op-breakdown">
        {rows.map((row) => (
          <div className="op-breakdown__row" key={row.key}>
            <div className="op-breakdown__head">
              <span className="op-breakdown__label">{row.label}</span>
              {row.score !== null && <span className="op-breakdown__score">{row.score}<span className="op-muted">/100</span></span>}
            </div>
            {row.rationale && <div className="op-muted op-small">{row.rationale}</div>}
          </div>
        ))}
      </div>
    </section>
  );
}

function CriterionScores({ card }) {
  const dimensions = card.dimensions && typeof card.dimensions === 'object' && !Array.isArray(card.dimensions)
    ? card.dimensions : {};
  const rubric = card.scoring_rubric || card.rubric || {};
  const criteria = Array.isArray(rubric.criteria) ? rubric.criteria : [];
  const criterionByKey = Object.fromEntries(criteria.map((criterion) => [criterion.key, criterion]));
  const rows = Object.entries(dimensions).map(([key, dimension]) => {
    const criterion = criterionByKey[key] || {};
    return {
      key,
      label: dimension?.label || criterion.label || humanize(key),
      score: scoreValue(dimension?.score),
      rationale: String(dimension?.rationale || dimension?.summary || dimension?.reasoning || '').trim(),
      confidence: String(dimension?.confidence || '').trim(),
    };
  }).filter((row) => row.score !== null);
  if (!rows.length) return null;
  return (
    <section className="op-detail-section" aria-label="Criterion scores and rationale">
      <h3 className="op-detail-heading">Criterion scores and rationale</h3>
      <div className="op-breakdown">
        {rows.map((row) => (
          <div className="op-breakdown__row" key={row.key}>
            <div className="op-breakdown__head">
              <span className="op-breakdown__label">{row.label}</span>
              {row.confidence && <span className="op-muted op-small">{humanize(row.confidence)} confidence</span>}
              {row.score !== null && <span className="op-breakdown__score">{row.score}<span className="op-muted">/100</span></span>}
            </div>
            {row.rationale && <div className="op-muted op-small">{row.rationale}</div>}
          </div>
        ))}
      </div>
    </section>
  );
}

function EvidenceProfile({ card }) {
  const profile = card.evidence_profile && typeof card.evidence_profile === 'object'
    ? card.evidence_profile : null;
  const facts = card.facts && typeof card.facts === 'object' ? card.facts : {};
  const criteria = Array.isArray(profile?.criteria) ? profile.criteria : [];
  if (!profile && !Object.keys(facts).length) return null;
  const factRows = Object.entries(facts).map(([key, fact]) => ({
    label: fact?.label || humanize(key),
    value: `${formatValue(fact?.value, fact?.unit)}${fact?.source ? ` · ${sourceLabel(fact.source)}` : ''}`,
  })).filter((row) => row.value);
  return (
    <section className="op-detail-section" aria-label="Evidence profile">
      <h3 className="op-detail-heading">Evidence profile</h3>
      {profile && (
        <div className="op-evidence-summary">
          {hasValue(profile.evidence_backed_pct) && <span><strong>{profile.evidence_backed_pct}%</strong> stated facts</span>}
          {hasValue(profile.assumption_dependent_pct) && <span><strong>{profile.assumption_dependent_pct}%</strong> assumptions</span>}
        </div>
      )}
      <DetailRows rows={factRows} />
      {criteria.length > 0 && (
        <ul className="op-detail-list">
          {criteria.map((entry, index) => {
            const references = Array.isArray(entry?.evidence_references) ? entry.evidence_references : [];
            return (
              <li key={entry?.key || index}>
                <strong>{entry?.label || humanize(entry?.key)}</strong>
                {entry?.source && <span className="op-muted"> · {sourceLabel(entry.source)}</span>}
                {references.length > 0 && (
                  <ul className="op-detail-sources">
                    {references.map((reference, referenceIndex) => (
                      <li key={`${referenceSource(reference)}-${referenceIndex}`}>
                        <span className="op-detail-source">{referenceSource(reference)}</span>
                        {reference?.excerpt && <> — “{reference.excerpt}”</>}
                      </li>
                    ))}
                  </ul>
                )}
              </li>
            );
          })}
        </ul>
      )}
    </section>
  );
}

function Assumptions({ card }) {
  const rows = (Array.isArray(card.assumptions) ? card.assumptions : [])
    .map((item) => itemText(item, ['statement', 'assumption', 'text', 'label', 'description']))
    .filter(Boolean);
  if (!rows.length) return null;
  return (
    <section className="op-detail-section" aria-label="Assumptions">
      <h3 className="op-detail-heading">Assumptions</h3>
      <ul className="op-detail-list">{rows.map((item, index) => <li key={`${item}-${index}`}>{item}</li>)}</ul>
    </section>
  );
}

function Risks({ card }) {
  const items = [
    ...(Array.isArray(card.top_risks) ? card.top_risks : (Array.isArray(card.risks) ? card.risks : [])),
    ...(Array.isArray(card.key_considerations) ? card.key_considerations : []),
  ].map((item) => ({
    text: itemText(item, ['risk', 'text', 'title', 'description', 'consideration']),
    mitigation: typeof item === 'object' && item
      ? String(item.mitigation || item.mitigation_plan || item.response || '').trim() : '',
  })).filter((item) => item.text);
  if (!items.length) return null;
  return (
    <section className="op-detail-section" aria-label="Risks and considerations">
      <h3 className="op-detail-heading">Risks and considerations</h3>
      <ul className="op-detail-list">
        {items.map((item, index) => (
          <li key={`${item.text}-${index}`}>
            {item.text}
            {item.mitigation && <div className="op-strengthen op-small"><span className="op-strengthen__label">Mitigation:</span> {item.mitigation}</div>}
          </li>
        ))}
      </ul>
    </section>
  );
}

function FinancialsAndMetrics({ card }) {
  const groups = FINANCIAL_GROUPS.map(([title, outer, inner]) => {
    const value = inner ? card?.[outer]?.[inner] : card?.[outer];
    return { title, rows: flattenRows(value) };
  }).filter((group) => group.rows.length);
  const metrics = Object.entries(card.metrics || {}).map(([key, metric]) => {
    const isMetric = metric && typeof metric === 'object' && !Array.isArray(metric);
    return {
      label: metric?.label || humanize(key),
      value: formatValue(isMetric ? metric.value : metric, metric?.unit),
    };
  }).filter((row) => row.value);
  if (!groups.length && !metrics.length) return null;
  return (
    <section className="op-detail-section" aria-label="Financial sections and Decision Kit metrics">
      {groups.length > 0 && (
        <>
          <h3 className="op-detail-heading">Financial sections</h3>
          <div className="op-detail-grid">
            {groups.map((group) => (
              <div key={group.title}>
                <div className="op-col-label">{group.title}</div>
                <DetailRows rows={group.rows} />
              </div>
            ))}
          </div>
        </>
      )}
      {metrics.length > 0 && (
        <div className={groups.length ? 'op-detail-subsection' : ''}>
          <h3 className="op-detail-heading">Decision Kit metrics</h3>
          <DetailRows rows={metrics} />
        </div>
      )}
    </section>
  );
}

function CardDetails({ card, showName, hidden }) {
  return (
    <section className="op-option-details" aria-label={`${cardName(card)} scoring details`}>
      {showName && <h3 className="op-option-heading">{cardName(card)}</h3>}
      {!hidden.has('criteria') && <CategoryScores card={card} />}
      {!hidden.has('criteria') && <CriterionScores card={card} />}
      <EvidenceProfile card={card} />
      {!hidden.has('exposure') && <Assumptions card={card} />}
      {!hidden.has('exposure') && <Risks card={card} />}
      {!hidden.has('financials') && <FinancialsAndMetrics card={card} />}
    </section>
  );
}

export default function ScoringDetails({ artifactType, snapshot }) {
  const cards = artifactType === 'tradeoff'
    ? (Array.isArray(snapshot?.scorecards) ? snapshot.scorecards : [])
    : (snapshot?.scorecard ? [snapshot.scorecard] : []);
  const hidden = new Set(snapshot?.presentation?.layout?.hidden || []);
  return (
    <div className="op-scoring-details">
      {cards.map((card, index) => (
        <CardDetails
          key={card?.id || card?.analysis_id || `${cardName(card)}-${index}`}
          card={card}
          showName={cards.length > 1}
          hidden={hidden}
        />
      ))}
    </div>
  );
}
