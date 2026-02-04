"""
app.routes.market_iq_threads

Purpose
  Thread hydration + adoption support for Market IQ.

Why this file exists
  - Stores and returns thread messages (conversation history).
  - Provides thread-level "adoption" controls for selecting a current analysis.
  - Provides a bundle endpoint that hydrates the UI with messages + analyses + scenarios.

Routing contract (IMPORTANT)
  - app/__init__.py currently registers this blueprint WITHOUT a url_prefix.
  - Therefore THIS blueprint MUST own url_prefix="/api/market-iq" to preserve
    the frontend contract (/api/market-iq/...).
"""

from datetime import datetime, timezone

from flask import Blueprint, request, jsonify, current_app
from flask_jwt_extended import jwt_required, get_jwt_identity
from sqlalchemy import desc

from app import db
from app.models import (
    MiqMessage,
    MiqAnalysis,
    MiqScenario,
    MiqThread,
    MiqThreadAnalysisLink,
)

# ---------------------------------------------------------------------------
# Blueprint (url_prefix owned here due to create_app wiring)
# ---------------------------------------------------------------------------

market_iq_threads_bp = Blueprint("market_iq_threads", __name__, url_prefix="/api/market-iq")


# ---------------------------------------------------------------------------
# Small helpers (formatting + safe ints)
# ---------------------------------------------------------------------------

def _iso(dt):
    try:
        return dt.isoformat()
    except Exception:
        return str(dt)


def _limit_int(v, default, min_v=1, max_v=500):
    try:
        n = int(v)
    except Exception:
        return default
    return max(min_v, min(max_v, n))


# ---------------------------------------------------------------------------
# Analysis selection helpers
# ---------------------------------------------------------------------------

def _latest_analysis(thread_id: str):
    return (
        MiqAnalysis.query
        .filter_by(thread_id=thread_id)
        .order_by(desc(MiqAnalysis.created_at))
        .first()
    )


def _latest_baseline_analysis(thread_id: str):
    """
    Baseline analysis = an analysis not derived from a scenario.
    Best-effort: if the column isn't present or a query fails, fall back to scanning.
    """
    try:
        return (
            MiqAnalysis.query
            .filter_by(thread_id=thread_id)
            .filter(MiqAnalysis.derived_from_scenario_id.is_(None))
            .order_by(desc(MiqAnalysis.created_at))
            .first()
        )
    except Exception:
        try:
            db.session.rollback()
        except Exception:
            pass

        try:
            rows = (
                MiqAnalysis.query
                .filter_by(thread_id=thread_id)
                .order_by(desc(MiqAnalysis.created_at))
                .limit(200)
                .all()
            )
            for r in rows:
                if not getattr(r, "derived_from_scenario_id", None):
                    return r
        except Exception:
            try:
                db.session.rollback()
            except Exception:
                pass
            return None

    return None


def _resolve_current_analysis(thread_id: str):
    """
    Hydration behavior:
      - If the thread explicitly adopted an analysis -> that is current.
      - Otherwise -> fall back to latest analysis (so the UI can hydrate without requiring adoption).

    Returns:
      (analysis_row_or_none, adopted_analysis_id_or_none)
    """
    thread = MiqThread.query.filter_by(thread_id=thread_id).first()
    adopted_analysis_id = thread.adopted_analysis_id if thread else None

    if adopted_analysis_id:
        adopted_row = MiqAnalysis.query.filter_by(analysis_id=adopted_analysis_id).first()
        if adopted_row:
            return adopted_row, adopted_analysis_id
        # If the adopted pointer is stale, treat as not adopted and fall back.
        adopted_analysis_id = None

    latest_row = _latest_analysis(thread_id)
    if not latest_row:
        return None, None

    return latest_row, None


