# Organization Ownership — Phase 1 Audit and Implementation Plan

Branch: `foundation/org-ownership-model` (cut from `main`, not pushed)
Date: 2026-08-27
Status: **Plan only. No code or schema changed.**

Companion to `docs/cross-session-memory-next-phase.md`, which specifies the
memory layer this plan makes possible. That document's items 3, 4, 7 and 9 are
adopted here rather than restated.

---

## 1. Confirmed current-state architecture

### 1.1 Session ownership

`UserSession` — `backend/app/models.py:724-761`

| Column | Definition | Line |
|---|---|---|
| `user_id` | FK `users.id`, **ondelete=CASCADE**, NOT NULL | models.py:728 |
| `session_id` | String(255), **not unique on its own** | models.py:729 |
| `organization_id` | FK `organizations.id`, ondelete=SET NULL, **nullable** | models.py:733-738 |
| `created_by_user_id` | FK `users.id`, ondelete=SET NULL, nullable | models.py:739-744 |
| `visibility` | String(32), default `'private'` | models.py:745 |
| `shared_with_user_ids` | JSON list | models.py:746 |
| `payload` | JSON blob — the entire project | models.py:747 |
| `archived_at` / `purge_after` | soft-delete pair | models.py:753-754 |

Constraints — models.py:756-759:

```python
db.UniqueConstraint('user_id', 'session_id', name='uq_user_sessions_user_id_session_id')
db.Index('ix_user_sessions_user_id_updated_at', 'user_id', 'updated_at')
db.Index('ix_user_sessions_user_archived', 'user_id', 'archived_at')
```

**Confirmed:** the effective primary key of a project is `(user_id, session_id)`.
`session_id` is *not* globally unique, and there is no index or constraint on
`(organization_id, session_id)`. Two rows may legally share a `session_id`
under different users. The fork is structurally permitted, not accidental.

### 1.2 The read/write funnel

Three functions in `backend/app/routes/sessions.py` mediate nearly everything:

- `load_user_sessions(user_id, include_archived=False)` — sessions.py:151-174.
  Returns a dict of **all** of one user's sessions, keyed by `session_id`.
- `save_user_sessions(user_id, sessions, session_ids_to_delete=None)` — sessions.py:232-271.
  Whole-dict upsert; every row is bound to `user_id`.
- `_upsert_session_row(user_id, session_id, payload, existing=None)` — sessions.py:126-149.

Call-site census for `load_user_sessions` / `save_user_sessions` — **141 outside
`sessions.py`**:

| File | Calls |
|---|---|
| `routes/ai_agent.py` | 59 |
| `routes/strategy.py` | 56 |
| `routes/export.py` | 9 |
| `routes/sessions.py` | 8 |
| `routes/starters.py`, `routes/reports.py`, `routes/activity.py`, `decision_records.py`, `decision_asset_email_service.py` | 2 each |

**The seam.** Single-session access follows one dominant idiom:

```python
sessions = load_user_sessions(user_id)
key, session = _resolve_user_session(sessions, thread_id)
```

`_resolve_user_session` — ai_agent.py:7909-7918 — is referenced 33 times. Of the
32 `load_user_sessions` calls in `ai_agent.py`, 21 are immediately followed by
it; of 29 in `strategy.py`, 18 are. **Roughly 39 of ~61 single-session accesses
share one resolver.** That resolver, not the 141 call sites, is where
authorization gets inserted.

### 1.3 Fork paths — where a collaborator creates a second row

The fork is one line. `save_user_sessions` looks up existing rows as:

```python
existing_rows = {row.session_id: row
                 for row in UserSession.query.filter_by(user_id=user_id).all()}   # sessions.py:239-240
```

then `_upsert_session_row` does:

```python
row = existing or UserSession(user_id=str(user_id), session_id=str(session_id))   # sessions.py:128
```

A collaborator never matches the owner's row, so `existing` is `None`, so a new
row is inserted under their own `user_id`. Paths that reach this:

