import csv
import io
import re
from datetime import datetime, timezone

from flask import Blueprint, jsonify, request, send_file
from flask_jwt_extended import get_jwt_identity, jwt_required

from app.billing_config import PLAN_RANK, to_public_plan
from app.models import Organization, User
from app.orgs import active_membership_for_user, resolve_active_org_for_user

from .ai_agent import _normalize_analysis_history
from .reports import _markdown_to_pdf_bytes, _safe_text
from .sessions import load_user_sessions
from .strategy import _load_scenarios, _resolve_thread_wbs, _scorecard_snapshot_state

export_bp = Blueprint("export", __name__)

PPTX_MIMETYPE = "application/vnd.openxmlformats-officedocument.presentationml.presentation"
CSV_MIMETYPE = "text/csv; charset=utf-8"
PDF_MIMETYPE = "application/pdf"
XLSX_MIMETYPE = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
DOCX_MIMETYPE = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
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
    if export_type in {"csv", "wbs_xlsx"}:
        return None

    required_plan = "team" if export_type == "pptx" else "essential"
    if PLAN_RANK.get(plan_key, 0) >= PLAN_RANK.get(required_plan, 0):
        return None

    label = {
        "pdf": "PDF export",
        "pptx": "PowerPoint export",
        "csv": "WBS CSV export",
        "wbs_xlsx": "Execution plan Excel export",
        "xlsx": "Excel export",
        "docx": "Word export",
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


def _scorecard_record_for_export(session, thread_id, scorecard_id=None, user_id=None):
    analyses = _normalize_analysis_history(session, thread_id)
    scorecard_id = str(scorecard_id or "").strip()
    selected = None

    if user_id is not None:
        from app.scenarios_store import load_scenarios_data
        from app.scorecards import collect_peer_scorecards
        thread_data = (load_scenarios_data(user_id) or {}).get(thread_id) or {}
        peers = collect_peer_scorecards(
            user_id,
            thread_id,
            legacy_session=session,
            legacy_thread_data=thread_data,
        )
        chosen = None
        if scorecard_id:
            chosen = next((
                item for item in peers
                if str(item.get('id') or item.get('analysis_id') or '') == scorecard_id
            ), None)
            if chosen is None:
                return None, (
                    jsonify({"error": "Scorecard not found in this thread.", "code": "scorecard_not_found"}),
                    404,
                )
        elif peers:
            chosen = peers[0]
        if isinstance(chosen, dict):
            selected = {
                'analysis_id': str(chosen.get('id') or chosen.get('analysis_id') or thread_id),
                'created_at': chosen.get('createdAt') or chosen.get('timestamp'),
                'result': chosen,
            }

    if scorecard_id and selected is None:
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
        "scenario_variants": _scorecard_variants_for_export(
            session,
            thread_id,
            selected_scorecard_id=scorecard_id,
            user_id=user_id,
        ),
        # Full content for rich exports (Excel/Word): the per-criterion grid, the
        # written summary, and the rubric (for ordering/labels).
        "dimensions": result.get("dimensions") if isinstance(result.get("dimensions"), dict) else {},
        "executive_summary": _safe_text(result.get("executive_summary"), 4000) or None,
        "rubric": result.get("rubric") if isinstance(result.get("rubric"), dict) else None,
        "top_risks": risks,
        # #4 custom colors: carry the user's brand accent into exports.
        "accent_color": (
            str((result.get("display_overrides") or {}).get("accent_color") or result.get("_accent_color") or "").strip()
            or None
        ),
    }
    return payload, None


def _accent_hex(scorecard, default="#A0036C"):
    """Validated brand accent for exports, falling back to Jaspen magenta."""
    raw = str((scorecard or {}).get("accent_color") or "").strip()
    if re.fullmatch(r"#[0-9a-fA-F]{6}", raw):
        return raw.upper()
    return default


def _display_value(value):
    if value is None or value == "":
        return "N/A"
    if isinstance(value, float):
        return f"{value:,.2f}"
    return str(value)


def _safe_float(value):
    try:
        numeric = float(value)
        if numeric == numeric:
            return numeric
    except Exception:
        return None
    return None


def _scorecard_variants_for_export(session, thread_id, selected_scorecard_id=None, user_id=None):
    if not isinstance(session, dict):
        return []

    if user_id is not None:
        from app.scenarios_store import load_scenarios_data
        from app.scorecards import collect_peer_scorecards
        snapshots = collect_peer_scorecards(
            user_id,
            thread_id,
            legacy_session=session,
            legacy_thread_data=(load_scenarios_data(user_id) or {}).get(thread_id) or {},
        )
        snapshot_state = {'selected_id': selected_scorecard_id}
    else:
        result_blob = session.get("result") if isinstance(session.get("result"), dict) else {}
        if not result_blob:
            return []
        try:
            snapshot_state = _scorecard_snapshot_state(result_blob, thread_id)
        except Exception:
            return []
        snapshots = snapshot_state.get("snapshots") if isinstance(snapshot_state.get("snapshots"), list) else []
    if len(snapshots) <= 1:
        return []

    selected_id = str(selected_scorecard_id or snapshot_state.get("selected_id") or "").strip()
    variants = []
    for snap in snapshots:
        if not isinstance(snap, dict):
            continue
        snap_id = str(snap.get("id") or snap.get("analysis_id") or "").strip()
        if not snap_id:
            continue
        score = _safe_float(snap.get("jaspen_score") or snap.get("overall_score") or snap.get("score"))
        variants.append(
            {
                "id": snap_id,
                "label": _safe_text(snap.get("project_name") or snap.get("name") or snap.get("label") or "Project", 120),
                "is_baseline": False,
                "is_selected": bool(selected_id and snap_id == selected_id),
                "jaspen_score": score,
                "score_category": _safe_text(snap.get("score_category"), 64) or None,
            }
        )

    return variants


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


