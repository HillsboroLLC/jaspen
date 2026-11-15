"""H-2e-4: permanent seven-role net for the routes H-2R probed but nobody tested.

H-2R section E listed routes that matched the organization rule in its probes
but had no permanent test:

1. ai_agent ``/threads/<id>``: GET, PATCH, touch, messages, usage, levers,
   knowledge refresh and message feedback;
2. archive (DELETE), purge and restore, for viewer, creator-now-viewer and
   former member;
3. routes missing everywhere: analyze-data, pm_sync preview and bindings,
   connectors import and sync, decision shares, decision-record thread routes
   (all covered since by the H-2e-1 to H-2e-3 and P2e-C1 files, see
   ``COVERED_ELSEWHERE``), Decision Impact routes and team project routes
   (covered here).

Each cell runs for the seven roles of the acceptance matrix (section 4) and
asserts the status; a content marker present for allowed reads and absent
for refusals; zero model, HTTP and email calls on refusal; exactly one
project row afterwards; attribution unchanged except
``last_edited_by_user_id``. Former-member cells run in enforce mode; report
mode (today's default, SEC-06) is pinned separately with its
``org_access_shadow_events`` row.

Also covered: the same project id in two organizations, a member switching
their active organization, conflicting project ids in one request (body
``thread_id`` vs ``session_id`` vs ``X-Session-ID``), and unknown ids.

This file changes no application code. A cell that disagrees with the matrix
is marked strict xfail with the route and a one-line reason.

Journeys (blueprint acceptance matrix): B2, B6 to B9, section 4.
"""

import json
import uuid

import pytest

from app import db as _db
from app.models import OrganizationMember, UserSession
from tests.journeys.test_conversation_turn_lifecycle import _headers, _mk_org, _mk_user, _settle_meter
from tests.journeys.test_p2b_workspace_project_access import (  # noqa: F401 (fixtures)
    MARKER,
    _no_rate_limits,
    _project_state,
    _seed_project,
    solo,
    team,
)
from tests.journeys.test_p2c_distribution_project_access import dist  # noqa: F401 (fixture)

ACTORS = ["owner", "administrator", "editor", "viewer", "creator-now-viewer",
          "former-member", "other-org"]
READERS = {"owner", "administrator", "editor", "viewer", "creator-now-viewer"}
WRITERS = {"owner", "administrator", "editor"}
READ_ONLY = {"viewer", "creator-now-viewer"}
OUTSIDERS = {"former-member", "other-org"}
ARCHIVERS = {"owner", "administrator"}   # shared work: can_archive_session
SIGNAL_MARK = "SIGNAL-H2E4"              # what the stand-in model returns

# H-2R section E item 3 routes whose seven-role cells already exist. Not
# duplicated here; each pointer names the test that holds the cells.
COVERED_ELSEWHERE = {
    "POST /ai-agent/analyze-data (form, query; X-Session-ID ignored)":
        "test_p2e_data_upload_project_access.py::test_upload_access_matrix, "
        "::test_no_project_id_ignores_x_session_id, ::test_report_mode_former_creator_upload_is_audited",
    "GET /pm-sync/preview":
        "test_p2e_jira_plan_access.py::test_preview_follows_read_access_without_contacting_jira",
    "POST /pm-sync/bindings":
        "test_p2e_jira_plan_access.py::test_bind_and_send_requires_current_edit_role, "
        "::test_report_mode_former_creator_binding_is_allowed_and_audited",
    "pm-sync bindings by id (owner role, pause, resume)":
        "test_p2e_jira_owner_role_and_webhooks.py::test_owner_made_viewer_is_refused_before_jira_and_binding_pauses",
    "POST /connectors/threads/<id>/<connector>/import":
        "test_p2e_jira_plan_access.py::test_legacy_import_checks_access_before_external_work",
    "GET /connectors/threads/<id>/sync (readiness)":
        "test_p2e_jira_plan_access.py::test_readiness_uses_the_readable_projects_plan",
    "POST /connectors/threads/<id>/jira/sync (legacy alias)":
        "test_p2e_jira_owner_role_and_webhooks.py::test_paused_binding_never_reactivates_implicitly[legacy_alias]",
    "POST /connectors/threads/<id>/smartsheet/sync":
        "test_p2e_jira_plan_access.py::test_legacy_smartsheet_send_refuses_before_call_or_sync_lock",
    "Jira and Smartsheet webhooks (named member)":
        "test_p2e_jira_owner_role_and_webhooks.py::test_webhook_follows_the_named_members_current_role",
    "POST /decision-shares (Share with Jaspen)":
        "test_p2e_decision_sharing_and_records.py::test_teammate_scorecard_share_follows_read_access, "
        "::test_tradeoff_spans_authors_and_create_keeps_each_author",
    "POST /decision-records/from-thread/<id>":
        "test_p2e_decision_sharing_and_records.py::test_create_record_from_thread_access_matrix",
    "GET/POST /decision-records/threads/<id>/accepted-exposures":
        "test_p2e_decision_sharing_and_records.py::test_accepted_exposure_access_matrix",
    "decision-record id routes (cross-organization, orphaned)":
        "test_p2e_record_cross_org_authorization.py (all)",
    "POST /ai-agent/conversation/start, /continue, /regenerate, /undo-mutations":
        "test_conversation_turn_lifecycle.py, test_conversation_undo_access.py, test_turn_project_tools.py",
}


# --- Fixtures and recorders ---------------------------------------------------

@pytest.fixture(autouse=True)
def _enforce_for_former_members(request, monkeypatch):
    """Matrix section 4: a former member is refused in enforce mode. Report
    mode is pinned in the report-mode tests below."""
    params = getattr(getattr(request.node, "callspec", None), "params", {})
    if params.get("actor") == "former-member":
        monkeypatch.setenv("ORG_ACCESS_ENFORCEMENT", "enforce")


