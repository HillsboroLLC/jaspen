"""P2e-C1: record-bound Decision Record routes authorize against the RECORD's project.

C1 (H-2e-3 independent audit): the routes that act on a record id resolved the
project with ``canonical_row(user, record.thread_id)``, which follows the
caller's ACTIVE organization. A viewer in organization A who owns a same-id
project in organization B (or who simply switches to an organization with no
such project) switched to B and wrote outcomes, lessons, consent, supersession
and PATCH changes into organization A's decision history.

Now every record-bound check resolves ``record_project_row(record)``: the
project in the record's own organization. Seven roles of the acceptance
matrix (section 4), each attempted with the active organization switched away:

* owner, administrator, editor: read, ``can_edit`` true, every write works;
* viewer, creator now viewer: read, ``can_edit`` false, every write 403;
* former member (enforce mode), other organization: 404 on read and write,
  no record content;
* no refused request changes any decision or project table.
"""

import json

import pytest
from sqlalchemy import select

from app import db as _db
from app.models import Organization, OrganizationMember, UserSession
from app.models_decision_record import DecisionRecord
from tests.journeys.test_conversation_turn_lifecycle import _headers, _mk_org, solo  # noqa: F401
from tests.journeys.test_p2b_workspace_project_access import (  # noqa: F401
    MARKER, _no_rate_limits, _seed_project, team,
)
from tests.journeys.test_p2c_distribution_project_access import dist  # noqa: F401


ACTORS = ["owner", "administrator", "editor", "viewer", "creator-now-viewer",
          "former-member", "other-org"]
WRITERS = {"owner", "administrator", "editor"}
READ_ONLY = {"viewer", "creator-now-viewer"}
REFUSED_404 = {"former-member", "other-org"}
# How the caller's active organization is switched away from organization A.
SWITCHES = ["own-same-id-project", "no-same-id-project"]

B_MARKER = "ORGB-PROJECT-CONTENT"


@pytest.fixture(autouse=True)
def _enforce_former_member_matrix(request, monkeypatch):
    params = getattr(getattr(request.node, "callspec", None), "params", {})
    if params.get("actor") == "former-member":
        monkeypatch.setenv("ORG_ACCESS_ENFORCEMENT", "enforce")


@pytest.fixture
def xorg(dist):
    """Organization A (``dist``) with two Decision Records: ``t-shared``
    (the target) and ``t-demoted`` (a prior decision for supersession)."""
    from app.decision_records import create_or_refresh_record

    owner = dist["users"]["owner"]
    owner.active_organization_id = dist["org"].id
    _db.session.commit()
    target, _ = create_or_refresh_record(owner, "t-shared")
    prior, _ = create_or_refresh_record(owner, "t-demoted")
    assert target.organization_id == prior.organization_id == dist["org"].id
    dist["record"] = target.id
    dist["prior"] = prior.id
    return dist


def _switch_away(fixture, actor, switch):
    """Make the actor's ACTIVE organization one other than A.

    ``own-same-id-project``: an organization B where the actor is owner and
    has its own project with the same thread id (``t-shared``), as the
    auditor's reproduction. ``no-same-id-project``: an organization with no
    project of that id at all."""
    user = fixture["users"][actor]
    if actor == "other-org":
        org_b = Organization.query.filter_by(owner_user_id=user.id).first()
    else:
        org_b = _mk_org(user, f"OrgB{actor.replace('-', '')[:10]}")
    already_holds_id = UserSession.query.filter_by(
        user_id=user.id, session_id="t-shared").first() is not None
    # user_sessions is unique on (user_id, session_id): A's creator cannot
    # also hold a same-id project in B, so for them both switches are the same.
    if switch == "own-same-id-project" and not already_holds_id:
        from app.routes.sessions import save_user_sessions
        assert save_user_sessions(user.id, {"t-shared": {
            "session_id": "t-shared", "user_id": user.id, "name": f"B {B_MARKER}",
            "status": "completed", "organization_id": org_b.id, "visibility": "team",
            "chat_history": [{"role": "user", "content": B_MARKER}],
        }})
        b_row = UserSession.query.filter_by(user_id=user.id, session_id="t-shared",
                                            organization_id=org_b.id).one()
        assert b_row is not None
    user.active_organization_id = org_b.id
    _db.session.commit()
    _db.session.expire_all()
    return org_b


def _state():
    """Every row of every decision table and every project row, for
    "nothing changed" checks."""
    _db.session.expire_all()
    tables = [t for t in _db.metadata.sorted_tables
              if "decision" in t.name or t.name == "user_sessions"]
    snapshot = {}
    for table in tables:
        rows = _db.session.execute(select(table)).mappings().all()
        snapshot[table.name] = sorted(
            json.dumps(dict(r), sort_keys=True, default=str) for r in rows
        )
    return snapshot


