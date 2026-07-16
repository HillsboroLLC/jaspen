# backend/app/models.py

import json
import uuid
from datetime import datetime, timezone
from . import db


class Lead(db.Model):
    __tablename__ = 'leads'

    id = db.Column(
        db.String(36),
        primary_key=True,
        default=lambda: str(uuid.uuid4()),
    )
    email = db.Column(db.String(255), nullable=False, index=True)
    normalized_email = db.Column(db.String(255), nullable=False, unique=True, index=True)
    source = db.Column(db.String(80), nullable=False, default='unknown')
    first_name = db.Column(db.String(120), nullable=True)
    last_name = db.Column(db.String(120), nullable=True)
    company = db.Column(db.String(160), nullable=True)
    title = db.Column(db.String(160), nullable=True)
    utm_source = db.Column(db.String(120), nullable=True)
    utm_medium = db.Column(db.String(120), nullable=True)
    utm_campaign = db.Column(db.String(160), nullable=True)
    referrer = db.Column(db.String(512), nullable=True)
    created_at = db.Column(
        db.DateTime,
        nullable=False,
        default=datetime.utcnow,
        index=True,
    )
    updated_at = db.Column(
        db.DateTime,
        nullable=False,
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
    )

    __table_args__ = (
        db.Index('ix_leads_source_created_at', 'source', 'created_at'),
    )


class LeadAttributionEvent(db.Model):
    __tablename__ = 'lead_attribution_events'

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    lead_id = db.Column(
        db.String(36),
        db.ForeignKey('leads.id', ondelete='CASCADE'),
        nullable=False,
        index=True,
    )
    source = db.Column(db.String(80), nullable=False, default='unknown', index=True)
    first_name = db.Column(db.String(120), nullable=True)
    last_name = db.Column(db.String(120), nullable=True)
    company = db.Column(db.String(160), nullable=True)
    title = db.Column(db.String(160), nullable=True)
    utm_source = db.Column(db.String(120), nullable=True)
    utm_medium = db.Column(db.String(120), nullable=True)
    utm_campaign = db.Column(db.String(160), nullable=True)
    referrer = db.Column(db.String(512), nullable=True)
    marketing_opt_in = db.Column(db.Boolean, nullable=False, default=False)
    email_delivery_requested = db.Column(db.Boolean, nullable=False, default=False)
    created_at = db.Column(
        db.DateTime,
        nullable=False,
        default=datetime.utcnow,
        index=True,
    )

    __table_args__ = (
        db.Index('ix_lead_attribution_source_created', 'source', 'created_at'),
    )


class LeadEmailDelivery(db.Model):
    __tablename__ = 'lead_email_deliveries'

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    lead_id = db.Column(
        db.String(36),
        db.ForeignKey('leads.id', ondelete='CASCADE'),
        nullable=False,
        index=True,
    )
    attribution_event_id = db.Column(
        db.Integer,
        db.ForeignKey('lead_attribution_events.id', ondelete='SET NULL'),
        nullable=True,
        index=True,
    )
    email = db.Column(db.String(255), nullable=False, index=True)
    email_type = db.Column(db.String(80), nullable=False, index=True)
    status = db.Column(db.String(32), nullable=False, default='sent', index=True)
    provider_message = db.Column(db.String(255), nullable=True)
    created_at = db.Column(
        db.DateTime,
        nullable=False,
        default=datetime.utcnow,
        index=True,
    )
    sent_at = db.Column(db.DateTime, nullable=True)


