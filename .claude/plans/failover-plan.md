# True Provider Failover — Implementation Plan

## Current State (as of `f1ed430`)

### What exists today

**Multi-provider routing** already works. `_ROUTING_MATRIX` (line 132) defines ordered `(provider, model_key)` tuples per tier+objective. `_resolve_generation_routes()` (line 1358) resolves these to concrete `{provider, model_key, model}` dicts, skipping any provider whose API key is missing.

**Two orchestration functions** already loop through routes:

- `_generate_assistant_reply()` (line 3047) — non-streaming. Iterates `routes`, tries Gemini via `_generate_assistant_reply_gemini()`, catches exceptions and `continue`s, falls through to Anthropic via `_generate_assistant_reply_anthropic()`. If all routes fail, falls back to a hardcoded Anthropic call (line 3125).

- `_stream_assistant_reply_events()` (line 3141) — streaming. Same loop, but for Gemini streaming it tracks `yielded_any`. If the Gemini stream fails **after** yielding content, it does NOT fail over (correct — partial content was already sent). If it fails before any content, it `continue`s to the next route.

**Within** each provider, Anthropic has its own model-level fallback chain: `_anthropic_model_candidates()` (line 1314) tries the requested model, then env-configured models, then hardcoded fallbacks. Gemini has no equivalent — it's one model per call, fail or succeed.

### What's missing for true failover

| Gap | Impact |
|-----|--------|
| Anthropic routes don't `continue` on failure — they're the `else` case after the Gemini `if`, so Anthropic failure = total failure | If Anthropic is down but Gemini is available, no automatic failover |
| No classification of retryable vs terminal errors | Auth misconfigs, validation errors, and policy refusals are retried just like 5xx/timeout |
| No timeout on `_gemini_openai_request` read phase (connect=20s, read=240s) | A hung Gemini stream can block for 4 minutes before failover |
| No telemetry on failover events | No visibility into provider health, failover frequency, or failure modes |
| `_record_usage` overwrites `provider`/`model` each event — no failover chain recorded | Can't distinguish primary success from fallback success |
| No mutation-safety gate on cross-provider failover | If Anthropic fails mid-tool-loop (after mutations applied), falling to Gemini could replay mutations |
| Streaming Anthropic path has no `yielded_any` guard (unlike Gemini) | If Anthropic fails after partial stream, there's no check to prevent fallover |

---

## Implementation Plan

### Phase 1: Error Classification Layer

**File:** `backend/app/routes/ai_agent.py`
**Where:** New helper, after `_check_response_for_leak` (~line 858)

Create an error classifier that determines whether a provider failure is retryable (should fail over) or terminal (should surface to user).

```python
_RETRYABLE_HTTP_STATUS_CODES = {408, 429, 500, 502, 503, 504, 529}

def _classify_provider_error(exc):
    """
    Returns a dict:
      retryable: bool — should we try the next provider?
      reason: str — short label for telemetry
      status_code: int|None
    """
```

**Classification rules:**

| Error Type | Retryable? | Reason Label |
|------------|-----------|--------------|
| `requests.exceptions.Timeout` | Yes | `"timeout"` |
| `requests.exceptions.ConnectionError` | Yes | `"connection_error"` |
| `httpx.TimeoutException` (Anthropic SDK) | Yes | `"timeout"` |
| `httpx.ConnectError` | Yes | `"connection_error"` |
| HTTP 5xx from provider | Yes | `"server_error"` |
| HTTP 429 from provider | Yes | `"rate_limited"` |
| HTTP 529 (Anthropic overloaded) | Yes | `"overloaded"` |
| `anthropic.APIStatusError` with status in retryable set | Yes | `"api_status_{code}"` |
| HTTP 401/403 from provider | **No** | `"auth_error"` |
| HTTP 400 (bad request — our fault) | **No** | `"bad_request"` |
| `anthropic.AuthenticationError` | **No** | `"auth_error"` |
| `anthropic.BadRequestError` | **No** | `"bad_request"` |
| `RuntimeError("...API_KEY not configured")` | **No** | `"config_missing"` |
| Content policy refusal (stop_reason = "end_turn" with refusal text, or Gemini `finish_reason: "SAFETY"`) | **No** | `"content_refused"` |
| Empty/invalid response that doesn't match any above | Yes | `"invalid_response"` |

