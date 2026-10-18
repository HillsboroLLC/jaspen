# Jaspen: instructions for Claude

Read `docs/JASPEN_PRODUCT_CONTRACT.md` and `docs/JASPEN_CONSTITUTION.md` before proposing or reviewing any change to Jaspen. The coding rules in `AGENTS.md` apply to you too.

## How Lydia works with Claude on Jaspen

- **Jaspen is a thought partner** for consequential decisions. Never call it a "SaaS product".
- **Don't edit product code unless Lydia asks.** The default is to diagnose, then write a Codex prompt. Codex implements in development, and Claude reviews, runs the full test suites, and verifies.
- **Review against the foundation, not just the feature.** Every review reports:
  - what changed;
  - what's preserved;
  - what could be affected;
  - what needs Lydia's decision.

  Check the code itself and run the tests; don't rely on an agent's report alone.
- **Lens for every change:** does it let the AI give the user its best, while code protects only the guardrails (numbers, truth, labels, permissions, billing, approved behavior)? Flag keyword rules, forced steps, and dead ends.
- **Every Codex prompt includes a short usage block:**
  - one item per fresh session;
  - targeted reads and tests;
  - Claude runs the full suites;
  - short report.
- **Cost:** ask before paid AI runs, and keep them to the minimum.
- **Safety:**
  - no pushes to `main` (production) or `develop` without Lydia's approval each time;
  - the staging deploy workflow stays disabled until staging has its own database;
  - never use Lydia's Jira SCRUM project for testing (use JST or JPT).
- **Design:** solid colors only, never CSS gradients.
