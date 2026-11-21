"""P2c: distribution surfaces follow the organization's project.

Exports (8), report generation, starters, share links, decision-asset email
and the decision-impact source reader resolve the project through the access
seam (``session_access``) and read its content from the organization's
canonical row:

* every role that may read the project gets its real content: owner,
  administrator, editor, viewer and creator-now-viewer. Exports and reports
  follow read access (OD-7 option A, ``project_scope.authorized_export_scope``);
  share links, emailed assets and starters follow read access on their own
  seam (spec 2.3), so a change to export permission cannot change them;
* a former member (enforce mode) and a member of another organization get
  404 and no content, and the project and its attribution are kept;
* an unknown project id gets 404 and nothing is created (OD-6 A);
* nothing here writes the project, and the existing plan-entitlement check
  still applies after the access check.

Assertions are on content (MARKER, stored in the project), the project's
stored state, and side effects (model calls, report files, starter rows,
share-link ownership, email deliveries), not only status codes.

Journeys (blueprint acceptance matrix): B6, H.
"""

import ast
import inspect
import io
import textwrap
import uuid
import zipfile

import pytest

from app import db as _db
from app.models import (
    DecisionAssetEmail,
    SavedStarter,
    SharedArtifact,
    SharedArtifactOwnership,
    UserSession,
)
from tests.journeys.test_p2b_workspace_project_access import (  # noqa: F401 (fixtures)
    MARKER,
    _call,
    _no_rate_limits,
    _project_state,
    _seed_project,
    solo,
    team,
)

# The seven roles of the acceptance matrix (section 4).
ACTORS = ["owner", "administrator", "editor", "viewer", "creator-now-viewer",
          "former-member", "other-org"]
READERS = {"owner", "administrator", "editor", "viewer", "creator-now-viewer"}
WRITERS = {"owner", "administrator", "editor"}

TASK_TITLE = f"Kickoff {MARKER}"

EXPORT_ROUTES = {
    "scorecard-xlsx": "/api/v1/export/threads/{t}/scorecard/xlsx?scorecard_id={c}",
    "scorecard-docx": "/api/v1/export/threads/{t}/scorecard/docx?scorecard_id={c}",
    "scorecard-pdf": "/api/v1/export/threads/{t}/scorecard/pdf?scorecard_id={c}",
    "scorecard-pptx": "/api/v1/export/threads/{t}/scorecard/pptx?scorecard_id={c}",
    "wbs-csv": "/api/v1/export/threads/{t}/wbs/csv",
    "wbs-xlsx": "/api/v1/export/threads/{t}/wbs/xlsx",
    "conversation-markdown": "/api/v1/export/threads/{t}/conversation/markdown",
    "conversation-pdf": "/api/v1/export/threads/{t}/conversation/pdf",
}

# The existing per-format plan gate (export._require_export_plan): on the free
# plan these three are refused with export_plan_required; the rest are
# available on every signed-in plan.
PLAN_GATED_ON_FREE = {"scorecard-xlsx", "scorecard-docx", "conversation-pdf"}


def _distributors():
    """OD-7 option A: everyone who may read the project may export it."""
    return READERS


# --- Fixture ---------------------------------------------------------------

@pytest.fixture(autouse=True)
def _enforce_for_former_members(request, monkeypatch):
    """A former member is refused in enforce mode (matrix section 4: "404
    (enforce mode)"). Report mode, today's default, is pinned separately in
    test_report_mode_former_creator_is_unchanged_and_audited."""
    params = getattr(getattr(request.node, "callspec", None), "params", {})
    if params.get("actor") == "former-member":
        monkeypatch.setenv("ORG_ACCESS_ENFORCEMENT", "enforce")

@pytest.fixture(autouse=True)
def _remove_share_links(app):
    """The shared ``db`` fixture does not clear share links; remove the ones
    these tests make so later modules start from none."""
    yield
    with app.app_context():
        SharedArtifactOwnership.query.delete()
        SharedArtifact.query.delete()
        _db.session.commit()


def _add_plan(owner, thread_id):
    """A plan with a task carrying MARKER, so plan exports have content."""
    from app.scenarios_store import save_project_scenarios_data

    def _populate(td):
        td["project_wbs"] = {
            "name": f"Plan {MARKER}", "phases": [],
            "tasks": [{"id": "t1", "title": TASK_TITLE, "status": "todo", "phase": "Start"}],
        }
        return td

    save_project_scenarios_data(owner.id, thread_id, updater=_populate)
    _db.session.expire_all()


