from __future__ import annotations

import io
import json
import os
import re
import uuid
from datetime import datetime

import anthropic
import pandas as pd
from flask import Blueprint, current_app, jsonify, request
from flask_jwt_extended import get_jwt_identity, jwt_required

from app import db
from app.models import UserDataset

insights_bp = Blueprint('insights', __name__)

_MAX_UPLOAD_BYTES = 10 * 1024 * 1024
_ALLOWED_EXTENSIONS = {'.csv', '.xlsx', '.xls'}


def _pagination_params():
    page = request.args.get('page', 1, type=int)
    per_page = min(request.args.get('per_page', 25, type=int), 100)
    return max(page, 1), max(per_page, 1)


def _extract_json_object(text):
    try:
        return json.loads(text)
    except Exception:
        match = re.search(r'\{.*\}', str(text or ''), re.DOTALL)
        if not match:
            return None
        try:
            return json.loads(match.group())
        except Exception:
            return None


def _sanitize_filename(name):
    base = str(name or 'dataset').strip()
    return re.sub(r'[^A-Za-z0-9._-]+', '_', base)[:255] or 'dataset'


def _uploads_root():
    # backend/data/user_uploads
    backend_root = os.path.dirname(current_app.root_path)
    root = os.path.join(backend_root, 'data', 'user_uploads')
    os.makedirs(root, exist_ok=True)
    return root


def _dataset_csv_path(user_id, dataset_id):
    base = os.path.realpath(_uploads_root())
    user_dir = os.path.realpath(os.path.join(base, str(user_id)))
    if os.path.commonpath([base, user_dir]) != base:
        raise ValueError('Invalid dataset path')
    os.makedirs(user_dir, exist_ok=True)
    path = os.path.realpath(os.path.join(user_dir, f'{dataset_id}.csv'))
    if os.path.commonpath([base, path]) != base:
        raise ValueError('Invalid dataset path')
    return path


def _read_excel_dataset(raw, filename):
    try:
        from openpyxl import load_workbook
    except Exception as exc:
        raise ValueError(f'Could not parse Excel file ({filename}): openpyxl is required ({exc})')

    wb = None
    try:
        wb = load_workbook(filename=io.BytesIO(raw), read_only=True, data_only=True)
        ws = wb.active
        rows = ws.iter_rows(values_only=True)
        header_row = next(rows, None)
        if header_row is None:
            raise ValueError('Excel file has no header row.')

        normalized_headers = []
        for idx, cell in enumerate(header_row):
            label = str(cell).strip() if cell is not None else ''
            if not label:
                label = f'column_{idx + 1}'
            normalized_headers.append(label)

        values = []
        width = len(normalized_headers)
        for row in rows:
            row_values = list(row[:width]) if isinstance(row, tuple) else []
            if len(row_values) < width:
                row_values.extend([None] * (width - len(row_values)))
            values.append(row_values)

        return pd.DataFrame(values, columns=normalized_headers)
    except ValueError:
        raise
    except Exception as exc:
        raise ValueError(f'Could not parse Excel file ({filename}): {exc}')
    finally:
        if wb is not None:
            try:
                wb.close()
            except Exception:
                pass


def _parse_uploaded_dataset(uploaded_file):
    filename = _sanitize_filename(getattr(uploaded_file, 'filename', 'dataset.csv'))
    ext = os.path.splitext(filename)[1].lower()
    if ext not in _ALLOWED_EXTENSIONS:
        raise ValueError('Unsupported file type. Upload CSV or Excel (.csv/.xlsx/.xls).')

    raw = uploaded_file.read()
    if not raw:
        raise ValueError('Uploaded file is empty.')
    if len(raw) > _MAX_UPLOAD_BYTES:
        raise ValueError('File exceeds 10MB upload limit.')

    bio = io.BytesIO(raw)
    if ext == '.csv':
        df = pd.read_csv(bio)
    else:
        df = _read_excel_dataset(raw, filename)

    if df is None or df.empty:
        raise ValueError('Dataset has no rows.')

    return filename, df


def _dataset_summary(df):
    numeric_summary = {}
    categorical_summary = {}

    numeric_cols = list(df.select_dtypes(include=['number']).columns)
    for col in numeric_cols:
        series = pd.to_numeric(df[col], errors='coerce').dropna()
        if series.empty:
            continue
        numeric_summary[str(col)] = {
            'mean': float(series.mean()),
            'median': float(series.median()),
            'min': float(series.min()),
            'max': float(series.max()),
            'std': float(series.std(ddof=0)),
        }

    for col in df.columns:
        col_name = str(col)
        if col_name in numeric_summary:
            continue
        try:
            counts = df[col].astype(str).value_counts(dropna=True).head(10)
            categorical_summary[col_name] = [
                {'value': str(idx), 'count': int(val)}
                for idx, val in counts.items()
            ]
        except Exception:
            categorical_summary[col_name] = []

    try:
        preview_rows = json.loads(df.head(5).where(df.head(5).notna(), None).to_json(orient='records', date_format='iso'))
    except Exception:
        preview_rows = []

    try:
        context_rows = json.loads(df.head(20).where(df.head(20).notna(), None).to_json(orient='records', date_format='iso'))
    except Exception:
        context_rows = []

    column_types = {str(col): str(dtype) for col, dtype in df.dtypes.items()}

    return {
        'row_count': int(df.shape[0]),
        'column_count': int(df.shape[1]),
        'column_names': [str(col) for col in df.columns],
        'column_types': column_types,
        'numeric_summary': numeric_summary,
        'categorical_summary': categorical_summary,
        'preview_rows': preview_rows,
        'context_rows': context_rows,
    }


