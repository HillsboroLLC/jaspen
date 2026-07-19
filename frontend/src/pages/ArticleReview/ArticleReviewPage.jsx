import React, { useEffect, useMemo, useRef, useState } from 'react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { ArrowLeft, ArrowRight, BookOpen, Calculator, Clock3, Pause, Volume2 } from 'lucide-react';
import { Link, useParams } from 'react-router-dom';
import MarketingPageLayout from '../Marketing/MarketingPageLayout';
import Seo from '../../shared/components/Seo';
import './ArticleReviewPage.css';

const ARTICLES = [
  {
    slug: 'true-cost-of-home-ownership',
    title: 'What Is the True Monthly Cost of Owning a Home?',
    eyebrow: 'Personal finance',
    description: 'Separate the lender payment, the cost of carrying the home, cash to close, and equity—because one headline number cannot answer four different questions.',
    calculatorPath: '/tools/mortgage-calculator',
    calculatorLabel: 'Home ownership calculator',
    readingTime: '7 min read',
    listeningTime: '11 min listen',
    audioPath: '/article-review-narration/true-cost-of-home-ownership.mp3',
    railPoints: ['Required payment', 'True carrying cost', 'Cash to close', 'Equity built'],
  },
  {
    slug: 'true-cost-of-renting',
    title: 'What Does Rent Actually Cost Each Month?',
    eyebrow: 'Personal finance',
    description: 'See past advertised rent to concessions, recurring fees, utilities, move-in cash, and the portion of a deposit that is not automatically a cost.',
    calculatorPath: '/tools/rent-calculator',
    calculatorLabel: 'Rent calculator',
    readingTime: '6 min read',
    listeningTime: '7 min listen',
    audioPath: '/article-review-narration/true-cost-of-renting.mp3',
    railPoints: ['Effective rent', 'Recurring costs', 'Move-in cash', 'Refundable deposits'],
  },
  {
    slug: 'cost-of-employee-turnover',
    title: 'Employee Turnover Cost: Beyond the Flat Salary Multiple',
    eyebrow: 'Business operations',
    description: 'Build the estimate line by line—from recruiting and vacancy through ramp-up, knowledge transfer, and context recovery.',
    calculatorPath: '/tools/cost-of-turnover',
    calculatorLabel: 'Turnover cost calculator',
    readingTime: '8 min read',
    listeningTime: '9 min listen',
    audioPath: '/article-review-narration/cost-of-employee-turnover.mp3',
    railPoints: ['Vacancy', 'Hiring', 'Ramp-up', 'Knowledge loss'],
  },
  {
    slug: 'cost-of-rework',
    title: 'How to Calculate the Cost of Rework',
    eyebrow: 'Business operations',
    description: 'Put a boundary around repeated work, then calculate labor, coordination, documented nonlabor cost, and the portion the organization can reasonably influence.',
    calculatorPath: '/tools/rework-cost-calculator',
    calculatorLabel: 'Rework cost calculator',
    readingTime: '8 min read',
    listeningTime: '9 min listen',
    audioPath: '/article-review-narration/cost-of-rework.mp3',
    railPoints: ['Repeated labor', 'Coordination', 'Nonlabor cost', 'Influenceable share'],
  },
];

function slugify(value = '') {
  return value
    .toLowerCase()
    .replace(/[^a-z0-9\s-]/g, '')
    .trim()
    .replace(/\s+/g, '-');
}

function internalHref(href = '') {
  if (href.startsWith('https://jaspen.ai/')) return href.replace('https://jaspen.ai', '');
  return href;
}