class LeadDecisionProfile(db.Model):
    __tablename__ = 'lead_decision_profiles'

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    lead_id = db.Column(
        db.String(36),
        db.ForeignKey('leads.id', ondelete='CASCADE'),
        nullable=False,
        index=True,
    )
    attribution_event_id = db.Column(
        db.Integer,
        db.ForeignKey('lead_attribution_events.id', ondelete='SET NULL'),
        nullable=True,
        index=True,
    )
    user_id = db.Column(
        db.String(36),
        db.ForeignKey('users.id', ondelete='SET NULL'),
        nullable=True,
        index=True,
    )
    email = db.Column(db.String(255), nullable=False, index=True)
    normalized_email = db.Column(db.String(255), nullable=False, index=True)
    source = db.Column(db.String(80), nullable=False, default='decision-style-assessment', index=True)
    answers = db.Column(db.JSON, nullable=False)
    client_style_key = db.Column(db.String(80), nullable=True)
    verified_style_key = db.Column(db.String(80), nullable=False, index=True)
    style_name = db.Column(db.String(120), nullable=False)
    is_fallback = db.Column(db.Boolean, nullable=False, default=False)
    affinity = db.Column(db.JSON, nullable=False, default=dict)
    created_at = db.Column(
        db.DateTime,
        nullable=False,
        default=datetime.utcnow,
        index=True,
    )
    completed_at = db.Column(
        db.DateTime,
        nullable=False,
        default=datetime.utcnow,
        index=True,
    )
    updated_at = db.Column(
        db.DateTime,
        nullable=False,
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
    )
    version = db.Column(db.Integer, nullable=False, default=1)
    is_current = db.Column(db.Boolean, nullable=False, default=True, index=True)

    __table_args__ = (
        db.Index('ix_lead_decision_profiles_user_current', 'user_id', 'is_current'),
        db.Index('ix_lead_decision_profiles_email_current', 'normalized_email', 'is_current'),
    )


class LeadDecisionProfileResponse(db.Model):
    __tablename__ = 'lead_decision_profile_responses'

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    decision_profile_id = db.Column(
        db.Integer,
        db.ForeignKey('lead_decision_profiles.id', ondelete='CASCADE'),
        nullable=False,
        index=True,
    )
    question_id = db.Column(db.String(80), nullable=False)
    answer_id = db.Column(db.String(80), nullable=False)
    question = db.Column(db.Text, nullable=False)
    tendency = db.Column(db.String(120), nullable=False)
    answer_label = db.Column(db.String(255), nullable=False)
    meaning = db.Column(db.Text, nullable=False)
    created_at = db.Column(
        db.DateTime,
        nullable=False,
        default=datetime.utcnow,
        index=True,
    )

    __table_args__ = (
        db.UniqueConstraint('decision_profile_id', 'question_id', name='uq_decision_profile_response_question'),
    )


