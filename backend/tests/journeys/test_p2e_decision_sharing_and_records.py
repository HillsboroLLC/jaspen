"""H-2e-3: decision shares and decision records follow the organization's project.

F3 (H-2R): "Share this decision with Jaspen" collects the PROJECT's scorecards,
whoever on the team scored them, the same call share links make
(``sharing._load_thread_cards``: the caller's id plus the authorized project
row). Each card keeps its author; the snapshot, disclosure filter, preview
consent and the organization sharing switch are unchanged.

F4 (H-2R): creating a Decision Record from a thread and recording an accepted
exposure authorize through the access seam
(``resolve_session_for_actor(require_write=True)``) before any write: a viewer
gets 403, a former member (enforce mode) and another organization get 404 with
no project content, and nothing is written for any refusal.

Seven roles of the acceptance matrix (section 4), on the P2 fixtures.
"""

import json

import pytest

from app import db as _db
from app.models import DecisionShare, Scorecard
from app.models_decision_record import DecisionRecord
from tests.journeys.test_conversation_turn_lifecycle import _headers, solo  # noqa: F401
from tests.journeys.test_p2b_workspace_project_access import (  # noqa: F401
    MARKER, _card, _no_rate_limits, _project_state, team,
)
from tests.journeys.test_p2c_distribution_project_access import dist  # noqa: F401


ACTORS = ["owner", "administrator", "editor", "viewer", "creator-now-viewer",
          "former-member", "other-org"]
READERS = {"owner", "administrator", "editor", "viewer", "creator-now-viewer"}
WRITERS = {"owner", "administrator", "editor"}
REFUSED_404 = {"former-member", "other-org"}

TEAMMATE_CARD = "t-shared-editor-card"
TEAMMATE_NAME = f"Vendor B {MARKER}"
PRIVATE_PASSAGE = "private teammate passage"

SHARE_PREVIEW = "/api/v1/decision-shares/preview"
SHARE_CREATE = "/api/v1/decision-shares"
RECORD_CREATE = "/api/v1/decision-records/from-thread/{t}"
RECORD_EXPOSURE = "/api/v1/decision-records/from-thread/{t}/accepted-exposures"


@pytest.fixture(autouse=True)
def _enforce_former_member_matrix(request, monkeypatch):
    """Matrix section 4: a former member is refused in enforce mode (SEC-06 is
    tested locally only; production enforcement is a separate approval)."""
    params = getattr(getattr(request.node, "callspec", None), "params", {})
    if params.get("actor") == "former-member":
        monkeypatch.setenv("ORG_ACCESS_ENFORCEMENT", "enforce")


@pytest.fixture
def shares(dist):
    """``dist`` with decision sharing on for the organization and a second
    scorecard in ``t-shared`` scored by the editor (not the creator)."""
    from app.scorecards import upsert_scorecard

    org = dist["org"]
    settings = dict(org.settings or {})
    settings["data_sharing"] = {**(settings.get("data_sharing") or {}),
                                "decision_sharing_allowed": True}
    org.settings = settings
    payload = {**_card(TEAMMATE_CARD, "t-shared", TEAMMATE_NAME),
               "evidence": [{"passage": PRIVATE_PASSAGE, "token": "secret-token"}]}
    upsert_scorecard(
        user_id=dist["users"]["editor"].id, thread_id="t-shared", payload=payload,
        organization_id=org.id, session_id="t-shared", source="native",
    )
    _db.session.commit()
    _db.session.expire_all()
    return dist


def _post(client, fixture, actor, path, body=None):
    return client.post(path, headers=_headers(fixture["app"], fixture["users"][actor]),
                       json=body or {})


def _authors(thread_id):
    _db.session.expire_all()
    return {c.id: c.user_id for c in Scorecard.query.filter_by(thread_id=thread_id).all()}


def _share_count():
    _db.session.expire_all()
    return DecisionShare.query.count()


# --- F3: Share with Jaspen includes teammates' scorecards ---------------------

@pytest.mark.parametrize("actor", ACTORS)
def test_teammate_scorecard_share_follows_read_access(client, shares, actor):
    authors_before = _authors("t-shared")
    state_before = _project_state("t-shared")

    response = _post(client, shares, actor, SHARE_PREVIEW,
                     {"thread_id": "t-shared", "scorecard_id": TEAMMATE_CARD})
    text = response.get_data(as_text=True)

    if actor in READERS:
        assert response.status_code == 200, text
        snapshot = response.get_json()["snapshot"]
        assert TEAMMATE_NAME in json.dumps(snapshot)
        # Disclosure filter unchanged: the teammate's evidence never leaves.
        assert PRIVATE_PASSAGE not in text and "secret-token" not in text
    else:
        assert response.status_code == 404, text
        assert MARKER not in text
    assert _authors("t-shared") == authors_before
    assert _project_state("t-shared") == state_before
    assert _share_count() == 0


