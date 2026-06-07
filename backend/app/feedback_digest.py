import json
import os
from collections import Counter, defaultdict
from datetime import datetime, time, timedelta, timezone

from flask import current_app
from flask_mail import Message

from app import mail
from app.models import User, UserSession


THEME_KEYWORDS = {
    "unclear next steps": ("next step", "what now", "unclear", "confusing", "where do i", "how do i"),
    "wrong or missing context": ("wrong", "missing", "didn't use", "did not use", "not what i asked", "irrelevant"),
    "scorecard quality": ("score", "scorecard", "rubric", "criteria", "weight"),
    "execution planning": ("execution", "task", "timeline", "owner", "wbs", "roadmap"),
    "speed or reliability": ("slow", "stuck", "failed", "error", "timeout", "loading"),
    "helpful synthesis": ("helpful", "clear", "useful", "good", "great", "accurate"),
}


def _utc_now():
    return datetime.now(timezone.utc).replace(tzinfo=None)


def previous_month_range(now=None):
    today = (now or _utc_now()).date()
    first_this_month = today.replace(day=1)
    last_prev_month = first_this_month - timedelta(days=1)
    first_prev_month = last_prev_month.replace(day=1)
    return (
        datetime.combine(first_prev_month, time.min),
        datetime.combine(first_this_month, time.min),
    )


def _parse_date(value):
    if not value:
        return None
    if isinstance(value, datetime):
        return value.replace(tzinfo=None)
    raw = str(value).strip()
    if not raw:
        return None
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        if parsed.tzinfo:
            parsed = parsed.astimezone(timezone.utc).replace(tzinfo=None)
        return parsed
    except Exception:
        return None


def _session_chat_history(payload):
    if not isinstance(payload, dict):
        return []
    chat_history = payload.get("chat_history")
    if isinstance(chat_history, list):
        return chat_history
    result_blob = payload.get("result")
    if isinstance(result_blob, dict) and isinstance(result_blob.get("chat_history"), list):
        return result_blob.get("chat_history")
    return []


def _message_excerpt(content, max_len=260):
    text = " ".join(str(content or "").split())
    if len(text) <= max_len:
        return text
    return f"{text[: max_len - 1].rstrip()}..."


def _normalize_feedback(value):
    if not isinstance(value, dict):
        return None
    reaction = str(value.get("value") or "").strip().lower()
    if reaction not in {"up", "down"}:
        return None
    note = str(value.get("note") or "").strip()
    return {
        "value": reaction,
        "note": note[:1000] if note else "",
        "updated_at": _parse_date(value.get("updated_at")),
    }


def _theme_for_item(item):
    haystack = " ".join([
        str(item.get("note") or ""),
        str(item.get("message_excerpt") or ""),
        str(item.get("session_name") or ""),
    ]).lower()
    for theme, needles in THEME_KEYWORDS.items():
        if any(needle in haystack for needle in needles):
            return theme
    return "other"


def collect_feedback_items(start_at, end_at, *, limit=500):
    start_at = _parse_date(start_at) or start_at
    end_at = _parse_date(end_at) or end_at
    rows = (
        UserSession.query
        .filter(UserSession.updated_at >= start_at - timedelta(days=2))
        .filter(UserSession.updated_at < end_at + timedelta(days=2))
        .order_by(UserSession.updated_at.desc(), UserSession.id.desc())
        .limit(max(limit * 4, 250))
        .all()
    )
    user_ids = sorted({row.user_id for row in rows if row.user_id})
    users = {
        user.id: user
        for user in User.query.filter(User.id.in_(user_ids)).all()
    } if user_ids else {}

    items = []
    for row in rows:
        payload = row.payload if isinstance(row.payload, dict) else {}
        user = users.get(row.user_id)
        for idx, message in enumerate(_session_chat_history(payload)):
            if not isinstance(message, dict):
                continue
            if str(message.get("role") or "").strip().lower() != "assistant":
                continue
            feedback = _normalize_feedback(message.get("feedback"))
            if not feedback:
                continue
            feedback_at = feedback.get("updated_at") or row.updated_at
            if feedback_at < start_at or feedback_at >= end_at:
                continue
            item = {
                "thread_id": row.session_id,
                "session_name": row.name,
                "user_id": row.user_id,
                "user_email": getattr(user, "email", None),
                "user_name": getattr(user, "name", None),
                "message_index": idx,
                "value": feedback["value"],
                "note": feedback["note"],
                "feedback_at": feedback_at,
                "message_excerpt": _message_excerpt(message.get("content")),
            }
            item["theme"] = _theme_for_item(item)
            items.append(item)

    items.sort(key=lambda item: item.get("feedback_at") or datetime.min, reverse=True)
    return items[:limit]


