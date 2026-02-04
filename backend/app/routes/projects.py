# app/routes/projects.py — clean drop-in
from __future__ import annotations

import json
from datetime import datetime, timezone
from hashlib import sha256
from typing import List

from flask import Blueprint, jsonify, request, current_app
from werkzeug.exceptions import BadRequest
from sqlalchemy import text

from app import db
from app.models import Project
# Lazy imports inside routes avoid circulars for ProjectPlan/MiqMessage
# Pydantic plan schema for validation/normalization
from app.schemas.project_plan import Plan, WBS, Phase, Task, Timeline, Milestone, Risk, Resources, Assumption

projects_bp = Blueprint("projects_bp", __name__, url_prefix="/api/projects")

@projects_bp.teardown_request
def _projects_bp_teardown_tx(exc):
    # Always leave the session clean for the next request
    try:
        db.session.rollback()
    except Exception:
        pass
    try:
        db.session.close()
    except Exception:
        pass
    try:
        db.session.remove()
    except Exception:
        pass

@projects_bp.before_request
def _projects_bp_reset_tx():
    # Light reset to avoid poisoned sessions across requests
    try:
        db.session.rollback()
    except Exception:
        pass
    try:
        db.session.remove()
    except Exception:
        pass

  # ---------- Existing minimal routes ----------

@projects_bp.post("/begin")
def begin_project():
    """
    Create-or-return a 'Project shell' with no plan.
    - Idempotent by sid (returns existing active project if found).
    - Optionally stores transcript/breadcrumbs in idea_snapshot.
    """
    from flask import jsonify
    from werkzeug.exceptions import BadRequest
    from app.models import Project
    from app import db

    data = request.get_json(silent=True) or {}
    sid = (data.get("sid") or "").strip()
    if not sid or len(sid) < 3:
        raise BadRequest("sid is required and must be at least 3 characters")

    # Optional breadcrumbs
    project_name = (data.get("project_name") or "").strip()
    transcript   = (data.get("transcript") or "").strip()
    thread_id    = (data.get("thread_id") or "").strip()
    analysis_id  = (data.get("analysis_id") or "").strip()

    # Idempotent: fetch existing active project for sid
    project = (
        Project.query
        .filter(Project.sid == sid)
        .filter(Project.deleted_at.is_(None))
        .first()
    )
    created_now = False
    if not project:
        created_now = True
        idea_snapshot = {
            "source": "market_iq",
            "project_name": project_name or None,
            "thread_id": thread_id or None,
            "analysis_id": analysis_id or None,
        }
        # include transcript breadcrumb if provided
        if transcript:
            idea_snapshot["transcript"] = transcript

        project = Project(
            sid=sid,
            status="PENDING",  # shell only; no plan yet
            idea_snapshot=idea_snapshot,
            business_case_snapshot=None,
        )
        db.session.add(project)
        db.session.commit()  # allocate id

    # If already exists, optionally merge new breadcrumbs (non-destructive)
    else:
        merged = dict(project.idea_snapshot or {})
        if project_name and not merged.get("project_name"):
            merged["project_name"] = project_name
        if thread_id:
            merged["thread_id"] = thread_id
        if analysis_id:
            merged["analysis_id"] = analysis_id
        if transcript and not merged.get("transcript"):
            merged["transcript"] = transcript
        # Only write if changed
        if merged != (project.idea_snapshot or {}):
            project.idea_snapshot = merged
            db.session.commit()

    return jsonify({
        "project_id": project.id,
        "sid": project.sid,
        "status": project.status,
        "created": created_now,
        "has_plan": bool(project.plan and project.plan.deleted_at is None),
    }), 201 if created_now else 200

@projects_bp.get("/")
def list_projects():
    rows = db.session.execute(text(
        "select id,sid,status,created_at from projects "
        "where deleted_at is null order by created_at desc limit 5"
    )).fetchall()
    return jsonify({
        "count": len(rows),
        "items": [
            {"id": r[0], "sid": r[1], "status": r[2], "created_at": r[3].isoformat() if r[3] else None}
            for r in rows
        ],
    }), 200

@projects_bp.get("/ping")
def ping():
    from sqlalchemy import text
    try:
        # Touch the DB to surface any poisoned transaction state.
        db.session.execute(text("SELECT 1"))
        db.session.rollback()  # leave session clean
        return jsonify({"ok": True, "db_ok": True}), 200
    except Exception as e:
        # Recover session so the next request isn't poisoned.
        try:
            db.session.rollback()
        except Exception:
            pass
        return jsonify({"ok": False, "db_ok": False, "detail": str(e)}), 500


@projects_bp.get("/debug/<path:p>")
def debug_projects_path(p: str):
    return jsonify({"matched": p}), 200


# ---------- New: Generate Project + Plan (idempotent) ----------