def _scorecard_pdf_bytes(scorecard, *, org=None):
    project_name = scorecard.get("project_name") or "Untitled Idea"
    markdown_fallback = _scorecard_markdown(scorecard, org=org)

    try:
        from reportlab.lib import colors
        from reportlab.lib.pagesizes import letter
        from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
        from reportlab.lib.units import inch
        from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle
    except Exception:
        return _markdown_to_pdf_bytes(project_name, markdown_fallback)

    try:
        navy = colors.HexColor("#161F3B")
        accent_hex = _accent_hex(scorecard)
        magenta = colors.HexColor(accent_hex)
        ice = colors.HexColor("#EFF9FC")
        ink = colors.HexColor("#1F2937")
        slate = colors.HexColor("#475569")
        border = colors.HexColor("#D7DEE8")

        component_scores = scorecard.get("component_scores") if isinstance(scorecard.get("component_scores"), dict) else {}
        financial_impact = scorecard.get("financial_impact") if isinstance(scorecard.get("financial_impact"), dict) else {}
        risks = _list_text_items(scorecard.get("risks"), fallback="No key risks recorded.")
        recommendations = _list_text_items(scorecard.get("recommendations"), fallback="No recommendations recorded.")
        generated_at = str(scorecard.get("updated_at") or _iso_now())
        workspace_name = org.name if org else "Personal Workspace"
        score_text = _display_value(scorecard.get("jaspen_score"))
        category_text = _display_value(scorecard.get("score_category"))

        styles = getSampleStyleSheet()
        title_style = ParagraphStyle(
            "ScoreTitle",
            parent=styles["Heading1"],
            fontName="Helvetica-Bold",
            fontSize=20,
            leading=24,
            textColor=colors.white,
            spaceAfter=0,
        )
        subtitle_style = ParagraphStyle(
            "ScoreSubtitle",
            parent=styles["Normal"],
            fontName="Helvetica",
            fontSize=9,
            leading=12,
            textColor=colors.white,
            spaceAfter=0,
        )
        section_style = ParagraphStyle(
            "SectionTitle",
            parent=styles["Heading3"],
            fontName="Helvetica-Bold",
            fontSize=12,
            leading=14,
            textColor=navy,
            spaceBefore=2,
            spaceAfter=6,
        )
        body_style = ParagraphStyle(
            "Body",
            parent=styles["Normal"],
            fontName="Helvetica",
            fontSize=10,
            leading=14,
            textColor=ink,
        )
        bullet_style = ParagraphStyle(
            "Bullet",
            parent=body_style,
            leftIndent=10,
            firstLineIndent=-8,
            spaceBefore=1,
            spaceAfter=1,
        )

        buffer = io.BytesIO()
        doc = SimpleDocTemplate(
            buffer,
            pagesize=letter,
            leftMargin=0.55 * inch,
            rightMargin=0.55 * inch,
            topMargin=0.5 * inch,
            bottomMargin=0.5 * inch,
            title=_safe_text(project_name, 200),
        )

        story = []

        header = Table(
            [[
                Paragraph(_safe_text(project_name, 180), title_style),
                Paragraph(
                    f"<b>Jaspen Score</b><br/><font color='{accent_hex}' size='18'><b>{score_text}</b></font>",
                    ParagraphStyle(
                        "ScoreChip",
                        parent=styles["Normal"],
                        fontName="Helvetica",
                        fontSize=9,
                        leading=13,
                        alignment=2,
                        textColor=ink,
                    ),
                ),
            ]],
            colWidths=[4.9 * inch, 2.0 * inch],
            hAlign="LEFT",
        )
        header.setStyle(
            TableStyle(
                [
                    ("BACKGROUND", (0, 0), (0, 0), navy),
                    ("BACKGROUND", (1, 0), (1, 0), ice),
                    ("BOX", (0, 0), (1, 0), 0.75, border),
                    ("VALIGN", (0, 0), (1, 0), "MIDDLE"),
                    ("LEFTPADDING", (0, 0), (0, 0), 14),
                    ("RIGHTPADDING", (0, 0), (0, 0), 10),
                    ("TOPPADDING", (0, 0), (1, 0), 12),
                    ("BOTTOMPADDING", (0, 0), (1, 0), 12),
                    ("LEFTPADDING", (1, 0), (1, 0), 10),
                    ("RIGHTPADDING", (1, 0), (1, 0), 12),
                ]
            )
        )
        story.append(header)

        subtitle = Table(
            [[Paragraph(
                f"Generated: {generated_at} &nbsp;&nbsp;•&nbsp;&nbsp; Workspace: {_safe_text(workspace_name, 120)} &nbsp;&nbsp;•&nbsp;&nbsp; Category: {category_text}",
                subtitle_style,
            )]],
            colWidths=[6.9 * inch],
            hAlign="LEFT",
        )
        subtitle.setStyle(
            TableStyle(
                [
                    ("BACKGROUND", (0, 0), (0, 0), navy),
                    ("LEFTPADDING", (0, 0), (0, 0), 14),
                    ("RIGHTPADDING", (0, 0), (0, 0), 12),
                    ("TOPPADDING", (0, 0), (0, 0), 6),
                    ("BOTTOMPADDING", (0, 0), (0, 0), 8),
                ]
            )
        )
        story.append(subtitle)
        story.append(Spacer(1, 12))

        story.append(Paragraph("Component Scores", section_style))
        component_rows = [["Component", "Score"]]
        for key, value in component_scores.items():
            component_rows.append([_format_label(key), _display_value(value)])
        if len(component_rows) == 1:
            component_rows.append(["No component scores recorded.", "N/A"])

        component_table = Table(component_rows, colWidths=[5.4 * inch, 1.5 * inch], hAlign="LEFT")
        component_style = [
            ("BACKGROUND", (0, 0), (1, 0), ice),
            ("TEXTCOLOR", (0, 0), (1, 0), navy),
            ("FONTNAME", (0, 0), (1, 0), "Helvetica-Bold"),
            ("FONTSIZE", (0, 0), (1, 0), 10),
            ("ALIGN", (1, 1), (1, -1), "RIGHT"),
            ("GRID", (0, 0), (1, -1), 0.5, border),
            ("FONTNAME", (0, 1), (1, -1), "Helvetica"),
            ("FONTSIZE", (0, 1), (1, -1), 9),
            ("TEXTCOLOR", (0, 1), (1, -1), ink),
            ("ROWBACKGROUNDS", (0, 1), (1, -1), [colors.white, colors.HexColor("#F8FAFC")]),
            ("LEFTPADDING", (0, 0), (1, -1), 8),
            ("RIGHTPADDING", (0, 0), (1, -1), 8),
            ("TOPPADDING", (0, 0), (1, -1), 6),
            ("BOTTOMPADDING", (0, 0), (1, -1), 6),
        ]
        component_table.setStyle(TableStyle(component_style))
        story.append(component_table)
        story.append(Spacer(1, 12))

        variants = scorecard.get("scenario_variants") if isinstance(scorecard.get("scenario_variants"), list) else []
        if len(variants) > 1:
            story.append(Paragraph("Project Comparison", section_style))
            variant_rows = [["Project", "Score", "Category"]]
            for item in variants[:10]:
                if not isinstance(item, dict):
                    continue
                label = str(item.get("label") or "Project").strip() or "Project"
                if item.get("is_selected"):
                    label = f"{label} (Selected)"
                variant_rows.append(
                    [
                        _safe_text(label, 80),
                        _display_value(item.get("jaspen_score")),
                        _display_value(item.get("score_category")),
                    ]
                )
            if len(variant_rows) == 1:
                variant_rows.append(["No peer projects recorded.", "N/A", "N/A"])
            variant_table = Table(
                variant_rows,
                colWidths=[3.6 * inch, 1.2 * inch, 1.8 * inch],
                hAlign="LEFT",
            )
            variant_table.setStyle(
                TableStyle(
                    [
                        ("BACKGROUND", (0, 0), (2, 0), ice),
                        ("TEXTCOLOR", (0, 0), (2, 0), navy),
                        ("FONTNAME", (0, 0), (2, 0), "Helvetica-Bold"),
                        ("FONTSIZE", (0, 0), (2, 0), 9),
                        ("GRID", (0, 0), (2, -1), 0.5, border),
                        ("FONTNAME", (0, 1), (2, -1), "Helvetica"),
                        ("FONTSIZE", (0, 1), (2, -1), 8.5),
                        ("ALIGN", (1, 1), (1, -1), "RIGHT"),
                        ("ROWBACKGROUNDS", (0, 1), (2, -1), [colors.white, colors.HexColor("#F8FAFC")]),
                        ("LEFTPADDING", (0, 0), (2, -1), 6),
                        ("RIGHTPADDING", (0, 0), (2, -1), 6),
                        ("TOPPADDING", (0, 0), (2, -1), 5),
                        ("BOTTOMPADDING", (0, 0), (2, -1), 5),
                    ]
                )
            )
            story.append(variant_table)
            story.append(Spacer(1, 12))

        story.append(Paragraph("Financial Impact", section_style))
        fin_rows = [["Metric", "Value"]]
        for key, value in list(financial_impact.items())[:12]:
            fin_rows.append([_format_label(key), _display_value(value)])
        if len(fin_rows) == 1:
            fin_rows.append(["No financial impact data recorded.", "N/A"])
        fin_table = Table(fin_rows, colWidths=[4.7 * inch, 2.2 * inch], hAlign="LEFT")
        fin_table.setStyle(TableStyle(component_style))
        story.append(fin_table)
        story.append(Spacer(1, 12))

        story.append(Paragraph("Top Risks", section_style))
        for item in risks[:8]:
            story.append(Paragraph(f"• {_safe_text(item, 500)}", bullet_style))
        story.append(Spacer(1, 10))

        story.append(Paragraph("Recommendations + Next Steps", section_style))
        for item in recommendations[:8]:
            story.append(Paragraph(f"• {_safe_text(item, 500)}", bullet_style))

        footer = ParagraphStyle(
            "Footer",
            parent=styles["Normal"],
            fontName="Helvetica-Oblique",
            fontSize=8,
            textColor=slate,
            spaceBefore=14,
        )
        story.append(Spacer(1, 12))
        story.append(Paragraph("Generated by Jaspen strategic export.", footer))

        doc.build(story)
        buffer.seek(0)
        return buffer.read()
    except Exception:
        return _markdown_to_pdf_bytes(project_name, markdown_fallback)


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
    variants = scorecard.get("scenario_variants") if isinstance(scorecard.get("scenario_variants"), list) else []
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

    if len(variants) > 1:
        slide = prs.slides.add_slide(prs.slide_layouts[6])
        add_title(slide, "Project Comparison", "Peer scorecard outcomes")
        rows = ["Project | Score | Category"]
        for item in variants[:8]:
            if not isinstance(item, dict):
                continue
            label = str(item.get("label") or "Project").strip() or "Project"
            if item.get("is_selected"):
                label = f"{label} (Selected)"
            score_text = _display_value(item.get("jaspen_score"))
            rows.append(f"{label} | {score_text} | {_display_value(item.get('score_category'))}")
        add_bullets(slide, rows, left=0.7, top=1.7, width=8.8, height=4.9)

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