function withoutReviewNotes(markdown = '') {
  return markdown.replace(/^(# [^\n]+\n\n)(?:>.*\n)+\n?/, '$1');
}

function OwnershipCostMap() {
  return (
    <figure className="article-purpose-diagram article-ownership-map">
      <figcaption>
        <span>One home, four different numbers</span>
        <strong>Keep the questions separate.</strong>
      </figcaption>
      <div className="article-ownership-map-grid">
        <div><small>Monthly obligation</small><strong>Required payment</strong><span>What must be paid to stay current</span></div>
        <div><small>Monthly budget</small><strong>True carrying cost</strong><span>Payment plus the cost of living in and preserving the home</span></div>
        <div><small>Upfront cash</small><strong>Cash to close</strong><span>What the transaction requires before move-in</span></div>
        <div><small>Balance sheet</small><strong>Equity built</strong><span>Principal that becomes ownership rather than expense</span></div>
      </div>
    </figure>
  );
}

function OwnershipExampleDiagram() {
  return (
    <figure className="article-purpose-diagram article-example-diagram">
      <figcaption>
        <span>Illustrative $400,000 home</span>
        <strong>Three outputs answer three different questions.</strong>
      </figcaption>
      <div>
        <section><small>Required monthly payment</small><strong>$2,556</strong><span>Principal, interest, taxes, and insurance</span></section>
        <section><small>True monthly carrying cost</small><strong>$3,189</strong><span>Required payment plus maintenance reserve and utilities</span></section>
        <section><small>Estimated cash to close</small><strong>$92,000</strong><span>Down payment plus modeled closing costs</span></section>
      </div>
      <p>Illustrative planning outputs, not market quotes.</p>
    </figure>
  );
}

function ArticleIndex({ reviewMode = false }) {
  const articleListJsonLd = {
    '@context': 'https://schema.org',
    '@type': 'CollectionPage',
    name: 'Jaspen Articles',
    description: 'Practical articles for understanding costs, assumptions, and tradeoffs before making a consequential decision.',
    url: 'https://jaspen.ai/articles',
    mainEntity: {
      '@type': 'ItemList',
      itemListElement: ARTICLES.map((article, index) => ({
        '@type': 'ListItem',
        position: index + 1,
        url: `https://jaspen.ai/articles/${article.slug}`,
        name: article.title,
      })),
    },
  };

  return (
    <MarketingPageLayout pageClass="page-article-review">
      <Seo
        title={reviewMode ? 'Calculator article review' : 'Articles for Clearer Decisions'}
        description={reviewMode ? 'Review-only calculator article drafts.' : 'Practical Jaspen articles that make costs, assumptions, and tradeoffs easier to see before you decide.'}
        canonicalPath={reviewMode ? '/review/articles' : '/articles'}
        noindex={reviewMode}
        jsonLd={reviewMode ? null : articleListJsonLd}
      />

      <section className="article-review-hero">
        <div>
          <p className="article-review-kicker"><BookOpen size={15} aria-hidden="true" /> {reviewMode ? 'Editorial review room' : 'Jaspen articles'}</p>
          <h1>{reviewMode ? <>Four useful answers.<br /><span>No content-farm voice.</span></> : <>Better decisions start<br /><span>with clearer numbers.</span></>}</h1>
          <p>{reviewMode ? 'These published articles explain the thinking behind Jaspen’s calculators without pretending an estimate is a verdict. This room mirrors the live articles for ongoing editorial review.' : 'Practical explanations of the costs, assumptions, and tradeoffs that are easy to miss when one headline number gets all the attention.'}</p>
        </div>
        {reviewMode ? (
          <aside className="article-review-note">
            <span>Review status</span>
            <strong>Published</strong>
            <p>All four articles are live in Articles, linked in the public navigation, and included in the sitemap.</p>
          </aside>
        ) : (
          <aside className="article-review-note article-review-note-public">
            <span>How Jaspen writes</span>
            <strong>Inspect the estimate.</strong>
            <p>Each article separates the parts of a decision so you can replace broad assumptions with numbers that match your situation.</p>
          </aside>
        )}
      </section>

      <section className="article-review-grid" aria-label="Article drafts">
        {ARTICLES.map((article, index) => (
          <Link key={article.slug} to={`${reviewMode ? '/review' : ''}/articles/${article.slug}`} className="article-review-card">
            <article>
              <div className="article-review-card-topline">
                <span>{article.eyebrow}</span>
                <span>0{index + 1}</span>
              </div>
              <h2>{article.title}</h2>
              <p>{article.description}</p>
              <div className="article-review-card-footer">
                <span><Clock3 size={15} aria-hidden="true" /> {article.readingTime}</span>
                <span className="article-review-open">Read article <ArrowRight size={16} aria-hidden="true" /></span>
              </div>
            </article>
          </Link>
        ))}
      </section>
    </MarketingPageLayout>
  );
}

function ArticleNavigation({ article, reviewMode }) {
  const index = ARTICLES.findIndex((entry) => entry.slug === article.slug);
  const previous = index > 0 ? ARTICLES[index - 1] : null;
  const next = index < ARTICLES.length - 1 ? ARTICLES[index + 1] : null;
  const basePath = reviewMode ? '/review/articles' : '/articles';

  return (
    <nav className="article-series-nav" aria-label="More Jaspen articles">
      <Link className="article-series-all" to={basePath}><BookOpen size={16} aria-hidden="true" /> All articles</Link>
      <div>
        {previous ? <Link to={`${basePath}/${previous.slug}`}><ArrowLeft size={16} aria-hidden="true" /><span><small>Previous article</small>{previous.title}</span></Link> : <span />}
        {next ? <Link to={`${basePath}/${next.slug}`}><span><small>Next article</small>{next.title}</span><ArrowRight size={16} aria-hidden="true" /></Link> : <span />}
      </div>
    </nav>
  );
}

function ArticleDraft({ article, reviewMode = false }) {
  const [markdown, setMarkdown] = useState('');
  const [error, setError] = useState(false);
  const [isListening, setIsListening] = useState(false);
  const audioRef = useRef(null);

  useEffect(() => {
    let active = true;
    setMarkdown('');
    setError(false);
    fetch(`/article-review-drafts/${article.slug}.md`)
      .then((response) => {
        if (!response.ok) throw new Error('Draft could not be loaded.');
        return response.text();
      })
      .then((text) => { if (active) setMarkdown(text); })
      .catch(() => { if (active) setError(true); });
    return () => { active = false; };
  }, [article.slug]);

  useEffect(() => {
    const audio = audioRef.current;
    setIsListening(false);
    return () => {
      if (audio) audio.pause();
    };
  }, [article.audioPath]);

  const displayMarkdown = useMemo(() => withoutReviewNotes(markdown), [markdown]);

  const articleJsonLd = useMemo(() => ({
    '@context': 'https://schema.org',
    '@type': 'Article',
    headline: article.title,
    description: article.description,
    mainEntityOfPage: `https://jaspen.ai/articles/${article.slug}`,
    publisher: {
      '@type': 'Organization',
      name: 'Jaspen',
      url: 'https://jaspen.ai',
    },
  }), [article]);

  const headings = useMemo(() => (
    displayMarkdown
      .split('\n')
      .filter((line) => line.startsWith('## '))
      .map((line) => line.replace(/^##\s+/, '').trim())
  ), [displayMarkdown]);

  const toggleNarration = () => {
    const audio = audioRef.current;
    if (!audio) return;

    if (!audio.paused) {
      audio.pause();
      return;
    }

    audio.play().catch(() => setIsListening(false));
  };

  return (
    <MarketingPageLayout pageClass="page-article-draft">
      <Seo
        title={reviewMode ? `${article.title} — Editorial review` : article.title}
        description={article.description}
        canonicalPath={reviewMode ? `/review/articles/${article.slug}` : `/articles/${article.slug}`}
        type="article"
        noindex={reviewMode}
        jsonLd={reviewMode ? null : articleJsonLd}
      />

      {reviewMode ? (
        <div className="article-draft-toolbar">
          <Link to="/review/articles"><ArrowLeft size={16} aria-hidden="true" /> Editorial review room</Link>
          <span>Published · Production layout mirror</span>
        </div>
      ) : null}

      <div className="article-draft-shell">
        <aside className="article-draft-rail">
          <p className="article-draft-rail-label">In this article</p>
          <nav aria-label="Article sections">
            {headings.map((heading) => <a key={heading} href={`#${slugify(heading)}`}>{heading}</a>)}
          </nav>
          <Link to={article.calculatorPath} className="article-draft-calculator-link">
            <Calculator size={18} aria-hidden="true" />
            <span><small>Related tool</small>{article.calculatorLabel}</span>
          </Link>
          <div className="article-draft-rail-summary">
            <p>At a glance</p>
            <ul>
              {article.railPoints.map((point) => <li key={point}>{point}</li>)}
              </ul>
            </div>
          <div className="article-draft-ad-stack" aria-label="Reserved advertisement placements">
            {['300 × 600', '300 × 250', '300 × 600'].map((size, index) => (
              <div className={`article-draft-ad-slot article-draft-ad-slot-${index + 1}`} key={`${size}-${index}`}>
                <span>Advertisement</span>
                <div>
                  <strong>Reserved ad placement</strong>
                  <small>{size}</small>
                </div>
              </div>
            ))}
          </div>
        </aside>
        <article className="article-draft-paper">
          <div className="article-draft-byline">
            <div>
              <span>{article.eyebrow}</span>
              <span><Clock3 size={14} aria-hidden="true" /> {article.readingTime}</span>
            </div>
            {article.audioPath ? (
              <>
                <button type="button" onClick={toggleNarration} disabled={!markdown} aria-pressed={isListening}>
                  {isListening ? <Pause size={15} aria-hidden="true" /> : <Volume2 size={15} aria-hidden="true" />}
                  <span>{isListening ? 'Pause article' : 'Listen to this article'}</span>
                  <small>{article.listeningTime}</small>
                </button>
                <audio
                  ref={audioRef}
                  src={article.audioPath}
                  preload="metadata"
                  onPlay={() => setIsListening(true)}
                  onPause={() => setIsListening(false)}
                  onEnded={() => setIsListening(false)}
                >
                  Your browser does not support audio playback.
                </audio>
              </>
            ) : null}
          </div>
          {error ? <p className="article-draft-error">This draft could not be loaded. Refresh the page and try again.</p> : null}
          {!error && !markdown ? <p className="article-draft-loading">Setting the page…</p> : null}
          {markdown ? (
            <ReactMarkdown
              remarkPlugins={[remarkGfm]}
              components={{
                h1: ({ children }) => <h1>{children}</h1>,
                h2: ({ children }) => {
                  const headingSlug = slugify(String(children));
                  return (
                    <>
                      <h2 id={headingSlug}>{children}</h2>
                      {article.slug === 'true-cost-of-home-ownership' && headingSlug === 'what-will-you-actually-have-to-pay-each-month' ? <OwnershipCostMap /> : null}
                      {article.slug === 'true-cost-of-home-ownership' && headingSlug === 'what-might-this-look-like-with-real-numbers' ? <OwnershipExampleDiagram /> : null}
                    </>
                  );
                },
                a: ({ href, children }) => {
                  const normalizedHref = internalHref(href);
                  const internal = normalizedHref.startsWith('/');
                  return internal
                    ? <Link to={normalizedHref}>{children}</Link>
                    : <a href={normalizedHref} target="_blank" rel="noreferrer">{children}</a>;
                },
              }}
            >
              {displayMarkdown}
            </ReactMarkdown>
          ) : null}
        </article>
      </div>

      <section className="article-draft-next">
        <p>Ready to check the math?</p>
        <div className="article-draft-next-row">
          <span>Start with researched assumptions, then replace every material input with your own numbers. No email required.</span>
          <Link className="article-draft-next-action" to={article.calculatorPath}>Open {article.calculatorLabel} <ArrowRight size={17} aria-hidden="true" /></Link>
        </div>
      </section>
      <ArticleNavigation article={article} reviewMode={reviewMode} />
    </MarketingPageLayout>
  );
}

export default function ArticleReviewPage({ reviewMode = false }) {
  const { slug } = useParams();
  if (!slug) return <ArticleIndex reviewMode={reviewMode} />;
  const article = ARTICLES.find((entry) => entry.slug === slug);
  if (!article) return <ArticleIndex reviewMode={reviewMode} />;
  return <ArticleDraft article={article} reviewMode={reviewMode} />;
}