@projects_bp.post("/generate")
def generate_project_and_plan():
    """
    Create-or-get Project by sid/analysis_id/thread_id and attach a validated Plan.
    Builds a deterministic WBS skeleton; validates with Pydantic; two-stage DB write.
    """
    # Defensive: clear any aborted txn from prior requests
    try:
        db.session.rollback()
    except Exception:
        pass

    # Local imports avoid circulars
    from app.models import Project, ProjectPlan, MiqMessage
    from app.schemas.project_plan import (
        Plan, WBS, Phase, Task, Timeline, Milestone, Risk, Resources, Assumption
    )
    import json
    from hashlib import sha256
    from datetime import datetime, timezone

    pld = request.get_json(silent=True) or {}
    raw_sid = (pld.get("sid") or pld.get("analysis_id") or pld.get("thread_id") or "").strip()
    if not raw_sid or len(raw_sid) < 3:
        raise BadRequest("One of sid | analysis_id | thread_id is required (min length 3)")

    # ------- find-or-create Project -------
    try:
        project = (
            Project.query
            .filter(Project.sid == raw_sid)
            .filter(Project.deleted_at.is_(None))
            .first()
        )
        created_now = False
        if not project:
            project = Project(
                sid=raw_sid,
                status="GENERATING",
                idea_snapshot={"source": "market_iq", "analysis_id": pld.get("analysis_id"), "thread_id": pld.get("thread_id")},
                business_case_snapshot=None,
            )
            db.session.add(project)
            try:
                db.session.commit()  # commit to satisfy FK before inserting ProjectPlan
                created_now = True
            except Exception as e:
                current_app.logger.exception("project create commit failed")
                try:
                    db.session.rollback()
                except Exception:
                    pass
                return jsonify({"error": "db_error", "stage": "project_create_commit", "detail": str(e)}), 500
            # re-fetch to ensure we have a managed instance (fresh after commit)
            project = (
                Project.query
                .filter(Project.id == project.id)
                .first()
            )
            created_now = True
    except Exception as e:
        current_app.logger.exception("generate_project_and_plan: PROJECT init failed")
        try:
            db.session.rollback()
        except Exception:
            pass
        return jsonify({"error": "db_error", "stage": "project_init", "detail": str(e)}), 500

    # Idempotency: return existing plan if present
    existing_plan = project.plan if getattr(project, "plan", None) and project.plan.deleted_at is None else None
    if existing_plan:
        return jsonify({
            "project_id": project.id,
            "plan_id": existing_plan.id,
            "status": project.status,
            "redirect": f"/ops/project-planning?projectId={project.id}",
            "idempotent": True,
        }), 200

    # ------- optional context from thread messages -------
    thread_id = (pld.get("thread_id") or raw_sid)
    # Optional: tie plan generation to a specific MarketIQ analysis (baseline or scenario)
    analysis_id = (pld.get("analysis_id") or pld.get("source_analysis_id") or "").strip()
    transcript_parts = []
    try:
        msgs = (
            db.session.query(MiqMessage)
            .filter(MiqMessage.thread_id == thread_id)
            .order_by(MiqMessage.created_at.asc())
            .all()
        )
        for m in msgs:
            c = m.content
            text_value = ""
            if isinstance(c, dict):
                for k in ("text", "message", "content", "body", "prompt"):
                    v = c.get(k)
                    if isinstance(v, str) and v.strip():
                        text_value = v.strip()
                        break
            elif isinstance(c, str) and c.strip():
                text_value = c.strip()
            if text_value:
                transcript_parts.append(f"{m.role}: {text_value}")
    except Exception:
        pass
    transcript = "\n".join(transcript_parts)

    # ------- deterministic seed & plan build (validated) -------
    basis = json.dumps({
        "sid": raw_sid,
        "project_name": pld.get("project_name") or "",
        "transcript": transcript[-4000:],
    }, sort_keys=True)
    fphex = sha256(basis.encode("utf-8")).hexdigest()
    derived_name = pld.get("project_name") or _extract_title_from_transcript(transcript) or "Market IQ Project"

    init = Phase(
        id=f"PLN-{fphex[:6]}",
        name="Initialization",
        children=[
            Task(id=f"TSK-{fphex[6:12]}",  name="Project kickoff & scope",       lead_time_days=2),
            Task(id=f"TSK-{fphex[12:18]}", name="Requirements consolidation",    lead_time_days=3, depends_on=[f"TSK-{fphex[6:12]}"]),
        ],
    )
    execu = Phase(
        id=f"PLN-{fphex[18:24]}",
        name="Execution",
        children=[
            Task(id=f"TSK-{fphex[24:30]}", name="Implement core features", lead_time_days=5, depends_on=[f"TSK-{fphex[12:18]}"]),
            Task(id=f"TSK-{fphex[30:36]}", name="Testing & QA",            lead_time_days=3, depends_on=[f"TSK-{fphex[24:30]}"]),
        ],
    )
    wbs = WBS(
        version=1,
        fingerprint=fphex[:12],
        items=[init, execu],
        meta={"generated_at": datetime.now(timezone.utc).isoformat(), "source": "deterministic_skeleton"},
    )
    timeline = Timeline(phases=[{"id": init.id, "name": init.name}, {"id": execu.id, "name": execu.name}])
    milestones = [Milestone(id=f"MLS-{fphex[36:42]}", name="MVP ready", depends_on=[f"TSK-{fphex[30:36]}"])]
    risks = [Risk(id=f"RSK-{fphex[42:48]}", name="Scope creep", mitigation="Lock acceptance criteria")]
    resources = Resources(team=[], budget={"currency": "USD", "total": None})  # accepts any dict
    assumptions = [Assumption(id=f"ASM-{fphex[48:54]}", text="Availability of stakeholders for reviews")]
    notes_str = json.dumps(
        {"project_name": derived_name, "context_sample": transcript[:1000] if transcript else ""},
        ensure_ascii=False,
    )

    try:
        plan_model = Plan(
            wbs=wbs,
            timeline=timeline,
            milestones=milestones,
            risks=risks,
            resources=resources,
            assumptions=assumptions,
            notes=notes_str,
        )
        payload = plan_model.to_db_payload()
    except Exception as e:
        # Why: ensure any schema validation error is surfaced as JSON
        return jsonify({"error": "validation_error", "detail": str(e)}), 400
        # ------- preflight: respect unique(project_id) on project_plans -------
    try:
        from app.models import ProjectPlan
        prior = (
            db.session.query(ProjectPlan.id, ProjectPlan.deleted_at)
            .filter(ProjectPlan.project_id == project.id)
            .first()
        )
        if prior:
            prior_id, prior_deleted = prior
            if prior_deleted is None:
                # Active plan exists → idempotent return
                return jsonify({
                    "project_id": project.id,
                    "plan_id": prior_id,
                    "status": project.status,
                    "redirect": f"/ops/project-planning?projectId={project.id}",
                    "idempotent": True,
                    "note": "Existing plan reused",
                }), 200
            else:
                # Soft-deleted exists → revive/update in-place to avoid unique violation
                revived = db.session.query(ProjectPlan).get(prior_id)
                revived.wbs         = payload["wbs"]
                revived.timeline    = payload["timeline"]
                revived.milestones  = payload["milestones"]
                revived.risks       = payload["risks"]
                revived.resources   = payload["resources"]
                revived.assumptions = payload["assumptions"]
                revived.notes       = payload["notes"]
                revived.deleted_at  = None
                db.session.flush()  # validate UPDATE

                project.status = "READY"
                db.session.commit()
                return jsonify({
                    "project_id": project.id,
                    "plan_id": revived.id,
                    "status": project.status,
                    "redirect": f"/ops/project-planning?projectId={project.id}",
                    "idempotent": False,
                    "note": "Soft-deleted plan revived",
                }), 200
    except Exception as e:
        current_app.logger.exception("preflight check failed; continuing to insert")
        try:
            db.session.rollback()
        except Exception:
            pass
        # fall through to insert path

    # ------- persist plan, then update project (two-stage) -------
    try:
        plan = ProjectPlan(
            project_id=project.id,
            wbs=payload["wbs"],
            timeline=payload["timeline"],
            milestones=payload["milestones"],
            risks=payload["risks"],
            resources=payload["resources"],
            assumptions=payload["assumptions"],
            notes=payload["notes"],
        )
        db.session.add(plan)
        db.session.flush()  # surface plan insert errors first
    except Exception as e:
        current_app.logger.exception("generate_project_and_plan: PLAN flush failed")
        try:
            db.session.rollback()
        except Exception:
            pass
        return jsonify({"error": "db_error", "stage": "plan_flush", "detail": str(e)}), 500

    try:
        project.status = "READY"
        if created_now and not project.idea_snapshot:
            project.idea_snapshot = {"source": "market_iq", "thread_id": thread_id}
        db.session.commit()
    except Exception as e:
        current_app.logger.exception("generate_project_and_plan: PROJECT commit failed")
        try:
            db.session.rollback()
        except Exception:
            pass
        return jsonify({"error": "db_error", "stage": "project_commit", "detail": str(e)}), 500

    return jsonify({
        "project_id": project.id,
        "plan_id": plan.id,
        "status": project.status,
        "redirect": f"/ops/project-planning?projectId={project.id}",
        "idempotent": False,
    }), 201