@pytest.mark.parametrize("actor", ACTORS)
def test_tradeoff_spans_authors_and_create_keeps_each_author(client, shares, actor):
    authors_before = _authors("t-shared")
    assert len(set(authors_before.values())) == 2  # owner and editor
    preview = _post(client, shares, actor, SHARE_PREVIEW, {"thread_id": "t-shared"})

    if actor not in READERS:
        assert preview.status_code == 404, preview.get_data(as_text=True)
        assert MARKER not in preview.get_data(as_text=True)
        created = _post(client, shares, actor, SHARE_CREATE, {
            "thread_id": "t-shared", "preview_confirmed": True, "snapshot_sha256": "x",
        })
        assert created.status_code == 404
        assert MARKER not in created.get_data(as_text=True)
        assert _share_count() == 0
        return

    assert preview.status_code == 200, preview.get_data(as_text=True)
    body = preview.get_json()
    assert body["artifact_type"] == "tradeoff"
    dumped = json.dumps(body["snapshot"])
    assert TEAMMATE_NAME in dumped and f"Vendor A {MARKER}" in dumped

    created = _post(client, shares, actor, SHARE_CREATE, {
        "thread_id": "t-shared", "preview_confirmed": True,
        "snapshot_sha256": body["snapshot_sha256"],
    })
    assert created.status_code == 201, created.get_data(as_text=True)
    share = DecisionShare.query.one()
    assert share.user_id == shares["users"][actor].id  # the sharer
    assert share.snapshot_sha256 == body["snapshot_sha256"]
    # Each scorecard keeps its original author; nothing is re-attributed.
    assert _authors("t-shared") == authors_before


def test_owner_shares_editor_card_and_editor_shares_owner_card(client, shares):
    for actor, card in (("owner", TEAMMATE_CARD), ("editor", "t-shared-card")):
        preview = _post(client, shares, actor, SHARE_PREVIEW,
                        {"thread_id": "t-shared", "scorecard_id": card})
        assert preview.status_code == 200, preview.get_data(as_text=True)
        created = _post(client, shares, actor, SHARE_CREATE, {
            "thread_id": "t-shared", "scorecard_id": card, "preview_confirmed": True,
            "snapshot_sha256": preview.get_json()["snapshot_sha256"],
        })
        assert created.status_code == 201
        assert created.get_json()["share"]["scorecard_id"] == card
    assert _share_count() == 2


def test_former_member_own_project_is_not_shareable_in_enforce_mode(client, shares, monkeypatch):
    monkeypatch.setenv("ORG_ACCESS_ENFORCEMENT", "enforce")
    response = _post(client, shares, "former-member", SHARE_PREVIEW,
                     {"thread_id": "t-former", "scorecard_id": "t-former-card"})
    assert response.status_code == 404
    assert MARKER not in response.get_data(as_text=True)


def test_consent_and_org_switch_still_apply_to_teammate_cards(client, shares):
    preview = _post(client, shares, "owner", SHARE_PREVIEW,
                    {"thread_id": "t-shared", "scorecard_id": TEAMMATE_CARD})
    digest = preview.get_json()["snapshot_sha256"]

    unconfirmed = _post(client, shares, "owner", SHARE_CREATE, {
        "thread_id": "t-shared", "scorecard_id": TEAMMATE_CARD, "snapshot_sha256": digest,
    })
    assert unconfirmed.status_code == 400
    assert unconfirmed.get_json()["code"] == "preview_confirmation_required"

    stale = _post(client, shares, "owner", SHARE_CREATE, {
        "thread_id": "t-shared", "scorecard_id": TEAMMATE_CARD,
        "preview_confirmed": True, "snapshot_sha256": "0" * 64,
    })
    assert stale.status_code == 409
    assert stale.get_json()["code"] == "preview_changed"

    org = shares["org"]
    org.settings = {**(org.settings or {}), "data_sharing": {"decision_sharing_allowed": False}}
    _db.session.commit()
    off = _post(client, shares, "editor", SHARE_PREVIEW,
                {"thread_id": "t-shared", "scorecard_id": TEAMMATE_CARD})
    assert off.status_code == 403
    assert off.get_json()["code"] == "decision_sharing_disabled"
    assert _share_count() == 0


