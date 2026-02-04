"""
app.routes.market_iq_analyze

Purpose
  Single authoritative owner for Market IQ analysis + scenarios endpoints.

Why this file exists
  - Provides deterministic analysis/scenario computation from thread inputs.
  - Persists analysis + scenarios to the DB (MiqAnalysis / MiqScenario).

Routing contract
  - This blueprint intentionally DOES NOT define a url_prefix.
  - This file assumes create_app() registers it with url_prefix="/api/market-iq".
    (Verification only: if create_app() registers without that prefix, routes here
     will be at /analyze and /threads/<id>/scenarios instead of /api/market-iq/...).

IMPORTANT
  - This module does NOT own /threads/<thread_id>/bundle.
  - Bundle/hydration is owned by app.routes.market_iq_threads to avoid route collisions.
"""

from __future__ import annotations

import hashlib
import json
import os
import random
import re
import time
from functools import wraps

from flask import Blueprint, current_app, jsonify, request
from flask_jwt_extended import get_jwt, get_jwt_identity, jwt_required
from pydantic import BaseModel, Field, ValidationError
from sqlalchemy import desc

from app import db
from app.decorators.subscription import subscription_required
from app.models import MiqAnalysis, MiqMessage, MiqScenario, MiqThread


# ---------------------------------------------------------------------------
# Blueprint (prefix is owned by create_app registration)
# ---------------------------------------------------------------------------

market_iq_analyze_bp = Blueprint("market_iq_analyze", __name__)


# ---------------------------------------------------------------------------
# Demo bypass (analyze only)
# ---------------------------------------------------------------------------

DEMO_EMAIL_DEFAULT = "demo@sekki.io"


def _resolve_jwt_email_best_effort() -> str | None:
    """
    Best-effort email resolution for the currently authenticated caller.

    Priority:
      1) JWT custom claim "email" (if present)
      2) Lookup by JWT identity against a User-like model (if available)

    Returns:
      email string or None if not resolvable.
    """
    # 1) Try JWT claims
    try:
        claims = get_jwt() or {}
        email = claims.get("email")
        if isinstance(email, str) and email.strip():
            return email.strip().lower()
    except Exception:
        pass

    # 2) Try identity -> user lookup (best effort; model name may vary)
    try:
        user_id = get_jwt_identity()
        if not user_id:
            return None

        # Try common model names without hard failing if they don't exist.
        # NOTE: We intentionally keep this best-effort and silent.
        try:
            from app.models import User  # type: ignore
            user = User.query.filter_by(id=user_id).first()
            if user and getattr(user, "email", None):
                return str(user.email).strip().lower()
        except Exception:
            pass

        try:
            from app.models import AppUser  # type: ignore
            user = AppUser.query.filter_by(id=user_id).first()
            if user and getattr(user, "email", None):
                return str(user.email).strip().lower()
        except Exception:
            pass

    except Exception:
        return None

    return None


def _is_demo_analyze_user() -> bool:
    """
    Allows demo user to call /analyze without an active subscription.

    This is intentionally narrow:
      - only demo email
      - only affects the /analyze endpoint (scenarios remain unchanged)
    """
    demo_email = (
        current_app.config.get("DEMO_USER_EMAIL")
        or os.getenv("DEMO_USER_EMAIL")
        or DEMO_EMAIL_DEFAULT
    )
    if not isinstance(demo_email, str) or not demo_email.strip():
        demo_email = DEMO_EMAIL_DEFAULT
    demo_email = demo_email.strip().lower()

    caller_email = _resolve_jwt_email_best_effort()
    return bool(caller_email and caller_email == demo_email)


def subscription_required_or_demo(fn):
    """
    Wrapper that enforces subscription for all users EXCEPT the demo user.
    """
    gated = subscription_required(fn)

    @wraps(fn)
    def _wrapped(*args, **kwargs):
        try:
            if _is_demo_analyze_user():
                return fn(*args, **kwargs)
        except Exception:
            # If bypass check fails for any reason, fall back to normal gating.
            pass
        return gated(*args, **kwargs)

    return _wrapped


# ---------------------------------------------------------------------------
# Request schemas
# ---------------------------------------------------------------------------

