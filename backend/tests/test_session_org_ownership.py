"""Phase 1: canonical organization ownership, attribution, and the fork fix.

The behaviour under test is the one the audit named as the root cause: a
session used to be keyed (user_id, session_id), so an authorized collaborator
saving a shared project inserted a SECOND row under their own user_id and the
project silently forked.
"""
import pytest
from flask_jwt_extended import create_access_token
from werkzeug.security import generate_password_hash

from app.models import Organization, OrganizationMember, User, UserSession
from app.session_access import (
    PERSONAL_SESSION_IDS,
    canonical_row,
    find_forked_sessions,
    is_personal_session_id,
)


# --- fixtures ----------------------------------------------------------------

def _mk_user(db, email, plan="team"):
    user = User(
        email=email,
        name=email.split("@")[0].title(),
        password_hash=generate_password_hash("ValidPass1", method="pbkdf2:sha256"),
        subscription_plan=plan,
        subscription_status="active",
        credits_remaining=1000,
        seat_limit=5,
        max_seats=5,
    )
    db.session.add(user)
    db.session.commit()
    return user


def _mk_org(db, owner, name="Acme", plan="team"):
    org = Organization(name=name, slug=f"{name.lower()}-{owner.id[:6]}",
                       owner_user_id=owner.id, plan_key=plan)
    db.session.add(org)
    db.session.flush()
    db.session.add(OrganizationMember(
        organization_id=org.id, user_id=owner.id, role="owner", status="active"
    ))
    owner.active_organization_id = org.id
    db.session.commit()
    return org


def _add_member(db, org, user, role="collaborator"):
    db.session.add(OrganizationMember(
        organization_id=org.id, user_id=user.id, role=role, status="active"
    ))
    user.active_organization_id = org.id
    db.session.commit()


def _headers(app, user):
    with app.app_context():
        return {"Authorization": f"Bearer {create_access_token(identity=str(user.id))}"}


def _seed_project(db, org, creator, session_id="proj-1", visibility="team"):
    row = UserSession(
        user_id=creator.id,
        session_id=session_id,
        name="Shared project",
        organization_id=org.id,
        created_by_user_id=creator.id,
        visibility=visibility,
        payload={
            "session_id": session_id,
            "name": "Shared project",
            "organization_id": org.id,
            "created_by_user_id": creator.id,
            "visibility": visibility,
            "chat_history": [],
        },
    )
    db.session.add(row)
    db.session.commit()
    return row


@pytest.fixture
def team_setup(db):
    owner = _mk_user(db, "owner@acme.test")
    org = _mk_org(db, owner)
    editor = _mk_user(db, "editor@acme.test")
    _add_member(db, org, editor, role="collaborator")
    return {"org": org, "owner": owner, "editor": editor}


# --- A. solo-user behaviour is unchanged -------------------------------------

def test_solo_user_project_still_saves_and_loads(client, app, db):
    solo = _mk_user(db, "solo@example.test", plan="free")
    headers = _headers(app, solo)

    resp = client.post("/api/v1/sessions", headers=headers, json={
        "session_id": "solo-1", "name": "My idea", "chat_history": [],
    })
    assert resp.status_code == 200, resp.get_json()
    assert resp.get_json()["success"] is True

    got = client.get("/api/v1/sessions/solo-1", headers=headers)
    assert got.status_code == 200
    assert got.get_json()["session"]["name"] == "My idea"

    rows = UserSession.query.filter_by(session_id="solo-1").all()
    assert len(rows) == 1
    assert rows[0].user_id == solo.id
    assert rows[0].created_by_user_id == solo.id


def test_organization_is_derived_server_side_when_client_omits_it(client, app, db):
    """A save that omits organization_id must not detach the project."""
    solo = _mk_user(db, "derive@example.test", plan="free")
    org = _mk_org(db, solo, name="Derive", plan="free")
    headers = _headers(app, solo)

    client.post("/api/v1/sessions", headers=headers,
                json={"session_id": "derive-1", "name": "Idea"})

    row = UserSession.query.filter_by(session_id="derive-1").one()
    assert row.organization_id == org.id


# --- B / D. one canonical row; a collaborator save does not fork -------------

