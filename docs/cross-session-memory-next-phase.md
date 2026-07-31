# Cross-Session Decision Memory: Next Phase

This branch establishes durable standalone scorecards and canonical Decision
Records without adding a vector database. The next memory phase should build on
those artifacts rather than replaying every full conversation.

## Proposed layers

1. **Durable artifacts.** Scorecards, execution plans, evidence references, and
   Decision Records remain immutable-by-default rows with stable ids, ownership,
   organization, project, portfolio, timestamps, and supersession metadata.
2. **Canonical decision records.** A Decision Record connects alternatives,
   rubric, recommendation, final human decision, outcomes, and lessons. It is the
   long-lived narrative; scorecards remain separately addressable evidence.
3. **Organization and project entities.** Add explicit permission-bearing
   organization, portfolio, project, and initiative links instead of inferring
   identity from free text or a thread id.
4. **Permission-aware retrieval.** Retrieve only artifacts visible to the caller
   under user/org ownership and sharing policy. Apply authorization before
   ranking, not after context assembly.
5. **Lexical then semantic retrieval.** Start with indexed metadata, names,
   tags, rubric keys, dates, status, and score ranges. Add semantic retrieval
   behind a provider-neutral interface only after a measured corpus requires it.
6. **Summarized long-term memory.** Store attributed summaries that link back to
   source artifact ids and versions. Never let an unattributed summary replace
   the primary record.
7. **Current versus superseded information.** Add `supersedes_id`, effective
   dates, and explicit current/superseded status. Retrieval should prefer current
   information while allowing historical explanation.
8. **Outcomes.** Connect measured outcomes and lessons to the decision and
   scorecards that produced them so future guidance can distinguish forecast
   from observed result.
9. **Context assembly.** Build prompts from the user request plus a small ranked
   set of scorecard/Decision Record summaries, then fetch full artifacts only
   when needed. Never load all full chat histories by default.

The repository-level entry point is `app.scorecards.collect_peer_scorecards` for
thread compatibility and queryable `Scorecard` rows for cross-session search.
The next implementation should add entity links, supersession, permission-aware
search endpoints, and retrieval evaluation before selecting any vector store.
