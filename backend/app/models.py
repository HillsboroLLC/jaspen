# backend/app/models.py

import uuid
from datetime import datetime
from . import db

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
        default=300
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
            'max_creator_seats': self.max_creator_seats,
            'max_collaborator_seats': self.max_collaborator_seats,
            'seat_policy_overrides': self.seat_policy_overrides if isinstance(self.seat_policy_overrides, dict) else {},
            'created_at': self.created_at.isoformat() if self.created_at else None,
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
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    __table_args__ = (
        db.UniqueConstraint('user_id', 'session_id', name='uq_user_sessions_user_id_session_id'),
        db.Index('ix_user_sessions_user_id_updated_at', 'user_id', 'updated_at'),
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
