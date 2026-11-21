"""P2d: the one-time legacy plan identifier backfill.

Acceptance tests 1 to 10 of P2B_ACCEPTANCE_DEPENDENCIES_2026-11-13.md section
1, plus 11: after the job, the five plan lookups (workspace, export, email,
chat plan tools, Jira) return the same plan for the same option id. Every run
here is against test fixtures; no real database is touched.
"""

import copy
import json
import re
import uuid

import pytest
from sqlalchemy.orm.attributes import flag_modified

from app import db as _db
from app.legacy_plan_backfill import backfill_legacy_plans, rollback_legacy_plans
from app.models import UserSession
from tests.journeys.test_p2b_workspace_project_access import (  # noqa: F401 (fixtures)
    HIST,
    MARKER,
    _call,
    _no_rate_limits,
    _project_state,
    _seed_populated_plan,
    solo,
    team,
)

OPTION_NAME = f"Title {MARKER}"


def _row(thread_id, user=None):
    _db.session.expire_all()
    query = UserSession.query.filter_by(session_id=thread_id)
    if user is not None:
        query = query.filter_by(user_id=user.id)
    return query.order_by(UserSession.id).first()


def _set_project(thread_id, owner, *, by_card, project_wbs=None, history=None, active=None):
    """Store exactly this plan data and chat history on the canonical row,
    with the product's own save path."""
    from app.scenarios_store import save_project_scenarios_data

    def _apply(td):
        td["wbs_by_scorecard"] = copy.deepcopy(by_card)
        if project_wbs is not None:
            td["project_wbs"] = copy.deepcopy(project_wbs)
        if active is None:
            td.pop("active_execution_scorecard_id", None)
        else:
            td["active_execution_scorecard_id"] = active
        return td

    save_project_scenarios_data(owner.id, thread_id, updater=_apply)
    if history is not None:
        row = _row(thread_id, owner)
        payload = dict(row.payload)
        payload["chat_history"] = copy.deepcopy(history)
        row.payload = payload
        flag_modified(row, "payload")
        _db.session.commit()
    _db.session.expire_all()


def _plan(title, *, key, name="Execution Plan", sc_name="Old idea", updated_at=None):
    plan = {
        "name": name, "scorecard_id": key, "scorecard_name": sc_name, "phases": [],
        "tasks": [{"id": "t1", "title": title, "status": "todo"}],
    }
    if updated_at:
        plan["updated_at"] = updated_at
    return plan


def _artifact(option_id, title="x"):
    return {
        "role": "assistant", "content": "Plan",
        "artifact": {"type": "execution_plan", "data": {
            "scorecard_id": option_id, "tasks": [{"id": "t1", "title": title}],
        }},
    }


def _add_option(owner, org, thread_id, card_id, name):
    from app.scorecards import upsert_scorecard

    upsert_scorecard(
        user_id=owner.id, thread_id=thread_id,
        payload={"id": card_id, "analysis_id": card_id, "thread_id": thread_id,
                 "name": name, "project_name": name, "jaspen_score": 61},
        organization_id=org.id, session_id=thread_id, source="native",
    )
    _db.session.commit()


def _write(tmp_path, **kwargs):
    path = tmp_path / f"before-{uuid.uuid4().hex[:6]}.jsonl"
    report = backfill_legacy_plans(write=True, before_image_path=str(path), **kwargs)
    return report, path


def _project(report, thread_id):
    return [p for p in report["projects"] if p["session_id"] == thread_id]


# 1 ---------------------------------------------------------------------------