def summarize_feedback_items(items):
    total = len(items)
    up_count = sum(1 for item in items if item.get("value") == "up")
    down_count = sum(1 for item in items if item.get("value") == "down")
    note_count = sum(1 for item in items if item.get("note"))
    theme_counts = Counter(item.get("theme") or "other" for item in items)
    by_value = defaultdict(list)
    for item in items:
        by_value[item.get("value")].append(item)
    return {
        "total": total,
        "up_count": up_count,
        "down_count": down_count,
        "note_count": note_count,
        "positive_rate": round((up_count / total) * 100, 1) if total else 0.0,
        "theme_counts": dict(theme_counts.most_common()),
        "positive_samples": by_value.get("up", [])[:5],
        "negative_samples": by_value.get("down", [])[:8],
    }


def _format_item(item):
    stamp = item.get("feedback_at")
    stamp_text = stamp.strftime("%Y-%m-%d") if isinstance(stamp, datetime) else "unknown date"
    who = item.get("user_email") or item.get("user_name") or "unknown user"
    note = item.get("note") or "(no written note)"
    return (
        f"- [{stamp_text}] {item.get('value', '').upper()} | {who} | "
        f"{item.get('session_name') or item.get('thread_id')}\n"
        f"  Note: {note}\n"
        f"  Response: {item.get('message_excerpt') or '(no response excerpt)'}"
    )


def _deterministic_digest_text(items, start_at, end_at):
    summary = summarize_feedback_items(items)
    period = f"{start_at.date().isoformat()} through {(end_at - timedelta(days=1)).date().isoformat()}"
    lines = [
        f"Jaspen monthly user feedback digest",
        f"Period: {period}",
        "",
        "Summary",
        f"- Total feedback items: {summary['total']}",
        f"- Thumbs up: {summary['up_count']}",
        f"- Thumbs down: {summary['down_count']}",
        f"- Written notes: {summary['note_count']}",
        f"- Positive rate: {summary['positive_rate']}%",
        "",
        "Themes",
    ]
    if summary["theme_counts"]:
        lines.extend([f"- {theme}: {count}" for theme, count in summary["theme_counts"].items()])
    else:
        lines.append("- No feedback was recorded in this period.")

    lines.extend(["", "Recommended actions"])
    if summary["down_count"]:
        top_negative_themes = [
            theme for theme, _count in Counter(
                item.get("theme") for item in items if item.get("value") == "down"
            ).most_common(3)
        ]
        lines.extend([
            f"- Review negative feedback around {', '.join(top_negative_themes)}.",
            "- Inspect the response excerpts below and decide whether UI copy, prompt behavior, or workflow logic needs adjustment.",
            "- Follow up on any repeated issue that appears in more than one user session.",
        ])
    else:
        lines.extend([
            "- No negative feedback this period. Review positive examples for language and behaviors worth reinforcing.",
            "- Keep monitoring written notes for early friction signals.",
        ])

    lines.extend(["", "Negative feedback samples"])
    negative_samples = summary["negative_samples"]
    lines.extend([_format_item(item) for item in negative_samples] or ["- None"])

    lines.extend(["", "Positive feedback samples"])
    positive_samples = summary["positive_samples"]
    lines.extend([_format_item(item) for item in positive_samples] or ["- None"])
    return "\n".join(lines)


