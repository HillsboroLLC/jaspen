# Codex brief — agent can't fill/update a custom block the user created

## Symptom
User adds a custom block on the scorecard (e.g. a "MITIGATION" block, body =
"checking"), then asks the agent to populate it. The agent replies "Done… updated
top_risks on this scorecard" and the MITIGATION block stays as "checking." The
agent never writes into the user's block.

## Root cause (confirmed, read-only trace)
`patch_scorecard`'s block path is **append-only**. In
`backend/app/routes/ai_agent.py`:
- Building blocks (lines ~6114–6135): every incoming block is given a brand-new id
  `f"blk_{uuid.uuid4().hex[:10]}"` — an incoming `id`/heading is never used to
  target an existing block.
- Merge (lines ~6190–6199): `existing_blocks.extend(new_blocks)` — always appends.

So the agent has **no way to update an existing custom block**. Asked to fill the
user's "MITIGATION" block, its only real choices are:
  (a) `add_blocks` → creates a SECOND "Mitigation" block (a duplicate), or
  (b) route the text into a standard patchable field (`top_risks`, etc.).
It picked (b), hence "updated top_risks" while the user's block is untouched.

(The frontend stores user-created blocks in `display_overrides.custom_blocks` as
`{id, heading, body}` with `id = blk_<timestamp>`; see JaspenWorkspace.jsx. The
agent doesn't know that id, so the fix must match by **heading**.)

## The fix — make `add_blocks` an UPSERT (match by heading), + tell the agent

### 1) Backend handler — upsert instead of append-only
In `ai_agent.py`, the `patch_scorecard` handler.

a) When building `new_blocks` (~6120–6135), preserve an incoming id and DON'T mint
a uuid if one is supplied:
```python
        if isinstance(raw_blocks, list):
            for b in raw_blocks:
                if isinstance(b, str):
                    b = {"body": b}
                if not isinstance(b, dict):
                    continue
                heading = str(b.get("heading") or b.get("title") or b.get("label") or "").strip()[:160]
                body = str(b.get("body") or b.get("text") or b.get("content") or "").strip()
                if not heading and not body:
                    continue
                new_blocks.append({
                    "id": str(b.get("id") or "").strip() or f"blk_{uuid.uuid4().hex[:10]}",
                    "heading": heading or "New section",
                    "body": body,
                })
```

b) In the merge step (~6190–6199), upsert each block: if its `id` matches, or its
heading matches an existing block (case-insensitive, trimmed), UPDATE that entry
in place; else append:
```python
            if new_blocks:
                _ovb = merged.get("display_overrides")
                _ovb = dict(_ovb) if isinstance(_ovb, dict) else {}
                existing_blocks = _ovb.get("custom_blocks")
                existing_blocks = list(existing_blocks) if isinstance(existing_blocks, list) else []

                def _norm(h):
                    return str(h or "").strip().casefold()

                for nb in new_blocks:
                    match_idx = None
                    for i, eb in enumerate(existing_blocks):
                        if not isinstance(eb, dict):
                            continue
                        same_id = nb.get("id") and str(eb.get("id")) == str(nb.get("id"))
                        same_heading = nb.get("heading") and _norm(eb.get("heading")) == _norm(nb.get("heading"))
                        if same_id or same_heading:
                            match_idx = i
                            break
                    if match_idx is not None:
                        updated = dict(existing_blocks[match_idx])
                        updated["heading"] = nb.get("heading") or updated.get("heading")
                        if nb.get("body"):
                            updated["body"] = nb["body"]          # replace body
                        existing_blocks[match_idx] = updated
                    else:
                        existing_blocks.append(nb)

                _ovb["custom_blocks"] = existing_blocks
                merged["display_overrides"] = _ovb
```
Notes:
- Matching by heading is the key — the agent fills the user's "MITIGATION" block by
  passing `add_blocks: [{heading: "Mitigation", body: "..."}]`. Case-insensitive so
  "MITIGATION" (CSS-uppercased in the UI) matches the stored "Mitigation".
- Default is REPLACE body. If you want append-to-existing semantics, support an
  optional `mode: "append"` on the block and concatenate instead.

### 2) Tool schema — allow an optional id (so re-fills are precise)
In the `patch_scorecard` tool definition (~5120–5160), the `add_blocks` items
schema: add an optional `id` string and document the heading-match behavior, e.g.
"To update a section the user already added, pass the same `heading` (or its `id`);
the block is updated in place instead of duplicated."

### 3) Prompt — tell the agent the capability exists
In the system prompt, the "ADD A SECTION" instruction (ai_agent.py:530) currently
only describes appending. Add a sentence:
> "FILL/UPDATE AN EXISTING SECTION: if the user asks you to populate or update a
> block they already created (e.g. a 'Mitigation' block), call patch_scorecard with
> `add_blocks` using the SAME heading — it updates that block in place rather than
> creating a duplicate. Do NOT fold that content into top_risks or other standard
> fields when the user clearly wants it in their named block."

This also stops the wrong-field behavior (writing mitigations into top_risks).

## Verify (test mode, one thread)
1. On a scorecard, "+ Add block" → heading "Mitigation", body "checking".
2. Ask the agent: "fill the Mitigation block with a mitigation for each top risk."
3. Expect: the SAME Mitigation block's body is replaced (no duplicate appears), and
   the agent's confirmation says it updated custom_blocks (not top_risks).
4. Refresh → the change persists (proves it's in display_overrides.custom_blocks).
5. Regression: a plain "add a section on X" with a NEW heading still appends a new
   block (no false match), and wording edits to top_risks still work.

## Note
If, after this, an edit still doesn't show, separately confirm
`apply_scorecard_edit_in_place` (ai_agent.py:6202) actually persists
display_overrides for this thread and the canvas re-reads it — but the missing
upsert above is the reproducible root cause of the reported behavior.