class EmailSuppression(db.Model):
    __tablename__ = 'email_suppressions'

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    email = db.Column(db.String(255), nullable=False, index=True)
    normalized_email = db.Column(db.String(255), nullable=False, index=True)
    scope = db.Column(db.String(32), nullable=False, default='marketing', index=True)
    reason = db.Column(db.String(120), nullable=True)
    created_at = db.Column(
        db.DateTime,
        nullable=False,
        default=datetime.utcnow,
        index=True,
    )

    __table_args__ = (
        db.UniqueConstraint('normalized_email', 'scope', name='uq_email_suppressions_email_scope'),
    )


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
    industry = db.Column(db.String(120), nullable=True)
    company_size = db.Column(db.String(32), nullable=True)

    # Stripe integration
    stripe_customer_id = db.Column(db.String(255), nullable=True)
    stripe_subscription_id = db.Column(db.String(255), nullable=True)
    subscription_status = db.Column(db.String(32), nullable=True)
    active_organization_id = db.Column(
        db.String(36),
        db.ForeignKey('organizations.id', ondelete='SET NULL'),
        nullable=True,
        index=True,
    )

    # Subscription & seat limits
    subscription_plan = db.Column(
        db.String(50),
        nullable=False,
        default='free'
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
        default=500
    )
    credits_reset_at = db.Column(
        db.DateTime,
        nullable=True,
    )
    failed_login_attempts = db.Column(
        db.Integer,
        nullable=False,
        default=0,
    )
    locked_until = db.Column(
        db.DateTime,
        nullable=True,
    )
    mfa_secret = db.Column(
        db.String(512),
        nullable=True,
    )
    mfa_enabled = db.Column(
        db.Boolean,
        default=False,
        nullable=False,
    )
    mfa_backup_codes = db.Column(
        db.JSON,
        nullable=True,
    )
    auth_token_version = db.Column(
        db.Integer,
        nullable=False,
        default=0,
    )
    email_verified = db.Column(
        db.Boolean,
        nullable=False,
        default=False,
    )
    email_verified_at = db.Column(
        db.DateTime,
        nullable=True,
    )
    email_verification_sent_at = db.Column(
        db.DateTime,
        nullable=True,
    )
    password_reset_requested_at = db.Column(
        db.DateTime,
        nullable=True,
    )
    password_reset_version = db.Column(
        db.Integer,
        nullable=False,
        default=0,
    )
    access_approval_status = db.Column(
        db.String(32),
        nullable=False,
        default='approved',
    )
    access_approved_at = db.Column(
        db.DateTime,
        nullable=True,
    )
    access_reviewed_by_user_id = db.Column(
        db.String(36),
        db.ForeignKey('users.id', ondelete='SET NULL'),
        nullable=True,
        index=True,
    )
    deactivated_at = db.Column(
        db.DateTime,
        nullable=True,
    )
    deactivated_by_user_id = db.Column(
        db.String(36),
        db.ForeignKey('users.id', ondelete='SET NULL'),
        nullable=True,
        index=True,
    )
    deactivation_reason = db.Column(
        db.String(500),
        nullable=True,
    )
    recovery_expires_at = db.Column(
        db.DateTime,
        nullable=True,
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
    referred_by_user_id = db.Column(
        db.String(36),
        db.ForeignKey('users.id', ondelete='SET NULL'),
        nullable=True,
        index=True,
    )
    signup_referral_code_used = db.Column(
        db.String(36),
        nullable=True,
    )
    ui_preferences = db.Column(
        db.JSON,
        nullable=True,
        default=dict,
    )

    # Timestamps
    created_at = db.Column(
        db.DateTime,
        nullable=False,
        default=datetime.utcnow,
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
            'industry': self.industry,
            'company_size': self.company_size,
            'subscription_plan': self.subscription_plan,
            'seat_limit': self.seat_limit,
            'max_seats': self.max_seats,
            'unlimited_analysis': self.unlimited_analysis,
            'max_concurrent_sessions': self.max_concurrent_sessions,
            'credits_remaining': self.credits_remaining,
            'credits_reset_at': self.credits_reset_at.isoformat() if self.credits_reset_at else None,
            'auth_token_version': self.auth_token_version,
            'email_verified': bool(self.email_verified),
            'email_verified_at': self.email_verified_at.isoformat() if self.email_verified_at else None,
            'email_verification_sent_at': self.email_verification_sent_at.isoformat() if self.email_verification_sent_at else None,
            'password_reset_requested_at': self.password_reset_requested_at.isoformat() if self.password_reset_requested_at else None,
            'password_reset_version': self.password_reset_version,
            'access_approval_status': self.access_approval_status,
            'access_approved_at': self.access_approved_at.isoformat() if self.access_approved_at else None,
            'access_reviewed_by_user_id': self.access_reviewed_by_user_id,
            'deactivated_at': self.deactivated_at.isoformat() if self.deactivated_at else None,
            'deactivated_by_user_id': self.deactivated_by_user_id,
            'deactivation_reason': self.deactivation_reason,
            'recovery_expires_at': self.recovery_expires_at.isoformat() if self.recovery_expires_at else None,
            'referral_code': self.referral_code,
            'referrals_earned': self.referrals_earned,
            'feedback_earned': self.feedback_earned,
            'referred_by_user_id': self.referred_by_user_id,
            'signup_referral_code_used': self.signup_referral_code_used,
            'ui_preferences': self.ui_preferences if isinstance(self.ui_preferences, dict) else {},
            'stripe_customer_id': self.stripe_customer_id,
            'stripe_subscription_id': self.stripe_subscription_id,
            'subscription_status': self.subscription_status,
            'active_organization_id': self.active_organization_id,
            'created_at': self.created_at.isoformat(),
            'updated_at': self.updated_at.isoformat(),
        }


class Organization(db.Model):
    __tablename__ = 'organizations'

    id = db.Column(
        db.String(36),
        primary_key=True,
        default=lambda: str(uuid.uuid4())
    )
    name = db.Column(db.String(255), nullable=False)
    slug = db.Column(db.String(255), unique=True, nullable=True)
    owner_user_id = db.Column(
        db.String(36),
        db.ForeignKey('users.id', ondelete='SET NULL'),
        nullable=True,
        index=True,
    )
    plan_key = db.Column(
        db.String(50),
        nullable=False,
        default='team',
        index=True,
    )
    max_admin_seats = db.Column(
        db.Integer,
        nullable=False,
        default=2,
    )
    max_total_paid_seats = db.Column(
        db.Integer,
        nullable=True,
        default=None,
    )
    max_creator_seats = db.Column(
        db.Integer,
        nullable=False,
        default=5,
    )
    max_collaborator_seats = db.Column(
        db.Integer,
        nullable=False,
        default=10,
    )
    seat_policy_overrides = db.Column(
        db.JSON,
        nullable=True,
    )
    settings = db.Column(
        db.JSON,
        nullable=True,
        default=dict,
    )
    created_at = db.Column(
        db.DateTime,
        nullable=False,
        default=datetime.utcnow,
        index=True,
    )
    updated_at = db.Column(
        db.DateTime,
        nullable=False,
        default=datetime.utcnow,
        onupdate=datetime.utcnow
    )
    members = db.relationship('OrganizationMember', backref='organization', lazy='dynamic')

    @property
    def owner_id(self):
        return self.owner_user_id

    @owner_id.setter
    def owner_id(self, value):
        self.owner_user_id = value

    @property
    def plan(self):
        return self.plan_key

    @plan.setter
    def plan(self, value):
        self.plan_key = value

    def to_dict(self):
        return {
            'id': self.id,
            'name': self.name,
            'slug': self.slug,
            'owner_id': self.owner_user_id,
            'plan': self.plan_key,
            'owner_user_id': self.owner_user_id,
            'plan_key': self.plan_key,
            'max_admin_seats': self.max_admin_seats,
            'max_total_paid_seats': self.max_total_paid_seats,
            'max_creator_seats': self.max_creator_seats,
            'max_collaborator_seats': self.max_collaborator_seats,
            'seat_policy_overrides': self.seat_policy_overrides if isinstance(self.seat_policy_overrides, dict) else {},
            'settings': self.settings if isinstance(self.settings, dict) else {},
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None,
        }


class AppSetting(db.Model):
    __tablename__ = 'app_settings'

    key = db.Column(db.String(100), primary_key=True)
    value = db.Column(db.JSON, nullable=False, default=dict)
    updated_at = db.Column(
        db.DateTime,
        nullable=False,
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
    )

    def to_dict(self):
        return {
            'key': self.key,
            'value': self.value if isinstance(self.value, dict) else {},
            'updated_at': self.updated_at.isoformat() if self.updated_at else None,
        }


class OrganizationMember(db.Model):
    __tablename__ = 'organization_members'

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    organization_id = db.Column(
        db.String(36),
        db.ForeignKey('organizations.id', ondelete='CASCADE'),
        nullable=False,
        index=True,
    )
    user_id = db.Column(
        db.String(36),
        db.ForeignKey('users.id', ondelete='CASCADE'),
        nullable=False,
        index=True,
    )
    role = db.Column(db.String(32), nullable=False, default='collaborator', index=True)
    status = db.Column(db.String(32), nullable=False, default='active', index=True)
    invited_by_user_id = db.Column(
        db.String(36),
        db.ForeignKey('users.id', ondelete='SET NULL'),
        nullable=True,
        index=True,
    )
    joined_at = db.Column(db.DateTime, nullable=True)
    last_active_at = db.Column(db.DateTime, nullable=True)
    created_at = db.Column(
        db.DateTime,
        nullable=False,
        default=datetime.utcnow,
        index=True,
    )
    updated_at = db.Column(
        db.DateTime,
        nullable=False,
        default=datetime.utcnow,
        onupdate=datetime.utcnow
    )

    __table_args__ = (
        db.UniqueConstraint('organization_id', 'user_id', name='uq_org_members_organization_user'),
    )

    def to_dict(self):
        return {
            'id': self.id,
            'organization_id': self.organization_id,
            'user_id': self.user_id,
            'role': self.role,
            'status': self.status,
            'invited_by': self.invited_by_user_id,
            'invited_by_user_id': self.invited_by_user_id,
            'joined_at': self.joined_at.isoformat() if self.joined_at else None,
            'last_active_at': self.last_active_at.isoformat() if self.last_active_at else None,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None,
        }


class OrganizationInvitation(db.Model):
    __tablename__ = 'organization_invitations'

    id = db.Column(
        db.String(36),
        primary_key=True,
        default=lambda: str(uuid.uuid4())
    )
    organization_id = db.Column(
        db.String(36),
        db.ForeignKey('organizations.id', ondelete='CASCADE'),
        nullable=False,
        index=True,
    )
    email = db.Column(db.String(255), nullable=False, index=True)
    role = db.Column(db.String(32), nullable=False, default='collaborator')
    token = db.Column(db.String(128), nullable=False, unique=True, index=True, default=lambda: str(uuid.uuid4()))
    status = db.Column(db.String(32), nullable=False, default='pending', index=True)
    invited_by_user_id = db.Column(
        db.String(36),
        db.ForeignKey('users.id', ondelete='SET NULL'),
        nullable=True,
        index=True,
    )
    accepted_by_user_id = db.Column(
        db.String(36),
        db.ForeignKey('users.id', ondelete='SET NULL'),
        nullable=True,
        index=True,
    )
    expires_at = db.Column(db.DateTime, nullable=True, index=True)
    accepted_at = db.Column(db.DateTime, nullable=True)
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
            'organization_id': self.organization_id,
            'email': self.email,
            'role': self.role,
            'token': self.token,
            'status': self.status,
            'invited_by': self.invited_by_user_id,
            'invited_by_user_id': self.invited_by_user_id,
            'accepted_by_user_id': self.accepted_by_user_id,
            'expires_at': self.expires_at.isoformat() if self.expires_at else None,
            'accepted_at': self.accepted_at.isoformat() if self.accepted_at else None,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None,
        }