@pytest.fixture
def dist(team):
    """P2b's five-role team plus an administrator (who created nothing) and a
    former member (who created ``t-former``, then left), with plans that have
    tasks, an organization plan that includes every export, verified emails
    and a paid seat for sharing."""
    from app.models import OrganizationMember
    from tests.journeys.test_conversation_turn_lifecycle import _add_member, _mk_user

    org = team["org"]
    org.plan_key = "team"
    admin = _mk_user(f"admin-{uuid.uuid4().hex[:8]}@example.test")
    _add_member(org, admin, role="admin")
    former = _mk_user(f"former-{uuid.uuid4().hex[:8]}@example.test")
    _add_member(org, former)
    former_card = _seed_project(former, org, "t-former")
    team["users"]["administrator"] = admin
    team["users"]["former-member"] = former
    team["projects"]["administrator"] = team["projects"]["owner"]
    team["projects"]["former-member"] = ("t-former", former_card)
    for user in team["users"].values():
        user.email_verified = True
        user.subscription_plan = "team"
    _db.session.commit()
    _add_plan(team["users"]["owner"], "t-shared")
    # The creator is a viewer now, so the organization owner adds the plan.
    _add_plan(team["users"]["owner"], "t-demoted")
    _add_plan(former, "t-former")
    OrganizationMember.query.filter_by(organization_id=org.id, user_id=former.id).one().status = "removed"
    _db.session.commit()
    return team


@pytest.fixture
def report_calls(monkeypatch, tmp_path):
    """Report generation writes its PDF under a temporary root, and the model
    step is a stand-in that records it was reached."""
    from app.routes import reports

    calls = []

    def _markdown(user, report_type, analysis):
        calls.append(analysis)
        return f"# Report\n\n{analysis.get('project_name')}\n"

    monkeypatch.setattr(reports, "_reports_root", lambda: str(tmp_path))
    monkeypatch.setattr(reports, "_llm_report_markdown", _markdown)
    return calls


@pytest.fixture
def sent_emails(monkeypatch):
    from app import decision_asset_email_service as service

    class _Provider:
        def __init__(self):
            self.messages = []

        def send(self, **message):
            from app.email_provider import EmailProviderResult
            self.messages.append(message)
            return EmailProviderResult(provider="test", response_category="accepted")

    provider = _Provider()
    monkeypatch.setattr(service, "get_transactional_email_provider", lambda: provider)
    monkeypatch.setattr(
        "app.routes.decision_asset_email.start_delivery",
        lambda delivery_id: service.process_delivery(delivery_id),
    )
    return provider.messages


def _content_bytes(response):
    """Readable bytes of an export: zip members for Office formats, raw
    otherwise (PDF text streams are compressed, so PDFs are checked for
    their content separately)."""
    data = response.data
    if data[:2] == b"PK":
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            return b"".join(archive.read(name) for name in archive.namelist())
    return data


def _pdf_text(data):
    """Decompressed PDF content streams, enough to find the marker."""
    import re
    import zlib

    out = [data]
    for match in re.finditer(rb"stream\r?\n(.*?)\r?\n?endstream", data, re.S):
        chunk = match.group(1)
        try:
            out.append(zlib.decompress(chunk))
        except zlib.error:
            try:
                import base64
                text = chunk.strip()
                text = text[:-2] if text.endswith(b"~>") else text
                out.append(zlib.decompress(base64.a85decode(text, adobe=False)))
            except Exception:
                out.append(chunk)
    return b"".join(out)


def _has_marker(response):
    if response.data[:5] == b"%PDF-":
        text = _pdf_text(response.data)
        # PDF text operators may split or escape the marker; its distinctive
        # suffix is enough to prove the project's content is in the file.
        return MARKER.encode() in text
    return MARKER.encode() in _content_bytes(response)


# --- Exports: role matrix --------------------------------------------------

@pytest.mark.parametrize("actor", ACTORS)
@pytest.mark.parametrize("route", sorted(EXPORT_ROUTES))
def test_exports_follow_distribution_access(client, dist, actor, route):
    thread_id, card_id = dist["projects"][actor]
    before = _project_state(thread_id)

    response = _call(client, dist, actor, "GET", EXPORT_ROUTES[route].format(t=thread_id, c=card_id))

    if actor in _distributors():
        assert response.status_code == 200, (route, actor, response.get_data(as_text=True)[:400])
        assert _has_marker(response), (route, actor, "the project's content is missing")
    elif actor in READERS:
        raise AssertionError("every reader may export (OD-7 A)")
    else:
        assert response.status_code == 404, (route, actor, response.status_code)
        assert MARKER.encode() not in _content_bytes(response)
    # An export is a read: nothing about the project changes, for anyone.
    assert _project_state(thread_id) == before, (route, actor)


@pytest.mark.parametrize("route", sorted(EXPORT_ROUTES))
def test_editor_export_is_the_owners_export(client, dist, route):
    """B6: a teammate exports the organization's project itself, byte for
    byte what the owner gets (all exports are of the same canonical row)."""
    path = EXPORT_ROUTES[route].format(t="t-shared", c=dist["projects"]["owner"][1])
    owner = _call(client, dist, "owner", "GET", path)
    editor = _call(client, dist, "editor", "GET", path)
    assert owner.status_code == editor.status_code == 200, route
    assert _normalized_export(owner) == _normalized_export(editor), route
    assert owner.headers.get("Content-Disposition") == editor.headers.get("Content-Disposition")


