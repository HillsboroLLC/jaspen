"""P5b (AI-5): every AI operation records the prompt version that produced it.

Evidence only. Prompts, provider requests, routing, streaming, failover,
charges and the turn lifecycle ``version`` are unchanged. No provider is
called.
"""

import ast
import pathlib
import re
import uuid

import pytest

from app import db as _db
from app import prompt_version as pv
from app.ai_audit import (
    TURN_LIFECYCLE_VERSION,
    UNCLOSED_STALE_TURN_EVIDENCE,
    classify_unclosed_operation,
    persist_operation,
    report_turn_operations,
)
from app.models import AIOperation
from tests.journeys.test_conversation_turn_lifecycle import (  # noqa: F401  (fixtures)
    CONTINUE_URL,
    REGENERATE_URL,
    START_URL,
    _TWO_TURNS,
    _agent,
    _balance,
    _disable_rate_limiting_for_this_file,
    _post_turn,
    _script_generation,
    _seed,
    solo,
)

APP_DIR = pathlib.Path(__file__).resolve().parents[2] / "app"
URLS = {"start": START_URL, "continue": CONTINUE_URL, "regenerate": REGENERATE_URL}


def _body(route, thread_id):
    body = {"thread_id": thread_id}
    if route != "regenerate":
        body["message"] = "Record this turn"
    return body


def _prepare(user, route, thread_id):
    if route != "start":
        _seed(user, thread_id, history=_TWO_TURNS if route == "regenerate" else None)


def _ops(thread_id):
    _db.session.expire_all()
    return AIOperation.query.filter_by(thread_id=thread_id).all()


def _meta(operation):
    return operation.metadata_json or {}


@pytest.fixture
def conversation_version(app):
    version = pv.prompt_version("conversation")
    assert version and version.startswith("conversation:")
    return version


# --------------------------------------------------------------------------
# the version itself
# --------------------------------------------------------------------------

def test_every_family_resolves_to_a_deterministic_version(app):
    for family in pv.PROMPT_FAMILIES:
        cached = pv.prompt_version(family)
        fresh = pv.compute_prompt_version(family)
        assert cached == fresh, family
        assert re.fullmatch(rf"{re.escape(family)}:[0-9a-f]{{16}}", cached), cached
    # Deterministic, not time- or call-dependent.
    pv._cached_prompt_version.cache_clear()
    assert pv.warm_prompt_versions() == {f: pv.compute_prompt_version(f) for f in pv.PROMPT_FAMILIES}


def _edit_source(module, old, new):
    """``{module: source}`` with one exact edit, as a deploy would ship it."""
    source = pv._module_source(module)
    assert source.count(old) == 1, (module, old)
    return {module: source.replace(old, new)}


def _assignment_line(module, name):
    """The first line of ``name``'s module-level assignment, exactly."""
    mod = pv._Module(module, pv._module_source(module))
    return mod.material(name).splitlines(keepends=True)[0]


# (families, module, constant) for every static input B1 showed unhashed,
# plus the other constants and the cross-module renderers it named.
_B1_DEPENDENCIES = [
    (("scorecard", "scorecard_batch"), "app.routes.strategy", "_DEFAULT_SCORECARD_DIMENSIONS_BLOCK"),
    (("scorecard", "scorecard_batch"), "app.routes.strategy", "_OBJECTIVE_DIMENSION_WEIGHTS"),
    (("conversation",), "app.routes.ai_agent", "INTAKE_OBJECTIVE_GUIDANCE"),
    (("conversation",), "app.routes.ai_agent", "_CAPTURE_NOTE_KINDS"),
    (("report_generation",), "app.routes.reports", "REPORT_TYPE_DEFS"),
    (("public_intake_chat",), "app.routes._public_intake_chat", "_PUBLIC_PLAIN_MISSING_FOCUS"),
    (("conversation",), "app.routes.ai_agent", "_DECISION_CAPTURE_TOOLS"),
    (("conversation",), "app.routes.ai_agent", "_CAPTURE_TOOL_NAME"),
    (("conversation",), "app.routes.ai_agent", "_WBS_STATUS_KEYS"),
    (("conversation",), "app.routes.ai_agent", "CONNECTOR_CONTEXT_MAX_ALERTS"),
    (("portfolio_analysis",), "app.routes.strategy", "_SCORES_SORT_BY_OPTIONS"),
    (("conversation",), "app.memory_context", "MEMORY_OPEN_TAG"),
]