def test_a_stale_key_plan_moves_to_its_option_with_the_right_name_once(team, tmp_path):
    owner = team["users"]["owner"]
    card_id = team["projects"]["owner"][1]
    _seed_populated_plan("t-shared", card_id, owner)
    revision = int(_row("t-shared", owner).revision)

    report, _path = _write(tmp_path)

    td = _row("t-shared", owner).scenarios_json
    assert sorted(td["wbs_by_scorecard"]) == [card_id]
    plan = td["wbs_by_scorecard"][card_id]
    assert plan["scorecard_id"] == card_id
    assert plan["scorecard_name"] == OPTION_NAME
    assert plan["idea_name"] == OPTION_NAME
    assert plan["name"] == f"{OPTION_NAME} — Execution Plan"
    assert plan["tasks"] == [{"id": "t1", "title": f"Kickoff for {OPTION_NAME}", "status": "todo"}]
    assert td["project_wbs"] == plan, "the thread-level mirror follows the moved plan"
    assert int(_row("t-shared", owner).revision) == revision + 1
    changes = _project(report, "t-shared")[0]["changes"]
    assert {"change": "rekey", "from_key": "stale-id", "to_option_id": card_id,
            "plan_name": plan["name"], "option_name": OPTION_NAME} in changes

    before = _project_state("t-shared")
    second, _ = _write(tmp_path)
    assert _project_state("t-shared") == before
    assert second["counts"]["rows_changed"] == 0


# 2 ---------------------------------------------------------------------------

def test_a_plan_under_a_current_options_id_is_never_touched(team, tmp_path):
    owner, org = team["users"]["owner"], team["org"]
    card_id = team["projects"]["owner"][1]
    _add_option(owner, org, "t-shared", "t-shared-beta", "Beta Logistics Option")
    # Option A's plan names option B in its content; B has no plan.
    misnamed = _plan("Kickoff for Beta Logistics Option", key=card_id)
    _set_project("t-shared", owner, by_card={card_id: misnamed},
                 history=list(HIST) + [_artifact(card_id, "Kickoff for Beta Logistics Option")])
    before = _project_state("t-shared")

    report, _ = _write(tmp_path)

    assert _project_state("t-shared") == before
    assert _row("t-shared", owner).scenarios_json["wbs_by_scorecard"] == {card_id: misnamed}
    assert report["counts"]["rekeys"] == 0


# 3 ---------------------------------------------------------------------------

def test_two_stale_plans_for_one_option_move_the_newest_and_report_the_other(team, tmp_path):
    owner = team["users"]["owner"]
    card_id = team["projects"]["owner"][1]
    older = _plan(f"Kickoff for {OPTION_NAME}", key="stale-old", updated_at="2026-01-01T00:00:00")
    newer = _plan(f"Plan review for {OPTION_NAME}", key="stale-new", updated_at="2026-06-01T00:00:00")
    _set_project("t-shared", owner, by_card={"stale-old": older, "stale-new": newer})

    report, _ = _write(tmp_path)

    by_card = _row("t-shared", owner).scenarios_json["wbs_by_scorecard"]
    assert sorted(by_card) == sorted([card_id, "stale-old"])
    assert by_card[card_id]["tasks"] == newer["tasks"]
    assert by_card["stale-old"] == older
    reported = _project(report, "t-shared")[0]["reported"]
    assert any(r["case"] == "stale_plan_older_duplicate" and r["key"] == "stale-old"
               and r["names_option_id"] == card_id for r in reported)


# 4 ---------------------------------------------------------------------------

def test_a_stale_plan_that_names_no_option_stays_and_is_reported(team, tmp_path):
    owner = team["users"]["owner"]
    card_id = team["projects"]["owner"][1]
    nameless = _plan("Kickoff for something unrelated", key="stale-x")
    # No artifact for it either: the job must not make an unattributed plan
    # visible in Session Artifacts.
    _set_project("t-shared", owner, by_card={"stale-x": nameless}, history=list(HIST))
    before = _project_state("t-shared")

    report, _ = _write(tmp_path)

    assert _project_state("t-shared") == before
    reported = _project(report, "t-shared")[0]["reported"]
    assert {"case": "stale_plan_names_no_option", "key": "stale-x", "names_option_id": None,
            "option_name": None, "updated_at": None} in reported
    assert card_id not in _row("t-shared", owner).scenarios_json["wbs_by_scorecard"]


# 5 ---------------------------------------------------------------------------

