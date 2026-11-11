# Current Billing State, Retirement, and Conflict Inventory

Inventory base: `88684284a33836106cad639d36e191271109c2c7`, with Phase 1
documentation reconciliation performed on `7d2e2510`.
Line numbers are intentionally omitted because Phase 2 will change them;
functions and symbols are the stable trace keys.

## D04 Current writer, reader, and owner inventory

### Persisted stores and effective owners

| Store | Current writers | Current readers | Current effective owner/problem |
|---|---|---|---|
| `users.subscription_plan`, `subscription_status`, `stripe_*` | signup/admin/auth helpers; checkout confirmation; embedded sync; Stripe webhook; subscription modification/deletion | auth payloads; billing status; entitlement gates; org sync; frontend account/workspace/menu | `User` is simultaneously payer, plan, and capability authority; organization billing is indirect |
| `users.credits_remaining`, `credits_reset_at` | `apply_plan_to_user`, pool resolvers, bootstrap, reset job, consume/release/cap, admin controls, auth admin enforcement, webhooks, stream persistence | auth payload, billing status, admin UI, AI preflight, workspace/menu | Combined mutable counter duplicates monthly and persistent stores |
| `users.ui_preferences.thinking_power` | `_resolve_user_pool`, add/consume/release/cap/reset | `get_usage_meter_state` | UI preferences act as a personal recurring-credit database |
| `organizations.settings.thinking_power` | `_resolve_org_pool`, add/consume/release/cap/reset | `get_usage_meter_state` | Generic settings JSON acts as an organization recurring-credit database |
| `organizations.plan_key` | organization creation and `sync_org_plan_from_owner` | collaboration/seat/team gates | Plan is synchronized from owner during resolution and team reads |
| `organizations.max_total_paid_seats` | seat purchase endpoint and org/admin operations | seat policy/payload, team capacity | Commitment, capacity, and manual override overlap |
| `payments` | `_record_payment`, payment backfill script | admin revenue analytics | Positive receipt/redemption facts only; refunds/disputes absent |
| `account_entitlements` | limited-time offer grant/reversal | effective plan, rate limits, billing UI | One offer-specific entitlement partially separates capability from plan |
| `persistent_credit_grants.remaining_amount/status` | offer/pack grants, consumption, release, refund/dispute reversal | balance/status/effective plan | Mutable lot balance is authoritative alongside an append-only audit table |
| `persistent_credit_transactions` | persistent grant/usage/release/reversal helpers | tests and audit | Append-only only for persistent sources, not recurring or all adjustments |
| `stripe_webhook_events` | webhook receipt plus purchase claim helpers | webhook dedupe/tests | Event receipt and business idempotency claims share one table; no object ordering |
| `usage_events` | operation persistence and selected routes/services | admin analytics/evaluations | Telemetry stores charged values but is not linked to a universal credit entry |
| `ai_operations`, `ai_provider_attempts` | AI runtime/audit | idempotent replay, tests, analytics | Correct operation boundary exists, but reservation source is held on ORM-instance attributes |
| live Stripe subscription metadata | create/modify/cancel/resume/clear schedule; webhook clear | billing status; webhook renewal logic | Stripe metadata is the only scheduled-change store and audit history is lost |

### Mutation functions

