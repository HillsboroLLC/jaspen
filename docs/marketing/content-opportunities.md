# Content Opportunities — Prioritized (Not Yet Built)

Last updated: 2026-07-14

Nothing in this document has been implemented. It is a planning list only, built on top of the keyword map (`seo-keyword-map.md`) and the technical SEO work completed so far. Ranked by expected business value: how likely the resulting page is to attract someone facing a real decision who could become a long-term Jaspen user, not by traffic potential alone.

## Technical SEO status check (why we're moving to content now)

Before this list, I checked for remaining technical issues: heading structure (every page has exactly one H1, correctly), image alt text (no images missing alt text), and internal links (every `Link` in the codebase points to a route that actually exists — no dead links found). I also found and fixed one more real issue: the 404 page had no `noindex` tag, so any mistyped or dead URL on the site would have been eligible for indexing. Fixed by extending the shared `Seo` component with an optional `noindex` prop and applying it to the 404 page.

One technical item remains, flagged but **not actioned**: this is a client-side-rendered app, and like most single-page apps, unmatched URLs likely return an HTTP 200 status (not a true 404) because the host serves `index.html` for any unrecognized path, then React renders the "page not found" view on top of that 200 response. This is commonly called a "soft 404" and Google Search Console will likely flag it once the site has enough crawl history. The `noindex` fix prevents these from being indexed, which covers the practical risk, but a full fix (returning an actual 404 status code) requires a routing-level change on Vercel that I can't verify from this environment. I'd want your sign-off before touching deployment routing, since a mistake there affects every page on the site, not just one.

## Prioritized content list

### 1. Weighted decision matrix guide
- **Target intent:** informational, "weighted decision matrix," "weighted scoring model," "decision matrix template" — an established, active search category with real competitor content (airfocus, Tempo, ProductSchool).
- **Business value:** highest of this list. This is the cluster Jaspen Score already partially serves, but the product page is a product pitch, not a neutral how-to guide. A dedicated guide can rank on the informational term, then hand off to Jaspen Score and Pricing for anyone ready to move from "how do I do this" to "what tool does this for me."
- **IA fit:** new page under a new `Resources > Guides` section (proposed below), linked from Jaspen Score and Project Management.

### 2. Decision-making frameworks compared (DACI, RAPID, Eisenhower Matrix, weighted scoring)
- **Target intent:** informational, "decision making framework," "DACI vs RAPID," "how to choose a decision framework" — confirmed active search category (Atlassian, ProjectManager.com, and others already rank here).
- **Business value:** strong topical-authority play. Positions Jaspen as knowledgeable about the whole landscape, not just its own method, which builds the kind of trust that turns a one-time reader into a return visitor. Natural link target from the Weighted Decision Matrix guide (#1) and Jaspen Score.
- **IA fit:** `Resources > Guides`, cross-linked with #1.

### 3. "Turning a decision into an execution plan" guide
- **Target intent:** informational/consideration, "how to turn a decision into a plan," "strategy execution vs project management" — real category, but dominated by leadership-operating-rhythm platforms (Elate, ClearPoint, AchieveIt) rather than anyone covering the specific decision-to-plan handoff.
- **Business value:** this is Jaspen's most specific, defensible differentiation (per its own product copy: "no translation step between strategy and delivery"), and currently no page explains the underlying problem in depth before pitching the product. A guide-first approach here can capture people earlier in their research, before they've decided a category.
- **IA fit:** `Resources > Guides`, linked from Project Management and the Jaspen product page.

### 4. Decision walkthrough examples (e.g., "build vs. buy," "which initiative to prioritize this quarter")
- **Target intent:** long-tail informational/consideration, highly specific to a real decision someone is actively facing right now rather than a general category term.
- **Business value:** directly matches your stated goal ("people facing meaningful decisions"), since these are the exact searches a person mid-decision would run. Lower individual search volume per topic, but higher relevance and conversion likelihood than broad category terms. Would need real worked examples (not fabricated ones) — I'd want your input or real customer scenarios before writing these, since invented case studies would cross into the overclaiming you've asked me to avoid.
- **IA fit:** `Resources > Guides`, could grow into its own recurring series over time.

### 5. Comparison content ("Jaspen vs. spreadsheet decision matrix," "Jaspen vs. [category] software")
- **Target intent:** decision-stage, bottom-of-funnel, high commercial intent.
- **Business value:** real, but riskiest to do well — needs to be accurate and fair to alternatives or it undermines trust rather than building it, and I don't currently have verified, sourced facts about named competitors to build this on. I'd want this to be the last of the five built, and only with your direct input on positioning, not something to draft speculatively.
- **IA fit:** could live under Pricing or a new `Compare` section; needs more thought once the guides above establish the site's editorial voice.

## Proposed IA change to support this

Right now, `Resources` covers Demos, Tutorials, Connectors, and Plugins — all product-adjacent, not educational. I'd recommend a new `Guides` section alongside it (nav already supports adding a column to the existing "Resources" mega-menu without restructuring anything else). This keeps product pages and educational content clearly separated, which matters for topical authority: search engines and readers both read a "guide" differently than a "feature page."

## Suggested build order

1. Weighted decision matrix guide
2. Decision-making frameworks compared
3. Turning a decision into an execution plan
4. Decision walkthrough examples (pending your input on real scenarios)
5. Comparison content (pending your input on positioning)

Each would still go through the same process as everything else so far: one recommendation, reasoning and expected impact explained, your approval, then a small, isolated change.
