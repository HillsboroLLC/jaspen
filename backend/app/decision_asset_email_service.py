"""Authorization-preserving assembly and delivery of decision-result emails."""

import html
import threading
from datetime import datetime

from flask import current_app

from app import db
from app.email_provider import EmailAttachment, get_transactional_email_provider
from app.evaluation_telemetry import evaluation_id_for_scorecard
from app.models import DecisionAssetEmail, Organization, UsageEvent, User
from app.orgs import active_membership_for_user
from app.routes.export import (
    PDF_MIMETYPE,
    PPTX_MIMETYPE,
    XLSX_MIMETYPE,
    _accent_hex,
    _pptx_bytes,
    _resolve_export_context,
    _resolve_thread_session,
    _safe_filename_base,
    _scorecard_component_rows,
    _scorecard_custom_blocks,
    _scorecard_pdf_bytes,
    _scorecard_record_for_export,
    _wbs_xlsx_bytes,
)
from app.routes.sessions import load_user_sessions
from app.routes.strategy import _load_scenarios, _resolve_thread_wbs
from app.scorecards import collect_peer_scorecards


SUPPORTED_OUTPUT_TYPES = frozenset({
    "ranked_ideas",
    "scorecards",
    "tradeoff",
    "why_this_order",
    "evidence_gaps_assumptions_risks",
    "what_could_change_order",
    "starter_execution_plan",
    "scorecard_detail",
})


class DeliveryError(RuntimeError):
    def __init__(self, category, message=None):
        super().__init__(message or category)
        self.category = category


def mask_email(value):
    email = str(value or "").strip()
    if "@" not in email:
        return "your verified email"
    local, domain = email.rsplit("@", 1)
    if len(local) <= 1:
        masked_local = "*"
    elif len(local) == 2:
        masked_local = f"{local[0]}*"
    else:
        masked_local = f"{local[0]}{'*' * min(6, len(local) - 2)}{local[-1]}"
    return f"{masked_local}@{domain}"


def delivery_json(delivery):
    return {
        "delivery_id": delivery.id,
        "status": delivery.status,
        "recipient_masked": mask_email(delivery.recipient_email),
        "output_types": list(delivery.output_types or []),
        "error_category": delivery.error_category,
        "created_at": delivery.created_at.isoformat() if delivery.created_at else None,
        "sent_at": delivery.sent_at.isoformat() if delivery.sent_at else None,
    }


def record_telemetry(delivery, event_name, *, success=True, error_category=None, provider_response=None):
    db.session.add(UsageEvent(
        user_id=delivery.user_id,
        thread_id=delivery.thread_id,
        evaluation_id=delivery.evaluation_id,
        organization_id=delivery.organization_id,
        endpoint="email_assets",
        operation_type=event_name,
        provider=delivery.provider,
        input_tokens=0,
        output_tokens=0,
        total_tokens=0,
        credits_charged=0,
        reserved_credits=0,
        settled_credits=0,
        success=bool(success),
        error_code=error_category,
        scorecard_id=delivery.scorecard_id,
        metadata_json={
            "delivery_id": delivery.id,
            "output_types": list(delivery.output_types or []),
            "provider_response": provider_response,
        },
    ))


def _text(value, default=""):
    if value is None:
        return default
    if isinstance(value, str):
        return value.strip() or default
    if isinstance(value, dict):
        for key in ("text", "summary", "risk", "assumption", "name", "title", "label", "action"):
            if value.get(key):
                return str(value[key]).strip()
        return default
    return str(value).strip() or default


def _items(value, limit=5):
    if isinstance(value, dict):
        value = list(value.values())
    if not isinstance(value, list):
        value = [value] if value else []
    rows = []
    for item in value:
        clean = _text(item)
        if clean and clean not in rows:
            rows.append(clean)
        if len(rows) >= limit:
            break
    return rows


def _score(peer):
    for key in ("jaspen_score", "overall_score", "score"):
        try:
            value = float(peer.get(key))
            if value == value:
                return value
        except (TypeError, ValueError):
            pass
    return 0.0


def _peer_name(peer):
    return _text(peer.get("project_name") or peer.get("name") or peer.get("title"), "Untitled option")


