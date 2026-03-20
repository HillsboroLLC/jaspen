import csv
import io
import re
from datetime import datetime

from flask import Blueprint, jsonify, request, send_file
from flask_jwt_extended import get_jwt_identity, jwt_required

from app.billing_config import PLAN_RANK, to_public_plan
from app.models import Organization, User
from app.orgs import active_membership_for_user, resolve_active_org_for_user

from .ai_agent import _normalize_analysis_history
from .reports import _markdown_to_pdf_bytes, _safe_text
from .sessions import load_user_sessions
from .strategy import _load_scenarios

export_bp = Blueprint("export", __name__)

PPTX_MIMETYPE = "application/vnd.openxmlformats-officedocument.presentationml.presentation"
CSV_MIMETYPE = "text/csv; charset=utf-8"
PDF_MIMETYPE = "application/pdf"
MARKDOWN_MIMETYPE = "text/markdown; charset=utf-8"


def _iso_now():
    return datetime.utcnow().isoformat()


def _resolve_thread_session(sessions, thread_id):
    tid = str(thread_id or "").strip()
    if not tid or not isinstance(sessions, dict):
        return None
    if tid in sessions and isinstance(sessions.get(tid), dict):
        return sessions.get(tid)
    for candidate in sessions.values():
        if not isinstance(candidate, dict):
            continue
        if str(candidate.get("session_id") or "").strip() == tid:
            return candidate
    return None


def _resolve_export_context(user, session):
    plan_key = to_public_plan(getattr(user, "subscription_plan", None))
    org = None
    membership = None
    session_org_id = str((session or {}).get("organization_id") or "").strip()

    if session_org_id:
        org = Organization.query.filter_by(id=session_org_id).first()
        if org is not None:
            membership = active_membership_for_user(session_org_id, user.id)
            if membership:
                plan_key = to_public_plan(org.plan_key)
            else:
                org = None
    elif isinstance(user, User):
        active_org, active_membership = resolve_active_org_for_user(user)
        if active_org and active_membership:
            org = active_org
            membership = active_membership

    return plan_key, org, membership


def _require_export_plan(plan_key, export_type):
    required_plan = "team" if export_type in {"pptx", "csv"} else "essential"
    if PLAN_RANK.get(plan_key, 0) >= PLAN_RANK.get(required_plan, 0):
        return None

    label = {
        "pdf": "PDF export",
        "pptx": "PowerPoint export",
        "csv": "WBS CSV export",
    }.get(export_type, "Export")
    return (
        jsonify(
            {
                "error": f"{label} is not available on your current plan.",
                "code": "export_plan_required",
                "plan_key": plan_key,
                "required_plan": required_plan,
                "export_type": export_type,
            }
        ),
        403,
    )


def _format_label(key):
    token = str(key or "").replace("_", " ").strip()
    return token.title() if token else "Item"


def _scorecard_record_for_export(session, thread_id, scorecard_id=None):
    analyses = _normalize_analysis_history(session, thread_id)
    scorecard_id = str(scorecard_id or "").strip()
    selected = None

    if scorecard_id:
        for item in analyses:
            if not isinstance(item, dict):
                continue
            result = item.get("result") if isinstance(item.get("result"), dict) else {}
            candidates = {
                str(item.get("analysis_id") or "").strip(),
                str(item.get("id") or "").strip(),
                str(result.get("analysis_id") or "").strip(),
                str(result.get("id") or "").strip(),
                str(result.get("scenario_id") or "").strip(),
            }
            candidates.discard("")
            if scorecard_id in candidates:
                selected = item
                break
        if selected is None:
            return None, (
                jsonify({"error": "Scorecard not found in this thread.", "code": "scorecard_not_found"}),
                404,
            )

    if selected is None:
        result_blob = session.get("result") if isinstance(session.get("result"), dict) else {}
        if result_blob:
            selected = {
                "analysis_id": str(
                    result_blob.get("analysis_id")
                    or result_blob.get("id")
                    or session.get("session_id")
                    or thread_id
                ),
                "created_at": result_blob.get("timestamp") or session.get("timestamp") or session.get("created"),
                "result": result_blob,
            }
        elif analyses:
            selected = analyses[0]

    if not isinstance(selected, dict):
        return None, (jsonify({"error": "No scorecard is available for this thread."}), 404)

    result = selected.get("result") if isinstance(selected.get("result"), dict) else {}
    component_scores = result.get("component_scores") if isinstance(result.get("component_scores"), dict) else {}
    if not component_scores and isinstance(result.get("scores"), dict):
        component_scores = result.get("scores")
    component_scores = component_scores if isinstance(component_scores, dict) else {}

    financial_impact = result.get("financial_impact") if isinstance(result.get("financial_impact"), dict) else {}
    risks = result.get("top_risks")
    if not isinstance(risks, list):
        risks = result.get("risks")
    risks = risks if isinstance(risks, list) else []
    recommendations = result.get("recommendations") if isinstance(result.get("recommendations"), list) else []

    payload = {
        "analysis_id": str(selected.get("analysis_id") or thread_id),
        "project_name": _safe_text(
            result.get("project_name") or result.get("name") or session.get("name") or f"Thread {thread_id}",
            255,
        ),
        "jaspen_score": result.get("jaspen_score") or result.get("overall_score") or result.get("score"),
        "score_category": _safe_text(result.get("score_category"), 64) or None,
        "component_scores": component_scores,
        "financial_impact": financial_impact,
        "risks": risks,
        "recommendations": recommendations,
        "updated_at": selected.get("created_at") or result.get("timestamp") or session.get("timestamp"),
    }
    return payload, None


