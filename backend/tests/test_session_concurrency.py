"""Phase 1: optimistic concurrency on the canonical session row.

The requirement is preventing SILENT data loss, not resolving conflicts in the
UI. A write that is based on a revision which is no longer current is refused
with 409 and changes nothing.
"""
import pytest

from app.models import UserSession
from app.session_access import (
    RevisionConflict,
    check_revision,
    extract_base_revision,
    revision_required_for,
    stamp_write,
)

from tests.test_session_org_ownership import (
    _headers,
    _mk_org,
    _mk_user,
    _seed_project,
    team_setup,
)


def test_new_rows_start_at_revision_one(client, app, db):
    solo = _mk_user(db, "rev-solo@example.test", plan="free")
    _mk_org(db, solo, name="RevSolo", plan="free")

    resp = client.post("/api/v1/sessions", headers=_headers(app, solo),
                       json={"session_id": "r-1", "name": "New"})
    assert resp.status_code == 200
    assert resp.get_json()["revision"] == 1
    assert int(UserSession.query.filter_by(session_id="r-1").one().revision) == 1


def test_saving_one_session_does_not_bump_the_others(client, app, db):
    """`revision` must track the project, not the request.

    save_user_sessions() is routinely handed the caller's whole session dict to
    persist one edit. Stamping every row in it would inflate revisions on
    untouched projects, fire spurious 409s, and rewrite
    `last_edited_by_user_id` on work the caller never opened.
    """
    solo = _mk_user(db, "rev-isolate@example.test", plan="free")
    _mk_org(db, solo, name="RevIsolate", plan="free")
    headers = _headers(app, solo)

    for sid in ("iso-a", "iso-b", "iso-c"):
        client.post("/api/v1/sessions", headers=headers,
                    json={"session_id": sid, "name": sid})

    before = {r.session_id: int(r.revision) for r in UserSession.query.all()}
    assert before == {"iso-a": 1, "iso-b": 1, "iso-c": 1}

    client.post("/api/v1/sessions", headers=headers,
                json={"session_id": "iso-a", "name": "changed"})

    after = {r.session_id: int(r.revision) for r in UserSession.query.all()}
    assert after == {"iso-a": 2, "iso-b": 1, "iso-c": 1}


def test_resaving_identical_content_does_not_bump_the_revision(client, app, db):
    solo = _mk_user(db, "rev-noop@example.test", plan="free")
    _mk_org(db, solo, name="RevNoop", plan="free")
    headers = _headers(app, solo)

    client.post("/api/v1/sessions", headers=headers,
                json={"session_id": "noop", "name": "same"})
    client.post("/api/v1/sessions", headers=headers,
                json={"session_id": "noop", "name": "same"})

    assert int(UserSession.query.filter_by(session_id="noop").one().revision) == 1


def test_untouched_rows_keep_their_editor_attribution(client, app, db, team_setup):
    """A collaborator's save must not stamp them onto projects they never opened."""
    org, owner, editor = team_setup["org"], team_setup["owner"], team_setup["editor"]
    _seed_project(db, org, owner, session_id="attr-a", visibility="team")
    _seed_project(db, org, owner, session_id="attr-b", visibility="team")

    client.post("/api/v1/sessions", headers=_headers(app, editor), json={
        "session_id": "attr-a", "name": "edited", "base_revision": 1,
    })

    untouched = UserSession.query.filter_by(session_id="attr-b").one()
    assert untouched.last_edited_by_user_id is None
    assert int(untouched.revision) == 1


def test_each_accepted_write_increments_by_one(client, app, db):
    solo = _mk_user(db, "rev-inc@example.test", plan="free")
    _mk_org(db, solo, name="RevInc", plan="free")
    headers = _headers(app, solo)

    client.post("/api/v1/sessions", headers=headers,
                json={"session_id": "r-2", "name": "v1"})
    for expected in (2, 3, 4):
        resp = client.post("/api/v1/sessions", headers=headers,
                           json={"session_id": "r-2", "name": f"v{expected}"})
        assert resp.status_code == 200, resp.get_json()
        assert resp.get_json()["revision"] == expected


# --- G. a stale revision cannot overwrite a newer one ------------------------