def test_missing_artifact_registered_orphan_removed_rest_of_history_identical(team, tmp_path):
    owner = team["users"]["owner"]
    card_id = team["projects"]["owner"][1]
    plan = _plan(f"Kickoff for {OPTION_NAME}", key=card_id, sc_name=OPTION_NAME)
    _set_project("t-shared", owner, by_card={card_id: plan},
                 history=list(HIST) + [_artifact("orphan-id", "Unrelated old task")])
    td_before = copy.deepcopy(_row("t-shared", owner).scenarios_json)

    report, _ = _write(tmp_path)

    row = _row("t-shared", owner)
    history = row.payload["chat_history"]
    assert json.dumps(history[:len(HIST)], sort_keys=True) == json.dumps(HIST, sort_keys=True)
    plan_artifacts = [m for m in history if (m.get("artifact") or {}).get("type") == "execution_plan"]
    assert [m["artifact"]["data"]["scorecard_id"] for m in plan_artifacts] == [card_id]
    assert plan_artifacts[0]["artifact"]["data"]["tasks"] == plan["tasks"]
    assert len(history) == len(HIST) + 1
    assert row.scenarios_json == td_before, "registering an artifact never edits the plan"
    kinds = [c["change"] for c in _project(report, "t-shared")[0]["changes"]]
    assert sorted(kinds) == ["register_artifact", "remove_orphan_artifact"]


def test_an_artifact_of_another_option_with_the_same_tasks_is_kept(team, tmp_path):
    owner, org = team["users"]["owner"], team["org"]
    card_id = team["projects"]["owner"][1]
    _add_option(owner, org, "t-shared", "t-shared-beta", "Beta Logistics Option")
    same_tasks = [{"id": "t1", "title": "Kickoff", "status": "todo"}]
    a = dict(_plan("x", key=card_id), tasks=same_tasks)
    b = dict(_plan("x", key="t-shared-beta"), tasks=same_tasks)
    beta_artifact = _artifact("t-shared-beta", "Kickoff")
    _set_project("t-shared", owner, by_card={card_id: a, "t-shared-beta": b},
                 history=list(HIST) + [beta_artifact])

    _write(tmp_path)

    history = _row("t-shared", owner).payload["chat_history"]
    ids = [m["artifact"]["data"]["scorecard_id"] for m in history if m.get("artifact")]
    assert ids == ["t-shared-beta", card_id]
    assert history[len(HIST)] == beta_artifact


# 6 ---------------------------------------------------------------------------

def test_a_dry_run_writes_nothing_and_reports_what_would_change(team):
    owner = team["users"]["owner"]
    card_id = team["projects"]["owner"][1]
    _seed_populated_plan("t-shared", card_id, owner)
    before = _project_state("t-shared")

    report = backfill_legacy_plans()

    assert report["mode"] == "dry_run"
    assert _project_state("t-shared") == before
    project = _project(report, "t-shared")[0]
    assert project["status"] == "change"
    kinds = sorted(c["change"] for c in project["changes"])
    assert kinds == ["register_artifact", "rekey", "remove_orphan_artifact"]
    assert report["counts"]["rows_changed"] == 1


def test_the_cli_is_a_dry_run_by_default_and_a_write_needs_a_before_image(app, team):
    owner = team["users"]["owner"]
    _seed_populated_plan("t-shared", team["projects"]["owner"][1], owner)
    before = _project_state("t-shared")
    runner = app.test_cli_runner()

    result = runner.invoke(args=["legacy-plans", "backfill"])
    assert result.exit_code == 0, result.output
    assert json.loads(result.output)["mode"] == "dry_run"
    assert _project_state("t-shared") == before

    refused = runner.invoke(args=["legacy-plans", "backfill", "--write"])
    assert refused.exit_code != 0
    assert _project_state("t-shared") == before


# 7 ---------------------------------------------------------------------------

