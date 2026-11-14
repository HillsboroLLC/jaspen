"""Inactive Phase 8 seat-commitment evidence (lifecycle D09).

Paid seat commitment is an Entitlement Authority record. Occupancy is never
stored here as authority: it is projected from active organization membership
and only recorded as observed audit evidence on the decision that used it.
"""

import uuid

from . import db


SEAT_COMMITMENT_ORIGINS = ("opening", "increase", "reduction")
SEAT_CHANGE_STATES = (
    "increased", "scheduled_reduction", "blocked_occupancy", "awaiting_payment",
    "reduced", "cancelled", "superseded",
)
ACTIVE_SEAT_CHANGE_STATES = ("scheduled_reduction", "blocked_occupancy", "awaiting_payment")
SEAT_FUNDING_CONTRACT_VERSION = 1
SEAT_FUNDING_SOURCES = ("included", "purchased")
SEAT_TERM_FUNDING_PURPOSES = ("opening", "increase", "renewal", "top_up")
SEAT_TERM_FUNDING_STATES = ("funded", "unresolved")


def _quoted(values):
    return ",".join(f"'{value}'" for value in values)


class SeatCommitment(db.Model):
    """One immutable interval of paid seat commitment for a subscription."""

    __tablename__ = "seat_commitments"

    id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    billing_account_id = db.Column(
        db.String(36),
        db.ForeignKey("billing_accounts.id", name="fk_seat_commitments_account", ondelete="RESTRICT"),
        nullable=False,
    )
    subscription_id = db.Column(
        db.String(36),
        db.ForeignKey("billing_subscriptions.id", name="fk_seat_commitments_subscription", ondelete="RESTRICT"),
        nullable=False,
    )
    quantity = db.Column(db.Integer, nullable=False)
    origin_type = db.Column(db.String(24), nullable=False)
    state = db.Column(db.String(16), nullable=False, default="active", server_default="active")
    starts_at = db.Column(db.DateTime(timezone=True), nullable=False)
    ends_at = db.Column(db.DateTime(timezone=True), nullable=True)
    previous_commitment_id = db.Column(
        db.String(36),
        db.ForeignKey("seat_commitments.id", name="fk_seat_commitments_previous", ondelete="RESTRICT"),
        nullable=True,
    )
    idempotency_registry_id = db.Column(
        db.String(36),
        db.ForeignKey("idempotency_registry.id", name="fk_seat_commitments_registry", ondelete="RESTRICT"),
        nullable=False,
    )
    domain_event_id = db.Column(
        db.String(36),
        db.ForeignKey("domain_events.id", name="fk_seat_commitments_domain_event", ondelete="RESTRICT"),
        nullable=False,
    )
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, server_default=db.func.now())

    __table_args__ = (
        db.CheckConstraint("quantity > 0", name="ck_seat_commitments_quantity"),
        db.CheckConstraint(
            f"origin_type IN ({_quoted(SEAT_COMMITMENT_ORIGINS)})",
            name="ck_seat_commitments_origin",
        ),
        db.CheckConstraint(
            "(state='active' AND ends_at IS NULL) OR "
            "(state='replaced' AND ends_at IS NOT NULL AND ends_at >= starts_at)",
            name="ck_seat_commitments_interval",
        ),
        db.CheckConstraint(
            "(origin_type='opening' AND previous_commitment_id IS NULL) OR "
            "(origin_type<>'opening' AND previous_commitment_id IS NOT NULL)",
            name="ck_seat_commitments_lineage",
        ),
        db.CheckConstraint(
            "previous_commitment_id IS NULL OR previous_commitment_id<>id",
            name="ck_seat_commitments_not_self",
        ),
        db.UniqueConstraint("previous_commitment_id", name="uq_seat_commitments_previous"),
        db.UniqueConstraint("idempotency_registry_id", name="uq_seat_commitments_registry"),
        db.UniqueConstraint("domain_event_id", name="uq_seat_commitments_domain_event"),
        db.Index("ix_seat_commitments_subscription_starts", "subscription_id", "starts_at", "id"),
        db.Index(
            "uq_seat_commitments_one_active",
            "subscription_id",
            unique=True,
            postgresql_where=db.text("state = 'active'"),
            sqlite_where=db.text("state = 'active'"),
        ),
        db.Index(
            "uq_seat_commitments_one_opening",
            "subscription_id",
            unique=True,
            postgresql_where=db.text("origin_type = 'opening'"),
            sqlite_where=db.text("origin_type = 'opening'"),
        ),
    )


