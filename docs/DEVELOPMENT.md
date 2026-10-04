# Jaspen — Local Development Guide

How to run, change, and test Jaspen locally **without touching production**.
Written for humans and AI coding agents alike. Last verified: 2026-07-05.

---

## 1. Architecture at a glance

| Layer | Technology | Local dev | Production |
|---|---|---|---|
| Frontend | React 18 (Create React App) | `npm start` → http://localhost:3000 | Vercel (jaspen.ai), built by GitHub Actions |
| Backend | Flask 3 (Python 3.12), Gunicorn in prod | `flask run` → http://localhost:8000 | DigitalOcean droplet `~/sekki-platform`, `gunicorn-sekki.service`, behind Nginx (api.jaspen.ai) |
| Database | SQLAlchemy + Flask-Migrate | SQLite file `backend/instance/jaspen_dev.db` | PostgreSQL on DigitalOcean |
| Auth | JWT in cookies (`flask-jwt-extended`), CSRF double-submit | cookies non-Secure (`JWT_COOKIE_SECURE=false`) | Secure cookies over HTTPS |
| AI | Anthropic (judgment: scoring, scenarios, agent) + Gemini (processing) | optional — set keys in `backend/.env` | keys pinned in server `.env` |
| Billing | Stripe | placeholder test key boots the app | live keys on server |
| Connectors | Jira, Salesforce, Smartsheet, Snowflake, Workfront, etc. | all optional; pages load without credentials | credentials encrypted with `CONNECTOR_ENCRYPTION_KEY` (Fernet) |

**Deploy paths (for awareness — dev never triggers these):**
- Push to `main` → GitHub Actions → Vercel prod + SSH deploy to DigitalOcean (`~/sekki-platform`) + service restart.
- Push to `develop` → staging (Vercel preview + `~/jaspen-dev`, api-dev.jaspen.ai).
- `frontend/npm run deploy` is a legacy SFTP path; avoid.

**Working locally is safe:** nothing deploys until you push to `main`/`develop`.

---

## 2. First-time setup (one command)

Prereqs: Node 24.3.0 (`frontend/.nvmrc`), npm 11.4.2 (`frontend/package.json`), and Homebrew Python 3.12. Use `nvm install` / `nvm use` from `frontend/` if you use nvm. CI uses the same Node/npm versions.

```bash
./scripts/dev_setup.sh
```

This idempotently:
1. Creates `backend/venv` (Python 3.12) and installs `requirements.txt`.
2. Creates `backend/.env` from `.env.example` with freshly generated secrets (skipped if `.env` exists).
3. Creates the local SQLite DB (`backend/instance/jaspen_dev.db`) via `db.create_all()` and seeds two users.
4. Runs `npm ci` in `frontend/` if dependencies are absent.

## 3. Running dev

```bash
# Terminal 1 — backend on :8000 (auto-reload)
./scripts/dev_backend.sh

# Terminal 2 — frontend on :3000 (hot reload)
cd frontend && npm start
```

Log in at http://localhost:3000 with:

| User | Password | Role |
|---|---|---|
| `dev@jaspen.local` | `jaspen-dev-password` | regular (5,000 credits) |
| `dev-admin@jaspen.local` | `jaspen-dev-password` | admin (`ADMIN_EMAILS`) |

`frontend/.env.development` (committed, no secrets) pins `npm start` to
`REACT_APP_API_BASE=http://localhost:8000`, so **local dev can never
accidentally hit the production API**. Production builds ignore that file and
fall back to `https://api.jaspen.ai` (`src/config/apiBase.js`).

**Ports 3000 vs 3001 — both are valid on purpose.** Manual `npm start` uses
CRA's default **:3000**. `.claude/launch.json` (used by Claude Code's preview)
pins the frontend to **:3001** so an agent-launched preview never collides with
a dev server you already have running on :3000. The backend's `CORS_ORIGINS`
in `backend/.env` allows both, so either port works identically. (JSON forbids
comments, which is why this note lives here and not in launch.json.)

## 4. Environment variables

Backend config lives in `backend/.env` (gitignored). `backend/.env.example` is
the canonical, commented reference. The dev-critical ones:

| Variable | Dev value | Why |
|---|---|---|
| `DATABASE_URL` | `sqlite:///jaspen_dev.db` | Local SQLite under `backend/instance/`; prod is Postgres |
| `JWT_SECRET_KEY`, `SECRET_KEY` | generated | App refuses to boot without JWT secret |
| `STRIPE_SECRET_KEY` | `sk_test_placeholder` | App refuses to boot without it; use a real `sk_test_...` to test billing. Never `sk_live_...` locally |
| `JWT_COOKIE_SECURE` | `false` | `true` (prod default) silently drops login cookies on http://localhost |
| `REQUIRE_EMAIL_VERIFICATION` | `false` | No mail server locally; signup/login work immediately |
| `ENABLE_FLASK_CORS` + `CORS_ORIGINS` | `true`, localhost:3000/3001 | Prod terminates CORS at Nginx; dev needs Flask CORS |
| `FRONTEND_BASE_URL` | `http://localhost:3000` | Redirect links, CORS derivation |
| `ANTHROPIC_API_KEY` / `GEMINI_API_KEY` | empty or your key | Only needed to exercise scoring/chat/agent; calls cost real API credits |

Production values live **only** in the DigitalOcean server's `.env`
(`~/sekki-platform/backend`). Never copy them into the repo.

## 5. Database & migrations

The supported SQLite bootstrap is `scripts/init_dev_db.py`, which creates
schema from current models and seeds local users. Historical migrations contain
constraint operations that cannot be replayed from zero on SQLite.

For a **new, separate** development database with verified migration tracking:

```bash
cd backend
DATABASE_URL=sqlite:///jaspen_baseline.db ./venv/bin/python scripts/init_dev_db.py --fresh-baseline
```

Persist that DATABASE_URL in your local, ignored `backend/.env` before starting
the server. The option exclusively creates a new SQLite file, checks its schema
against current model metadata, then records the single current Alembic head.
It refuses existing databases, including empty files; it never adopts an
unversioned database. If initialization fails, inspect the new file and choose
a different filename for another attempt rather than stamping a partial schema.
This is a fresh-schema baseline, not a rehearsal of PostgreSQL migration history.

For existing databases, ordinary initialization retains its previous behavior:
create missing tables and seed missing dev users, without altering existing
columns or stamping migration history. Preserve or back up existing data before
any schema change. Do not blindly stamp or replay migrations against an
unversioned database. Future SQLite migrations may need Alembic batch operations.

The migration graph must retain a single head; inspect it dynamically instead
of relying on an old revision listed in documentation:

```bash
./venv/bin/flask --app wsgi:app db heads
./venv/bin/flask --app wsgi:app db current
```

The production owner-credential migration helper is for production deployment,
not local SQLite setup. Never copy its credential into a local environment.

## 6. Tests & builds

```bash
cd backend && ./venv/bin/python -m pytest -q        # backend tests (own SQLite, own env)
cd frontend && CI=true npm test -- --watchAll=false  # frontend tests
cd frontend && npm run build                         # production build check
```

CI (GitHub Actions `ci.yml`) runs the same on Python 3.12 / Node 24.3.0 and npm 11.4.2 for every
push and PR.

## 7. Testing specific areas safely in dev

- **Scoring / strategy routes** (`/api/v1/strategy/*`): need a login cookie.
  Deterministic scoring math runs without AI keys; agent/interview/synthesis
  paths need `ANTHROPIC_API_KEY` in `backend/.env`.
- **Chat / AI agent**: same — set `ANTHROPIC_API_KEY`; calls bill your key.
- **Connectors** (`/api/v1/connectors/*`): pages and list/status routes work
  with no credentials. To test a real connector, put its sandbox credentials in
  `backend/.env` — never production tenant credentials.
- **Billing**: replace the placeholder with a real Stripe **test** key + test
  price IDs; use `stripe listen --forward-to localhost:8000/api/v1/billing/webhook`
  for webhooks.
- **Admin routes**: log in as `dev-admin@jaspen.local`.
- **Prompts**: prompt text lives in the backend (e.g. `app/routes/strategy.py`,
  `app/routes/chat.py`); changes hot-reload with the dev server and only hit
  your own API key.

## 8. Troubleshooting

