import hashlib
from datetime import datetime
from pathlib import Path
import re
from urllib.parse import urlencode

from flask import Blueprint, current_app, jsonify, request, send_file
from flask_mail import Message
from markupsafe import escape
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer
from werkzeug.exceptions import BadRequest, UnsupportedMediaType

from app import db, limiter, mail
from app.decision_profile_service import ensure_profile_responses
from app.decision_profile import derive_decision_style, validate_answers
from app.email_templates.decision_profile_results import (
    render_decision_profile_email,
)
from app.models import EmailSuppression, Lead, LeadAttributionEvent, LeadDecisionProfile, LeadEmailDelivery, User


leads_bp = Blueprint("leads", __name__)

MAX_LEAD_PAYLOAD_BYTES = 8 * 1024
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
TOOLKIT_SOURCE = "decision-planning-toolkit"
TOOLKIT_EMAIL_TYPE = "decision_planning_toolkit"
DECISION_PROFILE_SOURCE = "decision-style-assessment"
DECISION_PROFILE_EMAIL_TYPE = "decision_profile_results"
DECISION_PROFILE_SENDER = "Jaspen <hello@jaspen.ai>"
DECISION_PROFILE_REPLY_TO = "hello@jaspen.ai"
LEAD_EMAIL_SENDER = "Jaspen <hello@jaspen.ai>"
LEAD_EMAIL_REPLY_TO = "hello@jaspen.ai"
SUBSCRIPTION_SCOPES = {
    "marketing": "Marketing",
    "updates": "Updates",
    "decision_notes": "Decision Notes",
}
TOOLKIT_OPT_IN_SCOPES = ("marketing", "updates", "decision_notes")
TOOLKIT_FILENAME = "Jaspen-Decision-Planning-Toolkit.xlsx"
HONEYPOT_FIELDS = ("website", "url", "hp_name")
FIELD_LIMITS = {
    "email": 255,
    "source": 80,
    "first_name": 120,
    "last_name": 120,
    "company": 160,
    "title": 160,
    "utm_source": 120,
    "utm_medium": 120,
    "utm_campaign": 160,
    "referrer": 512,
    "decision_style": 80,
}

