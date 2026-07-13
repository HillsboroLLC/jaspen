"""Shared Decision Profile persistence and serialization helpers."""

from datetime import datetime

from app import db
from app.decision_profile import derive_decision_style, validate_answers
from app.decision_profile_content import (
    QUESTION_PROFILES,
    answer_profile,
    style_copy,
    tendency_labels,
)
from app.models import (
    Lead,
    LeadAttributionEvent,
    LeadDecisionProfile,
    LeadDecisionProfileResponse,
)

LOGGED_IN_SOURCE = "logged-in-decision-profile"


def _now():
    return datetime.utcnow()


def normalize_email(value):
    return str(value or "").strip().lower()


def _ordered_answers(answers):
    answers = answers or {}
    ordered = []
    for question in QUESTION_PROFILES:
        answer_id = answers.get(question["id"])
        if answer_id:
            ordered.append((question["id"], answer_id))
    for question_id, answer_id in answers.items():
        if not any(question_id == existing_id for existing_id, _ in ordered):
            ordered.append((question_id, answer_id))
    return ordered


def ensure_profile_responses(profile):
    LeadDecisionProfileResponse.query.filter_by(decision_profile_id=profile.id).delete()
    for question_id, answer_id in _ordered_answers(profile.answers):
        item = answer_profile(question_id, answer_id)
        db.session.add(
            LeadDecisionProfileResponse(
                decision_profile_id=profile.id,
                question_id=item["question_id"],
                answer_id=item["answer_id"],
                question=item["question"],
                tendency=item["tendency"],
                answer_label=item["answer_label"],
                meaning=item["meaning"],
            )
        )


def _response_rows(profile):
    rows = (
        LeadDecisionProfileResponse.query
        .filter_by(decision_profile_id=profile.id)
        .order_by(LeadDecisionProfileResponse.id.asc())
        .all()
    )
    if rows:
        return rows
    ensure_profile_responses(profile)
    db.session.flush()
    return (
        LeadDecisionProfileResponse.query
        .filter_by(decision_profile_id=profile.id)
        .order_by(LeadDecisionProfileResponse.id.asc())
        .all()
    )


def _mark_user_profiles_not_current(user_id):
    if not user_id:
        return
    (
        LeadDecisionProfile.query
        .filter(
            LeadDecisionProfile.user_id == str(user_id),
            LeadDecisionProfile.is_current.is_(True),
        )
        .update({"is_current": False}, synchronize_session=False)
    )


def _next_user_version(user_id):
    latest = (
        LeadDecisionProfile.query
        .filter_by(user_id=str(user_id))
        .order_by(LeadDecisionProfile.version.desc(), LeadDecisionProfile.id.desc())
        .first()
    )
    return int(getattr(latest, "version", 0) or 0) + 1


def _get_or_create_lead_for_user(user, source):
    email = normalize_email(user.email)
    lead = Lead.query.filter_by(normalized_email=email).one_or_none()
    if lead is None:
        lead = Lead(email=email, normalized_email=email, source=source)
        db.session.add(lead)
        db.session.flush()
    else:
        lead.email = email
        lead.normalized_email = email
        lead.source = source
        lead.updated_at = _now()
    event = LeadAttributionEvent(
        lead_id=lead.id,
        source=source,
        email_delivery_requested=False,
    )
    db.session.add(event)
    db.session.flush()
    return lead, event


def create_user_decision_profile(user, answers, source=LOGGED_IN_SOURCE):
    validated = validate_answers(answers)
    derived = derive_decision_style(validated)
    email = normalize_email(user.email)
    _mark_user_profiles_not_current(user.id)
    lead, event = _get_or_create_lead_for_user(user, source)
    profile = LeadDecisionProfile(
        lead_id=lead.id,
        attribution_event_id=event.id,
        user_id=str(user.id),
        email=email,
        normalized_email=email,
        source=source,
        answers=validated,
        client_style_key=None,
        verified_style_key=derived["style"]["key"],
        style_name=derived["style"]["name"],
        is_fallback=derived["is_fallback"],
        affinity=derived["affinity"],
        completed_at=_now(),
        updated_at=_now(),
        version=_next_user_version(user.id),
        is_current=True,
    )
    db.session.add(profile)
    db.session.flush()
    ensure_profile_responses(profile)
    return profile


def link_latest_public_decision_profile_for_user(user):
    email = normalize_email(user.email)
    if not email:
        return None
    current = (
        LeadDecisionProfile.query
        .filter_by(user_id=str(user.id), is_current=True)
        .order_by(LeadDecisionProfile.completed_at.desc(), LeadDecisionProfile.id.desc())
        .first()
    )
    if current:
        return current
    profile = (
        LeadDecisionProfile.query
        .filter(
            LeadDecisionProfile.normalized_email == email,
            LeadDecisionProfile.user_id.is_(None),
        )
        .order_by(LeadDecisionProfile.created_at.desc(), LeadDecisionProfile.id.desc())
        .first()
    )
    if profile is None:
        return None
    _mark_user_profiles_not_current(user.id)
    profile.user_id = str(user.id)
    profile.version = _next_user_version(user.id)
    profile.is_current = True
    profile.completed_at = profile.completed_at or profile.created_at or _now()
    profile.updated_at = _now()
    ensure_profile_responses(profile)
    return profile


def get_current_profile_for_user(user):
    profile = (
        LeadDecisionProfile.query
        .filter_by(user_id=str(user.id), is_current=True)
        .order_by(LeadDecisionProfile.completed_at.desc(), LeadDecisionProfile.id.desc())
        .first()
    )
    if profile:
        return profile
    return link_latest_public_decision_profile_for_user(user)


def _iso(value):
    return value.isoformat() if value else None


def serialize_decision_profile(profile):
    if profile is None:
        return {"has_profile": False, "profile": None}
    copy = style_copy(profile.verified_style_key)
    tendencies = tendency_labels(profile.answers)
    rows = _response_rows(profile)
    return {
        "has_profile": True,
        "profile": {
            "id": profile.id,
            "style_key": profile.verified_style_key,
            "style_name": profile.style_name,
            "interpretation": copy["explanation"],
            "source": profile.source,
            "version": profile.version,
            "completed_at": _iso(profile.completed_at or profile.created_at),
            "last_updated_at": _iso(profile.updated_at or profile.completed_at or profile.created_at),
            "responses": [
                {
                    "question_id": row.question_id,
                    "answer_id": row.answer_id,
                    "question": row.question,
                    "tendency": row.tendency,
                    "answer_label": row.answer_label,
                    "meaning": row.meaning,
                }
                for row in rows
            ],
            "sections": {
                "shows_up": copy["shows_up"],
                "natural_strength": copy["strength"],
                "watch": copy["watch"],
                "decision_tendencies": [
                    {
                        "label": answer_profile(question_id, answer_id)["tendency"],
                        "value": tendencies.get(question_id, "Usually"),
                    }
                    for question_id, answer_id in _ordered_answers(profile.answers)
                ],
                "jaspen_support": copy["support"],
                "questions": copy["questions"],
                "history": "Future versions will show how this profile changes as you retake the assessment and use Jaspen on real decisions.",
                "additional_context": "Add work context, decision types, or team preferences here as the profile grows.",
            },
        },
    }