def _xlsx_text(value):
    """Keep exported user text from being interpreted as an Excel formula."""
    text = str(value or "")
    if text.startswith(("=", "+", "-", "@")):
        return f"'{text}"
    return text


def _finalize_xlsx_text_cells(worksheet):
    """Hide the formula-injection escape while retaining a literal text cell."""
    for row in worksheet.iter_rows():
        for cell in row:
            value = cell.value
            if not isinstance(value, str) or len(value) < 2:
                continue
            if value[0] == "'" and value[1] in "=+-@":
                cell.value = value[1:]
                cell.data_type = "s"
                cell.quotePrefix = True


def _xlsx_date(value):
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return datetime.strptime(text[:10], "%Y-%m-%d").date()
    except (TypeError, ValueError):
        return _xlsx_text(text)


def _wbs_phase_names(project_wbs, tasks):
    names = []
    seen = set()
    for phase in project_wbs.get("phases") or []:
        if not isinstance(phase, dict):
            continue
        name = str(phase.get("name") or phase.get("title") or "").strip()
        if name and name not in seen:
            names.append(name)
            seen.add(name)
    for task in tasks:
        if not isinstance(task, dict):
            continue
        name = str(task.get("phase") or "Execution").strip() or "Execution"
        if name not in seen:
            names.append(name)
            seen.add(name)
    return names