def _normalized_export(response):
    """Export bytes with only generation-time values removed: the PDF
    creation date and document id, and Office core-properties timestamps."""
    import re
    data = response.data
    if data[:5] == b"%PDF-":
        data = re.sub(rb"/(CreationDate|ModDate) \([^)]*\)", b"/\\1 ()", data)
        data = re.sub(rb"/ID\s*\[[^\]]*\]", b"/ID []", data)
        return data
    if data[:2] == b"PK":
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            parts = []
            for name in sorted(archive.namelist()):
                body = archive.read(name)
                if name == "docProps/core.xml":
                    body = re.sub(rb"<dcterms:(created|modified)[^>]*>[^<]*</dcterms:\1>", b"", body)
                parts.append(name.encode() + b"\0" + body)
            # The plan workbook's "Generated" cell is the export time; only its
            # value is masked.
            return re.sub(rb"(<t>Generated</t></is></c><c r=\"B\d+\"[^>]*><v>)[0-9.]+(</v>)",
                          rb"\1\2", b"\0\0".join(parts))
    return data


@pytest.mark.parametrize("route", sorted(PLAN_GATED_ON_FREE))
@pytest.mark.parametrize("actor", sorted(WRITERS))
def test_plan_entitlement_still_applies_after_access(client, dist, actor, route):
    """The existing per-format plan check runs after the access check: on a
    free organization a member who may read the project is still refused
    the gated formats, with the existing code and no content."""
    dist["org"].plan_key = "free"
    _db.session.commit()
    thread_id, card_id = dist["projects"][actor]
    response = _call(client, dist, actor, "GET", EXPORT_ROUTES[route].format(t=thread_id, c=card_id))
    assert response.status_code == 403, (route, actor)
    body = response.get_json()
    assert body["code"] == "export_plan_required"
    assert body["plan_key"] == "free"
    assert MARKER.encode() not in response.data


def test_access_is_checked_before_the_plan(client, dist):
    """Another organization's member is told the project does not exist,
    never what plan its organization is on."""
    dist["org"].plan_key = "free"
    _db.session.commit()
    for route in sorted(PLAN_GATED_ON_FREE):
        response = _call(client, dist, "other-org", "GET",
                         EXPORT_ROUTES[route].format(t="t-shared", c="t-shared-card"))
        assert response.status_code == 404, route
        assert b"export_plan_required" not in response.data


def test_exports_report_an_unknown_project(client, dist):
    """OD-6 A: an unknown id is reported as not found, and nothing is made."""
    for route, template in sorted(EXPORT_ROUTES.items()):
        response = _call(client, dist, "owner", "GET", template.format(t="t-missing", c="c-missing"))
        assert response.status_code == 404, route
    assert UserSession.query.filter_by(session_id="t-missing").count() == 0


def test_exports_never_reach_another_organizations_same_id(client, dist):
    """Another organization holding a project under the same id exports its
    own project and never the shared one."""
    from app.routes.sessions import save_user_sessions
    outsider = dist["users"]["other-org"]
    assert save_user_sessions(outsider.id, {"t-shared": {
        "session_id": "t-shared", "user_id": outsider.id, "name": "Outsider own",
        "status": "in_progress", "organization_id": outsider.active_organization_id,
        "chat_history": [{"role": "user", "content": "outsider words"}],
    }})
    before = _project_state("t-shared")
    response = _call(client, dist, "other-org", "GET",
                     EXPORT_ROUTES["conversation-markdown"].format(t="t-shared", c=""))
    assert response.status_code == 200
    assert b"outsider words" in response.data
    assert MARKER.encode() not in response.data
    for route in ("scorecard-pdf", "wbs-csv"):
        response = _call(client, dist, "other-org", "GET",
                         EXPORT_ROUTES[route].format(t="t-shared", c="t-shared-card"))
        assert MARKER.encode() not in _content_bytes(response), route
    assert _project_state("t-shared") == before


def test_creator_now_viewer_follows_current_role_not_authorship(client, dist):
    """B9: authorship of the project does not decide distribution; the
    member's current role does."""
    thread_id, card_id = dist["projects"]["creator-now-viewer"]
    response = _call(client, dist, "creator-now-viewer", "GET",
                     EXPORT_ROUTES["scorecard-pptx"].format(t=thread_id, c=card_id))
    viewer = _call(client, dist, "viewer", "GET",
                   EXPORT_ROUTES["scorecard-pptx"].format(t=thread_id, c=card_id))
    assert response.status_code == viewer.status_code