def _anthropic_digest_text(items, start_at, end_at):
    api_key = (
        current_app.config.get("ANTHROPIC_API_KEY")
        or current_app.config.get("CLAUDE_API_KEY")
        or os.getenv("ANTHROPIC_API_KEY")
        or os.getenv("CLAUDE_API_KEY")
    )
    if not api_key:
        return None
    try:
        import anthropic
    except Exception:
        current_app.logger.warning("Anthropic SDK unavailable; using deterministic feedback digest")
        return None

    summary = summarize_feedback_items(items)
    compact_items = [
        {
            "value": item.get("value"),
            "note": item.get("note"),
            "theme": item.get("theme"),
            "session_name": item.get("session_name"),
            "message_excerpt": item.get("message_excerpt"),
            "feedback_at": item.get("feedback_at").isoformat() if isinstance(item.get("feedback_at"), datetime) else None,
        }
        for item in items[:80]
    ]
    prompt = (
        "Synthesize this monthly Jaspen user-feedback dataset into an operator-friendly email digest. "
        "Be concise, concrete, and action-oriented. Include: Summary, Themes, Recommended actions, "
        "Negative examples to inspect, Positive examples to reinforce. Do not invent facts.\n\n"
        f"Period: {start_at.date().isoformat()} to {(end_at - timedelta(days=1)).date().isoformat()}\n"
        f"Summary JSON: {json.dumps(summary, default=str)}\n"
        f"Feedback JSON: {json.dumps(compact_items, default=str)}"
    )
    try:
        client = anthropic.Anthropic(api_key=api_key, timeout=20.0)
        model = (
            current_app.config.get("FEEDBACK_DIGEST_ANTHROPIC_MODEL")
            or current_app.config.get("AI_AGENT_ANTHROPIC_MODEL")
            or os.getenv("FEEDBACK_DIGEST_ANTHROPIC_MODEL")
            or os.getenv("AI_AGENT_ANTHROPIC_MODEL")
            or "claude-sonnet-4-20250514"
        )
        response = client.messages.create(
            model=model,
            max_tokens=1800,
            temperature=0.2,
            system="You write concise product-operations feedback digests for a founder.",
            messages=[{"role": "user", "content": prompt}],
        )
        parts = []
        for block in getattr(response, "content", []) or []:
            text = getattr(block, "text", None)
            if text:
                parts.append(text)
        return "\n".join(parts).strip() or None
    except Exception:
        current_app.logger.exception("AI feedback digest synthesis failed; using deterministic digest")
        return None


def build_feedback_digest(start_at=None, end_at=None, *, use_ai=True, limit=500):
    if start_at is None or end_at is None:
        start_at, end_at = previous_month_range()
    items = collect_feedback_items(start_at, end_at, limit=limit)
    body = _anthropic_digest_text(items, start_at, end_at) if use_ai else None
    if not body:
        body = _deterministic_digest_text(items, start_at, end_at)
    summary = summarize_feedback_items(items)
    return {
        "start_at": start_at,
        "end_at": end_at,
        "items": items,
        "summary": summary,
        "body": body,
    }


def _recipient_list(explicit=None):
    raw_values = []
    if explicit:
        raw_values.extend(explicit if isinstance(explicit, list) else [explicit])
    raw_values.extend([
        current_app.config.get("FEEDBACK_DIGEST_RECIPIENTS"),
        os.getenv("FEEDBACK_DIGEST_RECIPIENTS"),
        current_app.config.get("ADMIN_EMAILS"),
        os.getenv("ADMIN_EMAILS"),
    ])
    recipients = []
    for raw in raw_values:
        for item in str(raw or "").split(","):
            email = item.strip()
            if email and email not in recipients:
                recipients.append(email)
    return recipients


def send_feedback_digest(digest, *, recipients=None, dry_run=False):
    resolved_recipients = _recipient_list(recipients)
    if not resolved_recipients and not dry_run:
        raise RuntimeError("No feedback digest recipients configured")
    subject = (
        "Jaspen Monthly User Feedback Digest "
        f"({digest['start_at'].date().isoformat()} to {(digest['end_at'] - timedelta(days=1)).date().isoformat()})"
    )
    if dry_run:
        return {
            "sent": False,
            "recipients": resolved_recipients,
            "subject": subject,
            "body": digest["body"],
        }
    sender = (
        current_app.config.get("MAIL_DEFAULT_SENDER")
        or os.getenv("MAIL_DEFAULT_SENDER")
        or os.getenv("DEFAULT_FROM_EMAIL")
        or "noreply@jaspen.ai"
    )
    msg = Message(
        subject=subject,
        recipients=resolved_recipients,
        sender=sender,
        body=digest["body"],
    )
    mail.send(msg)
    return {
        "sent": True,
        "recipients": resolved_recipients,
        "subject": subject,
    }
