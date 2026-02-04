# statistical_analysis_api.py

from __future__ import annotations
import os
import json
import numpy as np
import pandas as pd
import io
import zipfile
import tempfile, zipfile

from flask import send_file
from flask import Blueprint, request, jsonify, current_app
from werkzeug.utils import secure_filename
from scipy.stats import chi2_contingency
from sklearn.linear_model import LinearRegression
from sklearn.metrics import r2_score

import anthropic  # Anthropic client

def _coerce_numeric_columns(df):
    """
    Convert object columns that look like numbers (e.g., '$1,234', '8.5%', '(1,200)') into numeric.
    Leaves columns untouched if conversion would produce mostly NaNs.
    """
    
    for col in df.columns:
        if df[col].dtype == 'object':
            s = df[col].astype(str).str.strip()

            # Convert accounting negatives like "(1,234.56)" -> "-1234.56"
            s = s.str.replace(r'\(([^)]+)\)', r'-\1', regex=True)

            # Remove currency symbols and thousands separators, drop percent sign
            s = s.str.replace(r'[\$,]', '', regex=True).str.replace(r'%', '', regex=True)

            # Normalize empties
            s = s.replace({'': np.nan, 'nan': np.nan, 'None': np.nan})

            num = pd.to_numeric(s, errors='coerce')
            valid_ratio = num.notna().mean()
            enough_valid = num.notna().sum() >= max(3, int(0.3 * len(num)))
            if valid_ratio >= 0.6 and enough_valid:
                df[col] = num

    return df

statistical_bp = Blueprint('statistical_analysis', __name__, url_prefix='/api/statistical-analysis')

# ----------------------------- Helpers -----------------------------

def allowed_file(filename: str) -> bool:
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in {'csv', 'xlsx', 'xls'}

def detect_column_types(df: pd.DataFrame) -> dict[str, str]:
    column_types = {}
    for col in df.columns:
        if pd.api.types.is_numeric_dtype(df[col]):
            unique_ratio = df[col].nunique(dropna=True) / max(len(df), 1)
            if unique_ratio < 0.05 and df[col].nunique(dropna=True) < 20:
                column_types[col] = 'categorical'
            else:
                column_types[col] = 'numeric'
        else:
            column_types[col] = 'categororical' if False else 'categorical'
    return column_types

def get_claude_client() -> anthropic.Anthropic:
    api_key = (
        os.environ.get("ANTHROPIC_API_KEY")
        or os.environ.get("CLAUDE_API_KEY")
        or current_app.config.get("ANTHROPIC_API_KEY")
        or current_app.config.get("CLAUDE_API_KEY")
    )
    if not api_key:
        raise ValueError("ANTHROPIC_API_KEY/CLAUDE_API_KEY not configured")
    return anthropic.Anthropic(api_key=api_key)

STATISTICIAN_SYSTEM_PROMPT = (
    "You are a top 0.1% senior statistician and methods expert. "
    "You must: (1) interpret the provided summary/results; (2) recommend appropriate tests "
    "with assumptions and quick checks; (3) explain interpretation in concise, non-jargon bullets; "
    "(4) call out limitations (sample size, distributional assumptions, outliers, multiple testing); "
    "(5) propose next steps (validation, diagnostics, visualization). Keep answers crisp and actionable."
)

def get_ai_analysis(data_summary: str, goal: str, target_col: str|None=None, group_col: str|None=None) -> str:
    try:
        client = get_claude_client()
        model = os.environ.get("ANTHROPIC_MODEL", "claude-sonnet-4-5-20250929")
        prompt = (
            f"Dataset Summary:\n{data_summary}\n\n"
            f"Analysis Goal: {goal}\n"
            f"Target Column: {target_col or 'None'}\n"
            f"Group Column: {group_col or 'None'}\n\n"
            "Please provide:\n"
            "1) 3–5 key insights\n"
            "2) Recommended statistical tests (assumptions & quick checks)\n"
            "3) Interpretation guidance\n"
            "4) Next steps\n"
            "Use tight bullet points."
        )
        resp = client.messages.create(
            model=model,
            max_tokens=700,
            temperature=0.3,
            system=STATISTICIAN_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": prompt}],
        )
        return (resp.content[0].text or "").strip()
    except Exception as e:
        return f"AI analysis unavailable: {str(e)}"

