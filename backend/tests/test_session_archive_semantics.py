"""Phase 1: personal hide vs organization archive (audit risk R6).

Under canonical organization ownership, "delete from my history" must not
reach `archived_at` / `purge_after` on shared organizational work -- those
schedule a purge that would destroy the canonical row for everyone.
"""
import pytest

from app.models import UserSession
from app.routes.sessions import (
    archive_user_session,
    load_user_sessions,
    restore_user_session,
)
from app.session_access import (
    SessionForbidden,
    hidden_ids,
    is_hidden_for,
    uses_personal_hide,
)

from tests.test_session_org_ownership import (
    _add_member,
    _headers,
    _mk_org,
    _mk_user,
    _seed_project,
    team_setup,
)


# --- I. a member cannot archive organizational work --------------------------

def test_member_removing_shared_work_hides_it_instead_of_archiving(db, team_setup):
    org, owner, editor = team_setup["org"], team_setup["owner"], team_setup["editor"]
    row = _seed_project(db, org, owner, session_id="a-shared", visibility="team")

    assert uses_personal_hide(row, editor) is True
    archive_user_session(editor.id, "a-shared")

    refreshed = UserSession.query.filter_by(session_id="a-shared").one()
    assert refreshed.archived_at is None, "a member scheduled a purge of org work"
    assert refreshed.purge_after is None
    assert is_hidden_for(refreshed, editor.id) is True
    assert is_hidden_for(refreshed, owner.id) is False


def test_hidden_project_disappears_from_that_members_lists_only(client, app, db, team_setup):
    """The hide takes effect on both surfaces a member sees a project through:
    their own history, and the shared-projects list."""
    org, owner, editor = team_setup["org"], team_setup["owner"], team_setup["editor"]
    _seed_project(db, org, owner, session_id="a-hist", visibility="team")

    def shared_ids(user):
        resp = client.get("/api/v1/team/projects", headers=_headers(app, user))
        assert resp.status_code == 200, resp.get_json()
        return {p["session_id"] for p in resp.get_json()["projects"]}

    assert "a-hist" in shared_ids(editor)

    archive_user_session(editor.id, "a-hist")

    assert "a-hist" not in shared_ids(editor)
    assert "a-hist" in shared_ids(owner)
    # The owner's own history is untouched.
    assert "a-hist" in load_user_sessions(owner.id)


def test_creator_removing_their_own_SHARED_project_only_hides_it(db, team_setup):
    """The strict half of the rule.

    A collaborator who created a project and shared it to the team is still a
    normal member: removing it from their history must not schedule a purge of
    work other people now rely on. Only an owner/admin archives from here.
    """
    org, editor = team_setup["org"], team_setup["editor"]
    _seed_project(db, org, editor, session_id="a-own-hist", visibility="team")

    assert "a-own-hist" in load_user_sessions(editor.id)
    archive_user_session(editor.id, "a-own-hist")
    assert "a-own-hist" not in load_user_sessions(editor.id)

    row = UserSession.query.filter_by(session_id="a-own-hist").one()
    assert row.archived_at is None
    assert row.purge_after is None
    assert is_hidden_for(row, editor.id) is True


def test_delete_endpoint_reports_the_scope_it_used(client, app, db, team_setup):
    org, owner, editor = team_setup["org"], team_setup["owner"], team_setup["editor"]
    _seed_project(db, org, owner, session_id="a-scope", visibility="team")

    resp = client.delete("/api/v1/sessions/a-scope", headers=_headers(app, editor))
    assert resp.status_code == 200, resp.get_json()
    assert resp.get_json()["scope"] == "personal"

    assert UserSession.query.filter_by(session_id="a-scope").one().archived_at is None


def test_scorecards_are_not_archived_by_a_personal_hide(db, team_setup):
    from app.models import Scorecard

    org, owner, editor = team_setup["org"], team_setup["owner"], team_setup["editor"]
    _seed_project(db, org, owner, session_id="a-cards", visibility="team")
    db.session.add(Scorecard(
        id="sc-hide", user_id=owner.id, organization_id=org.id,
        thread_id="a-cards", project_name="Shared project", data={},
    ))
    db.session.commit()

    archive_user_session(editor.id, "a-cards")

    assert Scorecard.query.get("sc-hide").archived_at is None