@projects_bp.post("/generate/ai")
def generate_project_and_plan_ai():
    """
    Context-driven generator (no external AI calls):
    - Pulls latest MarketIQ analysis + thread messages
    - Builds a richer Plan-shaped payload (WBS/TL/milestones/risks/resources/assumptions)
    - dry_run=True: validate & return (no DB writes)
    - persist=True: upsert Project (by sid) and save a new ProjectPlan
    - mode: 'create' | 'replace' (behavior if plan exists)
    """
    # Route-level safety reset
    try:
        db.session.rollback()
    except Exception:
        pass

    from datetime import datetime, timezone
    import json as _json
    import hashlib, random

    from app.models import Project, ProjectPlan, MiqMessage, MiqAnalysis
    from app.schemas.project_plan import (
        Plan, WBS, Timeline, Milestone, Risk, Resources, Assumption, Task, Phase
    )

    pld = request.get_json(silent=True) or {}

    # Flags
    dry_run  = bool(pld.get("dry_run", True))
    persist  = bool(pld.get("persist", not dry_run))
    mode     = (pld.get("mode") or "create").strip().lower()  # create | replace
    if mode not in ("create", "replace"):
        mode = "create"

    # Identity hints
    sid = (pld.get("sid") or pld.get("analysis_id") or pld.get("thread_id") or "").strip()
    if not sid or len(sid) < 3:
        return jsonify({"error": "bad_request", "detail": "sid | analysis_id | thread_id required (min len 3)"}), 400

    project_name = (pld.get("project_name") or "Project").strip()
    thread_id    = (pld.get("thread_id") or sid).strip()

    analysis_id = (pld.get("analysis_id") or pld.get("score_id") or pld.get("latest_analysis_id"))
    if isinstance(analysis_id, str):
        analysis_id = analysis_id.strip() or None

    # Optional selected variant (baseline/scenario)
    variant_id = (pld.get("variant_id") or pld.get("selected_variant_id") or pld.get("scenario_id") or "baseline").strip() or "baseline"

    # Incoming scorecard override (if UI sends it)
    incoming_scorecard = pld.get("analysis_result") or pld.get("scorecard") or pld.get("analysis") or None
    if isinstance(incoming_scorecard, str):
        try:
            incoming_scorecard = _json.loads(incoming_scorecard)
        except Exception:
            incoming_scorecard = None

    # ---- helpers ----
    def _extract_text(c):
        if isinstance(c, str):
            return c.strip()
        if isinstance(c, dict):
            for k in ("text", "message", "content", "body"):
                v = c.get(k)
                if isinstance(v, str) and v.strip():
                    return v.strip()
        return ""

    def _safe_get(d, *keys, default=None):
        cur = d
        for k in keys:
            if not isinstance(cur, dict) or k not in cur:
                return default
            cur = cur[k]
        return cur

    # ---- fetch analysis (current) ----
    # Current analysis = adopted scenario snapshot if one is adopted for this thread, else latest baseline, else latest.
    adopted_scn = None
    try:
        # Find most-recent adopted scenario for this thread
        scn_rows = (
            MiqScenario.query
            .filter(MiqScenario.thread_id == thread_id)
            .order_by(MiqScenario.created_at.desc())
            .limit(200)
            .all()
        )
        for r in scn_rows:
            meta = r.meta if isinstance(r.meta, dict) else {}
            if meta.get('adopted') is True:
                adopted_scn = r
                break
    except Exception:
        adopted_scn = None

    adopted_analysis_id = None
    if adopted_scn and isinstance(adopted_scn.meta, dict):
        adopted_analysis_id = adopted_scn.meta.get('adopted_analysis_id') or adopted_scn.meta.get('derived_analysis_id')

    baseline_row = None
    try:
        # baseline = analyses not derived from scenario
        baseline_row = (
            MiqAnalysis.query
            .filter(MiqAnalysis.thread_id == thread_id)
            .filter(~MiqAnalysis.meta.has_key('derived_from_scenario_id'))  # type: ignore
            .order_by(MiqAnalysis.created_at.desc())
            .first()
        )
    except Exception:
        baseline_row = None
        try:
            rows = (
                MiqAnalysis.query
                .filter(MiqAnalysis.thread_id == thread_id)
                .order_by(MiqAnalysis.created_at.desc())
                .limit(200)
                .all()
            )
            for r in rows:
                meta = r.meta if isinstance(r.meta, dict) else {}
                if not meta.get('derived_from_scenario_id'):
                    baseline_row = r
                    break
        except Exception:
            baseline_row = None

    latest_row = None
    try:
        latest_row = (
            MiqAnalysis.query
            .filter(MiqAnalysis.thread_id == thread_id)
            .order_by(MiqAnalysis.created_at.desc())
            .first()
        )
    except Exception:
        latest_row = None

    latest_meta = None
    try:
        latest_meta = latest_row.meta if latest_row else None
    except Exception:
        latest_meta = None

    current_row = None
    if adopted_analysis_id:
        try:
            current_row = MiqAnalysis.query.filter(MiqAnalysis.analysis_id == adopted_analysis_id).first()
        except Exception:
            current_row = None

    if not current_row:
        current_row = baseline_row or latest_row

    current_analysis_id = None
    current_result = None
    current_meta = None
    if current_row:
        current_analysis_id = getattr(current_row, 'analysis_id', None) or (current_row.meta or {}).get('analysis_id') or (current_row.result or {}).get('analysis_id')
        current_result = current_row.result
        current_meta = current_row.meta

    # Choose a scorecard to drive plan generation
    scorecard = incoming_scorecard or (current_result or {})
    if not analysis_id:
        analysis_id = current_analysis_id

    # ---- fetch richer context (messages) ----
    try:
        mq = (MiqMessage.query
              .filter(MiqMessage.thread_id == thread_id)
              .order_by(MiqMessage.created_at.asc()))
        msgs = mq.limit(40).all()
    except Exception:
        msgs = []

    context_lines = []
    for m in msgs:
        t = _extract_text(getattr(m, "content", None))
        if t:
            role = getattr(m, "role", "user")
            context_lines.append(f"{role}: {t}")
    context_sample = "\n".join(context_lines)[-6000:]  # keep notes bounded

    # ---- determine execution style ----
    execution_style = (pld.get("execution_style") or pld.get("project_style") or "").strip().lower()
    if not execution_style:
        # try to infer from scorecard/meta
        inferred = (
            _safe_get(scorecard, "project_type") or
            _safe_get(scorecard, "execution_style") or
            _safe_get(scorecard, "meta", "execution_style") or
            _safe_get(latest_meta or {}, "execution_style")
        )
        execution_style = (inferred or "").strip().lower()

    if execution_style not in ("agile", "waterfall", "it_sprint", "it", "ops"):
        execution_style = "ops"

    # ---- deterministic ID + ordering seed ----
    seed = int(hashlib.sha256(f"{sid}:{analysis_id}:{variant_id}".encode("utf-8")).hexdigest()[:8], 16)
    rng  = random.Random(seed)

    def _rid(prefix: str) -> str:
        return f"{prefix}-{hashlib.sha1(f'{prefix}:{rng.random()}'.encode()).hexdigest()[:6]}"

    # ---- build a richer plan template ----
    # Core phases common to ops execution. (Agile swaps the middle.)
    if execution_style in ("agile", "it_sprint", "it"):
        phase_defs = [
            ("Discovery", [
                ("Define problem statement & success metrics", 2),
                ("Confirm stakeholders & cadence", 1),
                ("Define MVP scope + non-goals", 2),
            ]),
            ("Backlog & Design", [
                ("Create epics / user stories", 3),
                ("Define acceptance criteria", 2),
                ("Design workflows / UI / data", 3),
            ]),
            ("Sprint Build", [
                ("Sprint 1 build", 5),
                ("Sprint 2 build", 5),
                ("Sprint review + backlog grooming", 2),
            ]),
            ("Test & Readiness", [
                ("QA + UAT", 3),
                ("Training + SOP updates", 3),
                ("Cutover plan + rollback plan", 2),
            ]),
            ("Launch & Stabilize", [
                ("Pilot / phased rollout", 5),
                ("Hypercare + issue triage", 5),
                ("Stabilize + handoff", 2),
            ]),
        ]
    else:
        phase_defs = [
            ("Initiation", [
                ("Define scope & objectives", 2),
                ("Stakeholder alignment & governance", 2),
                ("Baseline current state (process/data)", 3),
            ]),
            ("Design", [
                ("Future state design + requirements", 4),
                ("Risk assessment (FMEA-lite) + mitigations", 3),
                ("Implementation plan + readiness checklist", 3),
            ]),
            ("Build / Prepare", [
                ("Develop materials (SOPs, training, comms)", 4),
                ("System / tooling updates (if applicable)", 5),
                ("Pilot plan + measurement plan", 3),
            ]),
            ("Validate", [
                ("Pilot execution", 5),
                ("Results review + adjustments", 3),
                ("Go/No-Go decision", 1),
            ]),
            ("Rollout & Sustain", [
                ("Rollout execution", 10),
                ("Monitoring + corrective actions", 5),
                ("Sustainment + closeout", 2),
            ]),
        ]

    # Build phases + tasks with sequential dependencies across phases
    phases = []
    prev_last_task_id = None

    for pname, tasks in phase_defs:
        phase_id = _rid("PLN")
        children = []
        prev_task_id_in_phase = None

        for tname, ltd in tasks:
            tid = _rid("TSK")
            deps = []
            if prev_task_id_in_phase:
                deps = [prev_task_id_in_phase]
            elif prev_last_task_id:
                deps = [prev_last_task_id]

            children.append(Task(
                id=tid,
                name=tname,
                lead_time_days=int(ltd),
                depends_on=deps,
            ))
            prev_task_id_in_phase = tid

        prev_last_task_id = prev_task_id_in_phase
        phases.append(Phase(id=phase_id, name=pname, children=children))

    # Milestones tied to end of key phases
    milestones = [
        Milestone(id=_rid("MLS"), name="Scope approved", depends_on=[phases[0].children[-1].id]),
        Milestone(id=_rid("MLS"), name="Ready for pilot / build complete", depends_on=[phases[-2].children[-1].id]),
        Milestone(id=_rid("MLS"), name="Rollout complete", depends_on=[phases[-1].children[-1].id]),
    ]

    # Risks: seed with a few ops-standard risks; optionally enrich from scorecard
    risks = [
        Risk(id=_rid("RSK"), name="Scope creep", likelihood="medium", impact="medium", mitigation="Lock acceptance criteria; use change control"),
        Risk(id=_rid("RSK"), name="Stakeholder availability", likelihood="medium", impact="medium", mitigation="Confirm cadence; assign delegates"),
        Risk(id=_rid("RSK"), name="Readiness gaps at launch", likelihood="medium", impact="high", mitigation="Use readiness checklist; pilot + hypercare"),
    ]

    # Assumptions: seed with a few; optionally enrich from scorecard
    assumptions = [
        Assumption(id=_rid("ASM"), text="Stakeholders available for reviews and decisions"),
        Assumption(id=_rid("ASM"), text="Required data/tools access will be granted in time"),
    ]

    # Try to pull useful signals from scorecard without assuming schema
    # Example places we’ve seen: result.overall_recommendation, result.investment_status, result.timeline, result.budget
    overall = _safe_get(scorecard, "overall_recommendation") or _safe_get(scorecard, "recommendation")
    invest  = _safe_get(scorecard, "investment_status") or _safe_get(scorecard, "status")

    # Resources: keep structure stable; budget may be unknown
    resources = Resources(team=[], budget={"currency": "USD", "total": None})

    wbs = WBS(
        version=1,
        fingerprint=hashlib.md5(f"{sid}:{analysis_id}:{variant_id}".encode("utf-8")).hexdigest()[:12],
        items=phases,
        meta={
            "source": "ai_context",
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "thread_id": (thread_id or ""),
            "analysis_id": (analysis_id or ""),
            "variant_id": (variant_id or "baseline"),
            "execution_style": (execution_style or ""),
            "overall_recommendation": (overall or ""),
            "investment_status": (invest or ""),
        },
    )

    timeline = Timeline(phases=[{"id": p.id, "name": p.name} for p in phases])

    plan_model = Plan(
        wbs=wbs,
        timeline=timeline,
        milestones=milestones,
        risks=risks,
        resources=resources,
        assumptions=assumptions,
        notes=_json.dumps({
            "project_name": project_name,
            "source": "ai_context",
            "thread_id": thread_id,
            "analysis_id": analysis_id,
            "variant_id": variant_id,
            "execution_style": execution_style,
            "context_sample": context_sample[:6000],
        }),
    )

    payload = plan_model.to_db_payload()

    # Dry-run path: no DB writes, just echo plan.
    if dry_run and not persist:
        return jsonify({
            "mode": mode,
            "persisted": False,
            "project_id": None,
            "plan_id": None,
            "status": "DRY_RUN",
            "plan": payload,
        }), 200

    # Persist path: upsert Project + write ProjectPlan (create/replace)
    try:
        project = (
            Project.query
            .filter(Project.sid == sid)
            .filter(Project.deleted_at.is_(None))
            .first()
        )
    except Exception:
        project = None

    created_now = False
    if not project:
        project = Project(
            sid=sid,
            status="GENERATING",
            idea_snapshot={
                "source": "market_iq",
                "analysis_id": analysis_id,
                "thread_id": thread_id,
                "variant_id": variant_id,
                "execution_style": execution_style,
            },
            business_case_snapshot=None,
        )
        db.session.add(project)
        db.session.commit()
        created_now = True

    # Existing plan handling
    existing = None
    try:
        existing = (
            ProjectPlan.query
            .filter(ProjectPlan.project_id == project.id)
            .filter(ProjectPlan.deleted_at.is_(None))
            .first()
        )
    except Exception:
        existing = None

    if existing and mode != "replace":
        # keep existing, return it
        project.status = "READY"
        db.session.commit()
        return jsonify({
            "mode": mode,
            "persisted": True,
            "project_id": project.id,
            "plan_id": existing.id,
            "redirect": f"/ops/project-planning?projectId={project.id}",
            "status": project.status,
        }), 200

    if existing and mode == "replace":
        try:
            existing.deleted_at = datetime.utcnow()
            db.session.add(existing)
            db.session.commit()
        except Exception:
            try:
                db.session.rollback()
            except Exception:
                pass

    plan = ProjectPlan(
        project_id=project.id,
        wbs=payload.get("wbs"),
        timeline=payload.get("timeline"),
        milestones=payload.get("milestones"),
        risks=payload.get("risks"),
        resources=payload.get("resources"),
        assumptions=payload.get("assumptions"),
        notes=payload.get("notes"),
    )

    try:
        db.session.add(plan)
        db.session.flush()
    except Exception as e:
        current_app.logger.exception("generate_project_and_plan_ai: PLAN flush failed")
        try:
            db.session.rollback()
        except Exception:
            pass
        return jsonify({"error": "db_error", "stage": "plan_flush", "detail": str(e)}), 500

    try:
        project.status = "READY"
        db.session.commit()
    except Exception as e:
        current_app.logger.exception("generate_project_and_plan_ai: PROJECT commit failed")
        try:
            db.session.rollback()
        except Exception:
            pass
        return jsonify({"error": "db_error", "stage": "project_commit", "detail": str(e)}), 500

    return jsonify({
        "mode": mode,
        "persisted": True,
        "plan_id": plan.id,
        "project_id": project.id,
        "redirect": f"/ops/project-planning?projectId={project.id}",
        "status": project.status,
    }), 201