| Symptom | Cause / fix |
|---|---|
| Backend exits: `STRIPE_SECRET_KEY not set` or `JWT_SECRET_KEY not set` | `backend/.env` missing — run `./scripts/dev_setup.sh` |
| Login "succeeds" but you're logged out immediately | `JWT_COOKIE_SECURE` not `false` in dev, or frontend and backend on different hosts (mixing `localhost` and `127.0.0.1`) — use `localhost` for both |
| CORS errors in browser console | Frontend origin missing from `CORS_ORIGINS`, or `ENABLE_FLASK_CORS` not `true` |
| Frontend calls `https://api.jaspen.ai` in dev | `.env.development` missing/overridden — check `frontend/.env.development.local`; restart `npm start` after env changes (CRA reads env at boot) |
| 401s with `CSRF` messages on POST | Cookie `csrf_access_token` missing; log out/in. Frontend sends `X-CSRF-TOKEN` automatically (`src/shared/auth/http.js`) |
| SQLite migration fails on ALTER constraints | Historical migrations target PostgreSQL. Use the guarded fresh-baseline initializer for a new SQLite DB; preserve existing databases |
| `no such table: ...` | Confirm the selected database and schema. Preserve it before reconciling schema or choosing a new baseline file |
| AI scoring returns 500 `ANTHROPIC_API_KEY not set` | Expected without a key; set one in `backend/.env` to exercise AI paths |
| Port already in use | Backend: `PORT=8001 ./scripts/dev_backend.sh` and update `frontend/.env.development.local`; frontend: `PORT=3001 npm start` (already in `CORS_ORIGINS`) |

## 9. Guardrails for AI coding agents (Claude Code, Codex, etc.)

1. **Never run deploys.** Do not push to `main`/`develop` unless asked; do not
   run `npm run deploy`, `vercel`, or SSH to any server. Push to `main` =
   production deploy.
2. **Production lives on the DigitalOcean server (`~/sekki-platform`), not in
   this repo.** Never copy server `.env` values into the repo; never point
   local `DATABASE_URL` at a remote database.
3. **Secrets:** `backend/.env` and `frontend/.env*.local` are gitignored — keep
   it that way. Before committing, check `git status` for env files and check
   diffs for keys (`sk_live_`, `sk_test_`, API keys).
4. **Database:** local SQLite may contain user work; preserve it. The Alembic
   history must remain single-headed — a schema change needs a proper migration,
   and after generating one run `flask db heads` to confirm it still reports a
   single head. Never restructure or renumber existing migration history as a
   side effect of another task.
5. **Testing changes:** backend → `pytest` + exercise the route locally;
   frontend → `npm start` against the local backend; both running = full-stack
   check with the seeded dev users.
6. **Scoring methodology, prompts, pricing copy, and connector UX are
   product-sensitive** — change them only when the task explicitly asks.
7. **AI keys cost money.** Leave `ANTHROPIC_API_KEY`/`GEMINI_API_KEY` empty
   unless the task requires live model calls.
8. Jaspen is a **thought partner**, not a "SaaS product" — keep that framing in
   any copy.
9. **Collaboration entitlement is Team-or-higher, and it lives in
   `backend/app/orgs.py`.** `plan_allows_collaboration()` and
   `org_collaboration_state()` are the only authority; both team blueprints
   (`/api/v1/team/*` and `/api/v1/teams/*`) delegate to them. Do not add a
   second copy of role, seat or entitlement logic to a route module — extend
   `app.orgs` instead.

   The rule is keyed on **subscription plan rank and nothing else**. Never
   infer collaboration from credits, Thinking Power balances, persistent
   credit grants, the 300K limited-time offer, the founder offer, advisory
   packages, or a generic "has an active entitlement" check. Those confer
   individual capability, not collaboration. In particular
   `effective_plan_key()` deliberately lifts a 300K holder to
   Essential-equivalent access — that lift stops below Team, and `org.plan_key`
   is synced from the raw `subscription_plan`, so neither path reaches
   collaboration. A gate written as "is entitled" instead of "is Team+" would
   wrongly admit all of them.

   Plan eligibility is checked first, billing standing second, seat
   capacity/overrides third. Billing standing is a separate gate: a past-due
   Team org keeps its entitlement but cannot send or accept invitations while
   Stripe retries. Nothing in this path removes an existing member — dunning
   handles that. Downgrading below Team ends the entitlement; there is no
   grandfathering in the logic, by design.