# ----------------------------- Routes -----------------------------

@statistical_bp.route('/upload', methods=['POST'])
def upload_file():
    if 'file' not in request.files:
        return jsonify({'error': 'No file provided'}), 400
    file = request.files['file']
    if file.filename == '':
        return jsonify({'error': 'No file selected'}), 400
    if not allowed_file(file.filename):
        return jsonify({'error': 'File type not supported. Please upload CSV or Excel files.'}), 400

    try:
        filename = secure_filename(file.filename)
        if filename.lower().endswith('.csv'):
            df = pd.read_csv(file)
        else:
            df = pd.read_excel(file)

        

        column_types = detect_column_types(df)
        preview = {
            'filename': filename,
            'rows': int(len(df)),
            'columns': int(len(df.columns)),
            'column_info': [
                {
                    'name': col,
                    'type': column_types[col],
                    'non_null': int(df[col].count()),
                    'null_count': int(df[col].isnull().sum()),
                    'unique_values': int(df[col].nunique(dropna=True))
                }
                for col in df.columns
            ]
            
        }
        sample_rows = df.head(5).where(pd.notnull(df), None)
        preview["sample_data"] = sample_rows.to_dict(orient="records")

        return jsonify({
            'success': True,
            'data': preview,
            'message': f'Successfully loaded {filename} with {len(df)} rows and {len(df.columns)} columns'
        })
    except Exception as e:
        return jsonify({'error': f'Error processing file: {str(e)}'}), 500