def _dimension_rows(peer):
    dimensions = peer.get("dimensions") if isinstance(peer.get("dimensions"), dict) else {}
    component_scores = peer.get("component_scores") if isinstance(peer.get("component_scores"), dict) else {}
    source = dimensions or component_scores
    rows = {}
    for key, value in source.items():
        if isinstance(value, dict):
            numeric = value.get("score")
            label = _text(value.get("label") or value.get("name"), str(key).replace("_", " ").title())
        else:
            numeric = value
            label = str(key).replace("_", " ").title()
        try:
            rows[str(key)] = (label, float(numeric))
        except (TypeError, ValueError):
            continue
    return rows


def _tradeoff_summary(ranked):
    by_dimension = {}
    for peer in ranked:
        for key, (label, score) in _dimension_rows(peer).items():
            by_dimension.setdefault(key, {"label": label, "values": []})["values"].append((score, _peer_name(peer)))
    spreads = []
    for row in by_dimension.values():
        if len(row["values"]) < 2:
            continue
        ordered = sorted(row["values"], reverse=True)
        spread = ordered[0][0] - ordered[-1][0]
        if spread > 0:
            spreads.append((spread, row["label"], ordered[0], ordered[-1]))
    spreads.sort(reverse=True)
    return [
        f"{label}: {high[1]} is strongest ({high[0]:g}); {low[1]} is weakest ({low[0]:g})."
        for _spread, label, high, low in spreads[:3]
    ]


def _first_present(record, peers, keys, limit=5):
    values = []
    for source in [record] + list(peers):
        if not isinstance(source, dict):
            continue
        for key in keys:
            values.extend(_items(source.get(key), limit=limit))
            if len(values) >= limit:
                return values[:limit]
    return values[:limit]


def _build_summary(session, scorecard, peers):
    ranked = sorted([p for p in peers if isinstance(p, dict)], key=_score, reverse=True)
    if not ranked and scorecard:
        ranked = [scorecard]
    top = ranked[0] if ranked else scorecard
    decision_name = _text(session.get("name") or (top or {}).get("project_name"), "Jaspen decision")
    generated = (scorecard or {}).get("updated_at") or (top or {}).get("createdAt") or datetime.utcnow().isoformat()
    ranking = [{"rank": index + 1, "name": _peer_name(peer), "score": _score(peer)} for index, peer in enumerate(ranked)]
    top_name = ranking[0]["name"] if ranking else decision_name

    explanation = _text(
        (top or {}).get("executive_summary")
        or (top or {}).get("summary")
        or (scorecard or {}).get("executive_summary")
    )
    if not explanation:
        explanation = (
            f"{top_name} ranked first based on the saved Jaspen score and the evidence currently available. "
            "The remaining options follow in descending score order."
        )
    elif len(ranking) > 1:
        explanation = f"{explanation} The options are listed in descending order of their saved Jaspen scores."

    tradeoffs = _tradeoff_summary(ranked)
    if not tradeoffs and len(ranking) > 1:
        tradeoffs = [f"{top_name} leads the next option by {ranking[0]['score'] - ranking[1]['score']:g} points."]

    remaining_sources = list(ranked[1:]) + ([scorecard] if scorecard and scorecard is not top else [])
    evidence_gaps = _first_present(
        top or {}, remaining_sources,
        ("evidence_gaps", "missing_evidence", "gaps", "data_gaps"),
    )
    assumptions = _first_present(top or {}, remaining_sources, ("assumptions", "key_assumptions"))
    risks = _first_present(top or {}, remaining_sources, ("top_risks", "risks"))
    change_order = _first_present(
        top or {}, remaining_sources,
        ("what_could_change_order", "what_could_change_ranking", "ranking_sensitivities", "sensitivity"),
    )
    if not change_order:
        change_order = evidence_gaps[:3]
    if not change_order and tradeoffs:
        change_order = ["New evidence that materially changes the largest tradeoffs above could change the order."]

    next_step = _text((top or {}).get("recommended_scenario"))
    if not next_step:
        next_step = _text(((top or {}).get("recommendations") or [None])[0])
    if not next_step:
        next_step = _text(((top or {}).get("next_steps") or [None])[0])
    if not next_step:
        next_step = _text((scorecard or {}).get("recommended_scenario"))
    if not next_step:
        next_step = _text(((scorecard or {}).get("recommendations") or [None])[0])
    if not next_step:
        next_step = f"Validate the most important evidence gap before committing resources to {top_name}."

    confidence = _confidence_blocks(top, ranked)
    return {
        "confidence_html": confidence["html"],
        "confidence_text": confidence["text"],
        "decision_name": decision_name,
        "generated": str(generated),
        "ranking": ranking,
        "top_name": top_name,
        "explanation": explanation,
        "tradeoffs": tradeoffs,
        "evidence_gaps": evidence_gaps,
        "assumptions": assumptions,
        "risks": risks,
        "change_order": change_order,
        "next_step": next_step,
    }



