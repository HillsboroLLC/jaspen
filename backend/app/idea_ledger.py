# ============================================================================
# File: backend/app/idea_ledger.py
# Purpose: Distill a UserSession into a de-identified OrgIdeaLedger row.
#
#   What stays in the ledger after the user soft-deletes a session:
#     - Categorical tags (industry, idea_category, company_size, objective)
#     - Structured numeric scores (jaspen_score, dimension scores, score_category)
#     - Categorical risk/recommendation tags (NOT free-text)
#     - Engagement signals (had_tradeoff, had_execution_plan, phase/task counts)
#
#   What does NOT enter the ledger:
#     - Idea title / project_name / executive_summary
#     - Free-text rationale, risks, recommendations
#     - Chat history, file uploads, intake answers
#
# The ledger powers org-level benchmarking ("ideas like this typically score
# X for B2B SaaS in seed stage") without leaking individual idea content.
# ============================================================================

from datetime import datetime
from typing import Any, Dict, List, Optional
import logging

from app import db
from app.models import OrgIdeaLedger, User

logger = logging.getLogger(__name__)


# Canonical dimension keys we'll keep numeric scores for. Anything else in
# the dimensions blob is dropped on its way into the ledger.
_KEEP_DIMENSIONS = (
    "market_opportunity",
    "financial_viability",
    "execution_readiness",
    "strategic_alignment",
    "risk_profile",
    "evidence_quality",
)

# Map free-text risk descriptions → categorical tags. Very lightweight; we
# don't try to be exhaustive — the goal is "did this idea hit market /
# financial / execution / regulatory / competitive risk?" buckets.
_RISK_KEYWORD_TAGS = (
    ("market", "market_risk"),
    ("competition", "competitive_risk"),
    ("competitive", "competitive_risk"),
    ("regulator", "regulatory_risk"),
    ("compliance", "regulatory_risk"),
    ("privacy", "privacy_risk"),
    ("financial", "financial_risk"),
    ("revenue", "financial_risk"),
    ("margin", "financial_risk"),
    ("cost", "cost_risk"),
    ("budget", "cost_risk"),
    ("execution", "execution_risk"),
    ("timeline", "execution_risk"),
    ("hiring", "talent_risk"),
    ("talent", "talent_risk"),
    ("technical", "technical_risk"),
    ("technology", "technical_risk"),
    ("integration", "technical_risk"),
    ("adoption", "adoption_risk"),
    ("churn", "adoption_risk"),
    ("brand", "brand_risk"),
    ("reputation", "brand_risk"),
)

# Same shape for recommendation/next-step text.
_RECOMMENDATION_KEYWORD_TAGS = (
    ("pilot", "pilot_first"),
    ("audit", "discovery_then_build"),
    ("research", "discovery_then_build"),
    ("validate", "discovery_then_build"),
    ("hire", "build_team"),
    ("partner", "partner_strategy"),
    ("acquire", "inorganic"),
    ("invest", "capital_intensive"),
    ("phased", "phased_rollout"),
    ("phase", "phased_rollout"),
    ("kill", "deprioritize"),
    ("defer", "deprioritize"),
)


def _as_text_list(value) -> List[str]:
    if isinstance(value, list):
        out = []
        for item in value:
            if isinstance(item, str):
                out.append(item)
            elif isinstance(item, dict):
                text = item.get("text") or item.get("action") or item.get("description") or ""
                if isinstance(text, str):
                    out.append(text)
        return out
    if isinstance(value, str):
        return [value]
    return []


def _tag_from_keywords(texts: List[str], mapping) -> List[str]:
    tags = set()
    for raw in texts:
        low = raw.lower()
        for kw, tag in mapping:
            if kw in low:
                tags.add(tag)
    return sorted(tags)


def _idea_category_from_session(session: Dict[str, Any]) -> Optional[str]:
    """Best-effort categorical tag derived from intake context. We never
    keep the original free-text idea description — only its bucket."""
    # Prefer view/intake-derived hints if present.
    notes = session.get("notes") if isinstance(session.get("notes"), dict) else {}
    intake = notes.get("intake_context") if isinstance(notes.get("intake_context"), dict) else {}
    for key in ("idea_category", "category", "vertical", "segment"):
        v = intake.get(key) or notes.get(key)
        if isinstance(v, str) and v.strip():
            return v.strip().lower()[:100]
    # Fall back to a coarse bucket inferred from the project name keywords.
    pn = str(session.get("name") or "").lower()
    if not pn:
        result = session.get("result") if isinstance(session.get("result"), dict) else {}
        pn = str(result.get("project_name") or result.get("name") or "").lower()
    if not pn:
        return None
    buckets = [
        ("b2b saas", "saas_b2b"),
        ("saas", "saas"),
        ("fintech", "fintech"),
        ("hr ", "hr_tech"),
        ("hr-", "hr_tech"),
        ("ai-powered", "ai_app"),
        ("ai ", "ai_app"),
        ("marketplace", "marketplace"),
        ("e-commerce", "ecommerce"),
        ("ecommerce", "ecommerce"),
        ("healthcare", "healthcare"),
        ("logistics", "logistics"),
        ("restaurant", "food_service"),
    ]
    for needle, bucket in buckets:
        if needle in pn:
            return bucket
    return "other"


