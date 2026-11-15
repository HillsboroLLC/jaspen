"""Inactive Phase 10 trial, promotion, comp, and internal-funding evidence.

Nothing in live routes, webhooks, jobs, or readers writes to or reads from
these tables. Phase 3 remains the only credit ledger and Phase 4 the only
entitlement authority; these immutable rows bind each offer-funded lot and
entitlement to an approved, versioned ``EntitlementDefinition`` offer and, for
comps and internal funding, to an explicit Jaspen staff permission grant.
"""

import uuid
from datetime import datetime, timezone

from . import db


OFFER_ORIGINS = ("trial", "promotion", "comp", "internal")
STAFF_PERMISSIONS = ("billing.comp.grant", "billing.internal_funding.grant")
PERMISSION_VERSION = 1


def _quoted(values):
    return ", ".join(f"'{value}'" for value in values)


def _now():
    return datetime.now(timezone.utc)


class BillingStaffPermissionGrant(db.Model):
    """Explicit, versioned Jaspen staff authority for one billing command family.

    Global-admin identity, organization membership, and customer billing roles
    never imply this permission. Grants are recorded only by the trusted
    provisioning service from documented approval evidence and are immutable;
    revocation is a separate append-only record.
    """

    __tablename__ = "billing_staff_permission_grants"

    id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = db.Column(
        db.String(36),
        db.ForeignKey("users.id", name="fk_billing_staff_permission_grants_user", ondelete="RESTRICT"),
        nullable=False,
    )
    permission = db.Column(db.String(64), nullable=False)
    permission_version = db.Column(db.Integer, nullable=False)
    starts_at = db.Column(db.DateTime(timezone=True), nullable=False)
    ends_at = db.Column(db.DateTime(timezone=True), nullable=True)
    grant_key = db.Column(db.String(255), nullable=False)
    request_fingerprint = db.Column(db.String(64), nullable=False)
    approval_evidence_reference = db.Column(db.String(255), nullable=False)
    justification = db.Column(db.Text, nullable=False)
    idempotency_registry_id = db.Column(
        db.String(36),
        db.ForeignKey(
            "idempotency_registry.id", name="fk_billing_staff_permission_grants_registry", ondelete="RESTRICT",
        ),
        nullable=False,
    )
    actor_type = db.Column(db.String(40), nullable=False)
    actor_id = db.Column(db.String(255), nullable=False)
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=_now, server_default=db.func.now())

    __table_args__ = (
        db.UniqueConstraint("grant_key", name="uq_billing_staff_permission_grants_key"),
        db.UniqueConstraint("idempotency_registry_id", name="uq_billing_staff_permission_grants_registry"),
        db.CheckConstraint(
            f"permission IN ({_quoted(STAFF_PERMISSIONS)})",
            name="ck_billing_staff_permission_grants_permission",
        ),
        db.CheckConstraint(
            f"permission_version = {PERMISSION_VERSION}",
            name="ck_billing_staff_permission_grants_version",
        ),
        db.CheckConstraint(
            "ends_at IS NULL OR ends_at > starts_at",
            name="ck_billing_staff_permission_grants_interval",
        ),
        db.CheckConstraint(
            "actor_type = 'system' AND length(trim(actor_id)) > 0 "
            "AND length(trim(grant_key)) > 0 "
            "AND length(trim(approval_evidence_reference)) > 0 AND length(trim(justification)) > 0 "
            "AND length(request_fingerprint) = 64 AND request_fingerprint = lower(request_fingerprint)",
            name="ck_billing_staff_permission_grants_provenance",
        ),
        db.Index("ix_billing_staff_permission_grants_user_permission", "user_id", "permission", "starts_at"),
    )


class BillingStaffPermissionRevocation(db.Model):
    """Append-only revocation; once recorded, the grant authorizes no new command."""

    __tablename__ = "billing_staff_permission_revocations"

    id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    grant_id = db.Column(
        db.String(36),
        db.ForeignKey(
            "billing_staff_permission_grants.id", name="fk_billing_staff_permission_revocations_grant",
            ondelete="RESTRICT",
        ),
        nullable=False,
    )
    revoked_at = db.Column(db.DateTime(timezone=True), nullable=False)
    reason = db.Column(db.Text, nullable=False)
    evidence_reference = db.Column(db.String(255), nullable=False)
    actor_type = db.Column(db.String(40), nullable=False)
    actor_id = db.Column(db.String(255), nullable=False)
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=_now, server_default=db.func.now())

    __table_args__ = (
        db.UniqueConstraint("grant_id", name="uq_billing_staff_permission_revocations_grant"),
        db.CheckConstraint(
            "actor_type = 'system' AND length(trim(actor_id)) > 0 "
            "AND length(trim(reason)) > 0 AND length(trim(evidence_reference)) > 0",
            name="ck_billing_staff_permission_revocations_provenance",
        ),
    )


