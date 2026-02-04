# backend/app/models.py

import uuid
from datetime import datetime
from sqlalchemy import JSON as SA_JSON, Index
from sqlalchemy.dialects.postgresql import JSONB
from . import db

# Use portable JSON type: in SQLite it's TEXT/JSON shim; on PG it's JSONB if available.
JSONType = SA_JSON

class User(db.Model):
    __tablename__ = 'users'

    # Use UUID strings for primary keys
    id = db.Column(
        db.String(36),
        primary_key=True,
        default=lambda: str(uuid.uuid4())
    )

    # Core user fields
    email = db.Column(db.String(255), unique=True, nullable=False)
    name = db.Column(db.String(255), nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)

    # Stripe integration
    stripe_customer_id = db.Column(db.String(255), nullable=True)
    stripe_subscription_id = db.Column(db.String(255), nullable=True)

    # Subscription & seat limits
    subscription_plan = db.Column(
        db.String(50),
        nullable=False,
        default='essential'
    )
    seat_limit = db.Column(
        db.Integer,
        nullable=False,
        default=1
    )
    max_seats = db.Column(
        db.Integer,
        nullable=False,
        default=1
    )
    unlimited_analysis = db.Column(
        db.Boolean,
        nullable=False,
        default=False
    )
    max_concurrent_sessions = db.Column(
        db.Integer,
        nullable=True
    )

    # Credits
    # None = unlimited, else track remaining
    credits_remaining = db.Column(
        db.Integer,
        nullable=True,
        default=0
    )

    # Referrals & feedback
    referral_code = db.Column(
        db.String(36),
        unique=True,
        nullable=False,
        default=lambda: str(uuid.uuid4())
    )
    referrals_earned = db.Column(
        db.Integer,
        nullable=False,
        default=0
    )
    feedback_earned = db.Column(
        db.Integer,
        nullable=False,
        default=0
    )

    # Timestamps
    created_at = db.Column(
        db.DateTime,
        nullable=False,
        default=datetime.utcnow
    )
    updated_at = db.Column(
        db.DateTime,
        nullable=False,
        default=datetime.utcnow,
        onupdate=datetime.utcnow
    )

    def to_dict(self):
        return {
            'id': self.id,
            'email': self.email,
            'name': self.name,
            'subscription_plan': self.subscription_plan,
            'seat_limit': self.seat_limit,
            'max_seats': self.max_seats,
            'unlimited_analysis': self.unlimited_analysis,
            'max_concurrent_sessions': self.max_concurrent_sessions,
            'credits_remaining': self.credits_remaining,
            'referral_code': self.referral_code,
            'referrals_earned': self.referrals_earned,
            'feedback_earned': self.feedback_earned,
            'stripe_customer_id': self.stripe_customer_id,
            'stripe_subscription_id': self.stripe_subscription_id,
            'created_at': self.created_at.isoformat(),
            'updated_at': self.updated_at.isoformat(),
        }


# === Market IQ Threading & Context Models ===

class MiqMessage(db.Model):
    __tablename__ = "miq_messages"
    id          = db.Column(db.Integer, primary_key=True)
    thread_id   = db.Column(db.String(64), index=True, nullable=False)
    session_id  = db.Column(db.String(64), index=True, nullable=True)
    user_id     = db.Column(db.String(64), index=True, nullable=True)
    role        = db.Column(db.String(16), nullable=False)  # 'user' | 'assistant' | 'system'
    content     = db.Column(JSONType, nullable=False)       # {text, parts...} or plain string
    meta        = db.Column(JSONType, nullable=True)
    created_at  = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, index=True)

class MiqThread(db.Model):
    __tablename__ = "miq_threads"
    id                   = db.Column(db.Integer, primary_key=True)
    thread_id            = db.Column(db.String(64), unique=True, index=True, nullable=False)
    user_id              = db.Column(db.String(64), index=True, nullable=True)
    session_id           = db.Column(db.String(64), index=True, nullable=True)
    adopted_analysis_id  = db.Column(db.String(64), index=True, nullable=True)  # current/adopted snapshot
    created_at           = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, index=True)
    updated_at           = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow, index=True)


class MiqThreadAnalysisLink(db.Model):
    """Many-to-many attachment between MiqThread and MiqAnalysis.

    Allows showing analyses created pre-thread (session-only) in a later thread,
    and optionally attaching analyses from other threads (same owner) for
    comparison, without altering the MiqAnalysis.thread_id provenance.
    """

    __tablename__ = "miq_thread_analysis_links"

    id = db.Column(db.Integer, primary_key=True)
    # store the external identifiers used everywhere else in the codebase
    thread_key = db.Column(db.String(64), nullable=False, index=True)      # MiqThread.thread_id
    analysis_key = db.Column(db.String(64), nullable=False, index=True)    # MiqAnalysis.analysis_id

    attached_by_user_id = db.Column(db.String(64), nullable=True, index=True)
    attached_by_session_id = db.Column(db.String(64), nullable=True, index=True)

    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, index=True)

    __table_args__ = (
        db.UniqueConstraint("thread_key", "analysis_key", name="uq_miq_thread_analysis_link"),
    )