1. `POST /api/v1/sessions` → `save_session` — sessions.py:275-292
2. `POST /api/v1/sessions/complete` — sessions.py:341-366
3. Every `ai_agent` chat turn that writes — e.g. ai_agent.py:9084-9100
4. Every `strategy.py` scoring write — 56 call sites
5. `scenarios_store.py:57` — constructs `UserSession(...)` **directly**, bypassing
   the `sessions.py` helpers entirely. Easy to miss; must follow the same rule.

Downstream effect: `_get_project_row` — team.py:135-141 — selects by
`(organization_id, session_id)` ordered by `updated_at desc`. With two forks the
Team view returns whichever was written last.

### 1.4 Organization binding is client-supplied and droppable

`_normalize_session_payload` — sessions.py:88:

```python
'organization_id': str(src.get('organization_id') or '').strip() or None,
```

The org comes from the **request body**. A `POST /api/v1/sessions` that omits it
nulls the column. The `ai_agent` path backfills server-side
(`session["organization_id"] = session.get("organization_id") or active_org_id`
— ai_agent.py:9099), the generic sessions path does not.

**Confirmed:** organization ownership today is advisory metadata, not an
enforced invariant.

### 1.5 Every user already has an organization

`ensure_default_organization_for_user` — orgs.py:403-484 — auto-creates a solo
org with the user as `owner`, `plan_key` mirrored from `user.subscription_plan`
(orgs.py:442-460, 474-478). `resolve_active_org_for_user` — orgs.py:487-491 —
runs on essentially every org-aware authenticated path.

**This is the most consequential fact in the audit.** There is no population
without an owning organization, so organization ownership does not need a Team+
branch. See §3.

### 1.6 Authorization today

- `_can_access_project(row, user_id)` — team.py:170-183 — is the **only**
  org-aware access predicate for sessions anywhere in the codebase. It is used
  at team.py:662 and inside the sharing / activity / comments handlers. It is
  never used by the workspace.
- `GET /api/v1/ai-agent/threads/<id>` — ai_agent.py:10523-10529 — resolves
  through `load_user_sessions(user_id)` and returns `404 Thread not found` for
  non-owners.
- `GET /api/v1/sessions/<id>` — sessions.py:325-338 — same.
- Role vocabulary already exists and is sufficient: `ORG_MANAGE_ROLES`
  (orgs.py:32), `ORG_EDIT_ROLES` (orgs.py:33), `can_manage_org` (orgs.py:123),
  `can_edit_projects` (orgs.py:128).

### 1.7 CASCADE audit (`users.id`, `ondelete='CASCADE'`)

**Institutional-memory bearing — must change:**

| Table | Column | Line |
|---|---|---|
| `user_sessions` | `user_id` | models.py:728 |
| `scorecards` | `user_id` | models.py:1382 |
| `decision_records` | `user_id` | models_decision_record.py:57-62 |
| `studio_workspaces` | `user_id` | models_studio.py:29-33 |
| `studio_artifacts` | `user_id` | models_studio.py:114-118 |
| `user_datasets` | `user_id` | models.py:799 |
| `saved_starters` | `user_id` | models.py:906 |
| `batch_idea_uploads` | `user_id` | models.py:837 |

`studio_artifacts.workspace_id` CASCADE (models_studio.py:107-112) is
intra-aggregate and **correct** — leave it.

**Not memory-bearing — leave alone:** `user_auth_sessions` (768),
`usage_events` (1038), `account_entitlements` (1281),
`persistent_credit_grants` (1312), `persistent_credit_transactions` (1354),
`connector_sync_logs` (958), `decision_asset_emails` (1090),
`saved_utility_estimates` (1519).

**Correct precedent already in the codebase:**
`OrgIdeaLedger.originating_user_id` uses `ondelete='SET NULL'`
(models.py:1459-1464) and its docstring (models.py:1436-1445) explicitly
describes surviving a purge. Copy that pattern; do not invent one.

**Comments and activity** live inside `UserSession.payload` as
`payload['comments']` / `payload['activity_feed']` (team.py:186-200, 744-803).
No separate table, therefore no separate cascade. They already snapshot
`author_name` (team.py:772) rather than holding an FK — accidentally the right
pattern for departure survival, and the model to copy for other artifacts.

