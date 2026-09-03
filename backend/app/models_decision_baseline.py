# backend/app/models_decision_baseline.py
#
# The sealed intake baseline — link 1 and link 2 of the evidence chain
# (docs/DECISION_IMPACT_REPORT_SPEC.md §3.7). One row records what a user
# actually supplied when they brought a decision to Jaspen, and the
# deterministic measurements derived from it, frozen at a point in time.
#
# WHY THIS IS ITS OWN TABLE AND NOT A FIELD ON DecisionRecord
#
# Two reasons, both structural rather than stylistic (spec §3.1):
#
#   LIFECYCLE     The baseline is captured at intake. The Decision Record is
#                 assembled after analysis. The baseline has to be able to
#                 exist before any record row does, so it cannot live on one.
#   IMMUTABILITY  decision_records.create_or_refresh_record() re-derives
#                 _DERIVED_FIELDS and writes `record=payload` wholesale on the
#                 create path. A baseline living inside that payload is one
#                 refresh away from being overwritten. The codebase already
#                 solved this problem once — human-owned fields (final_decision,
#                 outcomes, lessons_learned) were deliberately kept OUTSIDE
#                 `record` so re-derivation could never clobber them. The
#                 baseline faces the same hazard and gets the same treatment,
#                 one step further out.
#
# WHY THE ROW HOLDS BOTH HALVES
#
# `submission_payload` is the raw material the user supplied, verbatim.
# `measures` is what was counted from it. Keeping only the second would give us
# a summary of evidence rather than evidence: a reader could see that we
# recorded "2 alternatives at intake" and would have nothing to check that
# against. With both halves present the derivation is falsifiable — re-run the
# engine over the submission and the measures must come back identical.
#
# WRITE-ONCE IS ENFORCED HERE, NOT ONLY IN THE SERVICE LAYER
#
# A guard that lives only in a service function protects only the callers who
# remember to use it. The before_update listener at the bottom of this file
# refuses any flush that alters a protected column on an already-sealed row,
# whatever path reached it.

import uuid
from datetime import datetime

from sqlalchemy import event, inspect as sa_inspect

from . import db

# Bumped when the measure set, the basis rules, or the predicate change shape.
# A baseline sealed under one methodology is never re-verdicted under a later
# one; the version travels on the row so an old report stays readable.
IMPACT_METHODOLOGY_VERSION = 'impact-v1'

# How a baseline measure came by its value (spec §3.7). Only the first two
# count toward the impact predicate.
BASIS_DETERMINISTIC = 'deterministic'          # derived by code from the submission
BASIS_USER_CONFIRMED = 'user_confirmed'        # the user stood behind it
BASIS_PROPOSED_UNCONFIRMED = 'proposed_unconfirmed'  # offered, never confirmed
MEASURE_BASES = (
    BASIS_DETERMINISTIC,
    BASIS_USER_CONFIRMED,
    BASIS_PROPOSED_UNCONFIRMED,
)
PREDICATE_ELIGIBLE_BASES = frozenset({BASIS_DETERMINISTIC, BASIS_USER_CONFIRMED})

SEALED_BY_USER = 'user_confirmed'
SEALED_BY_ANALYSIS = 'auto_on_analysis'
SEALED_BY = (SEALED_BY_USER, SEALED_BY_ANALYSIS)


class SealedBaselineError(RuntimeError):
    """Raised on any attempt to alter a baseline after it was sealed."""