# --- J. an authorized organization archive still works -----------------------

def test_owner_archive_still_schedules_the_purge(db, team_setup):
    org, owner = team_setup["org"], team_setup["owner"]
    _seed_project(db, org, owner, session_id="a-org", visibility="team")

    archive_user_session(owner.id, "a-org")

    row = UserSession.query.filter_by(session_id="a-org").one()
    assert row.archived_at is not None
    assert row.purge_after is not None


def test_admin_can_archive_work_they_did_not_create(db, team_setup):
    org, owner = team_setup["org"], team_setup["owner"]
    admin = _mk_user(db, "arch-admin@acme.test")
    _add_member(db, org, admin, role="admin")
    _seed_project(db, org, owner, session_id="a-admin", visibility="team")

    archive_user_session(admin.id, "a-admin")
    assert UserSession.query.filter_by(session_id="a-admin").one().archived_at is not None


def test_collaborator_cannot_permanently_purge_organizational_work(db, team_setup):
    from app.routes.sessions import hard_delete_user_session

    org, owner, editor = team_setup["org"], team_setup["owner"], team_setup["editor"]
    _seed_project(db, org, owner, session_id="a-purge", visibility="team")

    with pytest.raises(SessionForbidden):
        hard_delete_user_session(editor.id, "a-purge")

    assert UserSession.query.filter_by(session_id="a-purge").count() == 1


# --- solo users keep today's behaviour exactly -------------------------------

def test_solo_user_delete_still_archives_with_a_purge_window(client, app, db):
    solo = _mk_user(db, "arch-solo@example.test", plan="free")
    org = _mk_org(db, solo, name="ArchSolo", plan="free")
    _seed_project(db, org, solo, session_id="a-solo", visibility="private")

    resp = client.delete("/api/v1/sessions/a-solo", headers=_headers(app, solo))
    assert resp.status_code == 200, resp.get_json()
    assert resp.get_json()["scope"] == "organization"

    row = UserSession.query.filter_by(session_id="a-solo").one()
    assert row.archived_at is not None
    assert row.purge_after is not None
    assert hidden_ids(row) == []


def test_creator_deleting_their_own_private_project_in_a_team_org_archives(db, team_setup):
    """Private work in a team org is still the creator's to archive."""
    org, owner = team_setup["org"], team_setup["owner"]
    row = _seed_project(db, org, owner, session_id="a-priv", visibility="private")

    assert uses_personal_hide(row, owner) is False
    archive_user_session(owner.id, "a-priv")
    assert UserSession.query.filter_by(session_id="a-priv").one().archived_at is not None


# --- restore ----------------------------------------------------------------

def test_restore_clears_a_personal_hide(db, team_setup):
    org, editor = team_setup["org"], team_setup["editor"]
    _seed_project(db, org, editor, session_id="a-restore", visibility="team")

    archive_user_session(editor.id, "a-restore")
    assert "a-restore" not in load_user_sessions(editor.id)

    restore_user_session(editor.id, "a-restore")
    assert "a-restore" in load_user_sessions(editor.id)


def test_restore_lifts_an_organization_archive_for_an_entitled_member(db, team_setup):
    org, owner = team_setup["org"], team_setup["owner"]
    _seed_project(db, org, owner, session_id="a-restore-org", visibility="team")

    archive_user_session(owner.id, "a-restore-org")
    restore_user_session(owner.id, "a-restore-org")

    row = UserSession.query.filter_by(session_id="a-restore-org").one()
    assert row.archived_at is None
    assert row.purge_after is None


def test_hiding_never_affects_the_purge_sweep_window(db, team_setup):
    """The sweep selects on purge_after; a hide must never populate it."""
    org, owner, editor = team_setup["org"], team_setup["owner"], team_setup["editor"]
    _seed_project(db, org, owner, session_id="a-sweep", visibility="team")

    archive_user_session(editor.id, "a-sweep")

    sweepable = UserSession.query.filter(UserSession.purge_after.isnot(None)).all()
    assert [r.session_id for r in sweepable] == []