@pytest.mark.parametrize("families,module,name", _B1_DEPENDENCIES, ids=[d[2] for d in _B1_DEPENDENCIES])
def test_editing_a_static_prompt_constant_changes_its_family_version(app, families, module, name):
    line = _assignment_line(module, name)
    edited = _edit_source(module, line, line.rstrip("\n") + "  # edited\n")
    for family in families:
        assert pv.compute_prompt_version(family, sources=edited) != pv.compute_prompt_version(family), family
    # A family that does not use the constant is unaffected.
    assert pv.compute_prompt_version("feedback_digest", sources=edited) == pv.compute_prompt_version("feedback_digest")


@pytest.mark.parametrize("module,function", [
    ("app.jira_portfolio", "ai_prompt_text"),
    ("app.jira_portfolio", "ai_prompt_payload"),
    ("app.memory_context", "render_memory_prompt"),
])
def test_editing_a_cross_module_prompt_renderer_changes_the_conversation_version(app, module, function):
    edited = _edit_source(module, f"def {function}(", f"def {function}(  ")
    assert pv.compute_prompt_version("conversation", sources=edited) != pv.compute_prompt_version("conversation")


def test_editing_listed_prompt_text_changes_the_version(app):
    edited = _edit_source("app.routes.ai_agent", "_SYSTEM_PROMPT_PREFIX = (", "_SYSTEM_PROMPT_PREFIX = (  ")
    assert pv.compute_prompt_version("conversation", sources=edited) != pv.compute_prompt_version("conversation")


def test_shared_context_history_shaping_changes_workspace_assistant_versions(app):
    edited = _edit_source(
        "app.ai_context",
        "    def recent_history(self, *, limit, max_chars):",
        "    def recent_history(self, *, limit, max_chars):  ",
    )
    for family in ("scorecard_assistant", "execution_assistant"):
        material = {key for key, _source in pv.family_material(family)}
        assert "app.ai_context:SharedAssistantContext" in material
        assert pv.compute_prompt_version(family, sources=edited) != pv.compute_prompt_version(family)
    assert pv.compute_prompt_version("scorecard", sources=edited) == pv.compute_prompt_version("scorecard")


def test_an_unordered_constant_hashes_identically_under_every_hash_seed(app):
    """``_DECISION_CAPTURE_TOOLS`` is a set: its runtime order depends on
    PYTHONHASHSEED. The version must not."""
    import os
    import subprocess
    import sys

    backend = pathlib.Path(__file__).resolve().parents[2]
    script = (
        "import ast;"
        "from app import prompt_version as pv;"
        "m = pv._Module('app.routes.ai_agent', pv._module_source('app.routes.ai_agent'));"
        "value = ast.literal_eval(m.assigns['_DECISION_CAPTURE_TOOLS'][0].value);"
        "print(pv.compute_prompt_version('conversation'), ','.join(value))"
    )
    results = set()
    orders = set()
    for seed in ("0", "1", "2", "3", "4", "5"):
        out = subprocess.run(
            [sys.executable, "-c", script], cwd=backend, capture_output=True, text=True,
            env={**os.environ, "PYTHONHASHSEED": seed}, check=True,
        ).stdout.strip().splitlines()[-1]
        version, _, order = out.partition(" ")
        results.add(version)
        orders.add(order)
    assert len(results) == 1, results
    assert len(orders) > 1, "control: the set's runtime order really varies across seeds"


def test_an_unknown_or_missing_family_has_no_version_and_never_raises(app):
    assert pv.prompt_version(None) is None
    assert pv.prompt_version("") is None
    assert pv.prompt_version("no_such_family") is None


def test_restamp_keeps_a_different_earlier_version():
    assert pv.restamp_prompt_version({"a": 1}, "f:1") == {"a": 1, "prompt_version": "f:1"}
    assert pv.restamp_prompt_version({"prompt_version": "f:1"}, "f:1") == {"prompt_version": "f:1"}
    assert pv.restamp_prompt_version({"prompt_version": "f:1"}, "f:2") == {
        "prompt_version": "f:2", "prompt_version_history": ["f:1"],
    }
    assert pv.restamp_prompt_version({"prompt_version": "f:1"}, None) == {"prompt_version": "f:1"}


