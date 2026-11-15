"""Inactive Phase 11 Enterprise contract evidence (P09; STOP-15; founder-approved
P11-DEP-001..004, 2026-11-15).

The Enterprise contract is the commercial authority. Each paid term of a
contract is represented by its own contract-backed ``BillingSubscription``
(processor ``jaspen_contract``), so the Phase 4 entitlement, Phase 6
allocation, Phase 3 ledger, Phase 5 financial, and Phase 8 seat authorities are
reused rather than duplicated. These tables record only the contract's own
facts: executed versions, staff approvals, verified Stripe term funding,
activations, nonrenewal notices, and the recorded access state.

Nothing in live routes, webhooks, jobs, or readers writes to or reads from
these tables. Version terms and evidence are immutable; the only mutable
columns are state projections that the database guards tie to an append-only
event.
"""

import uuid
from datetime import datetime, timezone

from . import db


CONTRACT_PROCESSOR = "jaspen_contract"
CONTRACT_PERMISSION = "billing.enterprise_contract.manage"
CONTRACT_STATES = ("recorded", "approved", "active", "renewal_grace", "ended", "cancelled")
VERSION_STATES = ("recorded", "approved", "active", "completed", "cancelled", "superseded")
VERSION_KINDS = ("initial", "renewal", "amendment")
TERM_INTERVALS = ("month", "year")
RENEWAL_MODES = ("manual", "automatic")
NOTICE_KINDS = ("nonrenewal", "nonrenewal_reversal")
EVENT_SCOPES = ("contract", "version")
# Founder-approved durations (2026-11-15). The retention date is a billing-side
# record only: no deletion, export, or notice is implemented or activated, and
# the 180-day target remains subject to legal review before enforcement.
NONRENEWAL_NOTICE_DAYS = 30
RENEWAL_GRACE_DAYS = 15
RETENTION_REVIEW_DAYS = 180


def _quoted(values):
    return ",".join(f"'{value}'" for value in values)


def _now():
    return datetime.now(timezone.utc)


def _fk(table, name, *, nullable=False, deferred=False):
    kwargs = {"deferrable": True, "initially": "DEFERRED"} if deferred else {}
    return db.Column(
        db.String(36),
        db.ForeignKey(f"{table}.id", name=name, ondelete="RESTRICT", **kwargs),
        nullable=nullable,
    )


class EnterpriseContract(db.Model):
    """One executed, organization-owned Enterprise agreement."""

    __tablename__ = "enterprise_contracts"

    id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    billing_account_id = _fk("billing_accounts", "fk_enterprise_contracts_account")
    contract_reference = db.Column(db.String(255), nullable=False)
    state = db.Column(db.String(16), nullable=False, default="recorded", server_default="recorded")
    last_event_id = db.Column(db.String(36), nullable=True)
    paid_access_ended_at = db.Column(db.DateTime(timezone=True), nullable=True)
    retention_review_until = db.Column(db.DateTime(timezone=True), nullable=True)
    idempotency_registry_id = _fk("idempotency_registry", "fk_enterprise_contracts_registry")
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=_now, server_default=db.func.now())

    __table_args__ = (
        db.UniqueConstraint("contract_reference", name="uq_enterprise_contracts_reference"),
        db.UniqueConstraint("idempotency_registry_id", name="uq_enterprise_contracts_registry"),
        db.CheckConstraint(f"state IN ({_quoted(CONTRACT_STATES)})", name="ck_enterprise_contracts_state"),
        db.CheckConstraint("length(trim(contract_reference)) > 0", name="ck_enterprise_contracts_reference"),
        db.CheckConstraint(
            "(paid_access_ended_at IS NULL) = (retention_review_until IS NULL) "
            "AND (paid_access_ended_at IS NULL OR retention_review_until > paid_access_ended_at)",
            name="ck_enterprise_contracts_retention",
        ),
        db.CheckConstraint(
            "(state = 'ended') = (paid_access_ended_at IS NOT NULL) OR state = 'cancelled'",
            name="ck_enterprise_contracts_ended_shape",
        ),
        db.Index("ix_enterprise_contracts_account_state", "billing_account_id", "state"),
    )