def test_a_concurrent_edit_skips_the_row_and_loses_nothing(team, tmp_path, monkeypatch):
    from app import legacy_plan_backfill as job
    from app.scenarios_store import save_project_scenarios_data

    owner, editor = team["users"]["owner"], team["users"]["editor"]
    card_id = team["projects"]["owner"][1]
    _seed_populated_plan("t-shared", card_id, owner)
    original = job._plan_row

    def _plan_then_teammate_edits(row):
        entry = original(row)
        if str(row.session_id) == "t-shared":
            def _edit(td):
                td["teammate_note"] = "edited during the job"
                return td
            save_project_scenarios_data(editor.id, "t-shared", updater=_edit)
        return entry

    monkeypatch.setattr(job, "_plan_row", _plan_then_teammate_edits)
    report, path = _write(tmp_path)

    td = _row("t-shared", owner).scenarios_json
    assert td["teammate_note"] == "edited during the job"
    assert sorted(td["wbs_by_scorecard"]) == ["stale-id"], "the job's change was not applied"
    project = _project(report, "t-shared")[0]
    assert project["status"] == "skipped"
    assert {"case": "changed_during_job"} in project["reported"]
    assert report["counts"]["rows_conflicted"] == 1
    lines = [json.loads(line) for line in path.read_text().splitlines()]
    assert [line["type"] for line in lines] == ["before", "not_written"]


# 8 ---------------------------------------------------------------------------

def test_rollback_restores_before_images_and_refuses_rows_edited_since(team, tmp_path):
    from app.scenarios_store import save_project_scenarios_data

    owner = team["users"]["owner"]
    shared_card = team["projects"]["owner"][1]
    demoted_card = team["projects"]["creator-now-viewer"][1]
    _seed_populated_plan("t-shared", shared_card, owner)
    demoted = team["users"]["creator-now-viewer"]
    _seed_populated_plan_for(demoted, owner, "t-demoted", demoted_card)
    shared_before = _content("t-shared")

    report, path = _write(tmp_path)
    assert report["counts"]["rows_changed"] == 2
    assert _content("t-shared") != shared_before

    def _edit(td):
        td["later_edit"] = True
        return td
    save_project_scenarios_data(owner.id, "t-demoted", updater=_edit)
    demoted_after_edit = _content("t-demoted")

    preview = rollback_legacy_plans(str(path))
    assert preview["restored"] == [] and len(preview["would_restore"]) == 1
    assert _content("t-demoted") == demoted_after_edit

    result = rollback_legacy_plans(str(path), write=True)

    assert _content("t-shared") == shared_before
    assert [r["row_id"] for r in result["edited_since"]] == [_row("t-demoted").id]
    assert _content("t-demoted") == demoted_after_edit
    again = rollback_legacy_plans(str(path), write=True)
    assert again["restored"] == []
    assert _content("t-shared") == shared_before


def _seed_populated_plan_for(creator, owner, thread_id, card_id):
    """The P2b legacy-plan fixture on a project whose creator is now a viewer:
    written by the organization owner, who may still write it."""
    from app.scenarios_store import save_project_scenarios_data

    plan = _plan(f"Kickoff for {OPTION_NAME}", key="stale-id")

    def _populate(td):
        td["wbs_by_scorecard"] = {"stale-id": plan}
        td["project_wbs"] = plan
        return td

    row = _row(thread_id, creator)
    from app.scenarios_store import ScenariosData
    source = ScenariosData()
    source[thread_id] = copy.deepcopy(row.scenarios_json or {})
    source.remember(thread_id, row)
    save_project_scenarios_data(owner.id, thread_id, source=source, updater=_populate)
    _db.session.expire_all()


def _content(thread_id):
    row = _row(thread_id)
    return (json.dumps(row.scenarios_json, sort_keys=True),
            json.dumps((row.payload or {}).get("chat_history"), sort_keys=True))


# 9 ---------------------------------------------------------------------------

