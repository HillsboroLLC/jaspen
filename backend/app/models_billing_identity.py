"""D18 row 17, identity family: which billing model owns an organization (I1).

``billing_model_assignments`` holds one immutable row per organization that the
modernized billing model owns. An organization without a row is a legacy
organization; nothing else decides the model, and no read, sign-in or UI context
creates a row. The row is written only by the explicit identity command in
``app.billing_cutover`` (``establish_modern_billing_identity``), together with the
organization's Phase 2 billing account and its ``billing_owner`` role, in one
transaction and under one idempotency claim.

The assignment is durable and one-way: turning a family switch off never returns
an organization to legacy billing (that would give one organization two billing
authorities). Moving an existing legacy organization to the modern model is the
D18 rows 14-16 migration, never this command.
"""

from datetime import datetime, timezone
import uuid

from . import db


ASSIGNMENT_RULE_VERSION = "jaspen.billing.model_assignment.v1"


class BillingModelAssignment(db.Model):
    __tablename__ = "billing_model_assignments"

    id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    organization_id = db.Column(
        db.String(36),
        db.ForeignKey("organizations.id", name="fk_billing_model_assignments_organization", ondelete="RESTRICT"),
        nullable=False,
    )
    billing_account_id = db.Column(
        db.String(36),
        db.ForeignKey("billing_accounts.id", name="fk_billing_model_assignments_account", ondelete="RESTRICT"),
        nullable=False,
    )
    model = db.Column(db.String(16), nullable=False)
    rule_version = db.Column(db.String(64), nullable=False)
    assigned_by_user_id = db.Column(
        db.String(36),
        db.ForeignKey("users.id", name="fk_billing_model_assignments_actor", ondelete="RESTRICT"),
        nullable=False,
    )
    origin_type = db.Column(db.String(40), nullable=False)
    origin_id = db.Column(db.String(255), nullable=False)
    footprint_json = db.Column(db.JSON, nullable=False)
    request_fingerprint = db.Column(db.String(64), nullable=False)
    idempotency_registry_id = db.Column(
        db.String(36),
        db.ForeignKey("idempotency_registry.id", name="fk_billing_model_assignments_registry", ondelete="RESTRICT"),
        nullable=False,
    )
    assigned_at = db.Column(db.DateTime(timezone=True), nullable=False)
    created_at = db.Column(
        db.DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        server_default=db.func.now(),
    )

    __table_args__ = (
        db.UniqueConstraint("organization_id", name="uq_billing_model_assignments_organization"),
        db.UniqueConstraint("billing_account_id", name="uq_billing_model_assignments_account"),
        db.UniqueConstraint("idempotency_registry_id", name="uq_billing_model_assignments_registry"),
        db.CheckConstraint(
            "model = 'modern' AND rule_version = 'jaspen.billing.model_assignment.v1'",
            name="ck_billing_model_assignments_model",
        ),
        db.CheckConstraint(
            "length(trim(origin_type)) > 0 AND length(trim(origin_id)) > 0 AND "
            "length(request_fingerprint) = 64 AND request_fingerprint = lower(request_fingerprint)",
            name="ck_billing_model_assignments_provenance",
        ),
    )