**Implementation detail:** Extract status code from:
- `anthropic.APIStatusError` → `exc.status_code`
- `requests.exceptions.HTTPError` → `exc.response.status_code`
- `httpx.HTTPStatusError` → `exc.response.status_code`

Return `{"retryable": bool, "reason": str, "status_code": int|None}`.

---

### Phase 2: Failover Telemetry Record

**File:** `backend/app/routes/ai_agent.py`
**Where:** New helper, near `_record_usage` (~line 3243)

#### 2a. Add failover metadata to the return value

Both `_generate_assistant_reply` and `_stream_assistant_reply_events` currently return usage dicts with `provider` and `model`. Extend this to include failover information.

Add a new key to the usage dict returned by all generation functions:

```python
usage["failover"] = {
    "attempted_providers": [
        {"provider": "gemini", "model": "gemini-2.5-flash", "outcome": "timeout", "duration_ms": 20400},
    ],
    "final_provider": "anthropic",
    "final_model": "claude-sonnet-4-20250514",
    "failover_count": 1,
}
```

This travels through the existing pipeline — it's just extra keys in the `usage` dict. `_record_usage` already stores the full usage dict in `usage_events`, so failover telemetry is automatically persisted.

#### 2b. Update `_record_usage` to preserve failover data

**Line:** 3277 (the `events.append(...)` block)

Add to the event dict:
```python
"failover": usage.get("failover"),
```

No other changes needed — the `usage_summary` overwrites `provider`/`model` which is correct (it shows the final provider that served the turn).

#### 2c. Admin visibility

The existing admin/feedback insights endpoint can be extended later to aggregate `failover` data from `usage_events`. This is not in scope for Phase 1 — the data just needs to be recorded now.

---

### Phase 3: Restructure the Orchestration Loop

This is the core change. The current orchestration has an asymmetry: Gemini routes are tried-and-caught, but Anthropic routes fall through without try/catch. This needs to become a uniform loop where **every** provider route gets the same treatment.

#### 3a. `_generate_assistant_reply` (line 3047)

**Current structure:**
```python
for route in routes:
    if route["provider"] == "gemini":
        try:
            return _generate_assistant_reply_gemini(...)
        except:
            continue
    return _generate_assistant_reply_anthropic(...)  # ← no try/catch, no continue
# hardcoded Anthropic fallback
```

**New structure:**
```python
def _generate_assistant_reply(...):
    # ... existing setup (attachments check, objective, routes) ...

    failover_log = []
    for route in routes:
        t_start = time.monotonic()
        try:
            if route["provider"] == "gemini":
                result = _generate_assistant_reply_gemini(
                    ..., routed_selection, ...
                )
            else:
                result = _generate_assistant_reply_anthropic(
                    ..., routed_selection, ...
                )

            # Success — attach failover telemetry to usage
            reply, usage, actions, mutations, undo = result
            usage["failover"] = {
                "attempted_providers": failover_log,
                "final_provider": route["provider"],
                "final_model": route["model"],
                "failover_count": len(failover_log),
            }
            if failover_log:
                current_app.logger.info(
                    "ai_agent failover succeeded | user=%s provider=%s model=%s after=%d attempts",
                    user_id, route["provider"], route["model"], len(failover_log),
                )
            return result

        except Exception as exc:
            elapsed_ms = int((time.monotonic() - t_start) * 1000)
            classification = _classify_provider_error(exc)

            failover_log.append({
                "provider": route["provider"],
                "model": route["model"],
                "outcome": classification["reason"],
                "status_code": classification.get("status_code"),
                "duration_ms": elapsed_ms,
            })

            if not classification["retryable"]:
                current_app.logger.warning(
                    "ai_agent non-retryable provider error | provider=%s reason=%s",
                    route["provider"], classification["reason"],
                )
                raise  # Terminal error — surface to caller

            current_app.logger.warning(
                "ai_agent provider failed (retryable) | provider=%s model=%s reason=%s elapsed=%dms, trying next",
                route["provider"], route["model"], classification["reason"], elapsed_ms,
            )
            continue

    # All routes exhausted
    if failover_log:
        current_app.logger.error(
            "ai_agent all provider routes exhausted | attempts=%s",
            json.dumps(failover_log),
        )
    # Fall through to hardcoded Anthropic fallback (existing behavior)
    ...
```

