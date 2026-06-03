# backend/app/models_studio.py
#
# "Studio" storage — the clean, compartmentalized replacement for the
# session/thread blob + baseline/scenario model. See docs/STUDIO_BUILD_PLAN.md.
#
# Two additive tables (they do NOT touch existing tables):
#   - StudioWorkspace : the thin per-session parent. Holds the user's shared
#                       rubric (criteria + weights + groups) and theme ONCE.
#   - StudioArtifact  : one standalone, first-class row per idea/output. No
#                       baseline, no scenarios, no hierarchy. A comparison is its
#                       own artifact that references scorecard artifact ids.
#
# Each artifact is its own row → atomic per-row saves → no last-writer-wins blob
# clobbering (the bug class that plagued the old session payload).

import uuid
from datetime import datetime
from . import db


def _uuid():
    return str(uuid.uuid4())


class StudioWorkspace(db.Model):
    __tablename__ = 'studio_workspaces'

    id = db.Column(db.String(36), primary_key=True, default=_uuid)
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
    created_by_user_id = db.Column(
        db.String(36),
        db.ForeignKey('users.id', ondelete='SET NULL'),
        nullable=True,
        index=True,
    )

    title = db.Column(db.String(255), nullable=False, default='Untitled evaluation')
    status = db.Column(db.String(50), nullable=False, default='active')

    # The user's OWN rubric — criteria + weights + optional groups. The app never
    # fabricates this; it applies it deterministically. Shape:
    #   {"criteria": [{key, label, weight, group?, is_risk?, description?}, ...]}
    rubric = db.Column(db.JSON, nullable=True, default=dict)

    # Confidence threshold (0-100) at which the app auto-generates artifacts.
    # Chosen by the user via a choice prompt; null = ask / use default.
    autogenerate_confidence = db.Column(db.Integer, nullable=True)

    # Theme override for this workspace; null = inherit the org/app default.
    theme = db.Column(db.JSON, nullable=True)

    # Sharing parity with the rest of the app.
    visibility = db.Column(db.String(32), nullable=False, default='private', index=True)
    shared_with_user_ids = db.Column(db.JSON, nullable=True, default=list)

    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)
    archived_at = db.Column(db.DateTime, nullable=True, index=True)
    purge_after = db.Column(db.DateTime, nullable=True, index=True)

    __table_args__ = (
        db.Index('ix_studio_workspaces_user_updated', 'user_id', 'updated_at'),
    )

    def to_dict(self, include_artifacts=False):
        out = {
            'id': self.id,
            'user_id': self.user_id,
            'organization_id': self.organization_id,
            'created_by_user_id': self.created_by_user_id,
            'title': self.title,
            'status': self.status,
            'rubric': self.rubric if isinstance(self.rubric, dict) else {},
            'autogenerate_confidence': self.autogenerate_confidence,
            'theme': self.theme,
            'visibility': self.visibility,
            'shared_with_user_ids': self.shared_with_user_ids or [],
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None,
        }
        if include_artifacts:
            out['artifacts'] = [
                a.to_dict() for a in sorted(
                    (self.artifacts or []),
                    key=lambda x: (x.position if x.position is not None else 0, x.created_at or datetime.utcnow()),
                )
                if a.archived_at is None
            ]
        return out


class StudioArtifact(db.Model):
    __tablename__ = 'studio_artifacts'

    id = db.Column(db.String(36), primary_key=True, default=_uuid)
    workspace_id = db.Column(
        db.String(36),
        db.ForeignKey('studio_workspaces.id', ondelete='CASCADE'),
        nullable=False,
        index=True,
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

    # scorecard | comparison | execution_plan | document
    type = db.Column(db.String(40), nullable=False, default='scorecard', index=True)
    name = db.Column(db.String(255), nullable=False, default='Untitled')

    # The artifact's full content (e.g. the scored scorecard payload). Self-contained.
    data = db.Column(db.JSON, nullable=False, default=dict)

    # Optional per-artifact theme override + cosmetic display overrides.
    theme = db.Column(db.JSON, nullable=True)
    display_overrides = db.Column(db.JSON, nullable=True, default=dict)

    # Ordering within the workspace.
    position = db.Column(db.Integer, nullable=True)

    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)
    archived_at = db.Column(db.DateTime, nullable=True, index=True)

    workspace = db.relationship(
        'StudioWorkspace',
        backref=db.backref('artifacts', lazy='select', cascade='all, delete-orphan'),
    )

    __table_args__ = (
        db.Index('ix_studio_artifacts_workspace_position', 'workspace_id', 'position'),
    )

    def to_dict(self):
        return {
            'id': self.id,
            'workspace_id': self.workspace_id,
            'user_id': self.user_id,
            'organization_id': self.organization_id,
            'type': self.type,
            'name': self.name,
            'data': self.data if isinstance(self.data, dict) else {},
            'theme': self.theme,
            'display_overrides': self.display_overrides or {},
            'position': self.position,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None,
        }