@projects_bp.post("/<project_id>/plan")
def create_plan(project_id: str):
    from app.models import Project, ProjectPlan  # local import avoids circulars

    project = (
        Project.query
        .filter_by(id=project_id)
        .filter(Project.deleted_at.is_(None))
        .first()
    )
    if not project:
        return jsonify({"error": "Project not found", "id": project_id}), 404

    if project.plan and project.plan.deleted_at is None:
        return jsonify({"error": "Plan already exists", "plan_id": project.plan.id}), 409

    plan = ProjectPlan(
        project_id=project.id,
        wbs={"items": []},
        timeline={"phases": []},
        milestones={"items": []},
        risks={"items": []},
        resources={"team": [], "budget": {}},
        assumptions={"items": []},
        notes="",
    )
    db.session.add(plan)
    db.session.commit()

    return jsonify({"plan_id": plan.id, "project_id": project.id, "status": "DRAFT"}), 201


@projects_bp.get("/<project_id>/plan")
def get_plan(project_id: str):
    """Return the saved ProjectPlan; 404 if none or project missing."""
    from app.models import Project, ProjectPlan  # local import avoids circulars

    project = (
        Project.query
        .filter_by(id=project_id)
        .filter(Project.deleted_at.is_(None))
        .first()
    )
    if not project:
        return jsonify({"error": "Project not found", "id": project_id}), 404

    plan: "ProjectPlan" | None = project.plan if project.plan and project.plan.deleted_at is None else None
    if not plan:
        return jsonify({"error": "Plan not found", "project_id": project_id}), 404

    return jsonify({
        "plan_id": plan.id,
        "project_id": project.id,
        "wbs": plan.wbs,
        "timeline": plan.timeline,
        "milestones": plan.milestones,
        "risks": plan.risks,
        "resources": plan.resources,
        "assumptions": plan.assumptions,
        "notes": plan.notes,
        "created_at": plan.created_at.isoformat() if plan.created_at else None,
        "updated_at": plan.updated_at.isoformat() if plan.updated_at else None,
    }), 200
