from __future__ import annotations
import io, csv, json
from flask import Blueprint, request, Response, jsonify
from flask_jwt_extended import jwt_required

export_bp = Blueprint("export", __name__, url_prefix="/api")

@export_bp.post("/export/analysis.csv")
@jwt_required(optional=True)
def export_csv():
    """POST body: { analysis_result: {...} } -> returns CSV attachment."""
    p = request.get_json(silent=True) or {}
    a = p.get("analysis_result") or {}
    if not isinstance(a, dict) or not a:
        return jsonify({"error":"analysis_result_required"}), 400

    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["field","value"])

    # top-level
    for k in ("project_name","market_iq_score","summary"):
        if k in a: w.writerow([k, a.get(k)])

    # components
    comps = a.get("component_scores") or {}
    for k,v in comps.items():
        w.writerow([f"component_scores.{k}", v])

    # financial impact
    fin = a.get("financial_impact") or {}
    for k,v in fin.items():
        w.writerow([f"financial_impact.{k}", v])

    # deterministic calc (if attached)
    calc = a.get("_calc") or {}
    metrics = calc.get("metrics") or {}
    for mk, mv in metrics.items():
        val = (mv or {}).get("value")
        w.writerow([f"_calc.metrics.{mk}", val])

    # raw (optional, compact)
    w.writerow(["_raw_json", json.dumps(a, separators=(",",":"))[:4000]])

    data = buf.getvalue()
    return Response(
        data,
        200,
        headers={
            "Content-Type":"text/csv; charset=utf-8",
            "Content-Disposition": 'attachment; filename="analysis.csv"',
        }
    )