TOOLKIT_SUBJECT = "Your Decision Planning Toolkit is ready"
TOOLKIT_PREVIEW = "Organize your thinking first. Then let Jaspen challenge it."
TOOLKIT_INTRO_TEXT = (
    "Thank you for requesting the Decision Planning Toolkit.\n\n"
    "I created this toolkit because many important decisions become difficult long before anyone realizes it.\n\n"
    "Not because people do not care.\n\n"
    "Because assumptions stay hidden, tradeoffs are never fully explored, and everyone leaves with a different "
    "understanding of why the decision was made.\n\n"
    "This toolkit gives you a practical place to organize your thinking before making an important decision.\n\n"
    "Use it to define your decision, build a rubric that fits your situation, capture assumptions, compare options, "
    "and collaborate with others."
)
TOOLKIT_INTRO_HTML = (
    "<p style=\"margin:0 0 14px; font-size:16px; line-height:1.65; color:#d9deec;\">Thank you for requesting the Decision Planning Toolkit.</p>"
    "<p style=\"margin:0 0 14px; font-size:16px; line-height:1.65; color:#d9deec;\">I created this toolkit because many important decisions become difficult long before anyone realizes it.</p>"
    "<p style=\"margin:0 0 14px; font-size:16px; line-height:1.65; color:#d9deec;\">Not because people do not care.</p>"
    "<p style=\"margin:0 0 14px; font-size:16px; line-height:1.65; color:#d9deec;\">Because assumptions stay hidden, tradeoffs are never fully explored, and everyone leaves with a different understanding of why the decision was made.</p>"
    "<p style=\"margin:0 0 14px; font-size:16px; line-height:1.65; color:#d9deec;\">This toolkit gives you a practical place to organize your thinking before making an important decision.</p>"
    "<p style=\"margin:0; font-size:16px; line-height:1.65; color:#d9deec;\">Use it to define your decision, build a rubric that fits your situation, capture assumptions, compare options, and collaborate with others.</p>"
)
TOOLKIT_NO_ACCOUNT_COPY = (
    "A workbook can organize your thinking.\n\n"
    "It cannot ask the next question.\n\n"
    "That is where Jaspen comes in.\n\n"
    "Create a free account when you are ready to work through a real decision interactively.\n\n"
    "When the decision has real consequences for your career, business, finances, family, or the people affected by it, "
    "Essential gives you more room to test assumptions, compare tradeoffs, and preserve the reasoning behind your decision.\n\n"
    "P.S. You do not need a perfect decision process to start. Bring one real decision into Jaspen when you are ready, "
    "and let it help you pressure-test the thinking."
)
TOOLKIT_EXISTING_ACCOUNT_COPY = (
    "Once you have organized your thinking, open Jaspen and continue the conversation there.\n\n"
    "Unlike a spreadsheet, Jaspen can ask follow-up questions, challenge assumptions, highlight blind spots, and preserve "
    "your reasoning as a Decision Record.\n\n"
    "When the decision has real consequences for your career, business, finances, family, or the people affected by it, "
    "Essential gives you more room to explore evidence, pressure test assumptions, compare tradeoffs, and preserve why you made the decision.\n\n"
    "P.S. Your workspace is the place to turn this toolkit from a static exercise into a decision you can revisit, explain, and build on."
)
BOOL_FIELDS = ("marketing_opt_in",)
OPTIONAL_TEXT_FIELDS = (
    "first_name",
    "last_name",
    "company",
    "title",
    "utm_source",
    "utm_medium",
    "utm_campaign",
)


def _now():
    return datetime.utcnow()


def _lead_fingerprint(email):
    return hashlib.sha256(email.encode("utf-8")).hexdigest()[:12]


def _bad_request(code, message):
    current_app.logger.info("Lead capture validation failed: %s", code)
    return jsonify({"error": message, "code": code}), 400


def _normalized_text(data, field, *, required=False):
    value = data.get(field)
    if value is None:
        if required:
            raise ValueError(f"{field}_required")
        return None
    if not isinstance(value, str):
        raise TypeError(f"{field}_invalid_type")

    value = value.strip()
    if not value:
        if required:
            raise ValueError(f"{field}_required")
        return None
    if len(value) > FIELD_LIMITS[field]:
        raise OverflowError(f"{field}_too_long")
    return value


def _normalized_bool(data, field):
    value = data.get(field)
    if value is None:
        return False
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in ("1", "true", "yes", "on")
    return bool(value)


def _parse_payload():
    if request.content_length is not None and request.content_length > MAX_LEAD_PAYLOAD_BYTES:
        return None, _bad_request("payload_too_large", "Payload is too large.")

    if not request.is_json:
        return None, _bad_request("invalid_json", "Request body must be a JSON object.")

    try:
        data = request.get_json(silent=False)
    except (BadRequest, UnsupportedMediaType):
        return None, _bad_request("invalid_json", "Request body must be valid JSON.")

    if not isinstance(data, dict):
        return None, _bad_request("invalid_payload", "Request body must be a JSON object.")

    for field in HONEYPOT_FIELDS:
        value = data.get(field)
        if isinstance(value, str) and value.strip():
            return None, _bad_request("invalid_payload", "Invalid lead submission.")

    try:
        email = _normalized_text(data, "email", required=True).lower()
        source = _normalized_text(data, "source") or "unknown"
        optional = {field: _normalized_text(data, field) for field in OPTIONAL_TEXT_FIELDS}
        bools = {field: _normalized_bool(data, field) for field in BOOL_FIELDS}
    except ValueError as exc:
        return None, _bad_request(str(exc), "Email is required.")
    except TypeError as exc:
        return None, _bad_request(str(exc), "Lead fields must be strings.")
    except OverflowError as exc:
        return None, _bad_request(str(exc), "Lead field is too long.")

    if not EMAIL_RE.match(email):
        return None, _bad_request("invalid_email", "Email must be valid.")

    referrer = request.referrer
    if referrer:
        referrer = referrer.strip()[:FIELD_LIMITS["referrer"]]
    elif isinstance(data.get("referrer"), str):
        referrer = data["referrer"].strip() or None
        if referrer and len(referrer) > FIELD_LIMITS["referrer"]:
            return None, _bad_request("referrer_too_long", "Lead field is too long.")

    payload = {
        "email": email,
        "source": source,
        "referrer": referrer,
        "assessment_answers": data.get("assessment_answers"),
        "client_decision_style": data.get("decision_style"),
        **optional,
        **bools,
    }
    return payload, None


