"""Phase 1: authorization on the canonical organization-owned session.

Access is decided by ORGANIZATION MEMBERSHIP and role, never by
`row.user_id == current_user.id`. Authorization runs before the row is
returned, so nothing downstream can assemble a response out of a row the
caller may not read.
"""
import pytest

from app.models import UserSession
from app.session_access import (
    SessionForbidden,
    SessionNotFound,
    can_read_session,
    can_write_session,
    resolve_session_for_actor,
)

from tests.test_session_org_ownership import (  # reuse the fixtures/builders
    _add_member,
    _headers,
    _mk_org,
    _mk_user,
    _seed_project,
    team_setup,
)


@pytest.fixture
def cast(db, team_setup):
    """One organization with every role, plus an outsider."""
    org, owner = team_setup["org"], team_setup["owner"]

    admin = _mk_user(db, "admin@acme.test")
    _add_member(db, org, admin, role="admin")
    creator = _mk_user(db, "creator@acme.test")
    _add_member(db, org, creator, role="creator")
    viewer = _mk_user(db, "viewer@acme.test")
    _add_member(db, org, viewer, role="viewer")

    outsider = _mk_user(db, "outsider@other.test")
    _mk_org(db, outsider, name="Other")

    return {
        "org": org,
        "owner": owner,
        "admin": admin,
        "creator": creator,
        "editor": team_setup["editor"],   # collaborator
        "viewer": viewer,
        "outsider": outsider,
    }


# --- read -------------------------------------------------------------------

@pytest.mark.parametrize("role", ["owner", "admin", "creator", "editor", "viewer"])
def test_every_member_can_read_a_team_visible_project(db, cast, role):
    row = _seed_project(db, cast["org"], cast["owner"], session_id="t-read",
                        visibility="team")
    assert can_read_session(row, cast[role]) is True


def test_outsider_cannot_read(db, cast):
    row = _seed_project(db, cast["org"], cast["owner"], session_id="t-out",
                        visibility="team")
    assert can_read_session(row, cast["outsider"]) is False


def test_outsider_gets_not_found_not_forbidden(client, app, db, cast):
    """A non-member must not be able to probe which session ids exist."""
    _seed_project(db, cast["org"], cast["owner"], session_id="t-probe",
                  visibility="team")
    resp = client.get("/api/v1/sessions/t-probe", headers=_headers(app, cast["outsider"]))
    assert resp.status_code == 404
    assert resp.get_json()["code"] == "not_found"


def test_private_project_is_not_readable_by_other_members(db, cast):
    row = _seed_project(db, cast["org"], cast["owner"], session_id="t-priv",
                        visibility="private")
    assert can_read_session(row, cast["owner"]) is True
    assert can_read_session(row, cast["editor"]) is False
    assert can_read_session(row, cast["admin"]) is False


def test_specific_visibility_honours_the_share_list(db, cast):
    row = _seed_project(db, cast["org"], cast["owner"], session_id="t-spec",
                        visibility="specific")
    row.shared_with_user_ids = [cast["editor"].id]
    db.session.commit()

    assert can_read_session(row, cast["editor"]) is True
    assert can_read_session(row, cast["viewer"]) is False


def test_removed_member_loses_access_even_though_the_row_still_names_the_org(db, cast):
    from app.models import OrganizationMember

    row = _seed_project(db, cast["org"], cast["owner"], session_id="t-gone",
                        visibility="team")
    assert can_read_session(row, cast["editor"]) is True

    OrganizationMember.query.filter_by(
        organization_id=cast["org"].id, user_id=cast["editor"].id
    ).delete()
    db.session.commit()

    assert can_read_session(row, cast["editor"]) is False


# --- write ------------------------------------------------------------------

@pytest.mark.parametrize("role", ["owner", "admin", "creator", "editor"])
def test_editing_roles_can_write(db, cast, role):
    row = _seed_project(db, cast["org"], cast["owner"], session_id="t-write",
                        visibility="team")
    assert can_write_session(row, cast[role]) is True


