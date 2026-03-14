import io
import json
import os
import re
import textwrap
import uuid
from datetime import datetime

import anthropic
from flask import Blueprint, current_app, jsonify, request, send_file
from flask_jwt_extended import get_jwt_identity, jwt_required

from .sessions import load_user_sessions

reports_bp = Blueprint('reports', __name__)

REPORT_TYPE_DEFS = {
    'executive_summary': {
        'label': 'Executive Summary',
        'focus': 'Executive-level decision brief emphasizing score, risks, and top recommendations.',
    },
    'detailed': {
        'label': 'Detailed Analysis',
        'focus': 'Detailed analytical report including component scores, financial implications, and execution considerations.',
    },
    'portfolio': {
        'label': 'Portfolio Overview',
        'focus': 'Portfolio-style report comparing strategic posture and recommended next actions for leadership review.',
    },
}


def _iso_now():
    return datetime.utcnow().isoformat()


def _safe_text(value, max_len=500):
    text = str(value or '').strip()
    return text[:max_len]


def _reports_root():
    backend_root = os.path.dirname(current_app.root_path)
    root = os.path.join(backend_root, 'data', 'reports')
    os.makedirs(root, exist_ok=True)
    return root


def _user_reports_dir(user_id):
    path = os.path.join(_reports_root(), str(user_id))
    os.makedirs(path, exist_ok=True)
    return path


def _report_meta_path(user_id, report_id):
    return os.path.join(_user_reports_dir(user_id), f'{report_id}.json')


def _report_pdf_path(user_id, report_id):
    return os.path.join(_user_reports_dir(user_id), f'{report_id}.pdf')


def _resolve_thread_session(sessions, thread_id):
    tid = str(thread_id or '').strip()
    if not tid or not isinstance(sessions, dict):
        return None
    if tid in sessions and isinstance(sessions.get(tid), dict):
        return sessions.get(tid)
    for candidate in sessions.values():
        if not isinstance(candidate, dict):
            continue
        if str(candidate.get('session_id') or '').strip() == tid:
            return candidate
    return None


def _extract_latest_analysis(session, thread_id):
    if not isinstance(session, dict):
        return {
            'thread_id': str(thread_id),
            'project_name': f'Thread {thread_id}',
            'jaspen_score': None,
            'score_category': None,
            'component_scores': {},
            'financial_impact': {},
            'updated_at': None,
        }

    history = session.get('analysis_history') if isinstance(session.get('analysis_history'), list) else []
    latest = history[0] if history else None
    if not isinstance(latest, dict):
        latest = {'result': session.get('result') if isinstance(session.get('result'), dict) else {}}

    result = latest.get('result') if isinstance(latest.get('result'), dict) else {}
    compat = result.get('compat') if isinstance(result.get('compat'), dict) else {}
    component_scores = result.get('component_scores') if isinstance(result.get('component_scores'), dict) else result.get('scores')
    component_scores = component_scores if isinstance(component_scores, dict) else compat.get('components')
    if not isinstance(component_scores, dict):
        component_scores = {}

    financial_impact = result.get('financial_impact')
    if not isinstance(financial_impact, dict):
        financial_impact = {}

    raw_score = (
        result.get('jaspen_score')
        or result.get('overall_score')
        or result.get('score')
        or compat.get('score')
    )
    try:
        jaspen_score = float(raw_score)
    except Exception:
        jaspen_score = None

    return {
        'thread_id': str(thread_id),
        'project_name': _safe_text(
            result.get('project_name')
            or result.get('name')
            or session.get('name')
            or f'Thread {thread_id}',
            255,
        ),
        'jaspen_score': jaspen_score,
        'score_category': _safe_text(result.get('score_category'), 64) or None,
        'component_scores': component_scores,
        'financial_impact': financial_impact,
        'updated_at': latest.get('created_at') or session.get('timestamp') or session.get('created'),
    }


def _fallback_markdown(report_type, analysis):
    report_label = REPORT_TYPE_DEFS[report_type]['label']
    score = analysis.get('jaspen_score')
    score_text = 'Unavailable' if score is None else f'{score:.0f}'

    components = analysis.get('component_scores') if isinstance(analysis.get('component_scores'), dict) else {}
    component_lines = '\n'.join(
        f'- **{key.replace("_", " ").title()}**: {value}'
        for key, value in components.items()
    ) or '- No component scores recorded.'

    fin = analysis.get('financial_impact') if isinstance(analysis.get('financial_impact'), dict) else {}
    fin_lines = '\n'.join(
        f'- **{key.replace("_", " ").title()}**: {value}'
        for key, value in fin.items()
    ) or '- No financial impact data recorded.'

    return f"""# {report_label}\n\n## Project\n- **Name**: {analysis.get('project_name') or 'Untitled'}\n- **Thread ID**: {analysis.get('thread_id')}\n- **Jaspen Score**: {score_text}\n- **Category**: {analysis.get('score_category') or 'N/A'}\n\n## Component Scores\n{component_lines}\n\n## Financial Impact\n{fin_lines}\n\n## Recommendations\n- Prioritize the lowest component score and define a short, measurable remediation plan.\n- Align owners and deadlines to the top 3 strategic execution tasks.\n- Re-run analysis after milestone completion to track score progression.\n"""