def _display_value(value):
    if value is None or value == "":
        return "N/A"
    if isinstance(value, float):
        return f"{value:,.2f}"
    return str(value)


def _list_text_items(items, *, fallback):
    if not isinstance(items, list) or not items:
        return [fallback]
    output = []
    for idx, item in enumerate(items, start=1):
        if isinstance(item, dict):
            text = (
                item.get("title")
                or item.get("recommendation")
                or item.get("risk")
                or item.get("description")
            )
        else:
            text = item
        text = str(text or "").strip()
        if text:
            output.append(f"{idx}. {text}")
    return output or [fallback]


def _scorecard_markdown(scorecard, *, org=None):
    project_name = scorecard.get("project_name") or "Untitled Idea"
    component_scores = scorecard.get("component_scores") or {}
    financial_impact = scorecard.get("financial_impact") or {}
    risks = _list_text_items(scorecard.get("risks"), fallback="No key risks recorded.")
    recommendations = _list_text_items(scorecard.get("recommendations"), fallback="No recommendations recorded.")
    generated_at = scorecard.get("updated_at") or _iso_now()

    lines = [
        f"# {project_name}",
        "",
        f"- **Generated**: {generated_at}",
        f"- **Workspace**: {(org.name if org else 'Personal Workspace')}",
        f"- **Jaspen Score**: {_display_value(scorecard.get('jaspen_score'))}",
        f"- **Score Category**: {_display_value(scorecard.get('score_category'))}",
        "",
        "## Component Scores",
    ]
    if component_scores:
        for key, value in component_scores.items():
            lines.append(f"- **{_format_label(key)}**: {_display_value(value)}")
    else:
        lines.append("- No component scores recorded.")

    lines.extend(["", "## Financial Impact"])
    if financial_impact:
        for key, value in financial_impact.items():
            lines.append(f"- **{_format_label(key)}**: {_display_value(value)}")
    else:
        lines.append("- No financial impact data recorded.")

    lines.extend(["", "## Key Risks"])
    lines.extend(f"- {item}" for item in risks)
    lines.extend(["", "## Recommendations + Next Steps"])
    lines.extend(f"- {item}" for item in recommendations)
    return "\n".join(lines)


def _safe_filename_base(value):
    slug = re.sub(r"[^a-z0-9._-]+", "-", str(value or "").strip().lower()).strip("-")
    return slug[:96] or "jaspen-export"


def _display_chat_role(role):
    normalized = str(role or "").strip().lower()
    if normalized in {"assistant", "ai", "bot"}:
        return "Jaspen"
    return "You"