@pytest.mark.parametrize("sequence", ["plan-and-chat", "workspace", "scenarios"])
def test_owner_responses_after_the_backfill_match_p2b_apart_from_revisions(
    client, team, tmp_path, monkeypatch, sequence,
):
    from tests.journeys import test_p2b_owner_compatibility as compat

    expected = json.loads(compat.BASELINE.read_text())[sequence]

    def _seed_then_backfill(thread_id, card_id, owner):
        _seed_populated_plan(thread_id, card_id, owner)
        _write(tmp_path)

    monkeypatch.setattr(compat, "_seed_populated_plan", _seed_then_backfill)
    if sequence != "plan-and-chat":
        _write(tmp_path)
    actual = compat.SEQUENCES[sequence](client, team)

    def _without_revisions(node):
        if isinstance(node, dict):
            return {k: _without_revisions(v) for k, v in node.items() if k != "revision"}
        if isinstance(node, list):
            return [_without_revisions(v) for v in node]
        return node

    def _strip(text):
        return re.sub(r'"revision":\s*\d+', '"revision":"<r>"', text)

    assert sorted(actual) == sorted(expected)
    for key in sorted(expected):
        p2a_status, p2a_body = expected[key]
        status, body = actual[key]
        assert status == p2a_status, (sequence, key)
        approved = {
            path: values
            for path, values in compat.APPROVED_DIFFERENCES.get(f"{sequence}/{key}", {}).items()
            if path != "revision"
        }
        if not approved:
            # Normalized bodies are compared as text (they carry placeholders).
            assert _strip(body) == _strip(p2a_body), (sequence, key)
            continue
        p2b_doc = json.loads(p2a_body)
        for path, (_p2a_value, p2b_value) in approved.items():
            compat._set_path(p2b_doc, path, p2b_value)
        assert _without_revisions(json.loads(body)) == _without_revisions(p2b_doc), (sequence, key)


# 10 --------------------------------------------------------------------------

def test_only_canonical_rows_are_written_no_row_is_created_and_scope_holds(team, tmp_path):
    owner, editor, outsider = (team["users"][k] for k in ("owner", "editor", "other-org"))
    card_id = team["projects"]["owner"][1]
    _seed_populated_plan("t-shared", card_id, owner)
    # A later same-id row (a historical fork) holding its own legacy plan.
    fork = UserSession(
        user_id=editor.id, session_id="t-shared", name="Fork", organization_id=team["org"].id,
        created_by_user_id=editor.id, revision=1,
        payload={"session_id": "t-shared", "chat_history": []},
        scenarios_json={"wbs_by_scorecard": {"stale-id": _plan(f"Kickoff for {OPTION_NAME}", key="stale-id")}},
    )
    _db.session.add(fork)
    # Another organization's project with a legacy plan.
    _seed_outsider_project(outsider)
    _db.session.commit()
    fork_id = fork.id
    fork_before = json.dumps(fork.scenarios_json, sort_keys=True)
    outsider_before = _project_state("t-outsider")
    row_count = UserSession.query.count()

    report, _ = _write(tmp_path, organization_id=team["org"].id)

    _db.session.expire_all()
    assert UserSession.query.count() == row_count
    fork_row = _db.session.get(UserSession, fork_id)
    assert json.dumps(fork_row.scenarios_json, sort_keys=True) == fork_before
    assert int(fork_row.revision) == 1
    assert {"case": "not_canonical_row"} in [
        r for p in report["projects"] if p["row_id"] == fork_id for r in p["reported"]
    ]
    assert _project_state("t-outsider") == outsider_before
    assert not _project(report, "t-outsider")
    canonical = _row("t-shared", owner).scenarios_json["wbs_by_scorecard"]
    assert sorted(canonical) == [card_id]


def _seed_outsider_project(outsider):
    from app.routes.sessions import save_user_sessions
    from app.scenarios_store import save_project_scenarios_data

    assert save_user_sessions(outsider.id, {"t-outsider": {
        "session_id": "t-outsider", "user_id": outsider.id, "name": "Elsewhere",
        "status": "in_progress", "chat_history": [],
        "result": {"id": "o-card", "name": "Outsider Vendor Choice", "jaspen_score": 50},
    }})
    save_project_scenarios_data(outsider.id, "t-outsider", {
        "wbs_by_scorecard": {"stale-o": _plan("Kickoff for Outsider Vendor Choice", key="stale-o")},
    })


# 11 --------------------------------------------------------------------------