def _scenario_to_dict(row: MiqScenario, adopted_analysis_id=None, derived_map=None):
    meta = row.meta if isinstance(row.meta, dict) else {}
    derived_id = row.derived_analysis_id or meta.get("derived_analysis_id")
    adopted = (derived_id == adopted_analysis_id) if adopted_analysis_id else False

    result = row.result
    if result and not result.get("inputs"):
        result["inputs"] = result.get("compat", {}) or {}

    scorecard = None
    if derived_map and derived_id:
        scorecard = derived_map.get(derived_id)
        if scorecard and not scorecard.get("inputs"):
            scorecard["inputs"] = scorecard.get("compat", {}) or {}

    return {
        "scenario_id": row.scenario_id,
        "thread_id": row.thread_id,
        "session_id": row.session_id,
        "based_on": row.based_on,
        "deltas": row.deltas or {},
        "result": result,
        "scorecard": scorecard,
        "label": row.label,
        "meta": meta,
        "adopted": adopted,
        "derived_analysis_id": derived_id,
        "created_at": _iso(row.created_at),
    }


# ---------------------------------------------------------------------------
# Routes: messages (create/list)
# ---------------------------------------------------------------------------

@market_iq_threads_bp.route("/threads/<thread_id>/messages", methods=["POST"])
def create_thread_message(thread_id):
    try:
        pld = request.get_json(silent=True) or {}
        role = (pld.get("role") or "user").strip().lower()
        if role not in ("user", "assistant", "system"):
            return jsonify({"error": "invalid_role"}), 400

        content = pld.get("content")
        if content is None:
            return jsonify({"error": "invalid_content"}), 400

        now = datetime.now(timezone.utc)
        msg = MiqMessage(thread_id=thread_id, role=role, content=content, created_at=now)
        db.session.add(msg)
        db.session.commit()

        return jsonify(
            {
                "message": {
                    "id": msg.id,
                    "thread_id": msg.thread_id,
                    "role": msg.role,
                    "content": msg.content,
                    "created_at": msg.created_at.isoformat(),
                }
            }
        ), 201

    except Exception as e:
        current_app.logger.exception("create_thread_message failed")
        db.session.rollback()
        return jsonify({"error": "internal_error", "detail": str(e)}), 500


@market_iq_threads_bp.get("/threads/<thread_id>/messages")
def list_thread_messages(thread_id: str):
    try:
        lim = _limit_int(request.args.get("limit"), 50, 1, 500)
        rows = (
            MiqMessage.query
            .filter_by(thread_id=thread_id)
            .order_by(desc(MiqMessage.created_at))
            .limit(lim)
            .all()
        )
        rows = list(reversed(rows))
        return jsonify(
            {
                "thread_id": thread_id,
                "messages": [
                    {
                        "id": r.id,
                        "thread_id": r.thread_id,
                        "role": r.role,
                        "content": r.content,
                        "meta": getattr(r, "meta", None),
                        "created_at": _iso(r.created_at),
                    }
                    for r in rows
                ],
            }
        ), 200
    except Exception as e:
        current_app.logger.exception("list_thread_messages failed")
        return jsonify({"error": "internal_error", "detail": str(e)}), 500


# ---------------------------------------------------------------------------
# Routes: attach/adopt analysis
# ---------------------------------------------------------------------------

