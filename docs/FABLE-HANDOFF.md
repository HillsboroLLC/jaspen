# Handoff to Fable — marketing pass + the 14-day sprint

Paste this to Fable as context. Written by the marketing-pass agent (Claude).

## The one thing that matters: your 14-day plan wins

Lydia is running your "sell 5 Founding Decision Sprints" plan. That plan is
correct and takes priority over everything below. The three gates you named are
the only things that close a sale in the next 14 days:

1. Stripe Payment Link ($500) + grant Team via admin force-plan.
2. A bulletproof production demo path: homepage conversation → signup → handoff
   → their real decision → **scorecard** → trade-off → PDF export.
3. Board-ready PDF export.

Most of the marketing work described below is, by your own plan, "postpone until
after paying customers." Do not let it distract from the three gates. It is here
so it is not lost, and so you can pull the few pieces that actually help the
sprint.

## Where the marketing pass genuinely helps your sprint

- **Gate 2 depends on a scoring behavior fix.** During a live sales session, if
  the agent interviews instead of reaching a scorecard, the demo dies. See
  `docs/codex-brief-workspace-first-turn-scores.md`. It is now framed as "the
  workspace must always lead to a scorecard," score appears when the agent has
  enough, and improving it is a conversation (no button). This is the single
  most sprint-relevant item I produced. Please review it against the demo path.
- **Your objection script is already the site copy.** Your line "ChatGPT gives
  you an answer; this gives you one you can defend when the CFO asks why it's a
  72" is exactly what the new hero + "Why not just ChatGPT" + "How the score
  works" sections now say. If those branches merge, the site backs the sales
  pitch. Not required for the sprint, but zero-conflict reinforcement.
- **A leave-behind exists.** `docs/marketing/Jaspen-Decision-Scorecard.xlsx` (a
  working scorecard with confidence caps) can be a warm-up or leave-behind asset
  in sales conversations.

## IMPORTANT: actual git state (read before you touch branches)

The sandbox could not commit (a stale `.git/index.lock` on a worktree checkout).
So:

- I created feature-branch **refs** as labels, but **all my edits are
  uncommitted together in the working tree**, on whatever branch is currently
  checked out (`feature/continuous-conversation-intake`). The changes are NOT
  actually committed onto the named branches.
- Nothing is lost; it is all in the working tree. But the per-branch separation
  is nominal. You (or Lydia) need to `rm -f .git/index.lock`, then stage and
  commit the changes into the right branches. The branch names below map each
  logical change to its intended branch.

## What the marketing pass changed (all frontend + docs)

Branch labels and their intent:

- `feature/marketing-hero-rewrite` — homepage hero copy leads with the
  reproducible/auditable differentiator (`InteractiveDecisionHero.jsx`).
- `feature/marketing-trust-section` — new `WhyNotChatGPT.jsx` + `HowScoreWorks.jsx`
  on the homepage (comparison + score-anatomy with confidence caps).
- `feature/faq-refresh` — real FAQ matching current pricing (`FAQSection.jsx`),
  wired onto the homepage.
- `feature/remove-legacy-marketing-components` — moved four dead components
  (Founder/Transform-era) into `frontend/src/homeSections/review-for-deletion/`.
  Verified imported nowhere. Safe to delete after review.
- `feature/marketing-seo-methodology` — rewrote `/pages/jaspen-score` into an
  accurate methodology page with SEO meta + FAQ JSON-LD; added
  `public/sitemap.xml` and a robots.txt sitemap line.
- `feature/marketing-lead-capture-form` — `LeadCapture.jsx` + the scorecard as a
  public download. Best-effort POST to `/api/v1/public/leads` (endpoint not built;
  see `docs/codex-brief-lead-capture-endpoint.md`). Fails silently until wired.
- `feature/unify-page-header` — added `JaspenNav` to privacy/terms/support and the
  `/pricing` result page so every page uses the homepage header.
- `feature/hero-speech-to-text` — mic dictation on the hero input (Web Speech API).
- `feature/homepage-rubric-section` — compact "the rubric is yours" flow on the
  homepage (`RubricIsYours.jsx`).

Constraints I worked under: site palette only, no gradients, no emojis, Font
Awesome icons only, no em dashes, and **no backend/production files edited**
(the two backend items are briefs, not code).

## What I recommend you do, in order

1. Ship the three sprint gates. Nothing here blocks that.
2. Implement `codex-brief-workspace-first-turn-scores.md` as part of hardening the
   demo path — it is the one marketing-pass item that directly protects Gate 2.
3. Verify the PDF export renders board-ready.
4. Only if there is spare time before selling: merge the hero + trust-section +
   FAQ branches so the site matches the sales script. Everything else waits.
5. Leave the lead-capture backend, SEO, header, mic, and rubric branches parked
   until after paying customers, exactly as your plan says.

## Two questions worth your judgment

- Does the current agent reliably reach a scorecard on a single well-specified
  decision framed as an analysis request (the case that failed for Lydia's
  sister)? If not, that is the demo-path risk to fix first.
- Is the homepage → workspace handoff seam stable enough on production to run 10
  live sales sessions on it? That seam is the sales weapon; it must not flake.
