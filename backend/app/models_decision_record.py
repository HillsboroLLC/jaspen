# backend/app/models_decision_record.py
#
# The canonical Decision Record — the permanent artifact created after a
# decision has been analyzed (Constitution Art. 20: "Every completed decision
# becomes knowledge"). The scorecard is one COMPONENT of the record; the record
# is the durable unit from which future capabilities derive (Decision Library,
# kits, dashboards, outcome tracking, pattern discovery, decision intelligence).
#
# Design principles:
# - One canonical schema, three custody rings (Art. 21):
#     Ring 1 (private):  customer-owned, the default, never shared.
#     Ring 2 (library):  opt-in only, anonymized or named, powers the public
#                        Decision Library and its derivations. Consent is a
#                        recorded, timestamped act — never a default.
#     Ring 3 (internal): evaluation/calibration corpus. Never customer-facing.
#                        Privacy-first default: records are NOT eligible until
#                        explicitly marked (policy work precedes data use).
# - Peer-to-peer scorecards: the record stores `scorecards` as a flat list of
#   standalone decision artifacts. It deliberately does NOT encode the legacy
#   baseline/variant hierarchy (see docs/peer-scorecard-migration-audit.md).
# - Human-readable: the payload is plain JSON an operator can read (Art. 20 —
#   "organizational memory, not hidden model state").
# - Additive: nothing in existing session/scenario storage changes. The record
#   is assembled FROM those stores; it never mutates them.

import uuid
from datetime import datetime

from . import db

# Schema version for the JSON payload in `record`. Bump when the canonical
# field set changes shape; readers must tolerate older versions.
DECISION_RECORD_SCHEMA_VERSION = 1

# Lifecycle vocabulary (promoted `status` column):
#   in_analysis      — record created; decision still being worked
#   recorded         — analysis complete; record snapshotted
#   decided          — final decision captured (Art. 4: the human decided)
#   outcome_recorded — at least one real-world outcome captured
#   archived         — retained but closed
DECISION_RECORD_STATUSES = (
    'in_analysis', 'recorded', 'decided', 'outcome_recorded', 'archived',
)

# Ring 2 consent vocabulary.
LIBRARY_CONSENT_LEVELS = ('none', 'anonymized', 'named')


class DecisionRecord(db.Model):
    __tablename__ = 'decision_records'

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
    organization_id = db.Column(db.String(36), nullable=True, index=True)

    # Provenance: the conversation this record was assembled from. One active
    # record per thread (enforced in the service layer, not the schema, so
    # future re-analysis flows stay possible).
    thread_id = db.Column(db.String(64), nullable=False, index=True)

    # Promoted, queryable columns (duplicated inside `record` for readability).
    title = db.Column(db.String(255), nullable=False, default='Untitled decision')
    decision_statement = db.Column(db.Text, nullable=True)
    status = db.Column(db.String(32), nullable=False, default='in_analysis', index=True)
    decision_type = db.Column(db.String(64), nullable=True, index=True)   # e.g. 'job_offer'
    altitude = db.Column(db.String(32), nullable=True)                    # individual|solopreneur|team|enterprise

    # ── Custody (Art. 21) ────────────────────────────────────────────────
    # Ring 1 is implicit: every row is private and customer-owned by default.
    library_consent = db.Column(db.String(16), nullable=False, default='none')
    library_consented_at = db.Column(db.DateTime, nullable=True)
    # Ring 3: privacy-first — nothing enters the internal corpus until
    # explicitly flipped by policy-governed tooling (never by default).
    internal_corpus_eligible = db.Column(db.Boolean, nullable=False, default=False)

    # ── The canonical payload ────────────────────────────────────────────
    # Full human-readable record. See decision_records.assemble_record_payload
    # for the field-by-field contract.
    schema_version = db.Column(db.Integer, nullable=False, default=DECISION_RECORD_SCHEMA_VERSION)
    record = db.Column(db.JSON, nullable=False, default=dict)

    # Human-owned, append-only fields kept OUTSIDE `record` so a re-derivation
    # of the analysis can never clobber them (Art. 20: outcomes are part of the
    # decision that produced them; Art. 2/4: the human's entries are theirs).
    final_decision = db.Column(db.Text, nullable=True)
    outcomes = db.Column(db.JSON, nullable=False, default=list)          # [{summary, recorded_at, ...}]
    lessons_learned = db.Column(db.JSON, nullable=False, default=list)   # [{lesson, recorded_at, ...}]

    # Search/retrieval metadata (future: Library, AI search, dashboards).
    tags = db.Column(db.JSON, nullable=False, default=list)

    # ── Supersession (Phase 5) ───────────────────────────────────────────
    #
    # ONE forward link, deliberately. The obvious design stores both
    # `supersedes_id` and `superseded_by_id`, but they are inverses of each
    # other and can desync -- and a desynced pair means the record claims a
    # current-state it does not have, which is the worst failure mode for
    # institutional memory. The reverse direction is a single indexed query
    # instead (successor_of()).
    #
    # There is likewise NO stored `is_current` flag. A denormalized boolean
    # must be rewritten on every supersession and silently lies the moment an
    # update is missed. Current state is DERIVED -- see current_state() in
    # app/decision_records.py.
    supersedes_id = db.Column(
        db.String(36),
        db.ForeignKey('decision_records.id', ondelete='SET NULL'),
        nullable=True,
        index=True,
    )
    # When the supersession link was made. A real event with a real timestamp,
    # unlike an `effective_from` / `effective_until` pair -- nothing in the
    # product captures when a decision *takes effect*, so inventing those
    # fields would fabricate a signal. `decided_at` remains the only temporal
    # marker of the decision itself.
    superseded_at = db.Column(db.DateTime, nullable=True)

    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)
    decided_at = db.Column(db.DateTime, nullable=True)
    outcome_recorded_at = db.Column(db.DateTime, nullable=True)

    def to_dict(self, *, include_record=True):
        payload = {
            'id': self.id,
            'user_id': self.user_id,
            'organization_id': self.organization_id,
            'thread_id': self.thread_id,
            'title': self.title,
            'decision_statement': self.decision_statement,
            'status': self.status,
            'decision_type': self.decision_type,
            'altitude': self.altitude,
            'custody': {
                'ring': 1,  # every customer-visible record is Ring 1
                'library_consent': self.library_consent,
                'library_consented_at': self.library_consented_at.isoformat() if self.library_consented_at else None,
            },
            'schema_version': self.schema_version,
            'final_decision': self.final_decision,
            'outcomes': self.outcomes if isinstance(self.outcomes, list) else [],
            'lessons_learned': self.lessons_learned if isinstance(self.lessons_learned, list) else [],
            'tags': self.tags if isinstance(self.tags, list) else [],
            'supersedes_id': self.supersedes_id,
            'superseded_at': self.superseded_at.isoformat() if self.superseded_at else None,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None,
            'decided_at': self.decided_at.isoformat() if self.decided_at else None,
            'outcome_recorded_at': self.outcome_recorded_at.isoformat() if self.outcome_recorded_at else None,
        }
        if include_record:
            payload['record'] = self.record if isinstance(self.record, dict) else {}
        return payload