class CreditOfferRedemption(db.Model):
    """Immutable proof that one approved offer version was redeemed once for one account."""

    __tablename__ = "credit_offer_redemptions"

    id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    billing_account_id = db.Column(
        db.String(36),
        db.ForeignKey("billing_accounts.id", name="fk_credit_offer_redemptions_account", ondelete="RESTRICT"),
        nullable=False,
    )
    entitlement_definition_id = db.Column(
        db.String(36),
        db.ForeignKey(
            "entitlement_definitions.id", name="fk_credit_offer_redemptions_definition", ondelete="RESTRICT",
        ),
        nullable=False,
    )
    offer_key = db.Column(db.String(80), nullable=False)
    offer_version = db.Column(db.Integer, nullable=False)
    origin = db.Column(db.String(16), nullable=False)
    redemption_id = db.Column(db.String(128), nullable=False)
    redemption_key = db.Column(db.String(255), nullable=False)
    request_fingerprint = db.Column(db.String(64), nullable=False)
    funding_source = db.Column(db.String(80), nullable=False)
    redeemed_at = db.Column(db.DateTime(timezone=True), nullable=False)
    term_starts_at = db.Column(db.DateTime(timezone=True), nullable=False)
    term_ends_at = db.Column(db.DateTime(timezone=True), nullable=False)
    credit_amount = db.Column(db.BigInteger, nullable=False)
    credit_expires_at = db.Column(db.DateTime(timezone=True), nullable=True)
    per_account_limit = db.Column(db.Integer, nullable=False)
    total_limit = db.Column(db.Integer, nullable=False)
    account_redemption_index = db.Column(db.Integer, nullable=False)
    total_redemption_index = db.Column(db.Integer, nullable=False)
    entitlement_instance_id = db.Column(
        db.String(36),
        db.ForeignKey(
            "entitlement_instances.id", name="fk_credit_offer_redemptions_instance", ondelete="RESTRICT",
        ),
        nullable=True,
    )
    staff_permission_grant_id = db.Column(
        db.String(36),
        db.ForeignKey(
            "billing_staff_permission_grants.id", name="fk_credit_offer_redemptions_permission",
            ondelete="RESTRICT",
        ),
        nullable=True,
    )
    reason_code = db.Column(db.String(64), nullable=True)
    justification = db.Column(db.Text, nullable=True)
    evidence_reference = db.Column(db.String(255), nullable=True)
    idempotency_registry_id = db.Column(
        db.String(36),
        db.ForeignKey("idempotency_registry.id", name="fk_credit_offer_redemptions_registry", ondelete="RESTRICT"),
        nullable=False,
    )
    domain_event_id = db.Column(
        db.String(36),
        db.ForeignKey("domain_events.id", name="fk_credit_offer_redemptions_domain_event", ondelete="RESTRICT"),
        nullable=False,
    )
    contract_version = db.Column(db.Integer, nullable=False)
    actor_type = db.Column(db.String(40), nullable=False)
    actor_id = db.Column(db.String(255), nullable=False)
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=_now, server_default=db.func.now())

    __table_args__ = (
        db.UniqueConstraint("redemption_key", name="uq_credit_offer_redemptions_key"),
        db.UniqueConstraint(
            "entitlement_definition_id", "redemption_id", name="uq_credit_offer_redemptions_definition_redemption",
        ),
        db.UniqueConstraint(
            "offer_key", "billing_account_id", "account_redemption_index",
            name="uq_credit_offer_redemptions_account_index",
        ),
        db.UniqueConstraint("offer_key", "total_redemption_index", name="uq_credit_offer_redemptions_total_index"),
        db.UniqueConstraint("idempotency_registry_id", name="uq_credit_offer_redemptions_registry"),
        db.UniqueConstraint("entitlement_instance_id", name="uq_credit_offer_redemptions_instance"),
        db.CheckConstraint(f"origin IN ({_quoted(OFFER_ORIGINS)})", name="ck_credit_offer_redemptions_origin"),
        db.CheckConstraint("contract_version = 1", name="ck_credit_offer_redemptions_contract"),
        db.CheckConstraint(
            "credit_amount >= 0 AND offer_version > 0 "
            "AND per_account_limit > 0 AND total_limit > 0 "
            "AND account_redemption_index > 0 AND account_redemption_index <= per_account_limit "
            "AND total_redemption_index > 0 AND total_redemption_index <= total_limit "
            "AND account_redemption_index <= total_redemption_index",
            name="ck_credit_offer_redemptions_limits",
        ),
        db.CheckConstraint(
            "term_starts_at = redeemed_at AND term_ends_at > term_starts_at "
            "AND (credit_expires_at IS NULL OR credit_expires_at = term_ends_at)",
            name="ck_credit_offer_redemptions_term",
        ),
        db.CheckConstraint(
            "length(trim(redemption_id)) > 0 AND length(trim(offer_key)) > 0 "
            "AND length(trim(funding_source)) > 0 "
            "AND redemption_key = 'offer-redemption:' || entitlement_definition_id || ':' || redemption_id "
            "AND length(request_fingerprint) = 64 AND request_fingerprint = lower(request_fingerprint) "
            "AND length(trim(actor_type)) > 0 AND length(trim(actor_id)) > 0",
            name="ck_credit_offer_redemptions_identity",
        ),
        db.CheckConstraint(
            "(origin IN ('trial', 'promotion') AND actor_type = 'system' "
            " AND staff_permission_grant_id IS NULL) OR "
            "(origin IN ('comp', 'internal') AND actor_type = 'user' "
            " AND staff_permission_grant_id IS NOT NULL "
            " AND reason_code IS NOT NULL AND length(trim(reason_code)) > 0 "
            " AND justification IS NOT NULL AND length(trim(justification)) > 0 "
            " AND evidence_reference IS NOT NULL AND length(trim(evidence_reference)) > 0)",
            name="ck_credit_offer_redemptions_authority",
        ),
        db.Index("ix_credit_offer_redemptions_account_redeemed", "billing_account_id", "redeemed_at", "id"),
        db.Index("ix_credit_offer_redemptions_domain_event", "domain_event_id"),
        db.Index("ix_credit_offer_redemptions_permission", "staff_permission_grant_id"),
    )