# --- Share links and email do not depend on export permission -----------

@pytest.fixture
def exports_for_editing_roles_only(monkeypatch):
    """A hypothetical future change that limits exports and reports to
    editing roles, applied to the export seam only."""
    from app.project_scope import authorized_thread_scope

    def _editing_only(user_id, thread_id):
        return authorized_thread_scope(user_id, thread_id, require_write=True)

    monkeypatch.setattr("app.routes.export.authorized_export_scope", _editing_only)
    monkeypatch.setattr("app.routes.reports.authorized_export_scope", _editing_only)


@pytest.mark.parametrize("actor", ["viewer", "creator-now-viewer"])
def test_share_links_and_email_follow_read_access_whatever_exports_allow(
    client, dist, exports_for_editing_roles_only, report_calls, sent_emails, actor,
):
    """Approved Nov 14: viewers may create share links and email assets on
    read access. Restricting exports (the export seam) must not silently
    revoke either, and starters stay on read access too."""
    thread_id, card_id = dist["projects"][actor]
    before = _project_state(thread_id)
    response = _call(client, dist, actor, "GET",
                     EXPORT_ROUTES["scorecard-pdf"].format(t=thread_id, c=card_id))
    assert response.status_code == 403, "the stand-in export restriction applies"
    response = _call(client, dist, actor, "POST", "/api/v1/reports/generate",
                     {"thread_id": thread_id, "report_type": "executive_summary"})
    assert response.status_code == 403 and report_calls == []

    response = _call(client, dist, actor, "POST", "/api/v1/shares",
                     {"artifact_type": "scorecard", "thread_id": thread_id, "scorecard_id": card_id,
                      "disclosure_review_confirmed": True})
    assert response.status_code == 201, response.get_data(as_text=True)[:300]
    response = _call(client, dist, actor, "POST", f"/api/v1/email-assets/threads/{thread_id}",
                     {"idempotency_key": f"read-{uuid.uuid4().hex[:12]}", "scorecard_id": card_id,
                      "output_types": ["scorecards"]})
    assert response.status_code == 202 and response.get_json()["status"] == "sent"
    assert len(sent_emails) == 1
    response = _call(client, dist, actor, "POST", "/api/v1/starters",
                     {"thread_id": thread_id, "name": "From the project"})
    assert response.status_code == 201
    assert _project_state(thread_id) == before


# --- Reports ---------------------------------------------------------------

@pytest.mark.parametrize("actor", ACTORS)
def test_generate_report_follows_distribution_access(client, dist, report_calls, actor):
    thread_id, _card_id = dist["projects"][actor]
    before = _project_state(thread_id)
    response = _call(client, dist, actor, "POST", "/api/v1/reports/generate",
                     {"thread_id": thread_id, "report_type": "executive_summary"})
    if actor in _distributors():
        assert response.status_code == 200, (actor, response.get_data(as_text=True)[:300])
        body = response.get_json()
        assert body["thread_id"] == thread_id
        assert MARKER in body["project_name"]
        assert len(report_calls) == 1 and MARKER in report_calls[0]["project_name"]
        assert report_calls[0]["jaspen_score"] == 72.0
        # The report file is the member's own; the project is not touched.
        listed = _call(client, dist, actor, "GET", "/api/v1/reports").get_json()["reports"]
        assert [item["report_id"] for item in listed] == [body["report_id"]]
    else:
        assert response.status_code in (403, 404), actor
        assert report_calls == [], "the model step ran for a member who may not distribute"
        assert MARKER.encode() not in response.data
    assert _project_state(thread_id) == before


def test_generate_report_reports_an_unknown_project(client, dist, report_calls):
    response = _call(client, dist, "owner", "POST", "/api/v1/reports/generate",
                     {"thread_id": "t-missing", "report_type": "detailed"})
    assert response.status_code == 404
    assert report_calls == []
    assert UserSession.query.filter_by(session_id="t-missing").count() == 0


# --- Starters --------------------------------------------------------------

@pytest.mark.parametrize("actor", ACTORS)
def test_create_starter_follows_read_access(client, dist, actor):
    """A starter copies the source project, so read access is enough (spec
    2.3). It is the member's own starter; the project is unchanged."""
    from app.scenarios_store import save_project_scenarios_data  # noqa: F401
    thread_id, _card_id = dist["projects"][actor]
    row = UserSession.query.filter_by(session_id=thread_id).first()
    payload = dict(row.payload)
    payload["strategy_objective"] = "growth"
    payload["baseline_inputs"] = {"marker_lever": 7}
    row.payload = payload
    from sqlalchemy.orm.attributes import flag_modified
    flag_modified(row, "payload")
    _db.session.commit()
    before = _project_state(thread_id)

    response = _call(client, dist, actor, "POST", "/api/v1/starters",
                     {"thread_id": thread_id, "name": f"Starter {actor}"})
    user = dist["users"][actor]
    if actor in READERS:
        assert response.status_code == 201, (actor, response.get_data(as_text=True)[:300])
        starter = response.get_json()["starter"]
        assert starter["source_thread_id"] == thread_id
        assert starter["objective"] == "growth"
        assert starter["lever_defaults"] == {"marker_lever": 7}
        stored = SavedStarter.query.filter_by(user_id=user.id).one()
        assert stored.source_thread_id == thread_id
    else:
        assert response.status_code == 404, actor
        assert SavedStarter.query.filter_by(user_id=user.id).count() == 0
    assert _project_state(thread_id) == before