class SeatChange(db.Model):
    """Historically retained D09 seat-change command and current-state projection."""

    __tablename__ = "seat_changes"

    id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    billing_account_id = db.Column(
        db.String(36),
        db.ForeignKey("billing_accounts.id", name="fk_seat_changes_account", ondelete="RESTRICT"),
        nullable=False,
    )
    subscription_id = db.Column(
        db.String(36),
        db.ForeignKey("billing_subscriptions.id", name="fk_seat_changes_subscription", ondelete="RESTRICT"),
        nullable=False,
    )
    kind = db.Column(db.String(16), nullable=False)
    state = db.Column(db.String(32), nullable=False)
    base_commitment_id = db.Column(
        db.String(36),
        db.ForeignKey("seat_commitments.id", name="fk_seat_changes_base_commitment", ondelete="RESTRICT"),
        nullable=False,
    )
    result_commitment_id = db.Column(
        db.String(36),
        db.ForeignKey("seat_commitments.id", name="fk_seat_changes_result_commitment", ondelete="RESTRICT"),
        nullable=True,
    )
    base_quantity = db.Column(db.Integer, nullable=False)
    target_quantity = db.Column(db.Integer, nullable=False)
    seat_delta = db.Column(db.Integer, nullable=True)
    occupancy_at_request = db.Column(db.Integer, nullable=False)
    requested_at = db.Column(db.DateTime(timezone=True), nullable=False)
    effective_at = db.Column(db.DateTime(timezone=True), nullable=False)
    authorizing_role_grant_id = db.Column(
        db.String(36),
        db.ForeignKey("billing_role_grants.id", name="fk_seat_changes_role_grant", ondelete="RESTRICT"),
        nullable=False,
    )
    requested_by_user_id = db.Column(
        db.String(36),
        db.ForeignKey("users.id", name="fk_seat_changes_requested_by", ondelete="RESTRICT"),
        nullable=False,
    )
    command_key = db.Column(db.String(512), nullable=False)
    request_fingerprint = db.Column(db.String(64), nullable=False)
    idempotency_registry_id = db.Column(
        db.String(36),
        db.ForeignKey("idempotency_registry.id", name="fk_seat_changes_registry", ondelete="RESTRICT"),
        nullable=False,
    )
    domain_event_id = db.Column(
        db.String(36),
        db.ForeignKey("domain_events.id", name="fk_seat_changes_domain_event", ondelete="RESTRICT"),
        nullable=False,
    )
    supersedes_change_id = db.Column(
        db.String(36),
        db.ForeignKey("seat_changes.id", name="fk_seat_changes_supersedes", ondelete="RESTRICT"),
        nullable=True,
    )
    last_event_id = db.Column(db.String(36), nullable=True)
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, server_default=db.func.now())

    __table_args__ = (
        db.CheckConstraint("kind IN ('increase','reduction')", name="ck_seat_changes_kind"),
        db.CheckConstraint(f"state IN ({_quoted(SEAT_CHANGE_STATES)})", name="ck_seat_changes_state"),
        db.CheckConstraint(
            "(kind='increase' AND state='increased' AND seat_delta IS NOT NULL AND seat_delta>0 "
            "AND target_quantity=base_quantity+seat_delta "
            "AND result_commitment_id IS NOT NULL AND requested_at<=effective_at) OR "
            "(kind='reduction' AND state<>'increased' AND seat_delta IS NULL "
            "AND target_quantity<base_quantity "
            "AND requested_at<effective_at "
            "AND ((state='reduced' AND result_commitment_id IS NOT NULL) OR "
            "(state<>'reduced' AND result_commitment_id IS NULL)))",
            name="ck_seat_changes_shape",
        ),
        db.CheckConstraint(
            "base_quantity>0 AND target_quantity>0 AND occupancy_at_request>=0",
            name="ck_seat_changes_quantities",
        ),
        db.CheckConstraint(
            "length(trim(command_key))>0 AND length(request_fingerprint)=64 "
            "AND request_fingerprint=lower(request_fingerprint)",
            name="ck_seat_changes_identity",
        ),
        db.CheckConstraint(
            "supersedes_change_id IS NULL OR supersedes_change_id<>id",
            name="ck_seat_changes_not_self",
        ),
        db.UniqueConstraint("command_key", name="uq_seat_changes_command_key"),
        db.UniqueConstraint("idempotency_registry_id", name="uq_seat_changes_registry"),
        db.UniqueConstraint("domain_event_id", name="uq_seat_changes_domain_event"),
        db.UniqueConstraint("result_commitment_id", name="uq_seat_changes_result_commitment"),
        db.Index("ix_seat_changes_subscription_state", "subscription_id", "state", "effective_at"),
        db.Index(
            "uq_seat_changes_one_active_reduction",
            "subscription_id",
            unique=True,
            postgresql_where=db.text(f"state IN ({_quoted(ACTIVE_SEAT_CHANGE_STATES)})"),
            sqlite_where=db.text(f"state IN ({_quoted(ACTIVE_SEAT_CHANGE_STATES)})"),
        ),
    )