def _apply_non_empty_metadata(lead, payload):
    changed = False
    for field in (*OPTIONAL_TEXT_FIELDS, "referrer"):
        value = payload.get(field)
        if value and getattr(lead, field) != value:
            setattr(lead, field, value)
            changed = True
    return changed


def _apply_payload_to_lead(lead, payload):
    changed = False
    if lead.email != payload["email"]:
        lead.email = payload["email"]
        changed = True
    if lead.normalized_email != payload["email"]:
        lead.normalized_email = payload["email"]
        changed = True
    if lead.source != payload["source"]:
        lead.source = payload["source"]
        changed = True
    return _apply_non_empty_metadata(lead, payload) or changed


def _create_attribution_event(lead, payload, *, email_delivery_requested=False):
    event = LeadAttributionEvent(
        lead_id=lead.id,
        source=payload["source"],
        first_name=payload.get("first_name"),
        last_name=payload.get("last_name"),
        company=payload.get("company"),
        title=payload.get("title"),
        utm_source=payload.get("utm_source"),
        utm_medium=payload.get("utm_medium"),
        utm_campaign=payload.get("utm_campaign"),
        referrer=payload.get("referrer"),
        marketing_opt_in=bool(payload.get("marketing_opt_in")),
        email_delivery_requested=email_delivery_requested,
    )
    db.session.add(event)
    return event


def _get_or_create_lead(payload):
    lead = Lead.query.filter_by(normalized_email=payload["email"]).one_or_none()
    created = lead is None
    if created:
        lead = Lead(
            email=payload["email"],
            normalized_email=payload["email"],
            source=payload["source"],
        )
        db.session.add(lead)
    _apply_payload_to_lead(lead, payload)
    return lead, created


def _serializer(salt):
    secret = current_app.config.get("SECRET_KEY") or current_app.config.get("JWT_SECRET_KEY")
    if not secret:
        raise RuntimeError("Missing SECRET_KEY/JWT_SECRET_KEY for lead email links")
    return URLSafeTimedSerializer(secret_key=secret, salt=salt)


def _toolkit_token(email):
    return _serializer("lead-toolkit-download").dumps({"email": email, "type": TOOLKIT_EMAIL_TYPE})


def _unsubscribe_token(email, scope="marketing"):
    return _serializer("email-unsubscribe").dumps({"email": email, "scope": scope})


def _frontend_base_url():
    return (current_app.config.get("FRONTEND_BASE_URL") or "http://localhost:3000").rstrip("/")


def _toolkit_download_link(email):
    query = urlencode({"token": _toolkit_token(email)})
    return f"{request.url_root.rstrip('/')}/api/v1/public/leads/toolkit?{query}"


def _workspace_link(source="decision-profile-email"):
    query = urlencode({"auth": "signup", "source": source})
    if source == "decision-profile-email":
        return f"{_frontend_base_url()}/decision-profile?{query}"
    return f"{_frontend_base_url()}/?{query}"


def _has_user_account(email):
    normalized = str(email or "").strip().lower()
    return (
        User.query
        .filter(db.func.lower(User.email) == normalized)
        .first()
        is not None
    )