def test_collaborator_save_updates_canonical_row_and_does_not_fork(client, app, db, team_setup):
    org, owner, editor = team_setup["org"], team_setup["owner"], team_setup["editor"]
    _seed_project(db, org, owner, session_id="proj-1")

    resp = client.post("/api/v1/sessions", headers=_headers(app, editor), json={
        "session_id": "proj-1",
        "name": "Shared project (edited by B)",
        "chat_history": [{"role": "user", "content": "hello"}],
        "base_revision": 1,
    })
    assert resp.status_code == 200, resp.get_json()

    rows = UserSession.query.filter_by(session_id="proj-1").all()
    assert len(rows) == 1, "collaborator save forked the project into a second row"

    row = rows[0]
    assert row.organization_id == org.id
    # Attribution is intact: ownership moved to the org, authorship did not move
    # to the editor.
    assert row.user_id == owner.id
    assert row.created_by_user_id == owner.id
    # ...and the editor is recorded as the last writer.
    assert row.last_edited_by_user_id == editor.id
    assert row.name == "Shared project (edited by B)"


def test_collaborator_reads_the_same_canonical_row(client, app, db, team_setup):
    org, owner, editor = team_setup["org"], team_setup["owner"], team_setup["editor"]
    _seed_project(db, org, owner, session_id="proj-read")

    resp = client.get("/api/v1/sessions/proj-read", headers=_headers(app, editor))
    assert resp.status_code == 200, resp.get_json()
    assert resp.get_json()["session"]["created_by_user_id"] == owner.id


def test_canonical_resolution_prefers_the_oldest_row(db, team_setup):
    """A historical fork must never displace the original."""
    from datetime import datetime, timedelta

    org, owner, editor = team_setup["org"], team_setup["owner"], team_setup["editor"]
    original = _seed_project(db, org, owner, session_id="forked")
    original.created_at = datetime.utcnow() - timedelta(days=5)

    fork = UserSession(
        user_id=editor.id, session_id="forked", name="fork",
        organization_id=org.id, created_by_user_id=owner.id,
        visibility="team", payload={"session_id": "forked"},
        created_at=datetime.utcnow(),
    )
    db.session.add(fork)
    db.session.commit()

    assert canonical_row(editor, "forked").id == original.id
    assert canonical_row(owner, "forked").id == original.id


# --- L. the migration's duplicate detector -----------------------------------

def test_find_forked_sessions_reports_duplicates_without_mutating(db, team_setup):
    org, owner, editor = team_setup["org"], team_setup["owner"], team_setup["editor"]
    _seed_project(db, org, owner, session_id="dupe")
    db.session.add(UserSession(
        user_id=editor.id, session_id="dupe", name="fork",
        organization_id=org.id, created_by_user_id=owner.id,
        visibility="team", payload={"session_id": "dupe"},
    ))
    db.session.commit()

    found = find_forked_sessions(organization_id=org.id)
    assert len(found) == 1
    entry = found[0]
    assert entry["session_id"] == "dupe"
    assert entry["count"] == 2
    assert entry["canonical_row_id"] == entry["row_ids"][0]
    # Nothing was deleted or merged.
    assert UserSession.query.filter_by(session_id="dupe").count() == 2


def test_personal_sessions_are_never_reported_as_forks(db, team_setup):
    """Two members' `__user_memory__` rows are correct, not duplicates."""
    org, owner, editor = team_setup["org"], team_setup["owner"], team_setup["editor"]
    for user in (owner, editor):
        db.session.add(UserSession(
            user_id=user.id, session_id="__user_memory__", name="__user_memory__",
            document_type="memory", organization_id=org.id,
            created_by_user_id=user.id, payload={"session_id": "__user_memory__"},
        ))
    db.session.commit()

    assert find_forked_sessions(organization_id=org.id) == []


# --- backward compatibility: `__user_memory__` stays personal ----------------

def test_user_memory_sentinel_is_personal_scope():
    assert "__user_memory__" in PERSONAL_SESSION_IDS
    assert is_personal_session_id("__user_memory__") is True
    assert is_personal_session_id("proj-1") is False


def test_user_memory_never_receives_a_server_derived_organization(client, app, db, team_setup):
    org, owner = team_setup["org"], team_setup["owner"]

    client.post("/api/v1/sessions", headers=_headers(app, owner), json={
        "session_id": "__user_memory__",
        "name": "__user_memory__",
        "document_type": "memory",
        "memory_facts": {"industry": "logistics"},
    })

    row = UserSession.query.filter_by(
        user_id=owner.id, session_id="__user_memory__"
    ).one()
    assert row.organization_id is None, (
        "the cross-session memory sentinel was swept into organization ownership"
    )


def test_members_do_not_resolve_each_others_user_memory(db, team_setup):
    org, owner, editor = team_setup["org"], team_setup["owner"], team_setup["editor"]
    owner_memory = UserSession(
        user_id=owner.id, session_id="__user_memory__", name="__user_memory__",
        document_type="memory", created_by_user_id=owner.id,
        payload={"session_id": "__user_memory__", "memory_facts": {"a": 1}},
    )
    db.session.add(owner_memory)
    db.session.commit()

    # The editor has no memory row of their own and must NOT inherit the
    # owner's just because they share an organization.
    assert canonical_row(editor, "__user_memory__") is None
    assert canonical_row(owner, "__user_memory__").id == owner_memory.id