def _call(client, fixture, actor, method, path, body=None):
    return client.open(path, method=method,
                       headers=_headers(fixture["app"], fixture["users"][actor]), json=body)


def _writes(fixture):
    rid, prior = fixture["record"], fixture["prior"]
    base = f"/api/v1/decision-records/{rid}"
    return {
        "outcome": ("POST", f"{base}/outcomes", {"summary": f"Outcome {MARKER}"}),
        "lesson": ("POST", f"{base}/lessons", {"lesson": f"Lesson {MARKER}"}),
        "consent": ("POST", f"{base}/consent", {"library_consent": "anonymized"}),
        "patch": ("PATCH", base, {"tags": ["c1"], "title": f"Retitled {MARKER}"}),
        "supersede": ("POST", f"{base}/supersedes", {"supersedes_id": prior}),
        "unsupersede": ("DELETE", f"{base}/supersedes", None),
    }


WRITE_OPS = ["outcome", "lesson", "consent", "patch", "supersede", "unsupersede"]
OK_STATUS = {"outcome": 201, "lesson": 201, "consent": 200, "patch": 200,
             "supersede": 200, "unsupersede": 200}


def _assert_refused(response, actor, before):
    text = response.get_data(as_text=True)
    if actor in REFUSED_404:
        assert response.status_code == 404, text
        assert response.get_json() == {"error": "Decision record not found"}
    else:
        assert response.status_code == 403, text
        assert response.get_json() == {
            "error": "Your role on this project is read-only", "code": "forbidden",
        }
    assert MARKER not in text and B_MARKER not in text
    assert _state() == before


# --- The auditor's exact reproduction ----------------------------------------

def test_c1_viewer_switched_to_own_same_id_project_cannot_write_org_a_outcome(client, xorg):
    """Viewer in A owns ``t-shared`` in B, switches to B, posts an outcome on
    A's record. Before the fix: 201 and A's history changed."""
    _switch_away(xorg, "viewer", "own-same-id-project")
    before = _state()
    response = _call(client, xorg, "viewer", "POST",
                     f"/api/v1/decision-records/{xorg['record']}/outcomes",
                     {"summary": "Injected from organization B"})
    _assert_refused(response, "viewer", before)
    record = DecisionRecord.query.filter_by(id=xorg["record"]).one()
    assert not any("Injected" in json.dumps(o) for o in (record.outcomes or []))


# --- Seven roles x write operations x active-organization switch --------------

@pytest.mark.parametrize("switch", SWITCHES)
@pytest.mark.parametrize("op", WRITE_OPS)
@pytest.mark.parametrize("actor", ACTORS)
def test_record_writes_follow_the_records_project(client, xorg, actor, op, switch):
    method, path, body = _writes(xorg)[op]
    if op == "unsupersede":
        # Something to remove, set up by the organization's owner in A first.
        from app.decision_records import supersede_record
        record = DecisionRecord.query.filter_by(id=xorg["record"]).one()
        prior = DecisionRecord.query.filter_by(id=xorg["prior"]).one()
        supersede_record(record, prior, xorg["users"]["owner"])
    _switch_away(xorg, actor, switch)
    before = _state()

    response = _call(client, xorg, actor, method, path, body)

    if actor in WRITERS:
        assert response.status_code == OK_STATUS[op], response.get_data(as_text=True)
        assert B_MARKER not in response.get_data(as_text=True)
        record = DecisionRecord.query.filter_by(id=xorg["record"]).one()
        assert record.organization_id == xorg["org"].id
        assert record.user_id == xorg["users"]["owner"].id  # authorship unchanged
        if op == "outcome":
            assert record.outcomes[-1]["summary"] == f"Outcome {MARKER}"
        if op == "supersede":
            assert record.supersedes_id == xorg["prior"]
        if op == "unsupersede":
            assert record.supersedes_id is None
    else:
        _assert_refused(response, actor, before)


# --- Reads and can_edit ---------------------------------------------------------

@pytest.mark.parametrize("switch", SWITCHES)
@pytest.mark.parametrize("actor", ACTORS)
def test_record_read_and_can_edit_follow_the_records_project(client, xorg, actor, switch):
    _switch_away(xorg, actor, switch)
    before = _state()
    rid = xorg["record"]

    detail = _call(client, xorg, actor, "GET", f"/api/v1/decision-records/{rid}")
    history = _call(client, xorg, actor, "GET", f"/api/v1/decision-records/{rid}/history")

    if actor in REFUSED_404:
        for response in (detail, history):
            assert response.status_code == 404, response.get_data(as_text=True)
            assert MARKER not in response.get_data(as_text=True)
    else:
        assert detail.status_code == 200, detail.get_data(as_text=True)
        body = detail.get_json()["record"]
        assert body["id"] == rid and body["organization_id"] == xorg["org"].id
        assert body["can_edit"] is (actor in WRITERS)
        # Nothing from the caller's same-id project in B is read into A's record.
        assert B_MARKER not in detail.get_data(as_text=True)
        assert history.status_code == 200
    assert _state() == before