@pytest.fixture
def calls(monkeypatch):
    """Every external effect a project route could have: the model (all
    entry points ai_agent and strategy use), outbound HTTP (Jira, Smartsheet,
    any provider) and email. The model stand-in answers like a provider so an
    allowed request completes; HTTP and email are refused outright."""
    from app import decision_asset_email_service
    from app.routes import ai_agent, strategy

    recorded = {"model": [], "http": [], "email": []}
    signals = json.dumps({"signals": [{"id": "s1", "label": f"Signal {SIGNAL_MARK}", "captured": True}],
                          "confidence": 40})

    def _text_operation(*_args, **_kwargs):
        recorded["model"].append("text")
        return signals, {}, None

    def _operation(*_args, **_kwargs):
        recorded["model"].append("operation")
        raise RuntimeError("stand-in model: no operation expected")

    def _client(*_args, **_kwargs):
        recorded["model"].append("client")
        raise RuntimeError("stand-in model: no client expected")

    for module in (ai_agent, strategy):
        monkeypatch.setattr(module, "execute_customer_text_operation", _text_operation, raising=False)
        monkeypatch.setattr(module, "execute_customer_operation", _operation, raising=False)
        monkeypatch.setattr(module, "get_llm_client", _client, raising=False)

    import requests

    def _http(self, method, url, *args, **kwargs):
        recorded["http"].append((method, url))
        raise RuntimeError("stand-in network: no external call expected")

    monkeypatch.setattr(requests.sessions.Session, "request", _http)

    def _email_provider():
        recorded["email"].append(True)
        raise RuntimeError("stand-in email: no delivery expected")

    monkeypatch.setattr(decision_asset_email_service, "get_transactional_email_provider", _email_provider)
    return recorded


def _external(calls_):
    return {kind: list(items) for kind, items in calls_.items() if items}


def _call(client, net, actor, method, path, body=None, headers=None):
    user = net["users"][actor]
    merged = dict(_headers(net["app"], user))
    merged.update(headers or {})
    return client.open(path, method=method, headers=merged, json=body)


def _target(net, actor):
    """The project each actor acts on: the shared project; the demoted
    creator's own project; the former member's own project (so enforce mode,
    not authorship, is what refuses them)."""
    return net["projects"][actor][0]


def _rows(thread_id):
    _db.session.expire_all()
    return UserSession.query.filter_by(session_id=thread_id).order_by(UserSession.id).all()


def _attribution(thread_id):
    return [(r.id, r.user_id, r.organization_id, r.created_by_user_id) for r in _rows(thread_id)]


def _payload(thread_id):
    rows = _rows(thread_id)
    assert len(rows) == 1, f"{thread_id}: expected exactly one project row, found {len(rows)}"
    return rows[0].payload or {}


def _assert_refused(response, actor, before, thread_id, calls_, route):
    expected = 403 if actor in READ_ONLY else 404
    assert response.status_code == expected, (route, actor, response.status_code,
                                              response.get_data(as_text=True)[:300])
    assert MARKER.encode() not in response.data, (route, actor, "protected content leaked")
    assert _project_state(thread_id) == before, (route, actor, "a refused request changed the project")
    assert _external(calls_) == {}, (route, actor, _external(calls_))


def _assert_written(response, actor, attribution, thread_id, route):
    assert response.status_code == 200, (route, actor, response.status_code,
                                         response.get_data(as_text=True)[:300])
    assert _attribution(thread_id) == attribution, (route, actor, "attribution or row count changed")


@pytest.fixture
def net(dist):
    """The seven-role team (P2c's ``dist``) with a marker in every surface
    these routes read: usage, team comments and the activity feed."""
    for thread_id in ("t-shared", "t-demoted", "t-former"):
        row = _rows(thread_id)[0]
        payload = dict(row.payload or {})
        payload["usage_summary"] = {"model_type": "pluto", "input_tokens": 7, "output_tokens": 3,
                                    "total_tokens": 10, "credits_charged": 4242, "events": 1}
        payload["usage_events"] = [{"timestamp": f"usage {MARKER}", "model_type": "pluto",
                                    "input_tokens": 7, "output_tokens": 3, "total_tokens": 10,
                                    "credits_charged": 4242}]
        payload["comments"] = [{"id": "cmt_seed", "timestamp": "2026-11-01T00:00:00",
                                "author_user_id": row.user_id, "author_name": "Seed",
                                "body": f"Seed comment {MARKER}"}]
        payload["activity_feed"] = [{"id": "act_seed", "timestamp": "2026-11-01T00:00:00",
                                     "action": "seeded", "actor_user_id": row.user_id,
                                     "details": {"note": MARKER}}]
        UserSession.query.filter_by(id=row.id).update({"payload": payload}, synchronize_session=False)
    _db.session.commit()
    _db.session.expire_all()
    for thread_id in ("t-shared", "t-demoted", "t-former"):
        assert MARKER in json.dumps(_rows(thread_id)[0].payload.get("comments")), thread_id
    return dist


# --- Item 1: ai_agent /threads/<id> reads --------------------------------------

THREAD_READS = {
    "thread": ("GET", "/api/v1/ai-agent/threads/{t}", MARKER),
    "usage": ("GET", "/api/v1/ai-agent/threads/{t}/usage", MARKER),
    "levers": ("GET", "/api/v1/ai-agent/threads/{t}/levers", None),
}


@pytest.mark.parametrize("actor", ACTORS)
@pytest.mark.parametrize("route", sorted(THREAD_READS))
def test_thread_reads_follow_read_access(client, net, calls, actor, route):
    method, template, marker = THREAD_READS[route]
    thread_id = _target(net, actor)
    before = _project_state(thread_id)

    response = _call(client, net, actor, method, template.format(t=thread_id))

    if actor in READERS:
        assert response.status_code == 200, (route, actor, response.get_data(as_text=True)[:300])
        assert response.get_json()["thread_id" if route != "thread" else "thread"], (route, actor)
        if marker:
            assert marker.encode() in response.data, (route, actor, "project content missing")
    else:
        assert response.status_code == 404, (route, actor, response.status_code)
        assert MARKER.encode() not in response.data and b"4242" not in response.data, (route, actor)
    assert _project_state(thread_id) == before, (route, actor, "a read wrote the project")
    assert _external(calls) == {}, (route, actor)


# --- Item 1: ai_agent /threads/<id> writes -------------------------------------

