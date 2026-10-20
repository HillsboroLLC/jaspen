# Instructions for coding agents working on Jaspen

Read these before making any change:
1. `docs/JASPEN_PRODUCT_CONTRACT.md`: how Jaspen behaves and how it's built.
2. `docs/JASPEN_CONSTITUTION.md`: the principles every feature must reinforce.

If a task conflicts with either, stop and ask. Don't resolve it yourself.

## The core rule

The AI owns the conversation, the user's intent, and the judgment. The code owns the numbers, the truth, permissions, and money. Don't add keyword or phrase-matching rules that decide what a user meant. If code needs intent, have the AI state it explicitly (for example through a tool call) and check that.

## Working rules

- **Scope:** do only the assigned task. List anything else you notice in your report; don't fix it.
- **Protect approved behavior.** Before changing anything, check what already-approved behavior it could affect. These must keep working:
  - a blank session starts clean (Balanced is the only default; no kit, data source, or carried-over context);
  - workflow steps advance only on real events;
  - plans have 10–18 tasks across 4–6 phases, with decision lineage;
  - decisions are per option, and human-owned fields are never overwritten;
  - per-plan Jira sync behaves as approved;
  - share-link disclosure protections hold;
  - billing charges only for usable results.
- **Ask instead of inventing** any user-facing wording, default, workflow, or product behavior that isn't specified.
- **No paid AI calls** without explicit approval. Use mocked or recorded responses in tests.
- **No production or staging access.** Staging is disabled because it currently shares production data. Verify locally (`./scripts/dev_setup.sh`, seed user `dev@jaspen.local`).
- **Database changes are additive,** with a downgrade, and with a server-side default for any new required column.
- **Git:**
  - always work in your own new worktree created from the stated base; never change the branch of, or edit files in, the main checkout (`/Users/ldbailey/Projects/jaspen-git/jaspen`). It's shared with other sessions and with Claude's live checks;
  - commit with `218708865+Bailey-Builds@users.noreply.github.com`;
  - one commit per item;
  - never push, merge, or deploy unless explicitly told to;
  - never force-push or rewrite shared history.
- **Never print, log, or commit secrets.**

## Working efficiently (usage is limited)

- Read only the functions you need; use `git grep` rather than opening whole large files (`routes/strategy.py` and `routes/ai_agent.py` are thousands of lines).
- Run only the related tests while working. Run the full suites once at the end, or skip them if told that Claude will run them.
- Keep reports short:
  - what changed;
  - what's preserved;
  - what could be affected;
  - tests and results;
  - decisions needed.