# Compatibility alias for refined naming.
Invitation = OrganizationInvitation


class UserSession(db.Model):
    __tablename__ = 'user_sessions'

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    user_id = db.Column(db.String(36), db.ForeignKey('users.id', ondelete='CASCADE'), nullable=False, index=True)
    session_id = db.Column(db.String(255), nullable=False)
    name = db.Column(db.String(255), nullable=False, default='Jaspen Intake')
    document_type = db.Column(db.String(100), nullable=False, default='strategy')
    status = db.Column(db.String(50), nullable=False, default='in_progress')
    organization_id = db.Column(
        db.String(36),
        db.ForeignKey('organizations.id', ondelete='SET NULL'),
        nullable=True,
        index=True,
    )
    created_by_user_id = db.Column(
        db.String(36),
        db.ForeignKey('users.id', ondelete='SET NULL'),
        nullable=True,
        index=True,
    )
    visibility = db.Column(db.String(32), nullable=False, default='private', index=True)
    shared_with_user_ids = db.Column(db.JSON, nullable=True, default=list)
    payload = db.Column(db.JSON, nullable=False, default=dict)
    scenarios_json = db.Column(db.JSON, nullable=True, default=dict)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)
    # Soft delete: when the user clicks "Delete from my history" we set
    # archived_at + purge_after. The row stays in the table (so we can undo
    # within the grace window) but is hidden from history queries.
    archived_at = db.Column(db.DateTime, nullable=True, index=True)
    purge_after = db.Column(db.DateTime, nullable=True, index=True)

    __table_args__ = (
        db.UniqueConstraint('user_id', 'session_id', name='uq_user_sessions_user_id_session_id'),
        db.Index('ix_user_sessions_user_id_updated_at', 'user_id', 'updated_at'),
        db.Index('ix_user_sessions_user_archived', 'user_id', 'archived_at'),
    )