def _wbs_xlsx_bytes(project_wbs, *, project_name=None, workspace_name=None):
    tasks = project_wbs.get("tasks") if isinstance(project_wbs, dict) else []
    tasks = [task for task in tasks if isinstance(task, dict) and str(task.get("title") or "").strip()]
    if not tasks:
        return None

    try:
        from openpyxl import Workbook
        from openpyxl.formatting.rule import FormulaRule
        from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
        from openpyxl.worksheet.datavalidation import DataValidation
        from openpyxl.worksheet.table import Table, TableStyleInfo
    except Exception as exc:
        raise RuntimeError("openpyxl is required for Excel export.") from exc

    wb = Workbook()
    wb.properties.title = _xlsx_text(project_name or project_wbs.get("name") or "Execution Plan")
    wb.properties.subject = "Jaspen execution plan export"
    wb.properties.creator = "Jaspen"
    try:
        wb.calculation.calcMode = "auto"
        wb.calculation.fullCalcOnLoad = True
        wb.calculation.forceFullCalc = True
    except Exception:
        pass

    overview = wb.active
    overview.title = "Overview"
    task_sheet = wb.create_sheet("Tasks")

    navy = "161F3B"
    rose = "A0036C"
    slate = "475569"
    pale = "F4F6FA"
    line = "D9E1EC"
    white = "FFFFFF"
    green = "DCFCE7"
    blue = "DBEAFE"
    amber = "FEF3C7"
    red = "FEE2E2"
    thin = Side(style="thin", color=line)
    section_border = Border(bottom=Side(style="medium", color=rose))
    body_border = Border(bottom=thin)
    title = _xlsx_text(project_name or project_wbs.get("name") or "Execution Plan")
    workspace = _xlsx_text(workspace_name or "Personal Workspace")
    generated_at = datetime.now(timezone.utc).replace(tzinfo=None)
    task_data_last_row = len(tasks) + 1
    task_phase_range = f"'Tasks'!$B$2:$B${task_data_last_row}"
    task_title_range = f"'Tasks'!$C$2:$C${task_data_last_row}"
    task_status_range = f"'Tasks'!$D$2:$D${task_data_last_row}"
    task_priority_range = f"'Tasks'!$E$2:$E${task_data_last_row}"
    task_start_range = f"'Tasks'!$H$2:$H${task_data_last_row}"
    task_due_range = f"'Tasks'!$I$2:$I${task_data_last_row}"

    # Overview sheet: a compact project snapshot plus phase-level rollup.
    overview.merge_cells("A1:F1")
    overview["A1"] = title
    overview["A1"].font = Font(bold=True, size=18, color=white)
    overview["A1"].fill = PatternFill("solid", fgColor=navy)
    overview["A1"].alignment = Alignment(vertical="center")
    overview.row_dimensions[1].height = 30

    overview.merge_cells("A2:F2")
    overview["A2"] = "Use the Tasks tab filters to focus on a phase, owner, status, priority, or date range."
    overview["A2"].font = Font(size=10, color=slate)
    overview["A2"].fill = PatternFill("solid", fgColor=pale)
    overview["A2"].alignment = Alignment(wrap_text=True, vertical="center")
    overview.row_dimensions[2].height = 30

    metadata = [
        ("Project", title),
        ("Workspace", workspace),
        ("Plan start", _xlsx_date(project_wbs.get("start_date"))),
        ("Generated", generated_at),
    ]
    for row_idx, (label, value) in enumerate(metadata, start=4):
        overview.cell(row=row_idx, column=1, value=label).font = Font(bold=True, color=navy)
        overview.cell(row=row_idx, column=2, value=value)
        overview.cell(row=row_idx, column=1).border = body_border
        overview.cell(row=row_idx, column=2).border = body_border
    overview["B6"].number_format = "yyyy-mm-dd"
    overview["B7"].number_format = "yyyy-mm-dd hh:mm"

    overview["A9"] = "Progress snapshot"
    overview["A9"].font = Font(bold=True, size=12, color=navy)
    overview["A9"].border = section_border
    overview.merge_cells("A9:B9")
    summary_rows = [
        ("Total tasks", f"=COUNTA({task_title_range})", "0"),
        ("To Do", f'=COUNTIF({task_status_range},"To Do")', "0"),
        ("In Progress", f'=COUNTIF({task_status_range},"In Progress")', "0"),
        ("Blocked", f'=COUNTIF({task_status_range},"Blocked")', "0"),
        ("Done", f'=COUNTIF({task_status_range},"Done")', "0"),
        ("Completion", f'=IFERROR(COUNTIF({task_status_range},"Done")/COUNTA({task_title_range}),0)', "0%"),
    ]
    for row_idx, (label, formula, number_format) in enumerate(summary_rows, start=10):
        overview.cell(row=row_idx, column=1, value=label).font = Font(color=slate)
        overview.cell(row=row_idx, column=2, value=formula).font = Font(bold=True, color=rose)
        overview.cell(row=row_idx, column=2).number_format = number_format

    phases = _wbs_phase_names(project_wbs, tasks)
    phase_start = 18
    overview.cell(row=phase_start, column=1, value="Phase summary")
    overview.cell(row=phase_start, column=1).font = Font(bold=True, size=12, color=navy)
    overview.cell(row=phase_start, column=1).border = section_border
    overview.merge_cells(start_row=phase_start, start_column=1, end_row=phase_start, end_column=6)
    phase_headers = ["Phase #", "Phase", "Tasks", "Done", "High Priority", "Date Range"]
    for col_idx, header in enumerate(phase_headers, start=1):
        cell = overview.cell(row=phase_start + 1, column=col_idx, value=header)
        cell.font = Font(bold=True, color=white)
        cell.fill = PatternFill("solid", fgColor=navy)
        cell.alignment = Alignment(vertical="center")
    for offset, phase_name in enumerate(phases, start=1):
        row_idx = phase_start + 1 + offset
        overview.cell(row=row_idx, column=1, value=offset)
        overview.cell(row=row_idx, column=2, value=_xlsx_text(phase_name))
        overview.cell(row=row_idx, column=3, value=f'=COUNTIF({task_phase_range},B{row_idx})')
        overview.cell(row=row_idx, column=4, value=f'=COUNTIFS({task_phase_range},B{row_idx},{task_status_range},"Done")')
        overview.cell(row=row_idx, column=5, value=f'=COUNTIFS({task_phase_range},B{row_idx},{task_priority_range},"High")')
        overview.cell(
            row=row_idx,
            column=6,
            value=(
                f'=IF(OR(COUNTIFS({task_phase_range},B{row_idx},{task_start_range},">0")=0,'
                f'COUNTIFS({task_phase_range},B{row_idx},{task_due_range},">0")=0),"",'
                f'TEXT(MINIFS({task_start_range},{task_phase_range},B{row_idx}),"yyyy-mm-dd")'
                f'&" to "&TEXT(MAXIFS({task_due_range},{task_phase_range},B{row_idx}),"yyyy-mm-dd"))'
            ),
        )
        for col_idx in range(1, 7):
            overview.cell(row=row_idx, column=col_idx).border = body_border
        overview.cell(row=row_idx, column=6).alignment = Alignment(wrap_text=True)

    overview.sheet_view.showGridLines = False
    for column, width in {"A": 18, "B": 32, "C": 12, "D": 12, "E": 16, "F": 25}.items():
        overview.column_dimensions[column].width = width

    # Tasks sheet: one flat, filterable row per task. Phase rows are data, not
    # decorative headers, so filtering Phase # = 1 returns every Phase 1 task.
    headers = [
        "Phase #",
        "Phase",
        "Task",
        "Status",
        "Priority",
        "Owner",
        "Suggested Role",
        "Start Date",
        "Due Date",
        "Duration (days)",
        "Dependencies",
        "Description / Acceptance Criteria",
        "Risk Area",
        "Rationale",
        "Jira Key",
        "Function",
        "Activity Type",
        "Task ID",
        "Dependency IDs",
        "Task Order",
    ]
    task_sheet.append(headers)
    phase_order = {name: index for index, name in enumerate(phases, start=1)}
    task_by_id = {str(task.get("id") or ""): task for task in tasks}

    def task_sort_key(task):
        phase_name = str(task.get("phase") or "Execution").strip() or "Execution"
        order = task.get("order")
        try:
            order = int(order)
        except (TypeError, ValueError):
            order = tasks.index(task) + 1
        return (phase_order.get(phase_name, len(phase_order) + 1), order)

    status_labels = {
        "todo": "To Do",
        "in_progress": "In Progress",
        "blocked": "Blocked",
        "done": "Done",
    }
    for fallback_order, task in enumerate(sorted(tasks, key=task_sort_key), start=1):
        phase_name = str(task.get("phase") or "Execution").strip() or "Execution"
        raw_dependency_ids = task.get("depends_on") if isinstance(task.get("depends_on"), list) else []
        dependency_ids = [str(dep).strip() for dep in raw_dependency_ids if str(dep).strip()]
        dependency_names = [
            str(task_by_id.get(dep_id, {}).get("title") or dep_id).strip()
            for dep_id in dependency_ids
        ]
        refs = task.get("external_refs") if isinstance(task.get("external_refs"), dict) else {}
        status_key = str(task.get("status") or "todo").strip().lower()
        priority = str(task.get("priority") or "").strip().lower()
        task_order = task.get("order")
        try:
            task_order = int(task_order)
        except (TypeError, ValueError):
            task_order = fallback_order
        duration = task.get("timeline_days")
        if duration is None:
            duration = task.get("estimated_days")
        try:
            duration = int(duration) if duration is not None else None
        except (TypeError, ValueError):
            duration = None
        task_sheet.append([
            phase_order.get(phase_name, len(phase_order) + 1),
            _xlsx_text(phase_name),
            _xlsx_text(task.get("title")),
            status_labels.get(status_key, _format_label(status_key)),
            _format_label(priority) if priority else "",
            _xlsx_text(task.get("owner")),
            _xlsx_text(task.get("suggested_role")),
            _xlsx_date(task.get("start_date")),
            _xlsx_date(task.get("due_date")),
            duration,
            _xlsx_text("; ".join(dependency_names)),
            _xlsx_text(task.get("description") or task.get("acceptance")),
            _xlsx_text(task.get("risk_area")),
            _xlsx_text(task.get("rationale")),
            _xlsx_text(task.get("jira_issue_key") or refs.get("jira_issue_key")),
            _xlsx_text(task.get("function")),
            _xlsx_text(task.get("activity_type")),
            _xlsx_text(task.get("id")),
            _xlsx_text("; ".join(dependency_ids)),
            task_order,
        ])

    last_row = task_sheet.max_row
    last_col = task_sheet.max_column
    table = Table(displayName="ExecutionTasks", ref=f"A1:T{last_row}")
    table.tableStyleInfo = TableStyleInfo(
        name="TableStyleMedium2",
        showFirstColumn=False,
        showLastColumn=False,
        showRowStripes=True,
        showColumnStripes=False,
    )
    task_sheet.add_table(table)
    task_sheet.sheet_view.showGridLines = False
    task_sheet.row_dimensions[1].height = 28
    for cell in task_sheet[1]:
        cell.font = Font(bold=True, color=white)
        cell.fill = PatternFill("solid", fgColor=navy)
        cell.alignment = Alignment(wrap_text=True, vertical="center")

    for row_idx in range(2, last_row + 1):
        for col_idx in range(1, last_col + 1):
            task_sheet.cell(row=row_idx, column=col_idx).alignment = Alignment(
                wrap_text=col_idx in {3, 11, 12, 13, 14, 19},
                vertical="top",
            )
        task_sheet.cell(row=row_idx, column=8).number_format = "yyyy-mm-dd"
        task_sheet.cell(row=row_idx, column=9).number_format = "yyyy-mm-dd"
        task_sheet.cell(row=row_idx, column=10).number_format = "0"

    status_validation = DataValidation(type="list", formula1='"To Do,In Progress,Blocked,Done"', allow_blank=False)
    priority_validation = DataValidation(type="list", formula1='"High,Medium,Low"', allow_blank=True)
    task_sheet.add_data_validation(status_validation)
    task_sheet.add_data_validation(priority_validation)
    status_validation.add(f"D2:D{last_row}")
    priority_validation.add(f"E2:E{last_row}")

    status_range = f"D2:D{last_row}"
    priority_range = f"E2:E{last_row}"
    for label, color in (("Done", green), ("In Progress", blue), ("Blocked", red), ("To Do", pale)):
        task_sheet.conditional_formatting.add(
            status_range,
            FormulaRule(formula=[f'$D2="{label}"'], fill=PatternFill("solid", fgColor=color)),
        )
    for label, color in (("High", red), ("Medium", amber), ("Low", green)):
        task_sheet.conditional_formatting.add(
            priority_range,
            FormulaRule(formula=[f'$E2="{label}"'], fill=PatternFill("solid", fgColor=color)),
        )

    widths = {
        "A": 10, "B": 24, "C": 38, "D": 14, "E": 11, "F": 20, "G": 20,
        "H": 12, "I": 12, "J": 14, "K": 34, "L": 52, "M": 20, "N": 44,
        "O": 14, "P": 20, "Q": 16, "R": 22, "S": 30, "T": 12,
    }
    for column, width in widths.items():
        task_sheet.column_dimensions[column].width = width
    task_sheet.print_title_rows = "1:1"
    task_sheet.page_setup.orientation = "landscape"
    task_sheet.page_setup.fitToWidth = 1
    task_sheet.sheet_properties.pageSetUpPr.fitToPage = True

    _finalize_xlsx_text_cells(overview)
    _finalize_xlsx_text_cells(task_sheet)

    buffer = io.BytesIO()
    wb.save(buffer)
    return buffer.getvalue()