def test_create_starter_reports_an_unknown_project(client, dist):
    response = _call(client, dist, "owner", "POST", "/api/v1/starters",
                     {"thread_id": "t-missing", "name": "Nope"})
    assert response.status_code == 404
    assert SavedStarter.query.count() == 0


# --- Share links -----------------------------------------------------------

@pytest.mark.parametrize("actor", ACTORS)
def test_share_preview_follows_distribution_access(client, dist, actor):
    thread_id, card_id = dist["projects"][actor]
    before = _project_state(thread_id)
    response = _call(client, dist, actor, "POST", "/api/v1/shares/preview",
                     {"artifact_type": "scorecard", "thread_id": thread_id, "scorecard_id": card_id})
    if actor in _distributors():
        assert response.status_code == 200, (actor, response.get_data(as_text=True)[:300])
        assert MARKER.encode() in response.data
    else:
        assert response.status_code in (403, 404), actor
        assert MARKER.encode() not in response.data
    assert _project_state(thread_id) == before


def test_a_teammates_share_link_belongs_to_the_projects_organization(client, dist):
    """A link an editor makes of the organization's project is owned by that
    organization (ownership comes from the project, not from who clicked), so
    it serves publicly and the organization can manage it. Before P2c the
    editor could not reach the project at all; resolving ownership from the
    editor's own rows would have held the link as ambiguous."""
    response = _call(client, dist, "editor", "POST", "/api/v1/shares",
                     {"artifact_type": "scorecard", "thread_id": "t-shared",
                      "scorecard_id": dist["projects"]["editor"][1],
                      "disclosure_review_confirmed": True})
    assert response.status_code == 201, response.get_data(as_text=True)[:300]
    link = SharedArtifact.query.filter_by(owner_user_id=dist["users"]["editor"].id).one()
    ownership = _db.session.get(SharedArtifactOwnership, link.id)
    assert (ownership.state, ownership.organization_id) == ("organization", dist["org"].id)
    token = response.get_json()["link"]["url"].rstrip("/").split("/")[-1]
    public = client.get(f"/api/v1/shares/public/{token}")
    assert public.status_code == 200
    assert MARKER.encode() in public.data


def test_the_owners_share_link_ownership_is_unchanged(client, dist):
    response = _call(client, dist, "owner", "POST", "/api/v1/shares",
                     {"artifact_type": "scorecard", "thread_id": "t-shared",
                      "scorecard_id": dist["projects"]["owner"][1],
                      "disclosure_review_confirmed": True})
    assert response.status_code == 201
    link = SharedArtifact.query.filter_by(owner_user_id=dist["users"]["owner"].id).one()
    from app import share_ownership
    ownership = _db.session.get(SharedArtifactOwnership, link.id)
    assert (ownership.state, ownership.organization_id) == share_ownership.resolve(
        link.owner_user_id, link.thread_id,
    )


def test_share_preview_reports_an_unknown_project(client, dist):
    response = _call(client, dist, "owner", "POST", "/api/v1/shares/preview",
                     {"artifact_type": "scorecard", "thread_id": "t-missing"})
    assert response.status_code == 404
    assert SharedArtifact.query.filter_by(thread_id="t-missing").count() == 0


# --- Decision-asset email --------------------------------------------------

@pytest.mark.parametrize("actor", ACTORS)
def test_email_assets_follow_distribution_access(client, dist, sent_emails, actor):
    """The email goes to the member themself, with the project's own
    scorecard; access is checked again when it is sent."""
    thread_id, card_id = dist["projects"][actor]
    before = _project_state(thread_id)
    response = _call(client, dist, actor, "POST", f"/api/v1/email-assets/threads/{thread_id}",
                     {"idempotency_key": f"p2c-{actor}-{uuid.uuid4().hex[:8]}",
                      "scorecard_id": card_id, "output_types": ["scorecards"]})
    user = dist["users"][actor]
    if actor in _distributors():
        assert response.status_code == 202, (actor, response.get_data(as_text=True)[:300])
        assert response.get_json()["status"] == "sent"
        assert len(sent_emails) == 1
        message = sent_emails[0]
        assert message["recipient"] == user.email
        assert MARKER in message["text_body"] or MARKER in message["html_body"]
        delivery = DecisionAssetEmail.query.filter_by(user_id=user.id).one()
        assert delivery.organization_id == dist["org"].id
        assert delivery.scorecard_id == card_id
    else:
        assert response.status_code in (403, 404), actor
        assert sent_emails == []
        assert DecisionAssetEmail.query.filter_by(user_id=user.id).count() == 0
    assert _project_state(thread_id) == before