@market_iq_threads_bp.route("/threads/<thread_id>/attach-analysis", methods=["POST"])
@jwt_required(optional=True)
def attach_analysis_to_thread(thread_id):
    user_id = get_jwt_identity()
    payload = request.get_json(silent=True) or {}
    analysis_id = payload.get("analysis_id")
    if not analysis_id:
        return jsonify({"error": "missing_analysis_id"}), 400

    thread = MiqThread.query.filter_by(thread_id=thread_id).first()
    if not thread:
        return jsonify({"error": "thread_not_found"}), 404

    analysis = MiqAnalysis.query.filter_by(analysis_id=analysis_id).first()
    if not analysis:
        return jsonify({"error": "analysis_not_found"}), 404

    # Ownership scope: if thread.user_id is set, require matching logged-in user.
    # (MiqAnalysis has no user_id column, so we cannot enforce ownership on the analysis row yet.)
    if thread.user_id:
        if not user_id or str(user_id) != str(thread.user_id):
            return jsonify({"error": "forbidden"}), 403
    else:
        if not thread.session_id or analysis.session_id != thread.session_id:
            return jsonify({"error": "forbidden"}), 403

    if analysis.thread_id == thread_id:
        return jsonify({"ok": True, "already_in_thread": True}), 200

    try:
        existing = MiqThreadAnalysisLink.query.filter_by(thread_key=thread_id, analysis_key=analysis_id).first()
    except Exception:
        # Table may not exist yet; don't hard-fail attach
        try:
            db.session.rollback()
        except Exception:
            pass
        return jsonify({"error": "thread_links_table_missing"}), 409

    if existing:
        return jsonify({"ok": True, "already_attached": True}), 200

    link = MiqThreadAnalysisLink(
        thread_key=thread_id,
        analysis_key=analysis_id,
        attached_by_user_id=(user_id or thread.user_id),
        attached_by_session_id=thread.session_id,
    )
    db.session.add(link)
    db.session.commit()
    return jsonify({"ok": True}), 200


@market_iq_threads_bp.route("/threads/<thread_id>/adopt-analysis", methods=["POST"])
@jwt_required(optional=True)
def adopt_analysis_for_thread(thread_id):
    user_id = get_jwt_identity()
    payload = request.get_json(silent=True) or {}
    analysis_id = payload.get("analysis_id")
    if not analysis_id:
        return jsonify({"error": "missing_analysis_id"}), 400

    thread = MiqThread.query.filter_by(thread_id=thread_id).first()
    if not thread:
        return jsonify({"error": "thread_not_found"}), 404

    analysis = MiqAnalysis.query.filter_by(analysis_id=analysis_id).first()
    if not analysis:
        return jsonify({"error": "analysis_not_found"}), 404

    if thread.user_id:
        if not user_id or str(user_id) != str(thread.user_id):
            return jsonify({"error": "forbidden"}), 403
    else:
        if not thread.session_id or analysis.session_id != thread.session_id:
            return jsonify({"error": "forbidden"}), 403

    # Ensure attached if it isn't directly on the thread
    if analysis.thread_id != thread_id:
        try:
            existing = MiqThreadAnalysisLink.query.filter_by(thread_key=thread_id, analysis_key=analysis_id).first()
        except Exception:
            try:
                db.session.rollback()
            except Exception:
                pass
            return jsonify({"error": "thread_links_table_missing"}), 409

        if not existing:
            db.session.add(
                MiqThreadAnalysisLink(
                    thread_key=thread_id,
                    analysis_key=analysis_id,
                    attached_by_user_id=(user_id or thread.user_id),
                    attached_by_session_id=thread.session_id,
                )
            )

    thread.adopted_analysis_id = analysis_id
    db.session.add(thread)
    db.session.commit()

    result = analysis.result or {}
    if result and not result.get("inputs"):
        result["inputs"] = result.get("compat", {}) or result.get("analysis_result", {}).get("inputs", {})

    return jsonify({
        "ok": True,
        "adopted_analysis_id": analysis_id,
        "analysis_id": analysis_id,
        "analysis_result": result,
    }), 200