**Blast-radius nuance.** There is **no account-deletion endpoint** in the
codebase. The CASCADEs are latent with one live exception:
`admin.py:1860` — the `clear_sessions` recovery action runs
`UserSession.query.filter_by(user_id=user.id).delete(synchronize_session=False)`,
which hard-deletes a user's sessions **including org-shared ones**. So the
departure risk is real today only through that admin action, and becomes
systemic the moment account deletion or GDPR erasure ships. Fix before, not
after.

### 1.8 `organization_id` written but never read

**Written:** `DecisionRecord` (decision_records.py:277), `Scorecard`
(scorecards.py:61, 182), `StudioWorkspace` / `StudioArtifact` (studio.py:122,
247, 285), `OrgIdeaLedger` (idea_ledger.py:226), `UserSession` (sessions.py:135,
ai_agent.py:9099).

**Read / filtered anywhere:** only `UserSession` at team.py:138, team.py:657,
dashboard.py:276 — and `SavedStarter` at starters.py:176-183.

**Never filtered:** `DecisionRecord` (routes/decision_records.py:34 and :68
filter `user_id` only), `Scorecard` (every query filters `user_id`:
scorecards.py:57, 100, 176, 190, 207, 218, 233), `StudioWorkspace`,
`StudioArtifact`, `OrgIdeaLedger` (zero org reads anywhere).

**Reference implementation to reuse** — `starters.py:176-183`, already shipping:

```python
conditions = [SavedStarter.user_id == user_id]
if active_org_id:
    conditions.append(
        (SavedStarter.organization_id == str(active_org_id))
        & (SavedStarter.is_shared.is_(True))
    )
query = SavedStarter.query.filter(or_(*conditions))
```

### 1.9 `OrgIdeaLedger`

- Model: models.py:1436-1499. Writer: `distill_session_to_ledger_row`
  (idea_ledger.py:171-258). Lifecycle: `mark_ledger_archived` (:259),
  `mark_ledger_purged` (:277).
- Called from the archive / purge / delete flows: ai_agent.py:10480, 10487,
  10489, 10893, 10916, 10986, 10991, 11031, 11128.
- Holds: org id, originating user (SET NULL), source session id, category /
  industry / company size, `jaspen_score`, `score_category`, `dimensions`,
  `risk_tags`, `recommendation_tags`, engagement booleans, lifecycle `outcome`.
- Indexed `(organization_id, jaspen_score)`, `(industry, jaspen_score)`,
  `(organization_id, created_at)` — models.py:1496-1498.
- Nothing reads it because no endpoint was ever written.

**Verdict: it belongs in the architecture, but not as organizational memory.**
It is de-identified aggregate signal with free-text rationale deliberately
stripped. It cannot answer *"what did we decide about X and why"* — Decision
Records answer that. Keep the split: **ledger = statistics, records = memory.**
Activating it is a small isolated win and does not belong on the critical path.

### 1.10 `DecisionRecord` state

- `DECISION_RECORD_SCHEMA_VERSION = 1` — models_decision_record.py:33; stamped
  on the row (:88) and inside the payload (decision_records.py:218).
- **Already has:** custody rings and `library_consent` (:80-86),
  `final_decision`, `outcomes` list, `lessons_learned` list, `tags` (:93-99),
  a status vocabulary including `outcome_recorded` (:40-42), `decided_at`,
  `outcome_recorded_at`. The human-owned fields are deliberately kept outside
  `record` so re-derivation cannot clobber them (:90-92).
- **Does not have:** `supersedes_id`, `superseded_by_id`, effective dates,
  current/superseded status — and `organization_id` is a bare `db.String(36)`
  with **no ForeignKey at all** (:63).
- **No frontend consumer exists.** A grep of `frontend/src` for the
  decision-records API returns nothing; the only match is an unrelated marketing
  component named `DecisionRecord` at `FounderCampaignPage.jsx:207`.
  `create_or_refresh_record` is called from exactly one place:
  `routes/decision_records.py:50`.

**Consequence: Decision Records are a backend-only, unexercised system.** Good
for migration risk — the schema can be extended freely. Bad for the memory
thesis — nothing in the product ever produces a record, so organizational
memory retrieval would query an empty table. See §11.