def test_email_send_rechecks_access_at_send_time(client, dist, monkeypatch, sent_emails):
    """A delivery queued while the member could distribute is not sent once
    they have left the organization: the send uses current permissions."""
    from app import decision_asset_email_service as service
    from app.models import OrganizationMember

    monkeypatch.setattr("app.routes.decision_asset_email.start_delivery", lambda _id: None)
    response = _call(client, dist, "editor", "POST", "/api/v1/email-assets/threads/t-shared",
                     {"idempotency_key": f"p2c-late-{uuid.uuid4().hex[:8]}",
                      "scorecard_id": dist["projects"]["editor"][1], "output_types": ["scorecards"]})
    assert response.status_code == 202
    delivery = DecisionAssetEmail.query.filter_by(user_id=dist["users"]["editor"].id).one()
    OrganizationMember.query.filter_by(
        organization_id=dist["org"].id, user_id=dist["users"]["editor"].id,
    ).delete()
    _db.session.commit()
    service.process_delivery(delivery.id)
    _db.session.expire_all()
    delivery = DecisionAssetEmail.query.get(delivery.id)
    assert delivery.status == "failed"
    assert sent_emails == []


def test_email_assets_report_an_unknown_project(client, dist, sent_emails):
    response = _call(client, dist, "owner", "POST", "/api/v1/email-assets/threads/t-missing",
                     {"idempotency_key": "p2c-missing-0001", "output_types": ["scorecards"]})
    assert response.status_code == 404
    assert response.get_json()["code"] == "thread_not_found"
    assert sent_emails == []


# --- Former members ----------------------------------------------------------

def test_removal_keeps_the_project_its_scorecards_and_attribution(client, dist, monkeypatch, report_calls,
                                                                  sent_emails):
    """Leaving the organization revokes a former member's access on every
    distribution surface (enforce mode) and erases nothing they made."""
    from app.models import Scorecard
    monkeypatch.setenv("ORG_ACCESS_ENFORCEMENT", "enforce")
    former = dist["users"]["former-member"]
    thread_id, card_id = dist["projects"]["former-member"]
    before = _project_state(thread_id)

    for route, template in sorted(EXPORT_ROUTES.items()):
        response = _call(client, dist, "former-member", "GET", template.format(t=thread_id, c=card_id))
        assert response.status_code == 404, route
        assert MARKER.encode() not in _content_bytes(response), route
    for method, path, body in [
        ("POST", "/api/v1/reports/generate", {"thread_id": thread_id, "report_type": "detailed"}),
        ("POST", "/api/v1/shares/preview", {"artifact_type": "scorecard", "thread_id": thread_id}),
        ("POST", "/api/v1/shares", {"artifact_type": "scorecard", "thread_id": thread_id,
                                    "disclosure_review_confirmed": True}),
        ("POST", f"/api/v1/email-assets/threads/{thread_id}",
         {"idempotency_key": "former-0001", "output_types": ["scorecards"]}),
        ("POST", "/api/v1/starters", {"thread_id": thread_id, "name": "Former"}),
    ]:
        response = _call(client, dist, "former-member", method, path, body)
        assert response.status_code == 404, path
        assert MARKER.encode() not in response.data, path
    assert report_calls == [] and sent_emails == []
    assert SharedArtifact.query.filter_by(owner_user_id=former.id).count() == 0
    assert DecisionAssetEmail.query.filter_by(user_id=former.id).count() == 0
    assert SavedStarter.query.filter_by(user_id=former.id).count() == 0

    # Nothing they made is erased or re-attributed: same rows, same authors.
    assert _project_state(thread_id) == before
    row = UserSession.query.filter_by(session_id=thread_id).one()
    assert str(row.created_by_user_id or row.user_id) == str(former.id)
    assert {c.user_id for c in Scorecard.query.filter_by(thread_id=thread_id).all()} == {former.id}
    # The organization keeps the project: its owner still reads and exports it.
    response = _call(client, dist, "owner", "GET", EXPORT_ROUTES["scorecard-pdf"].format(t=thread_id, c=card_id))
    assert response.status_code == 200 and _has_marker(response)