| Current function/route | Mutations | Trigger/read overlap | Target owner |
|---|---|---|---|
| `billing_config._resolve_user_pool` | initializes/resets UI meter, `credits_remaining`, `credits_reset_at` | called by status/preflight helpers | Credit Ledger commands only; projection becomes pure |
| `billing_config._resolve_org_pool` | initializes/resets org JSON meter | called by status/preflight helpers | Credit Ledger commands only |
| `billing_config.bootstrap_legacy_credits` | initializes counters/meters | login, `/auth/me`, `/auth/me-cookie`, billing status, AI/strategy routes | One migration/backfill; remove runtime call |
| `billing_config.apply_plan_to_user` | plan, balance, reset timestamp, meter | signup, admin, sync, webhooks, auth admin enforcement | Entitlement command plus separate funded-period command |
| `billing_config.reset_user_monthly_credits` | replenishes recurring meter | CLI job and webhook | Credit-period allocator using immutable anchor and idempotency key |
| `billing_config.consume_credits` | debits JSON meter, persistent grants, combined counter; may go negative | AI reservation | Ledger reservation only |
| `billing_config.release_consumed_credits` | restores sources using transient `_last_*_debit` attributes | failed/partial AI operation | Ledger release tied to reservation allocations |
| `billing_config.cap_monthly_credits` | reduces recurring balance | dunning webhook | No target equivalent; dunning does not confiscate funded value |
| `billing_config.get_usage_meter_state` | calls mutating resolvers | billing status, preflight, webhook post-processing | Pure projection query |
| `founder_entitlements.grant_*` | entitlement, mutable grant, transaction | payment/session/invoice events and browser confirmation | Entitlement + Credit Ledger commands |
| `founder_entitlements.consume/refund_*` | mutable grant plus transactions | AI reserve/release | Credit Ledger allocation/release |
| `founder_entitlements.reverse_*` | sets lot to zero/reversed | full or partial refund; dispute opened | Cumulative refund/dispute authority |
| `auth._enforce_admin_account_profile` | plan/unlimited/session cap and credit reset | login, `/me`, cookie auth, signup/Google auth | Explicit internal entitlement/funding provisioning command |
| `orgs.ensure_default_organization_for_user` | creates org/membership, changes active org, syncs plan | auth and organization resolution | Explicit onboarding command; resolver is pure |
| `orgs.sync_org_plan_from_owner` | rewrites org plan from payer user | resolution/team access | Entitlement projection, not a write |
| `billing.get_billing_status` | legacy bootstrap/admin provisioning/meter initialization | HTTP `GET` | Pure billing projection |
| `billing.sync_embedded_subscription` | processor IDs, status, plan, full credit reset | browser confirmation | Financial event confirmation then entitlement/period commands |
| `billing.modify_subscription` | Stripe price/metadata, user status/plan | customer command | Scheduled-change/upgrade state machine |
| `billing.stripe_webhook` | all subscription, plan, credit, financial, refund/dispute state | external event | Inbox dispatch to four authorities |
| `admin.patch_user`, `force_plan`, `adjust_user_credits`, recovery reset | direct plan/counter/seat/reset writes | internal admin command | Authorized entitlement, seat, or internal funding ledger commands |
| `ai_agent._reserve/_settle/_release_*` | balance mutation and stream persistence | AI operation | AI operation orchestrates ledger reservation/settlement |
| `backend/scripts/reset_monthly_credits.py` | iterates users and resets | scheduled command | Period allocator by due period, not user scan/reset |

### Route and service readers

| Reader | Fields/queries consumed | Risk |
|---|---|---|
| `routes/auth.py` payloads and login | raw plan, combined credits, active org | authentication currently provisions and resets before reading |
| `routes/billing.py /status` | every plan/balance/entitlement/schedule field plus live Stripe | read mutates and mixes local and live external state |
| `routes/ai_agent.py` | effective plan, usage state, raw balance | preflight can reset; many route-local bootstrap calls |
| `routes/strategy.py` | effective plan/bootstrap/consume imports | strategy reads can initialize legacy credits |
| `ai_runtime.py`, `ai_audit.py` | operation records, raw plan, payments, grants, raw balance | operation idempotency is useful, but subsidy and settlement infer across authorities |
| connector/insight/report routes | raw plan or shared AI runtime | capability checks and payment-required responses depend on legacy projections |
| homepage promotion service | persistent grant status/source | promotion reporting reads mutable grant authority |
| `orgs.py`, team routes, sharing | raw owner plan/status and org plan | payer ownership and active org can influence access |
| admin routes/analytics | user counters, payments, usage events | UI exposes direct authoritative-looking edits and revenue omits reversals |
| `decision_asset_email_service.py` | `UsageEvent` | telemetry only; must not imply settlement authority |
| payment/usage/reset scripts | payments, users, usage events, monthly reset | backfill and scheduled work write/read legacy authorities outside request paths |
| dev seed script | raw plan and credit counter | fixtures encode the old combined-counter model |
| frontend `Account.jsx`, `StripeCheckout.jsx` | billing status/catalog/seats/schedules | relies on compatibility response shape |
| frontend `JaspenChat.jsx`, `AppMenu.jsx` | effective plan and combined balance | locally patches balance from operation responses |
| frontend admin surfaces | raw credits and seat fields | direct mutable-counter editing model |

### External and scheduled dependencies

- Stripe Customer, Subscription, Subscription Item, Price, Invoice, Invoice
  Line, PaymentIntent, Checkout Session, Charge, Refund, Dispute, Promotion
  Code, Customer Portal, and webhook delivery.
- Application configuration for price IDs, plan catalog, credit packs, seat
  prices, admin allowlist, and provider-cost policy.
