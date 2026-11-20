"""P5c: every assistant entrance builds context from one authorized project."""

import ast
import inspect
from dataclasses import replace

import pytest

from app.ai_context import build_shared_assistant_context
from app.session_access import SessionNotFound
from tests.journeys.test_turn_project_tools import SAME_ID, two_orgs  # noqa: F401


def _agent():
    from app.routes import ai_agent
    return ai_agent


def _context(user):
    project = _agent()._build_turn_project(user, SAME_ID)
    return build_shared_assistant_context(
        user,
        SAME_ID,
        sessions=project.sessions(),
        project=project,
        scenarios=project.scenarios(),
        view_context={"current_view": "workspace"},
    )


def test_shared_context_keeps_same_thread_id_inside_its_organization(app, db, two_orgs):
    alpha = _context(two_orgs["consultant"])
    bravo = _context(two_orgs["bravo_owner"])

    assert alpha.organization_id == str(two_orgs["alpha"].id)
    assert bravo.organization_id == str(two_orgs["bravo"].id)
    assert alpha.scorecard_result["id"] == "card-alpha"
    assert bravo.scorecard_result["id"] == "card-bravo"
    assert "Bravo Secret Option" not in str(alpha.scorecard_result)
    assert "Alpha Harbor Option" not in str(bravo.scorecard_result)
    assert "Bravo plan" not in str(alpha.project_data)
    assert "Bravo plan" in str(bravo.project_data)


def test_shared_context_rejects_a_row_from_another_organization(app, db, two_orgs):
    from app.models import UserSession

    user = two_orgs["consultant"]
    project = _agent()._build_turn_project(user, SAME_ID)
    bravo_row = UserSession.query.filter_by(
        session_id=SAME_ID, organization_id=two_orgs["bravo"].id,
    ).one()

    with pytest.raises(SessionNotFound):
        build_shared_assistant_context(
            user,
            SAME_ID,
            sessions=project.sessions(),
            project=project,
            project_row=bravo_row,
        )


def test_shared_context_preserves_missing_plan_and_existing_empty_plan(app, db, two_orgs):
    context = _context(two_orgs["consultant"])

    assert replace(context, project_data={}).execution_plan is None
    assert replace(context, project_data={"project_wbs": {}}).execution_plan == {}


def test_all_three_assistant_entrances_call_the_shared_builder():
    from app.routes import ai_agent, strategy

    expected = {
        ai_agent._build_shared_system_prompt,
        strategy.scorecard_assistant,
        strategy.execution_assistant,
    }
    for function in expected:
        tree = ast.parse(inspect.getsource(function))
        calls = {
            node.func.id
            for node in ast.walk(tree)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
        }
        assert "build_shared_assistant_context" in calls, function.__name__


def test_main_conversation_builds_its_prompt_from_the_authorized_context(app, db, two_orgs):
    agent = _agent()
    user = two_orgs["consultant"]
    project = agent._build_turn_project(user, SAME_ID)
    session = project.sessions()[SAME_ID]
    prompt = agent._build_shared_system_prompt(
        session=session,
        chat_history=session["chat_history"],
        context_summary_text="",
        intake_context={},
        view_context={"current_view": "workspace"},
        readiness={},
        user=user,
        user_id=user.id,
        thread_id=SAME_ID,
        project=project,
    )

    assert "Alpha Harbor Option" in prompt
    assert "Bravo Secret Option" not in prompt