class EnterpriseContractVersion(db.Model):
    """One immutable executed term, renewal, or amendment of a contract."""

    __tablename__ = "enterprise_contract_versions"

    id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    contract_id = _fk("enterprise_contracts", "fk_enterprise_contract_versions_contract")
    billing_account_id = _fk("billing_accounts", "fk_enterprise_contract_versions_account")
    version_number = db.Column(db.Integer, nullable=False)
    version_kind = db.Column(db.String(16), nullable=False)
    # Renewal: the term it renews. Amendment: the term it amends.
    term_version_id = _fk(
        "enterprise_contract_versions", "fk_enterprise_contract_versions_term", nullable=True,
    )
    interval = db.Column(db.String(8), nullable=True)
    term_starts_at = db.Column(db.DateTime(timezone=True), nullable=True)
    term_ends_at = db.Column(db.DateTime(timezone=True), nullable=True)
    effective_at = db.Column(db.DateTime(timezone=True), nullable=False)
    currency = db.Column(db.String(3), nullable=False)
    price_minor = db.Column(db.BigInteger, nullable=False)
    monthly_credit_amount = db.Column(db.BigInteger, nullable=True)
    committed_seats = db.Column(db.Integer, nullable=False)
    capabilities_json = db.Column(db.JSON(none_as_null=True), nullable=True)
    # The entitlement exclusivity group the term occupies (Phase 4 D07), so a
    # contract term can never overlap another plan of the same group.
    exclusivity_key = db.Column(db.String(80), nullable=True)
    renewal_mode = db.Column(db.String(16), nullable=True)
    executed_reference = db.Column(db.String(255), nullable=False)
    executed_evidence_reference = db.Column(db.String(255), nullable=False)
    recorded_by_user_id = _fk("users", "fk_enterprise_contract_versions_recorded_by")
    recorded_permission_grant_id = _fk(
        "billing_staff_permission_grants", "fk_enterprise_contract_versions_recorded_grant",
    )
    request_fingerprint = db.Column(db.String(64), nullable=False)
    idempotency_registry_id = _fk("idempotency_registry", "fk_enterprise_contract_versions_registry")
    recorded_at = db.Column(db.DateTime(timezone=True), nullable=False)
    # State projections, each changed only together with a matching event.
    state = db.Column(db.String(16), nullable=False, default="recorded", server_default="recorded")
    last_event_id = db.Column(db.String(36), nullable=True)
    entitlement_definition_id = _fk(
        "entitlement_definitions", "fk_enterprise_contract_versions_definition", nullable=True,
    )
    subscription_id = _fk("billing_subscriptions", "fk_enterprise_contract_versions_subscription", nullable=True)
    entitlement_instance_id = _fk(
        "entitlement_instances", "fk_enterprise_contract_versions_instance", nullable=True,
    )

    __table_args__ = (
        db.UniqueConstraint("contract_id", "version_number", name="uq_enterprise_contract_versions_number"),
        db.UniqueConstraint("idempotency_registry_id", name="uq_enterprise_contract_versions_registry"),
        db.CheckConstraint("version_number > 0", name="ck_enterprise_contract_versions_number"),
        db.CheckConstraint(f"version_kind IN ({_quoted(VERSION_KINDS)})", name="ck_enterprise_contract_versions_kind"),
        db.CheckConstraint(f"state IN ({_quoted(VERSION_STATES)})", name="ck_enterprise_contract_versions_state"),
        db.CheckConstraint("price_minor > 0 AND committed_seats > 0", name="ck_enterprise_contract_versions_amounts"),
        db.CheckConstraint(
            "length(currency) = 3 AND currency = lower(currency)", name="ck_enterprise_contract_versions_currency",
        ),
        db.CheckConstraint(
            "length(trim(executed_reference)) > 0 AND length(trim(executed_evidence_reference)) > 0 "
            "AND length(request_fingerprint) = 64",
            name="ck_enterprise_contract_versions_evidence",
        ),
        # Term versions carry a whole paid term; amendments carry only the
        # seat increase and its agreed price (allocation amendments need a
        # separate founder decision and are refused).
        db.CheckConstraint(
            "(version_kind IN ('initial','renewal') AND interval IN ('month','year') "
            " AND term_starts_at IS NOT NULL AND term_ends_at > term_starts_at "
            " AND effective_at = term_starts_at AND monthly_credit_amount > 0 "
            " AND capabilities_json IS NOT NULL AND renewal_mode IN ('manual','automatic') "
            " AND length(trim(exclusivity_key)) > 0 "
            " AND ((version_kind = 'initial' AND term_version_id IS NULL) "
            "   OR (version_kind = 'renewal' AND term_version_id IS NOT NULL))) "
            "OR (version_kind = 'amendment' AND term_version_id IS NOT NULL AND interval IS NULL "
            " AND term_starts_at IS NULL AND term_ends_at IS NULL AND monthly_credit_amount IS NULL "
            " AND capabilities_json IS NULL AND renewal_mode IS NULL AND exclusivity_key IS NULL)",
            name="ck_enterprise_contract_versions_shape",
        ),
        db.Index("ix_enterprise_contract_versions_contract_state", "contract_id", "state"),
        db.Index("ix_enterprise_contract_versions_term", "term_version_id"),
    )


