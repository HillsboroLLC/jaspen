# Business and Enterprise pricing cost audit

Status: implementation audit for owner review before production. No live Stripe changes were made.

## Business configuration

- Public name: Business.
- Canonical self-service plan key: `business`. Legacy `enterprise` metadata is accepted as an alias and migrated to `business`; custom sales-led accounts use `enterprise_custom`.
- Price shown: $299 monthly or $249 per month billed as one $2,988 annual payment.
- Seats: five included, one workspace, maximum 10 total paid users.
- Additional seats: UI and entitlement limit are prepared, but checkout is disabled until `PRICE_ID_BUSINESS_ADDITIONAL_SEAT` is supplied and its price is confirmed.
- Included customer-facing credits: 80,000 shared per billing cycle.

## Credit and provider conversion

- `TOKENS_PER_CREDIT = 1000` in `backend/app/billing_config.py`.
- The Business catalog stores `80_000_000` internal tokens and the public API converts that to 80,000 customer-facing credits.
- Therefore, the current maximum allowance represents 80 million internal/provider-token units. This is material cost exposure and should be reviewed before increasing usage for extra seats.

## Model cost assumptions currently encoded

- Claude Haiku 4.5: $1 per million input tokens and $5 per million output tokens.
- Claude Sonnet 4.x: $3 input and $15 output per million tokens.
- Claude Opus current entries: $5 input and $25 output per million tokens; older Opus entries remain at $15/$75.
- Unknown Claude models fall back to Sonnet rates.
- The usage model applies a 3x margin multiplier.
- The Business plan has a $100 monthly pre-margin Anthropic-cost budget, which maps to approximately $300 of metered retail consumption at the default multiplier.
- Gemini and other non-Claude calls return a zero debit in the current usage meter. That is an accounting assumption, not evidence that backup-model or infrastructure cost is literally zero.

## Items not established by the code

The repository does not provide a validated expected input/output token mix, observed utilization distribution, tool/search/storage/infrastructure cost allocation, or a confirmed additional-seat Stripe price. Because these inputs are missing, reliable expected-use, worst-case, and add-on-seat gross-margin percentages cannot be claimed yet.

At $299 monthly, the encoded $100 maximum monthly Claude-cost budget leaves $199 before payment processing, Gemini, tools, search, storage, support, and infrastructure. At $2,988 annually, twelve months at that maximum Claude budget would leave $1,788 before those other costs. These are ceilings from the usage model, not forecast margins.

Top-up prices cannot be certified for margin from catalog values alone because the actual model mix and output ratio are unknown. No additional usage is granted for extra Business seats in this implementation.

## Production decisions still required

1. Confirm whether the existing $299 Stripe product will simply be renamed to Business while retaining its current price IDs.
2. Supply or confirm Business monthly and annual price IDs.
3. Supply the additional-seat monthly/annual IDs and price before enabling add-on checkout.
4. Review actual production utilization and model mix before increasing the 80,000-credit pool.
5. Keep manually provisioned custom Enterprise accounts on `enterprise_custom`; the former self-service `enterprise` key migrates to the first-class `business` value.