def test_stale_revision_is_refused_and_changes_nothing(client, app, db, team_setup):
    org, owner, editor = team_setup["org"], team_setup["owner"], team_setup["editor"]
    _seed_project(db, org, owner, session_id="r-conflict")

    # Both open at revision 1. The editor saves first.
    first = client.post("/api/v1/sessions", headers=_headers(app, editor), json={
        "session_id": "r-conflict", "name": "edited by B", "base_revision": 1,
    })
    assert first.status_code == 200
    assert first.get_json()["revision"] == 2

    # The owner now saves on top of the revision they loaded, which is stale.
    second = client.post("/api/v1/sessions", headers=_headers(app, owner), json={
        "session_id": "r-conflict", "name": "edited by A", "base_revision": 1,
    })
    assert second.status_code == 409
    body = second.get_json()
    assert body["code"] == "revision_conflict"
    assert body["expected_revision"] == 1
    assert body["current_revision"] == 2

    # The earlier write survived intact -- no silent overwrite.
    row = UserSession.query.filter_by(session_id="r-conflict").one()
    assert row.name == "edited by B"
    assert int(row.revision) == 2


# --- H. a valid revision saves and increments -------------------------------

def test_current_revision_saves_and_increments(client, app, db, team_setup):
    org, owner, editor = team_setup["org"], team_setup["owner"], team_setup["editor"]
    _seed_project(db, org, owner, session_id="r-ok")

    client.post("/api/v1/sessions", headers=_headers(app, editor), json={
        "session_id": "r-ok", "name": "first", "base_revision": 1,
    })
    resp = client.post("/api/v1/sessions", headers=_headers(app, owner), json={
        "session_id": "r-ok", "name": "second", "base_revision": 2,
    })
    assert resp.status_code == 200, resp.get_json()
    assert resp.get_json()["revision"] == 3
    assert UserSession.query.filter_by(session_id="r-ok").one().name == "second"


# --- client timestamps are not concurrency control ---------------------------

def test_client_timestamp_cannot_bypass_the_revision_check(client, app, db, team_setup):
    """`updated_at` is derived from the client-supplied `timestamp`, which is
    exactly why it must not be the token. A future timestamp buys nothing."""
    org, owner, editor = team_setup["org"], team_setup["owner"], team_setup["editor"]
    _seed_project(db, org, owner, session_id="r-clock")

    client.post("/api/v1/sessions", headers=_headers(app, editor), json={
        "session_id": "r-clock", "name": "editor wrote", "base_revision": 1,
    })

    resp = client.post("/api/v1/sessions", headers=_headers(app, owner), json={
        "session_id": "r-clock",
        "name": "owner tried with a future clock",
        "timestamp": "2999-01-01T00:00:00",
        "base_revision": 1,
    })
    assert resp.status_code == 409
    assert UserSession.query.filter_by(session_id="r-clock").one().name == "editor wrote"


# --- where a revision is required -------------------------------------------

def test_revision_is_required_for_shared_multi_member_work(db, team_setup):
    org, owner = team_setup["org"], team_setup["owner"]
    shared = _seed_project(db, org, owner, session_id="r-req", visibility="team")
    assert revision_required_for(shared) is True

    with pytest.raises(RevisionConflict):
        check_revision(shared, None)


def test_revision_is_optional_for_private_and_solo_work(db, team_setup):
    """No existing individual client can break: private work stays optional."""
    org, owner = team_setup["org"], team_setup["owner"]
    private = _seed_project(db, org, owner, session_id="r-opt", visibility="private")
    assert revision_required_for(private) is False
    check_revision(private, None)   # does not raise

    solo = _mk_user(db, "rev-req-solo@example.test", plan="free")
    solo_org = _mk_org(db, solo, name="RevReqSolo", plan="free")
    solo_row = _seed_project(db, solo_org, solo, session_id="r-opt-solo",
                             visibility="team")
    assert revision_required_for(solo_row) is False


def test_user_memory_never_requires_a_revision(db, team_setup):
    org, owner = team_setup["org"], team_setup["owner"]
    row = UserSession(
        user_id=owner.id, session_id="__user_memory__", name="__user_memory__",
        document_type="memory", created_by_user_id=owner.id, visibility="team",
        organization_id=None, payload={"session_id": "__user_memory__"},
    )
    db.session.add(row)
    db.session.commit()
    assert revision_required_for(row) is False


# --- helper semantics --------------------------------------------------------

def test_extract_base_revision_ignores_an_echoed_revision_field(db, team_setup):
    """A payload that merely echoes `revision` is not asserting a base.

    Server-side flows load once and save several times per request; treating
    the echoed field as an assertion would make the second save conflict with
    the first.
    """
    assert extract_base_revision({"revision": 7}) is None
    assert extract_base_revision({"base_revision": 7}) == 7
    assert extract_base_revision({}) is None


def test_stamp_write_records_the_editor(db, team_setup):
    org, owner, editor = team_setup["org"], team_setup["owner"], team_setup["editor"]
    row = _seed_project(db, org, owner, session_id="r-stamp")

    assert stamp_write(row, editor.id) == 2
    assert row.last_edited_by_user_id == editor.id
    assert row.created_by_user_id == owner.id