class UserAuthSession(db.Model):
    __tablename__ = 'user_auth_sessions'

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    user_id = db.Column(db.String(36), db.ForeignKey('users.id', ondelete='CASCADE'), nullable=False, index=True)
    token_jti = db.Column(db.String(128), nullable=False, unique=True, index=True)
    organization_id = db.Column(
        db.String(36),
        db.ForeignKey('organizations.id', ondelete='SET NULL'),
        nullable=True,
        index=True,
    )
    issued_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, index=True)
    expires_at = db.Column(db.DateTime, nullable=True, index=True)
    revoked_at = db.Column(db.DateTime, nullable=True, index=True)
    ip_address = db.Column(db.String(128), nullable=True)
    user_agent = db.Column(db.String(512), nullable=True)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    __table_args__ = (
        db.Index('ix_user_auth_sessions_user_revoked', 'user_id', 'revoked_at'),
    )


class UserDataset(db.Model):
    __tablename__ = 'user_datasets'

    id = db.Column(
        db.String(36),
        primary_key=True,
        default=lambda: str(uuid.uuid4())
    )
    user_id = db.Column(
        db.String(36),
        db.ForeignKey('users.id', ondelete='CASCADE'),
        nullable=False,
        index=True,
    )
    filename = db.Column(db.String(255), nullable=False)
    row_count = db.Column(db.Integer, nullable=False)
    column_names = db.Column(db.JSON, nullable=False)
    data_preview = db.Column(db.JSON, nullable=True)
    status = db.Column(db.String(50), nullable=False, default='ready')
    created_at = db.Column(
        db.DateTime,
        nullable=False,
        default=datetime.utcnow
    )

    def to_dict(self):
        return {
            'id': self.id,
            'user_id': self.user_id,
            'filename': self.filename,
            'row_count': self.row_count,
            'column_names': self.column_names if isinstance(self.column_names, list) else [],
            'data_preview': self.data_preview if isinstance(self.data_preview, list) else [],
            'status': self.status,
            'created_at': self.created_at.isoformat() if self.created_at else None,
        }