def _heuristic_analysis(summary, question=''):
    question_text = str(question or '').strip()
    trends = []
    anomalies = []
    opportunities = []
    risks = []

    for metric, stats in (summary.get('numeric_summary') or {}).items():
        try:
            stdev = float(stats.get('std') or 0.0)
            mean_val = float(stats.get('mean') or 0.0)
            ratio = (stdev / abs(mean_val)) if mean_val else stdev
        except Exception:
            stdev = 0.0
            ratio = 0.0

        trends.append(f"{metric}: mean {stats.get('mean'):.2f}, median {stats.get('median'):.2f}")
        if ratio > 0.75:
            anomalies.append(f"{metric} shows high variance; investigate outlier drivers.")
            risks.append(f"Operational volatility appears elevated in {metric}.")
        elif ratio < 0.15:
            opportunities.append(f"{metric} is stable enough to use as a planning baseline.")

    if not opportunities:
        opportunities.append('Build KPI control limits and track trend deltas weekly to identify upside opportunities early.')
    if not risks:
        risks.append('Review data freshness and source quality before making high-stakes decisions.')

    summary_text = (
        f"Analyzed {summary.get('row_count', 0)} rows across {summary.get('column_count', 0)} columns. "
        f"Question focus: {question_text or 'general strategy diagnostics'}."
    )

    return {
        'summary': summary_text,
        'trends': trends[:8],
        'anomalies': anomalies[:8],
        'opportunities': opportunities[:8],
        'risks': risks[:8],
        'charts': [],
    }


def _llm_analysis(summary, question=''):
    api_key = (
        current_app.config.get('ANTHROPIC_API_KEY')
        or current_app.config.get('CLAUDE_API_KEY')
        or os.getenv('ANTHROPIC_API_KEY')
        or os.getenv('CLAUDE_API_KEY')
    )
    model_name = (
        current_app.config.get('AI_DATA_INSIGHTS_MODEL')
        or os.getenv('AI_DATA_INSIGHTS_MODEL')
        or current_app.config.get('AI_AGENT_ANTHROPIC_MODEL')
        or os.getenv('AI_AGENT_ANTHROPIC_MODEL')
        or 'claude-3-7-sonnet-latest'
    )
    if not api_key:
        return _heuristic_analysis(summary, question)

    prompt = f"""
You are a strategy data analyst. Analyze the dataset context below.

Question (optional): {question or 'General analysis'}

Columns and dtypes:
{json.dumps(summary.get('column_types') or {}, indent=2)}

Numeric summary:
{json.dumps(summary.get('numeric_summary') or {}, indent=2)}

Categorical value counts:
{json.dumps(summary.get('categorical_summary') or {}, indent=2)}

First 20 rows:
{json.dumps(summary.get('context_rows') or [], indent=2)}

Return strict JSON with this shape:
{{
  "summary": "...",
  "trends": ["..."],
  "anomalies": ["..."],
  "opportunities": ["..."],
  "risks": ["..."],
  "charts": [
    {{"type": "bar|line|pie", "title": "...", "data": {{}}}}
  ]
}}
""".strip()

    try:
        client = anthropic.Anthropic(api_key=api_key)
        response = client.messages.create(
            model=model_name,
            temperature=0.2,
            max_tokens=1200,
            system='You are a concise analytics assistant. Return JSON only.',
            messages=[{'role': 'user', 'content': prompt}],
        )
        text_parts = []
        for block in getattr(response, 'content', []) or []:
            if getattr(block, 'type', None) == 'text':
                text = str(getattr(block, 'text', '') or '').strip()
                if text:
                    text_parts.append(text)
        payload = _extract_json_object('\n'.join(text_parts))
        if not isinstance(payload, dict):
            raise ValueError('Invalid analysis response')

        return {
            'summary': str(payload.get('summary') or '').strip(),
            'trends': [str(item) for item in (payload.get('trends') or []) if str(item).strip()],
            'anomalies': [str(item) for item in (payload.get('anomalies') or []) if str(item).strip()],
            'opportunities': [str(item) for item in (payload.get('opportunities') or []) if str(item).strip()],
            'risks': [str(item) for item in (payload.get('risks') or []) if str(item).strip()],
            'charts': payload.get('charts') if isinstance(payload.get('charts'), list) else [],
        }
    except Exception:
        return _heuristic_analysis(summary, question)