def _pre_h2e3_snapshot_hash(user, thread_id, scorecard_id):
    """The snapshot hash exactly as ``decision_shares._prepare`` built it at
    the H-2e-2b base (creator's id, no project row)."""
    from app.decision_records import recorded_option_decision_summary
    from app.routes.decision_shares import _hash
    from app.scorecards import collect_peer_scorecards
    from app.session_access import resolve_session_for_actor
    from app.sharing import ARTIFACT_SCORECARD, build_snapshot, filter_public_snapshot

    row, _membership = resolve_session_for_actor(user, thread_id)
    session = row.payload if isinstance(row.payload, dict) else {}
    cards = collect_peer_scorecards(
        row.user_id, thread_id, legacy_session=session,
        legacy_thread_data=row.scenarios_json if isinstance(row.scenarios_json, dict) else {},
    ) or []
    selected = next((c for c in cards if str(c.get("id")) == scorecard_id), None)
    raw, _title, _source, _evidence = build_snapshot(
        artifact_type=ARTIFACT_SCORECARD, cards=cards, include_evidence=False,
        scorecard_id=scorecard_id, thread_name=row.name or session.get("name"),
        strategy_objective=session.get("strategy_objective"),
        portfolio_summary=session.get("portfolio_summary"),
        decision_kit=session.get("decision_kit"),
        data_sources=session.get("report_data_sources"),
        recorded_decision=recorded_option_decision_summary(user, thread_id, selected),
    )
    return _hash(filter_public_snapshot(raw))


def test_owner_sharing_own_card_snapshot_hash_is_unchanged(client, dist):
    """No teammate card: the owner's own-card snapshot is byte-identical to
    the H-2e-2b base computation, so existing shares and previews still match."""
    org = dist["org"]
    org.settings = {**(org.settings or {}), "data_sharing": {"decision_sharing_allowed": True}}
    _db.session.commit()
    owner = dist["users"]["owner"]

    response = _post(client, dist, "owner", SHARE_PREVIEW,
                     {"thread_id": "t-shared", "scorecard_id": "t-shared-card"})
    assert response.status_code == 200, response.get_data(as_text=True)
    assert response.get_json()["snapshot_sha256"] == _pre_h2e3_snapshot_hash(
        owner, "t-shared", "t-shared-card")


# --- F4: decision-record writes authorize through the access seam -------------

def _record_state(thread_id):
    _db.session.expire_all()
    return [
        (r.id, r.user_id, r.organization_id, r.status,
         json.dumps(r.record, sort_keys=True, default=str),
         json.dumps(r.accepted_exposures, sort_keys=True, default=str))
        for r in DecisionRecord.query.filter_by(thread_id=thread_id).order_by(DecisionRecord.id).all()
    ]


def _assert_refused(response, fixture, actor, thread_id, before_project, before_records):
    text = response.get_data(as_text=True)
    if actor in REFUSED_404:
        assert response.status_code == 404, text
        assert MARKER not in text
        assert "read-only" not in text  # existence is not disclosed
    else:
        assert response.status_code == 403, text
        assert response.get_json() == {
            "error": "Your role on this project is read-only", "code": "forbidden",
        }
    assert _project_state(thread_id) == before_project
    assert _record_state(thread_id) == before_records
    if actor in REFUSED_404:
        # Nothing filed under the refused outsider, in any organization.
        assert DecisionRecord.query.filter_by(
            user_id=fixture["users"][actor].id, thread_id=thread_id).count() == 0


@pytest.mark.parametrize("actor", ACTORS)
def test_create_record_from_thread_access_matrix(client, dist, actor):
    thread_id, _card_id = dist["projects"][actor]
    before_project, before_records = _project_state(thread_id), _record_state(thread_id)

    response = _post(client, dist, actor, RECORD_CREATE.format(t=thread_id))

    if actor in WRITERS:
        assert response.status_code == 201, response.get_data(as_text=True)
        body = response.get_json()
        assert body["created"] is True
        record = body["record"]
        assert record["thread_id"] == thread_id
        # Attribution is the project's creator, ownership its organization,
        # whoever on the team created the record (unchanged).
        assert record["user_id"] == dist["users"]["owner"].id
        assert record["organization_id"] == dist["org"].id
        assert len(_record_state(thread_id)) == 1
        again = _post(client, dist, actor, RECORD_CREATE.format(t=thread_id))
        assert again.status_code == 200 and again.get_json()["created"] is False
        assert again.get_json()["record"]["id"] == record["id"]
    else:
        _assert_refused(response, dist, actor, thread_id, before_project, before_records)