# ----- update plan by project id (auto-save; PATCH) -----
@projects_bp.patch("/<project_id>/plan")
def patch_plan(project_id: str):
    """Partial update of a saved ProjectPlan (auto-save, Manus spec)."""
    from app.models import Project, ProjectPlan  # local import avoids circulars
    from datetime import datetime, timezone

    payload = request.get_json(silent=True) or {}

    # fetch project
    project = (
        Project.query
        .filter(Project.id == project_id)
        .filter(Project.deleted_at.is_(None))
        .first()
    )
    if not project:
        return jsonify({
            "error": {"code": "NOT_FOUND", "message": "Project not found", "details": {"project_id": project_id}}
        }), 404

    # fetch plan
    plan: "ProjectPlan" | None = project.plan if project.plan and project.plan.deleted_at is None else None
    if not plan:
        return jsonify({
            "error": {"code": "NOT_FOUND", "message": "Plan not found", "details": {"project_id": project_id}}
        }), 404

    # Only update fields provided; ignore unknown keys.
    allowed = {
        "wbs", "timeline", "progress", "budget", "objectives",
        "stakeholders", "risks", "documents", "milestones",
        "resources", "assumptions", "notes"
    }
    changed = False
    for k, v in payload.items():
        if k in allowed:
            setattr(plan, k, v)
            changed = True

    if not changed:
        return jsonify({
            "success": True,
            "message": "No changes",
            "updated_at": datetime.now(timezone.utc).isoformat()
        }), 200

    try:
        db.session.commit()
    except Exception as e:
        try:
            db.session.rollback()
        except Exception:
            pass
        return jsonify({
            "error": {"code": "SERVER_ERROR", "message": "Failed to save plan", "details": str(e)}
        }), 500

    return jsonify({
        "success": True,
        "message": "Plan updated successfully",
        "updated_at": datetime.now(timezone.utc).isoformat()
    }), 200