def _thread_writes():
    return {
        "rename": ("PATCH", "/api/v1/ai-agent/threads/{t}",
                   lambda rev: {"name": "Renamed by the net", "base_revision": rev}),
        "touch": ("POST", "/api/v1/ai-agent/threads/{t}/touch", lambda rev: {}),
        "messages": ("POST", "/api/v1/ai-agent/threads/{t}/messages",
                     lambda rev: {"messages": [{"role": "user", "content": "Net note"}]}),
        "feedback": ("POST", "/api/v1/ai-agent/threads/{t}/messages/1/feedback",
                     lambda rev: {"value": "up", "note": "Useful"}),
        "knowledge-refresh": ("POST", "/api/v1/ai-agent/threads/{t}/knowledge/refresh", lambda rev: {}),
    }


def _write_effect(route, payload):
    """What an allowed write left in the project."""
    history = payload.get("chat_history") or []
    if route == "rename":
        return payload.get("name") == "Renamed by the net"
    if route == "messages":
        return history and history[-1].get("content") == "Net note"
    if route == "feedback":
        return len(history) > 1 and (history[1].get("feedback") or {}).get("value") == "up"
    if route == "knowledge-refresh":
        return SIGNAL_MARK in json.dumps(payload.get("knowledge_signals") or {})
    return True  # touch: the timestamp moves, nothing else


@pytest.mark.parametrize("actor", ACTORS)
@pytest.mark.parametrize("route", sorted(_thread_writes()))
def test_thread_writes_follow_write_access(client, net, calls, actor, route):
    method, template, body = _thread_writes()[route]
    thread_id = _target(net, actor)
    before = _project_state(thread_id)
    attribution = _attribution(thread_id)
    revision = int(_rows(thread_id)[0].revision or 1)

    response = _call(client, net, actor, method, template.format(t=thread_id), body(revision))

    if actor in WRITERS:
        _assert_written(response, actor, attribution, thread_id, route)
        payload = _payload(thread_id)
        assert _write_effect(route, payload), (route, actor, "the write did not land")
        row = _rows(thread_id)[0]
        if route != "touch":
            assert row.last_edited_by_user_id == net["users"][actor].id, (route, actor)
        assert calls["model"] == (["text"] if route == "knowledge-refresh" else []), (route, actor)
        assert not calls["http"] and not calls["email"], (route, actor)
    else:
        _assert_refused(response, actor, before, thread_id, calls, route)


# --- Item 2: archive, purge, restore --------------------------------------------

@pytest.mark.parametrize("actor", ACTORS)
def test_archive_of_shared_work(client, net, calls, actor):
    """DELETE on shared work: owner and administrator archive it for the
    organization; every other reader only hides it from their own history
    (audit risk R6: nobody else can schedule its purge); outsiders get 404."""
    thread_id = _target(net, actor)
    before = _project_state(thread_id)
    attribution = _attribution(thread_id)
    user = net["users"][actor]

    response = _call(client, net, actor, "DELETE", f"/api/v1/ai-agent/threads/{thread_id}")

    if actor in OUTSIDERS:
        assert response.status_code == 404, (actor, response.status_code)
        assert MARKER.encode() not in response.data
        assert _project_state(thread_id) == before
    else:
        assert response.status_code == 200, (actor, response.get_data(as_text=True)[:300])
        assert _attribution(thread_id) == attribution
        row = _rows(thread_id)[0]
        if actor in ARCHIVERS:
            assert row.archived_at is not None and row.purge_after is not None, actor
        else:
            assert row.archived_at is None and row.purge_after is None, (actor, "a member scheduled a purge")
            assert user.id in (row.hidden_for_user_ids or []), actor
    assert _external(calls) == {}, actor


@pytest.mark.parametrize("actor", ACTORS)
def test_purge_of_shared_work(client, net, calls, actor):
    """Permanent purge destroys the organization's row: owner and
    administrator only. Editors, viewers and the demoted creator 403; former
    member and other organization 404. A refusal leaves the row intact."""
    thread_id = _target(net, actor)
    before = _project_state(thread_id)

    response = _call(client, net, actor, "POST", f"/api/v1/ai-agent/threads/{thread_id}/purge")

    if actor in ARCHIVERS:
        assert response.status_code == 200, (actor, response.get_data(as_text=True)[:300])
        assert _rows(thread_id) == [], actor
    else:
        expected = 404 if actor in OUTSIDERS else 403
        assert response.status_code == expected, (actor, response.status_code,
                                                  response.get_data(as_text=True)[:300])
        assert MARKER.encode() not in response.data
        assert _project_state(thread_id) == before, (actor, "a refused purge changed the project")
    assert _external(calls) == {}, actor


@pytest.mark.parametrize("actor", ACTORS)
def test_restore_of_archived_shared_work(client, net, calls, actor):
    """The organization owner archives the project; each role then asks to
    restore it. Only someone who may archive lifts the organization archive.
    Other readers get the existing 'not archived' answer for their own view
    and change nothing; outsiders get 404."""
    thread_id = _target(net, actor)
    owner = net["users"]["owner"]
    archive = _call(client, net, "owner", "DELETE", f"/api/v1/ai-agent/threads/{thread_id}")
    assert archive.status_code == 200, archive.get_data(as_text=True)[:300]
    assert _rows(thread_id)[0].archived_at is not None
    before = _project_state(thread_id)

    response = _call(client, net, actor, "POST", f"/api/v1/ai-agent/threads/{thread_id}/restore")

    row = _rows(thread_id)[0]
    if actor in ARCHIVERS:
        assert response.status_code == 200, (actor, response.get_data(as_text=True)[:300])
        assert row.archived_at is None and row.purge_after is None, actor
    elif actor in OUTSIDERS:
        assert response.status_code == 404, (actor, response.status_code)
        assert MARKER.encode() not in response.data
        assert _project_state(thread_id) == before
    else:
        assert response.status_code == 400, (actor, response.status_code,
                                             response.get_data(as_text=True)[:300])
        assert row.archived_at is not None, (actor, "a member lifted the organization archive")
        assert _project_state(thread_id) == before
    assert owner.id  # the archive was the owner's
    assert _external(calls) == {}, actor


@pytest.mark.xfail(strict=True, raises=AssertionError, reason=(
    "POST /ai-agent/threads/<id>/restore: _authorized_thread_scope drops rows the caller "
    "has hidden, so a member cannot undo their own hide (404); pre-existing, not fixed here"))