@pytest.mark.parametrize("actor", ["viewer", "creator-now-viewer"])
def test_write_response_can_edit_is_record_bound(client, xorg, actor):
    """An editor's write response reports can_edit for A's project, not for
    the editor's active organization."""
    _switch_away(xorg, "editor", "own-same-id-project")
    response = _call(client, xorg, "editor", "POST",
                     f"/api/v1/decision-records/{xorg['record']}/outcomes",
                     {"summary": "Editor outcome"})
    assert response.status_code == 201
    assert response.get_json()["record"]["can_edit"] is True
    # And a read-only member in A, switched to their own B, still sees false.
    _switch_away(xorg, actor, "own-same-id-project")
    detail = _call(client, xorg, actor, "GET", f"/api/v1/decision-records/{xorg['record']}")
    assert detail.get_json()["record"]["can_edit"] is False


# --- Wrong organization's record, from organization B's side ------------------

def test_org_b_owner_cannot_reach_org_a_record_through_same_thread_id(client, xorg):
    """The other organization's owner holds a ``t-shared`` project in B with
    its own record. A's record stays unreachable, and B's record stays B's."""
    from app.decision_records import create_or_refresh_record

    outsider = xorg["users"]["other-org"]
    org_b = _switch_away(xorg, "other-org", "own-same-id-project")
    b_record, _ = create_or_refresh_record(outsider, "t-shared")
    assert b_record.organization_id == org_b.id and b_record.id != xorg["record"]
    before = _state()

    for method, path, body in _writes(xorg).values():
        _assert_refused(_call(client, xorg, "other-org", method, path, body), "other-org", before)
    read = _call(client, xorg, "other-org", "GET", f"/api/v1/decision-records/{xorg['record']}")
    assert read.status_code == 404

    own = _call(client, xorg, "other-org", "GET", f"/api/v1/decision-records/{b_record.id}")
    assert own.status_code == 200 and own.get_json()["record"]["can_edit"] is True
    assert MARKER not in own.get_data(as_text=True)


def test_supersession_never_crosses_organizations(client, xorg):
    """An editor of A who also owns a same-id project and record in B cannot
    link A's record to B's (and the attempt changes nothing)."""
    from app.decision_records import create_or_refresh_record

    editor = xorg["users"]["editor"]
    org_b = _switch_away(xorg, "editor", "own-same-id-project")
    b_record, _ = create_or_refresh_record(editor, "t-shared")
    assert b_record.organization_id == org_b.id
    before = _state()
    response = _call(client, xorg, "editor", "POST",
                     f"/api/v1/decision-records/{xorg['record']}/supersedes",
                     {"supersedes_id": b_record.id})
    assert response.status_code in {400, 404}
    assert _state() == before


# --- Library helpers ----------------------------------------------------------

@pytest.mark.parametrize("actor", ACTORS)
def test_can_read_and_write_record_ignore_the_active_organization(xorg, actor):
    from app.decision_records import can_read_record, can_write_record

    _switch_away(xorg, actor, "own-same-id-project")
    record = DecisionRecord.query.filter_by(id=xorg["record"]).one()
    user = xorg["users"][actor]
    assert can_read_record(record, user) is (actor not in REFUSED_404)
    assert can_write_record(record, user) is (actor in WRITERS)


def test_record_bound_helpers_do_not_resolve_by_active_organization():
    """Guard: record-bound authorization never calls canonical_row."""
    import inspect

    from app import decision_records as lib
    from app.routes import decision_records as routes

    for fn in (lib.can_read_record, lib.can_write_record, lib.supersede_record,
               routes._writable_record_or_none, routes._decision_view, routes.get_record):
        source = inspect.getsource(fn)
        assert "canonical_row(" not in source, fn.__name__


# --- Orphaned records: the project was permanently deleted --------------------
#
# Records outlive their projects by design (Purge permanently, the purge sweep,
# explicit deletes). With no project row, write access still needs an editing
# role in the RECORD's organization: a viewer never writes, even on work they
# created (Unified Architecture section 4; matrix B8).