def _five_lookups(owner, thread_id, option_id):
    """Each lookup exactly as its surface calls it."""
    from app.decision_records import execution_option_key
    from app.pm_sync.service import get_plan
    from app.routes import ai_agent, connectors, strategy
    from app.routes.sessions import load_sessions_for_thread

    _db.session.expire_all()
    td = strategy._thread_scenarios(owner.id, thread_id).get(thread_id) or {}
    sessions = load_sessions_for_thread(owner, thread_id) or {}
    candidates = strategy._thread_plan_candidates(sessions, td, user_id=owner.id, thread_id=thread_id)
    _key, workspace = strategy._resolve_option_plan(td, option_id, candidates)
    export_and_email = strategy._resolve_thread_wbs(td, option_id)
    _skey, session = strategy._resolve_session_entry(sessions, thread_id)
    cards = ai_agent._collect_session_scorecards(session, user_id=owner.id, thread_id=thread_id)
    card = next(c for c in cards if str(c.get("id")) == option_id)
    _cid, chat = ai_agent._resolve_option_plan(
        owner.id, thread_id, cards, execution_option_key(card), None, thread_data=td,
    )
    try:
        jira, _jira_key = get_plan(owner.id, thread_id, option_id)
    except LookupError:
        jira = None
    _all, _thread, thread_level = connectors._load_thread_wbs(owner.id, thread_id)
    return {
        "workspace": workspace, "export_and_email": export_and_email, "chat": chat,
        "jira": jira, "connectors_active_plan": thread_level,
    }


@pytest.mark.parametrize("fixture", ["stale-key", "clean"])
def test_after_the_job_the_five_lookups_return_the_same_plan(team, tmp_path, fixture):
    owner = team["users"]["owner"]
    card_id = team["projects"]["owner"][1]
    if fixture == "stale-key":
        _seed_populated_plan("t-shared", card_id, owner)
        before = _five_lookups(owner, "t-shared", card_id)
        # Step 0 evidence: before the job only the workspace finds the plan.
        assert before["workspace"] is not None
        assert before["export_and_email"] is None and before["chat"] is None
    else:
        plan = _plan(f"Kickoff for {OPTION_NAME}", key=card_id, sc_name=OPTION_NAME)
        _set_project("t-shared", owner, by_card={card_id: plan}, project_wbs=plan, active=card_id,
                     history=list(HIST) + [_artifact(card_id, f"Kickoff for {OPTION_NAME}")])

    _write(tmp_path)

    after = _five_lookups(owner, "t-shared", card_id)
    stored = _row("t-shared", owner).scenarios_json["wbs_by_scorecard"][card_id]
    for surface, plan in after.items():
        assert plan == stored, surface


# --- Independent audit remediation (C1 to C3) --------------------------------

def _binding(owner, org, thread_id, plan_key):
    from app.models_pm_sync import PmSyncBinding

    binding = PmSyncBinding(
        user_id=owner.id, organization_id=org.id, thread_id=thread_id, plan_key=plan_key,
        connector_id="jira_sync", external_container_id="JPT",
        external_container_url="https://example.atlassian.net/browse/JPT",
        mode="two_way", conflict_policy="prefer_external", policy_set_by_user_id=owner.id,
        field_policy_overrides={}, config={"task_issue_type": "Task"}, user_map={}, status="active",
    )
    _db.session.add(binding)
    _db.session.commit()
    return binding


def _pull_back(binding):
    """What a Jira pull does with a task commitment: persist it to the plan
    the binding resolves."""
    from app.pm_sync.service import _persist_task_commitments, get_plan

    plan, _key = get_plan(binding.user_id, binding.thread_id, binding.plan_key, binding=binding)
    plan = copy.deepcopy(plan)
    plan["tasks"][0]["commitment"] = {"owner": "Jira", "due": "2026-12-01"}
    _persist_task_commitments(binding, plan)
    _db.session.expire_all()