@market_iq_threads_bp.route("/threads/<thread_id>/adopt", methods=["PUT"])
@jwt_required(optional=True)
def adopt_scorecard(thread_id: str):
    """
    Adopt a scenario scorecard as the current scorecard for this thread.
    Updates thread metadata to persist the adoption.
    """
    try:
        user_id = get_jwt_identity()
        data = request.get_json(silent=True) or {}
        scorecard_id = data.get("scorecard_id")

        if not scorecard_id:
            return jsonify({"error": "scorecard_id required"}), 400

        thread = MiqThread.query.filter_by(thread_id=thread_id).first()
        if not thread:
            return jsonify({"error": "thread_not_found"}), 404

        analysis = MiqAnalysis.query.filter_by(analysis_id=scorecard_id).first()
        if not analysis:
            return jsonify({"error": "scorecard_not_found"}), 404

        # Ownership scope
        if thread.user_id:
            if not user_id or str(user_id) != str(thread.user_id):
                return jsonify({"error": "forbidden"}), 403
        else:
            if not thread.session_id or analysis.session_id != thread.session_id:
                return jsonify({"error": "forbidden"}), 403

        # Ensure attached if it isn't directly on the thread
        if analysis.thread_id != thread_id:
            try:
                existing = MiqThreadAnalysisLink.query.filter_by(thread_key=thread_id, analysis_key=scorecard_id).first()
            except Exception:
                try:
                    db.session.rollback()
                except Exception:
                    pass
                return jsonify({"error": "thread_links_table_missing"}), 409

            if not existing:
                db.session.add(
                    MiqThreadAnalysisLink(
                        thread_key=thread_id,
                        analysis_key=scorecard_id,
                        attached_by_user_id=(user_id or thread.user_id),
                        attached_by_session_id=thread.session_id,
                    )
                )

        # Persist adoption in thread meta and adopted_analysis_id
        adopted_at = datetime.now(timezone.utc).isoformat()
        thread_meta = thread.meta or {}
        thread_meta["current_scorecard_id"] = scorecard_id
        thread_meta["adopted_at"] = adopted_at

        snapshots = thread_meta.get("scorecard_snapshots", [])
        label = (
            (analysis.meta or {}).get("label")
            or (analysis.result or {}).get("label")
            or (analysis.result or {}).get("project_name")
            or "Adopted Scenario"
        )
        if not any(s.get("id") == scorecard_id for s in snapshots if isinstance(s, dict)):
            snapshots.append({
                "id": scorecard_id,
                "label": label,
                "adopted_at": adopted_at,
            })
        thread_meta["scorecard_snapshots"] = snapshots

        thread.meta = thread_meta
        thread.adopted_analysis_id = scorecard_id
        db.session.add(thread)
        db.session.commit()

        result = analysis.result or {}
        if result and not result.get("inputs"):
            result["inputs"] = result.get("compat", {}) or result.get("analysis_result", {}).get("inputs", {})

        return jsonify({
            "success": True,
            "thread_id": thread_id,
            "current_scorecard_id": scorecard_id,
            "analysis_id": scorecard_id,
            "analysis_result": result,
        }), 200

    except Exception as e:
        db.session.rollback()
        current_app.logger.exception("adopt_scorecard failed")
        return jsonify({"error": "server_error", "detail": str(e)}), 500


# ---------------------------------------------------------------------------
# Route: thread bundle hydration (SINGLE OWNER)
# ---------------------------------------------------------------------------

