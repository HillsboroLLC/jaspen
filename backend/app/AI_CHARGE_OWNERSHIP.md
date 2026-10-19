# AI charge ownership (Phase 1 C8 review)

A customer charge belongs to a completed, usable action, never to an HTTP
attempt. Provider retries and failover attempts are absorbed and cannot be
separate customer charges. This table was prepared before implementation, as
required by the Phase 1 specification.

| Operation type / family | Intended charge owner | Billable completion boundary | Phase 1 status |
|---|---|---|---|
| `conversation`, `legacy_chat`, `statistics_guidance`, `statistics_analysis`, `tool_guidance` | Conversation route | A usable assistant reply is returned. If narration fails after an outer-owned persisted mutation, that completed mutation remains billable. | Defined |
| `score_next`, `scorecard_generation` | Scorecard operation | The complete judgment passes scorecard validation and is persisted. Reuse is excluded. | Defined |
| `score_batch` | One governed batch operation, allocated to persisted generated scorecards | The intended batch charge is divided into equal integer shares in original option order. Only generated cards that persist retain a share; rounding remainder goes to the earliest persisted cards. Failed/unpersisted shares and provider retries are absorbed. Reused cards receive no share. | Implemented |
| `score_reuse` | Cache/reuse route | Never billable; no provider generation occurred. | Defined |
| `execution_plan` | Execution-plan operation | A complete, traced plan passes validation and is persisted. A tool-invoked plan is owned here, not by its surrounding conversation. | Defined |
| `execution_plan_refinement` | Plan-refinement operation | A response with edits is billable only when the server validates and atomically saves all edits. A save failure reverses the settlement; the browser refreshes the saved plan instead of reapplying actions. A guidance-only reply is billable when returned usable. | Implemented |
| `scorecard_assistant`, `portfolio_analysis`, `scenario_generation`, `strategy_generation`, `structured_generation`, `data_insights`, `report_generation`, `connector_idea_generation`, `batch_ranking`, `batch_clarification`, decision-asset email generation | Named feature route | The validated customer-visible result is returned, or persisted where that feature stores it. | Defined, subject to each route validating before settlement. |
| `decision_kit_classification` | Conversation orchestration | Internal component of the conversation; never a second charge in addition to the owning turn. | Defined |
| `context_summarization`, `knowledge_refresh`, `feedback_digest` | Jaspen/internal | Never customer billed (`customer_visible=False`); provider cost is absorbed and reported under the operation type. | Defined |
| `user_memory_extraction` | Jaspen/internal | Disabled and not called pending the Phase 3 memory design. | Disabled |
| `public_intake_chat` | Jaspen/public intake | Never account billed; provider cost is classified as public-intake subsidy. | Defined |
| Deterministic tools (fact/config changes, decision records, queue bookkeeping, cache reads) | No independent AI charge | No provider operation is created. A surrounding AI turn may own its own usable reply or completed outer mutation. | Defined |

## Nested action rule

`generate_scorecard` and `generate_execution_plan` open their own governed
operation. Their artifact charge belongs there. The surrounding conversation
may separately own a successful conversational reply, but it cannot claim the
artifact as its own completed action. If closing narration fails, the outer turn
is free when all successful actions were already settled by nested operations.

## Persistence and retry rule

Every settled artifact operation returns its operation id to the persistence
layer. If the artifact cannot be retained, that exact settlement is reversed
once and its provider cost is recorded as absorbed. Batch allocation is
finalized once per operation id; an idempotent replay reads the recorded
allocation and cannot refund or charge it again.
