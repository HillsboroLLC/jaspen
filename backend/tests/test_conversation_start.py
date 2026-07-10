"""Integration test for the Homepage V2 → signup → conversation/start handoff.

This is the seam the whole Homepage V2 project hangs on: an anonymous
visitor's intake context, carried through signup, must land in a real
authenticated conversation thread. It went completely untested for the
first months of this codebase's life, which allowed a NameError regression
(_iso_now deleted during the intake_readiness.py extraction) to 500 every
new-thread creation while the entire rest of the suite stayed green.

The request payload here is EXACTLY what the frontend handoff sends —
see frontend/src/homeSections/HomePage/StrategyAccessCard.jsx
continueWithPendingContext(): {"message": <canonical joined context>,
"thread_id": <client-generated thread_...>, "strategy_objective":
"balanced"}. The objective is explicit because the homepage computed its
readiness promise under 'balanced'; without it, conversation/start infers
an objective from the text and cost-heavy briefs silently open the
workspace under a different profile than the visitor was shown. If
conversation/start's contract changes, this test failing is the alarm.

No ANTHROPIC_API_KEY is configured in the test environment, so the agent's
reply comes from its deterministic fallback path — which is exactly what
makes this a pure test of the endpoint's own plumbing (session creation,
readiness computation, persistence, response contract) rather than of any
model's output.
"""

import uuid

import pytest


# Same pre-existing conftest gap as documented in test_public_intake.py:
# RATELIMIT_ENABLED=False in app config doesn't actually disable Flask-Limiter
# (it caches .enabled at init). conversation/start is limited to 3/minute, so
# without this fixture the suite would trip real 429s. Scoped to this file.
@pytest.fixture(autouse=True)
def _disable_rate_limiting_for_this_file():
    from app import limiter
    original = limiter.enabled
    limiter.enabled = False
    yield
    limiter.enabled = original


START_URL = "/api/v1/ai-agent/conversation/start"

# Representative homepage context: the canonical "\n\n"-joined user turns the
# hero writes to sessionStorage after each successful analyze (see
# pendingIntakeContext.js joinTurns()).
HOMEPAGE_CONTEXT = (
    "We need to increase on-time delivery from 78% to 95% within 6 months. "
    "Our current baseline is a 22% late-delivery rate, costing roughly "
    "$40,000 per month in penalty fees — that's our KPI."
    "\n\n"
    "Our ops team lead flagged dispatch staffing on weekends as the main "
    "bottleneck; a second weekend shift would unlock more throughput."
)


def _signup(client, email=None):
    resp = client.post(
        "/api/v1/auth/signup",
        json={
            "name": "Handoff Test",
            "email": email or f"handoff-{uuid.uuid4().hex[:10]}@example.com",
            "password": "StrongPass1",
            "plan_key": "free",
        },
    )
    assert resp.status_code == 201, resp.get_data(as_text=True)
    return resp.get_json()


class TestHomepageHandoffIntegration:
    def test_signup_then_conversation_start_succeeds(self, client, db):
        """The full seam: fresh signup (cookie auth, exactly like the real
        flow) → conversation/start with the homepage handoff payload → 200
        with a usable thread. This is the test that would have caught the
        _iso_now 500."""
        _signup(client)
        thread_id = f"thread_{uuid.uuid4().hex[:16]}"

        res = client.post(START_URL, json={
            "message": HOMEPAGE_CONTEXT,
            "thread_id": thread_id,
            "strategy_objective": "balanced",
        })
        assert res.status_code == 200, res.get_data(as_text=True)
        data = res.get_json()

        # The frontend redirects to /new?sid=<thread_id|session_id> — both
        # must be present and echo the client-generated id (idempotency
        # depends on the server honoring it, not minting its own).
        assert data["thread_id"] == thread_id
        assert data["session_id"] == thread_id

        # A real assistant reply must come back (fallback path, non-empty).
        assert str(data.get("reply") or data.get("message") or "").strip()

        # Readiness must be the deterministic engine's output, computed
        # server-side from the same words the homepage analyzed.
        readiness = data.get("readiness") or {}
        assert isinstance(readiness.get("percent"), int)
        assert isinstance(readiness.get("categories"), list) and readiness["categories"]
        assert data.get("status") in ("ready_to_analyze", "gathering_info", "in_progress")

        # The workspace must open under the SAME objective the homepage's
        # readiness promise was computed with. HOMEPAGE_CONTEXT is full of
        # delivery/on-time language — without the explicit objective in the
        # payload, conversation/start's inference returns "speed" (verified
        # directly against _infer_strategy_objective_from_message), so the
        # thread would open as Speed to Market instead of the Balanced the
        # visitor was shown. Field observed in the wild: a cost-heavy brief
        # opened as Cost Optimization via this same inference path.
        assert data.get("strategy_objective") == "balanced"

    def test_handoff_readiness_matches_public_analyze(self, app, client, db):
        """One Jaspen: the readiness the workspace computes for the handed-off
        context must equal what the public /analyze endpoint told the
        anonymous visitor moments earlier for the same words."""
        public = client.post(
            "/api/v1/public/intake/analyze",
            json={"history": [{"role": "user", "content": HOMEPAGE_CONTEXT}]},
        ).get_json()

        _signup(client)
        res = client.post(START_URL, json={
            "message": HOMEPAGE_CONTEXT,
            "thread_id": f"thread_{uuid.uuid4().hex[:16]}",
            "strategy_objective": "balanced",
        })
        assert res.status_code == 200
        workspace_readiness = res.get_json()["readiness"]

        assert workspace_readiness["percent"] == public["overall_percent"]
        workspace_completed = {
            c["key"]: bool(c["completed"]) for c in workspace_readiness["categories"]
        }
        public_completed = {c["key"]: True for c in public["known"]}
        public_completed.update({c["key"]: False for c in public["missing"]})
        assert workspace_completed == public_completed

    def test_repeated_start_with_same_thread_id_reuses_thread(self, client, db):
        """The handoff retries with a persisted thread_id (double-click,
        login/signup race) — the server must converge on ONE thread, not
        mint duplicates."""
        _signup(client)
        thread_id = f"thread_{uuid.uuid4().hex[:16]}"

        first = client.post(START_URL, json={"message": HOMEPAGE_CONTEXT, "thread_id": thread_id, "strategy_objective": "balanced"})
        assert first.status_code == 200
        second = client.post(START_URL, json={"message": "And one more detail on timing.", "thread_id": thread_id, "strategy_objective": "balanced"})
        assert second.status_code == 200
        assert second.get_json()["thread_id"] == thread_id

        threads = client.get("/api/v1/ai-agent/threads").get_json()
        sessions = threads.get("sessions", []) if isinstance(threads, dict) else threads
        matching = [t for t in sessions if t.get("session_id") == thread_id]
        assert len(matching) == 1

    def test_unauthenticated_start_rejected(self, client, db):
        """Anonymous users must never be able to create workspace threads —
        the homepage's only path in is /public/intake, never this endpoint."""
        res = client.post(START_URL, json={
            "message": HOMEPAGE_CONTEXT,
            "thread_id": f"thread_{uuid.uuid4().hex[:16]}",
        })
        assert res.status_code == 401