@pytest.mark.parametrize("actor", ["editor", "viewer", "creator-now-viewer"])
def test_member_restores_their_own_hide_only(client, net, actor):
    thread_id = _target(net, actor)
    user = net["users"][actor]
    assert _call(client, net, actor, "DELETE", f"/api/v1/ai-agent/threads/{thread_id}").status_code == 200
    assert user.id in (_rows(thread_id)[0].hidden_for_user_ids or [])

    response = _call(client, net, actor, "POST", f"/api/v1/ai-agent/threads/{thread_id}/restore")

    assert response.status_code == 200, response.get_data(as_text=True)[:300]
    row = _rows(thread_id)[0]
    assert user.id not in (row.hidden_for_user_ids or [])
    assert row.archived_at is None


def test_editor_archives_and_purges_their_own_private_work(client, net, calls):
    """Matrix: an editor archives or deletes private work they created, and
    only that."""
    from app.routes.sessions import save_user_sessions

    editor, org = net["users"]["editor"], net["org"]
    assert save_user_sessions(editor.id, {"t-editor-private": {
        "session_id": "t-editor-private", "user_id": editor.id, "name": f"Private {MARKER}",
        "status": "in_progress", "organization_id": org.id, "visibility": "private",
        "chat_history": [{"role": "user", "content": "mine"}],
    }})
    _db.session.expire_all()

    archived = _call(client, net, "editor", "DELETE", "/api/v1/ai-agent/threads/t-editor-private")
    assert archived.status_code == 200
    assert _rows("t-editor-private")[0].archived_at is not None
    # Another editor-level member cannot see it at all.
    assert _call(client, net, "viewer", "POST", "/api/v1/ai-agent/threads/t-editor-private/purge").status_code == 404
    purged = _call(client, net, "editor", "POST", "/api/v1/ai-agent/threads/t-editor-private/purge")
    assert purged.status_code == 200
    assert _rows("t-editor-private") == []
    assert _external(calls) == {}


# --- Item 3: Decision Impact routes ------------------------------------------------

DI_ROUTES = {
    "baseline-read": ("GET", "/api/v1/decision-impact/baseline/{t}", None),
    "baseline-update": ("POST", "/api/v1/decision-impact/baseline/{t}",
                        {"structure": {"alternatives": ["Vendor A"], "confirmed": True}}),
    "baseline-seal": ("POST", "/api/v1/decision-impact/baseline/{t}/seal", {}),
    "report": ("GET", "/api/v1/decision-impact/report/{t}", None),
}


@pytest.mark.parametrize("actor", ACTORS)
@pytest.mark.parametrize("route", sorted(DI_ROUTES))
def test_decision_impact_routes_follow_read_access(client, net, calls, actor, route):
    """Decision Impact keeps a baseline per member (owner-scoped by design);
    it never writes the project. Readers reach the route; outsiders get 404,
    no project content, and no baseline row of their own."""
    from app.models_decision_baseline import DecisionBaseline

    method, template, body = DI_ROUTES[route]
    thread_id = _target(net, actor)
    user = net["users"][actor]
    before = _project_state(thread_id)

    response = _call(client, net, actor, method, template.format(t=thread_id), body)

    if actor in READERS:
        # The fixture project is already scored, so the correction window is
        # closed: revising the draft is the existing 409, everything else 200.
        expected = 409 if route == "baseline-update" else 200
        assert response.status_code == expected, (route, actor, response.status_code,
                                                  response.get_data(as_text=True)[:300])
        if route in ("baseline-read", "baseline-seal"):
            assert MARKER.encode() in response.data, (route, actor, "baseline lost the project content")
    else:
        assert response.status_code == 404, (route, actor, response.status_code)
        assert MARKER.encode() not in response.data, (route, actor)
        assert DecisionBaseline.query.filter_by(user_id=str(user.id), thread_id=thread_id).count() == 0
    assert _project_state(thread_id) == before, (route, actor, "Decision Impact wrote the project")
    assert _external(calls) == {}, (route, actor)


# --- Item 3: team project routes --------------------------------------------------

TEAM_READS = {
    "activity": "/api/v1/team/projects/{t}/activity",
    "comments": "/api/v1/team/projects/{t}/comments",
}


@pytest.mark.parametrize("actor", ACTORS)
@pytest.mark.parametrize("route", sorted(TEAM_READS))
def test_team_project_reads_follow_read_access(client, net, calls, actor, route):
    thread_id = _target(net, actor)
    before = _project_state(thread_id)

    response = _call(client, net, actor, "GET", TEAM_READS[route].format(t=thread_id))

    if actor in READERS:
        assert response.status_code == 200, (route, actor, response.get_data(as_text=True)[:300])
        assert MARKER.encode() in response.data, (route, actor)
    else:
        assert response.status_code == 404, (route, actor, response.status_code,
                                             response.get_data(as_text=True)[:300])
        assert MARKER.encode() not in response.data, (route, actor)
    assert _project_state(thread_id) == before, (route, actor)
    assert _external(calls) == {}, (route, actor)


@pytest.mark.parametrize("actor", ACTORS)
def test_team_comment_follows_today_s_participation_rule(client, net, calls, actor):
    """H-2R F5 (open decision): a team comment needs read access only, so
    viewers and the demoted creator may comment today. Pinned, not endorsed:
    if Lydia decides comments are edits, flip READ_ONLY to 403 here."""
    thread_id = _target(net, actor)
    before = _project_state(thread_id)
    attribution = _attribution(thread_id)

    response = _call(client, net, actor, "POST", f"/api/v1/team/projects/{thread_id}/comments",
                     {"body": "Net comment"})

    if actor in READERS:
        assert response.status_code == 201, (actor, response.get_data(as_text=True)[:300])
        assert response.get_json()["comment"]["author_user_id"] == net["users"][actor].id
        assert _attribution(thread_id) == attribution
    else:
        assert response.status_code == 404, (actor, response.status_code)
        assert MARKER.encode() not in response.data
        assert _project_state(thread_id) == before
    assert _external(calls) == {}, actor


@pytest.mark.xfail(strict=True, raises=AssertionError, reason=(
    "POST /team/projects/<id>/comments: add_project_comment mutates row.payload in place and "
    "db.JSON does not detect it, so the comment and its activity entry are not saved "
    "(pre-existing persistence defect, not authorization; not fixed here)"))