### 1.11 Concurrency

- `UserSession.payload` is one JSON blob replaced wholesale: `row.payload =
  normalized` — sessions.py:145.
- No version column, no ETag, no row lock anywhere.
- **`updated_at` cannot serve as a concurrency token.** sessions.py:147-148:
  `updated_dt = _parse_dt(normalized.get('timestamp')) or datetime.utcnow()` —
  it is set from the *client-supplied* `timestamp` when parseable. A real
  server-owned integer `revision` column is required.

### 1.12 Shared Projects defect — traced

1. Card renders — JaspenChat.jsx:13868-13886.
2. `onClick` → `navigate('/new?session_id=…')` — JaspenChat.jsx:13877.
3. Access label `'Can edit'` — JaspenChat.jsx:13884 — driven by
   `effectiveIsViewer`, a **role** check, not an access check.
4. `loadSessionById` → `GET /api/v1/ai-agent/threads/<id>` —
   JaspenChat.jsx:6140-6144; `if (!resp.ok) return null;` at :6160, **no
   fallback**.
5. Endpoint resolves through `load_user_sessions(user_id)` → `404 Thread not
   found` — ai_agent.py:10523-10529.

### 1.13 Migration and test infrastructure

- Alembic: 48 revisions, **single head `b7e2d91a4c03`**, linear. Low risk.
  (Any earlier note about multi-head is stale.)
- **Tests build the schema with `_db.create_all()`** — `conftest.py:89`.
  Migrations are therefore *not exercised by the suite*. Schema changes can pass
  tests while the Alembic path is broken. Mitigation in §10.
- Existing fixtures: `app`, `client`, `db`, `test_user`, `admin_user`,
  `auth_headers`, `admin_auth_headers` — conftest.py:40-219. Strong existing
  idiom in `test_team_collaboration_gating.py`.

---

## 2. Root causes

| # | Root cause |
|---|---|
| RC1 | **Identity.** `session_id` is not a global identifier; the real key is `(user_id, session_id)`, so "the same project" is not expressible in the schema. |
| RC2 | **Resolution.** Every accessor derives its working set from `load_user_sessions(user_id)`. Authorization is *implied by the query* rather than evaluated, so there is no place to insert a permission check — because nothing ever asks a permission question. |
| RC3 | **Provenance.** `organization_id` is client-supplied descriptive metadata (sessions.py:88), not a server-enforced ownership invariant. |
| RC4 | **Retention.** Durable artifacts are children of `users`, not of `organizations`, so delete semantics follow the employee. |
| RC5 | **Memory.** The only cross-session memory is a per-user mutable blob (ai_agent.py:1691-1782), and the durable artifacts that *should* be memory are never created by the product. |

---

## 3. Proposed target ownership model

### Is a separate organization-owned workspace entity necessary? **No.**

Extend `user_sessions`. Reasons:

1. Every user already has an organization (orgs.py:403-484), so there is no
   population that would need a fallback path.
2. `organization_id`, `created_by_user_id`, `visibility` and
   `shared_with_user_ids` **already exist on the row** — the model was designed
   for this and left half-wired.
3. A parallel entity means dual-writing 141 call sites — precisely the "second
   collaboration architecture" the guardrails forbid.

### The model

| Concern | Owner | Mechanism |
|---|---|---|
| **Ownership** | Organization | `user_sessions.organization_id`, server-derived, authoritative |
| **Attribution** | User | `created_by_user_id` (immutable) + new `last_edited_by_user_id` + per-turn author stamps |
| **Permission** | Role × visibility | `_can_access_project` predicate × `can_edit_projects` |
| **Retention** | Organization | FKs to `users` become `SET NULL`; org link persists |
| **Retrieval** | Authorize → then rank | new `app/session_access.py` chokepoint |

`user_id` is **demoted** from "owner" to "the row's home user". It is not
dropped in Phase 1 — it backs the unique constraint and 141 call sites. The
canonical key becomes `(organization_id, session_id)`.

### Why this needs no Team+ branch

Because `plan_allows_collaboration` (orgs.py:157-160) already gates *invitation*,
a sub-Team org can never acquire a second member. The authorization predicate
therefore collapses to "it's mine" for solo orgs **without any plan check in the
authorization path**. Backward compatibility for individual users falls out for
free rather than being engineered.

