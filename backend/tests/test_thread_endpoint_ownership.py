"""Phase 0 + Phase 1 at the AI-agent thread endpoints.

These are the endpoints the workspace actually uses, so they are where the
Shared Projects defect lived and where a regression for existing individual
users would show up first.
"""
import pytest

from app.models import UserSession

from tests.test_session_org_ownership import (
    _add_member,
    _headers,
    _mk_org,
    _mk_user,
    _seed_project,
    team_setup,
)


@pytest.fixture
def viewer_setup(db, team_setup):
    viewer = _mk_user(db, "t-viewer@acme.test")
    _add_member(db, team_setup["org"], viewer, role="viewer")
    return {**team_setup, "viewer": viewer}


# --- individual users are unaffected ----------------------------------------

def test_solo_user_opens_their_own_thread(client, app, db):
    solo = _mk_user(db, "th-solo@example.test", plan="free")
    org = _mk_org(db, solo, name="ThSolo", plan="free")
    _seed_project(db, org, solo, session_id="th-solo", visibility="private")

    resp = client.get("/api/v1/ai-agent/threads/th-solo", headers=_headers(app, solo))
    assert resp.status_code == 200, resp.get_json()
    assert resp.get_json()["thread"]["revision"] == 1


def test_thread_payload_exposes_the_revision_token(client, app, db, team_setup):
    org, owner = team_setup["org"], team_setup["owner"]
    row = _seed_project(db, org, owner, session_id="th-rev")
    row.revision = 4
    db.session.commit()

    resp = client.get("/api/v1/ai-agent/threads/th-rev", headers=_headers(app, owner))
    assert resp.get_json()["thread"]["revision"] == 4


# --- Phase 0: the Shared Projects journey end to end ------------------------

def test_collaborator_opens_a_shared_thread(client, app, db, team_setup):
    org, owner, editor = team_setup["org"], team_setup["owner"], team_setup["editor"]
    _seed_project(db, org, owner, session_id="th-shared", visibility="team")

    resp = client.get("/api/v1/ai-agent/threads/th-shared", headers=_headers(app, editor))
    assert resp.status_code == 200, resp.get_json()
    thread = resp.get_json()["thread"]
    assert thread["id"] == "th-shared"
    assert thread["created_by_user_id"] == owner.id


def test_viewer_can_open_but_not_rename_a_shared_thread(client, app, db, viewer_setup):
    org, owner, viewer = viewer_setup["org"], viewer_setup["owner"], viewer_setup["viewer"]
    _seed_project(db, org, owner, session_id="th-ro", visibility="team")

    assert client.get("/api/v1/ai-agent/threads/th-ro",
                      headers=_headers(app, viewer)).status_code == 200

    resp = client.patch("/api/v1/ai-agent/threads/th-ro",
                        headers=_headers(app, viewer), json={"name": "renamed"})
    assert resp.status_code == 403
    assert resp.get_json()["code"] == "forbidden"
    assert UserSession.query.filter_by(session_id="th-ro").one().name == "Shared project"


def test_collaborator_rename_updates_the_canonical_row_without_forking(client, app, db, team_setup):
    org, owner, editor = team_setup["org"], team_setup["owner"], team_setup["editor"]
    _seed_project(db, org, owner, session_id="th-rename", visibility="team")

    resp = client.patch("/api/v1/ai-agent/threads/th-rename",
                        headers=_headers(app, editor),
                        json={"name": "Renamed by B", "base_revision": 1})
    assert resp.status_code == 200, resp.get_json()

    rows = UserSession.query.filter_by(session_id="th-rename").all()
    assert len(rows) == 1
    assert rows[0].name == "Renamed by B"
    assert rows[0].created_by_user_id == owner.id
    assert rows[0].last_edited_by_user_id == editor.id


