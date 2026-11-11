# Pricing and Capacity Verification Report

Status: repository evidence verified; production settings and realized economics unverified

Date: 2026-11-09

This report records current implementation evidence. It does not approve or
change prices, credit allocations, provider multipliers, capacity limits, or
production configuration.

## Pricing sources and configuration

| Concern | Repository evidence | Verification result / gap |
|---|---|---|
| Claude rates | `backend/app/billing_config.py::ANTHROPIC_PRICES_USD_PER_M` | Hard-coded per-model input/output rates with a conservative default. Manual code release required. |
| Gemini rates | `GEMINI_PRICES_USD_PER_M` | Hard-coded per-model rates; unknown Gemini falls back to Pro. Manual code release required. |
| Other providers | `provider_cost_usd` | Unknown provider returns zero. OpenAI is not a priced customer provider; target must fail closed for unknown billable models. |
| Rate update policy | billing-config comments | “Sticky on decrease,” update upward manually. No automatic rate-ingestion/update job found. Comment is not an effective-dated policy record. |
| Legacy multiplier | `JASPEN_MARGIN_MULTIPLIER`, default `3.0` | Environment-overridable. Actual production value not established. |
| Plan budgets | `JASPEN_BUDGET_FREE/STARTER/ESSENTIAL/TEAM/BUSINESS`, legacy Enterprise fallback | Environment-overridable. Defaults exist; production values unverified. |
| Provider-rate override | rate dictionaries | No environment override found. |
| New governance conversion | `ai_governance.py::CREDIT_POLICY_VERSION`, `CREDITS_PER_PROVIDER_DOLLAR` | `provider-cost-3600-v1`; 3,600 public credits/provider dollar and 1,000 internal units/public credit, ceiling rounded. |
| Activation | `JASPEN_CREDIT_POLICY_MODE` | `shadow|active|off`, default shadow. Repository code cannot prove production mode. |
| Purchased packs/plan allowances | `DEFAULT_PLAN_CATALOG`, `DEFAULT_CREDIT_PACKS` | Commercial defaults exist. This audit does not certify intended or realized margin. |

Current legacy arithmetic computes provider cost from actual model token usage,
multiplies by the configured margin, maps it into a plan budget percentage, and
rounds to internal credits. The governance policy instead uses an explicit
3,600-credit/provider-dollar conversion. Both pathways exist; shadow mode can
record the proposed result while legacy remains customer-visible. Until the
active production mode and operation coverage are authorized and observed,
uniform enforcement is **not verified**.

## Execution-path and settlement coverage

| Area | Current evidence | Status |
|---|---|---|
| Governed operations | `ai_runtime.py::execute_customer_operation` claims operation, reserves, validates, settles, persists, and supports replay. | Implemented/strong partial; still uses legacy credit authority. |
| Streaming conversation/tools | Documented governed special boundary in `AI_ROUTING_AND_CREDIT_POLICY_V1.md`; durable response cache and bounded tool flow. | Implemented/partial; must remain a first-class target test path. |
| Provider attempts/fallback | `ai_audit.py`, route error classification, Claude/Gemini route loops. | Implemented and tested in existing suites; customer fallback must retain one operation/reservation. |
| Failed attempts | Attempt cost/estimate captured and treated as Jaspen-absorbed; successful visible result charged once. | Implemented intent, consistent with the 2026-11-11 delivery-based policy; required absorbed-usage evidence and provider-dispute status incomplete; realized aggregate margin unverified. |
| Validation/persistence failure | Release/compensation behavior and charge-owner rules documented/tested for selected paths. | Partial across all operation families. Target: an undelivered response is not charged; a delivered or still-accessible response is charged even if a later nonessential step fails. |
| Preflight reservation | `_preflight_credit_estimate` and reserve/settle helpers. | Partial: fallback token estimate is not a complete worst-case provider/model/tool/context price. |
| Settlement | Actual usage/provider cost available for governed completions; delta settlement/release exists. | Partial: transient source allocation and competing balance authorities block proof. |
| Unknown model/provider | Claude/Gemini defaults, other provider zero; active policy may reject unpriced usage after execution-path checks. | Gap: authorization must fail closed before chargeable work. |
| Reporting | `AIOperation`/attempt totals and admin `UsageEvent` recalculation. | Useful telemetry, not authoritative margin accounting; duplicate/incomplete path risk remains. |

Provider retry, fallback, context expansion, and tool usage must be recorded as
components of one operation. The target binds provider/model rates, conversion,
rounding, and customer terms in a pricing-policy version at authorization. That
version survives fallback and in-progress work. A new version has an effective
UTC time and never reprices earlier operations.

When a new version changes customer credit consumption, an outbox obligation
records advance notice, effective date, impact, affected billing accounts, and
delivery evidence. No lead time, wording, or channel is invented here. A rate
change absorbed by Jaspen without customer-credit impact does not automatically
notify customers.

## Margin conclusion