---

## 4. Schema changes required

### Phase 1 migration — additive only

1. Backfill `user_sessions.organization_id` from
   `created_by_user_id` → `user_id` → `users.active_organization_id`.
   Leave the column **nullable** for one release; enforce server-side. Add
   `NOT NULL` in a follow-up only after a verification query returns zero.
2. `user_sessions.revision` — `INTEGER NOT NULL DEFAULT 0`. Server-owned
   optimistic concurrency token (`updated_at` cannot be used — §1.11).
3. `user_sessions.last_edited_by_user_id` — FK `users.id`, `ON DELETE SET NULL`,
   nullable.
4. Index `ix_user_sessions_org_session` on `(organization_id, session_id)`.
5. `decision_records.organization_id` — add the missing FK to `organizations.id`,
   `ON DELETE SET NULL` (currently a bare String — models_decision_record.py:63).

**Unique constraint on `(organization_id, session_id)` is deferred** until the
de-fork scan in §8/R1 completes. Do not add it in the same migration.

### Phase 4 migration — retention

6. `ondelete` CASCADE → SET NULL on the eight tables in §1.7, which requires
   those `user_id` columns to become nullable.
7. Attribution snapshot columns on the durable artifacts (`authored_by_name`,
   `authored_by_email`, or one small `attribution` JSON), copying the
   `author_name` pattern at team.py:772, so attribution survives the FK nulling.

### Phase 7 migration — supersession

8. `decision_records`: `supersedes_id` (self FK), `superseded_by_id` (self FK),
   `effective_from`, `effective_to`, `is_current` Boolean default `True`,
   indexed.
9. Bump `DECISION_RECORD_SCHEMA_VERSION` to `2` **here and not before** — adding
   promoted columns alone does not change the payload shape, and readers are
   already required to tolerate older versions (models_decision_record.py:31-32).

---

## 5. Read/write paths requiring modification

Change these, not the 141 call sites:

| # | Target | Change |
|---|---|---|
| 1 | `load_user_sessions` — sessions.py:151 | Add optional `scope`; **default stays personal** so history, exports, dashboards and the memory suffix are unaffected. |
| 2 | **new** `app/session_access.py` | `resolve_session_for_actor(user, session_id, *, require_write=False)` → `(row, membership, role)`. The single authorization chokepoint. |
| 3 | `_resolve_user_session` — ai_agent.py:7909 | Route through #2. Highest leverage change in the plan — ~39 of ~61 single-session accesses. |
| 4 | `save_user_sessions` — sessions.py:239-240 | Look up `existing` by `(organization_id, session_id)`. **This is the line that stops the fork.** |
| 5 | `_upsert_session_row` — sessions.py:126-149 | Stop binding new rows to the caller; carry `created_by_user_id`, stamp `last_edited_by_user_id`, bump `revision`. |
| 6 | `_normalize_session_payload` — sessions.py:88 | Stop trusting client `organization_id`; derive from `resolve_active_org_for_user`. |
| 7 | `get_thread` — ai_agent.py:10523 | Route through #2. Closes the Shared Projects defect. |
| 8 | `get_session` — sessions.py:325 | Route through #2. |
| 9 | `scenarios_store.py:26, 47, 57` | Direct `UserSession` construction — must follow the same ownership rule or it reintroduces forks via the scenario path. |
| 10 | `archive_user_session` / `hard_delete_user_session` — sessions.py:175-221 | See §8/R6 — per-user hide vs org-wide delete. |
| 11 | `admin.py:1860` | `clear_sessions` must not hard-delete org-shared rows. |

---

## 6. Authorization changes

Move `_can_access_project` (team.py:170-183) **verbatim** into
`app/session_access.py` so `team.py` and the workspace share one predicate. Then:

| Operation | Rule |
|---|---|
| **read** | active member of the owning org **AND** the visibility predicate (`private` → creator only; `team` → any active member; `specific` → listed ids) |
| **write** | read **AND** `can_edit_projects(role)` — orgs.py:128 (owner / admin / creator / collaborator). Viewer is read-only. |
| **change sharing** | `can_manage_org(role)` **OR** creator-of-record — already implemented at team.py:678-684; reuse it. |
| **plan gate** | **None in this layer.** See §3. |