def _scorecard_dim_keys(scorecard):
    dims = scorecard.get("dimensions") if isinstance(scorecard.get("dimensions"), dict) else {}
    rubric = scorecard.get("rubric") if isinstance(scorecard.get("rubric"), dict) else {}
    ordered = [c.get("key") for c in (rubric.get("criteria") or []) if isinstance(c, dict) and c.get("key")]
    keys = [k for k in ordered if k in dims] or list(dims.keys())
    return dims, keys


def _scorecard_risk_texts(scorecard):
    risks = scorecard.get("top_risks") if isinstance(scorecard.get("top_risks"), list) else []
    out = []
    for r in risks:
        t = r if isinstance(r, str) else (r.get("risk") or r.get("text") or "" if isinstance(r, dict) else "")
        if str(t).strip():
            out.append(str(t).strip())
    return out


def _xlsx_bytes(scorecard, *, org=None):
    try:
        from openpyxl import Workbook
        from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
    except Exception as exc:
        raise RuntimeError("openpyxl is required for Excel export.") from exc

    wb = Workbook()
    ws = wb.active
    ws.title = "Scorecard"
    navy = "161F3B"
    hdr_font = Font(bold=True, color="FFFFFF", size=11)
    hdr_fill = PatternFill("solid", fgColor=navy)
    thin = Side(style="thin", color="DBE3EE")
    border = Border(left=thin, right=thin, top=thin, bottom=thin)
    wrap = Alignment(wrap_text=True, vertical="top")

    name = scorecard.get("project_name") or "Untitled Idea"
    ws["A1"] = name
    ws["A1"].font = Font(bold=True, size=16, color=navy)
    ws["A2"] = f"{(org.name if org else 'Personal Workspace')} · Generated {scorecard.get('updated_at') or _iso_now()}"
    ws["A2"].font = Font(size=9, color="6B7280")
    ws["A3"] = "Overall Score"
    ws["A3"].font = Font(bold=True)
    ws["B3"] = scorecard.get("jaspen_score")
    ws["B3"].font = Font(bold=True, color="A0036C")
    if scorecard.get("score_category"):
        ws["C3"] = scorecard.get("score_category")

    dims, keys = _scorecard_dim_keys(scorecard)
    row = 5
    for c, h in enumerate(["Criterion", "Score (0-100)", "Confidence", "Rationale"], start=1):
        cell = ws.cell(row=row, column=c, value=h)
        cell.font = hdr_font
        cell.fill = hdr_fill
        cell.border = border
    row += 1
    for k in keys:
        d = dims.get(k) if isinstance(dims.get(k), dict) else {}
        ws.cell(row=row, column=1, value=d.get("label") or k).border = border
        ws.cell(row=row, column=2, value=d.get("score")).border = border
        ws.cell(row=row, column=3, value=str(d.get("confidence") or "")).border = border
        rc = ws.cell(row=row, column=4, value=str(d.get("rationale") or ""))
        rc.border = border
        rc.alignment = wrap
        row += 1

    if scorecard.get("executive_summary"):
        row += 1
        ws.cell(row=row, column=1, value="Executive Summary").font = Font(bold=True, color=navy)
        row += 1
        ws.cell(row=row, column=1, value=str(scorecard.get("executive_summary"))).alignment = wrap
        ws.merge_cells(start_row=row, start_column=1, end_row=row, end_column=4)
        row += 2

    risk_texts = _scorecard_risk_texts(scorecard)
    if risk_texts:
        ws.cell(row=row, column=1, value="Top Risks").font = Font(bold=True, color=navy)
        row += 1
        for t in risk_texts:
            ws.cell(row=row, column=1, value=f"• {t}").alignment = wrap
            ws.merge_cells(start_row=row, start_column=1, end_row=row, end_column=4)
            row += 1

    for col, width in {"A": 28, "B": 14, "C": 14, "D": 64}.items():
        ws.column_dimensions[col].width = width

    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def _docx_bytes(scorecard, *, org=None):
    try:
        from docx import Document
        from docx.shared import Pt, RGBColor
    except Exception as exc:
        raise RuntimeError("python-docx is required for Word export.") from exc

    doc = Document()
    _ah = _accent_hex(scorecard)
    magenta = RGBColor(int(_ah[1:3], 16), int(_ah[3:5], 16), int(_ah[5:7], 16))
    name = scorecard.get("project_name") or "Untitled Idea"
    doc.add_heading(name, level=0)
    sub = doc.add_paragraph(f"{(org.name if org else 'Personal Workspace')} · Generated {scorecard.get('updated_at') or _iso_now()}")
    if sub.runs:
        sub.runs[0].font.size = Pt(9)
        sub.runs[0].font.color.rgb = RGBColor(0x6B, 0x72, 0x80)

    p = doc.add_paragraph()
    r = p.add_run(f"Overall Score: {_display_value(scorecard.get('jaspen_score'))}")
    r.bold = True
    r.font.size = Pt(14)
    r.font.color.rgb = magenta
    if scorecard.get("score_category"):
        p.add_run(f"  ({scorecard.get('score_category')})")

    if scorecard.get("executive_summary"):
        doc.add_heading("Executive Summary", level=1)
        doc.add_paragraph(str(scorecard.get("executive_summary")))

    dims, keys = _scorecard_dim_keys(scorecard)
    if keys:
        doc.add_heading("Scoring", level=1)
        table = doc.add_table(rows=1, cols=3)
        try:
            table.style = "Light Grid Accent 1"
        except Exception:
            pass
        hdr = table.rows[0].cells
        hdr[0].text, hdr[1].text, hdr[2].text = "Criterion", "Score", "Rationale"
        for k in keys:
            d = dims.get(k) if isinstance(dims.get(k), dict) else {}
            cells = table.add_row().cells
            cells[0].text = str(d.get("label") or k)
            cells[1].text = "" if d.get("score") is None else str(d.get("score"))
            cells[2].text = str(d.get("rationale") or "")

    risk_texts = _scorecard_risk_texts(scorecard)
    if risk_texts:
        doc.add_heading("Top Risks", level=1)
        for t in risk_texts:
            doc.add_paragraph(t, style="List Bullet")

    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()


