import copy
import json

from app.routes.sessions import save_user_sessions
from app.scorecards import upsert_scorecard
from tests.test_decision_flow_stabilization import modules


CARDS = [
    {"id": "card-denver", "option_key": "option-denver", "project_name": "Denver Water", "jaspen_score": 70},
    {"id": "card-adams", "option_key": "option-adams", "project_name": "Adams County", "jaspen_score": 65},
    {"id": "card-cdot", "option_key": "option-cdot", "project_name": "CDOT bridge rehab", "jaspen_score": 80},
]


def _seed(db, user, thread_id):
    result = {**CARDS[0], "_baseline_scorecard": CARDS[0], "scorecard_snapshots": CARDS}
    assert save_user_sessions(user.id, {thread_id: {
        "session_id": thread_id,
        "user_id": user.id,
        "name": "SMOKE TEST 5",
        "status": "completed",
        "result": result,
        "chat_history": [],
        "scorecard_queue": [],
    }})
    for card in CARDS:
        upsert_scorecard(user_id=user.id, thread_id=thread_id, payload=card)
    db.session.commit()


def _task(task_id, title, due_date):
    return {
        "id": task_id,
        "title": title,
        "description": f"Deliver {title}",
        "phase": "Delivery",
        "status": "todo",
        "priority": "high",
        "owner": "Project Manager",
        "suggested_role": "Project Manager",
        "due_date": due_date,
        "estimated_days": 3,
        "timeline_days": 3,
        "depends_on": [],
    }


def _store_plans(user, thread_id, plans, active_scorecard_id="card-denver"):
    strategy, _agent = modules()
    all_data = strategy._load_scenarios(user.id)
    entry = strategy._thread_entry()
    entry["wbs_by_scorecard"] = copy.deepcopy(plans)
    if plans:
        entry["project_wbs"] = copy.deepcopy(next(reversed(plans.values())))
    entry["active_execution_scorecard_id"] = active_scorecard_id
    all_data[thread_id] = entry
    assert strategy._save_project_scenarios(user.id, all_data, thread_id)


def _plans(user, thread_id):
    strategy, _agent = modules()
    return strategy._load_scenarios(user.id)[thread_id]["wbs_by_scorecard"]


def _plan(scorecard_id, task):
    return {
        "name": f"{scorecard_id} plan",
        "scorecard_id": scorecard_id,
        "created_at": "2026-11-01T10:00:00",
        "tasks": [task],
    }


def test_explicit_option_key_updates_named_plan_while_another_option_is_open(app, db, test_user):
    _strategy, agent = modules()
    thread_id = "plan-by-option-update"
    _seed(db, test_user, thread_id)
    cdot_task = _task("cdot-task", "Submit traffic control plan", "2026-11-20")
    _store_plans(test_user, thread_id, {
        "card-adams": _plan("card-adams", _task("adams-task", "Price Adams bid", "2026-11-18")),
        "card-cdot": _plan("card-cdot", cdot_task),
    })

    result = agent._execute_mutation_tool(
        "update_wbs_task",
        {"option_key": "option-cdot", "task_id": "cdot-task", "field": "due_date", "new_value": "2026-11-25"},
        user=test_user,
        user_id=test_user.id,
        thread_id=thread_id,
        view_context={"active_scorecard_id": "card-denver"},
    )

    assert result["ok"] is True, result
    stored = _plans(test_user, thread_id)
    assert "card-denver" not in stored
    assert stored["card-adams"]["tasks"][0]["due_date"] == "2026-11-18"
    changed = stored["card-cdot"]["tasks"][0]
    assert changed["due_date"] == "2026-11-25"
    assert changed["field_updated_at"]["due_date"]
    assert any(item["field"] == "due_date" for item in changed["history"])


def test_omitting_option_key_keeps_open_option_resolution(app, db, test_user):
    _strategy, agent = modules()
    thread_id = "plan-by-option-legacy"
    _seed(db, test_user, thread_id)
    _store_plans(test_user, thread_id, {
        "card-cdot": _plan("card-cdot", _task("cdot-task", "Submit traffic control plan", "2026-11-20")),
    })
    before = copy.deepcopy(_plans(test_user, thread_id))

    result = agent._execute_mutation_tool(
        "update_wbs_task",
        {"task_id": "cdot-task", "field": "due_date", "new_value": "2026-11-25"},
        user=test_user,
        user_id=test_user.id,
        thread_id=thread_id,
        view_context={"active_scorecard_id": "card-denver"},
    )

    assert result["ok"] is False
    assert result["code"] == "task_not_found"
    assert _plans(test_user, thread_id) == before


