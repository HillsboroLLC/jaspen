# Codex brief — the workspace must always lead the user to a scorecard

Status: PROPOSED (product principle + recommendation). Backend behavior change.
Author: marketing pass (Claude), read-only trace + founder direction.
For Fable to review and implement.

## The principle (read this first)

Jaspen promotes one promise: paste your context and it helps you weigh a
decision and walk away with a scored, defensible recommendation. The workspace
must **always visibly lead the user toward that scorecard.** This is not "always
score instantly." It is: every path the conversation can take must move toward
the weighed decision, and the user must never be left unsure whether the thing
they were promised is coming.

Three guarantees make that real:

1. **Offer to score with what is there, at honest confidence.** Missing evidence
   lowers confidence; it never blocks a score (Constitution Art. 13, 14). If the
   user has given a real decision and some context, Jaspen should offer (or just
   produce) a first scorecard at honest, possibly low/assumed confidence, and
   show what would sharpen it.
2. **Frame every question as building the scorecard.** When Jaspen does ask, the
   question must read as "this sharpens your scorecard," not as an open-ended
   interview with no visible destination. One high-value question at a time,
   always moving (Art. 15).
3. **Improving a score is a conversation, not a control.** The score appears when
   the agent judges it has enough. If the user thinks it is too low, they workshop
   it in dialogue: "what would make this higher?" or "what would give you more
   confidence?" The agent answers with specific, ranked actions (name the
   dimension, the evidence, the likely gain), and the user supplies it or not.
   No "score now" button — this stays a conversation, which is the point.

## Symptom that motivated this

A new user completed the homepage intake, cleared the readiness gate ("Enough
context to begin"), signed up, and landed in the workspace. Instead of moving
toward a scorecard, the agent asked open-ended clarifying questions with no
signal that a scorecard was coming. The user was left unsure the promised output
existed. When challenged, the agent conceded it should have moved to scoring.

Note on framing: the input was NOT too thin to start. It was a specific decision
(a contracting opportunity) with real context, tensions, and effectively a set
of user criteria embedded in the ask. The only thing missing was named options
to compare, which Jaspen can propose itself. So this is the exact case that
should have produced a humble first scorecard, not an open interview.

## Root cause (confirmed by read-only trace)

The handoff is intact; context reaches the agent:

1. Homepage joins the Q&A into one string and stores it
   (`frontend/src/shared/auth/pendingIntakeContext.js`).
2. On signup/login, `StrategyAccessCard.jsx` / `AuthCallback.jsx` POST it as the
   opening `message` to `/api/v1/ai-agent/conversation/start`
   (`strategy_objective: 'balanced'`).
3. `conversation_start` (`app/routes/ai_agent.py:8767`) starts a normal agent
   turn. It does not force or offer a scorecard; the system prompt decides.

The prompt biases the FIRST turn toward open interviewing:

- `ai_agent.py:569` — proactive interviewer "when criteria, weights, or key
  context are thin or missing... ask focused, ONE-AT-A-TIME questions."
- `ai_agent.py:632` — "any time this is the first turn... do NOT call
  generate_scorecard in the same reply... First give the shortlist... ask the
  user to confirm before scoring."

A single decision framed as an analysis request reads as "criteria thin" AND
trips the first-turn no-score guard, so the agent asks questions with no visible
path to the scorecard. That violates the promise above and Art. 13/15.

## Recommended fix

Make the three guarantees concrete. Fable's call on exact mechanics.

1. **First-turn behavior from a ready handoff or any substantial single
   decision:** propose a starter rubric (six defaults, objective-tilted, stated
   as proposed and editable) AND produce a first scorecard at honest confidence,
   OR, at minimum, lead with an explicit offer: "I can score this now with what
   you have (confidence will be modest and I will show what raises it), or ask
   one quick question first. Which do you want?" Never a silent open interview.
2. **Reframe clarifying questions** so each names the scorecard it is building
   ("To sharpen the Financial dimension, what is the rough day rate?") rather
   than open discovery.
3. **Keep the improve loop conversational.** After a score lands, the agent
   should make the improve path obvious in words ("this is a 61 at low
   confidence — ask me what would raise it, or what would make me more sure").
   The `what_would_improve` / confidence-gain guidance already exists in the
   scoring output; the fix is to surface and offer it reliably, not to add a UI
   button. No "Score now" control.

Preserve the guards where they belong:

- The first-turn no-score guard (`ai_agent.py:632`) is correct for "propose
  multiple options AND score them" — present the shortlist, score on confirm.
  Narrow it to that multi-option case so it does not suppress leading a single,
  well-specified decision toward its scorecard.
- A genuinely bare one-liner ("should I do X?" with no context) still gets one
  focused question — but framed as building the scorecard, with "score anyway"
  available.

Implementation options:
- Pass a signal from the handoff into `conversation_start` (e.g.
  `from_ready_gate: true` or the existing `intake_context`) so the first-turn
  path can deterministically choose "offer/produce scorecard" over open
  interview.
- Add the "Score now" control + intent in the workspace (`JaspenChat.jsx`) wired
  to the existing scoring tool path.

## Verification

- Paste the contracting-decision prompt, clear the gate, sign up: the first
  reply moves toward a scorecard. It either shows a first score at honest
  confidence or asks a single scorecard-framed question. It never opens a
  destination-less interview.
- After a score lands, "what would make this higher?" and "what would give you
  more confidence?" both return specific, ranked, dimension-named actions.
- "Propose 6 cities then score" still presents the shortlist first, scores on
  confirm (line 632 preserved).
- A bare one-liner gets one scorecard-framed question, with score-anyway
  available.

## Out of scope / caution

- Do not gate scoring on connectors or a captured rubric.
- Do not add rubric capture to the homepage intake (the rubric is proposed in the
  workspace; Art. 2).
- Honest confidence is the whole point: a humble, low-confidence first scorecard
  that shows what would sharpen it is the correct behavior, not a defect.
