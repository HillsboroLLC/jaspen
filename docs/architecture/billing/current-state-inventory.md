# Current Billing State, Retirement, and Conflict Inventory

Inventory base: `88684284a33836106cad639d36e191271109c2c7`.
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
| `test_single_device_and_personal_credits.py` | personal ownership and team-pool separation |
| `test_ai_governance.py` | operation idempotency, validate-before-settle, exact release/reversal, batch allocation |

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

Every item below is a stop condition for the affected Phase 2 area. Phase 1
documents the root cause and approved consolidation; it does not patch it.

| ID | Exact conflict/root cause | Affected code | Required consolidation before implementation |
|---|---|---|---|
| STOP-01 | Reads allocate/reset/synchronize billing state | billing pool resolvers, status, auth, AI/strategy bootstrap, org resolution | separate explicit commands from pure projections; remove runtime bootstrap |
| STOP-02 | Four balance authorities can diverge | user counter, user JSON, org JSON, persistent grant counter | one append-only ledger plus rebuildable projections |
| STOP-03 | Soft-stop grace permits negative recurring balance | `SOFT_STOP_GRACE_MULTIPLIER`, `consume_credits` | hard zero floor; insufficient reservation fails without debit |
| STOP-04 | Dunning removes paid capabilities and caps funded credits | `RESTRICTED_SUBSCRIPTION_STATUSES`, `effective_plan_key`, invoice-failed webhook | preserve effective entitlement/lot periods; withhold only unfunded future allocations |
| STOP-05 | Free and recurring anchors drift to first read/reset time | pool resolvers and `credits_reset_at` | immutable account/subscription UTC anchor and deterministic periods |
| STOP-06 | Annual payment currently maps to invoice-time full reset, not monthly allocations | invoice success handler and reset helper | annual funding schedule with monthly anchored lots |
| STOP-07 | Paid upgrade changes plan without authoritative prorated funded lot | `modify_subscription(... reset_credits=False)` | payment-confirmed, integer-floored UTC proration entry; Free-to-paid full period |
| STOP-08 | Schedule lives in mutable Stripe metadata and price is changed before effective downgrade | modify/status/webhook/clear routes | local audited scheduled-change owner and deterministic precedence |
| STOP-09 | Refund/dispute authority is non-cumulative and irreversible on dispute open | `charge.refunded`, `charge.dispute.created`, reverse helpers | cumulative financial lines plus opened/pending/won/lost hold/release/reverse/recovery machine |
| STOP-10 | Partial refunds reverse all unused lot value | persistent and 300K reversal helpers | proportional cumulative principal ratio excluding tax/fee |
| STOP-11 | Payment table cannot represent refund, dispute, recovery, or mixed lines | `Payment`, `_record_payment` | financial transaction and line authority |
| STOP-12 | Admin direct set/adjust bypasses source ownership and ledger | admin credit/plan/recovery routes | explicit internal funding/adjustment commands with actor/evidence |
| STOP-13 | Internal admin access is implemented by impersonating Business and resetting funding | auth/status admin enforcement | separate admin authority, capability, data access, and internal funding |
| STOP-14 | Organization payer is inferred from owner user and active context | user Stripe IDs, org plan sync, active org pool | explicit billing account owned by user or organization |
| STOP-15 | Enterprise is a nullable-credit sales plan without executed-contract authority | `enterprise_custom`, sales-only checks | organization-owned executed contract and evidence-backed migration |
| STOP-16 | Seat commitment, occupancy, and plan policy overlap; no reduction state machine | org max fields, seat endpoint, team membership | independent commitment records and blocked reduction workflow |
| STOP-17 | Event dedupe lacks object ordering/cumulative version semantics | `StripeWebhookEvent` and webhook dispatcher | inbox with payload digest, object/effective ordering, cumulative recomputation |
| STOP-18 | AI release relies on transient ORM attributes and a combined counter | consume/release helpers, AI reservation functions | persisted reservation allocations and exact entry-linked release/settlement |
| STOP-19 | Inline receipt email has no durable outbox; send behavior is coupled to fulfillment flow | limited-time email helpers | post-commit domain event and idempotent outbox delivery |
| STOP-20 | Compatibility aliases and frontend local balance patches can hide drift | founder aliases, status aliases, `JaspenChat` balance patching | versioned projections with explicit sunset conditions |
| STOP-21 | Consumption ordering cannot compare expiry because recurring value is not represented as lots | recurring JSON meters versus persistent grants | all funding represented as source-specific lots; expiration-first ordering |
| STOP-22 | Current source labels include legacy offer names and no general trial/promo/internal taxonomy | founder/300K aliases and grant sources | approved source taxonomy; evidence-backed `legacy_unattributed` only when necessary |
| STOP-23 | No risk-restriction authority exists; billing status is used as an implicit restriction | entitlement and collaboration gates | permissioned scoped restriction records with evidence/review/release |
| STOP-24 | Cancellation, upgrade, downgrade, and seat changes lack one shared precedence authority | several Stripe mutation endpoints and webhook | entitlement schedule state machines in the lifecycle specification |
| STOP-25 | Requesting Free through checkout immediately rewrites plan/credits and clears the local subscription ID instead of scheduling/cancelling the paid term | `create_checkout_session` Free branch | route Free transitions through the cancellation/scheduled-change authority |

Recommended action: approve ADR-0001 and these consolidation boundaries before
authorizing Phase 2. Do not implement any STOP item as a local fix or permanent
compatibility layer.