@statistical_bp.route('/comprehensive', methods=['POST'])
def comprehensive_analysis():
    try:
        file = request.files.get('file')
        goal = request.form.get('goal', 'describe')
        raw_target = (request.form.get('target_col') or '').strip()
        raw_group  = (request.form.get('group_col')  or '').strip()


        if not file:
            return jsonify({'error': 'No file provided'}), 400

        fname = file.filename.lower()
        if fname.endswith('.csv'):
            df = pd.read_csv(file)
        else:
            df = pd.read_excel(file)
        
        

        column_types = detect_column_types(df)
        numeric_cols = [c for c,t in column_types.items() if t == 'numeric']
        categorical_cols = [c for c,t in column_types.items() if t == 'categorical']
        # --- Column resolver: tolerant to case, spaces, quotes, punctuation ---
        import re

        def _norm(s: str) -> str:
            s = (s or "").strip().strip('"').strip("'")
            s = s.lower()
            s = re.sub(r'\s+', ' ', s)           # collapse whitespace
            s = re.sub(r'[^a-z0-9]+', '', s)     # drop punctuation/non-alnum
            return s

        def _resolve_name(user_name: str, candidates):
            if not user_name or not candidates:
                return None
            u = _norm(user_name)

            # exact case-insensitive
            for c in candidates:
                if user_name.strip().strip('"').strip("'").lower() == str(c).lower():
                    return c

            # normalized exact
            norm_map = { _norm(str(c)): c for c in candidates }
            if u in norm_map:
                return norm_map[u]

            # startswith / contains
            for k, c in norm_map.items():
                if k.startswith(u) or u.startswith(k):
                    return c
            for k, c in norm_map.items():
                if u and k and (u in k or k in u):
                    return c

            return None

        # Resolve requested columns (if provided)
        target_col = _resolve_name(raw_target, list(df.columns)) if raw_target else None
        group_col  = _resolve_name(raw_group,  list(df.columns)) if raw_group  else None

        # Validate / coerce types if resolved
        if target_col and target_col not in numeric_cols:
            try:
                df[target_col] = pd.to_numeric(df[target_col], errors='coerce')
                if df[target_col].notna().sum() > 0:
                    column_types[target_col] = 'numeric'
                if target_col not in numeric_cols:
                    numeric_cols.append(target_col)
            except Exception:
                target_col = None  # let frontend show picker

        if group_col and group_col not in categorical_cols:
            df[group_col] = df[group_col].astype('category')
            column_types[group_col] = 'categorical'
            if group_col not in categorical_cols:
                categorical_cols.append(group_col)

        if group_col and group_col not in categorical_cols:
            df[group_col] = df[group_col].astype('category')
            column_types[group_col] = 'categorical'
            if group_col not in categorical_cols:
                categorical_cols.append(group_col)
        results = {
            'dataset_info': {
                'rows': int(len(df)),
                'columns': int(len(df.columns)),
                'numeric_columns': numeric_cols,
                'categorical_columns': categorical_cols
            },
            'analysis': {}
        }

        # Descriptive statistics
        if numeric_cols:
            desc_stats = df[numeric_cols].describe().to_dict()
            results['analysis']['descriptive_stats'] = desc_stats

        # Correlations
        if len(numeric_cols) > 1:
            corr_matrix = df[numeric_cols].corr().to_dict()
            results['analysis']['correlations'] = corr_matrix

        # Regression
        if target_col and target_col in df.columns and column_types.get(target_col) == 'numeric':
            try:
                predictors = [c for c in numeric_cols if c != target_col]
                sub = df[[target_col] + predictors].dropna()
                if len(predictors) >= 1 and len(sub) >= 3:
                    X = sub[predictors].to_numpy()
                    y = sub[target_col].to_numpy()
                    model = LinearRegression()
                    model.fit(X, y)
                    y_pred = model.predict(X)
                    r2 = r2_score(y, y_pred)
                    results['analysis']['regression'] = {
                        'target': target_col,
                        'predictors': predictors,
                        'r2_score': float(r2) if np.isfinite(r2) else None,
                        'intercept': float(model.intercept_) if np.isfinite(model.intercept_) else None,
                        'coefficients': {
                            predictors[i]: float(coef) if np.isfinite(coef) else None
                            for i, coef in enumerate(model.coef_)
                        },
                        'n_obs': int(len(sub))
                    }
            except Exception as rex:
                results.setdefault('analysis', {}).setdefault('errors', {})['regression'] = str(rex)

        # Group means if numeric target + categorical group
        if group_col and target_col and group_col in df.columns and target_col in df.columns:
            if column_types.get(target_col) == 'numeric' and column_types.get(group_col) == 'categorical':
                try:
                    group_stats = df.groupby(group_col, dropna=True)[target_col].agg(['mean', 'std', 'count']).to_dict()
                    results['analysis']['group_analysis'] = group_stats
                except Exception as ex:
                    results.setdefault('analysis', {}).setdefault('errors', {})['group_analysis'] = str(ex)

        # ANOVA + T-test (2 groups)
        if group_col and target_col and group_col in df.columns and target_col in df.columns:
            if column_types.get(target_col) == 'numeric' and column_types.get(group_col) == 'categorical':
                sub = df[[group_col, target_col]].dropna()
                groups = []
                for gval, gdf in sub.groupby(group_col, dropna=True):
                    vals = pd.to_numeric(gdf[target_col], errors='coerce').dropna().to_numpy()
                    if vals.size > 0:
                        groups.append((str(gval), vals))
                if len(groups) >= 2:
                    try:
                        from scipy.stats import f_oneway, levene, ttest_ind
                        labels, arrays = zip(*groups)
                        f_stat, p_val = f_oneway(*arrays)
                        all_vals = np.concatenate(arrays)
                        grand_mean = np.mean(all_vals)
                        ss_total = float(np.sum((all_vals - grand_mean) ** 2))
                        ss_between = 0.0
                        for lbl, arr in groups:
                            n = arr.size
                            ss_between += float(n * (np.mean(arr) - grand_mean) ** 2)
                        eta_sq = float(ss_between / ss_total) if ss_total > 0 else None
                        results['analysis']['anova'] = {
                            'target': target_col,
                            'group': group_col,
                            'k_groups': len(groups),
                            'f_stat': float(f_stat) if np.isfinite(f_stat) else None,
                            'p_value': float(p_val) if np.isfinite(p_val) else None,
                            'eta_squared': eta_sq,
                            'group_means': {lbl: float(np.mean(arr)) for lbl, arr in groups},
                            'group_counts': {lbl: int(arr.size) for lbl, arr in groups},
                        }
                        if len(groups) == 2:
                            (lbl1, a1), (lbl2, a2) = groups
                            lev_stat, lev_p = levene(a1, a2, center='median')
                            equal_var = bool(lev_p >= 0.05)
                            t_stat, t_p = ttest_ind(a1, a2, equal_var=equal_var)
                            def cohens_d(x, y, use_pooled=True):
                                x, y = np.asarray(x), np.asarray(y)
                                nx, ny = x.size, y.size
                                mx, my = np.mean(x), np.mean(y)
                                vx, vy = np.var(x, ddof=1), np.var(y, ddof=1)
                                if use_pooled and (nx + ny - 2) > 0:
                                    sp2 = ((nx - 1) * vx + (ny - 1) * vy) / (nx + ny - 2)
                                    sp = np.sqrt(sp2) if sp2 >= 0 else np.nan
                                    return (mx - my) / sp if np.isfinite(sp) and sp != 0 else None
                                else:
                                    s = np.sqrt((vx + vy) / 2.0)
                                    return (mx - my) / s if np.isfinite(s) and s != 0 else None
                            d = cohens_d(a1, a2, use_pooled=equal_var)
                            results['analysis']['t_test'] = {
                                'target': target_col,
                                'group': group_col,
                                'groups': [lbl1, lbl2],
                                'equal_var_assumed': equal_var,
                                'levene_stat': float(lev_stat) if np.isfinite(lev_stat) else None,
                                'levene_p': float(lev_p) if np.isfinite(lev_p) else None,
                                't_stat': float(t_stat) if np.isfinite(t_stat) else None,
                                'p_value': float(t_p) if np.isfinite(t_p) else None,
                                'cohens_d': float(d) if d is not None and np.isfinite(d) else None,
                                'group_means': {lbl1: float(np.mean(a1)), lbl2: float(np.mean(a2))},
                                'group_counts': {lbl1: int(a1.size), lbl2: int(a2.size)},
                            }
                    except Exception as ex:
                        results.setdefault('analysis', {}).setdefault('errors', {})['anova_ttest'] = str(ex)

        # Chi-square (if at least 2 categorical columns)
        if len(categorical_cols) >= 2:
            try:
                cat_a, cat_b = categorical_cols[:2]
                ct = pd.crosstab(df[cat_a], df[cat_b])
                if ct.shape[0] >= 2 and ct.shape[1] >= 2:
                    chi2, p, dof, expected = chi2_contingency(ct)
                    results['analysis']['chi_square'] = {
                        'variables': [cat_a, cat_b],
                        'chi2': float(chi2),
                        'p_value': float(p),
                        'dof': int(dof),
                        'observed': {str(i): {str(j): int(ct.loc[i, j]) for j in ct.columns} for i in ct.index},
                        'expected': {str(i): {str(j): float(expected[idx_i, idx_j]) for idx_j, j in enumerate(ct.columns)} for idx_i, i in enumerate(ct.index)},
                    }
            except Exception as ex:
                results.setdefault('analysis', {}).setdefault('errors', {})['chi_square'] = str(ex)

        # AI insights
        data_summary = f"Dataset with {len(df)} rows, {len(numeric_cols)} numeric columns, {len(categorical_cols)} categorical columns"
        ai_insights = get_ai_analysis(data_summary, goal, target_col, group_col)
        results['ai_insights'] = ai_insights

        return jsonify({'success': True, 'results': results})
    except Exception as e:
        return jsonify({'error': f'Analysis error: {str(e)}'}), 500