def _seed_exposure(dist, thread_id):
    """A recorded decision whose option carries an unresolved criterion, as a
    writer would have produced it. Stored through the existing service."""
    from app.decision_records import create_or_refresh_record

    owner = dist["users"]["owner"]
    record, _ = create_or_refresh_record(owner, thread_id)
    return record


EXPOSURE_BODY = {"kind": "criterion", "option_name": "t-shared-card",
                 "target_key": "financial_viability", "note": "Accepted."}


@pytest.fixture
def exposure_card(dist):
    """Give the project's scorecard an unresolved criterion so an accepted
    exposure can be recorded against the derived Decision Record."""
    for card_id in ("t-shared-card", "t-demoted-card", "t-former-card"):
        row = Scorecard.query.filter_by(id=card_id).one()
        row.data = {**(row.data or {}), "evidence_profile": {"criteria": [{
            "key": "financial_viability", "label": "Financial viability",
            "confidence": "assumed", "weight": 0.25, "score": 45, "swing": 8.75,
            "severity": "material", "evidenced": False,
            "resolution": "Upload the supplier quote.",
        }]}}
    _db.session.commit()
    _db.session.expire_all()
    return dist


@pytest.mark.parametrize("actor", ACTORS)
def test_accepted_exposure_access_matrix(client, exposure_card, actor):
    dist = exposure_card
    thread_id, card_id = dist["projects"][actor]
    body = {**EXPOSURE_BODY, "option_name": card_id}
    before_project, before_records = _project_state(thread_id), _record_state(thread_id)

    response = _post(client, dist, actor, RECORD_EXPOSURE.format(t=thread_id), body)

    if actor in WRITERS:
        assert response.status_code == 201, response.get_data(as_text=True)
        entry = response.get_json()["accepted_exposure"]
        assert entry["accepted_by"]["user_id"] == dist["users"][actor].id
        assert entry["exposure"]["exposure_points"] == 8.75
        records = DecisionRecord.query.filter_by(thread_id=thread_id).all()
        assert len(records) == 1
        assert records[0].user_id == dist["users"]["owner"].id
        assert len(records[0].accepted_exposures) == 1
    else:
        _assert_refused(response, dist, actor, thread_id, before_project, before_records)


@pytest.mark.parametrize("actor", ["viewer", "creator-now-viewer", "former-member", "other-org"])
def test_refused_exposure_leaves_an_existing_record_untouched(client, exposure_card, actor):
    """With a record already present, a refused request changes nothing in it
    (authorization runs before the refresh)."""
    dist = exposure_card
    thread_id, card_id = dist["projects"][actor]
    if thread_id != "t-former":
        _seed_exposure(dist, thread_id)
    before_project, before_records = _project_state(thread_id), _record_state(thread_id)

    for path, body in ((RECORD_CREATE.format(t=thread_id), None),
                       (RECORD_EXPOSURE.format(t=thread_id), {**EXPOSURE_BODY, "option_name": card_id})):
        response = _post(client, dist, actor, path, body)
        _assert_refused(response, dist, actor, thread_id, before_project, before_records)


def test_unknown_thread_keeps_the_existing_not_found_answer(client, dist):
    for path in (RECORD_CREATE.format(t="t-unknown"), RECORD_EXPOSURE.format(t="t-unknown")):
        response = _post(client, dist, "owner", path, EXPOSURE_BODY)
        assert response.status_code == 404
        assert response.get_json() == {
            "error": "No conversation or analysis found for thread t-unknown",
        }
    assert DecisionRecord.query.filter_by(thread_id="t-unknown").count() == 0


def test_routes_use_the_access_seam_not_canonical_row():
    """Guard: both write routes authorize via resolve_session_for_actor."""
    import inspect

    from app.routes import decision_records as routes

    helper = inspect.getsource(routes._authorize_thread_write)
    assert "resolve_session_for_actor(" in helper and "require_write=True" in helper
    for fn in (routes.create_from_thread, routes.add_accepted_exposure):
        source = inspect.getsource(fn)
        assert "_authorize_thread_write(" in source
        assert "canonical_row(" not in source and "can_write_session(" not in source
        assert source.index("_authorize_thread_write(") < source.index("create_or_refresh_record(")
