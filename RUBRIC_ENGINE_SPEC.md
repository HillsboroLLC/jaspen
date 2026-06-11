# Spec: User-Defined Deterministic Rubric Scoring

**Goal:** Let an org bring its own scoring criteria + weights, and have Jaspen score each
idea **deterministically** against *that* rubric (not Jaspen's fixed 6 dimensions). The
overall score must be the transparent weighted sum of the user's criteria. The AI's only
job is to judge each criterion's 0–100 sub-score with a confidence; Python does the rollup.

**Key insight (do not rebuild this):** The deterministic rollup ALREADY EXISTS in
`backend/app/routes/strategy.py::_recompute_jaspen_score` (line 2019). It iterates whatever
`weights` map it is handed and reads `dimensions[key].score`, applies confidence caps, and
computes the weighted average + category. It is already generic over arbitrary dimension
keys. We only need to feed it a **user-defined** dimension set + weights instead of the
hardcoded presets, and render the result.

**Hard requirement: full backward compatibility.** If a thread has no rubric, EVERY code
path must behave exactly as it does today (the fixed 6-dimension scorecard).

---

## 1. Data model — the rubric

Stored on the per-thread session object (same store as scorecards:
`load_user_sessions` / `_resolve_user_session` in `strategy.py` / `ai_agent.py`).

```json
"scoring_rubric": {
  "criteria": [
    {
      "key": "technical_energy_talent",   // slug: lowercase, [a-z0-9_], unique
      "label": "Technical & Energy Talent",
      "weight": 0.18,                       // float 0..1, all weights sum to ~1.0
      "is_risk": false,                     // true => "higher score = lower risk" (display only)
      "description": "Depth of battery/grid/energy engineering talent in the metro."
    }
    // ... 2..12 criteria
  ],
  "source": "user",
  "created_at": "2026-06-02T20:00:00Z"
}
```

Rules:
- 2 ≤ criteria ≤ 12.
- Weights must sum to 1.0 ± 0.02; if off, normalize proportionally (`w_i / Σw`) and keep going.
- `key` = slugify(label); on collision append `_2`, `_3`, …
- Every criterion sub-score is **0–100 where 100 = best for that criterion**. For
  cost-type criteria (e.g. "Cost of Operations") this means 100 = most cost-favorable.
  This convention MUST be stated in the scoring prompt so the model is consistent.

---

## 2. Backend — `backend/app/routes/strategy.py`

### 2a. `_generate_jaspen_scorecard(...)` (line 2079) — add `rubric=None`

New signature:
```python
def _generate_jaspen_scorecard(client, project_description, llm_model, *,
                               model_selection=None, strategy_objective='balanced',
                               rubric=None):
```

Inside, branch on `rubric`:

**If `rubric` is a valid dict with ≥2 criteria → CUSTOM MODE:**
- `criteria = rubric["criteria"]`
- `weights = {c["key"]: float(c["weight"]) for c in criteria}` (renormalize if Σ ≠ 1.0).
- Build the `"dimensions"` block of the JSON template **dynamically**, one entry per
  criterion keyed by `c["key"]`, each with the SAME shape already used today:
  `score (0-100), confidence, source, rationale, what_would_improve`.
- In the prompt, list each criterion as `label (weight%) — description` so the model
  knows what it's judging. Replace the existing `weights_note` line with this list.
- Replace the EBITDA/commercialization framing ("Focus on: 1. EBITDA protection…",
  lines 2286–2295) with rubric-neutral guidance: "Score each criterion on its own merits
  using only evidence about THIS option. 100 = best possible on that criterion."
- Keep the confidence-cap rules (lines 2139–2144) verbatim — they apply generically.
- Drop the requirement to emit `component_scores`, `financial_impact`, NPV/IRR, valuation
  etc. in custom mode (make them optional/null). They are commercialization-specific and
  meaningless for a generic rubric. The normalizer already tolerates them being absent
  (it fills component_scores with 0). Leave the financial JSON keys in the template as
  "null unless the criteria call for it" so nothing downstream breaks.
- **Attach the rubric + labels to the returned payload** so the frontend can render
  without a hardcoded map:
  - `parsed["rubric"] = rubric`
  - For each `dimensions[key]`, set `dimensions[key]["label"] = <criterion label>` and
    `dimensions[key]["is_risk"] = <criterion is_risk>`.
- Call `_recompute_jaspen_score(parsed, weights)` exactly as today (line 2330). No change
  to that function — it already handles arbitrary keys.

**If `rubric` is None/invalid → DEFAULT MODE:** unchanged. Existing 6-dimension path runs
verbatim.

### 2b. `_recompute_jaspen_score` (line 2019) — NO CHANGE.
Confirm only: it iterates `(weights or {}).items()` and `dims.get(dim_key)`, so custom keys
work. The `component_scores` mirror block (lines 2069–2074) is a no-op when those keys are
absent — leave it.

### 2c. `_normalize_scorecard_payload` (line 805) — preserve new fields.
It does `normalized = dict(source)` so `rubric` and per-dimension `label`/`is_risk` already
survive. Add nothing unless a deep-copy strips them — verify `dimensions` passes through
untouched (it currently does; the function never rewrites `dimensions`).

---

## 3. Backend — `backend/app/routes/ai_agent.py`

### 3a. New tool: `set_scoring_rubric`
Add to the tool schema list (near `generate_scorecard`, line ~4759):
```json
{
  "name": "set_scoring_rubric",
  "description": "Store the user's custom scoring rubric (criteria + weights) for this thread. Call this BEFORE scoring when the user provides their own criteria and weights. Scores are then computed as the deterministic weighted sum of these criteria.",
  "input_schema": {
    "type": "object",
    "properties": {
      "criteria": {
        "type": "array",
        "items": {
          "type": "object",
          "properties": {
            "label": {"type": "string"},
            "weight": {"type": "number", "description": "0..1 or 0..100; will be normalized"},
            "description": {"type": "string"},
            "is_risk": {"type": "boolean"}
          },
          "required": ["label", "weight"]
        }
      }
    },
    "required": ["criteria"]
  }
}
```

### 3b. Register it as a mutation tool BUT exempt from the caps.
- Add `"set_scoring_rubric"` to the mutation-tool set (`_MUTATION_TOOLS` / `_is_mutation_tool`, line ~407) so it routes through `_execute_mutation_tool`.
- In `_guard_mutation_tool` (line 2819): **return `None` immediately for `set_scoring_rubric`** — it is reversible config, so allow it on the first turn and do NOT count it toward `MAX_MUTATIONS_PER_TURN`.
- In `_execute_local_tool` (line 3911): do NOT increment `next_count` for `set_scoring_rubric`.

### 3c. Implement it in `_execute_mutation_tool` (line 5087).
```python
if tool_name == "set_scoring_rubric":
    raw = tool_input.get("criteria")
    if not isinstance(raw, list) or len(raw) < 2:
        return _tool_error("Provide at least 2 criteria.", code="invalid_rubric")
    criteria = []
    used_keys = set()
    for c in raw:
        label = str(c.get("label") or "").strip()
        if not label:
            continue
        key = _slugify(label)              # add helper: lowercase, [a-z0-9_], collapse repeats
        while key in used_keys:
            key = f"{key}_2"
        used_keys.add(key)
        try:
            w = float(c.get("weight"))
        except (TypeError, ValueError):
            w = 0.0
        criteria.append({
            "key": key, "label": label, "weight": w,
            "is_risk": bool(c.get("is_risk")),
            "description": str(c.get("description") or "").strip() or None,
        })
    total = sum(c["weight"] for c in criteria) or 1.0
    # accept weights given as 0..1 or 0..100; normalize to sum 1.0
    for c in criteria:
        c["weight"] = round(c["weight"] / total, 4)
    # load + persist on session
    sessions = load_user_sessions(user_id) or {}
    session_key, session = _resolve_user_session(sessions, thread_id)
    session["scoring_rubric"] = {
        "criteria": criteria, "source": "user", "created_at": _iso_now(),
    }
    save_user_sessions(user_id, sessions)   # use whatever the existing persist call is
    summary = ", ".join(f'{c["label"]} {int(round(c["weight"]*100))}%' for c in criteria)
    return {"ok": True, "confirmation": f"Scoring rubric saved: {summary}."}
```

### 3d. Wire rubric into `generate_scorecard` (in `_execute_mutation_tool`, line 5121 branch).
After resolving `session` (line ~5128), read the rubric and pass it down:
```python
rubric = session.get("scoring_rubric") if isinstance(session, dict) else None
scorecard_payload = _generate_jaspen_scorecard(
    client, idea_description, llm_model=model_selection["llm_model"],
    model_selection=model_selection, strategy_objective=strategy_objective,
    rubric=rubric,
)
```

### 3e. System prompt (the big instruction string ending line ~535).
Add: "If the user supplies their own scoring criteria and weights, FIRST call
`set_scoring_rubric` with those criteria, confirm the saved rubric back to them in plain
language, and explain that each option's score will be the deterministic weighted sum of
those criteria. THEN follow the present-shortlist-before-scoring and batching rules. Never
invent or alter the user's weights." Keep the existing batching + present-first blocks.

---

## 4. Frontend — render dimensions from the payload, not a hardcoded map

Three places hardcode the 6 dimensions. Make each prefer the scorecard's own
`rubric.criteria` (and per-dimension `label`), and fall back to the existing constants when
absent (old scorecards / default mode).

### 4a. `src/jaspenInterface/Workspace/JaspenWorkspace.jsx` — `DimensionBars` (line 1804)
- Already renders unknown keys (lines 1811–1815) and humanizes labels (line 1831). Change
  the label line to prefer the payload label:
  ```js
  const label = dim?.label || _DIMENSION_LABELS[key] || key.replace(/_/g,' ').replace(/\b\w/g,c=>c.toUpperCase());
  ```
- If `scorecard.rubric?.criteria` exists, order bars by that array's order (pass its key
  order in as `dimOrder`). Use `dim.is_risk` to pick the risk color instead of the
  hardcoded `_RISK_DIMENSIONS` set.