Authorization is evaluated **before** the row is loaded into any context
assembly — satisfying item 4 of `cross-session-memory-next-phase.md`.

---

## 7. Employee-departure / retention changes

Treat as three distinct verbs:

| Verb | Today | Target |
|---|---|---|
| **Remove member** | team.py:417-450 — deletes only the `OrganizationMember` row. Already correct. | Unchanged. Add an activity entry. |
| **Delete user** | Does not exist. | When built: `user_id` → NULL on the eight tables; `organization_id` retained; `authored_by_name` snapshot preserved. |
| **Delete my history** | sessions.py:175-221 — per-user archive + purge. | Must not archive the org's canonical row. See §8/R6. |

Rules to adopt:

- Organization-owned artifacts **never** follow the user out of the building.
- Private artifacts in a Team org on departure: transfer to the org owner or
  archive with the existing `archived_at` / `purge_after` grace window
  (models.py:753-754). **Never hard-delete.**
- Fix `admin.py:1860` so `clear_sessions` soft-archives, or excludes rows with
  `visibility != 'private'`.
- `OrgIdeaLedger` already models "the de-identified signal survives the purge"
  (models.py:1436-1445). Do not rebuild it — extend the same idea.

---

## 8. Migration / backward-compatibility risks

| # | Risk | Mitigation |
|---|---|---|
| **R1** | **Pre-existing forks.** Duplicate `(organization_id, session_id)` pairs may already exist wherever a collaborator saved. A unique constraint would fail to create. | Run a de-fork scan **before** the migration. Resolution (keep latest, archive the other, log both) is a **human decision** — do not automate silently. Defer the unique constraint to a later migration. |
| **R2** | **NULL `organization_id` rows** from `POST /api/v1/sessions` without the field. | Backfill via `created_by_user_id` → `user_id` → `active_organization_id`. Rows whose user is gone go to a quarantine bucket, not a guess. |
| **R3** | `user_sessions.user_id` is NOT NULL **and** part of the unique constraint, blocking the CASCADE→SET NULL flip. | Ordering dependency: Phase 4 cannot precede Phase 1. |
| **R4** | **`load_user_sessions` semantics.** If it silently returns org-visible sessions, history lists, exports, dashboard counts and the memory suffix (ai_agent.py:1785-1860) all change behavior at once. | Default stays personal; opt in per call site. |
| **R5** | **`updated_at` is client-settable** (sessions.py:147) so it cannot be a concurrency token — and it also steers `_get_project_row`'s ordering (team.py:139). | Add the server-owned `revision` column; order by `revision` or `created_at` where correctness matters. |
| **R6** | **`archived_at` / `purge_after` are per-user today.** Under org ownership, "delete from my history" would archive the organization's row. | Needs a per-member hidden-list or a scope flag. This is a real design decision hiding in a small function — resolve it during Phase 1, not during Phase 4. |
| **R7** | `scenarios_store.py` writes `UserSession` rows outside the `sessions.py` helpers. | Include in Phase 1 scope explicitly. |
| **R8** | **Tests use `create_all()`** (conftest.py:89), so migrations are never exercised. | Add a migration smoke test that runs `alembic upgrade head` against a scratch DB, before any schema work merges. |
| **R9** | Alembic is single-head and linear (`b7e2d91a4c03`). | Low risk. Keep it linear — one revision per phase. |

---

## 9. Dependency-ordered implementation phases

### Challenges to the proposed A–L sequence