**Key change:** Anthropic failures are now caught, classified, and retried if retryable. Non-retryable errors (auth, bad request, content refusal) still raise immediately.

#### 3b. `_stream_assistant_reply_events` (line 3141)

**Same uniform loop, with streaming-specific guard:**

```python
def _stream_assistant_reply_events(...):
    # ... existing setup (attachments check, objective, routes) ...

    failover_log = []
    for route in routes:
        t_start = time.monotonic()
        yielded_any = False
        try:
            if route["provider"] == "gemini":
                gen = _stream_assistant_reply_events_gemini(
                    ..., routed_selection, ...
                )
            else:
                gen = _stream_assistant_reply_events_anthropic(
                    ..., routed_selection, ...
                )

            for payload in gen:
                yielded_any = True
                yield payload

            # Stream completed successfully — inject failover telemetry into state
            if isinstance(state, dict) and isinstance(state.get("usage"), dict):
                state["usage"]["failover"] = {
                    "attempted_providers": failover_log,
                    "final_provider": route["provider"],
                    "final_model": route["model"],
                    "failover_count": len(failover_log),
                }
            return

        except Exception as exc:
            if yielded_any:
                # Content already sent to client — cannot switch providers mid-stream
                current_app.logger.error(
                    "ai_agent stream failed after partial content | provider=%s — not failing over",
                    route["provider"],
                )
                return  # Client already has partial content

            elapsed_ms = int((time.monotonic() - t_start) * 1000)
            classification = _classify_provider_error(exc)

            failover_log.append({
                "provider": route["provider"],
                "model": route["model"],
                "outcome": classification["reason"],
                "status_code": classification.get("status_code"),
                "duration_ms": elapsed_ms,
            })

            if not classification["retryable"]:
                raise

            current_app.logger.warning(
                "ai_agent stream provider failed (retryable) | provider=%s reason=%s, trying next",
                route["provider"], classification["reason"],
            )
            continue

    # All routes exhausted — fall through to hardcoded Anthropic
    ...
```

**Critical streaming rule:** Once `yielded_any` is `True`, no failover. The client already has partial text — switching providers would produce incoherent output. This guard already exists for Gemini but needs to apply uniformly to all providers.

---

### Phase 4: Mutation Safety Gate

**File:** `backend/app/routes/ai_agent.py`
**Where:** Inside `_generate_assistant_reply_anthropic` (line 2250) and `_generate_assistant_reply_gemini` (line 2685)

The concern: if the model calls mutation tools (create_scenario, update_wbs_task, etc.) and those mutations are **applied**, then the Anthropic call fails on the subsequent "here are your tool results" follow-up message — we must NOT fail over to Gemini and replay the entire conversation, because Gemini would re-execute the mutations.

**Current state:** Both `_generate_assistant_reply_anthropic` and `_generate_assistant_reply_gemini` have internal tool loops (up to 3 iterations). Mutations are executed inside this loop. If the follow-up API call fails, the exception bubbles up to the orchestration loop, which would currently try the next provider — replaying mutations.

**Fix:** Track whether any mutations have been applied in the current call. If they have and the subsequent API call fails, **do not raise** — instead, return the partial result with whatever text was generated before the failure.

In both `_generate_assistant_reply_anthropic` and `_generate_assistant_reply_gemini`, the tool loop already tracks `executed_mutations`. Add a guard:

```python
# Inside the tool loop, after mutations are executed, before the follow-up API call:
mutations_applied = any(m.get("success") for m in executed_mutations)

try:
    response, resolved_model_name = _anthropic_message_create(...)  # or _gemini_openai_request(...)
except Exception as exc:
    if mutations_applied:
        # Mutations were already written — cannot safely retry or fail over
        current_app.logger.error(
            "ai_agent post-mutation API call failed | provider=%s mutations_applied=%d — returning partial result",
            "anthropic", len(executed_mutations),
        )
        # Return what we have — the mutations are real, the text reply is partial
        reply = _anthropic_text(response.content) if response else fallback_reply
        if tool_confirmations:
            confirmations_text = "\n".join(f"- {item}" for item in tool_confirmations)
            reply = f"{reply}\n\nApplied changes:\n{confirmations_text}".strip()
        # ... build and return usage, actions, mutations, undo_snapshot ...
        return reply, usage, executed_actions, executed_mutations, undo_snapshot
    raise  # No mutations applied — safe to fail over
```

**For streaming paths:** Same principle. If mutations have been applied and the follow-up stream fails, yield what we have and return — do not raise for the orchestration loop to catch.

#### Summary of mutation safety rules:

| State | Behavior |
|-------|----------|
| No tool calls attempted yet | Safe to fail over |
| Read-only tools called (get_readiness_snapshot, get_data_contract) | Safe to fail over |
| Mutation tools called but all failed | Safe to fail over |
| Mutation tools called and ≥1 succeeded | **NOT safe to fail over** — return partial result |

---

### Phase 5: Tighten Gemini Timeouts

**File:** `backend/app/routes/ai_agent.py`
**Where:** `_gemini_openai_request` (line 1443)

**Current:** `timeout=(20, 240)` — 20s connect, 240s read.

**Change:** Reduce read timeout for non-streaming to 60s. Keep streaming at a higher value since chunks arrive incrementally.

```python
def _gemini_openai_request(*, model_name, system_prompt, messages, tools, max_tokens, temperature, stream=False):
    read_timeout = 180 if stream else 60
    # ...
    response = requests.post(
        _GEMINI_OPENAI_BASE_URL,
        # ...
        timeout=(15, read_timeout),
        stream=stream,
    )
```

Also add a similar timeout to `_anthropic_message_create` by passing `timeout` to the Anthropic client constructor:

```python
client = anthropic.Anthropic(api_key=api_key, timeout=httpx.Timeout(60.0, connect=15.0))
```

This needs to happen at the client construction site, which is inside each provider-specific function:
- `_generate_assistant_reply_anthropic` line ~2305: `client = anthropic.Anthropic(api_key=api_key)`
- `_stream_assistant_reply_events_anthropic` line ~2505: `client = anthropic.Anthropic(api_key=api_key)`

Change both to:
```python
import httpx
client = anthropic.Anthropic(api_key=api_key, timeout=httpx.Timeout(60.0, connect=15.0))
```

For streaming, keep a longer timeout since tokens arrive incrementally:
```python
client = anthropic.Anthropic(api_key=api_key, timeout=httpx.Timeout(180.0, connect=15.0))
```

---

### Phase 6: Multimodal Failover Constraint

**File:** `backend/app/routes/ai_agent.py`
**Where:** `_generate_assistant_reply` (line 3047) and `_stream_assistant_reply_events` (line 3141)

Both functions already handle `attachments` by routing directly to Anthropic (lines 3066-3080 and 3157-3174). This is correct and should stay.

**Additional guard:** In the orchestration loop, if the turn has attachments and the Anthropic call fails, do NOT fail over to Gemini — Gemini multimodal support is not yet tested.

This is already the case because of the early `if attachments: return anthropic_only(...)` pattern. But add an explicit comment documenting this is intentional:

```python
if attachments:
    # Multimodal turns are Anthropic-only until Gemini multimodal is tested.
    # No cross-provider failover for image/PDF turns.
    return _generate_assistant_reply_anthropic(...)
```

---

### Phase 7: Admin Telemetry Endpoint

**File:** `backend/app/routes/ai_agent.py`
**Where:** After the existing admin/usage endpoints (after `/usage` endpoint)

Add a lightweight endpoint that aggregates failover data from recent sessions:

```
GET /api/v1/ai-agent/admin/provider-health
```

**Response shape:**
```json
{
  "window": "24h",
  "total_turns": 1482,
  "failover_turns": 23,
  "failover_rate": 0.016,
  "by_provider": {
    "anthropic": {"attempts": 1400, "successes": 1388, "failures": 12},
    "gemini": {"attempts": 105, "successes": 94, "failures": 11}
  },
  "failure_reasons": {
    "timeout": 8,
    "rate_limited": 6,
    "server_error": 5,
    "connection_error": 3,
    "overloaded": 1
  }
}
```