def _confidence_blocks(scorecard, peers=None):
    """Rendered Decision Confidence blocks for an email, or empty strings.

    Scorecards written before the report existed carry no evidence_profile, so
    they render nothing rather than a hollow section. Failure here must never
    cost a delivery: the rest of the email is still worth sending.
    """
    try:
        from app.decision_report import build_report
        from app.decision_report_email import render_report_html, render_report_text

        report = build_report(scorecard or {}, peers=peers)
        if not report:
            return {"html": "", "text": ""}
        return {"html": render_report_html(report), "text": render_report_text(report)}
    except Exception:
        current_app.logger.exception("decision confidence email block failed")
        return {"html": "", "text": ""}


def _bullet_text(title, values):
    if not values:
        return f"{title}: None recorded."
    return f"{title}:\n" + "\n".join(f"- {value}" for value in values)


def _bullet_html(title, values):
    safe_title = html.escape(title)
    if not values:
        return f"<h2>{safe_title}</h2><p>None recorded.</p>"
    items = "".join(f"<li>{html.escape(str(value))}</li>" for value in values)
    return f"<h2>{safe_title}</h2><ul>{items}</ul>"


def render_email(summary):
    ranking_text = "\n".join(
        f"{item['rank']}. {item['name']} ({item['score']:g})"
        for item in summary["ranking"]
    ) or "No ranked options recorded."
    text_body = "\n\n".join([
        "WHY THIS ORDER",
        summary["decision_name"],
        f"Generated: {summary['generated']}",
        f"Ranked order:\n{ranking_text}",
        f"Top-ranked option: {summary['top_name']}",
        f"Why this order:\n{summary['explanation']}",
        _bullet_text("Most important tradeoffs", summary["tradeoffs"]),
        _bullet_text("Evidence gaps", summary["evidence_gaps"]),
        summary.get("confidence_text") or "",
        _bullet_text("Assumptions", summary["assumptions"]),
        _bullet_text("Risks", summary["risks"]),
        _bullet_text("What could change the order", summary["change_order"]),
        f"Recommended next step:\n{summary['next_step']}",
        "Attached files are copies of the downloadable assets available in Jaspen when this email was prepared.",
    ])

    ranking_html = "".join(
        f"<li><strong>{html.escape(item['name'])}</strong> <span>({item['score']:g})</span></li>"
        for item in summary["ranking"]
    ) or "<li>No ranked options recorded.</li>"
    html_body = f"""<!doctype html>
<html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<style>
body{{margin:0;background:#f5f7fa;color:#161f3b;font-family:Arial,sans-serif;line-height:1.45}}
.wrap{{max-width:720px;margin:24px auto;background:#fff;border:1px solid #e2e8f0;border-radius:14px;overflow:hidden}}
.header{{padding:28px 32px;background:#161f3b;color:#fff;border-bottom:4px solid #a0036c}}
.header small{{letter-spacing:.12em;text-transform:uppercase;color:#d8e3ef}}
.content{{padding:28px 32px}}h1{{font-size:26px;margin:8px 0 4px}}h2{{font-size:15px;text-transform:uppercase;letter-spacing:.06em;margin:24px 0 8px;color:#64748b}}
p,li{{font-size:15px}}ol,ul{{padding-left:22px}}.top{{border-left:4px solid #a0036c;padding:12px 16px;background:#faf5f9}}
.footer{{padding:18px 32px;background:#f8fafc;color:#64748b;font-size:12px;border-top:1px solid #e2e8f0}}
</style></head><body><div class="wrap">
<div class="header"><small>Why this order</small><h1>{html.escape(summary['decision_name'])}</h1><div>Generated {html.escape(summary['generated'])}</div></div>
<div class="content"><h2>Ranked order</h2><ol>{ranking_html}</ol>
<div class="top"><strong>Top-ranked option</strong><br>{html.escape(summary['top_name'])}</div>
<h2>Why this order</h2><p>{html.escape(summary['explanation'])}</p>
{_bullet_html('Most important tradeoffs', summary['tradeoffs'])}
{_bullet_html('Evidence gaps', summary['evidence_gaps'])}
{summary.get('confidence_html') or ''}
{_bullet_html('Assumptions', summary['assumptions'])}
{_bullet_html('Risks', summary['risks'])}
{_bullet_html('What could change the order', summary['change_order'])}
<h2>Recommended next step</h2><p>{html.escape(summary['next_step'])}</p></div>
<div class="footer">Attached files are copies of the downloadable assets available in Jaspen when this email was prepared.</div>
</div></body></html>"""
    return text_body, html_body