def _llm_report_markdown(report_type, analysis):
    api_key = (
        current_app.config.get('ANTHROPIC_API_KEY')
        or current_app.config.get('CLAUDE_API_KEY')
        or os.getenv('ANTHROPIC_API_KEY')
        or os.getenv('CLAUDE_API_KEY')
    )
    model_name = (
        current_app.config.get('AI_REPORT_MODEL')
        or os.getenv('AI_REPORT_MODEL')
        or current_app.config.get('AI_AGENT_ANTHROPIC_MODEL')
        or os.getenv('AI_AGENT_ANTHROPIC_MODEL')
        or 'claude-3-7-sonnet-latest'
    )
    if not api_key:
        return _fallback_markdown(report_type, analysis)

    descriptor = REPORT_TYPE_DEFS[report_type]
    prompt = f"""
Generate a professional markdown report for Jaspen.

Report type: {descriptor['label']}
Focus: {descriptor['focus']}

Project context:
{json.dumps(analysis, indent=2)}

Output requirements:
- Markdown only
- Title + clear section headings
- Specific recommendations tied to score/components
- Include a concise action plan section
""".strip()

    try:
        client = anthropic.Anthropic(api_key=api_key)
        response = client.messages.create(
            model=model_name,
            temperature=0.2,
            max_tokens=1800,
            system='You are a strategy reporting assistant. Return markdown only.',
            messages=[{'role': 'user', 'content': prompt}],
        )
        text_parts = []
        for block in getattr(response, 'content', []) or []:
            if getattr(block, 'type', None) == 'text':
                text = str(getattr(block, 'text', '') or '').strip()
                if text:
                    text_parts.append(text)
        content = _safe_text('\n'.join(text_parts), max_len=20000)
        return content or _fallback_markdown(report_type, analysis)
    except Exception:
        return _fallback_markdown(report_type, analysis)


def _pdf_escape(value):
    return str(value or '').replace('\\', r'\\').replace('(', r'\(').replace(')', r'\)')


def _minimal_pdf_bytes(text):
    lines = []
    for raw_line in str(text or '').splitlines():
        wrapped = textwrap.wrap(raw_line, width=96) or ['']
        lines.extend(wrapped)

    content_ops = ['BT', '/F1 10 Tf', '50 780 Td', '14 TL']
    for line in lines[:2600]:
        content_ops.append(f'({_pdf_escape(line)}) Tj')
        content_ops.append('T*')
    content_ops.append('ET')

    stream_data = ('\n'.join(content_ops) + '\n').encode('latin-1', 'replace')

    objects = []
    objects.append(b'1 0 obj\n<< /Type /Catalog /Pages 2 0 R >>\nendobj\n')
    objects.append(b'2 0 obj\n<< /Type /Pages /Kids [3 0 R] /Count 1 >>\nendobj\n')
    objects.append(b'3 0 obj\n<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>\nendobj\n')
    objects.append(b'4 0 obj\n<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>\nendobj\n')
    objects.append(
        b'5 0 obj\n<< /Length ' + str(len(stream_data)).encode('ascii') + b' >>\nstream\n' + stream_data + b'endstream\nendobj\n'
    )

    out = io.BytesIO()
    out.write(b'%PDF-1.4\n')
    offsets = [0]
    for obj in objects:
        offsets.append(out.tell())
        out.write(obj)

    xref_pos = out.tell()
    out.write(f'xref\n0 {len(objects) + 1}\n'.encode('ascii'))
    out.write(b'0000000000 65535 f \n')
    for pos in offsets[1:]:
        out.write(f'{pos:010d} 00000 n \n'.encode('ascii'))

    out.write(
        (
            'trailer\n'
            f'<< /Size {len(objects) + 1} /Root 1 0 R >>\n'
            f'startxref\n{xref_pos}\n'
            '%%EOF\n'
        ).encode('ascii')
    )
    return out.getvalue()


def _markdown_to_pdf_bytes(title, markdown_text):
    try:
        from reportlab.lib.pagesizes import letter
        from reportlab.pdfgen import canvas

        buffer = io.BytesIO()
        pdf = canvas.Canvas(buffer, pagesize=letter)
        width, height = letter

        y = height - 48
        pdf.setFont('Helvetica-Bold', 14)
        pdf.drawString(40, y, _safe_text(title, 140))
        y -= 24

        pdf.setFont('Helvetica', 10)
        for raw_line in str(markdown_text or '').splitlines():
            chunks = textwrap.wrap(raw_line, width=98) or ['']
            for chunk in chunks:
                if y <= 48:
                    pdf.showPage()
                    y = height - 48
                    pdf.setFont('Helvetica', 10)
                pdf.drawString(40, y, _safe_text(chunk, 500))
                y -= 14

        pdf.save()
        buffer.seek(0)
        return buffer.read()
    except Exception:
        return _minimal_pdf_bytes(markdown_text)