class EnterpriseContractEvent(db.Model):
    """Append-only, staff-attributed transition of a contract or version."""

    __tablename__ = "enterprise_contract_events"

    id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    contract_id = _fk("enterprise_contracts", "fk_enterprise_contract_events_contract")
    version_id = _fk("enterprise_contract_versions", "fk_enterprise_contract_events_version", nullable=True)
    scope = db.Column(db.String(16), nullable=False)
    transition = db.Column(db.String(64), nullable=False)
    from_state = db.Column(db.String(16), nullable=False)
    to_state = db.Column(db.String(16), nullable=False)
    occurred_at = db.Column(db.DateTime(timezone=True), nullable=False)
    actor_user_id = _fk("users", "fk_enterprise_contract_events_actor")
    permission_grant_id = _fk("billing_staff_permission_grants", "fk_enterprise_contract_events_grant")
    reason = db.Column(db.String(2000), nullable=True)
    evidence_reference = db.Column(db.String(255), nullable=False)
    idempotency_registry_id = _fk("idempotency_registry", "fk_enterprise_contract_events_registry")
    domain_event_id = _fk("domain_events", "fk_enterprise_contract_events_domain_event")
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=_now, server_default=db.func.now())

    __table_args__ = (
        db.UniqueConstraint("idempotency_registry_id", name="uq_enterprise_contract_events_registry"),
        db.CheckConstraint(f"scope IN ({_quoted(EVENT_SCOPES)})", name="ck_enterprise_contract_events_scope"),
        db.CheckConstraint(
            "(scope = 'contract') = (version_id IS NULL) AND from_state <> to_state "
            "AND length(trim(transition)) > 0 AND length(trim(evidence_reference)) > 0",
            name="ck_enterprise_contract_events_shape",
        ),
        db.Index("ix_enterprise_contract_events_contract", "contract_id", "occurred_at", "id"),
    )


class EnterpriseContractTermFunding(db.Model):
    """Verified Stripe payment of one term or amendment, in the exact agreed amount."""

    __tablename__ = "enterprise_contract_term_fundings"

    id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    contract_id = _fk("enterprise_contracts", "fk_enterprise_contract_term_fundings_contract")
    version_id = _fk("enterprise_contract_versions", "fk_enterprise_contract_term_fundings_version")
    billing_account_id = _fk("billing_accounts", "fk_enterprise_contract_term_fundings_account")
    subscription_id = _fk("billing_subscriptions", "fk_enterprise_contract_term_fundings_subscription")
    financial_transaction_id = _fk("financial_transactions", "fk_enterprise_contract_term_fundings_transaction")
    financial_line_id = _fk("financial_lines", "fk_enterprise_contract_term_fundings_line")
    amount_minor = db.Column(db.BigInteger, nullable=False)
    currency = db.Column(db.String(3), nullable=False)
    paid_at = db.Column(db.DateTime(timezone=True), nullable=False)
    recorded_at = db.Column(db.DateTime(timezone=True), nullable=False)
    actor_user_id = _fk("users", "fk_enterprise_contract_term_fundings_actor")
    permission_grant_id = _fk("billing_staff_permission_grants", "fk_enterprise_contract_term_fundings_grant")
    idempotency_registry_id = _fk("idempotency_registry", "fk_enterprise_contract_term_fundings_registry")
    domain_event_id = _fk("domain_events", "fk_enterprise_contract_term_fundings_domain_event")

    __table_args__ = (
        db.UniqueConstraint("version_id", name="uq_enterprise_contract_term_fundings_version"),
        db.UniqueConstraint("financial_line_id", name="uq_enterprise_contract_term_fundings_line"),
        db.UniqueConstraint("idempotency_registry_id", name="uq_enterprise_contract_term_fundings_registry"),
        db.CheckConstraint("amount_minor > 0", name="ck_enterprise_contract_term_fundings_amount"),
        db.Index("ix_enterprise_contract_term_fundings_subscription", "subscription_id"),
    )


