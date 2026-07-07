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

Prereqs: Node 20+, Homebrew Python 3.12 (`brew install python@3.12`).

```bash
./scripts/dev_setup.sh
```

This idempotently:
1. Creates `backend/venv` (Python 3.12) and installs `requirements.txt`.
2. Creates `backend/.env` from `.env.example` with freshly generated secrets (skipped if `.env` exists).
3. Creates the local SQLite DB (`backend/instance/jaspen_dev.db`) via `db.create_all()` and seeds two users.
4. Runs `npm install` in `frontend/` if needed.

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

- Dev DB: `backend/instance/jaspen_dev.db` (SQLite, gitignored). Delete it and
  re-run `python scripts/init_dev_db.py` for a clean slate — it's disposable.
- **Known issue:** the Alembic history has multiple heads (`flask db upgrade`
  is ambiguous — see `docs/NEXT_STEPS.md` C13). Until merged, dev bootstraps
  with `db.create_all()` (creates missing tables only, never alters/drops).
- **Adding a model/column in dev:** add the model, then either delete + rebuild
  the dev DB, or write a proper Alembic migration and test it on SQLite first.
- `scripts/init_dev_db.py` refuses to run against anything that isn't SQLite.
  A localhost Postgres needs an explicit `--allow-non-sqlite` flag, and remote
  hosts are always refused. Caution: an SSH tunnel to production also looks
  like localhost — check what the port points at before using the flag.

```bash
cd backend
./venv/bin/python scripts/init_dev_db.py     # create/refresh schema + seed users
./venv/bin/flask --app wsgi:app db heads     # inspect the multi-head situation
```

## 6. Tests & builds

```bash
cd backend && ./venv/bin/python -m pytest -q        # backend tests (own SQLite, own env)
cd frontend && CI=true npm test -- --watchAll=false  # frontend tests
cd frontend && npm run build                         # production build check
```

CI (GitHub Actions `ci.yml`) runs the same on Python 3.12 / Node 20 for every
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
| `flask db upgrade` errors about multiple heads | Known tangle (NEXT_STEPS C13). Use `scripts/init_dev_db.py` for dev |
| `no such table: ...` | Model added after DB was created — delete `backend/instance/jaspen_dev.db`, re-run `init_dev_db.py` |
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
4. **Database:** dev DB is disposable SQLite. Don't "fix" the multi-head
   Alembic history as a side effect of another task — it's a deliberate,
   separate cleanup (NEXT_STEPS C13).
5. **Testing changes:** backend → `pytest` + exercise the route locally;
   frontend → `npm start` against the local backend; both running = full-stack
   check with the seeded dev users.
6. **Scoring methodology, prompts, pricing copy, and connector UX are
   product-sensitive** — change them only when the task explicitly asks.
7. **AI keys cost money.** Leave `ANTHROPIC_API_KEY`/`GEMINI_API_KEY` empty
   unless the task requires live model calls.
8. Jaspen is a **thought partner**, not a "SaaS product" — keep that framing in
   any copy.