def test_report_mode_former_creator_is_unchanged_and_audited(client, dist, monkeypatch, sent_emails):
    """Today's default mode is report-only (SEC-06: enforcement awaits
    approval). P2c does not change that. A former member keeps reading what
    they created, through the one access seam, and the read is recorded as
    a would-be refusal; email checks membership itself and refuses, as it
    always has. Pinned so enforcement stays the only switch."""
    from app import org_access
    from app.models import OrgAccessShadowEvent

    monkeypatch.setenv("ORG_ACCESS_ENFORCEMENT", "report")
    org_access.reset_dedup()
    former = dist["users"]["former-member"]
    thread_id, card_id = dist["projects"]["former-member"]
    before = _project_state(thread_id)

    response = _call(client, dist, "former-member", "GET",
                     EXPORT_ROUTES["scorecard-pdf"].format(t=thread_id, c=card_id))
    assert response.status_code == 200
    assert OrgAccessShadowEvent.query.filter_by(
        user_id=former.id, mode="report", resource_id=thread_id,
    ).count() >= 1, "the would-be refusal is recorded for review"

    response = _call(client, dist, "former-member", "POST", f"/api/v1/email-assets/threads/{thread_id}",
                     {"idempotency_key": "former-report-1", "output_types": ["scorecards"]})
    assert response.status_code == 403
    assert response.get_json()["code"] == "workspace_access_denied"
    assert sent_emails == []
    # A former member who did not create the project has no path in either mode.
    response = _call(client, dist, "former-member", "GET",
                     EXPORT_ROUTES["scorecard-pdf"].format(t="t-shared", c="t-shared-card"))
    assert response.status_code == 404
    assert _project_state(thread_id) == before


def test_a_former_members_existing_link_keeps_its_lifecycle(client, dist, monkeypatch):
    """Removing a member does not delete, revoke or re-scope a link they made
    while a member. Whether it serves is decided by the existing link rules
    (owner plan, ownership review), exactly as before P2c."""
    from app.models import OrganizationMember
    editor = dist["users"]["editor"]
    response = _call(client, dist, "editor", "POST", "/api/v1/shares",
                     {"artifact_type": "scorecard", "thread_id": "t-shared",
                      "scorecard_id": dist["projects"]["editor"][1], "disclosure_review_confirmed": True})
    assert response.status_code == 201
    token = response.get_json()["link"]["url"].rstrip("/").split("/")[-1]
    link = SharedArtifact.query.filter_by(owner_user_id=editor.id).one()
    ownership = (_db.session.get(SharedArtifactOwnership, link.id).state, link.revoked_at)
    served_before = client.get(f"/api/v1/shares/public/{token}").status_code

    OrganizationMember.query.filter_by(organization_id=dist["org"].id, user_id=editor.id).one().status = "removed"
    _db.session.commit()
    _db.session.expire_all()
    link = SharedArtifact.query.filter_by(owner_user_id=editor.id).one()
    assert (_db.session.get(SharedArtifactOwnership, link.id).state, link.revoked_at) == ownership
    assert client.get(f"/api/v1/shares/public/{token}").status_code == served_before == 200


# --- Decision impact: the project's scorecards, each member's baseline -------

def test_a_teammates_scored_output_closes_the_owners_correction_window(app, dist):
    """Spec 3.3/3.4: the correction window is open "before analysis begins"
    and refuses writes once the thread has scored output, so no baseline can
    absorb material added after seeing analysis. In a shared project the
    owner sees a teammate's scorecard, so that output closes the window for
    the owner too. Baselines stay per member and per project, and each
    scorecard keeps its author."""
    from app.decision_impact import (
        SealedBaselineError, analysis_has_started, capture_or_update_draft, get_baseline,
    )
    from app.models import Scorecard
    from app.routes.sessions import save_user_sessions
    from app.scorecards import upsert_scorecard

    owner, editor, org = dist["users"]["owner"], dist["users"]["editor"], dist["org"]
    assert save_user_sessions(owner.id, {"t-window": {
        "session_id": "t-window", "user_id": owner.id, "name": "Window", "status": "in_progress",
        "organization_id": org.id, "visibility": "team",
        "chat_history": [{"role": "user", "content": "Choose a payroll vendor: options A or B."}],
    }})
    draft = capture_or_update_draft(owner, "t-window")
    assert draft.user_id == owner.id and not draft.is_sealed
    assert analysis_has_started(owner.id, "t-window") is False

    upsert_scorecard(user_id=editor.id, thread_id="t-window", organization_id=org.id, session_id="t-window",
                     payload={"id": "w1", "analysis_id": "w1", "project_name": "A", "jaspen_score": 70},
                     source="native")
    _db.session.commit()
    assert analysis_has_started(owner.id, "t-window") is True
    with pytest.raises(SealedBaselineError):
        capture_or_update_draft(owner, "t-window")
    baseline = get_baseline(owner.id, "t-window")
    assert (baseline.user_id, baseline.thread_id) == (owner.id, "t-window")
    assert get_baseline(editor.id, "t-window") is None, "no baseline is made for the teammate"
    assert Scorecard.query.filter_by(id="w1").one().user_id == editor.id