def _build_scorecard_detail_summary(scorecard, *, workspace_url=None):
    """Summary for a single-scorecard email that mirrors the on-screen
    Workspace card layout (SCORE / EXECUTIVE SUMMARY / DIMENSIONS / TOP RISKS
    / any custom blocks) - as opposed to the multi-peer "why this order"
    ranked-comparison shape used for tradeoff/execution deliveries, which
    doesn't resemble a single scorecard's real on-screen layout at all."""
    project_name = _text(scorecard.get("project_name"), "Jaspen decision")
    generated = str(scorecard.get("updated_at") or datetime.utcnow().isoformat())
    try:
        score_display = f"{float(scorecard.get('jaspen_score')):g}"
    except (TypeError, ValueError):
        score_display = "N/A"
    category = _text(scorecard.get("score_category"), "").upper()
    executive_summary = _text(
        scorecard.get("executive_summary") or scorecard.get("summary"),
        "No executive summary recorded.",
    )
    dimensions = []
    for row in _scorecard_component_rows(scorecard):
        try:
            raw_value = float(row.get("value"))
        except (TypeError, ValueError):
            continue
        # Some scorecards store a dimension score as "75" meaning 7.5/10
        # rather than 7.5 directly (see the identical normalization in
        # _scorecard_pdf_bytes's ScoreBar) - without this, a value already
        # >10 makes the bar fill (and overflow) past 100%.
        value = raw_value / 10 if raw_value > 10 else raw_value
        dimensions.append({"label": row["label"], "value": value})
    risks = _items(scorecard.get("top_risks") or scorecard.get("risks"), limit=8)
    recommended = _text(scorecard.get("recommended_scenario"))
    if not recommended:
        recommended_items = _items(scorecard.get("recommendations"), limit=1)
        recommended = recommended_items[0] if recommended_items else ""
    custom_blocks = [
        {"heading": block["heading"], "body": block["body"]}
        for block in _scorecard_custom_blocks(scorecard)
        if block.get("body")
    ]
    return {
        "project_name": project_name,
        "generated": generated,
        "score_display": score_display,
        "category": category,
        "accent_hex": _accent_hex(scorecard),
        "executive_summary": executive_summary,
        "dimensions": dimensions,
        "risks": risks,
        "recommended": recommended,
        "custom_blocks": custom_blocks,
        "workspace_url": workspace_url,
    }