# --------------------------------------------------------------------------
# registry guards (static)
# --------------------------------------------------------------------------

def _module_tree(module_name):
    path = APP_DIR.parent / (module_name.replace(".", "/") + ".py")
    return ast.parse(path.read_text())


# Every app function, class or module a family symbol references must either
# be hashed (listed in the family) or appear here with the reason it does not
# shape static prompt text. Constants are never listed here: every referenced
# module-level constant is hashed automatically. The guard fails on any new,
# unclassified reference and on any stale entry below.
_NOT_PROMPT_MATERIAL = {
    "per-request data: loads, selects or normalizes this request's inputs": {
        "app.connector_monitor:check_connector_health",
        "app.connector_store:get_connector_settings",
        "app.decision_capture:decision_facts",
        "app.decision_facts:normalize_option_facts",
        "app.decision_facts:option_fact_text",
        "app.decision_fingerprint:scoring_fingerprint",
        "app.decision_records:execution_option_key",
        "app.decision_state:canonical_decision_state",
        "app.decision_state:stable_option_identity",
        "app.decision_state:state_is_reusable",
        "app.feedback_digest:summarize_feedback_items",
        "app.intake_readiness:normalize_strategy_objective",
        "app.jira_portfolio:refresh_portfolio",
        "app.memory_context:assemble_memory_context",
        "app.ai_context:build_shared_assistant_context",
        "app.netsuite_sync:fetch_netsuite_summary",
        "app.oracle_fusion_sync:fetch_oracle_summary",
        "app.salesforce_sync:fetch_pipeline_summary",
        "app.servicenow_sync:fetch_servicenow_summary",
        "app.snowflake_insights:extract_kpi_metrics",
        "app.routes.ai_agent:_collect_session_scorecards",
        "app.routes.ai_agent:_connected_connector_types",
        "app.routes.ai_agent:_connected_connector_types_from_registry",
        "app.routes.ai_agent:_iso_now",
        "app.routes.ai_agent:_load_user_memory",
        "app.routes.ai_agent:_normalize_company_size",
        "app.routes.ai_agent:_option_display_name",
        "app.routes.ai_agent:_project_scenarios",
        "app.routes.ai_agent:_project_sessions",
        "app.routes.ai_agent:_resolve_option_plan",
        "app.routes.ai_agent:_resolve_user_session",
        "app.routes.ai_agent:_sanitize_view_context",
        "app.routes.ai_agent:_session_chat_history",
        "app.routes.ai_agent:_thread_scorecard_summary",
        "app.routes.ai_agent:_turn_project",
        "app.routes.ai_agent:_unwrap_user_message_content",
        "app.routes.ai_agent:_user_has_active_connector",
        "app.routes.connectors:_text",
        "app.routes.reports:_safe_text",
        "app.routes.strategy:_collect_completed_scores",
        "app.routes.strategy:_criteria_with_supplied_information",
        "app.routes.strategy:_normalize_strategy_objective",
        "app.routes.strategy:_portfolio_agent_score_rows",
        "app.routes.strategy:_resolve_session_entry",
        "app.routes.strategy:_resolve_thread_wbs",
        "app.routes.strategy:_scorecard_snapshot_state",
        "app.routes.strategy:_thread_scenarios",
    },
    "decision kits: versioned per-request content; the kit key and version are recorded on the scorecard": {
        "app.decision_kits:get_decision_kit",
        "app.decision_processing:rubric_with_kit_gate_config",
        "app.decision_processing:normalize_gates",
        "app.decision_processing:apply_decision_kit",
    },
    "after generation: parses, validates or normalizes the model's output": {
        "app.decision_facts:apply_assumption_confidence_caps",
        "app.decision_lineage:assign_team_owners",
        "app.decision_lineage:validate_plan_lineage",
        "app.decision_metrics:calculate_metrics",
        "app.evidence_references:attach_evidence_references",
        "app.routes.ai_agent:_check_response_for_leak",
        "app.routes.ai_agent:_coerce_score_int",
        "app.routes.ai_agent:_extract_json_response_object",
        "app.routes.ai_agent:_json_safe_value",
        "app.routes.ai_agent:_validated_decision_kit_judgment",
        "app.routes.insights:_extract_json_object",
        "app.routes.strategy:InvalidTaskDate",
        "app.routes.strategy:UngroundedScorecardJudgment",
        "app.routes.strategy:_apply_execution_assistant_actions",
        "app.routes.strategy:_apply_neutral_unknown_criteria",
        "app.routes.strategy:_calibrate_confidence_to_verified_evidence",
        "app.routes.strategy:_clamp_unverified_high_confidence_dimensions",
        "app.routes.strategy:_clean_scorecard_text",
        "app.routes.strategy:_deterministic_executive_summary",
        "app.routes.strategy:_evidence_verification_text",
        "app.routes.strategy:_extract_json_object",
        "app.routes.strategy:_mark_scorecard_evidence_state",
        "app.routes.strategy:_merge_scorecard_patch",
        "app.routes.strategy:_normalize_scorecard_formatting",
        "app.routes.strategy:_normalize_scorecard_payload",
        "app.routes.strategy:_portfolio_summary_from_cards",
        "app.routes.strategy:_recompute_jaspen_score",
        "app.routes.strategy:_remove_unverified_model_numbers",
        "app.routes.strategy:_validate_grounded_scorecard_judgment",
    },
    "provider call, model selection or the operation runtime (prompt-free since P5a)": {
        "app.ai_runtime:AIOperationPaymentRequired",
        "app.ai_runtime:execute_customer_text_operation",
        "app.ai_runtime:execute_system_text_operation",
        "app.ai_runtime:reverse_customer_operation_charge",
        "app.routes._public_intake_chat:_public_preferred_model",
        "app.routes.ai_agent:_anthropic_api_key",
        "app.routes.ai_agent:_anthropic_json_completion",
        "app.routes.ai_agent:_anthropic_model_for_selection",
        "app.routes.ai_agent:_data_insights_model",
        "app.routes.ai_agent:_provider_model_id",
        "app.routes.strategy:_resolve_user_model_selection",
        "app.routes.strategy:_strategy_generate_reply",
    },
    "billing, authorization, persistence or audit": {
        "app.billing_config:bootstrap_legacy_credits",
        "app.billing_config:to_public_plan",
        "app.models:User",
        "app.project_scope:authorized_thread_scope",
        "app.routes.ai_agent:_public_usage_payload",
        "app.routes.ai_agent:_save_user_memory",
        "app.routes.sessions:save_one_project",
        "app.routes.strategy:_audit_strategy_event",
        "app.routes.strategy:_persist_generated_plan",
        "app.routes.strategy:_persist_scorecard_assistant_turn",
        "app.routes.strategy:_thread_scope",
        "app.session_access:RevisionConflict",
        "app.session_access:SessionAccessError",
    },
    "no-model fallback: shown instead of a model reply, never sent to a model": {
        "app.routes.ai_agent:_heuristic_insight_text",
        "app.routes.ai_agent:_heuristic_segment_summary",
        "app.routes.ai_agent:_safe_instructions_reply",
        "app.routes.connectors:_safe_data_context_failure_reason",
        "app.routes.insights:_heuristic_analysis",
        "app.routes.reports:_fallback_markdown",
    },
}