@statistical_bp.route('/ai-chat', methods=['POST'])
def ai_chat():
    try:
        data = request.get_json(silent=True) or {}
        message = (data.get('message') or '').strip()
        context = data.get('context') or {}
        if not message:
            return jsonify({'error': 'No message provided'}), 400

        user_message = (f"Context:\n{json.dumps(context, indent=2)}\n\nQuestion:\n{message}"
                        if context else message)

        client = get_claude_client()
        model = os.environ.get("ANTHROPIC_MODEL", "claude-sonnet-4-5-20250929")
        response = client.messages.create(
            model=model,
            max_tokens=800,
            temperature=0.3,
            system=STATISTICIAN_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user_message}],
        )
        return jsonify({'success': True, 'response': (response.content[0].text or "").strip()})
    except Exception as e:
        return jsonify({'error': f'AI chat error: {str(e)}'}), 500

@statistical_bp.route('/execute-action', methods=['POST'])
def execute_action():
    return jsonify({'success': True, 'message': 'Action execution not yet implemented', 'action': (request.get_json(silent=True) or {})})
@statistical_bp.route('/export', methods=['POST'])
def export_results():
    """
    Create a ZIP with CSVs for each available analysis component.
    Payload: { "results": { ... the full 'results' object returned by /comprehensive ... },
               "include": ["descriptive_stats","correlations","group_analysis","anova","t_test","regression","chi_square"] (optional) }
    Response: ZIP file download.
    """
    try:
        j = request.get_json(silent=True) or {}
        results = j.get("results") or {}
        analysis = results.get("analysis") or {}
        include = j.get("include") or ["descriptive_stats","correlations","group_analysis","anova","t_test","regression","chi_square"]

        # Convert dict-like blocks into tabular CSVs and zip them
        mem = io.BytesIO()
        with zipfile.ZipFile(mem, mode="w", compression=zipfile.ZIP_DEFLATED) as zf:

            # Descriptive Stats
            if "descriptive_stats" in include and analysis.get("descriptive_stats"):
                # dict-of-dicts -> DataFrame
                df = pd.DataFrame(analysis["descriptive_stats"])
                zf.writestr("descriptive_stats.csv", df.to_csv(index=True))

            # Correlations
            if "correlations" in include and analysis.get("correlations"):
                df = pd.DataFrame(analysis["correlations"])
                zf.writestr("correlations.csv", df.to_csv(index=True))

            # Group Analysis
            if "group_analysis" in include and analysis.get("group_analysis"):
                # group_analysis has nested dicts for mean/std/count by group
                ga = analysis["group_analysis"]
                # Normalize to rows = groups
                rows = []
                groups = set()
                for stat_name, stat_map in ga.items():
                    groups |= set(stat_map.keys())
                for g in sorted(groups):
                    row = {"group": g}
                    for stat_name, stat_map in ga.items():
                        row[stat_name] = stat_map.get(g)
                    rows.append(row)
                df = pd.DataFrame(rows)
                zf.writestr("group_analysis.csv", df.to_csv(index=False))

            # ANOVA
            if "anova" in include and analysis.get("anova"):
                a = analysis["anova"]
                # summary row
                summary = {
                    "target": a.get("target"),
                    "group": a.get("group"),
                    "k_groups": a.get("k_groups"),
                    "f_stat": a.get("f_stat"),
                    "p_value": a.get("p_value"),
                    "eta_squared": a.get("eta_squared"),
                }
                df_sum = pd.DataFrame([summary])
                zf.writestr("anova_summary.csv", df_sum.to_csv(index=False))
                # per-group stats
                gm = (a.get("group_means") or {})
                gc = (a.get("group_counts") or {})
                rows = [{"group": g, "mean": gm.get(g), "count": gc.get(g)} for g in sorted(set(gm) | set(gc))]
                df_g = pd.DataFrame(rows)
                zf.writestr("anova_groups.csv", df_g.to_csv(index=False))

            # T-Test
            if "t_test" in include and analysis.get("t_test"):
                t = analysis["t_test"]
                summary = {
                    "target": t.get("target"),
                    "group": t.get("group"),
                    "groups": " vs ".join(t.get("groups", [])),
                    "equal_var_assumed": t.get("equal_var_assumed"),
                    "levene_stat": t.get("levene_stat"),
                    "levene_p": t.get("levene_p"),
                    "t_stat": t.get("t_stat"),
                    "p_value": t.get("p_value"),
                    "cohens_d": t.get("cohens_d"),
                }
                df_sum = pd.DataFrame([summary])
                zf.writestr("ttest_summary.csv", df_sum.to_csv(index=False))
                # group means/counts
                gm = (t.get("group_means") or {})
                gc = (t.get("group_counts") or {})
                rows = [{"group": g, "mean": gm.get(g), "count": gc.get(g)} for g in sorted(set(gm) | set(gc))]
                df_g = pd.DataFrame(rows)
                zf.writestr("ttest_groups.csv", df_g.to_csv(index=False))

            # Regression
            if "regression" in include and analysis.get("regression"):
                r = analysis["regression"]
                # coefficients as rows
                coefs = r.get("coefficients") or {}
                rows = [{"predictor": k, "coefficient": v} for k, v in coefs.items()]
                df_coef = pd.DataFrame(rows)
                zf.writestr("regression_coefficients.csv", df_coef.to_csv(index=False))
                df_sum = pd.DataFrame([{
                    "target": r.get("target"),
                    "r2_score": r.get("r2_score"),
                    "intercept": r.get("intercept"),
                    "n_obs": r.get("n_obs"),
                    "predictors": ", ".join(r.get("predictors") or []),
                }])
                zf.writestr("regression_summary.csv", df_sum.to_csv(index=False))

            # Chi-Square (if present)
            if "chi_square" in include and analysis.get("chi_square"):
                c = analysis["chi_square"]
                df_sum = pd.DataFrame([{
                    "chi2": c.get("chi2"),
                    "dof": c.get("dof"),
                    "p_value": c.get("p_value"),
                    "variables": ", ".join(c.get("variables") or []),
                }])
                zf.writestr("chi_square_summary.csv", df_sum.to_csv(index=False))

                # Observed and expected as tables
                obs = pd.DataFrame(c.get("observed") or {}).fillna("")
                exp = pd.DataFrame(c.get("expected") or {}).fillna("")
                zf.writestr("chi_square_observed.csv", obs.to_csv(index=True))
                zf.writestr("chi_square_expected.csv", exp.to_csv(index=True))

        mem.seek(0)
        return send_file(
            mem,
            mimetype="application/zip",
            as_attachment=True,
            download_name="analysis_export.zip"
        )
    except Exception as e:
        current_app.logger.exception("export_failed")
        return jsonify({"error": "export_failed", "details": str(e)}), 500