@insights_bp.route('/upload', methods=['POST'])
@jwt_required()
def upload_dataset():
    user_id = str(get_jwt_identity())
    uploaded = request.files.get('file')
    if uploaded is None:
        return jsonify({'error': 'file is required (multipart/form-data)'}), 400

    try:
        filename, df = _parse_uploaded_dataset(uploaded)
        summary = _dataset_summary(df)

        dataset = UserDataset(
            id=str(uuid.uuid4()),
            user_id=user_id,
            filename=filename,
            row_count=summary['row_count'],
            column_names=summary['column_names'],
            data_preview=summary['preview_rows'],
            status='ready',
            created_at=datetime.utcnow(),
        )
        db.session.add(dataset)
        db.session.flush()

        csv_path = _dataset_csv_path(user_id, dataset.id)
        df.to_csv(csv_path, index=False)

        db.session.commit()
        return jsonify({
            'dataset_id': dataset.id,
            'filename': filename,
            'rows': summary['row_count'],
            'columns': summary['column_names'],
            'preview': summary['preview_rows'],
        }), 200
    except ValueError as err:
        return jsonify({'error': str(err)}), 400
    except Exception as err:
        db.session.rollback()
        current_app.logger.error("[insights.upload] %s", err)
        return jsonify({'error': 'Failed to upload dataset'}), 500


@insights_bp.route('/analyze', methods=['POST'])
@jwt_required()
def analyze_dataset():
    user_id = str(get_jwt_identity())
    payload = request.get_json() or {}
    dataset_id = str(payload.get('dataset_id') or '').strip()
    question = str(payload.get('question') or '').strip()
    if not dataset_id:
        return jsonify({'error': 'dataset_id is required'}), 400

    dataset = UserDataset.query.filter_by(id=dataset_id, user_id=user_id).first()
    if not dataset:
        return jsonify({'error': 'Dataset not found'}), 404

    csv_path = _dataset_csv_path(user_id, dataset.id)
    if not os.path.exists(csv_path):
        return jsonify({'error': 'Dataset file missing on disk'}), 404

    try:
        df = pd.read_csv(csv_path)
        if df.empty:
            return jsonify({'error': 'Dataset is empty'}), 400
        summary = _dataset_summary(df)
        analysis = _llm_analysis(summary, question)

        return jsonify({
            'summary': analysis.get('summary') or '',
            'trends': analysis.get('trends') if isinstance(analysis.get('trends'), list) else [],
            'anomalies': analysis.get('anomalies') if isinstance(analysis.get('anomalies'), list) else [],
            'opportunities': analysis.get('opportunities') if isinstance(analysis.get('opportunities'), list) else [],
            'risks': analysis.get('risks') if isinstance(analysis.get('risks'), list) else [],
            'charts': analysis.get('charts') if isinstance(analysis.get('charts'), list) else [],
        }), 200
    except ValueError as err:
        return jsonify({'error': str(err)}), 400
    except Exception as err:
        current_app.logger.error("[insights.analyze] %s", err)
        return jsonify({'error': 'Failed to analyze dataset'}), 500


@insights_bp.route('/datasets', methods=['GET'])
@jwt_required()
def list_datasets():
    user_id = str(get_jwt_identity())
    page, per_page = _pagination_params()
    pagination = (
        UserDataset.query
        .filter_by(user_id=user_id)
        .order_by(UserDataset.created_at.desc())
        .paginate(page=page, per_page=per_page, error_out=False)
    )
    items = [row.to_dict() for row in pagination.items]
    return jsonify({
        'items': items,
        'datasets': items,
        'total': pagination.total,
        'page': pagination.page,
        'per_page': pagination.per_page,
        'pages': pagination.pages,
    }), 200


@insights_bp.route('/datasets/<dataset_id>', methods=['DELETE'])
@jwt_required()
def delete_dataset(dataset_id):
    user_id = str(get_jwt_identity())
    dataset_id = str(dataset_id or '').strip()
    if not dataset_id:
        return jsonify({'error': 'dataset_id is required'}), 400

    dataset = UserDataset.query.filter_by(id=dataset_id, user_id=user_id).first()
    if not dataset:
        return jsonify({'error': 'Dataset not found'}), 404

    csv_path = _dataset_csv_path(user_id, dataset.id)

    try:
        if os.path.exists(csv_path):
            os.remove(csv_path)
        db.session.delete(dataset)
        db.session.commit()
        return jsonify({'success': True}), 200
    except ValueError as err:
        return jsonify({'error': str(err)}), 400
    except Exception as err:
        db.session.rollback()
        current_app.logger.error("[insights.delete] %s", err)
        return jsonify({'error': 'Failed to delete dataset'}), 500