def render_scorecard_detail_email(summary):
    accent = summary["accent_hex"]
    text_lines = [
        summary["project_name"],
        f"Generated: {summary['generated']}",
        f"Strategy scorecard: {summary['score_display']}" + (f" ({summary['category']})" if summary["category"] else ""),
        "",
        "EXECUTIVE SUMMARY",
        summary["executive_summary"],
    ]
    if summary["dimensions"]:
        text_lines += ["", "DIMENSIONS"]
        text_lines += [f"- {d['label']}: {d['value']:g}/10" for d in summary["dimensions"]]
    if summary["risks"]:
        text_lines += ["", "TOP RISKS"]
        text_lines += [f"- {risk}" for risk in summary["risks"]]
    for block in summary["custom_blocks"]:
        text_lines += ["", block["heading"].upper(), block["body"]]
    if summary["recommended"]:
        text_lines += ["", "RECOMMENDATION", summary["recommended"]]
    if summary.get("workspace_url"):
        text_lines += ["", f"Open in Jaspen (view, edit, or download PowerPoint): {summary['workspace_url']}"]
    text_body = "\n".join(text_lines)

    def bar_row(dim):
        pct = max(0, min(100, round((dim["value"] / 10) * 100)))
        return f"""<tr>
<td style="padding:6px 0;font-size:13px;color:#334155;width:60%">{html.escape(dim['label'])}</td>
<td style="padding:6px 0;font-size:13px;color:#0f172a;font-weight:700;text-align:right;width:15%">{dim['value']:g}/10</td>
</tr>
<tr><td colspan="2" style="padding:0 0 10px">
<table role="presentation" width="100%" cellpadding="0" cellspacing="0"><tr>
<td style="background:{accent};height:6px;border-radius:3px;width:{pct}%"></td>
<td style="background:#eef2f6;height:6px;border-radius:3px;width:{100 - pct}%"></td>
</tr></table>
</td></tr>"""

    dimensions_html = "".join(bar_row(d) for d in summary["dimensions"])
    dimensions_section = f"""
<div style="background:#fff;border:1px solid #e6eaf2;border-radius:12px;padding:20px;margin-bottom:16px">
<div style="font-size:11px;font-weight:700;letter-spacing:.06em;color:#64748b;text-transform:uppercase;margin-bottom:10px">Dimensions</div>
<table role="presentation" width="100%" cellpadding="0" cellspacing="0">{dimensions_html}</table>
</div>""" if summary["dimensions"] else ""

    risks_html = "".join(f"<li style='margin-bottom:6px'>{html.escape(risk)}</li>" for risk in summary["risks"])
    risks_section = f"""
<div style="background:#fff;border:1px solid #e6eaf2;border-radius:12px;padding:20px;margin-bottom:16px">
<div style="font-size:11px;font-weight:700;letter-spacing:.06em;color:#64748b;text-transform:uppercase;margin-bottom:10px">Top Risks</div>
<ul style="margin:0;padding-left:18px;font-size:13.5px;color:#334155">{risks_html}</ul>
</div>""" if summary["risks"] else ""

    custom_blocks_html = "".join(f"""
<div style="background:#fff;border:1px solid #e6eaf2;border-radius:12px;padding:20px;margin-bottom:16px">
<div style="font-size:11px;font-weight:700;letter-spacing:.06em;color:#64748b;text-transform:uppercase;margin-bottom:10px">{html.escape(block['heading'])}</div>
<p style="margin:0;font-size:14px;color:#334155;line-height:1.55">{html.escape(block['body'])}</p>
</div>""" for block in summary["custom_blocks"])

    recommendation_section = f"""
<div style="background:#fff;border:1px solid #e6eaf2;border-radius:12px;padding:20px;margin-bottom:16px">
<div style="font-size:11px;font-weight:700;letter-spacing:.06em;color:#64748b;text-transform:uppercase;margin-bottom:10px">Recommendation</div>
<p style="margin:0;font-size:14px;color:#334155;line-height:1.55">{html.escape(summary['recommended'])}</p>
</div>""" if summary["recommended"] else ""

    category_badge = f"""<div style="font-size:11px;font-weight:700;letter-spacing:.06em;color:{accent};text-transform:uppercase;margin-bottom:6px">{html.escape(summary['category'])}</div>""" if summary["category"] else ""

    workspace_url = summary.get("workspace_url")
    workspace_cta = f"""
<div style="text-align:center;margin-bottom:16px">
<a href="{html.escape(workspace_url)}" style="display:inline-block;background:{accent};color:#fff;text-decoration:none;font-size:14px;font-weight:700;padding:12px 24px;border-radius:8px">Open in Jaspen</a>
<div style="font-size:11px;color:#94a3b8;margin-top:8px">View, edit, or download PowerPoint</div>
</div>""" if workspace_url else ""

    html_body = f"""<!doctype html>
<html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{html.escape(summary['project_name'])}</title>
</head><body style="margin:0;background:#f5f7fa;color:#161f3b;font-family:Arial,Helvetica,sans-serif;line-height:1.45">
<div style="max-width:640px;margin:24px auto;background:#f5f7fa">
  <div style="padding:28px 4px 20px">
    <div style="font-size:11px;font-weight:700;letter-spacing:.08em;color:#64748b;text-transform:uppercase;margin-bottom:6px">Strategy Scorecard</div>
    <h1 style="font-size:24px;margin:0 0 4px;color:#161f3b">{html.escape(summary['project_name'])}</h1>
    <div style="font-size:12px;color:#64748b">Generated {html.escape(summary['generated'])}</div>
  </div>

  <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="margin-bottom:16px">
    <tr>
      <td width="34%" valign="top" style="background:#fff;border:1px solid #e6eaf2;border-radius:12px;padding:20px">
        {category_badge}
        <div style="font-size:44px;font-weight:800;color:{accent};line-height:1">{html.escape(summary['score_display'])}</div>
        <div style="font-size:11px;color:#94a3b8;margin-top:4px">Strategy scorecard</div>
      </td>
      <td width="3%"></td>
      <td valign="top" style="background:#fff;border:1px solid #e6eaf2;border-radius:12px;padding:20px">
        <div style="font-size:11px;font-weight:700;letter-spacing:.06em;color:#64748b;text-transform:uppercase;margin-bottom:10px">Executive Summary</div>
        <p style="margin:0;font-size:14px;color:#334155;line-height:1.55">{html.escape(summary['executive_summary'])}</p>
      </td>
    </tr>
  </table>

  {dimensions_section}
  {risks_section}
  {custom_blocks_html}
  {recommendation_section}
  {workspace_cta}

  <div style="padding:14px 4px;color:#94a3b8;font-size:11px">Sent from Jaspen &middot; jaspen.ai</div>
</div>
</body></html>"""
    return text_body, html_body