def _table_from_pairs(pairs):
    """Render a simple two-column HTML table from (key, value) pairs."""
    rows = [
        "<table><thead><tr><th>Field</th><th>Value</th></tr></thead><tbody>"
    ]
    for k, v in pairs:
        rows.append(f"<tr><td>{k}</td><td>{v}</td></tr>")
    rows.append("</tbody></table>")
    return "".join(rows)

@statistical_bp.route('/report', methods=['POST'], endpoint='build_report_html')

def build_report_html():
    """
    Generate an HTML report for the provided results.
    Payload: { "results": {...} }  where results is the object returned by /comprehensive
    """
    try:
        j = request.get_json(silent=True) or {}
        results = j.get("results") or {}
        dataset = results.get("dataset_info") or {}
        analysis = results.get("analysis") or {}
        insights = results.get("ai_insights") or ""

        import pandas as pd

        parts = []
        parts.append("""<!doctype html>
<html>
<head>
<meta charset="utf-8">
<title>Statistical Analysis Report</title>
<style>
body { font-family: system-ui, -apple-system, Segoe UI, Roboto, sans-serif; margin: 24px; color: #111; }
h1,h2,h3 { margin: 0.2em 0; }
h1 { font-size: 22px; }
h2 { font-size: 18px; margin-top: 16px; }
h3 { font-size: 16px; margin-top: 12px; }
table { border-collapse: collapse; width: 100%; margin: 8px 0 16px; }
th, td { border: 1px solid #ddd; padding: 6px 8px; font-size: 13px; }
th { background: #f6f6f6; text-align: left; }
.small { color: #555; font-size: 12px; }
.code { background: #f7f7f7; padding: 8px; border-radius: 4px; border: 1px solid #e5e5e5; white-space: pre-wrap; }
hr { border: none; border-top: 1px solid #eaeaea; margin: 20px 0; }
</style>
</head>
<body>
<h1>Statistical Analysis Report</h1>""")

        parts.append("<h2>Dataset</h2>")
        ds_rows = [
            ("Rows", dataset.get("rows")),
            ("Columns", dataset.get("columns")),
            ("Numeric Columns", ", ".join(dataset.get("numeric_columns") or [])),
            ("Categorical Columns", ", ".join(dataset.get("categorical_columns") or [])),
        ]
        parts.append(_table_from_pairs(ds_rows))

        # Descriptive Stats
        if analysis.get("descriptive_stats"):
            parts.append("<h2>Descriptive Statistics</h2>")
            df = pd.DataFrame(analysis["descriptive_stats"])
            parts.append(df.to_html(index=True, border=0))

        # Correlations
        if analysis.get("correlations"):
            parts.append("<h2>Correlations</h2>")
            df = pd.DataFrame(analysis["correlations"])
            parts.append(df.to_html(index=True, border=0))

        # Group analysis
        if analysis.get("group_analysis"):
            parts.append("<h2>Group Analysis</h2>")
            ga = analysis["group_analysis"]
            groups = set()
            for stat_name, stat_map in ga.items():
                groups |= set((stat_map or {}).keys())
            rows = []
            for g in sorted(groups):
                rows.append({
                    "group": g,
                    "mean": (ga.get("mean") or {}).get(g),
                    "std": (ga.get("std") or {}).get(g),
                    "count": (ga.get("count") or {}).get(g),
                })
            if rows:
                df = pd.DataFrame(rows)
                parts.append(df.to_html(index=False, border=0))

        # ANOVA
        if analysis.get("anova"):
            a = analysis["anova"]
            parts.append("<h2>ANOVA (One-way)</h2>")
            df_sum = pd.DataFrame([{
                "target": a.get("target"),
                "group": a.get("group"),
                "k_groups": a.get("k_groups"),
                "f_stat": a.get("f_stat"),
                "p_value": a.get("p_value"),
                "eta_squared": a.get("eta_squared"),
            }])
            parts.append(df_sum.to_html(index=False, border=0))

        # T-Test
        if analysis.get("t_test"):
            t = analysis["t_test"]
            parts.append("<h2>Two-sample t-test</h2>")
            df_sum = pd.DataFrame([{
                "target": t.get("target"),
                "groups": " vs ".join(t.get("groups") or []),
                "equal_var_assumed": t.get("equal_var_assumed"),
                "t_stat": t.get("t_stat"),
                "p_value": t.get("p_value"),
                "cohens_d": t.get("cohens_d"),
                "levene_p": t.get("levene_p"),
            }])
            parts.append(df_sum.to_html(index=False, border=0))

        # Regression
        if analysis.get("regression"):
            r = analysis["regression"]
            parts.append("<h2>Regression</h2>")
            df_sum = pd.DataFrame([{
                "target": r.get("target"),
                "r2_score": r.get("r2_score"),
                "intercept": r.get("intercept"),
                "n_obs": r.get("n_obs"),
                "predictors": ", ".join(r.get("predictors") or []),
            }])
            parts.append(df_sum.to_html(index=False, border=0))
            coefs = r.get("coefficients") or {}
            df_coef = pd.DataFrame([{"predictor": k, "coefficient": v} for k, v in coefs.items()])
            parts.append(df_coef.to_html(index=False, border=0))

        # Chi-Square
        if analysis.get("chi_square"):
            c = analysis["chi_square"]
            parts.append("<h2>Chi-Square Test</h2>")
            df_sum = pd.DataFrame([{
                "chi2": c.get("chi2"),
                "dof": c.get("dof"),
                "p_value": c.get("p_value"),
                "variables": ", ".join(c.get("variables") or []),
            }])
            parts.append(df_sum.to_html(index=False, border=0))

        # AI Insights
        if insights:
            parts.append("<h2>AI Insights</h2>")
            parts.append(f"<div class='code'>{insights}</div>")

        parts.append("<hr><div class='small'>Generated by Sekki Statistical Analysis API</div>")
        parts.append("</body></html>")
        html = "".join(parts)

        import io
        mem = io.BytesIO(html.encode("utf-8"))
        mem.seek(0)
        return send_file(mem, mimetype="text/html; charset=utf-8",
                         as_attachment=True, download_name="analysis_report.html")
    except Exception as e:
        current_app.logger.exception("report_failed")
        return jsonify({"error": "report_failed", "details": str(e)}), 500