@pytest.mark.parametrize("case", ["active-id-is-the-stale-key", "no-active-id-mirror-fallback"])
def test_c1_a_stale_key_a_sync_binding_uses_is_never_moved(team, tmp_path, case):
    from app.pm_sync.service import get_plan

    owner, org = team["users"]["owner"], team["org"]
    card_id = team["projects"]["owner"][1]
    stale = _plan(f"Kickoff for {OPTION_NAME}", key="stale-id")
    if case == "active-id-is-the-stale-key":
        _set_project("t-shared", owner, by_card={"stale-id": stale}, project_wbs=stale,
                     active="stale-id", history=list(HIST))
        binding = _binding(owner, org, "t-shared", "stale-id")
        target = ("wbs_by_scorecard", "stale-id")
    else:
        # Bound to the option id with no plan of its own: get_plan falls back
        # to the thread-level mirror, which holds the stale-key plan.
        _set_project("t-shared", owner, by_card={"stale-id": stale}, project_wbs=stale,
                     history=list(HIST))
        binding = _binding(owner, org, "t-shared", card_id)
        target = ("project_wbs",)
    resolved_before = get_plan(owner.id, "t-shared", binding.plan_key, binding=binding)
    before = _project_state("t-shared")

    report, _ = _write(tmp_path)

    assert _project_state("t-shared") == before, "a bound plan is not migrated"
    reported = _project(report, "t-shared")[0]["reported"]
    assert any(r["case"] == "stale_plan_has_sync_binding" and r["key"] == "stale-id"
               for r in reported), reported
    assert get_plan(owner.id, "t-shared", binding.plan_key, binding=binding) == resolved_before
    _pull_back(binding)
    td = _row("t-shared", owner).scenarios_json
    node = td
    for part in target:
        node = node[part]
    assert node["tasks"][0]["commitment"] == {"owner": "Jira", "due": "2026-12-01"}
    assert binding.plan_key == ("stale-id" if case.startswith("active") else card_id)


def _teammate_writes_payload(thread_id, owner):
    """A teammate's write that does not move the revision, on its own
    connection (the team comment route and visibility edits save the payload
    without the revision compare-and-swap)."""
    row = _row(thread_id, owner)
    payload = copy.deepcopy(row.payload)
    payload["comments"] = [{"id": "cmt_mid", "body": "Teammate comment mid-job"}]
    payload["activity"] = [{"type": "comment_added", "comment_id": "cmt_mid"}]
    payload["visibility_note"] = "changed by a teammate"
    table = UserSession.__table__
    with _db.engine.begin() as connection:
        connection.execute(
            table.update().where(table.c.id == row.id).values(payload=payload)
        )
    return row.id


def test_c2_a_teammate_comment_written_mid_job_is_kept(team, tmp_path, monkeypatch):
    from app import legacy_plan_backfill as job

    owner = team["users"]["owner"]
    card_id = team["projects"]["owner"][1]
    _seed_populated_plan("t-shared", card_id, owner)
    original = job._plan_row

    def _plan_then_comment(row):
        entry = original(row)
        if str(row.session_id) == "t-shared":
            _teammate_writes_payload("t-shared", owner)
        return entry

    monkeypatch.setattr(job, "_plan_row", _plan_then_comment)
    report, _path = _write(tmp_path)

    row = _row("t-shared", owner)
    assert row.payload["comments"] == [{"id": "cmt_mid", "body": "Teammate comment mid-job"}]
    assert row.payload["activity"] == [{"type": "comment_added", "comment_id": "cmt_mid"}]
    assert row.payload["visibility_note"] == "changed by a teammate"
    project = _project(report, "t-shared")[0]
    assert project["status"] == "written"
    ids = [m["artifact"]["data"]["scorecard_id"] for m in row.payload["chat_history"] if m.get("artifact")]
    assert ids == [card_id]
    assert sorted(row.scenarios_json["wbs_by_scorecard"]) == [card_id]


def test_c2_a_chat_change_written_mid_job_without_a_revision_is_refused(team, tmp_path, monkeypatch):
    from app import legacy_plan_backfill as job

    owner = team["users"]["owner"]
    card_id = team["projects"]["owner"][1]
    _seed_populated_plan("t-shared", card_id, owner)
    original = job._plan_row

    def _plan_then_chat(row):
        entry = original(row)
        if str(row.session_id) == "t-shared":
            fresh = _row("t-shared", owner)
            payload = copy.deepcopy(fresh.payload)
            payload["chat_history"] = payload["chat_history"] + [{"role": "user", "content": "new"}]
            table = UserSession.__table__
            with _db.engine.begin() as connection:
                connection.execute(table.update().where(table.c.id == fresh.id).values(payload=payload))
        return entry

    monkeypatch.setattr(job, "_plan_row", _plan_then_chat)
    report, _ = _write(tmp_path)

    row = _row("t-shared", owner)
    assert row.payload["chat_history"][-1] == {"role": "user", "content": "new"}
    assert sorted(row.scenarios_json["wbs_by_scorecard"]) == ["stale-id"]
    assert {"case": "changed_during_job"} in _project(report, "t-shared")[0]["reported"]