def load_authorized_context(user, thread_id, scorecard_id=None):
    sessions = load_user_sessions(user.id) or {}
    session = _resolve_thread_session(sessions, thread_id)
    if not isinstance(session, dict):
        raise DeliveryError("thread_not_found")

    organization_id = str(session.get("organization_id") or "").strip() or None
    if organization_id and not active_membership_for_user(organization_id, user.id):
        raise DeliveryError("workspace_access_denied")

    scenario_data = _load_scenarios(user.id) or {}
    thread_data = scenario_data.get(thread_id) if isinstance(scenario_data, dict) else {}
    peers = collect_peer_scorecards(
        user.id,
        thread_id,
        legacy_session=session,
        legacy_thread_data=thread_data or {},
    )
    ranked = sorted([peer for peer in peers if isinstance(peer, dict)], key=_score, reverse=True)
    effective_scorecard_id = str(scorecard_id or "").strip() or None
    if effective_scorecard_id is None and ranked:
        effective_scorecard_id = str(ranked[0].get("id") or ranked[0].get("analysis_id") or "").strip() or None

    scorecard, error_response = _scorecard_record_for_export(
        session,
        thread_id,
        scorecard_id=effective_scorecard_id,
        user_id=user.id,
    )
    if error_response:
        status = error_response[1] if isinstance(error_response, tuple) and len(error_response) > 1 else 404
        raise DeliveryError("scorecard_not_found" if status == 404 else "artifact_unavailable")
    project_wbs = _resolve_thread_wbs(thread_data or {}, effective_scorecard_id)
    _plan_key, org, _membership = _resolve_export_context(user, session)
    return {
        "session": session,
        "scorecard": scorecard,
        "scorecard_id": effective_scorecard_id,
        "peers": ranked,
        "project_wbs": project_wbs,
        "organization": org,
        "organization_id": organization_id,
    }


def _build_attachments(context, output_types):
    attachments = []
    scorecard = context["scorecard"]
    org = context["organization"]
    base = _safe_filename_base(scorecard.get("project_name"))

    # scorecard_detail deliveries use the HTML-body-matches-the-workspace email
    # (see render_scorecard_detail_email) with both a PowerPoint attachment
    # and an "Open in Jaspen" link back to the workspace. The server-rendered
    # PDF is a separately hand-built template that doesn't reflect the
    # on-screen block layout (and the client print/PDF path isn't reliable
    # either), so no PDF is attached here.
    if "scorecard_detail" in output_types:
        try:
            pptx = _pptx_bytes(scorecard, org=org, peers=context.get("peers"))
        except Exception as exc:
            raise DeliveryError("artifact_generation_failed") from exc
        if not pptx:
            raise DeliveryError("artifact_generation_failed")
        attachments.append(EmailAttachment(
            f"{base}-scorecard.pptx",
            PPTX_MIMETYPE,
            pptx,
        ))
        return attachments

    if {"scorecards", "ranked_ideas", "tradeoff"}.intersection(output_types):
        try:
            pdf = _scorecard_pdf_bytes(scorecard, org=org)
            pptx = _pptx_bytes(scorecard, org=org, peers=context.get("peers"))
        except Exception as exc:
            raise DeliveryError("artifact_generation_failed") from exc
        if not pdf or not pptx:
            raise DeliveryError("artifact_generation_failed")
        attachments.append(EmailAttachment(
            f"{base}-scorecard.pdf",
            PDF_MIMETYPE,
            pdf,
        ))
        attachments.append(EmailAttachment(
            f"{base}-scorecard.pptx",
            PPTX_MIMETYPE,
            pptx,
        ))

    if "starter_execution_plan" in output_types:
        project_wbs = context.get("project_wbs")
        if not isinstance(project_wbs, dict):
            raise DeliveryError("execution_plan_not_found")
        try:
            xlsx = _wbs_xlsx_bytes(
                project_wbs,
                project_name=context["session"].get("name") or scorecard.get("project_name"),
                workspace_name=getattr(org, "name", None) if isinstance(org, Organization) else None,
            )
        except Exception as exc:
            raise DeliveryError("artifact_generation_failed") from exc
        if not xlsx:
            raise DeliveryError("execution_plan_not_found")
        attachments.append(EmailAttachment(
            f"{base}-execution-plan.xlsx",
            XLSX_MIMETYPE,
            xlsx,
        ))

    max_bytes = int(current_app.config.get("DECISION_ASSET_EMAIL_MAX_ATTACHMENT_BYTES") or 0)
    total_bytes = sum(len(item.data) for item in attachments)
    if max_bytes > 0 and total_bytes > max_bytes:
        raise DeliveryError("attachments_too_large")
    return attachments