# --- Decision-impact source reader -------------------------------------------

@pytest.mark.parametrize("actor", ACTORS)
def test_decision_thread_sources_are_the_organizations_project(app, dist, actor):
    """decision_records._load_thread_sources reads the project the member
    may read, whoever created it; another organization gets nothing."""
    from app.decision_impact import analysis_has_started, current_measures
    from app.decision_records import _load_thread_sources

    thread_id, _card_id = dist["projects"][actor]
    user = dist["users"][actor]
    before = _project_state(thread_id)
    session, thread_data = _load_thread_sources(user.id, thread_id)
    if actor in READERS:
        assert MARKER in session["name"]
        assert thread_data["project_wbs"]["tasks"][0]["title"] == TASK_TITLE
        assert analysis_has_started(user.id, thread_id) is True
        measures, _context = current_measures(user.id, thread_id)
        assert measures["A1"]["value"] >= 1, "the project's scorecards were not counted"
    else:
        assert session is None and thread_data == {}
        assert analysis_has_started(user.id, thread_id) is False
    assert _project_state(thread_id) == before


def test_decision_impact_route_reports_an_unreadable_project(client, dist):
    response = _call(client, dist, "other-org", "GET", "/api/v1/decision-impact/baseline/t-shared")
    assert response.status_code == 404
    assert MARKER.encode() not in response.data


# --- Guards ----------------------------------------------------------------

# The P2c functions: each reads one project, so none may look it up among the
# caller's own rows.
_P2C_FUNCTIONS = {
    "app.routes.export": {
        "export_scorecard_xlsx", "export_scorecard_docx", "export_scorecard_pdf",
        "export_scorecard_pptx", "export_wbs_csv", "export_wbs_xlsx",
        "export_conversation_markdown", "export_conversation_pdf",
        "_export_project", "_scorecard_record_for_export", "_scorecard_variants_for_export",
    },
    "app.routes.reports": {"generate_report"},
    "app.routes.starters": {"create_starter"},
    "app.routes.sharing": {"_load_thread_cards", "_prepare"},
    "app.decision_asset_email_service": {"load_authorized_context"},
    "app.decision_records": {"_load_thread_sources"},
}
_PERSONAL_PROJECT_LOOKUPS = {"load_user_sessions", "_load_scenarios", "load_scenarios_data"}


def _functions(module_name):
    import importlib
    module = importlib.import_module(module_name)
    tree = ast.parse(inspect.getsource(module))
    return {node.name: node for node in ast.walk(tree) if isinstance(node, ast.FunctionDef)}


def _offenders(functions, names):
    found = []
    for name in sorted(names):
        for node in ast.walk(functions[name]):
            if isinstance(node, ast.Call):
                called = getattr(node.func, "id", None) or getattr(node.func, "attr", None)
                if called in _PERSONAL_PROJECT_LOOKUPS:
                    found.append(f"{name} line {node.lineno}: {called}()")
            elif isinstance(node, ast.ImportFrom):
                for alias in node.names:
                    if alias.name in _PERSONAL_PROJECT_LOOKUPS:
                        found.append(f"{name} line {node.lineno}: imports {alias.name}")
    return found


@pytest.mark.parametrize("module_name", sorted(_P2C_FUNCTIONS))
def test_guard_p2c_functions_read_the_project_not_the_callers_rows(module_name):
    functions = _functions(module_name)
    names = _P2C_FUNCTIONS[module_name]
    missing = names - set(functions)
    assert not missing, f"renamed or removed; update the guard list: {sorted(missing)}"
    offenders = _offenders(functions, names)
    assert not offenders, (
        "A P2c function looked the project up among the caller's own rows. Use "
        "project_scope.authorized_export_scope / authorized_thread_scope / scenarios_for_thread:\n" + "\n".join(offenders)
    )


@pytest.mark.parametrize("module_name", sorted(_P2C_FUNCTIONS))
def test_guard_no_function_with_a_thread_id_uses_a_personal_session_lookup(module_name):
    functions = _functions(module_name)
    offenders = []
    for name, node in functions.items():
        args = node.args
        if "thread_id" not in [a.arg for a in args.posonlyargs + args.args + args.kwonlyargs]:
            continue
        offenders += _offenders({name: node}, {name})
    assert not offenders, "\n".join(offenders)


def test_guard_catches_a_personal_lookup():
    tree = ast.parse(textwrap.dedent('''
        def generate_report():
            from app.routes.sessions import load_user_sessions as _load
            return _load("u")
    '''))
    functions = {node.name: node for node in ast.walk(tree) if isinstance(node, ast.FunctionDef)}
    assert _offenders(functions, {"generate_report"})