- CLI monthly-reset scheduler.
- Email delivery used inline by the limited-time offer receipt.
- SQLAlchemy transaction behavior and JSON mutation tracking.
- Frontend polling/refetch after subscription confirmation and AI operations.

### Existing regression fixtures

| Fixture/test area | Evidence available |
|---|---|
| `backend/tests/conftest.py` | isolated app/database, user/admin, auth headers, test Stripe IDs |
| `test_billing.py` | webhook signature, catalog, annual checkout, team/business seat purchase |
| `test_credit_pack_idempotency.py` | duplicate/cross-type/out-of-order/concurrent deliveries, reset survival, unused-pack refund |
| `test_founder_offer_infrastructure.py` | idempotent offer grants, entitlement separation, renew/reset survival, source consumption/release |
| `test_limited_time_300k_refund_and_receipt.py` | refund recognition, webhook reversal, idempotent receipt, failed-send independence |
| `test_payment_recording.py` | paid/comped receipts, duplicate invoice idempotency, interval and pack recording |
| `test_single_device_and_personal_credits.py` | legacy member-attributed value and team-pool separation; useful preservation intent, not approval of personal billing accounts |
| `test_ai_governance.py` | operation idempotency, validate-before-settle, exact release/reversal, batch allocation |
| `test_ai_economics.py` | provider-rate arithmetic and reported provider cost |
| `test_shared_ai_rate_limits.py` | shared hourly/daily request counters, Redis cross-worker behavior, per-user isolation, burst limits, and no charge when blocked |

### Verified pricing and AI execution controls

- `billing_config.py` hard-codes Claude and Gemini catalog-rate tables. Unknown
  Claude models use a Sonnet default, unknown Gemini models use a Pro default,
  and any other provider currently returns zero cost. No OpenAI customer path
  is priced.
- Legacy conversion uses provider cost, `JASPEN_MARGIN_MULTIPLIER` (default
  `3.0`), and plan budgets overridable by `JASPEN_BUDGET_*`. Provider rate
  tables themselves have no environment override and require a code change.
- The newer governance policy is separately versioned as
  `provider-cost-3600-v1`, mapping provider cost to 3,600 public credits per
  provider dollar (1,000 internal units per public credit) with ceiling
  rounding. `JASPEN_CREDIT_POLICY_MODE` defaults to `shadow`; therefore code
  presence is not proof of production enforcement.
- No operational automatic provider-rate ingestion/update job was found. The
  code comment prescribes manual upward updates and sticky-on-decrease behavior.
  There is no effective-dated customer pricing table or notification evidence.
- `ai_runtime.py`, `ai_audit.py`, and governed routes provide useful operation,
  provider-attempt, idempotency, validation, cost, and settlement evidence.
  Failed attempts are recorded/absorbed and a successful visible result is
  intended to settle once. This matches the 2026-11-11 delivery-based
  billability policy in intent; the required absorbed-usage evidence fields and
  uncertain-usage reconciliation are not yet complete. The streaming tool boundary is a documented special
  path and must remain in coverage.
- Legacy preflight estimation can fall back to token-count charging without a
  full provider/model rate calculation. Current reservations and transient
  source allocations therefore do not prove exact worst-case coverage across
  context growth, tools, retries, or fallback.
- Admin reporting uses both `AIOperation` attempt costs and recalculated
  `UsageEvent` costs. This is valuable telemetry, but reporting is not a
  ledger/profit authority and realized gross margin cannot be verified here.
- Production environment values were not accessed. Code defaults and example
  configuration are evidence only; actual production multiplier, modes,
  budgets, model IDs, and provider tiers remain unverified.

See [pricing-and-capacity-verification.md](pricing-and-capacity-verification.md)
for execution-path and evidence detail.

### Verified capacity, fallback, and abuse controls

- AI conversation routes use fixed-window, per-user hourly/daily request
  counters plus route-specific minute bursts. Current code contains numeric
  plan defaults and a founder override; these are implementation facts, not the
  approved future capacity policy.
- Production startup requires shared Redis-backed rate-limit storage and fails
  closed if it is missing or unavailable. Non-production defaults to memory.
- `/api/v1/ai-agent/usage/daily` exposes the same counters, but the current
  frontend loads it only for Free users. A global 429 response supplies
  `Retry-After`, but incorrectly suggests buying credits can provide more
  capacity.
- The limiter key is `user:<id>`. Tests explicitly show members of the same
  account have independent quotas, so the present implementation cannot prevent
  a large organization from multiplying capacity by member count and is not an
  organization-wide fairness control.