def test_viewer_cannot_write(db, cast):
    row = _seed_project(db, cast["org"], cast["owner"], session_id="t-view",
                        visibility="team")
    assert can_read_session(row, cast["viewer"]) is True
    assert can_write_session(row, cast["viewer"]) is False


def test_viewer_write_is_refused_with_403(client, app, db, cast):
    _seed_project(db, cast["org"], cast["owner"], session_id="t-403",
                  visibility="team")
    resp = client.post("/api/v1/sessions", headers=_headers(app, cast["viewer"]), json={
        "session_id": "t-403", "name": "viewer tried to edit", "base_revision": 1,
    })
    assert resp.status_code == 403
    assert resp.get_json()["code"] == "forbidden"

    # ...and nothing changed.
    row = UserSession.query.filter_by(session_id="t-403").one()
    assert row.name == "Shared project"
    assert int(row.revision) == 1


def test_viewer_is_read_only_even_on_work_they_created(db, cast):
    """The seat is the entitlement, not the authorship."""
    row = _seed_project(db, cast["org"], cast["viewer"], session_id="t-own",
                        visibility="team")
    assert can_read_session(row, cast["viewer"]) is True
    assert can_write_session(row, cast["viewer"]) is False


def test_solo_org_owner_can_read_and_write_their_own(db):
    solo = _mk_user(db, "solo-auth@example.test", plan="free")
    org = _mk_org(db, solo, name="SoloAuth", plan="free")
    row = _seed_project(db, org, solo, session_id="t-solo", visibility="private")

    assert can_read_session(row, solo) is True
    assert can_write_session(row, solo) is True


# --- the chokepoint ---------------------------------------------------------

def test_resolve_raises_before_returning_a_row(db, cast):
    _seed_project(db, cast["org"], cast["owner"], session_id="t-choke",
                  visibility="team")

    row, membership = resolve_session_for_actor(cast["editor"], "t-choke")
    assert row.session_id == "t-choke"
    assert membership is not None

    with pytest.raises(SessionNotFound):
        resolve_session_for_actor(cast["outsider"], "t-choke")

    with pytest.raises(SessionForbidden):
        resolve_session_for_actor(cast["viewer"], "t-choke", require_write=True)


# --- M. the Shared Projects defect -----------------------------------------

def test_authorized_collaborator_opens_the_thread_endpoint(client, app, db, cast):
    """PHASE 0. This is the exact call the Shared Projects card makes.

    It used to 404 for every non-owner while the card advertised "Can edit".
    """
    _seed_project(db, cast["org"], cast["owner"], session_id="t-card",
                  visibility="team")

    resp = client.get("/api/v1/ai-agent/threads/t-card",
                      headers=_headers(app, cast["editor"]))
    assert resp.status_code == 200, resp.get_json()
    assert resp.get_json()["thread"]["id"] == "t-card"


def test_owner_still_opens_the_thread_endpoint(client, app, db, cast):
    _seed_project(db, cast["org"], cast["owner"], session_id="t-card-owner",
                  visibility="team")
    resp = client.get("/api/v1/ai-agent/threads/t-card-owner",
                      headers=_headers(app, cast["owner"]))
    assert resp.status_code == 200, resp.get_json()


def test_outsider_cannot_open_the_thread_endpoint(client, app, db, cast):
    _seed_project(db, cast["org"], cast["owner"], session_id="t-card-out",
                  visibility="team")
    resp = client.get("/api/v1/ai-agent/threads/t-card-out",
                      headers=_headers(app, cast["outsider"]))
    assert resp.status_code == 404


def test_shared_project_payload_reports_truthful_access(client, app, db, cast):
    """The card's label comes from the backend now, not from a role guess."""
    _seed_project(db, cast["org"], cast["owner"], session_id="t-label",
                  visibility="team")

    for role, expect_edit in (("editor", True), ("viewer", False)):
        resp = client.get("/api/v1/team/projects", headers=_headers(app, cast[role]))
        assert resp.status_code == 200, resp.get_json()
        project = next(
            p for p in resp.get_json()["projects"] if p["session_id"] == "t-label"
        )
        assert project["can_read"] is True
        assert project["can_edit"] is expect_edit
