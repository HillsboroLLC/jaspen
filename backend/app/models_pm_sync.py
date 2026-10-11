import uuid
from datetime import datetime

from app import db


class PmSyncBinding(db.Model):
    __tablename__ = "pm_sync_bindings"

    id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = db.Column(db.String(36), db.ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    organization_id = db.Column(db.String(36), db.ForeignKey("organizations.id", ondelete="SET NULL"), nullable=True, index=True)
    thread_id = db.Column(db.String(64), nullable=False, index=True)
    plan_key = db.Column(db.String(64), nullable=False)
    connector_id = db.Column(db.String(32), nullable=False)
    external_container_id = db.Column(db.String(255), nullable=False)
    external_container_url = db.Column(db.Text, nullable=True)
    mode = db.Column(db.String(32), nullable=False)
    conflict_policy = db.Column(db.String(32), nullable=False)
    field_policy_overrides = db.Column(db.JSON, nullable=False, default=dict)
    policy_set_by_user_id = db.Column(db.String(36), db.ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    policy_set_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    config = db.Column(db.JSON, nullable=False, default=dict)
    user_map = db.Column(db.JSON, nullable=False, default=dict)
    status = db.Column(db.String(32), nullable=False, default="active")
    poll_cursor = db.Column(db.String(255), nullable=True)
    last_pull_at = db.Column(db.DateTime, nullable=True)
    last_push_at = db.Column(db.DateTime, nullable=True)
    last_success_at = db.Column(db.DateTime, nullable=True)
    lock_until = db.Column(db.DateTime, nullable=True)
    failure_count = db.Column(db.Integer, nullable=False, default=0)
    next_retry_at = db.Column(db.DateTime, nullable=True)
    webhook_token_hash = db.Column(db.String(128), nullable=True)
    external_webhook_id = db.Column(db.String(255), nullable=True)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    __table_args__ = (
        db.UniqueConstraint("thread_id", "plan_key", "connector_id", name="uq_pm_sync_binding_plan_connector"),
    )

    def to_dict(self):
        return {
            "id": self.id,
            "thread_id": self.thread_id,
            "plan_key": self.plan_key,
            "connector_id": self.connector_id,
            "external_container_id": self.external_container_id,
            "external_container_url": self.external_container_url,
            "mode": self.mode,
            "conflict_policy": self.conflict_policy,
            "field_policy_overrides": self.field_policy_overrides or {},
            "policy_set_by_user_id": self.policy_set_by_user_id,
            "policy_set_at": self.policy_set_at.isoformat() if self.policy_set_at else None,
            "config": self.config or {},
            "user_map": self.user_map or {},
            "status": self.status,
            "last_pull_at": self.last_pull_at.isoformat() if self.last_pull_at else None,
            "last_push_at": self.last_push_at.isoformat() if self.last_push_at else None,
            "last_success_at": self.last_success_at.isoformat() if self.last_success_at else None,
            "failure_count": int(self.failure_count or 0),
            "next_retry_at": self.next_retry_at.isoformat() if self.next_retry_at else None,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }


class PmSyncLink(db.Model):
    __tablename__ = "pm_sync_links"

    id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    binding_id = db.Column(db.String(36), db.ForeignKey("pm_sync_bindings.id", ondelete="CASCADE"), nullable=False, index=True)
    entity_type = db.Column(db.String(32), nullable=False)
    jaspen_id = db.Column(db.String(255), nullable=False)
    external_id = db.Column(db.String(255), nullable=True)
    external_parent_id = db.Column(db.String(255), nullable=True)
    base_snapshot = db.Column(db.JSON, nullable=False, default=dict)
    external_version = db.Column(db.String(255), nullable=True)
    jaspen_version = db.Column(db.String(255), nullable=True)
    state = db.Column(db.String(32), nullable=False, default="active")
    last_error = db.Column(db.Text, nullable=True)
    last_synced_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)

    __table_args__ = (
        db.UniqueConstraint("binding_id", "entity_type", "jaspen_id", name="uq_pm_sync_link_jaspen_entity"),
        db.UniqueConstraint("binding_id", "external_id", name="uq_pm_sync_link_external"),
    )

    def to_dict(self):
        return {
            "id": self.id,
            "binding_id": self.binding_id,
            "entity_type": self.entity_type,
            "jaspen_id": self.jaspen_id,
            "external_id": self.external_id,
            "external_parent_id": self.external_parent_id,
            "base_snapshot": self.base_snapshot or {},
            "external_version": self.external_version,
            "jaspen_version": self.jaspen_version,
            "state": self.state,
            "last_error": self.last_error,
            "last_synced_at": self.last_synced_at.isoformat() if self.last_synced_at else None,
        }