def test_every_dependency_of_a_family_is_hashed_or_classified(app):
    allowed = set().union(*_NOT_PROMPT_MATERIAL.values())
    referenced = set()
    unclassified = []
    for family in pv.PROMPT_FAMILIES:
        for symbol, helpers in pv.referenced_helpers(family).items():
            for helper in helpers:
                referenced.add(helper)
                if helper not in allowed:
                    unclassified.append(f"{family}: {symbol} -> {helper}")
    assert not unclassified, (
        "Hash these in their family, or classify them in _NOT_PROMPT_MATERIAL with a reason:\n"
        + "\n".join(sorted(unclassified))
    )
    stale = allowed - referenced
    assert not stale, f"stale _NOT_PROMPT_MATERIAL entries: {sorted(stale)}"
    reasons = [name for names in _NOT_PROMPT_MATERIAL.values() for name in names]
    assert len(reasons) == len(set(reasons)), "an entry is classified twice"


def test_every_referenced_constant_is_hashed(app):
    """Constants are included automatically and transitively, in their own
    module or imported from app.*, whatever their name."""
    for family, (home, entries) in pv.PROMPT_FAMILIES.items():
        hashed = {key for key, _text in pv.family_material(family)}
        modules = {}
        for entry in entries:
            mod, name = pv._split(home, entry)
            source = modules.setdefault(mod, pv._Module(mod, pv._module_source(mod)))
            nodes = [source.defs[name]] if name in source.defs else source.assigns[name]
            for node in nodes:
                for ref in pv.referenced_names(node):
                    if ref in source.assigns:
                        assert f"{mod}:{ref}" in hashed, (family, entry, ref)