- Claude/Gemini routing, retryable-error classification, provider-attempt
  telemetry, and fallback tests exist. Some processing turns may prefer Gemini;
  Business/Enterprise content blocks free-tier Gemini. OpenAI is not a current
  customer provider.
- Bounded feature-level parallelism and tool-loop guards exist, but no unified
  tier-aware concurrency allocator, priority queue, organization capacity
  budget, provider-pressure controller, or approved abuse policy was found.
- Existing tests prove a blocked request occurs before provider execution and
  credit deduction. Purchasing credits does not reset limiter counters.

## D15 Legacy retirement map

| Legacy item | Replacement | Compatibility window | Sunset condition |
|---|---|---|---|
| `User.credits_remaining` writes | ledger balance projection | Read-only API alias | zero legacy writes and zero drift for observation window |
| `User.credits_reset_at` | period projection from anchor | read alias only | all UI/API consumers use `next_allocation_at` |
| user/org `thinking_power` JSON | credit-period and balance projections | projector may populate | no direct readers/writers remain |
| `bootstrap_legacy_credits` runtime calls | one-time migration opening lots | none after cutover | every account reconciled or quarantined |
| monthly reset user scan | due-period allocator | shadow comparison only | allocator creates all due periods exactly once |
| `PersistentCreditGrant.remaining_amount` | ledger sum by lot | reconciliation column | ledger equals legacy lot for all rows; freeze writes |
| direct admin credit set/adjust | internal funding/adjustment commands | admin UI adapter | actor/reason/source ledger coverage complete |
| `User.subscription_plan/status` authority | entitlement/financial projections | API aliases | access gates read entitlement projection only |
| `Organization.plan_key` sync | organization entitlement projection | read alias | no `sync_org_plan*` callers |
| owner-user Stripe IDs | billing account processor identity | user aliases | all events resolve billing account directly |
| Stripe `scheduled_plan_change` metadata authority | scheduled-change records | mirrored metadata for processor integration | local schedule reconciles to Stripe and owns precedence |
| `StripeWebhookEvent.processed` dispatcher | external event inbox | historical archive | all new event types enter inbox and replay tooling works |
| `Payment` receipts | financial transactions/lines | immutable source archive | totals and external refs reconcile |
| refund/dispute helper reversals | cumulative case state machine | no dual writes | all refund/dispute cases linked and replayable |
| transient `_last_*_credit_debit` | reservation allocation records | none | every release references persisted allocations |
| frontend balance patching | projection refetch or versioned response | response adapter | operation responses carry projection version/reference |
| `founder_*` compatibility aliases | source-neutral entitlement/ledger APIs | existing callers only | no production callers or tests require alias |
| PR #27 code patch | pure-read status/auth plus projector | preserve tests, not patch | target read-purity regressions pass |

Temporary projections are never permitted to become a second write API. If a
consumer cannot migrate inside the compatibility window, cutover pauses; a
permanent synchronization layer is not an option.

## D19 PR #27 supersession analysis