| Proposed | Challenge |
|---|---|
| **B after A** | **Merge B into A.** The moment ownership moves to the org, `user_id` stops meaning "author". Shipping A without authoritative `created_by_user_id` and a `last_edited_by` stamp leaves a window where the product cannot say who made anything. |
| **F after E** | **Merge F into E, or ship F first.** E is exactly the change that lets two people write the same row. E without F converts a silent fork into a silent overwrite — strictly worse, because a fork at least preserves both copies. |
| **I after G** | **A new phase is required before G.** Decision Records are never created by the product (§1.10); G would query an empty table. Hook `create_or_refresh_record` into the completed-score flow first — alongside where `extract_and_update_user_memory` (strategy.py:3514-3537) and `distill_session_to_ledger_row` (ai_agent.py:10487, 10986) already fire. Small change; precondition for the entire memory thesis. |
| **K at position 11** | **Start K in parallel at Phase 1.** The manifest's job is to pin identity and ownership semantics; writing it *after* those change means rewriting it. It is a document, not code, and `DECISION_RECORD_SCHEMA_VERSION` is still 1. |
| **J in the arc** | **Drop J from the critical path.** It needs no ownership work and answers a different question (benchmarking, not memory). Standalone win, any time. |
| **D position** | Agreed as placed — and it cannot move earlier (R3). |
| **L last** | Agreed, and possibly out of scope entirely. With `revision` plus a "last edited by X at T" stamp, the felt experience is largely there for a tool whose primary surface is append-only conversation. |

### Revised sequence

| Phase | Work | Depends on |
|---|---|---|
| **0** | **Guard the Shared Projects card.** Stop labeling non-owners "Can edit"; stop navigating into a 404. One file, user-visible today, no schema. | — |
| **1** | **Canonical ownership + attribution** (A+B). De-fork scan → migration (backfill org, `revision`, `last_edited_by_user_id`, org index, DecisionRecord FK) → server-derive org → fork-stopping lookup change → `scenarios_store` → resolve R6. | 0 |
| **2** | **Authorization chokepoint** (C). `app/session_access.py`; route `get_thread`, `get_session`, `_resolve_user_session` through it. **The Shared Projects defect closes here for real.** | 1 |
| **3** | **Optimistic concurrency** (F). `revision` check on write; `409` with a merge-safe response body. Same release as Phase 2 or immediately after — never later. | 1, 2 |
| **4** | **Retention** (D). CASCADE→SET NULL ×8, attribution snapshots, fix `admin.py:1860`, define remove-member vs delete-user. | 1 |
| **5** | **Produce Decision Records** (new). Fire `create_or_refresh_record` from the completed-score path. | 1 |
| **6** | **Permission-aware org retrieval** (G). Apply the `starters.py:176-183` shape to `DecisionRecord` and `Scorecard`. Authorize, then rank. Lexical/metadata only — no vector store. | 2, 5 |
| **7** | **Supersession + outcomes/lessons** (H+I). Bump schema to 2. | 6 |
| **8** | **Export manifest contract** (K). *Runs in parallel from Phase 1.* Document only. | — |
| **9** | **Activate `OrgIdeaLedger`** (J). Standalone. | — |
| **10** | **Presence** (L). Only on measured need. | 3 |

**Smallest foundational phase to implement first: Phase 1**, with Phase 0 shipped
alongside it as an independent guard.

---

## 10. Tests required per phase

**Prerequisite (before any schema work merges):** a migration smoke test that
runs `alembic upgrade head` against a scratch database — the suite currently
builds via `create_all()` (conftest.py:89) and would not catch a broken revision.

Use the existing fixtures (`client`, `app`, `db`, `auth_headers` —
conftest.py:134-219) and the idiom in `test_team_collaboration_gating.py`.