class BatchIdeaUpload(db.Model):
    __tablename__ = 'batch_idea_uploads'

    id = db.Column(
        db.String(36),
        primary_key=True,
        default=lambda: str(uuid.uuid4())
    )
    user_id = db.Column(
        db.String(36),
        db.ForeignKey('users.id', ondelete='CASCADE'),
        nullable=False,
        index=True,
    )
    organization_id = db.Column(
        db.String(36),
        db.ForeignKey('organizations.id', ondelete='SET NULL'),
        nullable=True,
        index=True,
    )
    filename = db.Column(db.String(255), nullable=False)
    ideas_json = db.Column(db.Text, nullable=False)
    status = db.Column(db.String(32), nullable=False, default='uploaded', index=True)
    ranking_result_json = db.Column(db.Text, nullable=True)
    created_at = db.Column(
        db.DateTime,
        nullable=False,
        default=datetime.utcnow,
        index=True,
    )
    updated_at = db.Column(
        db.DateTime,
        nullable=False,
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
    )

    @staticmethod
    def _load_json_blob(raw, fallback):
        if not raw:
            return fallback
        try:
            parsed = json.loads(raw)
        except Exception:
            return fallback
        return parsed

    def ideas(self):
        parsed = self._load_json_blob(self.ideas_json, [])
        return parsed if isinstance(parsed, list) else []

    def ranking_result(self):
        parsed = self._load_json_blob(self.ranking_result_json, {})
        return parsed if isinstance(parsed, dict) else {}

    def to_dict(self):
        return {
            'id': self.id,
            'user_id': self.user_id,
            'organization_id': self.organization_id,
            'filename': self.filename,
            'ideas': self.ideas(),
            'status': self.status,
            'ranking_result': self.ranking_result(),
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None,
        }


class SavedStarter(db.Model):
    __tablename__ = 'saved_starters'

    id = db.Column(
        db.String(36),
        primary_key=True,
        default=lambda: str(uuid.uuid4())
    )
    user_id = db.Column(
        db.String(36),
        db.ForeignKey('users.id', ondelete='CASCADE'),
        nullable=False,
        index=True,
    )
    organization_id = db.Column(
        db.String(36),
        db.ForeignKey('organizations.id', ondelete='SET NULL'),
        nullable=True,
        index=True,
    )
    name = db.Column(db.String(255), nullable=False)
    description = db.Column(db.Text, nullable=True)
    objective = db.Column(db.String(100), nullable=True)
    lever_defaults = db.Column(db.JSON, nullable=True)
    scoring_weights = db.Column(db.JSON, nullable=True)
    intake_context = db.Column(db.JSON, nullable=True)
    is_shared = db.Column(db.Boolean, nullable=False, default=False, index=True)
    source_thread_id = db.Column(db.String(255), nullable=True, index=True)
    created_at = db.Column(
        db.DateTime,
        nullable=False,
        default=datetime.utcnow,
        index=True,
    )

    def to_dict(self):
        return {
            'id': self.id,
            'user_id': self.user_id,
            'organization_id': self.organization_id,
            'name': self.name,
            'description': self.description,
            'objective': self.objective,
            'lever_defaults': self.lever_defaults if isinstance(self.lever_defaults, dict) else {},
            'scoring_weights': self.scoring_weights if isinstance(self.scoring_weights, dict) else {},
            'intake_context': self.intake_context if isinstance(self.intake_context, dict) else {},
            'is_shared': bool(self.is_shared),
            'source_thread_id': self.source_thread_id,
            'created_at': self.created_at.isoformat() if self.created_at else None,
        }