def test_the_guard_catches_a_new_unclassified_helper(app, monkeypatch):
    """Negative control: a new helper called from a family symbol fails the guard."""
    module = "app.routes.reports"
    edited = _edit_source(module, "def _llm_report_markdown(", "def _new_prompt_helper():\n    return 1\n\n\ndef _llm_report_markdown(")
    source = edited[module].replace("    prompt = f\"\"\"", "    _new_prompt_helper()\n    prompt = f\"\"\"", 1)
    assert "_new_prompt_helper()\n    prompt" in source
    real = pv._module_source
    monkeypatch.setattr(pv, "_module_source", lambda name: source if name == module else real(name))
    pv._parsed_module.cache_clear()
    try:
        found = pv.referenced_helpers("report_generation")
    finally:
        monkeypatch.undo()
        pv._parsed_module.cache_clear()
    assert "app.routes.reports:_new_prompt_helper" in found["app.routes.reports:_llm_report_markdown"]


def test_every_chat_system_prompt_section_is_in_the_conversation_family():
    tree = _module_tree("app.routes.ai_agent")
    sections = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.AugAssign) and getattr(node.target, "id", None) == "system_prompt":
            for item in ast.walk(node.value):
                if isinstance(item, ast.Call) and isinstance(item.func, ast.Name):
                    sections.add(item.func.id)
    assert sections, "expected the reply generators to append prompt sections"
    assert sections <= set(pv.PROMPT_FAMILIES["conversation"][1])


def test_workspace_shared_context_dependency_cannot_leave_prompt_version_tracking():
    dependency = "app.ai_context:SharedAssistantContext"
    for family, route_symbol in (
        ("scorecard_assistant", "scorecard_assistant"),
        ("execution_assistant", "execution_assistant"),
    ):
        home, entries = pv.PROMPT_FAMILIES[family]
        assert home == "app.routes.strategy"
        assert route_symbol in entries
        assert dependency in entries


_OPERATION_ENTRIES = {
    "execute_customer_operation", "execute_customer_text_operation",
    "execute_system_text_operation", "_anthropic_json_completion", "persist_operation",
    "claim_turn_operation",
}
# persist_operation calls that need no family: the strategy-route recorders
# are only ever called with persist_ai_operation=False (asserted below).
_UNVERSIONED_PERSIST_SITES = {("app/routes/strategy.py", "_record_claude_operation"),
                              ("app/routes/strategy.py", "_record_claude_operation_batch")}


def _calls(name_filter):
    for path in sorted(APP_DIR.rglob("*.py")):
        rel = str(path.relative_to(APP_DIR.parent))
        tree = ast.parse(path.read_text())
        stack = []

        class Visitor(ast.NodeVisitor):
            def visit_FunctionDef(self, node):
                stack.append(node.name)
                self.generic_visit(node)
                stack.pop()

            visit_AsyncFunctionDef = visit_FunctionDef

            def visit_Call(self, node):
                name = getattr(node.func, "id", None) or getattr(node.func, "attr", None)
                if name in name_filter:
                    found.append((rel, stack[-1] if stack else None, node, name))
                self.generic_visit(node)

        found = []
        Visitor().visit(tree)
        yield from found


def test_every_ai_operation_entry_names_its_prompt_family():
    unnamed = []
    literal_families = set()
    for rel, function, node, name in _calls(_OPERATION_ENTRIES):
        keywords = {k.arg: k.value for k in node.keywords}
        if None in keywords:  # **kwargs pass-through (execute_system_text_operation)
            continue
        if (rel, function) in _UNVERSIONED_PERSIST_SITES and name == "persist_operation":
            continue
        if "prompt_family" not in keywords:
            unnamed.append(f"{rel}:{node.lineno} {function} -> {name}")
            continue
        value = keywords["prompt_family"]
        if isinstance(value, ast.Constant):
            literal_families.add(value.value)
    assert not unnamed, unnamed
    assert literal_families <= set(pv.PROMPT_FAMILIES), literal_families - set(pv.PROMPT_FAMILIES)