class CreditOfferFunding(db.Model):
    """Immutable proof that one offer redemption funded one credit component lot."""

    __tablename__ = "credit_offer_fundings"

    id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    redemption_id = db.Column(
        db.String(36),
        db.ForeignKey("credit_offer_redemptions.id", name="fk_credit_offer_fundings_redemption", ondelete="RESTRICT"),
        nullable=False,
    )
    billing_account_id = db.Column(
        db.String(36),
        db.ForeignKey("billing_accounts.id", name="fk_credit_offer_fundings_account", ondelete="RESTRICT"),
        nullable=False,
    )
    funding_component = db.Column(db.String(64), nullable=False)
    funding_key = db.Column(db.String(512), nullable=False)
    request_fingerprint = db.Column(db.String(64), nullable=False)
    credit_amount = db.Column(db.BigInteger, nullable=False)
    lot_id = db.Column(
        db.String(36),
        db.ForeignKey(
            "credit_lots.id", name="fk_credit_offer_fundings_lot", ondelete="RESTRICT",
            deferrable=True, initially="DEFERRED",
        ),
        nullable=False,
    )
    grant_entry_id = db.Column(
        db.String(36),
        db.ForeignKey(
            "credit_ledger_entries.id", name="fk_credit_offer_fundings_grant", ondelete="RESTRICT",
            deferrable=True, initially="DEFERRED",
        ),
        nullable=False,
    )
    idempotency_registry_id = db.Column(
        db.String(36),
        db.ForeignKey("idempotency_registry.id", name="fk_credit_offer_fundings_registry", ondelete="RESTRICT"),
        nullable=False,
    )
    contract_version = db.Column(db.Integer, nullable=False)
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=_now, server_default=db.func.now())

    __table_args__ = (
        db.UniqueConstraint("funding_key", name="uq_credit_offer_fundings_key"),
        db.UniqueConstraint("redemption_id", "funding_component", name="uq_credit_offer_fundings_component"),
        db.UniqueConstraint("lot_id", name="uq_credit_offer_fundings_lot"),
        db.UniqueConstraint("grant_entry_id", name="uq_credit_offer_fundings_grant"),
        db.UniqueConstraint("idempotency_registry_id", name="uq_credit_offer_fundings_registry"),
        db.CheckConstraint("credit_amount > 0", name="ck_credit_offer_fundings_amount"),
        db.CheckConstraint("contract_version = 1", name="ck_credit_offer_fundings_contract"),
        db.CheckConstraint(
            "length(trim(funding_component)) > 0 AND length(trim(funding_key)) > 0 "
            "AND length(request_fingerprint) = 64 AND request_fingerprint = lower(request_fingerprint)",
            name="ck_credit_offer_fundings_identity",
        ),
        db.Index("ix_credit_offer_fundings_account", "billing_account_id", "id"),
    )