def _decision_profile_cta_label(email):
    return "View My Decision Profile" if _has_user_account(email) else "Save My Decision Profile"


def _unsubscribe_link(email, scope="marketing"):
    query = urlencode({"token": _unsubscribe_token(email, scope=scope)})
    return f"{request.url_root.rstrip('/')}/api/v1/public/leads/unsubscribe?{query}"


def _subscription_preferences(email):
    suppressions = {
        row.scope
        for row in EmailSuppression.query.filter_by(normalized_email=email).all()
    }
    return {
        scope: scope not in suppressions
        for scope in SUBSCRIPTION_SCOPES
    }


def _set_subscription_preferences(email, subscribed_scopes):
    subscribed = {
        scope
        for scope in subscribed_scopes
        if scope in SUBSCRIPTION_SCOPES
    }
    changed = False
    for scope in SUBSCRIPTION_SCOPES:
        existing = _suppression_for(email, scope)
        if scope in subscribed:
            if existing is not None:
                db.session.delete(existing)
                changed = True
            continue
        if existing is None:
            db.session.add(EmailSuppression(email=email, normalized_email=email, scope=scope, reason="preference_update"))
            changed = True
    return changed


def _render_preferences_form(email, token, *, saved=False):
    preferences = _subscription_preferences(email)
    safe_email = escape(email)
    safe_token = escape(token)
    checked = {
        scope: " checked" if subscribed else ""
        for scope, subscribed in preferences.items()
    }
    status = (
        '<p class="status">Your email preferences have been saved.</p>'
        if saved else ""
    )
    rows = "\n".join(
        f"""
        <label class="option">
          <input type="checkbox" name="subscribed_scopes" value="{scope}"{checked[scope]}>
          <span>{escape(label)}</span>
        </label>
        """
        for scope, label in SUBSCRIPTION_SCOPES.items()
    )
    return f"""<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>Jaspen email preferences</title>
    <style>
      body {{ margin: 0; font-family: Arial, sans-serif; background: #f6f7fb; color: #172033; }}
      main {{ max-width: 560px; margin: 48px auto; padding: 28px; background: #fff; border: 1px solid #e7eaf3; border-radius: 16px; }}
      h1 {{ margin: 0 0 10px; font-size: 28px; }}
      p {{ color: #526070; line-height: 1.5; }}
      .status {{ color: #047857; font-weight: 700; }}
      .option, .all-option {{ display: flex; gap: 10px; align-items: center; padding: 12px 0; border-top: 1px solid #eef1f7; font-weight: 700; }}
      .all-option {{ margin-top: 10px; border-top: 0; color: #a0036c; }}
      button {{ margin-top: 18px; padding: 12px 16px; border: 0; border-radius: 8px; background: #a0036c; color: #fff; font-weight: 700; cursor: pointer; }}
      .fine {{ font-size: 13px; color: #667085; }}
    </style>
  </head>
  <body>
    <main>
      <h1>Email preferences</h1>
      <p>Choose what {safe_email} should receive from Jaspen.</p>
      {status}
      <form method="post" action="/api/v1/public/leads/unsubscribe?token={safe_token}">
        <input type="hidden" name="preferences_form" value="1">
        <label class="all-option">
          <input type="checkbox" id="all-preferences">
          <span>All / deselect all</span>
        </label>
        {rows}
        <button type="submit">Save preferences</button>
      </form>
      <p class="fine">Unchecking a category unsubscribes you from that type of email. You can change this any time from an unsubscribe link.</p>
    </main>
    <script>
      const allBox = document.getElementById('all-preferences');
      const boxes = Array.from(document.querySelectorAll('input[name="subscribed_scopes"]'));
      function syncAll() {{
        allBox.checked = boxes.every((box) => box.checked);
        allBox.indeterminate = boxes.some((box) => box.checked) && !allBox.checked;
      }}
      allBox.addEventListener('change', () => boxes.forEach((box) => {{ box.checked = allBox.checked; }}));
      boxes.forEach((box) => box.addEventListener('change', syncAll));
      syncAll();
    </script>
  </body>
</html>"""