class DecisionBaseline(db.Model):
    __tablename__ = 'decision_baselines'
    __table_args__ = (
        db.UniqueConstraint('user_id', 'thread_id', 'epoch', name='uq_baseline_thread_epoch'),
    )

    id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = db.Column(
        db.String(36),
        db.ForeignKey('users.id', ondelete='CASCADE'),
        nullable=False,
        index=True,
    )
    organization_id = db.Column(db.String(36), nullable=True, index=True)
    thread_id = db.Column(db.String(64), nullable=False, index=True)

    # Epochs exist because decisions get restated. A material restatement opens
    # a new epoch with its own baseline rather than amending a sealed one. What
    # counts as material is deliberately unanswered until we have real
    # transcripts to look at (spec §11 Q1), so nothing yet opens epoch 2.
    epoch = db.Column(db.Integer, nullable=False, default=1)

    # ── Link 1: what the user supplied, verbatim ─────────────────────────
    # No normalization, no summarization, no truncation. Attachment bytes are
    # not stored here; the reference (name, size, hash, locator) is, so the
    # chain still resolves to a specific artifact rather than a description.
    submission_payload = db.Column(db.JSON, nullable=False, default=dict)

    # ── Link 2: what was measured from it ────────────────────────────────
    # {measure_id: {'value': int|float|dict|None, 'basis': str, 'reason': str?}}
    measures = db.Column(db.JSON, nullable=False, default=dict)

    # ── Seal ─────────────────────────────────────────────────────────────
    sealed_at = db.Column(db.DateTime, nullable=True)
    sealed_by = db.Column(db.String(32), nullable=True)
    # Component hashes, so a mismatch says WHICH half diverged. A single
    # combined hash would prove only that something did.
    submission_hash = db.Column(db.String(80), nullable=True)
    measures_hash = db.Column(db.String(80), nullable=True)
    content_hash = db.Column(db.String(80), nullable=True)

    # The engine versions in force at seal time. Re-deriving link 2 from link 1
    # is only meaningful against the versions that produced it.
    readiness_spec_version = db.Column(db.String(32), nullable=True)
    methodology_version = db.Column(
        db.String(32), nullable=False, default=IMPACT_METHODOLOGY_VERSION,
    )

    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    updated_at = db.Column(
        db.DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow,
    )

    @property
    def is_sealed(self):
        return self.sealed_at is not None

    def to_dict(self, *, include_submission=False):
        """Serialized baseline.

        `include_submission` is off by default and is the custody boundary
        (spec §3.7): the raw submission is Ring 1 customer material and never
        travels with a derived export. Only an owner reading their own baseline
        gets it.
        """
        payload = {
            'id': self.id,
            'thread_id': self.thread_id,
            'epoch': self.epoch,
            'sealed': self.is_sealed,
            'sealed_at': self.sealed_at.isoformat() if self.sealed_at else None,
            'sealed_by': self.sealed_by,
            'submission_hash': self.submission_hash,
            'measures_hash': self.measures_hash,
            'content_hash': self.content_hash,
            'readiness_spec_version': self.readiness_spec_version,
            'methodology_version': self.methodology_version,
            'measures': self.measures if isinstance(self.measures, dict) else {},
            'submission_ref': self.submission_ref(),
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None,
        }
        if include_submission:
            payload['submission_payload'] = self.submission_payload
        return payload

    def submission_ref(self):
        """Link 1 as a pointer rather than a payload.

        The report embeds this instead of the submission itself: the payload
        can be large and most readers are not auditing it. An entitled reader
        resolves the pointer to the sealed material.
        """
        submission = self.submission_payload if isinstance(self.submission_payload, dict) else {}
        turns = submission.get('turns')
        attachments = submission.get('attachments')
        return {
            'baseline_id': self.id,
            'turn_count': len(turns) if isinstance(turns, list) else 0,
            'attachment_count': len(attachments) if isinstance(attachments, list) else 0,
            'retrievable': bool(submission),
        }


# Columns that a seal freezes. `sealed_at`/`sealed_by` are included so a sealed
# row cannot be quietly re-sealed under a different story.
_PROTECTED_AFTER_SEAL = (
    'user_id', 'thread_id', 'epoch',
    'submission_payload', 'measures',
    'submission_hash', 'measures_hash', 'content_hash',
    'sealed_at', 'sealed_by',
    'readiness_spec_version', 'methodology_version',
)


@event.listens_for(DecisionBaseline, 'before_update')
def _refuse_sealed_mutation(mapper, connection, target):
    """Refuse any flush that alters a sealed baseline (spec §3.5, AT-13).

    Enforced at the ORM rather than in the service function because a guard
    that lives only in a service protects only the callers who remember to use
    it. The unsealed → sealed transition is allowed; everything after it is not.

    One honest limit: an IN-PLACE mutation of the `submission_payload` or
    `measures` dicts without flag_modified produces no attribute history, so
    this listener cannot see it. That path is why content_hash is re-verified
    on every read (spec §3.5) — the listener stops the ordinary mistake, the
    hash catches the exotic one.
    """
    # Ask the DATABASE whether this row was already sealed, rather than the
    # in-memory attribute. After a commit every attribute is expired, so
    # `sealed_at` on the instance is either unloaded or already overwritten by
    # the very flush being inspected — neither answers "was it sealed before
    # this write?". The persisted value does, and it is the one reading that
    # cannot be arranged by the caller.
    table = DecisionBaseline.__table__
    row = connection.execute(
        table.select().with_only_columns(table.c.sealed_at).where(table.c.id == target.id)
    ).first()
    if not row or row[0] is None:
        return  # unsealed, or the seal itself: both are allowed

    state = sa_inspect(target)

    changed = [
        name for name in _PROTECTED_AFTER_SEAL
        if state.attrs[name].history.has_changes()
    ]
    if changed:
        raise SealedBaselineError(
            f'baseline {target.id} was sealed at {target.sealed_at}; '
            f'refusing to alter {", ".join(sorted(changed))}'
        )