class SeatChangeEvent(db.Model):
    """Append-only D09 state transition for a seat-change command."""

    __tablename__ = "seat_change_events"

    id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    seat_change_id = db.Column(
        db.String(36),
        db.ForeignKey("seat_changes.id", name="fk_seat_change_events_change", ondelete="RESTRICT"),
        nullable=False,
    )
    from_state = db.Column(db.String(32), nullable=False)
    to_state = db.Column(db.String(32), nullable=False)
    transition = db.Column(db.String(64), nullable=False)
    effective_at = db.Column(db.DateTime(timezone=True), nullable=False)
    target_effective_at = db.Column(db.DateTime(timezone=True), nullable=True)
    occupancy_observed = db.Column(db.Integer, nullable=True)
    actor_type = db.Column(db.String(32), nullable=False)
    actor_id = db.Column(db.String(255), nullable=False)
    authorizing_role_grant_id = db.Column(
        db.String(36),
        db.ForeignKey("billing_role_grants.id", name="fk_seat_change_events_role_grant", ondelete="RESTRICT"),
        nullable=True,
    )
    term_funding_id = db.Column(
        db.String(36),
        db.ForeignKey("seat_term_fundings.id", name="fk_seat_change_events_term_funding", ondelete="RESTRICT"),
        nullable=True,
    )
    result_commitment_id = db.Column(
        db.String(36),
        db.ForeignKey("seat_commitments.id", name="fk_seat_change_events_result_commitment", ondelete="RESTRICT"),
        nullable=True,
    )
    evidence_json = db.Column(db.JSON, nullable=False)
    idempotency_registry_id = db.Column(
        db.String(36),
        db.ForeignKey("idempotency_registry.id", name="fk_seat_change_events_registry", ondelete="RESTRICT"),
        nullable=False,
    )
    domain_event_id = db.Column(
        db.String(36),
        db.ForeignKey("domain_events.id", name="fk_seat_change_events_domain_event", ondelete="RESTRICT"),
        nullable=False,
    )
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, server_default=db.func.now())

    __table_args__ = (
        db.CheckConstraint("from_state<>to_state", name="ck_seat_change_events_transition"),
        db.CheckConstraint(
            "length(trim(transition))>0 AND length(trim(actor_type))>0 AND length(trim(actor_id))>0",
            name="ck_seat_change_events_text",
        ),
        db.CheckConstraint(
            "(actor_type='user' AND authorizing_role_grant_id IS NOT NULL) OR "
            "(actor_type='system' AND authorizing_role_grant_id IS NULL)",
            name="ck_seat_change_events_actor",
        ),
        db.CheckConstraint(
            "(to_state='reduced' AND result_commitment_id IS NOT NULL) OR "
            "(to_state<>'reduced' AND result_commitment_id IS NULL)",
            name="ck_seat_change_events_result",
        ),
        db.CheckConstraint(
            "occupancy_observed IS NULL OR occupancy_observed>=0",
            name="ck_seat_change_events_occupancy",
        ),
        db.CheckConstraint(
            "(to_state IN ('reduced','blocked_occupancy')) = (term_funding_id IS NOT NULL)",
            name="ck_seat_change_events_funding",
        ),
        db.UniqueConstraint("idempotency_registry_id", name="uq_seat_change_events_registry"),
        db.UniqueConstraint("domain_event_id", name="uq_seat_change_events_domain_event"),
        db.UniqueConstraint("result_commitment_id", name="uq_seat_change_events_result_commitment"),
        db.UniqueConstraint("term_funding_id", name="uq_seat_change_events_term_funding"),
        db.Index("ix_seat_change_events_change_created", "seat_change_id", "created_at", "id"),
    )