def _toolkit_file_path():
    return Path(current_app.root_path).parent / "assets" / TOOLKIT_FILENAME


def _suppression_for(email, scope):
    return EmailSuppression.query.filter_by(normalized_email=email, scope=scope).one_or_none()


def _record_marketing_opt_in(email, opted_in):
    if not opted_in:
        return False
    removed = False
    for scope in TOOLKIT_OPT_IN_SCOPES:
        existing = _suppression_for(email, scope)
        if existing is not None:
            db.session.delete(existing)
            removed = True
    return removed


def _send_toolkit_email(email):
    download_link = _toolkit_download_link(email)
    workspace_link = _workspace_link("decision-planning-toolkit-email")
    unsubscribe = _unsubscribe_link(email, scope="marketing")
    has_account = _has_user_account(email)
    workspace_cta = "Open My Workspace" if has_account else "Create a free account"
    account_copy = TOOLKIT_EXISTING_ACCOUNT_COPY if has_account else TOOLKIT_NO_ACCOUNT_COPY
    account_copy_html = "".join(
        f'<p style="margin:0 0 14px; font-size:15px; line-height:1.65; color:#4f5d75;">{escape(part)}</p>'
        for part in account_copy.split("\n\n")
    )
    download_link_html = escape(download_link)
    workspace_link_html = escape(workspace_link)
    unsubscribe_html = escape(unsubscribe)
    msg = Message(
        subject=TOOLKIT_SUBJECT,
        recipients=[email],
        sender=LEAD_EMAIL_SENDER,
        reply_to=LEAD_EMAIL_REPLY_TO,
    )
    msg.body = (
        f"{TOOLKIT_SUBJECT}\n\n"
        f"{TOOLKIT_PREVIEW}\n\n"
        "Hi there,\n\n"
        f"{TOOLKIT_INTRO_TEXT}\n\n"
        "Download the Decision Planning Toolkit:\n"
        f"{download_link}\n\n"
        f"{account_copy}\n\n"
        f"{workspace_cta}:\n"
        f"{workspace_link}\n\n"
        "Kind regards,\n"
        "Lydia\n\n"
        "You can unsubscribe from Jaspen updates here:\n"
        f"{unsubscribe}\n\n"
        "Jaspen\n"
        f"{_frontend_base_url()}"
    )
    msg.html = f"""<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>Decision Planning Toolkit</title>
  </head>
  <body style="margin:0; padding:0; background:#eff9fc; font-family: Arial, sans-serif; color: #172033; line-height: 1.5;">
    <div style="display:none; max-height:0; overflow:hidden; opacity:0; color:transparent;">{escape(TOOLKIT_PREVIEW)}</div>
    <table role="presentation" width="100%" cellspacing="0" cellpadding="0" style="background:#eff9fc; padding:28px 12px;">
      <tr>
        <td align="center">
          <table role="presentation" width="100%" cellspacing="0" cellpadding="0" style="max-width:640px; background:#ffffff; border:1px solid #cde7f0; border-radius:18px; overflow:hidden;">
            <tr>
              <td style="padding:24px 28px; background:#161f3b;">
                <div style="font-size:24px; line-height:1; color:#ffffff; font-weight:700;">Jaspen</div>
              </td>
            </tr>
            <tr>
              <td style="padding:34px 28px 26px; background:#161f3b;">
                <p style="margin:0 0 10px; font-size:13px; line-height:1.4; letter-spacing:.08em; text-transform:uppercase; color:#f0a6d4; font-weight:700;">Decision Planning Toolkit</p>
                <h1 style="margin:0 0 12px; font-size:28px; line-height:1.18; color:#ffffff;">A practical place to organize your thinking</h1>
                <p style="margin:0 0 14px; font-size:16px; line-height:1.65; color:#d9deec;">Hi there,</p>
                {TOOLKIT_INTRO_HTML}
              </td>
            </tr>
            <tr>
              <td align="center" style="padding:24px 28px 18px;">
                <a href="{download_link_html}" style="display:inline-block; padding:13px 18px; background:#a0036c; color:#ffffff; text-decoration:none; border-radius:8px; font-size:15px; font-weight:700;">Download the Decision Planning Toolkit</a>
              </td>
            </tr>
            <tr>
              <td style="padding:8px 28px 6px;">
                <table role="presentation" width="100%" cellspacing="0" cellpadding="0" style="background:#eff9fc; border:1px solid #cde7f0; border-radius:14px;">
                  <tr>
                    <td style="padding:20px;">
                      {account_copy_html}
                      <p style="margin:0 0 4px; font-size:15px; line-height:1.65; color:#4f5d75;">Kind regards,</p>
                      <p style="margin:0; font-size:15px; line-height:1.65; color:#4f5d75;">Lydia</p>
                    </td>
                  </tr>
                </table>
              </td>
            </tr>
            <tr>
              <td align="center" style="padding:18px 28px 34px;">
                <a href="{workspace_link_html}" style="display:inline-block; padding:13px 18px; background:#a0036c; color:#ffffff; text-decoration:none; border-radius:8px; font-size:15px; font-weight:700;">{escape(workspace_cta)}</a>
              </td>
            </tr>
            <tr>
              <td style="padding:22px 28px; background:#161f3b;">
                <p style="margin:0; font-size:13px; line-height:1.5; color:#d9deec;">You can unsubscribe from Jaspen updates <a href="{unsubscribe_html}" style="color:#f0a6d4;">here</a>.</p>
              </td>
            </tr>
          </table>
        </td>
      </tr>
    </table>
  </body>
</html>"""
    msg.extra_headers = {
        "List-Unsubscribe": f"<{unsubscribe}>, <mailto:support@jaspen.ai?subject=unsubscribe>",
        "List-Unsubscribe-Post": "List-Unsubscribe=One-Click",
    }
    mail.send(msg)