def test_team_comment_is_saved_to_the_project(client, net):
    response = _call(client, net, "editor", "POST", "/api/v1/team/projects/t-shared/comments",
                     {"body": "Net comment"})
    assert response.status_code == 201
    listed = _call(client, net, "owner", "GET", "/api/v1/team/projects/t-shared/comments").get_json()
    assert [c["body"] for c in listed["comments"]][0] == "Net comment"


SHARING_TARGET = "private"   # every fixture project is seeded "team"


def _sharing_state(thread_id):
    """Everything sharing can change: the project state plus the visibility
    columns (``_project_state`` does not include them)."""
    _db.session.expire_all()
    columns = [
        (r.id, r.visibility, json.dumps(r.shared_with_user_ids, sort_keys=True, default=str),
         json.dumps(r.hidden_for_user_ids, sort_keys=True, default=str))
        for r in UserSession.query.filter_by(session_id=thread_id).order_by(UserSession.id).all()
    ]
    return _project_state(thread_id), columns


def _check_sharing_cell(actor, response, before, after, attribution_before, attribution_after, calls_):
    """The sharing matrix: O and A change visibility; E (not the creator), V
    and CV 403; FM and OO 404. A refusal changes nothing at all."""
    if actor in ARCHIVERS:
        assert response.status_code == 200, (actor, response.status_code, response.get_data(as_text=True)[:300])
        assert attribution_after == attribution_before, (actor, "attribution or row count changed")
        assert [v for _id, v, _s, _h in after[1]] == [SHARING_TARGET], (actor, "the change did not persist")
    else:
        expected = 404 if actor in OUTSIDERS else 403
        assert response.status_code == expected, (actor, response.status_code,
                                                  response.get_data(as_text=True)[:300])
        assert MARKER.encode() not in response.data, (actor, "protected content leaked")
        assert after[1] == before[1], (actor, "a refused sharing update changed visibility")
        assert after == before, (actor, "a refused sharing update changed the project")
    assert _external(calls_) == {}, actor


def _run_sharing_cell(client, net, calls_, actor):
    thread_id = _target(net, actor)
    before = _sharing_state(thread_id)
    assert [v for _id, v, _s, _h in before[1]] == ["team"], "fixture must start from a different visibility"
    attribution = _attribution(thread_id)
    response = _call(client, net, actor, "PATCH", f"/api/v1/team/projects/{thread_id}/sharing",
                     {"visibility": SHARING_TARGET})
    _check_sharing_cell(actor, response, before, _sharing_state(thread_id),
                        attribution, _attribution(thread_id), calls_)


@pytest.mark.parametrize("actor", ACTORS)
def test_team_sharing_update_is_owner_or_admin(client, net, calls, actor):
    """Sharing changes who can see the project. Every project starts "team"
    and the request asks for "private", so an allowed request is a real
    change and a refused one would be visible if it slipped through."""
    _run_sharing_cell(client, net, calls, actor)


def test_creator_with_an_editing_role_may_change_their_projects_sharing(client, net, calls):
    editor, org = net["users"]["editor"], net["org"]
    _seed_named(editor, org.id, "t-editor-team", f"Editor team project {MARKER}")
    assert _rows("t-editor-team")[0].visibility == "team"
    response = _call(client, net, "editor", "PATCH", "/api/v1/team/projects/t-editor-team/sharing",
                     {"visibility": SHARING_TARGET})
    assert response.status_code == 200, response.get_data(as_text=True)[:300]
    assert _rows("t-editor-team")[0].visibility == SHARING_TARGET
    # The same editor still may not reshare the owner's project.
    before = _sharing_state("t-shared")
    refused = _call(client, net, "editor", "PATCH", "/api/v1/team/projects/t-shared/sharing",
                    {"visibility": SHARING_TARGET})
    assert refused.status_code == 403
    assert _sharing_state("t-shared") == before
    assert _external(calls) == {}


@pytest.mark.parametrize("actor", ["editor", "viewer", "creator-now-viewer"])
def test_sharing_cell_fails_when_the_role_check_is_broken(client, net, calls, monkeypatch, actor):
    """Mutation sensitivity: with the route's role check deliberately broken
    (every role treated as an organization manager), a refused actor's PATCH
    really changes visibility, and the cell must fail."""
    from app.routes import team as team_routes

    monkeypatch.setattr(team_routes, "can_manage_org", lambda *_args, **_kwargs: True)
    with pytest.raises(AssertionError):
        _run_sharing_cell(client, net, calls, actor)
    assert _rows(_target(net, actor))[0].visibility == SHARING_TARGET, "the mutation did not take effect"


def test_sharing_check_catches_a_silent_visibility_change(client, net, calls):
    """Mutation sensitivity for the persisted-state comparison alone: a real
    visibility change reported with the refusal status still fails the cell."""
    before = _sharing_state("t-shared")
    attribution = _attribution("t-shared")
    changed = _call(client, net, "owner", "PATCH", "/api/v1/team/projects/t-shared/sharing",
                    {"visibility": SHARING_TARGET})
    assert changed.status_code == 200
    after = _sharing_state("t-shared")
    assert after[1] != before[1]

    class _Refused:
        status_code = 403
        data = b'{"error":"Role does not allow sharing updates"}'

        def get_data(self, as_text=False):
            return self.data.decode() if as_text else self.data

    with pytest.raises(AssertionError, match="changed visibility"):
        _check_sharing_cell("viewer", _Refused(), before, after, attribution, _attribution("t-shared"), calls)


# --- Unknown project ids -------------------------------------------------------------

