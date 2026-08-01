import fs from 'fs';
import path from 'path';
import {
  FOUNDER_CAMPAIGNS,
  FOUNDER_CREDITS,
  FOUNDER_GUARANTEE_QUALIFIER,
  FOUNDER_PRICE,
  FOUNDER_PROJECT_ESTIMATE,
  FOUNDER_TECHNICAL_GUARANTEE,
  FOUNDER_VARIABILITY_NOTE,
  SHARED_OFFER_DISCLOSURES,
  SHARED_OFFER_ITEMS,
  SHARED_DECISION_RECORD,
} from './founderCampaigns';

const campaigns = Object.values(FOUNDER_CAMPAIGNS);

describe('Founder campaign content', () => {
  it('defines three distinct audience routes, metadata records, and analytics identifiers', () => {
    expect(campaigns.map((campaign) => campaign.path)).toEqual([
      '/thinking-power',
      '/thinking-power/portfolio',
      '/thinking-power/strategic-planning',
    ]);
    expect(new Set(campaigns.map((campaign) => campaign.id)).size).toBe(3);
    expect(new Set(campaigns.map((campaign) => campaign.seo.title)).size).toBe(3);
    expect(new Set(campaigns.map((campaign) => campaign.seo.description)).size).toBe(3);
    expect(campaigns.map((campaign) => campaign.id)).toEqual([
      'founder_consultants',
      'founder_pmo',
      'founder_strategic_planning_aop',
    ]);
  });

  it('keeps the Founder values and limitations consistent across every variant', () => {
    expect(FOUNDER_PRICE).toBe(599);
    expect(FOUNDER_CREDITS).toBe('300,000');
    expect(FOUNDER_PROJECT_ESTIMATE).toBe('~750–1,200 typical project evaluations over the life of the gift');
    expect(FOUNDER_VARIABILITY_NOTE).toContain('Actual usage varies');
    expect(SHARED_OFFER_ITEMS.map((item) => `${item.value} ${item.label} ${item.detail}`).join(' ')).toContain(
      'Compare up to 30 projects in one focused session. Continue evaluating and retaining additional projects across sessions.',
    );

    const disclosures = SHARED_OFFER_DISCLOSURES.join(' ');
    expect(disclosures).toContain('enrolls you in Essential');
    expect(disclosures).toContain('billing begins after the included month');
    expect(disclosures).toContain('remain available until used');
    expect(disclosures).toContain('does not delete scorecards');
    expect(disclosures).toContain('No consulting service');
  });

  it('uses the approved technical-failure guarantee exactly', () => {
    expect(FOUNDER_TECHNICAL_GUARANTEE).toBe(
      'If a technical issue prevents you from completing the advertised workflow and our team cannot resolve it, we’ll refund your purchase.',
    );
    expect(FOUNDER_GUARANTEE_QUALIFIER).toBe(
      'This guarantee covers unresolved product failures. The quality and usefulness of the results depend on the information, evidence, assumptions, criteria, and decisions provided by the user.',
    );
  });

  it('keeps unsupported promises and named download formats out of campaign copy', () => {
    const copy = JSON.stringify({
      campaigns: FOUNDER_CAMPAIGNS,
      disclosures: SHARED_OFFER_DISCLOSURES,
      offer: SHARED_OFFER_ITEMS,
    });
    const forbiddenTerms = [
      /\bJira\b/i,
      /\bSmartsheet\b/i,
      /\bSalesforce\b/i,
      /\bPDF\b/i,
      /\bPPTX\b/i,
      /\bExcel\b/i,
      /\bWord\b/i,
      /\bCSV\b/i,
      /done for you/i,
      /consulting included/i,
      /guaranteed recommendation/i,
      /unlimited projects in one session/i,
      /portfolio limit of 30/i,
      /credits expire monthly/i,
    ];
    forbiddenTerms.forEach((term) => expect(copy).not.toMatch(term));
    expect(copy).not.toMatch(/\bSTRAT\b/);
    expect(copy).not.toMatch(/recommendation you can defend|defensible recommendation/i);
    expect(copy).toContain('downloadable decision assets');
  });

  it('uses the complete planning terms prominently for search and visitors', () => {
    const campaign = FOUNDER_CAMPAIGNS['strategic-planning'];
    const completePhrase = 'Strategic Planning and Annual Operating Planning (AOP)';
    expect(`${campaign.heroTitle} ${campaign.heroBody}`).toContain(completePhrase);
    expect(campaign.seo.title).toContain(completePhrase);
  });

  it('preserves the complete structured decision record', () => {
    expect(SHARED_DECISION_RECORD).toEqual([
      'What was being decided',
      'What options were considered',
      'What mattered',
      'What evidence was available',
      'What assumptions were made',
      'What was selected',
      'Why it was selected',
      'What happened afterward',
      'What the company learned',
    ]);
  });

  it('registers all campaign routes for routing, sitemap-driven prerendering, and responsive CSS', () => {
    const app = fs.readFileSync(path.join(process.cwd(), 'src/App.js'), 'utf8');
    const sitemap = fs.readFileSync(path.join(process.cwd(), 'public/sitemap.xml'), 'utf8');
    const css = fs.readFileSync(path.join(process.cwd(), 'src/pages/Marketing/FounderCampaignPage.css'), 'utf8');
    campaigns.forEach((campaign) => {
      expect(app).toContain(`path="${campaign.path}"`);
      expect(sitemap).toContain(`<loc>https://jaspen.ai${campaign.path}</loc>`);
    });
    expect(css).toContain('@media (max-width: 980px)');
    expect(css).toContain('@media (max-width: 720px)');
    expect(css).not.toMatch(/gradient/i);
  });

  it('pulls renewal prices from the public billing catalog instead of campaign copy', () => {
    const checkout = fs.readFileSync(
      path.join(process.cwd(), 'src/pages/Marketing/ThinkingPowerCheckout.jsx'),
      'utf8',
    );
    expect(checkout).toContain('/api/v1/billing/catalog');
    expect(checkout).toContain('monthly_price_usd');
    expect(checkout).toContain('annual_monthly_price_usd');
    expect(checkout).not.toContain('then $39/month');
  });
});