def _send_decision_profile_email(email, style):
    unsubscribe = _unsubscribe_link(email, scope="marketing")
    rendered = render_decision_profile_email(
        style,
        workspace_url=_workspace_link(),
        unsubscribe_url=unsubscribe,
        cta_label=_decision_profile_cta_label(email),
    )
    msg = Message(
        subject=rendered["subject"],
        recipients=[email],
        sender=DECISION_PROFILE_SENDER,
        reply_to=DECISION_PROFILE_REPLY_TO,
    )
    msg.body = rendered["body"]
    msg.html = rendered["html"]
    msg.extra_headers = {
        "List-Unsubscribe": f"<{unsubscribe}>, <mailto:support@jaspen.ai?subject=unsubscribe>",
        "List-Unsubscribe-Post": "List-Unsubscribe=One-Click",
    }
    mail.send(msg)


def _record_email_delivery(lead, event, email, status, provider_message=None, *, email_type=TOOLKIT_EMAIL_TYPE):
    delivery = LeadEmailDelivery(
        lead_id=lead.id,
        attribution_event_id=getattr(event, "id", None),
        email=email,
        email_type=email_type,
        status=status,
        provider_message=(provider_message or "")[:255] or None,
        sent_at=_now() if status == "sent" else None,
    )
    db.session.add(delivery)
    return delivery