class ConnectorSyncLog(db.Model):
    __tablename__ = 'connector_sync_logs'

    id = db.Column(
        db.String(36),
        primary_key=True,
        default=lambda: str(uuid.uuid4())
    )
    user_id = db.Column(
        db.String(36),
        db.ForeignKey('users.id', ondelete='CASCADE'),
        nullable=False,
        index=True,
    )
    connector_id = db.Column(db.String(100), nullable=False, index=True)
    thread_id = db.Column(db.String(255), nullable=True, index=True)
    action = db.Column(db.String(100), nullable=False)
    status = db.Column(db.String(50), nullable=False, default='success')
    items_synced = db.Column(db.Integer, nullable=False, default=0)
    error_message = db.Column(db.Text, nullable=True)
    created_at = db.Column(
        db.DateTime,
        nullable=False,
        default=datetime.utcnow,
        index=True,
    )

    def to_dict(self):
        return {
            'id': self.id,
            'user_id': self.user_id,
            'connector_id': self.connector_id,
            'thread_id': self.thread_id,
            'action': self.action,
            'status': self.status,
            'items_synced': int(self.items_synced or 0),
            'error_message': self.error_message,
            'created_at': self.created_at.isoformat() if self.created_at else None,
        }


class AdminAuditEvent(db.Model):
    __tablename__ = 'admin_audit_events'

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    timestamp = db.Column(
        db.DateTime,
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        index=True,
    )
    actor_user_id = db.Column(
        db.String(36),
        db.ForeignKey('users.id'),
        nullable=True,
        index=True,
    )
    actor_email = db.Column(db.String(255), nullable=True)
    action = db.Column(db.String(100), nullable=False, index=True)
    target_user_id = db.Column(
        db.String(36),
        db.ForeignKey('users.id'),
        nullable=True,
        index=True,
    )
    target_email = db.Column(db.String(255), nullable=True)
    details = db.Column(db.JSON, nullable=True)
    remote_addr = db.Column(db.String(45), nullable=True)
    user_agent = db.Column(db.String(512), nullable=True)

    def to_dict(self):
        return {
            'timestamp': self.timestamp.isoformat() if self.timestamp else None,
            'actor_user_id': self.actor_user_id,
            'actor_email': self.actor_email,
            'action': self.action,
            'target_user_id': self.target_user_id,
            'target_email': self.target_email,
            'details': self.details if isinstance(self.details, dict) else {},
            'remote_addr': self.remote_addr,
            'user_agent': self.user_agent,
        }


class UsageEvent(db.Model):
    __tablename__ = 'usage_events'

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    user_id = db.Column(
        db.String(36),
        db.ForeignKey('users.id', ondelete='CASCADE'),
        nullable=False,
        index=True,
    )
    thread_id = db.Column(db.String(255), nullable=True, index=True)
    model_type = db.Column(db.String(16), nullable=True, index=True)
    provider = db.Column(db.String(32), nullable=True)
    model = db.Column(db.String(255), nullable=True)
    input_tokens = db.Column(db.Integer, nullable=False, default=0)
    output_tokens = db.Column(db.Integer, nullable=False, default=0)
    total_tokens = db.Column(db.Integer, nullable=False, default=0)
    credits_charged = db.Column(db.Integer, nullable=False, default=0)
    is_failover = db.Column(db.Boolean, nullable=False, default=False)
    created_at = db.Column(
        db.DateTime,
        nullable=False,
        default=datetime.utcnow,
        index=True,
    )

    __table_args__ = (
        db.Index('ix_usage_events_user_date', 'user_id', 'created_at'),
    )


class StripeWebhookEvent(db.Model):
    __tablename__ = 'stripe_webhook_events'

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    stripe_event_id = db.Column(db.String(255), nullable=False, unique=True, index=True)
    event_type = db.Column(db.String(100), nullable=False, index=True)
    processed = db.Column(db.Boolean, nullable=False, default=False, index=True)
    created_at = db.Column(
        db.DateTime,
        nullable=False,
        default=datetime.utcnow,
        index=True,
    )
    processed_at = db.Column(db.DateTime, nullable=True, index=True)