class MiqAnalysis(db.Model):
    __tablename__ = "miq_analyses"
    id                       = db.Column(db.Integer, primary_key=True)
    analysis_id              = db.Column(db.String(64), unique=True, index=True, nullable=False)
    thread_id                = db.Column(db.String(64), index=True, nullable=True)
    session_id               = db.Column(db.String(64), index=True, nullable=True)
    derived_from_scenario_id = db.Column(db.String(64), index=True, nullable=True)  # links scenario-derived analyses
    result                   = db.Column(JSONType, nullable=False)     # full scorecard payload
    meta                     = db.Column(JSONType, nullable=True)
    created_at               = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, index=True)

class MiqScenario(db.Model):
    __tablename__ = "miq_scenarios"
    id                  = db.Column(db.Integer, primary_key=True)
    scenario_id         = db.Column(db.String(64), unique=True, index=True, nullable=False)
    thread_id           = db.Column(db.String(64), index=True, nullable=True)
    session_id          = db.Column(db.String(64), index=True, nullable=True)
    based_on            = db.Column(db.String(64), index=True, nullable=True)  # analysis_id/score baseline
    deltas              = db.Column(JSONType, nullable=False)    # user levers / changes
    derived_analysis_id = db.Column(db.String(64), index=True, nullable=True)  # links to run result
    result              = db.Column(JSONType, nullable=True)     # scenario scorecard result (optional cache)
    label               = db.Column(db.String(128), nullable=True)
    meta                = db.Column(JSONType, nullable=True)
    created_at          = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, index=True)

# ==== BEGIN PROJECT PLANNING MODELS (sekki) ==================================
# Why: enterprise-safe IDs (UUID v4) + soft delete for audit/restore.

# Prefer JSONB on PG, fallback to generic JSON elsewhere (JSONType defined above)
try:
    JSONTypePP = JSONB
except Exception:  # pragma: no cover
    JSONTypePP = JSONType

class Project(db.Model):
    __tablename__ = "projects"

    id   = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    sid  = db.Column(db.String(128), nullable=False, index=True)

    status = db.Column(db.String(16), nullable=False, index=True, default="PENDING")
    idea_snapshot          = db.Column(JSONTypePP, nullable=True)
    business_case_snapshot = db.Column(JSONTypePP, nullable=True)

    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, index=True)
    updated_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow, index=True)
    deleted_at = db.Column(db.DateTime, nullable=True, index=True)  # NULL = active

    plan = db.relationship("ProjectPlan", uselist=False, back_populates="project", cascade="all, delete-orphan")

    def to_dict(self):
        return {
            "id": self.id, "sid": self.sid, "status": self.status,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }

class ProjectPlan(db.Model):
    __tablename__ = "project_plans"

    id         = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    project_id = db.Column(db.String(36), db.ForeignKey("projects.id", ondelete="CASCADE"), unique=True, nullable=False)

    wbs         = db.Column(JSONTypePP, nullable=False)
    timeline    = db.Column(JSONTypePP, nullable=False)
    milestones  = db.Column(JSONTypePP, nullable=False)
    risks       = db.Column(JSONTypePP, nullable=False)
    resources   = db.Column(JSONTypePP, nullable=False)
    assumptions = db.Column(JSONTypePP, nullable=False)
    notes       = db.Column(db.Text, nullable=True)

    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, index=True)
    updated_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow, index=True)
    deleted_at = db.Column(db.DateTime, nullable=True, index=True)  # NULL = active

    project = db.relationship("Project", back_populates="plan", lazy="joined")

# Partial index for fast active queries (Postgres only; safe no-op on others during migration gen)
try:
    Index(
        "ix_projects_sid_status_active",
        Project.sid, Project.status,
        postgresql_where=(Project.deleted_at.is_(None))
    )
except Exception:
    pass
# ==== END PROJECT PLANNING MODELS (sekki) ====================================


# ==== BEGIN AI AGENT SYSTEM MODELS (sekki) ===================================
# Why: Structured evaluation framework for project ideas/initiatives.
# Separate from Market IQ models (which are intake-specific).