def _profile_from_payload(payload):
    if payload["source"] != DECISION_PROFILE_SOURCE:
        return None
    try:
        answers = validate_answers(payload.get("assessment_answers"))
    except ValueError as exc:
        raise ValueError(str(exc)) from exc

    client_style_key = payload.get("client_decision_style")
    if client_style_key is not None:
        if not isinstance(client_style_key, str):
            raise ValueError("decision_style_invalid")
        client_style_key = client_style_key.strip()[:FIELD_LIMITS["decision_style"]] or None

    derived = derive_decision_style(answers)
    return {
        "answers": answers,
        "client_style_key": client_style_key,
        "verified_style_key": derived["style"]["key"],
        "style_name": derived["style"]["name"],
        "style": derived["style"],
        "is_fallback": derived["is_fallback"],
        "affinity": derived["affinity"],
    }


def _create_decision_profile(lead, event, payload, profile):
    row = LeadDecisionProfile(
        lead_id=lead.id,
        attribution_event_id=event.id,
        email=payload["email"],
        normalized_email=payload["email"],
        source=payload["source"],
        answers=profile["answers"],
        client_style_key=profile["client_style_key"],
        verified_style_key=profile["verified_style_key"],
        style_name=profile["style_name"],
        is_fallback=profile["is_fallback"],
        affinity=profile["affinity"],
    )
    db.session.add(row)
    db.session.flush()
    ensure_profile_responses(row)
    return row


def _commit_capture(payload):
    needs_toolkit_email = payload["source"] == TOOLKIT_SOURCE
    needs_decision_profile_email = payload["source"] == DECISION_PROFILE_SOURCE
    profile = _profile_from_payload(payload)
    lead, created = _get_or_create_lead(payload)
    db.session.flush()
    event = _create_attribution_event(
        lead,
        payload,
        email_delivery_requested=needs_toolkit_email or needs_decision_profile_email,
    )
    db.session.flush()

    if payload.get("marketing_opt_in"):
        _record_marketing_opt_in(payload["email"], True)

    if profile is not None:
        _create_decision_profile(lead, event, payload, profile)

    if needs_toolkit_email:
        try:
            _send_toolkit_email(payload["email"])
        except Exception as exc:
            current_app.logger.exception("Lead toolkit email send failed")
            _record_email_delivery(lead, event, payload["email"], "failed", str(exc))
            db.session.commit()
            return None, (jsonify({"error": "We could not email the toolkit right now. Please try again."}), 502)
        _record_email_delivery(lead, event, payload["email"], "sent")

    if needs_decision_profile_email:
        try:
            _send_decision_profile_email(payload["email"], profile["style"])
        except Exception as exc:
            current_app.logger.exception("Lead decision profile email send failed")
            _record_email_delivery(
                lead,
                event,
                payload["email"],
                "failed",
                str(exc),
                email_type=DECISION_PROFILE_EMAIL_TYPE,
            )
            db.session.commit()
            return None, (jsonify({"error": "We could not email your Decision Profile right now. Please try again."}), 502)
        _record_email_delivery(
            lead,
            event,
            payload["email"],
            "sent",
            email_type=DECISION_PROFILE_EMAIL_TYPE,
        )

    db.session.commit()
    current_app.logger.info(
        "Lead captured",
        extra={"lead_source": lead.source, "lead_fingerprint": _lead_fingerprint(lead.email)},
    )
    return (lead, created, profile), None


def _decode_download_token(token):
    ttl = int(current_app.config.get("LEAD_TOOLKIT_LINK_TTL_SECONDS") or 60 * 60 * 24 * 30)
    return _serializer("lead-toolkit-download").loads(token, max_age=ttl)