@statistical_bp.route('/test', methods=['GET'])
def test():
    return jsonify({
        'message': 'Statistical Analysis API is working',
        'endpoints': [
            '/upload - POST - Upload data file',
            '/comprehensive - POST - Comprehensive analysis',
            '/ai-chat - POST - AI chat assistance',
            '/execute-action - POST - Execute statistical actions'
        ]
    })
# --- Share endpoints (ephemeral in-memory; swap later for DB if needed) ---
import time, uuid
from flask import abort

# In-memory store survives only while the process runs
_SHARED_RESULTS: dict[str, dict] = {}

@statistical_bp.route('/share', methods=['POST'])
def create_share():
    """
    Accepts: {"results": {...}}
    Returns: {"url": "<app_base>/s/<token>", "token": "<token>"}
    """
    j = request.get_json(silent=True) or {}
    results = j.get("results")
    if results is None:
        return jsonify({"error": "Missing 'results'"}), 400

    token = uuid.uuid4().hex
    _SHARED_RESULTS[token] = {
        "saved_at": int(time.time()),
        "results": results
    }

    # Determine base URL
    base = (os.getenv("SHARE_BASE_URL") or request.url_root).rstrip("/")
    return jsonify({"url": f"{base}/s/{token}", "token": token})

@statistical_bp.route('/share/<token>', methods=['GET'])
def get_share(token: str):
    """
    Returns the saved payload for a token (JSON).
    """
    data = _SHARED_RESULTS.get(token)
    if not data:
        return jsonify({"error": "not_found"}), 404
    return jsonify(data)