@projects_bp.get("/<project_id>/plan/validate")
def validate_plan(project_id: str):
    # clear any prior aborted TX
    try:
        db.session.rollback()
    except Exception:
        pass

    from app.models import Project, ProjectPlan  # local import to avoid circulars
    from pydantic import ValidationError
    from app.schemas.project_plan import Plan

    # fetch project
    project = (
        Project.query
        .filter_by(id=project_id)
        .filter(Project.deleted_at.is_(None))
        .first()
    )
    if not project:
        return jsonify({"ok": False, "error": "Project not found", "id": project_id}), 404

    # fetch plan
    plan: ProjectPlan | None = project.plan if project.plan and project.plan.deleted_at is None else None
    if not plan:
        return jsonify({"ok": False, "error": "Plan not found", "project_id": project_id}), 404

    # build payload exactly as schema expects
    payload = {
        "wbs": plan.wbs,
        "timeline": plan.timeline,
        "milestones": plan.milestones,
        "risks": plan.risks,
        "resources": plan.resources,
        "assumptions": plan.assumptions,
        "notes": plan.notes or "",
    }

    try:
        model = Plan(**payload)  # validate
        phases = len(model.wbs.items)
        tasks = sum(len(ph.children) for ph in model.wbs.items)
        return jsonify({
            "ok": True,
            "summary": {
                "phases": phases,
                "tasks": tasks,
                "wbs_version": model.wbs.version,
                "fingerprint": model.wbs.fingerprint,
            }
        }), 200
    except ValidationError as ve:
        return jsonify({"ok": False, "errors": ve.errors()}), 422
    except Exception as e:
        return jsonify({"ok": False, "error": "internal_error", "detail": str(e)}), 500