def test_unknown_option_key_returns_error_without_write(app, db, test_user):
    _strategy, agent = modules()
    thread_id = "plan-by-option-unknown"
    _seed(db, test_user, thread_id)
    _store_plans(test_user, thread_id, {
        "card-cdot": _plan("card-cdot", _task("cdot-task", "Submit traffic control plan", "2026-11-20")),
    })
    before = copy.deepcopy(_plans(test_user, thread_id))

    result = agent._execute_mutation_tool(
        "update_wbs_task",
        {"option_key": "option-unknown", "task_id": "cdot-task", "field": "due_date", "new_value": "2026-11-25"},
        user=test_user,
        user_id=test_user.id,
        thread_id=thread_id,
        view_context={"active_scorecard_id": "card-denver"},
    )

    assert result == {
        "ok": False,
        "code": "option_not_found",
        "error": "That option is not part of this session. Nothing changed.",
    }
    assert _plans(test_user, thread_id) == before


def test_prompt_lists_each_plan_under_its_option_without_mixing_tasks(app, db, test_user):
    _strategy, agent = modules()
    thread_id = "plan-by-option-prompt"
    _seed(db, test_user, thread_id)
    _store_plans(test_user, thread_id, {
        "card-denver": _plan("card-denver", _task("denver-task", "Denver permit", "2026-11-19")),
        "card-adams": _plan("card-adams", _task("adams-task", "Price Adams bid", "2026-11-18")),
        "card-cdot": _plan("card-cdot", _task("cdot-task", "Submit traffic control plan", "2026-11-20")),
    })

    suffix = agent._wbs_content_prompt_suffix(test_user.id, thread_id, "card-denver")
    payload = json.loads(suffix.split("]\n", 1)[1])

    assert [plan["option_key"] for plan in payload] == ["option-denver", "option-adams", "option-cdot"]
    tasks_by_option = {
        plan["option_key"]: {task["id"] for task in plan["tasks"]}
        for plan in payload
    }
    assert tasks_by_option == {
        "option-denver": {"denver-task"},
        "option-adams": {"adams-task"},
        "option-cdot": {"cdot-task"},
    }
    assert "status" in payload[0]["tasks"][0] and "priority" in payload[0]["tasks"][0]
    assert "status" not in payload[1]["tasks"][0] and "priority" not in payload[1]["tasks"][0]


def test_prompt_includes_only_existing_cdot_plan_while_denver_is_open(app, db, test_user):
    _strategy, agent = modules()
    thread_id = "plan-by-option-smoke-five"
    _seed(db, test_user, thread_id)
    _store_plans(test_user, thread_id, {
        "card-cdot": _plan("card-cdot", _task("cdot-task", "Submit traffic control plan", "2026-11-20")),
    })

    suffix = agent._wbs_content_prompt_suffix(test_user.id, thread_id, "card-denver")
    payload = json.loads(suffix.split("]\n", 1)[1])

    assert [(plan["option_name"], plan["option_key"]) for plan in payload] == [
        ("CDOT bridge rehab", "option-cdot"),
    ]
    assert payload[0]["tasks"][0]["id"] == "cdot-task"


def test_plan_tool_schemas_accept_the_same_optional_option_key(app):
    _strategy, agent = modules()
    tools = {
        item["name"]: item
        for item in agent._anthropic_tool_definitions(enable_mutation_tools=True)
    }
    for name in ("update_wbs_task", "add_wbs_task", "remove_wbs_task", "set_execution_start_date"):
        option = tools[name]["input_schema"]["properties"]["option_key"]
        assert option == {
            "type": "string",
            "description": "Option key from the execution-plan context; omit for the open plan.",
        }
        assert "option_key" not in tools[name]["input_schema"].get("required", [])


def test_legacy_thread_level_plan_stays_visible_and_editable(app, db, test_user):
    strategy, agent = modules()
    thread_id = "plan-by-option-legacy"
    _seed(db, test_user, thread_id)
    all_data = strategy._load_scenarios(test_user.id)
    entry = strategy._thread_entry()
    entry["project_wbs"] = _plan("legacy", _task("legacy-task", "Legacy task", "2026-11-12"))
    all_data[thread_id] = entry
    assert strategy._save_project_scenarios(test_user.id, all_data, thread_id)

    suffix = agent._wbs_content_prompt_suffix(test_user.id, thread_id, None)
    payload = json.loads(suffix.split("]\n", 1)[1])
    assert len(payload) == 1
    assert payload[0]["option_key"] is None
    assert payload[0]["open_in_view"] is True
    assert payload[0]["tasks"][0]["id"] == "legacy-task"

    with app.test_request_context():
        result = agent._execute_mutation_tool(
            "update_wbs_task",
            {"task_id": "legacy-task", "field": "due_date", "new_value": "2026-11-15"},
            user=test_user, user_id=test_user.id, thread_id=thread_id, user_message="move it",
        )
    assert result["ok"] is True
    saved = strategy._load_scenarios(test_user.id)[thread_id]["project_wbs"]["tasks"][0]
    assert saved["due_date"] == "2026-11-15"