def _write_report_metadata(user_id, report_id, metadata):
    path = _report_meta_path(user_id, report_id)
    with open(path, 'w') as handle:
        json.dump(metadata, handle, indent=2)


def _read_report_metadata(user_id, report_id):
    path = _report_meta_path(user_id, report_id)
    if not os.path.exists(path):
        return None
    try:
        with open(path, 'r') as handle:
            data = json.load(handle)
        return data if isinstance(data, dict) else None
    except Exception:
        return None


@reports_bp.route('/generate', methods=['POST'])
@jwt_required()
def generate_report():
    user_id = str(get_jwt_identity())
    payload = request.get_json() or {}

    thread_id = _safe_text(payload.get('thread_id'), 255)
    report_type = _safe_text(payload.get('report_type'), 64).lower()

    if not thread_id:
        return jsonify({'error': 'thread_id is required'}), 400
    if report_type not in REPORT_TYPE_DEFS:
        return jsonify({'error': 'report_type must be executive_summary, detailed, or portfolio'}), 400

    sessions = load_user_sessions(user_id) or {}
    session = _resolve_thread_session(sessions, thread_id)
    if not isinstance(session, dict):
        return jsonify({'error': 'Thread not found'}), 404

    analysis = _extract_latest_analysis(session, thread_id)
    markdown = _llm_report_markdown(report_type, analysis)

    report_id = str(uuid.uuid4())
    filename = f"{_safe_text(analysis.get('project_name') or 'jaspen-report', 100).replace(' ', '-').lower()}-{report_type}.pdf"
    filename = re.sub(r'[^a-z0-9._-]+', '-', filename).strip('-') or f'{report_id}.pdf'
    if not filename.endswith('.pdf'):
        filename = f'{filename}.pdf'

    pdf_bytes = _markdown_to_pdf_bytes(REPORT_TYPE_DEFS[report_type]['label'], markdown)
    pdf_path = _report_pdf_path(user_id, report_id)
    with open(pdf_path, 'wb') as handle:
        handle.write(pdf_bytes)

    metadata = {
        'report_id': report_id,
        'user_id': user_id,
        'thread_id': thread_id,
        'project_name': analysis.get('project_name') or 'Untitled',
        'report_type': report_type,
        'report_type_label': REPORT_TYPE_DEFS[report_type]['label'],
        'filename': filename,
        'created_at': _iso_now(),
        'download_url': f'/api/v1/reports/{report_id}/download',
    }
    _write_report_metadata(user_id, report_id, metadata)

    return jsonify(metadata), 200


@reports_bp.route('', methods=['GET'])
@jwt_required()
def list_reports():
    user_id = str(get_jwt_identity())
    directory = _user_reports_dir(user_id)

    reports = []
    for entry in os.listdir(directory):
        if not entry.endswith('.json'):
            continue
        report_id = entry[:-5]
        meta = _read_report_metadata(user_id, report_id)
        if not isinstance(meta, dict):
            continue
        reports.append(meta)

    reports.sort(key=lambda row: str(row.get('created_at') or ''), reverse=True)
    return jsonify({'reports': reports}), 200


@reports_bp.route('/<report_id>/download', methods=['GET'])
@jwt_required()
def download_report(report_id):
    user_id = str(get_jwt_identity())
    meta = _read_report_metadata(user_id, report_id)
    if not isinstance(meta, dict):
        return jsonify({'error': 'Report not found'}), 404

    pdf_path = _report_pdf_path(user_id, report_id)
    if not os.path.exists(pdf_path):
        return jsonify({'error': 'Report file missing'}), 404

    return send_file(
        pdf_path,
        mimetype='application/pdf',
        as_attachment=True,
        download_name=meta.get('filename') or f'{report_id}.pdf',
    )


@reports_bp.route('/<report_id>', methods=['DELETE'])
@jwt_required()
def delete_report(report_id):
    user_id = str(get_jwt_identity())

    meta = _read_report_metadata(user_id, report_id)
    if not isinstance(meta, dict):
        return jsonify({'error': 'Report not found'}), 404

    pdf_path = _report_pdf_path(user_id, report_id)
    meta_path = _report_meta_path(user_id, report_id)

    try:
        if os.path.exists(pdf_path):
            os.remove(pdf_path)
        if os.path.exists(meta_path):
            os.remove(meta_path)
    except Exception as exc:
        return jsonify({'error': f'Failed to delete report: {exc}'}), 500

    return jsonify({'success': True, 'report_id': report_id}), 200