### 4b. `src/jaspenInterface/Workspace/JaspenChat.jsx` — inline scorecard dim list (line ~2674)
- Replace the hardcoded array with: if the scorecard has `rubric?.criteria`, map those to
  `{key, label, isRisk}`; else use the existing hardcoded 6.

### 4c. `src/jaspenInterface/Workspace/TradeoffView.jsx` — columns + quadrant (line 18, 254, 565)
- Derive the comparison columns from the union of dimension keys present across the scored
  ideas (prefer the rubric order/labels); fall back to the hardcoded `DIMS` array.
- Quadrant axes (`xDim`/`yDim`, currently fixed to Cost vs Strategic): when a rubric is
  present, default the two axes to the **two highest-weighted criteria**; keep the labels
  dynamic (`xLabel`/`yLabel` from those criteria). Fall back to current behavior otherwise.

---

## 5. Acceptance tests

1. **Rubric save:** Send the 10 GridPoint criteria+weights → `set_scoring_rubric` stores
   them, weights normalized to sum 1.0, agent confirms in plain language. No scorecard yet.
2. **Custom score:** `generate_scorecard` for "Austin, TX" → returned payload's
   `dimensions` has the 10 rubric keys (NOT market_opportunity/etc.), each with a `label`,
   `jaspen_score` equals the weighted sum of the 10 capped sub-scores, and `rubric` is
   attached. Verify by hand: `Σ(score_i × weight_i)` == `jaspen_score`.
3. **Determinism:** Re-score the same idea with the same rubric → identical `jaspen_score`
   and identical per-dimension scores (temperature is already 0).
4. **Frontend render:** Workspace scorecard shows 10 labeled bars; inline chat scorecard
   shows the 10; trade-off table shows 10 columns and ranks by weighted score; quadrant
   axes default to the two highest-weighted criteria.
5. **Backward compat:** A thread with NO rubric → identical to today (6 fixed dimensions,
   objective preset weights, all financial blocks populated).

---

## 6. Out of scope for tonight (note for later)
- A rubric editor UI (this build captures the rubric purely via the agent/chat).
- Per-org saved rubric templates / reuse across threads.
- User-entered (non-AI) per-criterion sub-scores. (Engine already supports it — dimensions
  are manual-or-AI editable per strategy.py:7000 — but no UI to type them yet.)
- The separate batching-reliability bug (malformed first `generate_scorecard` call wastes a
  round; 2nd batch 500s). Track and fix separately; not part of this rubric work.