def test_strategy_recorders_never_persist_an_operation_today():
    for rel, function, node, _name in _calls({"_record_claude_operation", "_record_claude_operation_batch"}):
        keywords = {k.arg: k.value for k in node.keywords}
        if function in {"_record_claude_operation", "_record_claude_operation_batch"}:
            continue  # the recorders' own internal forwarding
        flag = keywords.get("persist_ai_operation")
        assert isinstance(flag, ast.Constant) and flag.value is False, f"{rel}:{node.lineno}"


# --------------------------------------------------------------------------
# conversation turns (P4.0 claimed operations)
# --------------------------------------------------------------------------

@pytest.mark.parametrize("route", ["start", "continue", "regenerate"])
@pytest.mark.parametrize("stream", [False, True], ids=["json", "stream"])
def test_a_settled_turn_records_its_prompt_version(client, db, solo, monkeypatch, route, stream, conversation_version):
    _script_generation(monkeypatch)
    thread_id = f"t-p5b-ok-{route}-{uuid.uuid4().hex[:6]}"
    _prepare(solo["user"], route, thread_id)
    _post_turn(client, URLS[route], solo["headers"], _body(route, thread_id), stream=stream)

    [operation] = _ops(thread_id)
    lifecycle = _meta(operation)["turn_lifecycle"]
    assert operation.status in {"succeeded", "degraded"}
    assert _meta(operation)["prompt_version"] == conversation_version
    assert lifecycle["prompt_version"] == conversation_version
    # The lifecycle version P4.1's classifier keys on is unchanged.
    assert lifecycle["version"] == TURN_LIFECYCLE_VERSION == "p4.0-s0"
    # Existing closing metadata is intact.
    for key in ("degraded", "billable_action_completed", "customer_charged_once", "plan_attempts"):
        assert key in _meta(operation)


@pytest.mark.parametrize("stream", [False, True], ids=["json", "stream"])
def test_a_failed_turn_keeps_its_prompt_version(client, db, solo, monkeypatch, stream, conversation_version):
    _script_generation(monkeypatch, fail_with=RuntimeError("provider exploded"))
    thread_id = f"t-p5b-fail-{uuid.uuid4().hex[:6]}"
    _seed(solo["user"], thread_id)
    try:
        _post_turn(client, CONTINUE_URL, solo["headers"], {"thread_id": thread_id, "message": "Hi"}, stream=stream)
    except RuntimeError:
        pass

    [operation] = _ops(thread_id)
    assert operation.status == "failed"
    assert _meta(operation)["turn_lifecycle"]["outcome"] == "generation_failed"
    assert _meta(operation)["prompt_version"] == conversation_version
    assert _meta(operation)["turn_lifecycle"]["prompt_version"] == conversation_version


def test_a_turn_closed_without_a_provider_audit_keeps_its_prompt_version(client, db, solo, monkeypatch, conversation_version):
    agent = _agent()
    _script_generation(monkeypatch)
    monkeypatch.setattr(agent, "_reserve_preflight_credits", lambda *_a, **_k: {
        "ok": False, "required": 10, "reserved": 0, "remaining": 0,
        "payload": {"error": "Out of Thinking Power", "code": "thinking_power_exhausted"},
    })
    thread_id = f"t-p5b-refused-{uuid.uuid4().hex[:6]}"
    _seed(solo["user"], thread_id)
    _post_turn(client, CONTINUE_URL, solo["headers"], {"thread_id": thread_id, "message": "Hi"}, stream=False)

    [operation] = _ops(thread_id)
    assert _meta(operation)["turn_lifecycle"]["outcome"] == "refused_at_reserve"
    assert _meta(operation)["prompt_version"] == conversation_version


def test_a_turn_replay_creates_no_second_version(client, db, solo, monkeypatch, conversation_version):
    _script_generation(monkeypatch)
    thread_id = f"t-p5b-replay-{uuid.uuid4().hex[:6]}"
    _seed(solo["user"], thread_id)
    headers = {**solo["headers"], "X-Jaspen-Idempotency-Key": f"k-{uuid.uuid4().hex}"}
    body = {"thread_id": thread_id, "message": "Same turn", "idempotency_key": headers["X-Jaspen-Idempotency-Key"]}
    _post_turn(client, CONTINUE_URL, headers, body, stream=False)
    first = [(op.id, dict(op.metadata_json)) for op in _ops(thread_id)]
    _post_turn(client, CONTINUE_URL, headers, body, stream=False)
    second = [(op.id, dict(op.metadata_json)) for op in _ops(thread_id)]
    assert second == first
    assert all(meta["prompt_version"] == conversation_version for _id, meta in second)