def _purge(client, fixture, thread_id):
    """The organization owner permanently deletes the project through the
    supported route; the Decision Record survives."""
    owner = fixture["users"]["owner"]
    owner.active_organization_id = fixture["org"].id
    _db.session.commit()
    response = _call(client, fixture, "owner", "POST", f"/api/v1/ai-agent/threads/{thread_id}/purge")
    assert response.status_code == 200, response.get_data(as_text=True)
    _db.session.expire_all()
    assert UserSession.query.filter_by(session_id=thread_id,
                                       organization_id=fixture["org"].id).count() == 0


@pytest.fixture
def orphaned(client, xorg):
    """``t-shared``'s project purged; its record (attributed to the owner)
    remains in organization A."""
    from app.decision_records import record_project_row

    _purge(client, xorg, "t-shared")
    record = DecisionRecord.query.filter_by(id=xorg["record"]).one()
    assert record_project_row(record) is None
    assert record.organization_id == xorg["org"].id
    return xorg


@pytest.mark.parametrize("switch", ["stay-in-a"] + SWITCHES)
@pytest.mark.parametrize("op", WRITE_OPS)
@pytest.mark.parametrize("actor", ACTORS)
def test_orphaned_record_writes_need_an_editing_role(client, orphaned, actor, op, switch):
    fixture = orphaned
    method, path, body = _writes(fixture)[op]
    if op == "unsupersede":
        from app.decision_records import supersede_record
        record = DecisionRecord.query.filter_by(id=fixture["record"]).one()
        prior = DecisionRecord.query.filter_by(id=fixture["prior"]).one()
        supersede_record(record, prior, fixture["users"]["owner"])
    if switch != "stay-in-a":
        _switch_away(fixture, actor, switch)
    before = _state()

    response = _call(client, fixture, actor, method, path, body)

    if actor in WRITERS:
        assert response.status_code == OK_STATUS[op], response.get_data(as_text=True)
        record = DecisionRecord.query.filter_by(id=fixture["record"]).one()
        assert record.organization_id == fixture["org"].id
        assert record.user_id == fixture["users"]["owner"].id
        if op == "consent":
            assert record.library_consent == "anonymized"
        if op == "unsupersede":
            assert record.supersedes_id is None
    else:
        _assert_refused(response, actor, before)


@pytest.mark.parametrize("actor", ACTORS)
def test_orphaned_record_read_and_can_edit(client, orphaned, actor):
    before = _state()
    rid = orphaned["record"]
    detail = _call(client, orphaned, actor, "GET", f"/api/v1/decision-records/{rid}")
    if actor in REFUSED_404:
        assert detail.status_code == 404
        assert MARKER not in detail.get_data(as_text=True)
    else:
        assert detail.status_code == 200, detail.get_data(as_text=True)
        assert detail.get_json()["record"]["can_edit"] is (actor in WRITERS)
    assert _state() == before


@pytest.mark.parametrize("op", ["outcome", "lesson", "consent", "patch"])
def test_demoted_creator_cannot_write_their_own_orphaned_record(client, xorg, op):
    """``t-demoted`` was created by the member who is now a viewer; its record
    is attributed to them. After the project is purged they still cannot
    write it; the organization's owner still can."""
    from app.decision_records import record_project_row

    _purge(client, xorg, "t-demoted")
    prior = DecisionRecord.query.filter_by(id=xorg["prior"]).one()
    assert record_project_row(prior) is None
    assert prior.user_id == xorg["users"]["creator-now-viewer"].id
    method, path, body = _writes(xorg)[op]
    path = path.replace(xorg["record"], xorg["prior"])
    before = _state()

    refused = _call(client, xorg, "creator-now-viewer", method, path, body)
    _assert_refused(refused, "creator-now-viewer", before)

    allowed = _call(client, xorg, "owner", method, path, body)
    assert allowed.status_code == OK_STATUS[op], allowed.get_data(as_text=True)


@pytest.mark.parametrize("actor", ACTORS)
def test_can_write_record_on_orphaned_record(orphaned, actor):
    from app.decision_records import can_read_record, can_write_record

    record = DecisionRecord.query.filter_by(id=orphaned["record"]).one()
    user = orphaned["users"][actor]
    assert can_read_record(record, user) is (actor not in REFUSED_404)
    assert can_write_record(record, user) is (actor in WRITERS)


def test_orphaned_personal_record_keeps_the_author_only_rule(dist):
    """A legacy personal record (no organization) whose project is gone: its
    author may write it, nobody else may."""
    from app.decision_records import can_write_record, record_project_row

    author = dist["users"]["owner"]
    record = DecisionRecord(user_id=author.id, organization_id=None,
                            thread_id="t-personal-gone", title="Personal", record={})
    _db.session.add(record)
    _db.session.commit()
    assert record_project_row(record) is None
    assert can_write_record(record, author) is True
    for actor in ("administrator", "editor", "viewer", "other-org"):
        assert can_write_record(record, dist["users"][actor]) is False