@export_bp.route("/threads/<thread_id>/scorecard/xlsx", methods=["GET"])
@jwt_required()
def export_scorecard_xlsx(thread_id):
    user = User.query.filter_by(id=str(get_jwt_identity())).first()
    if not user:
        return jsonify({"error": "User not found"}), 404
    sessions = load_user_sessions(user.id) or {}
    session = _resolve_thread_session(sessions, thread_id)
    if not isinstance(session, dict):
        return jsonify({"error": "Thread not found"}), 404
    plan_key, org, _membership = _resolve_export_context(user, session)
    access_error = _require_export_plan(plan_key, "xlsx")
    if access_error:
        return access_error
    scorecard, error_response = _scorecard_record_for_export(session, thread_id, scorecard_id=request.args.get("scorecard_id"), user_id=user.id)
    if error_response:
        return error_response
    try:
        payload = _xlsx_bytes(scorecard, org=org)
    except RuntimeError as exc:
        return jsonify({"error": str(exc), "code": "xlsx_dependency_missing"}), 503
    filename = f"{_safe_filename_base(scorecard.get('project_name'))}-scorecard.xlsx"
    return _send_bytes(payload, filename=filename, mimetype=XLSX_MIMETYPE)


@export_bp.route("/threads/<thread_id>/scorecard/docx", methods=["GET"])
@jwt_required()
def export_scorecard_docx(thread_id):
    user = User.query.filter_by(id=str(get_jwt_identity())).first()
    if not user:
        return jsonify({"error": "User not found"}), 404
    sessions = load_user_sessions(user.id) or {}
    session = _resolve_thread_session(sessions, thread_id)
    if not isinstance(session, dict):
        return jsonify({"error": "Thread not found"}), 404
    plan_key, org, _membership = _resolve_export_context(user, session)
    access_error = _require_export_plan(plan_key, "docx")
    if access_error:
        return access_error
    scorecard, error_response = _scorecard_record_for_export(session, thread_id, scorecard_id=request.args.get("scorecard_id"), user_id=user.id)
    if error_response:
        return error_response
    try:
        payload = _docx_bytes(scorecard, org=org)
    except RuntimeError as exc:
        return jsonify({"error": str(exc), "code": "docx_dependency_missing"}), 503
    filename = f"{_safe_filename_base(scorecard.get('project_name'))}-scorecard.docx"
    return _send_bytes(payload, filename=filename, mimetype=DOCX_MIMETYPE)


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
        user_id=user.id,
    )
    if error_response:
        return error_response

    payload = _scorecard_pdf_bytes(scorecard, org=org)
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
        user_id=user.id,
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
    project_wbs = _resolve_thread_wbs(thread_data, request.args.get("scorecard_id"))
    if not isinstance(project_wbs, dict):
        return jsonify({"error": "No execution plan is available for this thread."}), 404

    payload = _wbs_csv_bytes(project_wbs)
    if payload is None:
        return jsonify({"error": "No WBS tasks are available to export."}), 404

    project_name = session.get("name") or thread_id
    filename = f"{_safe_filename_base(project_name)}-wbs.csv"
    return _send_bytes(payload, filename=filename, mimetype=CSV_MIMETYPE)