UNKNOWN_ROUTES = [
    ("GET", "/api/v1/ai-agent/threads/{t}", None),
    ("PATCH", "/api/v1/ai-agent/threads/{t}", {"name": "x"}),
    ("POST", "/api/v1/ai-agent/threads/{t}/touch", {}),
    ("POST", "/api/v1/ai-agent/threads/{t}/messages", {"messages": [{"role": "user", "content": "x"}]}),
    ("POST", "/api/v1/ai-agent/threads/{t}/messages/0/feedback", {"value": "up"}),
    ("POST", "/api/v1/ai-agent/threads/{t}/knowledge/refresh", {}),
    ("GET", "/api/v1/ai-agent/threads/{t}/usage", None),
    ("GET", "/api/v1/ai-agent/threads/{t}/levers", None),
    ("DELETE", "/api/v1/ai-agent/threads/{t}", None),
    ("POST", "/api/v1/ai-agent/threads/{t}/purge", {}),
    ("POST", "/api/v1/ai-agent/threads/{t}/restore", {}),
    ("GET", "/api/v1/decision-impact/baseline/{t}", None),
    ("POST", "/api/v1/decision-impact/baseline/{t}/seal", {}),
    ("GET", "/api/v1/decision-impact/report/{t}", None),
    ("GET", "/api/v1/team/projects/{t}/comments", None),
    ("POST", "/api/v1/team/projects/{t}/comments", {"body": "x"}),
    ("PATCH", "/api/v1/team/projects/{t}/sharing", {"visibility": "team"}),
]


@pytest.mark.parametrize(("method", "template", "body"), UNKNOWN_ROUTES,
                         ids=[f"{m} {t}" for m, t, _b in UNKNOWN_ROUTES])
def test_unknown_project_id_is_not_found_and_creates_nothing(client, net, calls, method, template, body):
    response = _call(client, net, "owner", method, template.format(t="t-does-not-exist"), body)
    assert response.status_code == 404, (method, template, response.status_code,
                                         response.get_data(as_text=True)[:300])
    assert _rows("t-does-not-exist") == []
    assert _external(calls) == {}


# --- Same id in two organizations; switching the active organization -------------

@pytest.fixture
def collision(net):
    """The other organization's owner has their own ``t-shared``; the viewer
    of organization A also owns a ``t-shared`` in an organization B they
    created."""
    outsider = net["users"]["other-org"]
    viewer = net["users"]["viewer"]
    outsider_org = outsider.active_organization_id
    _seed_named(outsider, outsider_org, "t-shared", "Other org project OTHER-ORG-MARK")
    org_b = _mk_org(viewer, f"B{uuid.uuid4().hex[:6]}")
    _seed_named(viewer, org_b.id, "t-shared", "Viewer org B project ORG-B-MARK")
    viewer.active_organization_id = org_b.id
    _db.session.commit()
    return {**net, "org_a": net["org"], "org_b": org_b}


def _seed_named(user, org_id, thread_id, name):
    from app.routes.sessions import save_user_sessions
    assert save_user_sessions(user.id, {thread_id: {
        "session_id": thread_id, "user_id": user.id, "name": name, "status": "in_progress",
        "organization_id": org_id, "visibility": "team",
        "chat_history": [{"role": "user", "content": name},
                         {"role": "assistant", "content": "ok"}],
    }})
    _db.session.expire_all()


def _row_in(org_id, thread_id):
    _db.session.expire_all()
    return UserSession.query.filter_by(session_id=thread_id, organization_id=str(org_id)).one()


def _snapshot(row):
    return (row.id, row.user_id, row.organization_id, int(row.revision or 1), row.last_edited_by_user_id,
            json.dumps(row.payload, sort_keys=True, default=str), row.archived_at)


def test_same_id_in_another_organization_never_reaches_this_one(client, collision, calls):
    org_a = collision["org_a"]
    a_before = _snapshot(_row_in(org_a.id, "t-shared"))

    read = _call(client, collision, "other-org", "GET", "/api/v1/ai-agent/threads/t-shared")
    assert read.status_code == 200
    assert b"OTHER-ORG-MARK" in read.data and MARKER.encode() not in read.data

    for method, path, body in (
        ("PATCH", "/api/v1/ai-agent/threads/t-shared", {"name": "Other org renamed its own"}),
        ("POST", "/api/v1/ai-agent/threads/t-shared/messages", {"messages": [{"role": "user", "content": "theirs"}]}),
        ("POST", "/api/v1/team/projects/t-shared/comments", {"body": "theirs"}),
        ("GET", "/api/v1/team/projects/t-shared/comments", None),
        ("GET", "/api/v1/decision-impact/baseline/t-shared", None),
    ):
        response = _call(client, collision, "other-org", method, path, body)
        assert MARKER.encode() not in response.data, (method, path)
    assert _snapshot(_row_in(org_a.id, "t-shared")) == a_before, "organization A's project changed"
    assert _row_in(collision["users"]["other-org"].active_organization_id, "t-shared").payload["name"] \
        == "Other org renamed its own"
    assert _external(calls) == {}


@pytest.mark.parametrize("route", ["rename", "messages", "feedback", "touch", "knowledge-refresh"])
def test_viewer_switched_to_own_same_id_project_writes_only_their_own(client, collision, calls, route):
    """A viewer in A who owns ``t-shared`` in B, active in B, writes B's
    project; A's is untouched. Switched back to A, the same request is 403."""
    method, template, body = _thread_writes()[route]
    org_a, org_b = collision["org_a"], collision["org_b"]
    viewer = collision["users"]["viewer"]
    a_before = _snapshot(_row_in(org_a.id, "t-shared"))
    b_revision = int(_row_in(org_b.id, "t-shared").revision or 1)

    response = _call(client, collision, "viewer", method, template.format(t="t-shared"), body(b_revision))
    assert response.status_code == 200, (route, response.get_data(as_text=True)[:300])
    assert MARKER.encode() not in response.data
    assert _snapshot(_row_in(org_a.id, "t-shared")) == a_before, (route, "A's project changed")

    viewer.active_organization_id = org_a.id
    _db.session.commit()
    a_revision = int(_row_in(org_a.id, "t-shared").revision or 1)
    calls["model"].clear()
    b_before = _snapshot(_row_in(org_b.id, "t-shared"))
    refused = _call(client, collision, "viewer", method, template.format(t="t-shared"), body(a_revision))
    assert refused.status_code == 403, (route, refused.status_code)
    assert _snapshot(_row_in(org_a.id, "t-shared")) == a_before
    assert _snapshot(_row_in(org_b.id, "t-shared")) == b_before
    assert calls["model"] == []