The repository contains direct-cost calculation, plan budgets, a configurable
legacy multiplier, and a versioned 3,600-credit policy. That demonstrates a
designed margin mechanism, not realized margin. Realized results require
authorized production evidence joining revenue, discounts/fees/refunds,
successful and failed provider attempts, tools/context, subsidies, provider
invoices, and policy versions. No production access occurred in Phase 1.

## Capacity and abuse-control findings

| Control | Evidence | Status and architectural disposition |
|---|---|---|
| Hourly/daily requests | `_PLAN_HOURLY_LIMITS`, `_PLAN_DAILY_LIMITS`, shared Flask-Limiter scope | Implemented with numeric defaults; values are legacy facts, **not approved target limits**. |
| Short burst | Per-route minute decorators | Implemented on selected routes; retain as an abuse primitive, inventory coverage. |
| Shared backend | `rate_limits.py` requires reachable Redis in production | Implemented and executable tests exist. |
| Same-counter UI | `/api/v1/ai-agent/usage/daily` reads limiter storage | Implemented; frontend currently requests it only for Free users. |
| Denial behavior | Global 429 + `Retry-After`; tests assert no AI call/credit debit | Implemented/verified intent. Copy conflates buying credits with capacity and requires correction. |
| Organization fairness | Limiter key is `user:<id>`; test proves same-account users have independent quotas | Absent. A many-member organization can multiply capacity. |
| Tier awareness | Different request-count defaults by raw user plan/founder state | Partial. Not an org entitlement-based capacity authority or queue priority. |
| Concurrency | Bounded feature pools/tool flow; public-intake semaphore | Fragmented partial. No unified org/member tier concurrency budget. |
| Provider throttling | Retryable 429/5xx classification and fallback | Partial. No provider-pressure-aware customer capacity allocator. |
| Fallback | Claude/Gemini routing and attempt audit | Implemented/partial. Must not reset window, reservation, or price version. |
| Abuse detection | Fixed request limits and scoped risk concepts | Partial/absent as a unified governed service. |
| Runaway loops | Tool/response bounds and bounded worker pools on selected paths | Partial; no universal operation exposure budget. |
| Queue/priority | Retry response; no durable tier-priority queue found | Absent. |
| Credit independence | Blocked limiter request does not debit; credit purchase does not reset counter | Useful implemented property; preserve. |
| Future OpenAI | No current priced provider path | Architecture supports adapter addition only after rate/capacity/test coverage. |

The target capacity decision is made for organization + member + operation and
may consider entitlement tier, short windows, weighted work, concurrency,
provider availability, queue pressure, abuse/safety, and reserved exposure.
Credits and capacity are independent. A capacity denial returns when use may be
available, releases any unused reservation, preserves the session, and charges
nothing. Buying credits cannot bypass it.

## Customer experience findings

- Existing upper-right **BALANCE** and hover behavior can remain.
- Current status/UI combine balance fields and locally patch them from
  responses; target values must come from versioned ledger projections.
- Current low-credit backend threshold is hard-coded at 10%, and UI behavior is
  described as once per session with a user opt-out. The approved target is a
  configurable 20%, once per applicable period, with no customer custom-alert
  controls in the initial release.
- Current capacity UI is Free-only and request-count based. Target **Usage &
  Billing** must distinguish credit exhaustion from temporary capacity,
  including next refresh/payment/term and `available_again_at`.

## Existing executable tests versus future coverage

Existing repository suites include `test_ai_economics.py`,
`test_ai_governance.py`, `test_shared_ai_rate_limits.py`, billing/payment/pack/
offer tests, and charge-owner/streaming route tests. Their existence and any
successful local run prove only current behavior.

Local execution on 2026-11-09 used the existing project virtual environment:

- `test_ai_economics.py` plus `test_shared_ai_rate_limits.py`: **11 passed**.
- Combined with `test_ai_governance.py`: **59 passed, 2 failed**. Both failures
  are pre-existing provider-adapter/governance expectations: HTTP-200 refusal
  handling incorrectly entered fallback, and a mocked Claude timeout was
  classified as `invalid_response` instead of `timeout`. No code or tests were
  changed because this assignment authorizes documentation only.

Accordingly, rate arithmetic and current limiter properties are **test
verified** for the passing cases. The governance suite is not wholly green and
Claude-to-Gemini fallback classification is an explicit implementation risk;
it is not marked complete.

Future target tests are specified as T-PRICE-01..10, T-CAPACITY-01..12,
T-USAGE-01..10, and expanded T-AI-01..16 in
[traceability-and-cutover.md](traceability-and-cutover.md#d17-regression-traceability-matrix).
They cover effective dates, rate changes, notification evidence, unknown-model
fail-closed behavior, org/member fairness, tier concurrency/priority, provider
pressure/fallback, abuse/runaway bounds, no-charge denial, session continuation,
and ledger-synchronized overall/session usage.

## Verification limits

- No production/staging system, secret, environment variable, Stripe object, or
  provider billing account was accessed.
- No paid AI call was made.
- No application behavior, configuration, tests, schemas, or migrations changed.
- No numerical capacity recommendation is made. Selection requires authorized
  usage distributions, provider quotas and failure modes, tier economics,
  simulations, and customer scenarios.