class SeatCommitmentFence(db.Model):
    """Concurrency-only fence serializing Phase 8 writes for one subscription.

    It holds no seat quantity or state. The migrated guards flip it on every
    seat commitment, change, and change-event insert so a stale snapshot
    cannot act on seat history committed after it began (D14 ordering).
    """

    __tablename__ = "seat_commitment_fences"

    subscription_id = db.Column(
        db.String(36),
        db.ForeignKey("billing_subscriptions.id", name="fk_seat_commitment_fences_subscription", ondelete="RESTRICT"),
        primary_key=True,
    )
    fence_bit = db.Column(db.Boolean, nullable=False, server_default=db.false())


class SeatFundingAttribution(db.Model):
    """Immutable, versioned statement of how many seats one paid line supports.

    It references Phase 5.2 evidence and never reinterprets
    the financial line's quantity. ``included`` seats come only from the approved
    plan definition; ``purchased`` seats are the separately bought seats that
    the recorded payment line funds for the stated paid term.
    """

    __tablename__ = "seat_funding_attributions"

    id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    billing_account_id = db.Column(
        db.String(36),
        db.ForeignKey("billing_accounts.id", name="fk_seat_funding_attributions_account", ondelete="RESTRICT"),
        nullable=False,
    )
    subscription_id = db.Column(
        db.String(36),
        db.ForeignKey("billing_subscriptions.id", name="fk_seat_funding_attributions_subscription", ondelete="RESTRICT"),
        nullable=False,
    )
    financial_line_id = db.Column(
        db.String(36),
        db.ForeignKey("financial_lines.id", name="fk_seat_funding_attributions_line", ondelete="RESTRICT"),
        nullable=False,
    )
    seat_source = db.Column(db.String(16), nullable=False)
    seats = db.Column(db.Integer, nullable=False)
    entitlement_definition_id = db.Column(
        db.String(36),
        db.ForeignKey("entitlement_definitions.id", name="fk_seat_funding_attributions_definition", ondelete="RESTRICT"),
        nullable=True,
    )
    term_starts_at = db.Column(db.DateTime(timezone=True), nullable=False)
    term_ends_at = db.Column(db.DateTime(timezone=True), nullable=False)
    contract_version = db.Column(db.Integer, nullable=False)
    evidence_reference = db.Column(db.String(255), nullable=False)
    actor_type = db.Column(db.String(32), nullable=False)
    actor_id = db.Column(db.String(255), nullable=False)
    idempotency_registry_id = db.Column(
        db.String(36),
        db.ForeignKey("idempotency_registry.id", name="fk_seat_funding_attributions_registry", ondelete="RESTRICT"),
        nullable=False,
    )
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, server_default=db.func.now())

    __table_args__ = (
        db.CheckConstraint(
            f"seat_source IN ({_quoted(SEAT_FUNDING_SOURCES)})", name="ck_seat_funding_attributions_source",
        ),
        db.CheckConstraint(
            "(seat_source='included' AND entitlement_definition_id IS NOT NULL AND seats>=0) OR "
            "(seat_source='purchased' AND entitlement_definition_id IS NULL AND seats>0)",
            name="ck_seat_funding_attributions_shape",
        ),
        db.CheckConstraint("term_ends_at > term_starts_at", name="ck_seat_funding_attributions_term"),
        db.CheckConstraint(
            f"contract_version = {SEAT_FUNDING_CONTRACT_VERSION}", name="ck_seat_funding_attributions_version",
        ),
        db.CheckConstraint(
            "length(trim(evidence_reference))>0 AND length(trim(actor_type))>0 AND length(trim(actor_id))>0",
            name="ck_seat_funding_attributions_text",
        ),
        db.UniqueConstraint("financial_line_id", name="uq_seat_funding_attributions_line"),
        db.UniqueConstraint("idempotency_registry_id", name="uq_seat_funding_attributions_registry"),
        db.Index("ix_seat_funding_attributions_subscription_term", "subscription_id", "term_starts_at", "id"),
    )