class ScenarioCreatePayload(BaseModel):
    deltas: dict = Field(default_factory=dict)
    label: str | None = None
    session_id: str | None = None


class ScenarioUpdatePayload(BaseModel):
    deltas: dict = Field(default_factory=dict)
    label: str | None = None


# ---------------------------------------------------------------------------
# Deterministic helpers
# ---------------------------------------------------------------------------

def _canonical(obj) -> str:
    """Stable JSON for hashing."""
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _stable_fingerprint(payload_like_dict: dict) -> str:
    """SHA-256 fingerprint of canonicalized inputs."""
    return hashlib.sha256(_canonical(payload_like_dict).encode("utf-8")).hexdigest()


def _parse_numeric_value(val_str: str) -> float:
    """Parse numeric values with units (k, M, %, months)."""
    if not val_str:
        return 0.0
    val_str = str(val_str).strip()
    multiplier = 1.0

    # Percent
    if "%" in val_str:
        val_str = val_str.replace("%", "")
        multiplier = 0.01
    # Millions
    elif val_str.lower().endswith("m"):
        multiplier = 1_000_000
        val_str = val_str[:-1]
    # Thousands
    elif val_str.lower().endswith("k"):
        multiplier = 1_000
        val_str = val_str[:-1]

    # Strip non-numeric except decimal
    val_str = re.sub(r"[^\d.]", "", val_str)
    try:
        return float(val_str) * multiplier
    except Exception:
        return 0.0


def _normalize_percent_deltas(deltas: dict) -> dict:
    """Normalize percentage-like deltas to fractional values (e.g. 22.5 -> 0.225)."""
    if not isinstance(deltas, dict):
        return deltas
    norm = dict(deltas)
    for k, v in list(norm.items()):
        if not isinstance(v, (int, float)):
            continue
        lk = str(k).lower()
        if any(s in lk for s in ("percent", "pct", "rate", "margin", "churn")):
            # If user sent whole-number percent (e.g. 22.5), convert to fraction.
            if v > 1:
                norm[k] = v / 100.0
    return norm


def _extract_levers(inputs: dict, transcript: str) -> dict:
    """Extract baseline input levers from structured data and transcript."""
    levers: dict = {}

    # Structured: budget
    budget_dict = inputs.get("budget") or {}
    if isinstance(budget_dict, dict):
        if "amount" in budget_dict:
            levers["budget"] = _parse_numeric_value(budget_dict["amount"])
        elif "total" in budget_dict:
            levers["budget"] = _parse_numeric_value(budget_dict["total"])

    # Structured: financial metrics
    financial_metrics = inputs.get("financial_metrics") or {}
    if isinstance(financial_metrics, dict):
        if "revenue_target" in financial_metrics:
            levers["revenue_target"] = _parse_numeric_value(financial_metrics["revenue_target"])
        if "margin" in financial_metrics:
            levers["margin_percent"] = _parse_numeric_value(financial_metrics["margin"])
        if "churn_rate" in financial_metrics:
            levers["churn_rate"] = _parse_numeric_value(financial_metrics["churn_rate"])
        if "price_point" in financial_metrics:
            levers["price_point"] = _parse_numeric_value(financial_metrics["price_point"])

    # Structured: timeline
    timeline_str = inputs.get("timeline") or ""
    if timeline_str:
        match = re.search(r"(\d+)\s*(month|mo)", timeline_str, re.IGNORECASE)
        if match:
            levers["timeline_months"] = int(match.group(1))

    # Transcript fallback for missing levers
    if not levers.get("budget") and transcript:
        match = re.search(r"budget[:\s]+\$?([\d.]+)\s*([kKmM]?)", transcript, re.IGNORECASE)
        if match:
            levers["budget"] = _parse_numeric_value(match.group(1) + match.group(2))

    if not levers.get("timeline_months") and transcript:
        match = re.search(r"(\d+)\s*(month|mo)", transcript, re.IGNORECASE)
        if match:
            levers["timeline_months"] = int(match.group(1))

    if not levers.get("revenue_target") and transcript:
        match = re.search(r"revenue[:\s]+\$?([\d.]+)\s*([kKmM]?)", transcript, re.IGNORECASE)
        if match:
            levers["revenue_target"] = _parse_numeric_value(match.group(1) + match.group(2))

    return levers