def test_closing_a_claimed_turn_never_restamps_it(app, db, solo, monkeypatch):
    """The claim-time version is the turn's version, even if the cached
    version were different when the turn closes."""
    from app.ai_audit import claim_turn_operation

    with app.test_request_context():
        operation_id, _lifecycle = claim_turn_operation(solo["user"], thread_id="t-p5b-claim")
        _db.session.commit()
        claimed = _meta(_db.session.get(AIOperation, operation_id))["prompt_version"]
        monkeypatch.setattr(pv, "_cached_prompt_version", lambda family: f"{family}:ffffffffffffffff")
        persist_operation(
            solo["user"], usage={"operation_id": operation_id, "input_tokens": 1, "output_tokens": 1,
                                 "provider": "anthropic", "model": "claude-sonnet-5"},
            charged_credits=0, operation_type="conversation", thread_id="t-p5b-claim",
            prompt_family="conversation",
        )
        _db.session.commit()
        operation = _db.session.get(AIOperation, operation_id)
        assert _meta(operation)["prompt_version"] == claimed
        assert _meta(operation)["turn_lifecycle"]["prompt_version"] == claimed
        assert "prompt_version_history" not in _meta(operation)


def test_turn_claim_accepts_the_callers_prompt_family(app, db, solo):
    from app.ai_audit import claim_turn_operation

    with app.test_request_context():
        operation_id, lifecycle = claim_turn_operation(
            solo["user"], thread_id="t-p5c-family", prompt_family="execution_assistant",
        )
        _db.session.commit()
        operation = _db.session.get(AIOperation, operation_id)
        expected = pv.prompt_version("execution_assistant")
        assert lifecycle["prompt_version"] == expected
        assert _meta(operation)["prompt_version"] == expected
        assert _meta(operation)["turn_lifecycle"]["version"] == TURN_LIFECYCLE_VERSION


# --------------------------------------------------------------------------
# runtime operations (execute_customer_operation)
# --------------------------------------------------------------------------

def _usage():
    return {"provider": "anthropic", "model": "claude-sonnet-5", "input_tokens": 10, "output_tokens": 5,
            "billable_action_completed": True}


def _run(user, *, key, generate, family="batch_ranking", payload=None):
    from app.ai_runtime import execute_customer_operation

    return execute_customer_operation(
        user, generate=generate, operation_type="batch_ranking",
        request_payload=payload or {"q": "same"}, idempotency_key=key,
        customer_visible=False, prompt_family=family, thread_id="t-p5b-runtime",
    )


def _op_by_key(user, key):
    import hashlib
    hashed = hashlib.sha256(f"{user.id}:batch_ranking:{key}".encode()).hexdigest()
    _db.session.expire_all()
    return AIOperation.query.filter_by(idempotency_key=hashed).one()


def test_runtime_operation_success_records_the_version_and_keeps_its_metadata(app, db, solo):
    with app.test_request_context():
        key = f"rk-{uuid.uuid4().hex}"
        _run(solo["user"], key=key, generate=lambda: ({"ok": 1}, _usage()))
        operation = _op_by_key(solo["user"], key)
        meta = _meta(operation)
        assert operation.status == "succeeded"
        assert meta["prompt_version"] == pv.prompt_version("batch_ranking")
        for k in ("idempotency_protected", "shadow_projected_credits", "charge_owner", "customer_charged_once"):
            assert k in meta


def test_runtime_operation_failure_keeps_the_version(app, db, solo):
    def boom():
        raise RuntimeError("provider down")

    with app.test_request_context():
        key = f"rk-{uuid.uuid4().hex}"
        with pytest.raises(RuntimeError):
            _run(solo["user"], key=key, generate=boom)
        operation = _op_by_key(solo["user"], key)
        assert operation.status == "failed"
        assert _meta(operation)["prompt_version"] == pv.prompt_version("batch_ranking")