def test_patch_rejects_a_stale_revision(client, app, db, team_setup):
    org, owner, editor = team_setup["org"], team_setup["owner"], team_setup["editor"]
    _seed_project(db, org, owner, session_id="th-stale", visibility="team")

    client.patch("/api/v1/ai-agent/threads/th-stale",
                 headers=_headers(app, editor),
                 json={"name": "first", "base_revision": 1})

    resp = client.patch("/api/v1/ai-agent/threads/th-stale",
                        headers=_headers(app, owner),
                        json={"name": "second", "base_revision": 1})
    assert resp.status_code == 409
    assert resp.get_json()["code"] == "revision_conflict"
    assert UserSession.query.filter_by(session_id="th-stale").one().name == "first"


def test_patch_on_shared_work_requires_a_revision(client, app, db, team_setup):
    """PHASE 1.1: missing is rejected, not silently accepted."""
    org, owner = team_setup["org"], team_setup["owner"]
    _seed_project(db, org, owner, session_id="th-nodecl", visibility="team")

    resp = client.patch("/api/v1/ai-agent/threads/th-nodecl",
                        headers=_headers(app, owner), json={"name": "renamed"})
    assert resp.status_code == 409
    assert resp.get_json()["code"] == "revision_conflict"
    assert UserSession.query.filter_by(session_id="th-nodecl").one().name == "Shared project"


def test_patch_on_private_work_does_not_require_a_revision(client, app, db, team_setup):
    """Unshared work is exempt, so individual usage is untouched."""
    org, owner = team_setup["org"], team_setup["owner"]
    _seed_project(db, org, owner, session_id="th-priv-patch", visibility="private")

    resp = client.patch("/api/v1/ai-agent/threads/th-priv-patch",
                        headers=_headers(app, owner), json={"name": "renamed"})
    assert resp.status_code == 200, resp.get_json()


def test_outsider_cannot_reach_any_thread_endpoint(client, app, db, team_setup):
    org, owner = team_setup["org"], team_setup["owner"]
    outsider = _mk_user(db, "th-out@other.test")
    _mk_org(db, outsider, name="ThOther")
    _seed_project(db, org, owner, session_id="th-out", visibility="team")

    headers = _headers(app, outsider)
    assert client.get("/api/v1/ai-agent/threads/th-out", headers=headers).status_code == 404
    assert client.patch("/api/v1/ai-agent/threads/th-out", headers=headers,
                        json={"name": "x"}).status_code == 404
    assert client.post("/api/v1/ai-agent/threads/th-out/touch",
                       headers=headers).status_code == 404
    assert client.get("/api/v1/ai-agent/threads/th-out/levers",
                      headers=headers).status_code == 404


def test_delete_thread_hides_for_a_collaborator_and_archives_for_the_owner(client, app, db, team_setup):
    org, owner, editor = team_setup["org"], team_setup["owner"], team_setup["editor"]
    _seed_project(db, org, owner, session_id="th-del", visibility="team")

    hide = client.delete("/api/v1/ai-agent/threads/th-del", headers=_headers(app, editor))
    assert hide.status_code == 200, hide.get_json()
    assert hide.get_json()["scope"] == "personal"
    assert UserSession.query.filter_by(session_id="th-del").one().archived_at is None

    arch = client.delete("/api/v1/ai-agent/threads/th-del", headers=_headers(app, owner))
    assert arch.status_code == 200, arch.get_json()
    assert arch.get_json()["scope"] == "organization"
    assert UserSession.query.filter_by(session_id="th-del").one().archived_at is not None


def test_collaborator_cannot_purge_a_shared_thread(client, app, db, team_setup):
    org, owner, editor = team_setup["org"], team_setup["owner"], team_setup["editor"]
    _seed_project(db, org, owner, session_id="th-purge", visibility="team")

    resp = client.post("/api/v1/ai-agent/threads/th-purge/purge",
                       headers=_headers(app, editor))
    assert resp.status_code == 403
    assert UserSession.query.filter_by(session_id="th-purge").count() == 1