class OrgIdeaLedger(db.Model):
    """De-identified scoring signals retained per session for org-level
    benchmarking and pattern detection.

    The ledger is what survives a "Delete from my history" action: the
    original UserSession (with the idea text, chat, attachments) gets
    archived and eventually purged, but the structured signals here power
    the "ideas like this typically score X" experience for teams /
    enterprises. A "Purge permanently" action sets purged_at and nulls the
    user_id to fully anonymize the row.
    """
    __tablename__ = 'org_idea_ledger'

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    ledger_id = db.Column(db.String(36), nullable=False, unique=True, default=lambda: str(uuid.uuid4()))
    organization_id = db.Column(
        db.String(36),
        db.ForeignKey('organizations.id', ondelete='SET NULL'),
        nullable=True,
        index=True,
    )
    originating_user_id = db.Column(
        db.String(36),
        db.ForeignKey('users.id', ondelete='SET NULL'),
        nullable=True,
        index=True,
    )
    # While the UserSession still exists this links back to it; nulled when
    # the session is fully purged.
    source_session_id = db.Column(db.String(255), nullable=True, index=True)

    # High-level categorical tags — these stay even after purge.
    idea_category = db.Column(db.String(100), nullable=True, index=True)
    industry = db.Column(db.String(100), nullable=True, index=True)
    company_size = db.Column(db.String(50), nullable=True)

    # Scoring snapshot (structured numbers only — no free-text rationale).
    jaspen_score = db.Column(db.Integer, nullable=True, index=True)
    score_category = db.Column(db.String(20), nullable=True, index=True)
    dimensions = db.Column(db.JSON, nullable=True)       # {<dim>: {score, confidence, source}}
    risk_tags = db.Column(db.JSON, nullable=True)        # ["market_risk", "execution_risk", ...]
    recommendation_tags = db.Column(db.JSON, nullable=True)

    # Engagement signals — did the user actually use the workflow.
    had_tradeoff = db.Column(db.Boolean, nullable=False, default=False)
    had_execution_plan = db.Column(db.Boolean, nullable=False, default=False)
    phase_count = db.Column(db.Integer, nullable=True)
    task_count = db.Column(db.Integer, nullable=True)
    objective = db.Column(db.String(50), nullable=True)
    model_tier_used = db.Column(db.String(32), nullable=True)

    # Lifecycle: "active" | "archived" | "purged"
    outcome = db.Column(db.String(32), nullable=False, default='active', index=True)

    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, index=True)
    updated_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)
    archived_at = db.Column(db.DateTime, nullable=True, index=True)
    purged_at = db.Column(db.DateTime, nullable=True, index=True)

    __table_args__ = (
        db.Index('ix_org_idea_ledger_org_score', 'organization_id', 'jaspen_score'),
        db.Index('ix_org_idea_ledger_industry_score', 'industry', 'jaspen_score'),
        db.Index('ix_org_idea_ledger_org_created', 'organization_id', 'created_at'),
    )


class SavedUtilityEstimate(db.Model):
    """A saved result from a public business utility (e.g. the Cost of Turnover
    calculator). Minimal and extensible: `utility_type` namespaces the utility,
    and the versioned JSON payloads let the utility evolve without a schema
    rewrite. Anonymous activity never creates a row here — a save only happens
    for an authenticated user.
    """

    __tablename__ = 'saved_utility_estimates'

    id = db.Column(
        db.String(36),
        primary_key=True,
        default=lambda: str(uuid.uuid4()),
    )
    user_id = db.Column(
        db.String(36),
        db.ForeignKey('users.id', ondelete='CASCADE'),
        nullable=False,
        index=True,
    )
    utility_type = db.Column(db.String(64), nullable=False, default='cost_of_turnover')
    source = db.Column(db.String(80), nullable=True)
    calculator_version = db.Column(db.String(32), nullable=True)
    benchmark_version = db.Column(db.String(32), nullable=True)

    # Versioned JSON payloads.
    user_inputs = db.Column(db.JSON, nullable=False, default=dict)
    defaults_used = db.Column(db.JSON, nullable=False, default=dict)
    result_breakdown = db.Column(db.JSON, nullable=False, default=list)
    built_using = db.Column(db.JSON, nullable=False, default=dict)

    total_low = db.Column(db.Integer, nullable=True)
    total_mid = db.Column(db.Integer, nullable=True)
    total_high = db.Column(db.Integer, nullable=True)

    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    updated_at = db.Column(
        db.DateTime,
        nullable=False,
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
    )

    __table_args__ = (
        db.Index('ix_saved_utility_estimates_user_utility', 'user_id', 'utility_type'),
    )

    def to_dict(self):
        return {
            'id': self.id,
            'utility_type': self.utility_type,
            'source': self.source,
            'calculator_version': self.calculator_version,
            'benchmark_version': self.benchmark_version,
            'user_inputs': self.user_inputs,
            'defaults_used': self.defaults_used,
            'result_breakdown': self.result_breakdown,
            'built_using': self.built_using,
            'total_low': self.total_low,
            'total_mid': self.total_mid,
            'total_high': self.total_high,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None,
        }