@pytest.mark.parametrize("route", ["purge", "sharing", "comments"])
def test_org_switch_never_carries_rights_across(client, collision, calls, route):
    """The viewer owns B, so they may destroy or reshare B's ``t-shared``;
    nothing they do there reaches A's project of the same id."""
    org_a, org_b = collision["org_a"], collision["org_b"]
    a_before = _snapshot(_row_in(org_a.id, "t-shared"))
    method, path, body = {
        "purge": ("POST", "/api/v1/ai-agent/threads/t-shared/purge", {}),
        "sharing": ("PATCH", "/api/v1/team/projects/t-shared/sharing", {"visibility": "private"}),
        "comments": ("POST", "/api/v1/team/projects/t-shared/comments", {"body": "B only"}),
    }[route]

    response = _call(client, collision, "viewer", method, path, body)
    assert response.status_code in (200, 201), (route, response.get_data(as_text=True)[:300])
    assert _snapshot(_row_in(org_a.id, "t-shared")) == a_before, (route, "A's project changed")
    if route == "purge":
        assert UserSession.query.filter_by(session_id="t-shared", organization_id=str(org_b.id)).count() == 0
    assert _external(calls) == {}


# --- Conflicting project ids in one request ---------------------------------------

@pytest.fixture
def own_private(net):
    """The viewer's own private project in organization A, which they may write."""
    viewer, org = net["users"]["viewer"], net["org"]
    _seed_named(viewer, org.id, "t-viewer-own", "Viewer own project")
    row = _row_in(org.id, "t-viewer-own")
    row.visibility = "private"
    _db.session.commit()
    return net


@pytest.mark.parametrize("variant", ["thread-id-vs-header", "thread-id-vs-session-id", "session-id-vs-header"])
def test_conflicting_ids_never_redirect_a_refused_write(client, own_private, calls, variant):
    """``conversation/continue`` reads ``thread_id``, then ``session_id``,
    then ``X-Session-ID``. A viewer naming the shared project in the field
    that wins and their own writable project in another is refused on the
    shared project, and neither project changes, before any model call."""
    body = {"message": "Overwrite please"}
    headers = {}
    if variant == "thread-id-vs-header":
        body["thread_id"] = "t-shared"
        headers["X-Session-ID"] = "t-viewer-own"
    elif variant == "thread-id-vs-session-id":
        body["thread_id"] = "t-shared"
        body["session_id"] = "t-viewer-own"
    else:
        body["session_id"] = "t-shared"
        headers["X-Session-ID"] = "t-viewer-own"
    shared_before = _project_state("t-shared")
    own_before = _project_state("t-viewer-own")

    response = _call(client, own_private, "viewer", "POST", "/api/v1/ai-agent/conversation/continue",
                     body, headers)

    assert response.status_code == 403, (variant, response.status_code, response.get_data(as_text=True)[:300])
    assert MARKER.encode() not in response.data
    assert _project_state("t-shared") == shared_before
    assert _project_state("t-viewer-own") == own_before
    assert _external(calls) == {}, variant


def test_header_never_overrides_a_path_project_id(client, own_private, calls):
    """Thread routes take the project from the path only; an ``X-Session-ID``
    naming a writable project does not turn a refused write into an allowed
    one, and a readable path never returns the header's project."""
    shared_before = _project_state("t-shared")
    own_before = _project_state("t-viewer-own")
    header = {"X-Session-ID": "t-viewer-own"}

    write = _call(client, own_private, "viewer", "POST", "/api/v1/ai-agent/threads/t-shared/messages",
                  {"messages": [{"role": "user", "content": "x"}], "thread_id": "t-viewer-own",
                   "session_id": "t-viewer-own"}, header)
    assert write.status_code == 403
    read = _call(client, own_private, "other-org", "GET", "/api/v1/ai-agent/threads/t-viewer-own",
                 None, {"X-Session-ID": "t-shared"})
    assert read.status_code == 404 and MARKER.encode() not in read.data
    assert _project_state("t-shared") == shared_before
    assert _project_state("t-viewer-own") == own_before
    assert _external(calls) == {}


# --- Report mode (today's default, SEC-06 pending) ---------------------------------

REPORT_MODE_CELLS = [
    ("GET", "/api/v1/ai-agent/threads/{t}", None, 200),
    ("GET", "/api/v1/ai-agent/threads/{t}/levers", None, 200),
    ("POST", "/api/v1/ai-agent/threads/{t}/touch", {}, 200),
    ("POST", "/api/v1/ai-agent/threads/{t}/messages", {"messages": [{"role": "user", "content": "x"}]}, 200),
    ("GET", "/api/v1/decision-impact/report/{t}", None, 200),
    ("GET", "/api/v1/team/projects/{t}/comments", None, 404),
]


@pytest.mark.parametrize(("method", "template", "body", "expected"), REPORT_MODE_CELLS,
                         ids=[f"{m} {t}" for m, t, _b, _e in REPORT_MODE_CELLS])
def test_report_mode_former_creator_is_pinned_and_audited(client, net, calls, monkeypatch,
                                                         method, template, body, expected):
    """Report mode is pinned, not changed, until SEC-06: a former member
    keeps reaching what they created through the access seam, and each pass
    is recorded as a would-be refusal. Team routes need an active membership
    in either mode."""
    from app import org_access
    from app.models import OrgAccessShadowEvent

    monkeypatch.setenv("ORG_ACCESS_ENFORCEMENT", "report")
    org_access.reset_dedup()
    former = net["users"]["former-member"]
    thread_id = "t-former"
    attribution = _attribution(thread_id)

    response = _call(client, net, "former-member", method, template.format(t=thread_id), body)

    assert response.status_code == expected, (template, response.status_code,
                                              response.get_data(as_text=True)[:300])
    assert _attribution(thread_id) == attribution
    if expected == 200 and "team/" not in template:
        assert OrgAccessShadowEvent.query.filter_by(
            user_id=former.id, mode="report", resource_id=thread_id,
        ).count() >= 1, "the would-be refusal is recorded for review"
    # A former member who did not create the project has no path in either mode.
    other = _call(client, net, "former-member", method, template.format(t="t-shared"), body)
    assert other.status_code == 404, (template, other.status_code)
    assert MARKER.encode() not in other.data
    assert _external(calls) == {}