def test_runtime_replay_returns_the_cached_result_without_touching_the_version(app, db, solo):
    with app.test_request_context():
        key = f"rk-{uuid.uuid4().hex}"
        _run(solo["user"], key=key, generate=lambda: ({"ok": 1}, _usage()))
        before = dict(_meta(_op_by_key(solo["user"], key)))
        calls = []
        _value, _usage_out, settlement = _run(
            solo["user"], key=key, generate=lambda: calls.append(1) or ({"ok": 2}, _usage()),
        )
        assert settlement["idempotent_replay"] is True and not calls
        assert dict(_meta(_op_by_key(solo["user"], key))) == before


def test_a_retry_under_a_new_prompt_keeps_the_earlier_version_in_history(app, db, solo, monkeypatch):
    def boom():
        raise RuntimeError("provider down")

    with app.test_request_context():
        key = f"rk-{uuid.uuid4().hex}"
        with pytest.raises(RuntimeError):
            _run(solo["user"], key=key, generate=boom)
        original = _meta(_op_by_key(solo["user"], key))["prompt_version"]

        monkeypatch.setattr(pv, "_cached_prompt_version", lambda family: f"{family}:0123456789abcdef")
        _run(solo["user"], key=key, generate=lambda: ({"ok": 1}, _usage()))
        meta = _meta(_op_by_key(solo["user"], key))
        assert meta["prompt_version"] == "batch_ranking:0123456789abcdef"
        assert meta["prompt_version_history"] == [original]


def test_a_retry_under_the_same_prompt_records_no_history(app, db, solo):
    def boom():
        raise RuntimeError("provider down")

    with app.test_request_context():
        key = f"rk-{uuid.uuid4().hex}"
        with pytest.raises(RuntimeError):
            _run(solo["user"], key=key, generate=boom)
        _run(solo["user"], key=key, generate=lambda: ({"ok": 1}, _usage()))
        meta = _meta(_op_by_key(solo["user"], key))
        assert meta["prompt_version"] == pv.prompt_version("batch_ranking")
        assert "prompt_version_history" not in meta


def test_an_operation_without_a_key_is_stamped_when_it_is_written(app, db, solo):
    from app.ai_runtime import execute_customer_operation

    with app.test_request_context():
        thread_id = f"t-p5b-nokey-{uuid.uuid4().hex[:6]}"
        execute_customer_operation(
            solo["user"], generate=lambda: ({"ok": 1}, _usage()), operation_type="report_generation",
            request_payload={}, customer_visible=False, prompt_family="report_generation", thread_id=thread_id,
        )
        [operation] = _ops(thread_id)
        assert _meta(operation)["prompt_version"] == pv.prompt_version("report_generation")


def test_a_charged_runtime_operation_charges_exactly_as_before(app, db, solo):
    """The version is evidence only: same charge with or without a family."""
    from app.ai_runtime import execute_customer_operation

    charges = []
    with app.test_request_context():
        for family in (None, "batch_ranking"):
            before = _balance(solo["user"])
            _v, _u, settlement = execute_customer_operation(
                solo["user"], generate=lambda: ({"ok": 1}, _usage()), operation_type="batch_ranking",
                request_payload={"f": family}, prompt_family=family, thread_id=f"t-p5b-charge-{family}",
            )
            charges.append((settlement["charged_credits"], before - _balance(solo["user"])))
    assert charges[0] == charges[1]
    assert charges[0][0] > 0 and charges[0][0] == charges[0][1]


# --------------------------------------------------------------------------
# historical rows (no version) stay readable
# --------------------------------------------------------------------------

def test_historical_rows_without_a_version_remain_readable(app, db, solo):
    from datetime import datetime, timedelta

    old = datetime.utcnow() - timedelta(days=2)
    row = AIOperation(
        id=str(uuid.uuid4()), user_id=str(solo["user"].id), thread_id="t-p5b-hist",
        operation_type="conversation", status="started", router_mode="shadow",
        router_version="jaspen-router-v1", policy_mode="shadow", policy_version="provider-cost-3600-v1",
        metadata_json={"turn_lifecycle": {"version": TURN_LIFECYCLE_VERSION, "estimated_reservation": 3}},
        created_at=old, updated_at=old,
    )
    _db.session.add(row)
    _db.session.commit()

    assert classify_unclosed_operation(row)["class"] == UNCLOSED_STALE_TURN_EVIDENCE
    report = report_turn_operations(since_days=0)
    [listed] = [item for item in report["unclosed"] if item["operation_id"] == row.id]
    assert listed["prompt_version"] is None
    assert "prompt_version" not in (row.metadata_json or {})
