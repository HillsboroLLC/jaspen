"""Phase 1.1: end-to-end revision enforcement on shared mutations.

Phase 1 validated a revision only when the client happened to send one. That
left every shipped mutation path unprotected, because no client sent it. These
tests pin the closed contract: for a shared project in a multi-member
organization a revision is REQUIRED, a stale one is refused, and neither
refusal mutates anything.
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


AI_PATCH = "/api/v1/ai-agent/threads/{}"
STRATEGY_PATCH = "/api/v1/strategy/threads/{}"


def _revision(session_id):
    return int(UserSession.query.filter_by(session_id=session_id).one().revision)


def _name(session_id):
    return UserSession.query.filter_by(session_id=session_id).one().name


# --- A / B. current revision succeeds and increments -------------------------

def test_shared_edit_with_current_revision_succeeds(client, app, db, team_setup):
    org, owner, editor = team_setup["org"], team_setup["owner"], team_setup["editor"]
    _seed_project(db, org, owner, session_id="c-ok", visibility="team")

    resp = client.patch(AI_PATCH.format("c-ok"), headers=_headers(app, editor),
                        json={"name": "Edited by B", "base_revision": 1})
    assert resp.status_code == 200, resp.get_json()
    assert _name("c-ok") == "Edited by B"


def test_successful_shared_mutation_increments_the_revision(client, app, db, team_setup):
    org, owner, editor = team_setup["org"], team_setup["owner"], team_setup["editor"]
    _seed_project(db, org, owner, session_id="c-inc", visibility="team")

    for expected in (2, 3, 4):
        resp = client.patch(AI_PATCH.format("c-inc"), headers=_headers(app, editor),
                            json={"name": f"v{expected}", "base_revision": expected - 1})
        assert resp.status_code == 200, resp.get_json()
        assert _revision("c-inc") == expected
        # The response carries the new revision so the client can keep going
        # without refetching.
        assert resp.get_json()["thread"]["revision"] == expected


# --- C. stale revision is refused -------------------------------------------

def test_shared_edit_with_stale_revision_returns_409(client, app, db, team_setup):
    org, owner, editor = team_setup["org"], team_setup["owner"], team_setup["editor"]
    _seed_project(db, org, owner, session_id="c-stale", visibility="team")

    client.patch(AI_PATCH.format("c-stale"), headers=_headers(app, editor),
                 json={"name": "B was first", "base_revision": 1})

    resp = client.patch(AI_PATCH.format("c-stale"), headers=_headers(app, owner),
                        json={"name": "A overwrites B", "base_revision": 1})
    assert resp.status_code == 409
    body = resp.get_json()
    assert body["code"] == "revision_conflict"
    assert body["expected_revision"] == 1
    assert body["current_revision"] == 2

    assert _name("c-stale") == "B was first"
    assert _revision("c-stale") == 2


# --- D. missing revision is refused -----------------------------------------

def test_shared_edit_without_a_revision_is_rejected(client, app, db, team_setup):
    org, owner = team_setup["org"], team_setup["owner"]
    _seed_project(db, org, owner, session_id="c-missing", visibility="team")

    resp = client.patch(AI_PATCH.format("c-missing"), headers=_headers(app, owner),
                        json={"name": "no base declared"})
    assert resp.status_code == 409
    assert resp.get_json()["expected_revision"] is None
    assert _name("c-missing") == "Shared project"
    assert _revision("c-missing") == 1


# --- E / F. no mutation path bypasses enforcement ----------------------------

def test_rename_cannot_bypass_enforcement_via_the_strategy_endpoint(client, app, db, team_setup):
    """`PATCH /strategy/threads/<id>` is the modal's fallback rename route.

    Before Phase 1.1 it resolved through load_user_sessions() with no
    organization authorization and no revision check at all, so a rename could
    sidestep the guarantee entirely.
    """
    org, owner = team_setup["org"], team_setup["owner"]
    _seed_project(db, org, owner, session_id="c-strategy", visibility="team")

    missing = client.patch(STRATEGY_PATCH.format("c-strategy"),
                           headers=_headers(app, owner), json={"name": "sneaky"})
    assert missing.status_code == 409, missing.get_json()
    assert _name("c-strategy") == "Shared project"

    ok = client.patch(STRATEGY_PATCH.format("c-strategy"),
                      headers=_headers(app, owner),
                      json={"name": "declared", "base_revision": 1})
    assert ok.status_code == 200, ok.get_json()
    assert _name("c-strategy") == "declared"

    stale = client.patch(STRATEGY_PATCH.format("c-strategy"),
                         headers=_headers(app, owner),
                         json={"name": "stale", "base_revision": 1})
    assert stale.status_code == 409
    assert _name("c-strategy") == "declared"


def test_strategy_rename_requires_write_access(client, app, db, team_setup):
    org, owner = team_setup["org"], team_setup["owner"]
    viewer = _mk_user(db, "c-viewer@acme.test")
    _add_member(db, org, viewer, role="viewer")
    _seed_project(db, org, owner, session_id="c-strat-ro", visibility="team")

    resp = client.patch(STRATEGY_PATCH.format("c-strat-ro"),
                        headers=_headers(app, viewer),
                        json={"name": "viewer rename", "base_revision": 1})
    assert resp.status_code == 403
    assert _name("c-strat-ro") == "Shared project"


@pytest.mark.parametrize("body", [
    {"status": "archived"},
    {"strategy_objective": "growth"},
    {"intake_context": {"objective": "Grow"}},
    {"visibility": "private"},
])
def test_every_shared_patch_field_requires_a_revision(client, app, db, team_setup, body):
    """Not just rename: every mutation the PATCH endpoint accepts."""
    org, owner = team_setup["org"], team_setup["owner"]
    sid = "c-field-" + "-".join(sorted(body))
    _seed_project(db, org, owner, session_id=sid, visibility="team")

    resp = client.patch(AI_PATCH.format(sid), headers=_headers(app, owner), json=body)
    assert resp.status_code == 409, resp.get_json()
    assert _revision(sid) == 1


def test_session_save_path_also_requires_a_revision(client, app, db, team_setup):
    org, owner, editor = team_setup["org"], team_setup["owner"], team_setup["editor"]
    _seed_project(db, org, owner, session_id="c-save", visibility="team")

    assert client.post("/api/v1/sessions", headers=_headers(app, editor),
                       json={"session_id": "c-save", "name": "x"}).status_code == 409
    assert client.post("/api/v1/sessions", headers=_headers(app, editor),
                       json={"session_id": "c-save", "name": "x",
                             "base_revision": 1}).status_code == 200


# --- G. solo behaviour is unchanged -----------------------------------------

def test_solo_user_never_needs_a_revision(client, app, db):
    solo = _mk_user(db, "c-solo@example.test", plan="free")
    org = _mk_org(db, solo, name="CSolo", plan="free")
    _seed_project(db, org, solo, session_id="c-solo", visibility="team")

    resp = client.patch(AI_PATCH.format("c-solo"), headers=_headers(app, solo),
                        json={"name": "renamed freely"})
    assert resp.status_code == 200, resp.get_json()
    assert _name("c-solo") == "renamed freely"

    strat = client.patch(STRATEGY_PATCH.format("c-solo"), headers=_headers(app, solo),
                         json={"name": "renamed again"})
    assert strat.status_code == 200, strat.get_json()


def test_private_project_in_a_team_org_never_needs_a_revision(client, app, db, team_setup):
    org, owner = team_setup["org"], team_setup["owner"]
    _seed_project(db, org, owner, session_id="c-private", visibility="private")

    resp = client.patch(AI_PATCH.format("c-private"), headers=_headers(app, owner),
                        json={"name": "renamed"})
    assert resp.status_code == 200, resp.get_json()


# --- H. a 409 never overwrites and never auto-retries ------------------------

def test_conflict_leaves_the_row_byte_for_byte_untouched(client, app, db, team_setup):
    org, owner, editor = team_setup["org"], team_setup["owner"], team_setup["editor"]
    _seed_project(db, org, owner, session_id="c-untouched", visibility="team")

    client.patch(AI_PATCH.format("c-untouched"), headers=_headers(app, editor),
                 json={"name": "B's edit", "base_revision": 1})

    row = UserSession.query.filter_by(session_id="c-untouched").one()
    before = {
        "name": row.name,
        "revision": int(row.revision),
        "last_edited_by_user_id": row.last_edited_by_user_id,
        "payload": dict(row.payload),
    }

    conflict = client.patch(AI_PATCH.format("c-untouched"), headers=_headers(app, owner),
                            json={"name": "A's overwrite", "base_revision": 1})
    assert conflict.status_code == 409

    row = UserSession.query.filter_by(session_id="c-untouched").one()
    assert row.name == before["name"]
    assert int(row.revision) == before["revision"]
    assert row.last_edited_by_user_id == before["last_edited_by_user_id"]
    assert dict(row.payload) == before["payload"]


def test_repeating_a_conflicting_write_stays_a_conflict(client, app, db, team_setup):
    """A stale write must not become valid just by being retried."""
    org, owner, editor = team_setup["org"], team_setup["owner"], team_setup["editor"]
    _seed_project(db, org, owner, session_id="c-retry", visibility="team")

    client.patch(AI_PATCH.format("c-retry"), headers=_headers(app, editor),
                 json={"name": "B's edit", "base_revision": 1})

    for _ in range(3):
        resp = client.patch(AI_PATCH.format("c-retry"), headers=_headers(app, owner),
                            json={"name": "A's overwrite", "base_revision": 1})
        assert resp.status_code == 409

    assert _name("c-retry") == "B's edit"
    assert _revision("c-retry") == 2


def test_the_documented_recovery_is_reload_then_write(client, app, db, team_setup):
    """The only sanctioned resolution: read the current state, then rewrite."""
    org, owner, editor = team_setup["org"], team_setup["owner"], team_setup["editor"]
    _seed_project(db, org, owner, session_id="c-recover", visibility="team")

    client.patch(AI_PATCH.format("c-recover"), headers=_headers(app, editor),
                 json={"name": "B's edit", "base_revision": 1})

    assert client.patch(AI_PATCH.format("c-recover"), headers=_headers(app, owner),
                        json={"name": "A retries blind", "base_revision": 1}).status_code == 409

    reloaded = client.get("/api/v1/ai-agent/threads/c-recover", headers=_headers(app, owner))
    current = reloaded.get_json()["thread"]["revision"]
    assert current == 2

    resp = client.patch(AI_PATCH.format("c-recover"), headers=_headers(app, owner),
                        json={"name": "A after reloading", "base_revision": current})
    assert resp.status_code == 200, resp.get_json()
    assert _name("c-recover") == "A after reloading"


# --- the client contract the frontend depends on -----------------------------

def test_read_paths_expose_the_revision_the_client_must_echo(client, app, db, team_setup):
    org, owner = team_setup["org"], team_setup["owner"]
    row = _seed_project(db, org, owner, session_id="c-expose", visibility="team")
    row.revision = 7
    db.session.commit()

    headers = _headers(app, owner)

    single = client.get("/api/v1/ai-agent/threads/c-expose", headers=headers)
    assert single.get_json()["thread"]["revision"] == 7

    listing = client.get("/api/v1/ai-agent/threads", headers=headers)
    entry = next(s for s in listing.get_json()["sessions"]
                 if s["session_id"] == "c-expose")
    assert entry["revision"] == 7

    session_get = client.get("/api/v1/sessions/c-expose", headers=headers)
    assert session_get.get_json()["session"]["revision"] == 7