def test_c2_rollback_keeps_a_teammate_comment_written_after_the_job(team, tmp_path):
    owner = team["users"]["owner"]
    card_id = team["projects"]["owner"][1]
    _seed_populated_plan("t-shared", card_id, owner)
    seeded = _row("t-shared", owner)
    seeded_scenarios = json.dumps(seeded.scenarios_json, sort_keys=True)
    seeded_history = json.dumps(seeded.payload["chat_history"], sort_keys=True)
    _report, path = _write(tmp_path)
    _teammate_writes_payload("t-shared", owner)

    result = rollback_legacy_plans(str(path), write=True)

    row = _row("t-shared", owner)
    assert result["restored"] == [row.id]
    assert json.dumps(row.scenarios_json, sort_keys=True) == seeded_scenarios
    assert json.dumps(row.payload["chat_history"], sort_keys=True) == seeded_history
    assert row.payload["comments"] == [{"id": "cmt_mid", "body": "Teammate comment mid-job"}]


def _former_member_project(team, *, org_owner_can_edit=True):
    """A project created by a member who has since left the organization."""
    from app.models import OrganizationMember

    owner, org = team["users"]["owner"], team["org"]
    editor = team["users"]["editor"]
    from tests.journeys.test_p2b_workspace_project_access import _seed_project
    card_id = _seed_project(editor, org, "t-former")
    _seed_populated_plan("t-former", card_id, editor)
    membership = OrganizationMember.query.filter_by(organization_id=org.id, user_id=editor.id).one()
    membership.status = "removed"
    if not org_owner_can_edit:
        OrganizationMember.query.filter_by(organization_id=org.id, user_id=owner.id).one().role = "viewer"
    _db.session.commit()
    _db.session.expire_all()
    return editor, card_id


def _database_state():
    from app.models import OrgAccessShadowEvent

    _db.session.expire_all()
    sessions = [
        (r.id, int(r.revision or 1), r.last_edited_by_user_id,
         json.dumps(r.payload, sort_keys=True, default=str),
         json.dumps(r.scenarios_json, sort_keys=True, default=str))
        for r in UserSession.query.order_by(UserSession.id).all()
    ]
    return sessions, OrgAccessShadowEvent.query.count()


def test_c3_a_former_member_is_never_the_writer_the_org_owner_is(team, tmp_path):
    from app import org_access

    owner = team["users"]["owner"]
    former, card_id = _former_member_project(team)
    org_access.reset_dedup()
    report = backfill_legacy_plans()
    project = _project(report, "t-former")[0]
    assert project["writer_user_id"] == str(owner.id)

    _write(tmp_path)

    row = _row("t-former")
    assert row.last_edited_by_user_id == str(owner.id)
    assert sorted(row.scenarios_json["wbs_by_scorecard"]) == [card_id]
    assert str(former.id) != row.last_edited_by_user_id


def test_c3_no_eligible_writer_is_reported_and_changes_nothing(team, tmp_path):
    from app import org_access

    _former_member_project(team, org_owner_can_edit=False)
    org_access.reset_dedup()
    before = _project_state("t-former")

    report, _ = _write(tmp_path)

    assert _project_state("t-former") == before
    assert {"case": "no_member_may_write"} in _project(report, "t-former")[0]["reported"]


def test_c3_a_dry_run_writes_nothing_anywhere_including_shadow_events(team):
    from app import org_access

    _former_member_project(team)
    _seed_populated_plan("t-shared", team["projects"]["owner"][1], team["users"]["owner"])
    org_access.reset_dedup()
    before = _database_state()

    report = backfill_legacy_plans()

    assert report["counts"]["rows_changed"] >= 2
    assert _database_state() == before
