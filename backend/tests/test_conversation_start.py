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

No provider credential is configured in the test environment. Tests that
exercise successful endpoint plumbing inject a controlled provider result;
provider-unavailable behavior is covered explicitly and must never masquerade
as a normal assistant response.
"""

import json
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


def _sse_events(response):
    return [
        json.loads(line[6:])
        for line in response.get_data(as_text=True).splitlines()
        if line.startswith("data: ")
    ]


def _patch_generation_success(monkeypatch):
    from app.routes import ai_agent

    monkeypatch.setattr(ai_agent, "_generate_assistant_reply", lambda *_args, **_kwargs: (
        "What outcome and time horizon should guide this decision?",
        {"provider": "test", "model": "test", "input_tokens": 1, "output_tokens": 1, "total_tokens": 2},
        [], [], None,
    ))
    monkeypatch.setattr(ai_agent, "_classify_decision_kit", lambda message, _selection: (
        {"kit": "rfp_bid", "confidence": "high", "evidence_quote": "RFP"}
        if "rfp" in message.lower() else
        {"kit": "none", "confidence": "high", "evidence_quote": ""}
    ))

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
    def test_new_thread_is_persisted_before_first_turn_tools(self, client, db, monkeypatch):
        from app.routes import ai_agent
        from app.routes.sessions import load_user_sessions

        signup = _signup(client)
        user_id = signup["user"]["id"]
        thread_id = f"thread_{uuid.uuid4().hex[:16]}"

        def assert_thread_exists(*_args, **_kwargs):
            stored = load_user_sessions(user_id)[thread_id]
            assert stored["chat_history"][-1]["content"] == "Use Value 60% and Risk 40%. Score it now."
            return ("Scoring started.", {"provider": "test", "model": "test", "input_tokens": 1, "output_tokens": 1, "total_tokens": 2}, [], [], None)

        monkeypatch.setattr(ai_agent, "_generate_assistant_reply", assert_thread_exists)
        response = client.post(START_URL, json={"message": "Use Value 60% and Risk 40%. Score it now.", "thread_id": thread_id})
        assert response.status_code == 200, response.get_data(as_text=True)

    def test_manual_and_inferred_rfp_activation_share_persisted_state(self, client, db, monkeypatch):
        from app.routes.sessions import load_user_sessions

        signup = _signup(client)
        user_id = signup["user"]["id"]
        _patch_generation_success(monkeypatch)
        message = "We received an RFP and need to decide whether to respond."
        manual_id = f"thread_{uuid.uuid4().hex[:16]}"
        inferred_id = f"thread_{uuid.uuid4().hex[:16]}"
        manual = client.post(START_URL, json={"message": message, "thread_id": manual_id, "strategy_objective": "growth", "decision_kit": "rfp"})
        inferred = client.post(START_URL, json={"message": message, "thread_id": inferred_id, "strategy_objective": "growth"})
        assert manual.status_code == inferred.status_code == 200
        sessions = load_user_sessions(user_id)
        for thread_id in (manual_id, inferred_id):
            assert sessions[thread_id]["decision_kit"] == "rfp_bid"
            assert sessions[thread_id]["decision_kit_family"] == "rfp"
            assert sessions[thread_id]["strategy_objective"] == "growth"
        assert sessions[manual_id]["decision_kit_source"] == "user"
        assert sessions[inferred_id]["decision_kit_source"] == "model_inference"

    def test_ambiguous_inferred_rfp_asks_one_subtype_question(self, client, db, monkeypatch):
        from app.routes import ai_agent

        _signup(client)
        monkeypatch.setattr(ai_agent, "_classify_decision_kit", lambda *_args, **_kwargs: {
            "kit": "none", "confidence": "low", "evidence_quote": "this RFP",
        })
        response = client.post(START_URL, json={"message": "Help me with this RFP.", "thread_id": f"thread_{uuid.uuid4().hex[:16]}"})
        assert response.status_code == 200
        assert response.get_json()["reply"] == ai_agent.RFP_SUBTYPE_QUESTION
        assert response.get_json()["decision_kit_family"] == "rfp"

    @pytest.mark.parametrize("message", [
        "Should we respond to the state’s RFP?",
        "Should we pursue this opportunity?",
        "Help me decide whether to bid.",
        "We received an RFP and need to decide whether to respond.",
    ])
    def test_common_response_side_phrasing_resolves_rfp_bid(self, message):
        from app.routes.ai_agent import _infer_rfp_decision_kit

        assert _infer_rfp_decision_kit(message) == "rfp_bid"

    @pytest.mark.parametrize("message", [
        "Our committee is evaluating three contractor bids.",
        "We received vendor proposals and need to select one.",
        "Help us evaluate these proposals.",
    ])
    def test_common_buyer_side_phrasing_resolves_vendor_selection(self, message):
        from app.routes.ai_agent import _infer_rfp_decision_kit

        assert _infer_rfp_decision_kit(message) == "rfp_vendor_selection"

    def test_rfp_selection_persists_through_new_thread_and_subtype_resolves_in_discovery(
        self, client, db, monkeypatch
    ):
        from app.routes import ai_agent

        _signup(client)
        thread_id = f"thread_{uuid.uuid4().hex[:16]}"
        monkeypatch.setattr(ai_agent, "_classify_decision_kit", lambda message, _selection: (
            {"kit": "rfp_vendor_selection", "confidence": "high", "evidence_quote": "selecting a vendor"}
            if "selecting a vendor" in message.lower() else
            {"kit": "none", "confidence": "low", "evidence_quote": "this RFP"}
        ))

        started = client.post(START_URL, json={
            "message": "Help me with this RFP.",
            "thread_id": thread_id,
            "strategy_objective": "growth",
            "decision_kit": "rfp",
        })
        assert started.status_code == 200, started.get_data(as_text=True)
        payload = started.get_json()
        assert payload["thread_id"] == thread_id
        assert payload["strategy_objective"] == "growth"
        assert payload["decision_kit_family"] == "rfp"
        assert payload["decision_kit"] is None
        assert payload["reply"] == ai_agent.RFP_SUBTYPE_QUESTION

        stored = client.get(f"/api/v1/ai-agent/threads/{thread_id}")
        assert stored.status_code == 200
        thread = stored.get_json()["thread"]
        assert thread["strategy_objective"] == "growth"
        assert thread["decision_kit_family"] == "rfp"

        monkeypatch.setattr(ai_agent, "_generate_assistant_reply", lambda *_args, **_kwargs: (
            "I’ll evaluate the submitted vendors.",
            {"provider": "test", "model": "test", "input_tokens": 0, "output_tokens": 0, "total_tokens": 0},
            [], [], None,
        ))
        continued = client.post("/api/v1/ai-agent/conversation/continue", json={
            "thread_id": thread_id,
            "message": "We are selecting a vendor.",
            "strategy_objective": "growth",
        })
        assert continued.status_code == 200, continued.get_data(as_text=True)
        resolved = client.get(f"/api/v1/ai-agent/threads/{thread_id}").get_json()["thread"]
        assert resolved["strategy_objective"] == "growth"
        assert resolved["decision_kit"] == "rfp_vendor_selection"
        assert resolved["decision_kit_family"] == "rfp"

    def test_stream_provider_unavailable_preserves_message_and_records_failed_zero_credit_operation(
        self, client, db, monkeypatch
    ):
        from app.models import AIOperation, UsageEvent, User
        from app.routes import ai_agent

        signup = _signup(client)
        user_id = signup["user"]["id"]
        user = User.query.get(user_id)
        credits_before = user.credits_remaining
        thread_id = f"thread_{uuid.uuid4().hex[:16]}"
        user_message = "Evaluate this expansion decision using the evidence I provided."

        monkeypatch.setattr(ai_agent, "_resolve_governed_routes", lambda *_args, **_kwargs: ([], {}))

        response = client.post(f"{START_URL}?stream=true", json={
            "message": user_message,
            "thread_id": thread_id,
            "strategy_objective": "balanced",
        })
        assert response.status_code == 200
        events = _sse_events(response)
        assert [event["type"] for event in events] == ["error"]
        failure = events[0]
        assert failure["code"] == "analysis_unavailable"
        assert failure["failure_state"] is True
        assert failure["retryable"] is True
        assert failure["action"] == {"type": "retry", "label": "Retry"}
        assert failure["message_saved"] is True
        assert failure["error"] == ai_agent.ANALYSIS_UNAVAILABLE_MESSAGE
        assert failure["credits"]["charged"] == 0
        assert "specific initiative goal" not in response.get_data(as_text=True)

        from app.routes.sessions import load_user_sessions
        stored = load_user_sessions(user_id)[thread_id]
        assert [entry["content"] for entry in stored["chat_history"] if entry["role"] == "user"] == [user_message]
        assert not [entry for entry in stored["chat_history"] if entry["role"] == "assistant"]

        db.session.expire_all()
        assert User.query.get(user_id).credits_remaining == credits_before
        operation = AIOperation.query.filter_by(thread_id=thread_id).one()
        assert operation.status == "failed"
        assert operation.charged_credits == 0
        assert operation.error_code == "provider_unavailable"
        usage = UsageEvent.query.filter_by(thread_id=thread_id).one()
        assert usage.success is False
        assert usage.credits_charged == 0

    def test_same_idempotency_key_replays_without_generating_or_charging_twice(
        self, client, db, monkeypatch
    ):
        from app.routes import ai_agent

        _signup(client)
        thread_id = f"thread_{uuid.uuid4().hex[:16]}"
        calls = {"generate": 0}

        def fake_generate(*_args, **_kwargs):
            calls["generate"] += 1
            return (
                "A single governed response.",
                {
                    "provider": "heuristic",
                    "model": None,
                    "input_tokens": 0,
                    "output_tokens": 0,
                    "total_tokens": 0,
                },
                [],
                [],
                None,
            )

        monkeypatch.setattr(ai_agent, "_generate_assistant_reply", fake_generate)
        payload = {
            "message": HOMEPAGE_CONTEXT,
            "thread_id": thread_id,
            "strategy_objective": "balanced",
        }
        headers = {"X-Jaspen-Idempotency-Key": f"test-{uuid.uuid4().hex}"}

        first = client.post(START_URL, json=payload, headers=headers)
        replay = client.post(START_URL, json=payload, headers=headers)

        assert first.status_code == 200
        assert replay.status_code == 200
        assert calls["generate"] == 1
        assert replay.get_json()["idempotent_replay"] is True
        assert replay.get_json()["reply"] == first.get_json()["reply"]
        assert replay.get_json()["credits"] == first.get_json()["credits"]

    def test_signup_then_conversation_start_succeeds(self, client, db, monkeypatch):
        """The full seam: fresh signup (cookie auth, exactly like the real
        flow) → conversation/start with the homepage handoff payload → 200
        with a usable thread. This is the test that would have caught the
        _iso_now 500."""
        _patch_generation_success(monkeypatch)
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

        # A successful provider response must come back non-empty.
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

    def test_handoff_readiness_matches_public_analyze(self, app, client, db, monkeypatch):
        """One Jaspen: the readiness the workspace computes for the handed-off
        context must equal what the public /analyze endpoint told the
        anonymous visitor moments earlier for the same words."""
        _patch_generation_success(monkeypatch)
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

    def test_repeated_start_with_same_thread_id_reuses_thread(self, client, db, monkeypatch):
        """The handoff retries with a persisted thread_id (double-click,
        login/signup race) — the server must converge on ONE thread, not
        mint duplicates."""
        _patch_generation_success(monkeypatch)
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