[PR #27](https://github.com/HillsboroLLC/jaspen/pull/27), “Preserve admin credit
usage across status reads,” remains open and unmodified. Its change narrows two
conditions in `routes/auth.py::_enforce_admin_account_profile` and
`routes/billing.py::get_billing_status` so a finite Business balance does not
cause `apply_plan_to_user(... reset_credits=True)` on every authentication or
status read. It also stops forcing displayed admin usage to zero and adds
regressions for preserved shared-pool usage.

That is correct regression intent but a symptom patch because:

1. both read paths still call legacy bootstrap/provisioning functions;
2. `get_usage_meter_state` still invokes mutating pool resolvers;
3. the same balance remains duplicated across user, user JSON, org JSON, and
   persistent grants;
4. admin capability, plan, and funding remain coupled;
5. non-admin authentication and AI routes still bootstrap on reads;
6. the patch does not establish an authoritative ledger or migration path.

Phase 2 should preserve these PR #27 assertions as architecture-level tests:

- repeated billing-status reads do not change any authoritative row;
- repeated authentication/profile reads do not change any authoritative row;
- usage is not hidden for internal/admin accounts;
- internal access is provisioned by an explicit command, not inferred during a
  read.

PR #27 must not be merged, closed, or edited during Phase 1. Once the target
architecture implements equivalent or stronger tests, the user can decide how
to supersede it.

## D20 Newly discovered conflicts and stop register

All 25 business policies are approved. “Architecture documented” below is not
an implementation, test, or cutover claim. Evidence status uses `verified` for
code inspected in this review, `partial` where useful behavior exists but not
the target authority, and `absent` where the target primitive was not found.
No genuine founder decision remains for these items; implementation choices,
notification copy, numeric capacity thresholds, and terminal dunning timing are
later product/engineering approvals, not reopened policy questions.

| ID | Original problem / root cause | Approved policy and architectural resolution | Existing implementation evidence | Remaining work and required tests | Dependencies | Decision remains? |
|---|---|---|---|---|---|---|
| STOP-01 | Reads allocate/reset/sync through pool resolvers, auth, status, AI bootstrap, and org resolution. | Reads are pure; onboarding, allocation, and projection are explicit commands/services. | **Verified conflict**; PR #27 covers only part. | Remove runtime bootstrap; T-READ repeat/auth/status/preflight/org no-write tests. | Schema, commands, projections. | No. |
| STOP-02 | User counter, user JSON, org JSON, and grant counter can diverge. | Append-only ledger is sole authority; all balances rebuildable. | **Verified conflict**; persistent transaction log is partial. | Add lots/entries/projector; conservation, replay, concurrent-spend tests. | Ledger primitives. | No. |
| STOP-03 | Soft grace can make recurring balance negative. | Hard zero; reserve enough before work; fail/release without debit. | **Verified conflict** (`SOFT_STOP_GRACE_MULTIPLIER`). | Atomic reservations; zero-floor/concurrency/insufficient-funds tests. | STOP-02, AI operations. | No. |
| STOP-04 | Dunning caps funded credits and can remove paid capabilities. | Preserve funded benefits/credits; withhold only future unfunded allocations. | **Verified conflict** in status/webhook logic. | Separate financial and entitlement periods; failure/later-success tests. | Financial lines, periods. | No; terminal timing still implementation approval. |
| STOP-05 | Free/recurring anchors drift to first read/reset. | Deterministic UTC organization/subscription anniversary; reads never move it. | **Verified conflict** in resolvers/reset timestamp. | Immutable anchors; month-end/leap/late-login tests. | Org billing account, periods. | No. |
| STOP-06 | Annual invoice can trigger full reset instead of monthly funding. | Annual payment, monthly anchored non-rollover allocations. | **Verified conflict**; interval capture exists. | Annual schedule/period allocator; duplicate webhook and 12-boundary tests. | STOP-05, financial evidence. | No. |
| STOP-07 | Upgrade changes plan without authoritative prorated lot. | Successful payment gate; UTC integer proration; Free-to-paid full period; preserve purchases. | **Verified conflict**; checkout/webhook idempotency patterns are partial. | Funded upgrade command; failed/race/rounding/proration tests. | Financial lines, periods, registry. | No. |
| STOP-08 | Downgrade schedule lives in mutable Stripe metadata; price timing can diverge. | Local audited schedule owns target/effective rule; price and tier change together after renewal payment. | **Verified conflict**; Stripe metadata integration is reusable only as mirror. | Schedule state machine; browse/no-op, supersede, failure, cancellation tests. | Entitlements, inbox. | No. |
| STOP-09 | Refund/dispute handling is non-cumulative; dispute open reverses irreversibly. | Cumulative source-specific open/pending hold, won release, lost reversal, recovery. | **Verified conflict**; source-specific grant records are partial. | Case authority; duplicate/out-of-order/won/lost/reopen tests. | Financial lines, ledger. | No. |
| STOP-10 | Partial refund can reverse all unused lot value. | Proportional cumulative refundable principal excluding tax/fee; no negative. | **Verified conflict** in reversal helpers. | Ratio/delta command; partial/cumulative/bonus/consumed tests. | STOP-09, line attribution. | No. |
| STOP-11 | `Payment` represents positive receipts, not full money lifecycle. | Immutable transactions and lines for payment/refund/dispute/recovery/mixed invoices. | **Verified conflict**; receipt idempotency is partial. | Add authority/backfill; exact minor-unit/mixed-line tests. | Inbox/schema. | No. |
| STOP-12 | Admin set/adjust directly edits plan/counter. | Permissioned adjustment/funding commands append entries with actor, reason, evidence. | **Verified conflict**; audit helpers partial. | Remove direct writes; allow/deny/source/replay tests. | Ledger, admin permissions. | No. |
| STOP-13 | Admin access impersonates Business and resets funding on reads. | Admin authority, capability, data access, and funding are independent. | **Verified conflict**; PR #27 regression intent partial. | Internal entitlement/funding commands; pure-read and visibility tests. | STOP-01/02/12. | No. |
| STOP-14 | Payer/credits inferred from owner user and active org; prior draft proposed personal vs org billing. | **Every customer is an organization** with explicit billing account; billing roles separate membership; active selection irrelevant. | **Verified conflict** in user Stripe IDs, org sync/pools. | Org-first onboarding/backfill/role checks; single-member, multi-member, org-switch isolation tests. | Org identity, migration. | No. |
| STOP-15 | Enterprise is a nullable-credit label without executed-contract authority. | Same org foundation; executed contract versions pricing, term, credits, seats, exceptions; never assume unlimited. | **Verified conflict**; catalog sales-only marker partial. | Contract authority/migration quarantine; evidence/term/funding tests. | STOP-14, entitlements. | No. |
| STOP-16 | Seat policy, commitment, occupancy, and overrides overlap. | Separate paid commitment from occupancy; block incompatible reduction; preserve members/work. | **Verified conflict**; seat purchase/usage tests partial. | Commitment state machine; occupancy/failure/schedule/contract tests. | Financial + entitlements. | No. |
| STOP-17 | Webhook event dedupe lacks object ordering/cumulative semantics. | Durable inbox, digest integrity, object/effective ordering, cumulative recomputation. | **Verified conflict**; event-ID/purchase claims partial. | Dispatcher/replay; duplicate/cross-type/out-of-order/concurrent tests. | Registry, financial authority. | No. |
| STOP-18 | AI releases rely on transient ORM source attributes and combined counter. | Persist per-lot reservation allocations; exact settle/release; delivered response charged once; absorbed-usage evidence; checkpoint/resume. | **Verified conflict**; governed operation/idempotency/attempt telemetry is strong partial. | Bind ledger entries/pricing/capacity; retry/fallback/tool/persistence/concurrency tests. | STOP-02/03, pricing/capacity. | No. |
| STOP-19 | Receipt email is inline; no durable post-commit outbox. | Domain-event outbox is idempotent/retryable/audited and never reverses business success. | **Verified conflict**; test proves failed send does not reverse one offer. | General outbox worker; delivery/retry/dedupe tests for required events. | Domain events. | No. |
| STOP-20 | Compatibility aliases and frontend balance patches can hide drift. | Versioned pure projections with explicit retirement; BALANCE reads ledger projection. | **Verified conflict** in status aliases/`JaspenChat`. | Projector versions/consumer migration; parity/staleness/retirement tests. | STOP-02, reader cutover. | No. |
| STOP-21 | Recurring JSON value and persistent grants cannot share expiry ordering. | All sources are lots; earliest expiry first, deterministic tie rules, purchases protected. | **Verified conflict**; monthly-before-founder test preserves intent. | Unified allocation engine; expiry/hold/tie/source tests. | Ledger/periods. | No. |
| STOP-22 | Legacy offer labels do not form a general source taxonomy. | Subscription, purchase, promo, trial, internal, legitimate legacy sources; unattributed only with evidence. | **Verified conflict**; offer/grant source records partial. | Versioned sources/offers/backfill review; source-isolation/migration tests. | Ledger/migration. | No. |
| STOP-23 | No separate risk-restriction authority; billing status doubles as restriction. | Scoped, permissioned, evidenced, reviewable restrictions independent of funding/data/admin. | **Absent** as target authority. | Add records/permissions/release; scope/authority/review/no-credit-impact tests. | Entitlements/admin. | No; numeric triggers later. |
| STOP-24 | Upgrade/downgrade/cancel/seat commands lack one precedence owner. | Audited schedule state machine with cancellation > paid upgrade > confirmed supersede > existing schedule. | **Verified conflict** across endpoints/webhooks. | Central command/state machine; race/precedence/history tests. | STOP-08/16/17. | No. |
| STOP-25 | Choosing Free can immediately rewrite paid plan/credits and clear subscription ID. | Paid-to-Free is a scheduled/cancellation transition preserving funded term and work. | **Verified conflict** in checkout Free branch. | Route through schedule authority; term/funding/data-preservation tests. | STOP-04/08/24. | No. |

Status summary: all 25 are **founder-approved business policy** and
**founder-approved architecture** as of 2026-11-09. Existing implementation is
partial or conflicting for every
item; none is cutover-authorized. Test execution status for this reconciliation
is recorded in the supporting verification report and must not be inferred
from test-file existence.