class ScoringFramework(db.Model):
    """
    Evaluation criteria framework for structured analyses.

    Defines the dimensions, weights, and scoring methodology for evaluating
    ideas/initiatives. Can be system-provided or user-created.
    """
    __tablename__ = "scoring_frameworks"

    id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = db.Column(db.String(36), db.ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)

    # Framework metadata
    name = db.Column(db.String(255), nullable=False)
    description = db.Column(db.Text, nullable=True)

    # Framework definition
    criteria = db.Column(JSONTypePP, nullable=False)
    """
    Criteria structure:
    [
        {
            "id": "market_demand",
            "name": "Market Demand",
            "description": "Size and urgency of target market",
            "weight": 0.25,
            "factors": [
                {"id": "audience_size", "name": "Target Audience Size", "description": "..."},
                {"id": "willingness_to_pay", "name": "Willingness to Pay", "description": "..."}
            ]
        },
        ...
    ]
    """

    scoring_range = db.Column(JSONTypePP, nullable=False, default=lambda: {"min": 0, "max": 100})
    scale_labels = db.Column(JSONTypePP, nullable=True)  # {"0-25": "Weak", "26-50": "Moderate", ...}

    # Visibility & reusability
    is_public = db.Column(db.Boolean, nullable=False, default=False, index=True)
    is_system = db.Column(db.Boolean, nullable=False, default=False, index=True)
    usage_count = db.Column(db.Integer, nullable=False, default=0)

    # Versioning
    version = db.Column(db.Integer, nullable=False, default=1)
    parent_id = db.Column(db.String(36), db.ForeignKey("scoring_frameworks.id", ondelete="SET NULL"), nullable=True, index=True)

    # Timestamps
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, index=True)
    updated_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow, index=True)
    deleted_at = db.Column(db.DateTime, nullable=True, index=True)

    def to_dict(self):
        return {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "is_public": self.is_public,
            "is_system": self.is_system,
            "usage_count": self.usage_count,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


class AgentThread(db.Model):
    """
    AI Agent conversation threads within projects.

    Separate from MiqThread (which is for Market IQ intake).
    Each project can have multiple threads representing different
    ideas, initiatives, or evaluation tracks.
    """
    __tablename__ = "agent_threads"

    id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    project_id = db.Column(db.String(36), db.ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True)
    user_id = db.Column(db.String(36), db.ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)

    # Thread metadata
    name = db.Column(db.String(255), nullable=False)
    description = db.Column(db.Text, nullable=True)
    status = db.Column(db.String(16), nullable=False, default="active", index=True)  # active | archived | completed

    # Context storage
    context = db.Column(JSONTypePP, nullable=True)
    conversation_history = db.Column(JSONTypePP, nullable=True)

    # Activity tracking
    last_activity_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, index=True)

    # Timestamps
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, index=True)
    updated_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow, index=True)
    deleted_at = db.Column(db.DateTime, nullable=True, index=True)

    # Relationships
    project = db.relationship("Project", backref="agent_threads", lazy="joined")
    analyses = db.relationship("Analysis", back_populates="thread", cascade="all, delete-orphan")

    def to_dict(self):
        return {
            "id": self.id,
            "project_id": self.project_id,
            "name": self.name,
            "status": self.status,
            "last_activity_at": self.last_activity_at.isoformat() if self.last_activity_at else None,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


class Analysis(db.Model):
    """
    Structured business evaluation using scoring frameworks.

    Separate from MiqAnalysis (which is Market IQ scorecard specific).
    Each analysis applies a ScoringFramework to evaluate an idea/initiative
    within an AgentThread.
    """
    __tablename__ = "analyses"

    id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    thread_id = db.Column(db.String(36), db.ForeignKey("agent_threads.id", ondelete="CASCADE"), nullable=False, index=True)
    scoring_framework_id = db.Column(db.String(36), db.ForeignKey("scoring_frameworks.id", ondelete="RESTRICT"), nullable=False, index=True)
    user_id = db.Column(db.String(36), db.ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)

    # Analysis metadata
    name = db.Column(db.String(255), nullable=False)
    description = db.Column(db.Text, nullable=True)

    # Analysis results
    scores = db.Column(JSONTypePP, nullable=False)  # {"criterion_id": {"score": 85, "weight": 0.25, "rationale": "..."}}
    overall_score = db.Column(db.Float, nullable=False, index=True)  # Weighted aggregate (0-100)

    # Status & ranking
    status = db.Column(db.String(16), nullable=False, default="draft", index=True)  # draft | completed | archived
    rank = db.Column(db.Integer, nullable=True, index=True)  # Relative ranking within thread (1=best)

    # SWOT analysis
    strengths = db.Column(JSONTypePP, nullable=True)  # Array of strings
    weaknesses = db.Column(JSONTypePP, nullable=True)  # Array of strings
    opportunities = db.Column(JSONTypePP, nullable=True)  # Array of strings
    threats = db.Column(JSONTypePP, nullable=True)  # Array of strings
    recommendations = db.Column(JSONTypePP, nullable=True)  # Array of strings

    # Context & provenance
    input_context = db.Column(JSONTypePP, nullable=True)
    meta = db.Column(JSONTypePP, nullable=True)

    # Timestamps
    analyzed_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, index=True)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, index=True)
    updated_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow, index=True)
    deleted_at = db.Column(db.DateTime, nullable=True, index=True)

    # Relationships
    thread = db.relationship("AgentThread", back_populates="analyses")
    scoring_framework = db.relationship("ScoringFramework", backref="analyses")

    def to_dict(self):
        return {
            "id": self.id,
            "thread_id": self.thread_id,
            "name": self.name,
            "overall_score": self.overall_score,
            "scores": self.scores,  # Component scores (financial_health, operational_efficiency, etc.)
            "status": self.status,
            "rank": self.rank,
            "analyzed_at": self.analyzed_at.isoformat() if self.analyzed_at else None,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }

# ==== END AI AGENT SYSTEM MODELS (sekki) =====================================