class EnterpriseContractActivation(db.Model):
    """Proof that one approved, effective, funded version took effect once."""

    __tablename__ = "enterprise_contract_activations"

    id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    contract_id = _fk("enterprise_contracts", "fk_enterprise_contract_activations_contract")
    version_id = _fk("enterprise_contract_versions", "fk_enterprise_contract_activations_version")
    billing_account_id = _fk("billing_accounts", "fk_enterprise_contract_activations_account")
    subscription_id = _fk("billing_subscriptions", "fk_enterprise_contract_activations_subscription")
    entitlement_instance_id = _fk(
        "entitlement_instances", "fk_enterprise_contract_activations_instance", nullable=True,
    )
    term_funding_id = _fk("enterprise_contract_term_fundings", "fk_enterprise_contract_activations_funding")
    seat_commitment_id = _fk(
        "seat_commitments", "fk_enterprise_contract_activations_commitment", deferred=True,
    )
    seats = db.Column(db.Integer, nullable=False)
    activated_at = db.Column(db.DateTime(timezone=True), nullable=False)
    actor_user_id = _fk("users", "fk_enterprise_contract_activations_actor")
    permission_grant_id = _fk("billing_staff_permission_grants", "fk_enterprise_contract_activations_grant")
    idempotency_registry_id = _fk("idempotency_registry", "fk_enterprise_contract_activations_registry")
    domain_event_id = _fk("domain_events", "fk_enterprise_contract_activations_domain_event")

    __table_args__ = (
        db.UniqueConstraint("version_id", name="uq_enterprise_contract_activations_version"),
        db.UniqueConstraint("term_funding_id", name="uq_enterprise_contract_activations_funding"),
        db.UniqueConstraint("seat_commitment_id", name="uq_enterprise_contract_activations_commitment"),
        db.UniqueConstraint("idempotency_registry_id", name="uq_enterprise_contract_activations_registry"),
        db.CheckConstraint("seats > 0", name="ck_enterprise_contract_activations_seats"),
        db.Index("ix_enterprise_contract_activations_subscription", "subscription_id"),
    )


class EnterpriseContractNotice(db.Model):
    """A customer nonrenewal notice or its reversal, recorded by authorized staff."""

    __tablename__ = "enterprise_contract_notices"

    id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    contract_id = _fk("enterprise_contracts", "fk_enterprise_contract_notices_contract")
    term_version_id = _fk("enterprise_contract_versions", "fk_enterprise_contract_notices_term")
    kind = db.Column(db.String(24), nullable=False)
    reverses_notice_id = _fk("enterprise_contract_notices", "fk_enterprise_contract_notices_reverses", nullable=True)
    received_at = db.Column(db.DateTime(timezone=True), nullable=False)
    deadline_at = db.Column(db.DateTime(timezone=True), nullable=False)
    timely = db.Column(db.Boolean, nullable=False)
    evidence_reference = db.Column(db.String(255), nullable=False)
    actor_user_id = _fk("users", "fk_enterprise_contract_notices_actor")
    permission_grant_id = _fk("billing_staff_permission_grants", "fk_enterprise_contract_notices_grant")
    idempotency_registry_id = _fk("idempotency_registry", "fk_enterprise_contract_notices_registry")
    domain_event_id = _fk("domain_events", "fk_enterprise_contract_notices_domain_event")

    __table_args__ = (
        db.UniqueConstraint("idempotency_registry_id", name="uq_enterprise_contract_notices_registry"),
        db.UniqueConstraint("reverses_notice_id", name="uq_enterprise_contract_notices_reversal"),
        db.CheckConstraint(f"kind IN ({_quoted(NOTICE_KINDS)})", name="ck_enterprise_contract_notices_kind"),
        db.CheckConstraint(
            "(kind = 'nonrenewal_reversal') = (reverses_notice_id IS NOT NULL) "
            "AND length(trim(evidence_reference)) > 0",
            name="ck_enterprise_contract_notices_shape",
        ),
        db.Index("ix_enterprise_contract_notices_term", "term_version_id", "kind"),
    )