**Implementation:** This reads `usage_events` from recent sessions (last 24h window), filters for events with `failover` data, and aggregates. No new database table needed — it reads from the existing session JSON store.

**Access:** Admin-only, gated by the existing `@admin_required` decorator.

---

## Complete File Change Summary

| # | File | What | Lines affected |
|---|------|------|----------------|
| 1 | `ai_agent.py` ~line 858 | New `_classify_provider_error()` helper | ~50 new lines |
| 2 | `ai_agent.py` lines 3047-3138 | Restructure `_generate_assistant_reply` orchestration loop | ~90 lines rewritten |
| 3 | `ai_agent.py` lines 3141-3240 | Restructure `_stream_assistant_reply_events` orchestration loop | ~100 lines rewritten |
| 4 | `ai_agent.py` inside `_generate_assistant_reply_anthropic` tool loop (~2360) | Mutation safety gate on post-mutation API failures | ~20 new lines |
| 5 | `ai_agent.py` inside `_generate_assistant_reply_gemini` tool loop (~2780) | Same mutation safety gate | ~20 new lines |
| 6 | `ai_agent.py` inside `_stream_assistant_reply_events_anthropic` tool loop | Same mutation safety gate for streaming | ~15 new lines |
| 7 | `ai_agent.py` inside `_stream_assistant_reply_events_gemini` tool loop | Same mutation safety gate for streaming | ~15 new lines |
| 8 | `ai_agent.py` line 1443 | Tighten Gemini timeouts | 2 lines changed |
| 9 | `ai_agent.py` lines ~2305, ~2505 | Add explicit Anthropic client timeouts | 4 lines changed |
| 10 | `ai_agent.py` line 3277 | Record failover data in usage events | 1 line added |
| 11 | `ai_agent.py` after usage endpoints | New `/admin/provider-health` endpoint | ~80 new lines |
| 12 | `ai_agent.py` line 1 | Add `import time` | 1 line |
| 13 | `__init__.py` | No changes needed — config is already in place | 0 |
| 14 | `billing_config.py` | No changes needed | 0 |
| 15 | Frontend | No changes — this is a backend reliability pass | 0 |

---

## Rollout Order

| Step | What | Risk | Test |
|------|------|------|------|
| 1 | `_classify_provider_error` + unit tests | None — new code, no callsites yet | Unit test with mocked exceptions |
| 2 | Restructure `_generate_assistant_reply` orchestration | Medium — changes the non-streaming response path | Manual: set `GEMINI_API_KEY` to invalid value, verify Anthropic serves the response; then set `ANTHROPIC_API_KEY` to invalid, verify Gemini serves |
| 3 | Add mutation safety gates | Low — only affects the post-mutation error path | Test: trigger a mutation tool call, then simulate API failure on follow-up — verify mutations persist and partial result is returned |
| 4 | Restructure `_stream_assistant_reply_events` orchestration | Medium — changes the streaming path | Manual: same as step 2 but with `?stream=true` |
| 5 | Tighten timeouts | Low | Verify normal responses still complete within limits |
| 6 | Add failover telemetry to `_record_usage` | None — extra dict key | Verify `usage_events` entries contain `failover` key after a failover event |
| 7 | Add `/admin/provider-health` endpoint | Low — read-only admin endpoint | Manual: call endpoint after generating some traffic |

---

## What This Plan Does NOT Include

- **Gemini multimodal failover** — intentionally excluded per your spec. Multimodal stays Anthropic-only.
- **Client-side failover UI** — no frontend changes. Users see a response or an error, never a "we failed over" indicator.
- **Cross-request retry** — this is per-turn failover only. If a turn fails entirely (all providers down), the user gets an error and must retry manually.
- **Provider circuit breaker** — a future enhancement where after N consecutive failures from a provider, we skip it for a cooldown period. Not needed for v1 but the telemetry data from this plan enables it later.
- **Load balancing / traffic splitting** — this is failover (try primary, fall to secondary), not round-robin distribution.