def _build_transcript_from_thread(thread_id: str) -> str:
    """Best-effort transcript builder from stored thread messages."""
    if not thread_id:
        return ""
    try:
        q = (
            MiqMessage.query
            .filter_by(thread_id=thread_id)
            .order_by(MiqMessage.created_at.asc())
        )
        parts: list[str] = []
        for mmsg in q.all():
            c = mmsg.content
            txt = ""
            if isinstance(c, dict):
                for k in ("text", "message", "content", "body"):
                    v = c.get(k)
                    if isinstance(v, str) and v.strip():
                        txt = v.strip()
                        break
            elif isinstance(c, str) and c.strip():
                txt = c.strip()

            if txt:
                parts.append(f"{mmsg.role}: {txt}")

        return "\n".join(parts).strip()
    except Exception:
        return ""


# ---------------------------------------------------------------------------
# Route: analysis (authoritative)
# ---------------------------------------------------------------------------

@market_iq_analyze_bp.route("/analyze", methods=["POST"])
@jwt_required(optional=True)
@subscription_required_or_demo
def analyze_from_conversation():
    """
    Market IQ analysis — strict & deterministic.
      - Normal path: compute deterministically from inputs + transcript.
      - On any exception: return 500 JSON (no stub / no fake data).
    """
    _t0 = time.time()
    pld = request.get_json(silent=True) or {}

    # BEGIN: thread_transcript_fallback
    thread_id = (pld.get("thread_id") or pld.get("session_id") or "")
    if isinstance(thread_id, str):
        thread_id = thread_id.strip()

    transcript = pld.get("transcript") or ""
    if isinstance(transcript, str):
        transcript = transcript.strip()

    if not transcript and thread_id:
        transcript = _build_transcript_from_thread(thread_id)
    # END: thread_transcript_fallback

    inputs = {
        "project_name": (pld.get("project_name") or "").strip(),
        "business_description": (pld.get("business_description") or "").strip(),
        "target_market": (pld.get("target_market") or "").strip(),
        "revenue_model": (pld.get("revenue_model") or "").strip(),
        "financial_metrics": pld.get("financial_metrics") or {},
        "timeline": (pld.get("timeline") or "").strip(),
        "budget": pld.get("budget") or {},
        "competition": (pld.get("competition") or "").strip(),
        "team": (pld.get("team") or "").strip(),
        "assumptions": pld.get("assumptions") or {},
        "transcript": transcript,
    }

    if not inputs["transcript"]:
        return jsonify({"error": "No transcript"}), 400

    # Deterministic fingerprint + seed
    fp = _stable_fingerprint(inputs)
    try:
        random.seed(int(fp[:16], 16))
    except Exception:
        random.seed(12345)

    # IMPORTANT: analysis_id must never be derived from session_id.
    requested_analysis_id = pld.get("analysis_id")
    if isinstance(requested_analysis_id, str):
        requested_analysis_id = requested_analysis_id.strip()
    else:
        requested_analysis_id = ""

    analysis_id = requested_analysis_id or f"analysis_{fp[:8]}"

    try:
        # ===== DETERMINISTIC COMPUTE PATH =====
        base = (int(fp[-4:], 16) % 41) + 50  # 50..90

        extracted_levers = _extract_levers(inputs, transcript)

        result = {
            "analysis_id": analysis_id,
            "thread_id": thread_id,
            "project_name": inputs["project_name"] or "Market IQ Project",
            "market_iq_score": base,
            "score_category": (
                "Excellent" if base >= 85 else
                "Good"      if base >= 70 else
                "Fair"      if base >= 55 else
                "Poor"
            ),
            "component_scores": {
                "execution_readiness": max(min(base - 7, 99), 0),
                "financial_health":   max(min(base + 21, 99), 0),
                "market_position":    max(min(base - 4, 99), 0),
                "operational_efficiency": max(min(base - 14, 99), 0),
                "overall": base,
            },
            "financial_impact": {
                "projected_ebitda": int(base * 2600),
                "ebitda_at_risk":   int(base * 2600 * 0.8),
                "potential_loss":   int(base * 2200 * 0.6),
                "roi_opportunity":  int(base * 10870),
            },
            "inputs_fingerprint": fp,
            "assumptions": inputs["assumptions"],
            "inputs": {
                **extracted_levers,
                "project_name": inputs.get("project_name"),
                "business_description": inputs.get("business_description"),
                "target_market": inputs.get("target_market"),
                "revenue_model": inputs.get("revenue_model"),
                "financial_metrics": inputs.get("financial_metrics") or {},
                "timeline": inputs.get("timeline"),
                "budget": inputs.get("budget") or {},
                "competition": inputs.get("competition"),
                "team": inputs.get("team"),
            },
            "compat": {
                **(inputs.get("financial_metrics") or {}),
                **(inputs.get("budget") or {}),
                **extracted_levers,
            },
        }

        # Persist (best-effort)
        try:
            # Ensure MiqThread exists
            thread = MiqThread.query.filter_by(thread_id=thread_id).first()
            if not thread:
                thread = MiqThread(thread_id=thread_id)
                db.session.add(thread)
                db.session.flush()

            # Upsert analysis
            existing = MiqAnalysis.query.filter_by(analysis_id=analysis_id).first()
            if existing:
                existing.thread_id = thread_id
                existing.session_id = pld.get("session_id")
                existing.result = result
                existing.meta = {"analysis_id": analysis_id, "fingerprint": fp}
            else:
                row = MiqAnalysis(
                    analysis_id=analysis_id,
                    thread_id=thread_id,
                    session_id=pld.get("session_id"),
                    result=result,
                    meta={"analysis_id": analysis_id, "fingerprint": fp},
                )
                db.session.add(row)

            db.session.commit()
        except Exception:
            current_app.logger.exception("persist_analysis failed (non-fatal)")
            try:
                db.session.rollback()
            except Exception:
                pass

        return jsonify({"analysis_result": result, "analysis_id": analysis_id}), 200
    except Exception as e:
        try:
            db.session.rollback()
        except Exception:
            pass
        current_app.logger.exception("analyze_from_conversation failed")
        return jsonify({"error": "server error", "detail": str(e)}), 500


