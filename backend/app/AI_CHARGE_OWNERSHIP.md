# AI charge ownership (Phase 1 C8 review)

A customer charge belongs to a completed, usable action, never to an HTTP
attempt. Provider retries and failover attempts are absorbed and cannot be
separate customer charges. This table was prepared before implementation, as
required by the Phase 1 specification.

| Operation type / family | Intended charge owner | Billable completion boundary | Phase 1 status |
|---|---|---|---|
| `conversation`, `legacy_chat`, `statistics_guidance`, `statistics_analysis`, `tool_guidance` | Conversation route | A usable assistant reply is returned. If narration fails after an outer-owned persisted mutation, that completed mutation remains billable. | Defined |
| `score_next`, `scorecard_generation` | Scorecard operation | The complete judgment passes scorecard validation and is persisted. Reuse is excluded. | Defined |
| `score_batch` | Each completed scorecard, coordinated by batch scoring | Only generated scorecards that pass validation and persist are billable. Failed components and provider attempts are absorbed. | **Approval needed:** one provider settlement can produce a partially persisted batch; the approved allocation rule is not defined. |
| `score_reuse` | Cache/reuse route | Never billable; no provider generation occurred. | Defined |
| `execution_plan` | Execution-plan operation | A complete, traced plan passes validation and is persisted. A tool-invoked plan is owned here, not by its surrounding conversation. | Defined |
| `execution_plan_refinement` | Plan-refinement operation | The validated edit is persisted. | **Approval needed:** the current endpoint settles before its browser-applied `uiActions` are persisted. It is unclear whether the proposal or the saved edit owns the charge. |
| `scorecard_assistant`, `portfolio_analysis`, `scenario_generation`, `strategy_generation`, `structured_generation`, `data_insights`, `report_generation`, `connector_idea_generation`, `batch_ranking`, `batch_clarification`, decision-asset email generation | Named feature route | The validated customer-visible result is returned, or persisted where that feature stores it. | Defined, subject to each route validating before settlement. |
| `decision_kit_classification` | Conversation orchestration | Internal component of the conversation; never a second charge in addition to the owning turn. | Defined |
| `context_summarization`, `knowledge_refresh`, `user_memory_extraction`, `feedback_digest` | Jaspen/internal | Never customer billed (`customer_visible=False`); provider cost is absorbed and reported under the operation type. | Defined |
| `public_intake_chat` | Jaspen/public intake | Never account billed; provider cost is classified as public-intake subsidy. | Defined |
| Deterministic tools (fact/config changes, decision records, queue bookkeeping, cache reads) | No independent AI charge | No provider operation is created. A surrounding AI turn may own its own usable reply or completed outer mutation. | Defined |

## Nested action rule

`generate_scorecard` and `generate_execution_plan` open their own governed
operation. Their artifact charge belongs there. The surrounding conversation
may separately own a successful conversational reply, but it cannot claim the
artifact as its own completed action. If closing narration fails, the outer turn
is free when all successful actions were already settled by nested operations.

## Decisions required before implementation

1. **Partially persisted batch:** choose whether each option becomes its own
   governed operation (recommended because it gives every persisted scorecard
   an exact operation id and charge), or approve a deterministic allocation of
   one batch provider cost across the cards that persisted.
2. **Plan refinement:** confirm that the charge occurs only after the proposed
   `uiActions` are applied and the plan is durably saved (recommended and most
   consistent with the specification), rather than when the proposal is merely
   returned to the browser.

No C8 billing behavior should be merged until these decisions are resolved.