def _transcript_markdown(session, *, org=None):
    if not isinstance(session, dict):
        return ""
    thread_name = _safe_text(session.get("name") or "Conversation Transcript", 255)
    workspace_name = org.name if org else "Personal Workspace"
    generated_at = session.get("timestamp") or session.get("created") or _iso_now()
    chat_history = session.get("chat_history") if isinstance(session.get("chat_history"), list) else []

    lines = [
        f"# {thread_name}",
        "",
        f"- **Generated**: {generated_at}",
        f"- **Workspace**: {workspace_name}",
        f"- **Thread ID**: {str(session.get('session_id') or '').strip() or 'N/A'}",
        "",
        "## Conversation",
    ]

    if not chat_history:
        lines.append("")
        lines.append("_No conversation messages available._")
        return "\n".join(lines)

    for message in chat_history:
        if not isinstance(message, dict):
            continue
        content = _safe_text(message.get("content") or message.get("text") or "", 20000)
        attachments = message.get("attachments") if isinstance(message.get("attachments"), list) else []
        if not str(content).strip() and not attachments:
            continue
        role_label = _display_chat_role(message.get("role"))
        timestamp = str(message.get("timestamp") or "").strip()
        lines.extend(["", f"### {role_label}"])
        if timestamp:
            lines.append(f"_Timestamp: {timestamp}_")
            lines.append("")
        if str(content).strip():
            lines.append(str(content).strip())
        if attachments:
            lines.append("")
            lines.append("Attached files:")
            for attachment in attachments:
                if not isinstance(attachment, dict):
                    continue
                name = _safe_text(attachment.get("name") or "attachment", 255)
                attachment_type = _safe_text(attachment.get("type") or attachment.get("kind") or "file", 120)
                size = int(attachment.get("size") or 0)
                size_kb = max(1, round(size / 1024)) if size > 0 else None
                suffix = f" ({attachment_type}{f', {size_kb} KB' if size_kb else ''})"
                lines.append(f"- {name}{suffix}")

    return "\n".join(lines).strip()


def _send_bytes(payload, *, filename, mimetype):
    buffer = io.BytesIO(payload)
    buffer.seek(0)
    return send_file(buffer, mimetype=mimetype, as_attachment=True, download_name=filename)


def _pptx_bytes(scorecard, *, org=None):
    try:
        from pptx import Presentation
        from pptx.dml.color import RGBColor
        from pptx.enum.text import PP_ALIGN
        from pptx.util import Inches, Pt
    except Exception as exc:
        raise RuntimeError("python-pptx is required for PowerPoint export.") from exc

    prs = Presentation()
    navy = RGBColor(0x16, 0x1F, 0x3B)
    magenta = RGBColor(0xA0, 0x03, 0x6C)
    gray = RGBColor(0x60, 0x67, 0x74)

    def add_title(slide, title, subtitle=None):
        title_box = slide.shapes.add_textbox(Inches(0.6), Inches(0.4), Inches(8.8), Inches(0.8))
        title_frame = title_box.text_frame
        title_frame.clear()
        title_para = title_frame.paragraphs[0]
        title_para.text = title
        title_para.font.size = Pt(28)
        title_para.font.bold = True
        title_para.font.color.rgb = navy

        if subtitle:
            subtitle_box = slide.shapes.add_textbox(Inches(0.6), Inches(1.1), Inches(8.8), Inches(0.5))
            subtitle_frame = subtitle_box.text_frame
            subtitle_frame.clear()
            subtitle_para = subtitle_frame.paragraphs[0]
            subtitle_para.text = subtitle
            subtitle_para.font.size = Pt(12)
            subtitle_para.font.color.rgb = gray

    def add_bullets(slide, items, *, left=0.9, top=1.7, width=8.2, height=4.8):
        box = slide.shapes.add_textbox(Inches(left), Inches(top), Inches(width), Inches(height))
        frame = box.text_frame
        frame.clear()
        for idx, item in enumerate(items):
            para = frame.paragraphs[0] if idx == 0 else frame.add_paragraph()
            para.text = item
            para.level = 0
            para.font.size = Pt(20 if idx == 0 else 18)
            para.font.color.rgb = navy

    project_name = scorecard.get("project_name") or "Untitled Idea"
    generated_at = scorecard.get("updated_at") or _iso_now()
    component_scores = scorecard.get("component_scores") or {}
    score_pairs = list(component_scores.items())[:4]
    while len(score_pairs) < 4:
        score_pairs.append((f"Metric {len(score_pairs) + 1}", "N/A"))

    slide = prs.slides.add_slide(prs.slide_layouts[6])
    add_title(
        slide,
        project_name,
        f"{(org.name if org else 'Personal Workspace')} • Generated {generated_at}",
    )
    score_box = slide.shapes.add_textbox(Inches(0.8), Inches(2.0), Inches(8.0), Inches(2.2))
    score_frame = score_box.text_frame
    score_frame.clear()
    para = score_frame.paragraphs[0]
    para.text = "Jaspen Score"
    para.font.size = Pt(20)
    para.font.color.rgb = gray
    para.alignment = PP_ALIGN.CENTER
    value_para = score_frame.add_paragraph()
    value_para.text = _display_value(scorecard.get("jaspen_score"))
    value_para.font.size = Pt(40)
    value_para.font.bold = True
    value_para.font.color.rgb = magenta
    value_para.alignment = PP_ALIGN.CENTER

    slide = prs.slides.add_slide(prs.slide_layouts[6])
    add_title(slide, "Component Scores", "Four-quadrant score overview")
    positions = [
        (0.8, 1.8),
        (5.0, 1.8),
        (0.8, 4.0),
        (5.0, 4.0),
    ]
    for idx, (key, value) in enumerate(score_pairs[:4]):
        left, top = positions[idx]
        shape = slide.shapes.add_shape(1, Inches(left), Inches(top), Inches(3.4), Inches(1.6))
        fill = shape.fill
        fill.solid()
        fill.fore_color.rgb = RGBColor(0xEF, 0xF9, 0xFC)
        shape.line.color.rgb = navy
        frame = shape.text_frame
        frame.clear()
        p1 = frame.paragraphs[0]
        p1.text = _format_label(key)
        p1.font.size = Pt(16)
        p1.font.bold = True
        p1.font.color.rgb = navy
        p2 = frame.add_paragraph()
        p2.text = _display_value(value)
        p2.font.size = Pt(24)
        p2.font.bold = True
        p2.font.color.rgb = magenta

    slide = prs.slides.add_slide(prs.slide_layouts[6])
    add_title(slide, "Financial Impact")
    fin_items = [
        f"{_format_label(key)}: {_display_value(value)}"
        for key, value in (scorecard.get("financial_impact") or {}).items()
    ] or ["No financial impact data recorded."]
    add_bullets(slide, fin_items)

    slide = prs.slides.add_slide(prs.slide_layouts[6])
    add_title(slide, "Key Risks")
    add_bullets(slide, _list_text_items(scorecard.get("risks"), fallback="No key risks recorded."))

    slide = prs.slides.add_slide(prs.slide_layouts[6])
    add_title(slide, "Recommendations + Next Steps")
    add_bullets(slide, _list_text_items(scorecard.get("recommendations"), fallback="No recommendations recorded."))

    buffer = io.BytesIO()
    prs.save(buffer)
    buffer.seek(0)
    return buffer.read()