class SeatTermFunding(db.Model):
    """Immutable decision on how far one paid term of a commitment is funded."""

    __tablename__ = "seat_term_fundings"

    id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    billing_account_id = db.Column(
        db.String(36),
        db.ForeignKey("billing_accounts.id", name="fk_seat_term_fundings_account", ondelete="RESTRICT"),
        nullable=False,
    )
    subscription_id = db.Column(
        db.String(36),
        db.ForeignKey("billing_subscriptions.id", name="fk_seat_term_fundings_subscription", ondelete="RESTRICT"),
        nullable=False,
    )
    commitment_id = db.Column(
        db.String(36),
        db.ForeignKey("seat_commitments.id", name="fk_seat_term_fundings_commitment", ondelete="RESTRICT"),
        nullable=False,
    )
    purpose = db.Column(db.String(16), nullable=False)
    term_starts_at = db.Column(db.DateTime(timezone=True), nullable=False)
    term_ends_at = db.Column(db.DateTime(timezone=True), nullable=False)
    required_seats = db.Column(db.Integer, nullable=False)
    funded_seats = db.Column(db.Integer, nullable=False)
    state = db.Column(db.String(16), nullable=False)
    supersedes_funding_id = db.Column(
        db.String(36),
        db.ForeignKey("seat_term_fundings.id", name="fk_seat_term_fundings_supersedes", ondelete="RESTRICT"),
        nullable=True,
    )
    idempotency_registry_id = db.Column(
        db.String(36),
        db.ForeignKey("idempotency_registry.id", name="fk_seat_term_fundings_registry", ondelete="RESTRICT"),
        nullable=False,
    )
    domain_event_id = db.Column(
        db.String(36),
        db.ForeignKey("domain_events.id", name="fk_seat_term_fundings_domain_event", ondelete="RESTRICT"),
        nullable=False,
    )
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, server_default=db.func.now())

    __table_args__ = (
        db.CheckConstraint(
            f"purpose IN ({_quoted(SEAT_TERM_FUNDING_PURPOSES)})", name="ck_seat_term_fundings_purpose",
        ),
        db.CheckConstraint(
            f"state IN ({_quoted(SEAT_TERM_FUNDING_STATES)})", name="ck_seat_term_fundings_state",
        ),
        db.CheckConstraint(
            "required_seats>0 AND funded_seats>=0 AND funded_seats<=required_seats "
            "AND ((state='funded') = (funded_seats=required_seats)) AND term_ends_at>term_starts_at",
            name="ck_seat_term_fundings_amounts",
        ),
        db.CheckConstraint(
            "(purpose IN ('opening','increase') AND state='funded' AND supersedes_funding_id IS NULL) OR "
            "(purpose='renewal' AND supersedes_funding_id IS NULL) OR "
            "(purpose='top_up' AND supersedes_funding_id IS NOT NULL)",
            name="ck_seat_term_fundings_shape",
        ),
        db.CheckConstraint(
            "supersedes_funding_id IS NULL OR supersedes_funding_id<>id", name="ck_seat_term_fundings_not_self",
        ),
        db.UniqueConstraint("supersedes_funding_id", name="uq_seat_term_fundings_supersedes"),
        db.UniqueConstraint("idempotency_registry_id", name="uq_seat_term_fundings_registry"),
        db.UniqueConstraint("domain_event_id", name="uq_seat_term_fundings_domain_event"),
        db.Index("ix_seat_term_fundings_subscription_term", "subscription_id", "term_starts_at", "id"),
        db.Index(
            "uq_seat_term_fundings_one_renewal",
            "subscription_id", "term_starts_at",
            unique=True,
            postgresql_where=db.text("purpose = 'renewal'"),
            sqlite_where=db.text("purpose = 'renewal'"),
        ),
        db.Index(
            "uq_seat_term_fundings_new_commitment",
            "commitment_id",
            unique=True,
            postgresql_where=db.text("purpose IN ('opening','increase')"),
            sqlite_where=db.text("purpose IN ('opening','increase')"),
        ),
    )


class SeatFundingUse(db.Model):
    """Single use of one funding attribution by one term-funding decision."""

    __tablename__ = "seat_funding_uses"

    id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    attribution_id = db.Column(
        db.String(36),
        db.ForeignKey("seat_funding_attributions.id", name="fk_seat_funding_uses_attribution", ondelete="RESTRICT"),
        nullable=False,
    )
    term_funding_id = db.Column(
        db.String(36),
        db.ForeignKey("seat_term_fundings.id", name="fk_seat_funding_uses_term_funding", ondelete="RESTRICT"),
        nullable=False,
    )
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, server_default=db.func.now())

    __table_args__ = (
        db.UniqueConstraint("attribution_id", name="uq_seat_funding_uses_attribution"),
        db.Index("ix_seat_funding_uses_term_funding", "term_funding_id"),
    )