def test_report_mode_does_not_reach_purge(client, net, calls, monkeypatch):
    """Destruction of shared work stays with owner and administrator in
    report mode too."""
    from app import org_access

    monkeypatch.setenv("ORG_ACCESS_ENFORCEMENT", "report")
    org_access.reset_dedup()
    before = _project_state("t-shared")
    response = _call(client, net, "former-member", "POST", "/api/v1/ai-agent/threads/t-shared/purge")
    assert response.status_code == 404
    assert _project_state("t-shared") == before


# --- Existence probe, then authorize (the guard's ORDERING_EXEMPTIONS) ----------

@pytest.fixture
def turn_calls(monkeypatch, calls):
    """conversation/start's model step: recorded, then stopped."""
    from app.routes import ai_agent

    def _reply(*_args, **_kwargs):
        calls["model"].append("reply")
        raise RuntimeError("stand-in model reached")

    monkeypatch.setattr(ai_agent, "_generate_assistant_reply", _reply)
    return calls


def _probe_request(route, thread_id, revision):
    if route == "start-json":
        return "POST", "/api/v1/ai-agent/conversation/start", {"message": "Reopen", "thread_id": thread_id}, None, None
    if route == "start-form":
        return "POST", "/api/v1/ai-agent/conversation/start", None, {"message": "Reopen", "thread_id": thread_id}, None
    if route == "analyze-body":
        return "POST", "/api/v1/strategy/analyze", {"thread_id": thread_id}, None, None
    if route == "analyze-header":
        return "POST", "/api/v1/strategy/analyze", {}, None, {"X-Session-ID": thread_id}
    if route == "strategy-rename":
        return "PATCH", f"/api/v1/strategy/threads/{thread_id}", {"name": "Renamed by strategy",
                                                                  "base_revision": revision}, None, None
    if route == "session-save":
        return "POST", "/api/v1/sessions", {"session_id": thread_id, "name": "Saved over",
                                            "base_revision": revision}, None, None
    raise AssertionError(route)


CREATE_ROUTES = {"start-json", "start-form", "session-save"}


def _a_rows(net, thread_id):
    """Organization A's rows for this id, every stored field."""
    _db.session.expire_all()
    return [
        (r.id, r.user_id, r.organization_id, int(r.revision or 1), r.last_edited_by_user_id, r.visibility,
         json.dumps(r.payload, sort_keys=True, default=str),
         json.dumps(r.scenarios_json, sort_keys=True, default=str), r.archived_at)
        for r in UserSession.query.filter_by(session_id=thread_id, organization_id=str(net["org"].id))
        .order_by(UserSession.id).all()
    ]


PROBE_ROUTES = ["start-json", "start-form", "analyze-body", "analyze-header", "strategy-rename", "session-save"]


@pytest.mark.parametrize("actor", ACTORS)
@pytest.mark.parametrize("route", PROBE_ROUTES)
def test_existence_probe_routes_follow_write_access(client, net, turn_calls, actor, route):
    """The routes that look a project up before authorizing it
    (``canonical_row`` existence probe) refuse every read-only member with 403
    and every outsider with 404, before any save, reservation or model call.
    Writers reach the route's work: the model for start (the project's
    creator) and analyze; the save for rename and session save. A writer who
    did not create the project is sent to conversation/continue by start
    (409), as approved."""
    calls = turn_calls
    thread_id = _target(net, actor)
    before = _project_state(thread_id)
    attribution = _attribution(thread_id)
    revision = int(_rows(thread_id)[0].revision or 1)
    _a_before = _a_rows(net, thread_id)
    method, path, body, form, headers = _probe_request(route, thread_id, revision)
    merged = dict(_headers(net["app"], net["users"][actor]))
    merged.update(headers or {})
    if form is not None:
        response = client.open(path, method=method, headers=merged, data=form,
                               content_type="multipart/form-data")
    else:
        response = client.open(path, method=method, headers=merged, json=body)

    if actor == "other-org" and route in CREATE_ROUTES:
        # Project ids are per organization (OD-6 A: these routes create). The
        # other organization's member creates their own project under the
        # same id in their own organization; organization A's is untouched
        # and nothing of it is returned.
        assert response.status_code != 404 and MARKER.encode() not in response.data, (route, response.status_code)
        assert _a_rows(net, thread_id) == _a_before, (route, "organization A's project changed")
        own_org = net["users"]["other-org"].active_organization_id
        assert all(r.organization_id == own_org for r in _rows(thread_id) if r.organization_id != net["org"].id)
        assert not calls["http"] and not calls["email"]
        return
    if actor in READ_ONLY or actor in OUTSIDERS:
        _assert_refused(response, actor, before, thread_id, calls, route)
        return
    assert response.status_code not in (403, 404), (route, actor, response.status_code,
                                                    response.get_data(as_text=True)[:300])
    assert _attribution(thread_id) == attribution, (route, actor, "attribution or row count changed")
    assert not calls["http"] and not calls["email"], (route, actor)
    if route.startswith("start"):
        if actor == "owner":
            assert calls["model"], (route, actor, "the creator's start never reached the model")
        else:
            assert response.status_code == 409 and response.get_json()["code"] == "thread_exists", \
                (route, actor, response.status_code)
            assert calls["model"] == [] and _project_state(thread_id) == before, (route, actor)
    elif route.startswith("analyze"):
        assert calls["model"], (route, actor, "analysis never reached the model")
    else:
        assert response.status_code == 200, (route, actor, response.get_data(as_text=True)[:300])
        assert calls["model"] == []


# --- Bookkeeping ------------------------------------------------------------------

def test_item_three_pointers_name_existing_tests():
    """Every pointer names a test that exists, so a renamed test cannot leave
    a cell silently uncovered."""
    import pathlib
    import re

    here = pathlib.Path(__file__).resolve().parent
    for route, pointer in COVERED_ELSEWHERE.items():
        files = re.findall(r"(test_[a-z0-9_]+\.py)", pointer)
        assert files, route
        current = None
        for part in re.split(r",\s*", pointer):
            match = re.match(r"(test_[a-z0-9_]+\.py)(?:::(\w+))?", part.strip())
            if match:
                current = here / match.group(1)
                assert current.exists(), (route, match.group(1))
                name = match.group(2)
            else:
                name_match = re.match(r"::(\w+)", part.strip())
                name = name_match.group(1) if name_match else None
            if name and current is not None:
                assert f"def {name}(" in current.read_text(), (route, name)