def process_delivery(delivery_id):
    delivery = DecisionAssetEmail.query.filter_by(id=delivery_id).first()
    if not delivery or delivery.status == "sent":
        return

    try:
        user = User.query.filter_by(id=delivery.user_id).first()
        if not user or not bool(user.email_verified) or not user.email:
            raise DeliveryError("verified_recipient_required")

        delivery.status = "sending"
        delivery.attempts = int(delivery.attempts or 0) + 1
        delivery.recipient_email = user.email
        delivery.error_category = None
        db.session.commit()

        context = load_authorized_context(user, delivery.thread_id, delivery.scorecard_id)
        delivery.scorecard_id = context["scorecard_id"]
        delivery.organization_id = context["organization_id"]
        delivery.evaluation_id = evaluation_id_for_scorecard(user.id, context["scorecard_id"])
        output_types = set(delivery.output_types or [])
        if "scorecard_detail" in output_types:
            frontend_base = (current_app.config.get("FRONTEND_BASE_URL") or "https://jaspen.ai").rstrip("/")
            workspace_url = f"{frontend_base}/workspace/{delivery.thread_id}/{context['scorecard_id']}"
            summary = _build_scorecard_detail_summary(context["scorecard"], workspace_url=workspace_url)
            text_body, html_body = render_scorecard_detail_email(summary)
            subject = f"Your Jaspen scorecard: {summary['project_name']}"
        else:
            summary = _build_summary(context["session"], context["scorecard"], context["peers"])
            text_body, html_body = render_email(summary)
            subject = f"Why this order: {summary['decision_name']}"
        attachments = _build_attachments(context, output_types)

        provider = get_transactional_email_provider()
        result = provider.send(
            subject=subject,
            recipient=user.email,
            text_body=text_body,
            html_body=html_body,
            attachments=attachments,
        )
        delivery.status = "sent"
        delivery.sent_at = datetime.utcnow()
        delivery.provider = result.provider
        delivery.provider_response = result.response_category
        record_telemetry(
            delivery,
            "email_assets_sent",
            provider_response=result.response_category,
        )
        db.session.commit()
    except Exception as exc:
        db.session.rollback()
        delivery = DecisionAssetEmail.query.filter_by(id=delivery_id).first()
        if not delivery:
            return
        category = exc.category if isinstance(exc, DeliveryError) else (
            "email_provider_not_configured" if str(exc) == "transactional_email_not_configured" else "provider_failure"
        )
        delivery.status = "failed"
        delivery.error_category = category
        record_telemetry(delivery, "email_assets_failed", success=False, error_category=category)
        db.session.commit()
        current_app.logger.warning(
            "Decision asset email failed",
            extra={"delivery_id": delivery.id, "failure_category": category},
        )


def start_delivery(delivery_id):
    app = current_app._get_current_object()

    def run():
        with app.app_context():
            process_delivery(delivery_id)

    threading.Thread(target=run, daemon=True, name=f"decision-email-{delivery_id[:8]}").start()