def _extract_result(session: Dict[str, Any]) -> Dict[str, Any]:
    result = session.get("result")
    return result if isinstance(result, dict) else {}


def _dimension_distillation(result: Dict[str, Any]) -> Dict[str, Any]:
    raw = result.get("dimensions") if isinstance(result.get("dimensions"), dict) else {}
    distilled = {}
    for key in _KEEP_DIMENSIONS:
        cell = raw.get(key)
        if isinstance(cell, dict):
            distilled[key] = {
                "score": cell.get("score"),
                "confidence": cell.get("confidence"),
                "source": cell.get("source"),
            }
        elif isinstance(cell, (int, float)):
            distilled[key] = {"score": cell}
    return distilled


def distill_session_to_ledger_row(
    *,
    user: Optional[User],
    session: Dict[str, Any],
    outcome: str = "active",
) -> Optional[OrgIdeaLedger]:
    """Create (or refresh) an OrgIdeaLedger row from a UserSession payload.

    Returns the row that was committed. Returns None if the session has
    nothing scorable in it (no scorecard) — we don't create empty rows.
    """
    if not isinstance(session, dict):
        return None

    result = _extract_result(session)
    score = result.get("jaspen_score")
    has_score = isinstance(score, (int, float)) and score is not None
    has_dimensions = isinstance(result.get("dimensions"), dict) and result["dimensions"]
    if not (has_score or has_dimensions):
        return None  # Nothing meaningful to capture yet

    session_id = str(session.get("session_id") or "").strip() or None
    org_id = session.get("organization_id")
    user_id = str(user.id) if user else None

    risk_tags = _tag_from_keywords(_as_text_list(result.get("top_risks")), _RISK_KEYWORD_TAGS)
    rec_tags = _tag_from_keywords(
        _as_text_list(result.get("recommendations")) + _as_text_list(result.get("next_steps")),
        _RECOMMENDATION_KEYWORD_TAGS,
    )

    # Engagement signals
    wbs = session.get("project_wbs") if isinstance(session.get("project_wbs"), dict) else {}
    tasks = wbs.get("tasks") if isinstance(wbs.get("tasks"), list) else []
    task_count = len(tasks)
    phases = {str(t.get("phase") or "").strip() for t in tasks if isinstance(t, dict)}
    phases.discard("")
    phase_count = len(phases) if phases else None

    scenarios = session.get("scenarios") if isinstance(session.get("scenarios"), list) else []
    had_tradeoff = len(scenarios) >= 1

    industry = None
    company_size = None
    if user:
        industry = getattr(user, "industry", None)
        company_size = getattr(user, "company_size", None)

    # Try to find an existing ledger row for this session and update it,
    # rather than always inserting (lets us refresh the outcome and dim
    # snapshot when the user re-scores).
    existing = None
    if session_id:
        existing = OrgIdeaLedger.query.filter_by(source_session_id=session_id).first()

    row = existing or OrgIdeaLedger(
        organization_id=str(org_id) if org_id else None,
        originating_user_id=user_id,
        source_session_id=session_id,
    )
    row.idea_category = _idea_category_from_session(session)
    row.industry = (industry or "").strip()[:100] if industry else None
    row.company_size = (company_size or "").strip()[:50] if company_size else None
    row.jaspen_score = int(score) if has_score else None
    row.score_category = str(result.get("score_category") or "").strip().lower()[:20] or None
    row.dimensions = _dimension_distillation(result)
    row.risk_tags = risk_tags
    row.recommendation_tags = rec_tags
    row.had_tradeoff = had_tradeoff
    row.had_execution_plan = task_count > 0
    row.phase_count = phase_count
    row.task_count = task_count or None
    row.objective = str(session.get("strategy_objective") or "").strip().lower()[:50] or None
    row.model_tier_used = str(session.get("model_type") or "").strip().lower()[:32] or None
    row.outcome = outcome
    row.updated_at = datetime.utcnow()

    try:
        if existing is None:
            db.session.add(row)
        db.session.commit()
        return row
    except Exception as e:
        db.session.rollback()
        logger.error(f"Failed to write idea ledger row: {e}")
        return None


def mark_ledger_archived(session_id: str) -> bool:
    """Stamp archived_at on the ledger row tied to this session_id."""
    if not session_id:
        return False
    row = OrgIdeaLedger.query.filter_by(source_session_id=session_id).first()
    if row is None:
        return False
    row.outcome = "archived"
    row.archived_at = datetime.utcnow()
    try:
        db.session.commit()
        return True
    except Exception as e:
        db.session.rollback()
        logger.error(f"Failed to mark ledger archived for {session_id}: {e}")
        return False


def mark_ledger_purged(session_id: str) -> bool:
    """Hard-purge: zero originating_user_id (fully anonymize), drop the
    source_session_id link, set outcome=purged. The row stays so org-level
    aggregates remain consistent — but no path leads back to a user."""
    if not session_id:
        return False
    row = OrgIdeaLedger.query.filter_by(source_session_id=session_id).first()
    if row is None:
        return False
    row.outcome = "purged"
    row.purged_at = datetime.utcnow()
    row.originating_user_id = None
    row.source_session_id = None
    try:
        db.session.commit()
        return True
    except Exception as e:
        db.session.rollback()
        logger.error(f"Failed to mark ledger purged for {session_id}: {e}")
        return False