@market_iq_threads_bp.get("/threads/<thread_id>/bundle")
def get_thread_bundle(thread_id: str):
    """
    Hydration bundle used by the frontend.
    Returns:
      - messages
      - scenarios
      - baseline/latest/current analysis payloads
      - analysis_history (thread + attached + session)
      - back-compat fields analysis_id / analysis_result
    """
    try:
        try:
            db.session.rollback()
        except Exception:
            pass

        msg_limit = _limit_int(request.args.get("msg_limit"), 50, 1, 500)
        scn_limit = _limit_int(request.args.get("scn_limit"), 50, 1, 200)

        msg_rows = (
            MiqMessage.query
            .filter_by(thread_id=thread_id)
            .order_by(desc(MiqMessage.created_at))
            .limit(msg_limit)
            .all()
        )
        msg_rows = list(reversed(msg_rows))

        baseline_row = _latest_baseline_analysis(thread_id)
        latest_row = _latest_analysis(thread_id)
        current_row, adopted_analysis_id = _resolve_current_analysis(thread_id)

        def _analysis_payload(row):
            if not row:
                return None
            result = (getattr(row, "analysis_result", None) or row.result or {})
            if not result.get("inputs"):
                result["inputs"] = result.get("compat", {}) or result.get("analysis_result", {}).get("inputs", {})
            return {
                "analysis_id": getattr(row, "analysis_id", None),
                "thread_id": getattr(row, "thread_id", None),
                "result": result,
                "meta": getattr(row, "meta", None),
                "created_at": _iso(getattr(row, "created_at", None)),
            }

        baseline_payload = _analysis_payload(baseline_row)
        latest_payload = _analysis_payload(latest_row)
        current_payload = _analysis_payload(current_row)

        thread_obj = MiqThread.query.filter_by(thread_id=thread_id).first()
        thread_session_id = getattr(thread_obj, "session_id", None) if thread_obj else None
        thread_meta = getattr(thread_obj, "meta", None) if thread_obj else None
        if not isinstance(thread_meta, dict):
            thread_meta = {}

        current_scorecard_id = thread_meta.get("current_scorecard_id")
        current_scorecard = None
        if current_scorecard_id:
            current_analysis = MiqAnalysis.query.filter_by(analysis_id=current_scorecard_id).first()
            if current_analysis and current_analysis.result:
                current_scorecard = current_analysis.result
                if not current_scorecard.get("inputs"):
                    current_scorecard["inputs"] = current_scorecard.get("compat", {}) or current_scorecard.get("analysis_result", {}).get("inputs", {})

        if not current_scorecard and latest_row and latest_row.result:
            current_scorecard = latest_row.result
            if not current_scorecard.get("inputs"):
                current_scorecard["inputs"] = current_scorecard.get("compat", {}) or current_scorecard.get("analysis_result", {}).get("inputs", {})

        first_analysis = (
            MiqAnalysis.query
            .filter_by(thread_id=thread_id)
            .order_by(MiqAnalysis.created_at.asc())
            .first()
        )
        baseline_scorecard = None
        if first_analysis and first_analysis.result:
            baseline_scorecard = first_analysis.result
            if not baseline_scorecard.get("inputs"):
                baseline_scorecard["inputs"] = baseline_scorecard.get("compat", {}) or baseline_scorecard.get("analysis_result", {}).get("inputs", {})

        thread_rows = (
            MiqAnalysis.query
            .filter(MiqAnalysis.thread_id == thread_id)
            .order_by(MiqAnalysis.created_at.desc())
            .all()
        )

        # Attached analyses: if table doesn't exist yet, treat as empty (do not 500)
        attached_ids = []
        try:
            attached_ids = [
                l.analysis_key
                for l in (
                    MiqThreadAnalysisLink.query
                    .filter(MiqThreadAnalysisLink.thread_key == thread_id)
                    .order_by(MiqThreadAnalysisLink.created_at.desc())
                    .all()
                )
            ]
        except Exception:
            try:
                db.session.rollback()
            except Exception:
                pass
            attached_ids = []

        attached_rows = []
        if attached_ids:
            attached_rows = (
                MiqAnalysis.query
                .filter(MiqAnalysis.analysis_id.in_(attached_ids))
                .order_by(MiqAnalysis.created_at.desc())
                .all()
            )

        session_rows = []
        if thread_session_id:
            session_rows = (
                MiqAnalysis.query
                .filter(MiqAnalysis.session_id == thread_session_id)
                .filter(MiqAnalysis.thread_id.is_(None))
                .order_by(MiqAnalysis.created_at.desc())
                .all()
            )

        def _hist_row(a, assoc: str, source_thread_id=None):
            p = _analysis_payload(a)
            if not p:
                return None
            p["association"] = assoc
            if source_thread_id:
                p["source_thread_id"] = source_thread_id
            return p

        seen = set()
        analysis_history = []

        for a in thread_rows:
            if a.analysis_id in seen:
                continue
            seen.add(a.analysis_id)
            analysis_history.append(_hist_row(a, "thread"))

        for a in attached_rows:
            if a.analysis_id in seen:
                continue
            seen.add(a.analysis_id)
            analysis_history.append(_hist_row(a, "attached", source_thread_id=a.thread_id))

        for a in session_rows:
            if a.analysis_id in seen:
                continue
            seen.add(a.analysis_id)
            analysis_history.append(_hist_row(a, "session"))

        analysis_history = [x for x in analysis_history if x]

        scn_rows = (
            MiqScenario.query
            .filter_by(thread_id=thread_id)
            .order_by(desc(MiqScenario.created_at))
            .limit(scn_limit)
            .all()
        )

        derived_ids = []
        for r in scn_rows:
            meta = r.meta if isinstance(r.meta, dict) else {}
            derived_id = r.derived_analysis_id or meta.get("derived_analysis_id")
            if derived_id:
                derived_ids.append(derived_id)

        derived_map = {}
        if derived_ids:
            rows = (
                MiqAnalysis.query
                .filter(MiqAnalysis.analysis_id.in_(list(set(derived_ids))))
                .all()
            )
            for r in rows:
                res = r.result or {}
                if res and not res.get("inputs"):
                    res["inputs"] = res.get("compat", {}) or res.get("analysis_result", {}).get("inputs", {})
                derived_map[r.analysis_id] = res

        def _build_scenario_levers(scorecard: dict | None):
            if not scorecard:
                return []

            compat = scorecard.get("compat") or {}
            inputs = scorecard.get("inputs") or {}

            if not isinstance(compat, dict):
                compat = {}
            if not isinstance(inputs, dict):
                inputs = {}

            def _infer_type(key: str) -> str:
                lk = key.lower()
                if any(s in lk for s in ("budget", "revenue", "price", "cost", "arr", "mrr")):
                    return "currency"
                if any(s in lk for s in ("margin", "percent", "rate")):
                    return "percentage"
                if any(s in lk for s in ("month", "timeline", "duration")):
                    return "months"
                return "number"

            levers = []
            source = {}
            source.update(compat)
            source.update({k: v for k, v in inputs.items() if k not in source})

            for k, v in source.items():
                if not isinstance(v, (int, float)):
                    continue
                typ = _infer_type(str(k))
                label = str(k).replace("_", " ").title()
                payload = {
                    "key": k,
                    "label": label,
                    "current": v,
                    "type": typ,
                }
                if typ == "percentage":
                    payload["display_multiplier"] = 100
                levers.append(payload)

            return levers

        scenario_levers_source = (
            (baseline_payload or {}).get("result")
            or (current_payload or {}).get("result")
            or (latest_payload or {}).get("result")
        )

        scenario_levers = thread_meta.get("scenario_levers")
        if not isinstance(scenario_levers, list):
            scenario_levers = _build_scenario_levers(scenario_levers_source)

        return jsonify(
            {
                "thread_id": thread_id,
                "messages": [
                    {
                        "id": r.id,
                        "thread_id": r.thread_id,
                        "role": r.role,
                        "content": r.content,
                        "meta": getattr(r, "meta", None),
                        "created_at": _iso(r.created_at),
                    }
                    for r in msg_rows
                ],
                "scenarios": [_scenario_to_dict(r, adopted_analysis_id, derived_map) for r in scn_rows],

                "baseline_analysis": baseline_payload,
                "baseline_analysis_id": (baseline_payload or {}).get("analysis_id"),
                "baseline_scorecard": baseline_scorecard or (baseline_payload or {}).get("result"),

                "latest_analysis": latest_payload,
                "latest_analysis_id": (latest_payload or {}).get("analysis_id"),

                "current_analysis": current_payload,
                "current_analysis_id": (current_payload or {}).get("analysis_id"),
                "current_scorecard": current_scorecard or (current_payload or {}).get("result"),
                "current_scorecard_id": current_scorecard_id or (current_payload or {}).get("analysis_id"),

                "scenario_levers": scenario_levers,

                "analysis_history": analysis_history,
                "adopted_analysis_id": adopted_analysis_id,

                # Back-compat
                "analysis_id": (current_payload or {}).get("analysis_id"),
                "analysis_result": (current_payload or {}).get("result"),
            }
        ), 200

    except Exception as e:
        current_app.logger.exception("get_thread_bundle failed")
        try:
            db.session.rollback()
        except Exception:
            pass
        return jsonify({"error": "internal_error", "detail": str(e)}), 500