def _wbs_csv_bytes(project_wbs):
    tasks = project_wbs.get("tasks") if isinstance(project_wbs, dict) else []
    if not isinstance(tasks, list) or not tasks:
        return None

    output = io.StringIO()
    writer = csv.DictWriter(
        output,
        fieldnames=[
            "id",
            "title",
            "status",
            "owner",
            "suggested_role",
            "phase",
            "priority",
            "due_date",
            "timeline_days",
            "estimated_days",
            "depends_on",
            "jira_issue_key",
            "description",
            "rationale",
            "risk_area",
            "order",
        ],
    )
    writer.writeheader()
    for task in tasks:
        if not isinstance(task, dict):
            continue
        refs = task.get("external_refs") if isinstance(task.get("external_refs"), dict) else {}
        writer.writerow(
            {
                "id": task.get("id"),
                "title": task.get("title"),
                "status": task.get("status"),
                "owner": task.get("owner"),
                "suggested_role": task.get("suggested_role"),
                "phase": task.get("phase"),
                "priority": task.get("priority"),
                "due_date": task.get("due_date"),
                "timeline_days": task.get("timeline_days"),
                "estimated_days": task.get("estimated_days"),
                "depends_on": ",".join(task.get("depends_on") or []),
                "jira_issue_key": refs.get("jira_issue_key"),
                "description": task.get("description"),
                "rationale": task.get("rationale"),
                "risk_area": task.get("risk_area"),
                "order": task.get("order"),
            }
        )
    return output.getvalue().encode("utf-8")


@export_bp.route("/threads/<thread_id>/scorecard/pdf", methods=["GET"])
@jwt_required()
def export_scorecard_pdf(thread_id):
    user = User.query.filter_by(id=str(get_jwt_identity())).first()
    if not user:
        return jsonify({"error": "User not found"}), 404

    sessions = load_user_sessions(user.id) or {}
    session = _resolve_thread_session(sessions, thread_id)
    if not isinstance(session, dict):
        return jsonify({"error": "Thread not found"}), 404

    plan_key, org, _membership = _resolve_export_context(user, session)
    access_error = _require_export_plan(plan_key, "pdf")
    if access_error:
        return access_error

    scorecard, error_response = _scorecard_record_for_export(
        session,
        thread_id,
        scorecard_id=request.args.get("scorecard_id"),
    )
    if error_response:
        return error_response

    markdown = _scorecard_markdown(scorecard, org=org)
    payload = _markdown_to_pdf_bytes(scorecard.get("project_name") or "Jaspen Scorecard", markdown)
    filename = f"{_safe_filename_base(scorecard.get('project_name'))}-scorecard.pdf"
    return _send_bytes(payload, filename=filename, mimetype=PDF_MIMETYPE)