# ----- POST /projects/:projectId/plan/validate (Manus spec) -----
@projects_bp.post("/<project_id>/plan/validate")
def post_validate_plan(project_id: str):
    """
    Validate the current plan without mutating the DB.
    Returns Manus-compliant envelope.
    """
    # ----- imports (local to avoid circulars) -----
    from app.models import Project, ProjectPlan
    from pydantic import ValidationError

    # ----- user identity (placeholder; replace with auth-derived user) -----
    validated_by = request.headers.get("X-User-Id") or "user_123"

    # ----- fetch project -----
    project = (
        Project.query
        .filter(Project.id == project_id)
        .filter(Project.deleted_at.is_(None))
        .first()
    )
    if not project:
        return jsonify({
            "error": {
                "code": "NOT_FOUND",
                "message": "Project not found",
                "details": {"project_id": project_id}
            }
        }), 404

    # ----- fetch plan -----
    plan: "ProjectPlan" | None = project.plan if project.plan and project.plan.deleted_at is None else None
    if not plan:
        return jsonify({
            "error": {
                "code": "NOT_FOUND",
                "message": "Plan not found",
                "details": {"project_id": project_id}
            }
        }), 404

    # ----- build payload for schema validation -----
    payload = {
        "wbs": plan.wbs,
        "timeline": plan.timeline,
        "milestones": plan.milestones,
        "risks": plan.risks,
        "resources": plan.resources,
        "assumptions": plan.assumptions,
        "notes": plan.notes or "",
    }

    # ----- validate with Pydantic schema -----
    try:
        _ = Plan(**payload)  # validate only
    except ValidationError as ve:
        return jsonify({
            "error": {
                "code": "VALIDATION_ERROR",
                "message": "Invalid plan data",
                "details": ve.errors()
            }
        }), 400
    except Exception as e:
        return jsonify({
            "error": {
                "code": "SERVER_ERROR",
                "message": "Unexpected error during validation",
                "details": {"reason": str(e)}
            }
        }), 500

    # ----- success response (Manus format) -----
    return jsonify({
        "success": True,
        "message": "Plan validated successfully",
        "validated_at": datetime.now(timezone.utc).isoformat(),
        "validated_by": validated_by,
    }), 200

    # ----- gather MarketIQ transcript (optional) -----
    transcript = ""
    thread_id = (pld.get("thread_id") or sid)
    try:
        q = (MiqMessage.query
             .filter_by(thread_id=thread_id)
             .order_by(MiqMessage.created_at.asc()))
        parts = []
        for m in q.all():
            c = m.content
            txt = ""
            if isinstance(c, dict):
                for k in ("text", "message", "content", "body"):
                    v = c.get(k)
                    if isinstance(v, str) and v.strip():
                        txt = v.strip(); break
            elif isinstance(c, str):
                txt = c.strip()
            if txt:
                parts.append(f"{m.role}: {txt}")
        transcript = "\n".join(parts).strip()
    except Exception:
        transcript = ""

    # ----- AI stub plan build -----
    from datetime import datetime, timezone
    import random, hashlib

    base_seed = hashlib.sha256((sid + (transcript[:200] if transcript else "")).encode("utf-8")).hexdigest()
    random.seed(int(base_seed[:8], 16))

    def _rid(prefix: str) -> str:
        return f"{prefix}-{base_seed[random.randint(0, len(base_seed)-7):][:6]}"

    pname = project_name or "Project Plan"
    fp = base_seed[:12]

    payload = {
        "wbs": {
            "version": 1,
            "fingerprint": fp,
            "items": [
                {
                    "id": f"PH-{fp[:6]}",
                    "type": "phase",
                    "name": "Discovery",
                    "children": [
                        {
                            "id": f"TSK-{fp[6:12]}",
                            "type": "task",
                            "name": "Requirements & scope",
                            "assignee": None,
                            "lead_time_days": 3,
                            "depends_on": [],
                            "due_date": None
                        },
                        {
                            "id": f"TSK-{fp[2:8]}",
                            "type": "task",
                            "name": "Architecture / approach",
                            "assignee": None,
                            "lead_time_days": 4,
                            "depends_on": [f"TSK-{fp[6:12]}"],
                            "due_date": None
                        }
                    ]
                },
                {
                    "id": f"PH-{fp[3:9]}",
                    "type": "phase",
                    "name": "Execution",
                    "children": [
                        {
                            "id": f"TSK-{fp[1:7]}",
                            "type": "task",
                            "name": "Implement core",
                            "assignee": None,
                            "lead_time_days": 7,
                            "depends_on": [f"TSK-{fp[2:8]}"],
                            "due_date": None
                        },
                        {
                            "id": f"TSK-{fp[0:6]}",
                            "type": "task",
                            "name": "QA & UAT",
                            "assignee": None,
                            "lead_time_days": 4,
                            "depends_on": [f"TSK-{fp[1:7]}"],
                            "due_date": None
                        }
                    ]
                }
            ],
            "meta": {
                "generated_at": datetime.now(timezone.utc).isoformat(),
                "source": "ai_stub",
            }
        },
        "timeline": {
            "phases": [
                {"id": f"PH-{fp[:6]}", "name": "Discovery"},
                {"id": f"PH-{fp[3:9]}", "name": "Execution"},
            ]
        },
        "milestones": [
            {"id": f"MS-{fp[:6]}", "name": "MVP ready", "depends_on": [f"TSK-{fp[0:6]}"]}
        ],
        "risks": [
            {"id": f"RSK-{fp[1:7]}", "name": "Scope creep", "mitigation": "Tight acceptance criteria", "impact": "medium", "likelihood": "medium"}
        ],
        "resources": {
            "team": [],
            "budget": {"currency": "USD", "total": None}
        },
        "assumptions": [
            {"id": f"ASM-{fp[2:8]}", "text": "Stakeholders available for reviews"}
        ],
        "notes": json.dumps({
            "project_name": pname,
            "context_sample": transcript[:400] if transcript else "",
            "commit_message": commit_message or "",
        }, ensure_ascii=False),
    }

    # ----- validate with Pydantic -----
    try:
        model = Plan(**payload)
    except ValidationError as ve:
        return jsonify({"error": "validation_error", "ok": False, "errors": ve.errors()}), 422

    # ----- dry run / no persist -----
    if dry_run or not persist:
        return jsonify({
            "ok": True,
            "idempotent": False,
            "dry_run": True,
            "project_id": project.id,
            "preview": {
                "summary": {
                    "phases": len(model.wbs.items),
                    "tasks": sum(len(ph.children) for ph in model.wbs.items),
                    "fingerprint": model.wbs.fingerprint,
                },
                "payload": payload,
            }
        }), 200

    # ----- persist plan (create or overwrite) -----
    try:
        if existing_plan and (force_overwrite or policy in ("overwrite", "upsert")):
            # update in place
            existing_plan.wbs = payload["wbs"]
            existing_plan.timeline = payload["timeline"]
            existing_plan.milestones = payload["milestones"]
            existing_plan.risks = payload["risks"]
            existing_plan.resources = payload["resources"]
            existing_plan.assumptions = payload["assumptions"]
            existing_plan.notes = payload["notes"]
            db.session.flush()
            plan_id = existing_plan.id
        else:
            plan = ProjectPlan(
                project_id=project.id,
                wbs=payload["wbs"],
                timeline=payload["timeline"],
                milestones=payload["milestones"],
                risks=payload["risks"],
                resources=payload["resources"],
                assumptions=payload["assumptions"],
                notes=payload["notes"],
            )
            db.session.add(plan)
            db.session.flush()
            plan_id = plan.id

        project.status = "READY"
        # store idempotency info & commit message in idea_snapshot
        idea = project.idea_snapshot or {}
        if idem_key:
            idea["last_idem_key"] = idem_key
        idea["last_plan_id"] = plan_id
        if commit_message:
            idea["last_commit_message"] = commit_message
        project.idea_snapshot = idea

        db.session.commit()

    except Exception as e:
        current_app.logger.exception("generate_ai_plan: persist failed")
        try:
            db.session.rollback()
        except Exception:
            pass
        return jsonify({"error": "db_error", "ok": False, "detail": str(e)}), 500

    # ----- best-effort audit (if table exists) -----
    try:
        from sqlalchemy import text
        db.session.execute(text("""
            INSERT INTO project_events (project_id, event_type, payload, created_at)
            VALUES (:pid, :etype, :payload::jsonb, NOW())
        """), {
            "pid": project.id,
            "etype": "ai_generate",
            "payload": json.dumps({
                "plan_id": plan_id,
                "policy": policy,
                "force_overwrite": force_overwrite,
                "idempotency_key": idem_key,
                "commit_message": commit_message,
            })
        })
        db.session.commit()
    except Exception:
        # ignore if table doesn't exist
        try:
            db.session.rollback()
        except Exception:
            pass

    return jsonify({
        "ok": True,
        "idempotent": False,
        "project_id": project.id,
        "plan_id": plan_id,
        "status": project.status,
        "redirect": f"/ops/project-planning?projectId={project.id}",
    }), 201
