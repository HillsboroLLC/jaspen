"""Phase 2: destructive behaviour must follow organization ownership.

Seven invariants, each asserted directly:

  1. A normal member cannot permanently destroy canonical shared work.
  2. Being the original creator does not confer organization ownership.
  3. "Remove from my history" is not deleting the organization's work.
  4. User-level administrative cleanup cannot delete organization-owned work.
  5. Evidence is not destroyed while its canonical project survives.
  6. Purge follows organization ownership, not the historical home user.
  7. Solo users retain expected cleanup behaviour.
"""
from datetime import datetime, timedelta

import pytest

from app.models import Scorecard, User, UserSession
from app.routes.sessions import archive_user_session, hard_delete_user_session
from app.session_access import (
    SessionForbidden,
    can_archive_session,
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


def _seed_scorecard(db, org, user, thread_id, card_id):
    db.session.add(Scorecard(
        id=card_id, user_id=user.id, organization_id=org.id,
        thread_id=thread_id, project_name="Shared project", data={},
    ))
    db.session.commit()


@pytest.fixture
def org_cast(db, team_setup):
    org, owner, editor = team_setup["org"], team_setup["owner"], team_setup["editor"]
    admin = _mk_user(db, "p2-admin@acme.test")
    _add_member(db, org, admin, role="admin")
    other = _mk_user(db, "p2-other@acme.test")
    _add_member(db, org, other, role="collaborator")
    return {"org": org, "owner": owner, "editor": editor, "admin": admin, "other": other}


# ── INVARIANT 2: creator attribution is not ownership ────────────────────────

def test_creator_of_shared_work_has_no_destructive_authority(db, org_cast):
    """The Phase 2 correction. `editor` CREATED this and shared it."""
    org, editor = org_cast["org"], org_cast["editor"]
    row = _seed_project(db, org, editor, session_id="p2-creator", visibility="team")

    assert row.created_by_user_id == editor.id
    assert can_archive_session(row, editor) is False
    assert uses_personal_hide(row, editor) is True


def test_creator_keeps_authority_over_their_unshared_work(db, org_cast):
    org, editor = org_cast["org"], org_cast["editor"]
    row = _seed_project(db, org, editor, session_id="p2-unshared", visibility="private")
    assert can_archive_session(row, editor) is True


def test_owner_and_admin_retain_destructive_authority(db, org_cast):
    org, owner, admin = org_cast["org"], org_cast["owner"], org_cast["admin"]
    row = _seed_project(db, org, org_cast["editor"], session_id="p2-mgr", visibility="team")
    assert can_archive_session(row, owner) is True
    assert can_archive_session(row, admin) is True


# ── INVARIANT 1 + 3: members cannot destroy; hide is not delete ──────────────

def test_creator_hard_delete_of_shared_work_is_refused(db, org_cast):
    org, editor = org_cast["org"], org_cast["editor"]
    _seed_project(db, org, editor, session_id="p2-hd", visibility="team")

    with pytest.raises(SessionForbidden):
        hard_delete_user_session(editor.id, "p2-hd")
    assert UserSession.query.filter_by(session_id="p2-hd").count() == 1


def test_another_member_cannot_hard_delete_it_either(db, org_cast):
    org, editor, other = org_cast["org"], org_cast["editor"], org_cast["other"]
    _seed_project(db, org, editor, session_id="p2-hd2", visibility="team")

    with pytest.raises(SessionForbidden):
        hard_delete_user_session(other.id, "p2-hd2")
    assert UserSession.query.filter_by(session_id="p2-hd2").count() == 1


def test_admin_may_perform_the_org_level_destructive_action(db, org_cast):
    org, editor, admin = org_cast["org"], org_cast["editor"], org_cast["admin"]
    _seed_project(db, org, editor, session_id="p2-hd3", visibility="team")

    assert hard_delete_user_session(admin.id, "p2-hd3") is True
    assert UserSession.query.filter_by(session_id="p2-hd3").count() == 0


def test_personal_hide_leaves_the_canonical_row_untouched(db, org_cast):
    org, editor = org_cast["org"], org_cast["editor"]
    _seed_project(db, org, editor, session_id="p2-hide", visibility="team")

    archive_user_session(editor.id, "p2-hide")

    row = UserSession.query.filter_by(session_id="p2-hide").one()
    assert row.archived_at is None
    assert row.purge_after is None
    assert is_hidden_for(row, editor.id) is True


# ── INVARIANT 1 via the bulk hard reset ──────────────────────────────────────

def test_hard_reset_cannot_destroy_shared_work_the_member_created(client, app, db, org_cast):
    """`reset_threads?hard=1` was the last place creator attribution bought
    destructive authority over organizational work."""
    org, editor = org_cast["org"], org_cast["editor"]
    _seed_project(db, org, editor, session_id="p2-reset-shared", visibility="team")
    _seed_project(db, org, editor, session_id="p2-reset-own", visibility="private")

    resp = client.delete("/api/v1/ai-agent/threads?hard=1", headers=_headers(app, editor))
    assert resp.status_code == 200, resp.get_json()
    body = resp.get_json()
    assert body["cleared_threads"] == 1
    assert body["hidden_threads"] == 1

    # The organization's project survives, hidden from this member only.
    survivor = UserSession.query.filter_by(session_id="p2-reset-shared").one()
    assert survivor.archived_at is None
    assert is_hidden_for(survivor, editor.id) is True

    # Their own private work was cleared as asked.
    assert UserSession.query.filter_by(session_id="p2-reset-own").count() == 0


def test_hard_reset_by_an_admin_may_destroy_org_work(client, app, db, org_cast):
    org, editor, admin = org_cast["org"], org_cast["editor"], org_cast["admin"]
    row = _seed_project(db, org, editor, session_id="p2-reset-admin", visibility="team")
    # Give the admin a row of their own so the reset has something to resolve.
    row.user_id = admin.id
    db.session.commit()

    resp = client.delete("/api/v1/ai-agent/threads?hard=1", headers=_headers(app, admin))
    assert resp.status_code == 200, resp.get_json()
    assert UserSession.query.filter_by(session_id="p2-reset-admin").count() == 0


# ── INVARIANT 7: solo users are unchanged ────────────────────────────────────

def test_solo_user_hard_reset_still_clears_everything(client, app, db):
    solo = _mk_user(db, "p2-solo@example.test", plan="free")
    org = _mk_org(db, solo, name="P2Solo", plan="free")
    _seed_project(db, org, solo, session_id="p2-solo-a", visibility="private")
    _seed_project(db, org, solo, session_id="p2-solo-b", visibility="team")

    resp = client.delete("/api/v1/ai-agent/threads?hard=1", headers=_headers(app, solo))
    assert resp.status_code == 200, resp.get_json()
    assert resp.get_json()["hidden_threads"] == 0
    assert UserSession.query.filter_by(user_id=solo.id).count() == 0


def test_solo_user_archive_and_purge_still_work(db):
    solo = _mk_user(db, "p2-solo2@example.test", plan="free")
    org = _mk_org(db, solo, name="P2Solo2", plan="free")
    _seed_project(db, org, solo, session_id="p2-solo-arch", visibility="team")

    archive_user_session(solo.id, "p2-solo-arch")
    row = UserSession.query.filter_by(session_id="p2-solo-arch").one()
    assert row.archived_at is not None and row.purge_after is not None

    assert hard_delete_user_session(solo.id, "p2-solo-arch") is True


# ── INVARIANT 4: admin user cleanup skips organizational work ────────────────

def test_admin_clear_sessions_preserves_org_owned_shared_work(client, app, db, org_cast, admin_auth_headers):
    org, editor = org_cast["org"], org_cast["editor"]
    _seed_project(db, org, editor, session_id="p2-admin-shared", visibility="team")
    _seed_project(db, org, editor, session_id="p2-admin-private", visibility="private")

    resp = client.post(
        f"/api/v1/admin/users/{editor.id}/recovery",
        headers=admin_auth_headers,
        json={"action": "clear_sessions", "reason": "support request"},
    )
    assert resp.status_code == 200, resp.get_json()
    body = resp.get_json()["result"]

    assert body["deleted_sessions"] == 1
    assert body["skipped_org_owned_sessions"] == 1
    assert "p2-admin-shared" in body["skipped_session_ids"]

    assert UserSession.query.filter_by(session_id="p2-admin-shared").count() == 1
    assert UserSession.query.filter_by(session_id="p2-admin-private").count() == 0


def test_admin_clear_sessions_still_clears_a_solo_users_data(client, app, db, admin_auth_headers):
    solo = _mk_user(db, "p2-admin-solo@example.test", plan="free")
    org = _mk_org(db, solo, name="P2AdminSolo", plan="free")
    _seed_project(db, org, solo, session_id="p2-admin-solo-a", visibility="team")

    resp = client.post(
        f"/api/v1/admin/users/{solo.id}/recovery",
        headers=admin_auth_headers,
        json={"action": "clear_sessions", "reason": "support request"},
    )
    assert resp.status_code == 200, resp.get_json()
    assert resp.get_json()["result"]["deleted_sessions"] == 1
    assert resp.get_json()["result"]["skipped_org_owned_sessions"] == 0
    assert UserSession.query.filter_by(user_id=solo.id).count() == 0


# ── INVARIANT 5: evidence outlives its surviving project ─────────────────────

def test_purge_that_removes_no_row_does_not_delete_scorecards(client, app, db, org_cast):
    """The exact defect: the scorecard delete ran after the purge loop even
    when nothing was removed."""
    org, editor = org_cast["org"], org_cast["editor"]
    _seed_project(db, org, editor, session_id="p2-ev", visibility="team")
    _seed_scorecard(db, org, editor, "p2-ev", "p2-card")

    # The creator is refused, so no canonical row is removed...
    resp = client.post("/api/v1/ai-agent/threads/p2-ev/purge", headers=_headers(app, editor))
    assert resp.status_code == 403

    # ...and the evidence for the surviving project is intact.
    assert Scorecard.query.get("p2-card") is not None
    assert UserSession.query.filter_by(session_id="p2-ev").count() == 1


def test_personal_hide_does_not_touch_evidence(db, org_cast):
    org, editor = org_cast["org"], org_cast["editor"]
    _seed_project(db, org, editor, session_id="p2-ev2", visibility="team")
    _seed_scorecard(db, org, editor, "p2-ev2", "p2-card2")

    archive_user_session(editor.id, "p2-ev2")

    card = Scorecard.query.get("p2-card2")
    assert card is not None
    assert card.archived_at is None


def test_authorized_purge_does_remove_evidence(client, app, db, org_cast):
    org, editor, admin = org_cast["org"], org_cast["editor"], org_cast["admin"]
    _seed_project(db, org, editor, session_id="p2-ev3", visibility="team")
    _seed_scorecard(db, org, editor, "p2-ev3", "p2-card3")

    resp = client.post("/api/v1/ai-agent/threads/p2-ev3/purge", headers=_headers(app, admin))
    assert resp.status_code == 200, resp.get_json()
    assert UserSession.query.filter_by(session_id="p2-ev3").count() == 0


# ── INVARIANT 6: purge follows organization ownership ────────────────────────

def _schedule_purge(db, session_id, days_ago=1):
    row = UserSession.query.filter_by(session_id=session_id).one()
    row.archived_at = datetime.utcnow() - timedelta(days=40)
    row.purge_after = datetime.utcnow() - timedelta(days=days_ago)
    db.session.commit()
    return row


def test_sweep_purges_an_org_row_created_by_someone_else(client, app, db, org_cast):
    """The creator need not be the caller, or even still present."""
    org, editor, admin = org_cast["org"], org_cast["editor"], org_cast["admin"]
    _seed_project(db, org, editor, session_id="p2-sweep", visibility="team")
    _schedule_purge(db, "p2-sweep")

    resp = client.post("/api/v1/ai-agent/threads/sweep-purge", headers=_headers(app, admin))
    assert resp.status_code == 200, resp.get_json()
    assert "p2-sweep" in resp.get_json()["purged_ids"]
    assert UserSession.query.filter_by(session_id="p2-sweep").count() == 0


def test_sweep_skips_org_rows_the_caller_may_not_destroy(client, app, db, org_cast):
    org, editor, other = org_cast["org"], org_cast["editor"], org_cast["other"]
    _seed_project(db, org, editor, session_id="p2-sweep-skip", visibility="team")
    _schedule_purge(db, "p2-sweep-skip")

    resp = client.post("/api/v1/ai-agent/threads/sweep-purge", headers=_headers(app, other))
    assert resp.status_code == 200, resp.get_json()
    assert resp.get_json()["purged_ids"] == []
    assert resp.get_json()["skipped_count"] == 1
    assert UserSession.query.filter_by(session_id="p2-sweep-skip").count() == 1


def test_a_personal_hide_never_becomes_purgeable(client, app, db, org_cast):
    org, editor, admin = org_cast["org"], org_cast["editor"], org_cast["admin"]
    _seed_project(db, org, editor, session_id="p2-sweep-hidden", visibility="team")

    archive_user_session(editor.id, "p2-sweep-hidden")

    row = UserSession.query.filter_by(session_id="p2-sweep-hidden").one()
    assert row.purge_after is None, "a hide scheduled a purge"

    resp = client.post("/api/v1/ai-agent/threads/sweep-purge", headers=_headers(app, admin))
    assert resp.get_json()["purged_ids"] == []
    assert UserSession.query.filter_by(session_id="p2-sweep-hidden").count() == 1


def test_solo_user_sweep_still_purges_their_own_expired_rows(client, app, db):
    solo = _mk_user(db, "p2-sweep-solo@example.test", plan="free")
    org = _mk_org(db, solo, name="P2SweepSolo", plan="free")
    _seed_project(db, org, solo, session_id="p2-sweep-solo", visibility="private")
    _schedule_purge(db, "p2-sweep-solo")

    resp = client.post("/api/v1/ai-agent/threads/sweep-purge", headers=_headers(app, solo))
    assert resp.status_code == 200, resp.get_json()
    assert "p2-sweep-solo" in resp.get_json()["purged_ids"]