@export_bp.route("/threads/<thread_id>/scorecard/pptx", methods=["GET"])
@jwt_required()
def export_scorecard_pptx(thread_id):
    user = User.query.filter_by(id=str(get_jwt_identity())).first()
    if not user:
        return jsonify({"error": "User not found"}), 404

    sessions = load_user_sessions(user.id) or {}
    session = _resolve_thread_session(sessions, thread_id)
    if not isinstance(session, dict):
        return jsonify({"error": "Thread not found"}), 404

    plan_key, org, _membership = _resolve_export_context(user, session)
    access_error = _require_export_plan(plan_key, "pptx")
    if access_error:
        return access_error

    scorecard, error_response = _scorecard_record_for_export(
        session,
        thread_id,
        scorecard_id=request.args.get("scorecard_id"),
    )
    if error_response:
        return error_response

    try:
        payload = _pptx_bytes(scorecard, org=org)
    except RuntimeError as exc:
        return jsonify({"error": str(exc), "code": "pptx_dependency_missing"}), 503

    filename = f"{_safe_filename_base(scorecard.get('project_name'))}-scorecard.pptx"
    return _send_bytes(payload, filename=filename, mimetype=PPTX_MIMETYPE)


@export_bp.route("/threads/<thread_id>/wbs/csv", methods=["GET"])
@jwt_required()
def export_wbs_csv(thread_id):
    user = User.query.filter_by(id=str(get_jwt_identity())).first()
    if not user:
        return jsonify({"error": "User not found"}), 404

    sessions = load_user_sessions(user.id) or {}
    session = _resolve_thread_session(sessions, thread_id)
    if not isinstance(session, dict):
        return jsonify({"error": "Thread not found"}), 404

    plan_key, _org, _membership = _resolve_export_context(user, session)
    access_error = _require_export_plan(plan_key, "csv")
    if access_error:
        return access_error

    scenario_data = _load_scenarios(user.id) or {}
    thread_data = scenario_data.get(thread_id) if isinstance(scenario_data, dict) else {}
    project_wbs = thread_data.get("project_wbs") if isinstance(thread_data, dict) else None
    if not isinstance(project_wbs, dict):
        return jsonify({"error": "No execution plan is available for this thread."}), 404

    payload = _wbs_csv_bytes(project_wbs)
    if payload is None:
        return jsonify({"error": "No WBS tasks are available to export."}), 404

    project_name = session.get("name") or thread_id
    filename = f"{_safe_filename_base(project_name)}-wbs.csv"
    return _send_bytes(payload, filename=filename, mimetype=CSV_MIMETYPE)


@export_bp.route("/threads/<thread_id>/conversation/markdown", methods=["GET"])
@jwt_required()
def export_conversation_markdown(thread_id):
    user = User.query.filter_by(id=str(get_jwt_identity())).first()
    if not user:
        return jsonify({"error": "User not found"}), 404

    sessions = load_user_sessions(user.id) or {}
    session = _resolve_thread_session(sessions, thread_id)
    if not isinstance(session, dict):
        return jsonify({"error": "Thread not found"}), 404

    _plan_key, org, _membership = _resolve_export_context(user, session)
    markdown = _transcript_markdown(session, org=org)
    project_name = session.get("name") or thread_id
    filename = f"{_safe_filename_base(project_name)}-conversation.md"
    return _send_bytes(markdown.encode("utf-8"), filename=filename, mimetype=MARKDOWN_MIMETYPE)


@export_bp.route("/threads/<thread_id>/conversation/pdf", methods=["GET"])
@jwt_required()
def export_conversation_pdf(thread_id):
    user = User.query.filter_by(id=str(get_jwt_identity())).first()
    if not user:
        return jsonify({"error": "User not found"}), 404

    sessions = load_user_sessions(user.id) or {}
    session = _resolve_thread_session(sessions, thread_id)
    if not isinstance(session, dict):
        return jsonify({"error": "Thread not found"}), 404

    plan_key, org, _membership = _resolve_export_context(user, session)
    access_error = _require_export_plan(plan_key, "pdf")
    if access_error:
        return access_error

    markdown = _transcript_markdown(session, org=org)
    project_name = session.get("name") or thread_id
    payload = _markdown_to_pdf_bytes(project_name, markdown)
    filename = f"{_safe_filename_base(project_name)}-conversation.pdf"
    return _send_bytes(payload, filename=filename, mimetype=PDF_MIMETYPE)