# --- unrelated durable artifacts are untouched -------------------------------

def test_scorecards_are_not_altered_by_session_ownership_changes(db, team_setup):
    from app.models import Scorecard

    org, owner = team_setup["org"], team_setup["owner"]
    card = Scorecard(
        id="sc-1", user_id=owner.id, organization_id=org.id,
        thread_id="proj-1", project_name="Shared project", data={},
    )
    db.session.add(card)
    db.session.commit()

    _seed_project(db, org, owner, session_id="proj-1")

    refreshed = Scorecard.query.get("sc-1")
    assert refreshed.user_id == owner.id
    assert refreshed.organization_id == org.id


# ── scenario storage must not fork the canonical row ─────────────────────────

def test_scenario_writes_do_not_fork_a_shared_project(db, team_setup):
    """Found in the final foundation review.

    save_scenarios_data() looked its target row up by the CALLER's user_id, so
    a collaborator writing scenario data to a shared project inserted a second
    row under themselves -- the same silent fork Phase 1 removed from the
    session save path, reachable through a side door.
    """
    from app.scenarios_store import save_scenarios_data

    org, owner, editor = team_setup["org"], team_setup["owner"], team_setup["editor"]
    _seed_project(db, org, owner, session_id="sc-shared", visibility="team")

    save_scenarios_data(editor.id, {"sc-shared": {"scenarios": {"a": {"label": "A"}}}})

    rows = UserSession.query.filter_by(session_id="sc-shared").all()
    assert len(rows) == 1, "scenario write forked the shared project"

    row = rows[0]
    assert row.user_id == owner.id, "attribution moved to the collaborator"
    assert row.created_by_user_id == owner.id
    assert row.organization_id == org.id
    assert row.scenarios_json["scenarios"]["a"]["label"] == "A"


def test_scenario_writes_still_create_a_row_for_a_new_thread(db, team_setup):
    """No canonical row yet: create one, bound to the organization."""
    from app.scenarios_store import save_scenarios_data

    org, owner = team_setup["org"], team_setup["owner"]
    save_scenarios_data(owner.id, {"sc-brand-new": {"scenarios": {}}})

    row = UserSession.query.filter_by(session_id="sc-brand-new").one()
    assert row.user_id == owner.id
    assert row.created_by_user_id == owner.id
    assert row.organization_id == org.id, "a new scenario row was detached from its org"


def test_solo_scenario_writes_are_unchanged(db):
    from app.scenarios_store import save_scenarios_data, load_scenarios_data

    solo = _mk_user(db, "sc-solo@example.test", plan="free")
    org = _mk_org(db, solo, name="ScSolo", plan="free")
    _seed_project(db, org, solo, session_id="sc-solo", visibility="private")

    save_scenarios_data(solo.id, {"sc-solo": {"scenarios": {"x": {"label": "X"}}}})

    assert UserSession.query.filter_by(session_id="sc-solo").count() == 1
    assert load_scenarios_data(solo.id)["sc-solo"]["scenarios"]["x"]["label"] == "X"


def test_team_page_and_workspace_resolve_the_same_canonical_row(db, team_setup):
    """Found in the canonical-write audit.

    _get_project_row ordered by updated_at DESC while canonical_row orders by
    created_at ASC -- two resolution rules for one (organization_id,
    session_id) pair. With a historical fork present, the Team page's sharing,
    comments and activity writes landed on the fork while the workspace wrote
    to the canonical row.
    """
    from datetime import datetime, timedelta
    from app.routes.team import _get_project_row

    org, owner, editor = team_setup["org"], team_setup["owner"], team_setup["editor"]

    original = _seed_project(db, org, owner, session_id="split", visibility="team")
    original.created_at = datetime.utcnow() - timedelta(days=5)
    original.updated_at = datetime.utcnow() - timedelta(days=5)

    # A historical fork that has been touched more recently.
    db.session.add(UserSession(
        user_id=editor.id, session_id="split", name="fork",
        organization_id=org.id, created_by_user_id=owner.id, visibility="team",
        payload={"session_id": "split"},
        created_at=datetime.utcnow(),
        updated_at=datetime.utcnow(),
    ))
    db.session.commit()

    assert _get_project_row(org.id, "split").id == original.id
    assert canonical_row(owner, "split").id == original.id
    assert _get_project_row(org.id, "split").id == canonical_row(owner, "split").id