| Phase | Test file | Cases |
|---|---|---|
| **0** | `test_shared_projects_guard.py` | Non-owner does not see an "editable" affordance for a project they cannot open; owner is unaffected. |
| **1** | `test_session_org_ownership.py` | Org id is server-derived and survives a save that omits it; a collaborator save updates the owner's row instead of inserting a second one; `created_by_user_id` never changes on edit; `last_edited_by_user_id` updates; `revision` increments monotonically; a solo (non-Team) user's flow is byte-identical to today; `scenarios_store` writes obey the same rule; the de-fork scan finds a seeded duplicate. |
| **2** | `test_session_authorization.py` | Matrix over {owner, admin, creator, collaborator, viewer, non-member} × {private, team, specific} × {read, write, share}; `GET /ai-agent/threads/<id>` returns 200 for an authorized collaborator and 404 for a non-member; viewer write returns 403; **authorization is evaluated before assembly** (no context built on a denied read). |
| **3** | `test_session_concurrency.py` | Stale `revision` write returns 409 and does not mutate; concurrent appends both land; a client-supplied `timestamp` cannot bypass the check (R5). |
| **4** | `test_departure_retention.py` | Removing a member leaves sessions, scorecards and decision records intact and still org-readable; nulling a user preserves `authored_by_name`; `admin.py` `clear_sessions` does not destroy org-shared rows; private-artifact policy behaves as decided. |
| **5** | `test_decision_record_creation.py` | A completed score produces exactly one record per thread; a re-score refreshes derived fields and never clobbers `final_decision`, `outcomes` or `lessons_learned` (models_decision_record.py:90-92). |
| **6** | `test_org_memory_retrieval.py` | Retrieval returns team-visible artifacts from other members and excludes private ones; a viewer never receives a fact sourced from a record they cannot read; a solo org sees exactly its own; result count is bounded (no full-history load). |
| **7** | `test_supersession.py` | A superseding record marks its predecessor non-current; historical records remain retrievable; retrieval prefers current; nothing is overwritten. |
| **8** | `test_export_manifest.py` | Manifest validates against the pinned contract; `schema_version` is present and stable. |
| **9** | `test_org_idea_ledger_reads.py` | Benchmarking query is org-scoped; purged rows are excluded; no cross-org leakage. |

---

## 11. What the codebase proves is wrong or unnecessary in the proposed approach

1. **"For Team+ organizations…" is the wrong scoping — and scoping it that way
   would add risk.** Every user already owns a solo organization
   (orgs.py:403-484). Making org ownership universal is *simpler* than making it
   conditional: one code path, no plan branch in the authorization layer, and
   backward compatibility for individuals falls out for free (§3). A Team+-only
   ownership path would mean two ownership models — the thing the guardrails
   forbid.

2. **A separate organization-owned workspace entity is unnecessary.** The
   columns already exist on `user_sessions` and were clearly designed for this.
   Extending is strictly less work and less risk than a parallel entity.

3. **"Fix authorization/retrieval" (C) is not 141 edits.** ~39 of ~61
   single-session accesses funnel through one resolver (`_resolve_user_session`,
   ai_agent.py:7909). The work is one chokepoint plus the direct outliers, not
   a sweep.

4. **The plan is missing a prerequisite: Decision Records are never created.**
   `create_or_refresh_record` has exactly one caller
   (routes/decision_records.py:50) and **no frontend consumer at all**. Building
   organizational memory retrieval (G) on Decision Records without first making
   them get produced would ship a query against an empty table. This is the
   largest genuine omission in the proposed sequence.

5. **`OrgIdeaLedger` does not belong in the memory architecture as memory.** It
   is de-identified aggregate signal with rationale deliberately stripped
   (models.py:1436-1445). It is a *benchmarking* asset. Treating it as
   organizational memory would put statistics where narrative belongs. Keep it,
   read it, but keep it out of the memory path (§1.9).

6. **`updated_at` cannot be the optimistic-concurrency token** — it is
   client-settable (sessions.py:147). Anyone reaching for "just compare
   timestamps" would build a check that a client can trivially defeat. A
   server-owned `revision` integer is required, and it is sufficient for the
   first implementation. **Your instinct here is correct; the field you would
   naturally reach for is not.**

7. **The Shared Projects defect does dissolve under the ownership fix** (Phase
   2), so it needs no separate architecture — but it is user-visible *today*, so
   it warrants an independent Phase 0 guard rather than waiting.

8. **The CASCADE risk is smaller than it looks today and larger than it looks
   tomorrow.** No account-deletion endpoint exists, so nothing is currently
   destroying institutional memory — with one live exception,
   `admin.py:1860`. The correct framing is that this is a landmine to defuse
   *before* account deletion or GDPR erasure ships, not an active fire.

9. **One item is missing from the risk list entirely: `archived_at` /
   `purge_after` are per-user** (sessions.py:175-221). Under org ownership,
   "delete from my history" would archive the organization's canonical row. This
   must be resolved in Phase 1, not discovered in Phase 4 (R6).
