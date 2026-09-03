# backend/app/models_challenge_event.py
#
# The challenge ledger — link 3 of the evidence chain
# (docs/DECISION_IMPACT_REPORT_SPEC.md §4). An append-only record of the
# analytical work Jaspen did on a decision.
#
# WHY THIS IS NOT AN ACTIVITY LOG
#
# Counts alone show that a decision record grew. They cannot show that JASPEN
# was the cause, and the attribution cap exists precisely because we could not
# tell those apart. This table closes that gap — which only works if it holds
# analytical findings and nothing else.
#
# So the bar for a row here is not "something happened". It is: would this
# legitimately appear under "what Jaspen challenged, validated, surfaced,
# quantified, or resolved" in front of someone disputing the claim? Scoring
# passes, renders, saves, refreshes, backfills and background arithmetic all
# happen constantly and none of them belong here. A ledger that logged them
# would inflate the very number the cap was invented to protect.
#
# EVERY ROW IS TIED TO SYSTEM STATE, NEVER TO PROSE
#
# A model may author the CONTENT of a challenge — the product already has it
# write the "what would resolve this" line. It may not author the FACT. Each
# row here is emitted from a deterministic state transition (a confidence grade,
# a computed swing, a generated dependency) at the moment that state was
# written. Nothing is inferred afterwards by reading a transcript, and no row
# exists because a model said it did something.

import uuid
from datetime import datetime

from . import db

# ── The taxonomy (spec §4.3) ─────────────────────────────────────────────
#
# Five types, each with a real emitter. Three from the original draft
# (`criterion_added`, `alternative_introduced`, `weighting_challenged`) are
# absent: no call site can establish who authored a criterion or an option, and
# the product is instructed never to alter a user's weights. Recording them
# anyway would attribute the user's own thinking to Jaspen, which is the exact
# failure the attribution cap exists to prevent. See spec §4.5.
EVENT_EVIDENCE_REQUESTED = 'evidence_requested'
EVENT_ASSUMPTION_RESOLVED = 'assumption_resolved'
EVENT_ASSUMPTION_LEFT_OPEN = 'assumption_left_open'
EVENT_EXPOSURE_QUANTIFIED = 'exposure_quantified'
EVENT_DEPENDENCY_SURFACED = 'dependency_surfaced'

EVENT_TYPES = (
    EVENT_EVIDENCE_REQUESTED,
    EVENT_ASSUMPTION_RESOLVED,
    EVENT_ASSUMPTION_LEFT_OPEN,
    EVENT_EXPOSURE_QUANTIFIED,
    EVENT_DEPENDENCY_SURFACED,
)

# Which types may lift the attribution cap (spec §5.4). Every current type
# qualifies, because every current type is a substantive analytical finding
# rendered on a surface the user can open. The set is declared separately from
# EVENT_TYPES anyway: the moment a type is added that is bookkeeping rather
# than analysis, it must be possible to admit it to the ledger without
# admitting it to the cap.
CAP_QUALIFYING_TYPES = frozenset(EVENT_TYPES)

# Who produced the thing the event is about.
ACTOR_JASPEN = 'jaspen'
ACTOR_USER_CONFIRMED = 'user_confirmed'
ACTOR_USER_SUPPLIED = 'user_supplied'
ACTORS = (ACTOR_JASPEN, ACTOR_USER_CONFIRMED, ACTOR_USER_SUPPLIED)

TARGET_CRITERION = 'criterion'
TARGET_DEPENDENCY = 'dependency'
TARGET_KINDS = (TARGET_CRITERION, TARGET_DEPENDENCY)


class ChallengeEvent(db.Model):
    __tablename__ = 'decision_challenge_events'
    __table_args__ = (
        # Idempotence, enforced by the database rather than by the caller
        # remembering. A retry, a refresh, a repeated scoring call or a
        # re-executed tool must never make Jaspen look like it did more
        # intellectual work than it did (spec §4.1).
        db.UniqueConstraint(
            'user_id', 'thread_id', 'epoch', 'dedupe_key',
            name='uq_challenge_event_dedupe',
        ),
        db.Index('ix_challenge_events_thread', 'user_id', 'thread_id', 'epoch'),
    )

    id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = db.Column(
        db.String(36), db.ForeignKey('users.id', ondelete='CASCADE'),
        nullable=False, index=True,
    )
    organization_id = db.Column(db.String(36), nullable=True, index=True)
    thread_id = db.Column(db.String(64), nullable=False, index=True)
    epoch = db.Column(db.Integer, nullable=False, default=1)

    # Ordering within a thread. `occurred_at` is authoritative; `seq` is a
    # convenience for rendering and is assigned single-threaded at write time.
    seq = db.Column(db.Integer, nullable=False, default=0)
    occurred_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)

    type = db.Column(db.String(40), nullable=False, index=True)

    # WHICH DECISION ELEMENT. Identity is a stable key — a rubric criterion key
    # or a plan dependency id — never a label, so a criterion challenged in one
    # pass and resolved three passes later is recognisably the same criterion
    # (spec §4.4). The label rides along for rendering only.
    target_kind = db.Column(db.String(24), nullable=True)
    target_id = db.Column(db.String(120), nullable=True, index=True)
    target_label = db.Column(db.String(255), nullable=True)

    # WHAT STATE TRIGGERED IT. The deterministic facts the event was derived
    # from — the grade, the previous grade, the computed swing. This is what
    # makes a row checkable rather than merely asserted.
    trigger = db.Column(db.JSON, nullable=False, default=dict)

    origin = db.Column(db.String(40), nullable=False)   # emitting subsystem
    actor = db.Column(db.String(24), nullable=False, default=ACTOR_JASPEN)
    # Could the user actually observe this intervention? Only observable events
    # may lift the attribution cap: something nobody could see did not
    # challenge anyone.
    user_visible = db.Column(db.Boolean, nullable=False, default=True)

    # The artifact whose write produced this event (a scorecard id, a plan id).
    derivation_id = db.Column(db.String(120), nullable=True)
    dedupe_key = db.Column(db.String(200), nullable=False)

    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)

    def to_dict(self):
        return {
            'id': self.id,
            'seq': self.seq,
            'occurred_at': self.occurred_at.isoformat() if self.occurred_at else None,
            'type': self.type,
            'target_kind': self.target_kind,
            'target_id': self.target_id,
            'target_label': self.target_label,
            'trigger': self.trigger if isinstance(self.trigger, dict) else {},
            'origin': self.origin,
            'actor': self.actor,
            'user_visible': self.user_visible,
            'derivation_id': self.derivation_id,
        }