@leads_bp.route("/leads", methods=["POST"])
@limiter.limit("5 per minute")
@limiter.limit("30 per hour")
def capture_lead():
    payload, error_response = _parse_payload()
    if error_response is not None:
        return error_response

    try:
        result, send_error = _commit_capture(payload)
        if send_error is not None:
            return send_error
        _, created, profile = result
        delivery = "email" if payload["source"] in (TOOLKIT_SOURCE, DECISION_PROFILE_SOURCE) else None
        body = {"ok": True, "delivery": delivery}
        if profile is not None:
            body["decision_style"] = {
                "key": profile["verified_style_key"],
                "name": profile["style_name"],
            }
        return jsonify(body), 201 if created else 200
    except ValueError as exc:
        db.session.rollback()
        return _bad_request(str(exc), "Assessment answers are required.")
    except IntegrityError:
        db.session.rollback()
        try:
            result, send_error = _commit_capture(payload)
        except ValueError as exc:
            db.session.rollback()
            return _bad_request(str(exc), "Assessment answers are required.")
        except SQLAlchemyError:
            db.session.rollback()
            current_app.logger.exception("Lead capture duplicate recovery failed")
            return jsonify({"error": "Internal server error"}), 500
        if send_error is not None:
            return send_error
        if result is not None:
            _, _, profile = result
            delivery = "email" if payload["source"] in (TOOLKIT_SOURCE, DECISION_PROFILE_SOURCE) else None
            body = {"ok": True, "delivery": delivery}
            if profile is not None:
                body["decision_style"] = {
                    "key": profile["verified_style_key"],
                    "name": profile["style_name"],
                }
            return jsonify(body), 200
        current_app.logger.exception("Lead capture uniqueness conflict could not be recovered")
        return jsonify({"error": "Internal server error"}), 500
    except SQLAlchemyError:
        db.session.rollback()
        current_app.logger.exception("Lead capture database error")
        return jsonify({"error": "Internal server error"}), 500
    except Exception:
        db.session.rollback()
        current_app.logger.exception("Lead capture unexpected error")
        return jsonify({"error": "Internal server error"}), 500


@leads_bp.route("/leads/toolkit", methods=["GET"])
@limiter.limit("60 per hour")
def download_toolkit():
    token = str(request.args.get("token") or "").strip()
    if not token:
        return jsonify({"error": "Missing download token."}), 400
    try:
        decoded = _decode_download_token(token)
    except SignatureExpired:
        return jsonify({"error": "This download link has expired."}), 410
    except BadSignature:
        return jsonify({"error": "Invalid download link."}), 400

    if decoded.get("type") != TOOLKIT_EMAIL_TYPE or not EMAIL_RE.match(str(decoded.get("email") or "")):
        return jsonify({"error": "Invalid download link."}), 400

    path = _toolkit_file_path()
    if not path.exists():
        current_app.logger.error("Toolkit asset missing: %s", path)
        return jsonify({"error": "Toolkit is temporarily unavailable."}), 503
    return send_file(path, as_attachment=True, download_name=TOOLKIT_FILENAME)


@leads_bp.route("/leads/unsubscribe", methods=["GET", "POST"])
@limiter.limit("30 per hour")
def unsubscribe():
    token = str(request.args.get("token") or "").strip()
    if not token:
        return jsonify({"error": "Missing unsubscribe token."}), 400
    try:
        decoded = _serializer("email-unsubscribe").loads(token, max_age=60 * 60 * 24 * 365)
    except (SignatureExpired, BadSignature):
        return jsonify({"error": "Invalid unsubscribe link."}), 400

    email = str(decoded.get("email") or "").strip().lower()
    scope = str(decoded.get("scope") or "marketing").strip().lower() or "marketing"
    if not EMAIL_RE.match(email):
        return jsonify({"error": "Invalid unsubscribe link."}), 400

    if request.method == "POST" and request.form.get("preferences_form") == "1":
        subscribed_scopes = request.form.getlist("subscribed_scopes")
        _set_subscription_preferences(email, subscribed_scopes)
        db.session.commit()
        return _render_preferences_form(email, token, saved=True), 200, {"Content-Type": "text/html; charset=utf-8"}

    if request.method == "POST":
        existing = _suppression_for(email, scope)
        if existing is None:
            db.session.add(EmailSuppression(email=email, normalized_email=email, scope=scope, reason="unsubscribe"))
            db.session.commit()
        return jsonify({"ok": True}), 200

    return _render_preferences_form(email, token), 200, {"Content-Type": "text/html; charset=utf-8"}