# --------- DB-backed Share (persists across devices) ----------
# Uses $DATABASE_URL already present on this server (Postgres)
import json, psycopg

def _get_dsn():
    dsn = os.getenv("DATABASE_URL") or os.getenv("DB_DSN")
    if not dsn:
        raise RuntimeError("DATABASE_URL not configured")
    return dsn

def _ensure_share_table():
    with psycopg.connect(_get_dsn()) as conn, conn.cursor() as cur:
        cur.execute("""
            CREATE TABLE IF NOT EXISTS shared_results (
              token TEXT PRIMARY KEY,
              created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
              payload JSONB NOT NULL
            );
        """)
        conn.commit()

def _share_base_url_from_request():
    return (os.getenv("SHARE_BASE_URL") or request.url_root).rstrip("/")

@statistical_bp.route('/share', methods=['POST'])
def create_share_db():
    """
    Accepts: {"results": {...}}  -> Persists in Postgres
    Returns: {"url": "<app_base>/s/<token>", "token": "<token>"}
    """
    j = request.get_json(silent=True) or {}
    results = j.get("results")
    if results is None:
        return jsonify({"error":"Missing 'results'"}), 400

    token = uuid.uuid4().hex
    payload = {"saved_at": int(time.time()), "results": results}
    try:
        _ensure_share_table()
        with psycopg.connect(_get_dsn()) as conn, conn.cursor() as cur:
            cur.execute(
                "INSERT INTO shared_results (token, payload) VALUES (%s, %s) "
                "ON CONFLICT (token) DO UPDATE SET payload = EXCLUDED.payload",
                (token, json.dumps(payload)),
            )
            conn.commit()
    except Exception as e:
        current_app.logger.exception("share_persist_failed")
        return jsonify({"error":"share_persist_failed","details":str(e)}), 500

    return jsonify({"url": f"{_share_base_url_from_request()}/s/{token}", "token": token})

@statistical_bp.route('/share/<token>', methods=['GET'])
def get_share_db(token: str):
    """Fetch share payload from Postgres; falls back to in-memory if present."""
    try:
        _ensure_share_table()
        with psycopg.connect(_get_dsn()) as conn, conn.cursor() as cur:
            cur.execute("SELECT payload FROM shared_results WHERE token=%s", (token,))
            row = cur.fetchone()
            if row:
                data = row[0] if isinstance(row[0], dict) else json.loads(row[0])
                return jsonify(data)
    except Exception as e:
        current_app.logger.warning("share_fetch_db_failed: %s", e)

    # legacy fallback: in-memory (if process hasn’t restarted)
    try:
        data = _SHARED_RESULTS.get(token)  # type: ignore[name-defined]
        if data:
            return jsonify(data)
    except Exception:
        pass

    return jsonify({"error":"not_found"}), 404