@export_bp.route("/threads/<thread_id>/wbs/xlsx", methods=["GET"])
@jwt_required()
def export_wbs_xlsx(thread_id):
    user = User.query.filter_by(id=str(get_jwt_identity())).first()
    if not user:
        return jsonify({"error": "User not found"}), 404

    sessions = load_user_sessions(user.id) or {}
    session = _resolve_thread_session(sessions, thread_id)
    if not isinstance(session, dict):
        return jsonify({"error": "Thread not found"}), 404

    plan_key, org, _membership = _resolve_export_context(user, session)
    access_error = _require_export_plan(plan_key, "wbs_xlsx")
    if access_error:
        return access_error

    scenario_data = _load_scenarios(user.id) or {}
    thread_data = scenario_data.get(thread_id) if isinstance(scenario_data, dict) else {}
    project_wbs = _resolve_thread_wbs(thread_data, request.args.get("scorecard_id"))
    if not isinstance(project_wbs, dict):
        return jsonify({"error": "No execution plan is available for this thread."}), 404

    project_name = session.get("name") or project_wbs.get("name") or thread_id
    try:
        payload = _wbs_xlsx_bytes(
            project_wbs,
            project_name=project_name,
            workspace_name=getattr(org, "name", None) or "Personal Workspace",
        )
    except RuntimeError as exc:
        return jsonify({"error": str(exc), "code": "xlsx_dependency_missing"}), 503
    if payload is None:
        return jsonify({"error": "No WBS tasks are available to export."}), 404

    filename = f"{_safe_filename_base(project_name)}-execution-plan.xlsx"
    return _send_bytes(payload, filename=filename, mimetype=XLSX_MIMETYPE)


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