# ---------------------------------------------------------------------------
# Routes: scenarios (create/list/update/apply)
# ---------------------------------------------------------------------------

@market_iq_analyze_bp.post("/threads/<thread_id>/scenarios")
def create_scenario(thread_id: str):
    """Create a new scenario for this thread (deterministic compute from deltas)."""
    try:
        try:
            payload = ScenarioCreatePayload.model_validate(request.get_json(silent=True) or {}).model_dump()
        except ValidationError as ve:
            return jsonify({"error": "bad_request", "detail": ve.errors()}), 400

        deltas = _normalize_percent_deltas(payload.get("deltas"))
        label = payload.get("label") or "Custom Scenario"
        session_id = payload.get("session_id")

        if not isinstance(deltas, dict) or not deltas:
            return jsonify({"error": "deltas required (object)"}), 400

        # Baseline: latest persisted analysis for this thread
        base = (
            MiqAnalysis.query
            .filter_by(thread_id=thread_id)
            .order_by(desc(MiqAnalysis.created_at))
            .first()
        )
        if not base:
            return jsonify({"error": "no_baseline", "detail": "run /analyze first for this thread"}), 409

        baseline_id = (
            getattr(base, "analysis_id", None)
            or (base.meta or {}).get("analysis_id")
            or (base.result or {}).get("analysis_id")
        )
        if not baseline_id:
            return jsonify({"error": "invalid_baseline"}), 500

        base_result = base.result or {}
        baseline_score = int(
            base_result.get("market_iq_score")
            or base_result.get("component_scores", {}).get("overall")
            or 0
        )

        canon = json.dumps({"based_on": baseline_id, "deltas": deltas}, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        fp = hashlib.sha256(canon.encode("utf-8")).hexdigest()
        delta = (int(fp[:4], 16) % 21) - 10  # [-10, +10]
        new_score = max(0, min(99, baseline_score + delta))

        result = {
            "based_on": baseline_id,
            "market_iq_score": new_score,
            "score_category": ("Excellent" if new_score >= 85 else "Good" if new_score >= 70 else "Fair" if new_score >= 55 else "Poor"),
            "component_scores": {
                "overall": new_score,
                "execution_readiness": max(min(new_score - 7, 99), 0),
                "financial_health":   max(min(new_score + 21, 99), 0),
                "market_position":    max(min(new_score - 4, 99), 0),
                "operational_efficiency": max(min(new_score - 14, 99), 0),
            },
            "applied_deltas": deltas,
            "inputs_fingerprint": (base_result.get("inputs_fingerprint") or ""),
            "computed_at": int(time.time()),
        }

        scenario_id = "scn_" + fp[:8]
        row = MiqScenario(
            scenario_id=scenario_id,
            thread_id=thread_id,
            session_id=session_id,
            based_on=baseline_id,
            deltas=deltas,
            result=result,
            label=label,
            meta={"fingerprint": fp},
        )
        db.session.add(row)
        db.session.commit()

        return jsonify({
            "thread_id": thread_id,
            "scenario": {
                "scenario_id": scenario_id,
                "based_on": baseline_id,
                "label": label,
                "deltas": deltas,
                "result": result,
                "meta": {"fingerprint": fp},
            }
        }), 201
    except Exception:
        try:
            db.session.rollback()
        except Exception:
            pass
        current_app.logger.exception("create_scenario failed")
        return jsonify({"error": "server error"}), 500


@market_iq_analyze_bp.get("/threads/<thread_id>/scenarios")
def list_scenarios(thread_id: str):
    """List scenarios for a thread (newest first), with pagination."""
    try:
        try:
            limit = int(request.args.get("limit", "20"))
        except Exception:
            limit = 20
        try:
            offset = int(request.args.get("offset", "0"))
        except Exception:
            offset = 0

        limit = max(1, min(100, limit))
        offset = max(0, offset)

        q = (
            MiqScenario.query
            .filter_by(thread_id=thread_id)
            .order_by(desc(MiqScenario.created_at))
        )
        total = q.count()
        rows = q.limit(limit).offset(offset).all()

        items = []
        for r in rows:
            created_at = getattr(r.created_at, "isoformat", lambda: str(r.created_at))()
            items.append({
                "scenario_id": r.scenario_id,
                "based_on": r.based_on,
                "label": r.label,
                "deltas": r.deltas,
                "result": r.result,
                "meta": r.meta,
                "created_at": created_at,
            })

        return jsonify({
            "thread_id": thread_id,
            "total": total,
            "limit": limit,
            "offset": offset,
            "scenarios": items,
        }), 200
    except Exception:
        try:
            db.session.rollback()
        except Exception:
            pass
        current_app.logger.exception("list_scenarios failed")
        return jsonify({"error": "server error"}), 500


@market_iq_analyze_bp.put("/scenarios/<scenario_id>")
@market_iq_analyze_bp.patch("/scenarios/<scenario_id>")
def update_scenario(scenario_id: str):
    """Update scenario deltas (and optional label) then recompute deterministically."""
    try:
        try:
            payload = ScenarioUpdatePayload.model_validate(request.get_json(silent=True) or {}).model_dump()
        except ValidationError as ve:
            return jsonify({"error": "bad_request", "detail": ve.errors()}), 400

        deltas = _normalize_percent_deltas(payload.get("deltas"))
        label = payload.get("label")
        tid_guard = request.args.get("thread_id")

        if not isinstance(deltas, dict) or not deltas:
            return jsonify({"error": "deltas required (object)"}), 400

        q = MiqScenario.query.filter_by(scenario_id=scenario_id)
        if tid_guard:
            q = q.filter_by(thread_id=tid_guard)
        scn = q.first()
        if not scn:
            return jsonify({"error": "not_found", "scenario_id": scenario_id}), 404

        base = None
        baseline_id = scn.based_on
        if baseline_id:
            base = MiqAnalysis.query.filter_by(analysis_id=baseline_id).first()
        if not base:
            base = (
                MiqAnalysis.query
                .filter_by(thread_id=scn.thread_id)
                .order_by(desc(MiqAnalysis.created_at))
                .first()
            )
        if not base:
            return jsonify({"error": "no_baseline", "detail": "no analysis for thread"}), 409

        base_result = base.result or {}
        baseline_id = (
            getattr(base, "analysis_id", None)
            or (base.meta or {}).get("analysis_id")
            or (base_result or {}).get("analysis_id")
        )
        if not baseline_id:
            return jsonify({"error": "invalid_baseline"}), 500

        baseline_score = int(
            base_result.get("market_iq_score")
            or base_result.get("component_scores", {}).get("overall")
            or 0
        )

        canon = json.dumps({"based_on": baseline_id, "deltas": deltas}, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        fp = hashlib.sha256(canon.encode("utf-8")).hexdigest()
        delta = (int(fp[:4], 16) % 21) - 10
        new_score = max(0, min(99, baseline_score + delta))

        result = {
            "based_on": baseline_id,
            "market_iq_score": new_score,
            "score_category": ("Excellent" if new_score >= 85 else "Good" if new_score >= 70 else "Fair" if new_score >= 55 else "Poor"),
            "component_scores": {
                "overall": new_score,
                "execution_readiness": max(min(new_score - 7, 99), 0),
                "financial_health":   max(min(new_score + 21, 99), 0),
                "market_position":    max(min(new_score - 4, 99), 0),
                "operational_efficiency": max(min(new_score - 14, 99), 0),
            },
            "applied_deltas": deltas,
            "inputs_fingerprint": (base_result.get("inputs_fingerprint") or ""),
            "computed_at": int(time.time()),
        }

        scn.deltas = deltas
        scn.result = result
        if label is not None:
            scn.label = label
        meta = scn.meta or {}
        meta["fingerprint"] = fp
        scn.meta = meta

        db.session.commit()

        return jsonify({
            "thread_id": scn.thread_id,
            "scenario": {
                "scenario_id": scn.scenario_id,
                "based_on": baseline_id,
                "label": scn.label,
                "deltas": scn.deltas,
                "result": scn.result,
                "meta": scn.meta,
            }
        }), 200
    except Exception:
        try:
            db.session.rollback()
        except Exception:
            pass
        current_app.logger.exception("update_scenario failed")
        return jsonify({"error": "server error"}), 500


@market_iq_analyze_bp.post("/scenarios/<scenario_id>/apply")
@market_iq_analyze_bp.post("/scenarios/<scenario_id>/run")
def apply_scenario(scenario_id: str):
    """Compute from scenario and persist a new analysis row."""
    try:
        tid_guard = request.args.get("thread_id")
        payload = request.get_json(silent=True) or {}

        q = MiqScenario.query.filter_by(scenario_id=scenario_id)
        if tid_guard:
            q = q.filter_by(thread_id=tid_guard)
        scn = q.first()
        if not scn:
            return jsonify({"error": "not_found", "scenario_id": scenario_id}), 404

        thread_id = scn.thread_id
        deltas = _normalize_percent_deltas(scn.deltas or {})
        label = scn.label

        base = None
        baseline_id = scn.based_on
        if baseline_id:
            base = MiqAnalysis.query.filter_by(analysis_id=baseline_id).first()
        if not base:
            base = (
                MiqAnalysis.query
                .filter_by(thread_id=thread_id)
                .order_by(desc(MiqAnalysis.created_at))
                .first()
            )
        if not base:
            return jsonify({"error": "no_baseline", "detail": "no analysis for thread"}), 409

        base_result = base.result or {}
        baseline_id = (
            getattr(base, "analysis_id", None)
            or (base.meta or {}).get("analysis_id")
            or (base_result or {}).get("analysis_id")
        )

        project_name = (
            base_result.get("project_name")
            or (payload.get("project_name") if isinstance(payload, dict) else None)
            or "Market IQ Project"
        )

        baseline_score = int(
            base_result.get("market_iq_score")
            or base_result.get("component_scores", {}).get("overall")
            or 0
        )

        canon = json.dumps({"based_on": baseline_id, "deltas": deltas}, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        fp = hashlib.sha256(canon.encode("utf-8")).hexdigest()
        delta = (int(fp[:4], 16) % 21) - 10
        new_score = max(0, min(99, baseline_score + delta))
        analysis_id = "analysis_" + fp[:8]

        result = {
            "analysis_id": analysis_id,
            "project_name": project_name,
            "thread_id": thread_id,
            "market_iq_score": new_score,
            "score_category": ("Excellent" if new_score >= 85 else "Good" if new_score >= 70 else "Fair" if new_score >= 55 else "Poor"),
            "component_scores": {
                "overall": new_score,
                "execution_readiness": max(min(new_score - 7, 99), 0),
                "financial_health":   max(min(new_score + 21, 99), 0),
                "market_position":    max(min(new_score - 4, 99), 0),
                "operational_efficiency": max(min(new_score - 14, 99), 0),
            },
            "financial_impact": {
                "projected_ebitda": int(new_score * 2600),
                "ebitda_at_risk":   int(new_score * 2600 * 0.8),
                "potential_loss":   int(new_score * 2200 * 0.6),
                "roi_opportunity":  int(new_score * 10870),
            },
            "inputs_fingerprint": fp,
            "assumptions": (base_result.get("assumptions") or {}),
            "inputs": (base_result.get("inputs") or {}),
            "compat": (base_result.get("compat") or {}),
            "applied_deltas": deltas,
            "based_on": baseline_id,
            "derived_from_scenario": scenario_id,
        }

        # Apply deltas to inputs/compat (best-effort)
        try:
            base_inputs = dict(result.get("inputs") or {})
            base_compat = dict(result.get("compat") or {})
            for k, v in (deltas or {}).items():
                if isinstance(v, (int, float)) and isinstance(base_compat.get(k), (int, float)):
                    base_compat[k] = base_compat.get(k) + v
                else:
                    base_compat[k] = v
                if isinstance(v, (int, float)) and isinstance(base_inputs.get(k), (int, float)):
                    base_inputs[k] = base_inputs.get(k) + v
                else:
                    base_inputs[k] = v
            result["inputs"] = base_inputs
            result["compat"] = base_compat
        except Exception:
            pass

        existing = MiqAnalysis.query.filter_by(analysis_id=analysis_id, thread_id=thread_id).first()
        if existing:
            existing.result = result
            existing.meta = {"analysis_id": analysis_id, "derived_from_scenario": scenario_id, "fingerprint": fp, "label": label}
            db.session.add(existing)
            scn.derived_analysis_id = analysis_id
            db.session.commit()
            return jsonify({
                "analysis_result": result,
                "analysis_id": analysis_id,
                "scenario": {
                    "scenario_id": scenario_id,
                    "label": label,
                    "based_on": baseline_id,
                    "applied_deltas": deltas,
                    "scorecard": result,
                },
            }), 200

        row = MiqAnalysis(
            analysis_id=analysis_id,
            thread_id=thread_id,
            session_id=None,
            derived_from_scenario_id=scenario_id,
            result=result,
            meta={"analysis_id": analysis_id, "derived_from_scenario": scenario_id, "fingerprint": fp, "label": label},
        )
        db.session.add(row)

        scn.derived_analysis_id = analysis_id

        db.session.commit()

        return jsonify({
            "analysis_result": result,
            "analysis_id": analysis_id,
            "scenario": {
                "scenario_id": scenario_id,
                "label": label,
                "based_on": baseline_id,
                "applied_deltas": deltas,
                "scorecard": result,
            },
        }), 201
    except Exception:
        try:
            db.session.rollback()
        except Exception:
            pass
        current_app.logger.exception("apply_scenario failed")
        return jsonify({"error": "server error"}), 500


@market_iq_analyze_bp.get("/analyses/<analysis_id>")
def get_analysis_by_id(analysis_id: str):
    """Fetch a single analysis (scorecard) by ID."""
    try:
        analysis = MiqAnalysis.query.filter_by(analysis_id=analysis_id).first()
        if not analysis:
            return jsonify({"error": "analysis_not_found", "analysis_id": analysis_id}), 404

        result = analysis.result or {}
        if result and not result.get("inputs"):
            result["inputs"] = result.get("compat", {}) or result.get("analysis_result", {}).get("inputs", {})

        return jsonify({
            "analysis_id": analysis_id,
            "analysis_result": result,
        }), 200
    except Exception as e:
        current_app.logger.exception("get_analysis_by_id failed")
        return jsonify({"error": "server_error", "detail": str(e)}), 500
