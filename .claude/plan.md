# Jaspen Platform — Execution Plan

> **Excludes:** Side drawer tab color/UI, MFA re-enable, SSL configuration (handled separately)

---

## PHASE 1: Critical Fixes (Days 1–2)

### 1.1 — Raise AI Agent Max Output Tokens
**Why:** Current `AI_AGENT_MAX_OUTPUT_TOKENS=260` truncates Claude mid-sentence. Strategic advice requires nuance.
**Files:**
- `backend/app/__init__.py` — change default from `260` to `1500`
**Steps:**
1. In `create_app()`, change the `AI_AGENT_MAX_OUTPUT_TOKENS` default from `260` to `1500`
2. Verify the env var override still works for production tuning
3. Test a full intake conversation and confirm responses no longer truncate

### 1.2 — Fix XSS Vector (dangerouslySetInnerHTML)
**Why:** Line ~6458 in JaspenWorkspace.jsx transforms AI/help content to raw HTML via regex. Even though current source is backend-controlled, any future change (user-generated content, injection in help responses) creates a direct XSS path.
**Files:**
- `frontend/package.json` — add `dompurify` dependency
- `frontend/src/jaspenInterface/Workspace/JaspenWorkspace.jsx` — sanitize before render
**Steps:**
1. `npm install dompurify` in frontend
2. Import DOMPurify at top of JaspenWorkspace.jsx
3. Wrap the `.replace()` chain result in `DOMPurify.sanitize(...)` before passing to `dangerouslySetInnerHTML`
4. Alternatively, replace the entire block with `react-markdown` + `remark-gfm` (already in deps) for proper markdown rendering without raw HTML

### 1.3 — Remove localStorage Token Fallback
**Why:** localStorage tokens are accessible to any XSS. Cookie-primary auth is correct; the localStorage path should be removed for production.
**Files:**
- `frontend/src/jaspenInterface/Workspace/JaspenClient.jsx` — remove `localStorage.getItem('access_token')` / `localStorage.getItem('token')` fallbacks from `getToken()` or equivalent
- `frontend/src/shared/auth/AuthContext.jsx` — ensure login/logout only uses httpOnly cookies
**Steps:**
1. Audit every `localStorage.getItem('access_token')` and `localStorage.getItem('token')` reference
2. Remove token reads from localStorage in the API client's header construction
3. Ensure the backend sets httpOnly cookies on login and the frontend relies solely on `credentials: 'include'`
4. Keep `localStorage` for non-sensitive prefs (display name, model type, notifications) — those are fine
5. Test full login → workspace → API call → logout flow with cookies only

### 1.4 — Add Content Security Policy Header
**Why:** `X-XSS-Protection` is deprecated. Modern browsers rely on CSP.
**Files:**
- `frontend/nginx.conf`
**Steps:**
1. Add to the `server` block:
   ```
   add_header Content-Security-Policy "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data: https:; connect-src 'self' https://api.jaspen.ai https://*.stripe.com; frame-src https://*.stripe.com; font-src 'self' data:;" always;
   ```
2. Adjust `connect-src` to match your actual API domain(s)
3. Test that Stripe checkout iframes still work
4. Test that no console CSP violations appear during normal usage

### 1.5 — Add Sentry Error Tracking
**Why:** No observability = flying blind in production. When GridPoint hits an error, you won't know.
**Files:**
- `frontend/package.json` — add `@sentry/react`
- `frontend/src/index.js` — initialize Sentry
- `backend/requirements.txt` — add `sentry-sdk[flask]`
- `backend/app/__init__.py` — initialize Sentry in `create_app()`
**Steps:**
1. Create Sentry account + project (React frontend, Flask backend)
2. Frontend: `npm install @sentry/react` → init in `index.js` with DSN, environment, release tag
3. Backend: `pip install sentry-sdk[flask]` → init in `create_app()` with DSN + Flask integration
4. Add `SENTRY_DSN` env var to both frontend build and backend config
5. Verify errors surface in Sentry dashboard with a deliberate test error

---

## PHASE 2: Batch Idea Upload → Scored Projects (Days 3–6)

This is the new feature: users upload a list of ideas (CSV/Excel), the agent ranks/scores them, asks clarifying questions per idea, and each scored idea becomes its own project/thread.

### 2.1 — Backend: New Batch Upload Endpoint
**Files:**
- `backend/app/routes/ai_agent.py` — new route `/api/v1/ai-agent/batch-ideas/upload`
**Steps:**
1. Create `POST /api/v1/ai-agent/batch-ideas/upload` endpoint:
   - Accept multipart/form-data with CSV/Excel file
   - Parse with pandas (reuse existing `_dataset_from_upload()` pattern)
   - Validate: file has at least a `name` or `title` or `idea` column (flexible header matching)
   - Extract each row as an idea with all available columns as metadata
   - Return a `batch_id` + parsed idea list with IDs for frontend confirmation:
     ```json
     {
       "batch_id": "uuid",
       "ideas": [
         {"idea_id": "uuid", "title": "row title", "metadata": {col: val, ...}},
         ...
       ],
       "columns_detected": ["title", "budget", "timeline", ...],
       "total_count": 15
     }
     ```
2. Store batch state in a new `BatchIdeaUpload` model or in-memory (see 2.2)

### 2.2 — Backend: Batch Idea Model
**Files:**
- `backend/app/models.py` — new `BatchIdeaUpload` model
- `backend/migrations/versions/` — new migration
**Steps:**
1. Add model:
   ```python
   class BatchIdeaUpload(db.Model):
       __tablename__ = 'batch_idea_uploads'
       id = db.Column(db.String(36), primary_key=True)
       user_id = db.Column(db.String(36), db.ForeignKey('users.id'))
       organization_id = db.Column(db.String(36), nullable=True)
       filename = db.Column(db.String(255))
       ideas_json = db.Column(db.Text)  # JSON array of parsed ideas
       status = db.Column(db.String(32), default='uploaded')  # uploaded | ranking | clarifying | scoring | completed
       ranking_result_json = db.Column(db.Text, nullable=True)  # AI ranking output
       created_at = db.Column(db.DateTime, default=datetime.utcnow)
       updated_at = db.Column(db.DateTime, onupdate=datetime.utcnow)
   ```
2. Generate Alembic migration: `flask db migrate -m "add batch_idea_uploads table"`
3. Apply: `flask db upgrade`

### 2.3 — Backend: AI Ranking Endpoint
**Files:**
- `backend/app/routes/ai_agent.py` — new route `/api/v1/ai-agent/batch-ideas/<batch_id>/rank`
**Steps:**
1. Create `POST /api/v1/ai-agent/batch-ideas/<batch_id>/rank` endpoint:
   - Load batch by ID
   - Build prompt with all ideas + their metadata
   - Ask Claude to rank ideas by strategic potential using available info
   - Claude identifies which ideas have enough info to score immediately vs. which need clarifying questions
   - Return:
     ```json
     {
       "batch_id": "uuid",
       "ranked_ideas": [
         {
           "idea_id": "uuid",
           "title": "...",
           "rank": 1,
           "preliminary_score": 72,
           "scoreable": true,
           "clarifying_questions": [],
           "rationale": "Strong market fit with clear financials provided"
         },
         {
           "idea_id": "uuid",
           "title": "...",
           "rank": 2,
           "preliminary_score": null,
           "scoreable": false,
           "clarifying_questions": [
             "What is the estimated budget for this initiative?",
             "What is the target timeline for delivery?"
           ],
           "rationale": "Promising but missing financial and timeline data"
         }
       ]
     }
     ```
2. Charge credits proportional to total token usage (same model as existing credit system)
3. Update batch status to `ranking`

### 2.4 — Backend: Clarify & Score Individual Idea
**Files:**
- `backend/app/routes/ai_agent.py` — new routes:
  - `POST /api/v1/ai-agent/batch-ideas/<batch_id>/ideas/<idea_id>/clarify`
  - `POST /api/v1/ai-agent/batch-ideas/<batch_id>/ideas/<idea_id>/promote`
**Steps:**
1. `/clarify` endpoint:
   - Accept user answers to clarifying questions as JSON body
   - Merge answers into the idea's metadata
   - Re-evaluate if idea is now scoreable
   - Return updated idea with new `scoreable` status
2. `/promote` endpoint:
   - Takes a scoreable idea and creates a full Jaspen thread/session for it
   - Call `_new_session()` with idea title as name, metadata as intake context
   - Pre-populate chat history with a synthetic intake summary built from the idea metadata
   - Auto-trigger scorecard generation via existing `_generate_jaspen_scorecard()` flow
   - Return the new `thread_id` so the frontend can navigate to it
   - Update idea record with `thread_id` linkage
3. Add `thread_id` field to the ideas JSON structure to track promotion

### 2.5 — Backend: Bulk Promote (Score All Scoreable)
**Files:**
- `backend/app/routes/ai_agent.py` — new route `POST /api/v1/ai-agent/batch-ideas/<batch_id>/promote-all`
**Steps:**
1. Iterate through all ideas where `scoreable == true` and `thread_id == null`
2. For each, run the promote flow from 2.4
3. Return array of created thread_ids mapped to idea_ids
4. Rate-limit: max 10 promotions per call to avoid timeout; return `has_more: true` if batch is larger
5. Frontend can call repeatedly until `has_more: false`

### 2.6 — Frontend: Batch Upload UI
**Files:**
- `frontend/src/jaspenInterface/Workspace/JaspenWorkspace.jsx` — add batch upload trigger
- New file: `frontend/src/jaspenInterface/Workspace/components/BatchIdeaManager.jsx`
- `frontend/src/jaspenInterface/Workspace/JaspenClient.jsx` — add batch API methods
**Steps:**
1. Add to JaspenClient:
   ```javascript
   uploadBatchIdeas(file) { /* POST /batch-ideas/upload with FormData */ }
   rankBatchIdeas(batchId) { /* POST /batch-ideas/{id}/rank */ }
   clarifyIdea(batchId, ideaId, answers) { /* POST /batch-ideas/{id}/ideas/{ideaId}/clarify */ }
   promoteIdea(batchId, ideaId) { /* POST /batch-ideas/{id}/ideas/{ideaId}/promote */ }
   promoteAllIdeas(batchId) { /* POST /batch-ideas/{id}/promote-all */ }
   ```
2. Create `BatchIdeaManager.jsx` component:
   - **Upload state**: File drop zone + upload button → shows parsed ideas table
   - **Ranking state**: "Rank Ideas" button → shows ranked list with scores, rationale
   - **Clarification state**: Inline form for answering questions per idea (expandable rows)
   - **Promotion state**: "Score This Idea" per-row button + "Score All Ready" bulk button
   - **Completion state**: Links to each created project/thread
3. Wire into workspace:
   - Add a "Batch Ideas" option to the new session/project creation flow
   - Or add as a sidebar action alongside "New Conversation"
   - Each promoted idea appears in the session history sidebar as its own thread

### 2.7 — Agent Awareness: Batch Context in System Prompt
**Files:**
- `backend/app/routes/ai_agent.py` — modify system prompt builder
**Steps:**
1. When a thread was created from a batch promotion, include in the system prompt:
   ```
   This project was promoted from a batch idea upload.
   Original idea: "{title}"
   Provided metadata: {key: value pairs}
   The user has already provided baseline information.
   Focus on deepening the analysis rather than re-asking for information already provided.
   ```
2. This prevents the agent from re-asking questions the user already answered in the batch flow

---

## PHASE 3: Streaming Responses (Days 7–8)

### 3.1 — Backend: Streaming for AI Agent Conversation
**Files:**
- `backend/app/routes/ai_agent.py` — modify `/conversation/continue` to support streaming
**Steps:**
1. Add `?stream=true` query parameter support to `/conversation/continue`
2. When streaming:
   - Use `anthropic.messages.stream()` instead of `anthropic.messages.create()`
   - Yield SSE events: `data: {"type": "delta", "text": "..."}` for each text chunk
   - Yield tool-use events: `data: {"type": "tool_use", "tool": "...", "input": {...}}` when agent invokes tools
   - Yield tool results: `data: {"type": "tool_result", "tool": "...", "result": {...}}`
   - Yield final: `data: {"type": "done", "usage": {...}, "readiness": {...}}`
   - Return `Content-Type: text/event-stream`
3. Tool execution still happens server-side between stream segments
4. Credit charging happens on `done` event

### 3.2 — Frontend: Stream Rendering
**Files:**
- `frontend/src/jaspenInterface/Workspace/JaspenClient.jsx` — add `streamConversation()` method
- `frontend/src/jaspenInterface/Workspace/JaspenWorkspace.jsx` — wire streaming into chat
**Steps:**
1. Add `streamConversation({ threadId, message, onDelta, onToolUse, onDone })` to JaspenClient
2. Use `EventSource` or `fetch` with `ReadableStream` to consume SSE
3. In workspace, when user sends message:
   - Immediately add user message to `messages` state
   - Add placeholder assistant message with `streaming: true`
   - Append delta text to placeholder as chunks arrive
   - On `done`, finalize message and update readiness/credits
4. Show typing indicator during tool execution pauses

---

## PHASE 4: Conversation Context Summarization (Day 9)

### 4.1 — Backend: Context Window Management
**Files:**
- `backend/app/routes/ai_agent.py` — add summarization to `_build_messages()`
**Steps:**
1. When conversation history exceeds the plan's context budget (e.g., 24 turns for Essential):
   - Take the oldest N turns that exceed the budget
   - Call Claude with a summarization prompt: "Summarize the key facts, decisions, and data points from this conversation segment"
   - Store the summary as a synthetic system message at the start of the context window
   - Keep only the most recent turns within budget + the summary
2. Cache summaries in the session payload so you don't re-summarize on every request:
   ```json
   {
     "context_summaries": [
       {"covers_turns": [0, 15], "summary": "User described a SaaS platform..."}
     ]
   }
   ```
3. This ensures the agent never "forgets" early conversation even in long sessions

---

## PHASE 5: Export Functionality (Days 10–11)

### 5.1 — Backend: PDF/PPTX Export Endpoints
**Files:**
- New file: `backend/app/routes/export.py`
- `backend/app/__init__.py` — register blueprint
- `backend/requirements.txt` — add `python-pptx`
**Steps:**
1. Create `export_bp` Flask blueprint
2. `GET /api/v1/export/threads/<thread_id>/scorecard/pdf`:
   - Use `reportlab` or `weasyprint` to generate a styled PDF
   - Include: Jaspen score, component scores, financial impact, risks, recommendations
   - Header with org logo (if available) + timestamp
3. `GET /api/v1/export/threads/<thread_id>/scorecard/pptx`:
   - Use `python-pptx` to generate a slide deck
   - Slide 1: Title + Jaspen Score
   - Slide 2: Component Scores (4 quadrant visual)
   - Slide 3: Financial Impact
   - Slide 4: Key Risks
   - Slide 5: Recommendations + Next Steps
4. `GET /api/v1/export/threads/<thread_id>/wbs/csv`:
   - Export WBS tasks as CSV for import into external PM tools
5. All exports gated by plan (free: no export, essential+: PDF, team+: PPTX)

### 5.2 — Frontend: Export Buttons
**Files:**
- `frontend/src/jaspenInterface/Workspace/ScoreDashboard.jsx` — add export dropdown
- `frontend/src/jaspenInterface/Workspace/JaspenClient.jsx` — add export methods
**Steps:**
1. Add export dropdown button to ScoreDashboard header (PDF / PPTX / CSV options)
2. Trigger download via `window.open(exportUrl)` or fetch + blob download
3. Show loading state during generation
4. Gate UI options by plan entitlement

---

## PHASE 6: Onboarding Flow (Day 12)

### 6.1 — Frontend: First-Time User Wizard
**Files:**
- New file: `frontend/src/jaspenInterface/Workspace/components/OnboardingWizard.jsx`
- `frontend/src/jaspenInterface/Workspace/JaspenWorkspace.jsx` — conditional render
**Steps:**
1. Create 3-step onboarding wizard:
   - **Step 1**: "What's your role?" (Executive, PM, Analyst, Other)
   - **Step 2**: "What are you evaluating?" (New initiative, Cost optimization, Growth strategy, Operational improvement)
   - **Step 3**: "How would you like to start?" → options:
     - "Start a conversation" → normal intake flow
     - "Upload a list of ideas" → batch upload flow
     - "Upload data for analysis" → data analysis flow
2. Store completion flag in user profile or localStorage: `jaspen_onboarded: true`
3. Show wizard on first login; skip on subsequent visits
4. Pass selections as `intake_context` to the conversation start

---

## PHASE 7: Backend Hardening (Days 13–14)

### 7.1 — Add Backend Dockerfile
**Files:**
- New file: `backend/Dockerfile`
**Steps:**
1. Create multi-stage Dockerfile:
   ```dockerfile
   FROM python:3.12-slim AS base
   WORKDIR /app
   COPY requirements.txt .
   RUN pip install --no-cache-dir -r requirements.txt
   COPY . .
   EXPOSE 8000
   CMD ["gunicorn", "--bind", "0.0.0.0:8000", "--workers", "4", "--timeout", "120", "wsgi:app"]
   ```
2. Add `.dockerignore` excluding tests, instance/, sessions_data/, __pycache__
3. Test build locally: `docker build -t jaspen-backend .`

### 7.2 — Rate Limiting by User/Org
**Files:**
- `backend/app/__init__.py` — modify rate limiter key function
- `backend/app/routes/ai_agent.py` — add per-route limits
**Steps:**
1. Change rate limiter key from `get_remote_address` to a composite key:
   ```python
   def rate_limit_key():
       from flask_jwt_extended import get_jwt_identity
       try:
           user_id = get_jwt_identity()
           return f"user:{user_id}" if user_id else get_remote_address()
       except:
           return get_remote_address()
   ```
2. Add specific rate limits to expensive routes:
   - `/conversation/start`: 10/minute per user
   - `/conversation/continue`: 30/minute per user
   - `/analyze`: 5/minute per user
   - `/batch-ideas/rank`: 3/minute per user

### 7.3 — Migrate Session Storage to DB-Only
**Files:**
- `backend/app/routes/sessions.py`
- `backend/app/routes/ai_agent.py`
- `backend/app/routes/strategy.py`
**Steps:**
1. Remove all file-based `sessions_data/` reads/writes
2. Remove all file-based `scenarios_data/` reads/writes
3. Add `scenarios_json` column to `UserSession` model (or a dedicated `Scenario` model)
4. Migrate existing file data to DB via one-time script
5. This is critical for Digital Ocean App Platform where filesystem is ephemeral

### 7.4 — GitHub Actions CI/CD Pipeline
**Files:**
- New file: `.github/workflows/ci.yml`
- New file: `.github/workflows/deploy.yml`
**Steps:**
1. CI workflow (on push/PR):
   - Checkout → install deps → run `pytest` → run frontend `npm test`
   - Lint check (optional: add `ruff` for Python, `eslint` for JS)
2. Deploy workflow (on push to main):
   - Build frontend → deploy to Vercel (or via SFTP script)
   - Build backend Docker image → push to registry → deploy to Digital Ocean
3. Add secrets to GitHub repo settings (SENTRY_DSN, API keys, etc.)

---

## PHASE 8: Enterprise Polish (Days 15–17)

### 8.1 — Audit Logging Expansion
**Files:**
- `backend/app/models.py` — verify `AdminAuditEvent` model
- All route files — add audit events for significant actions
**Steps:**
1. Log these events to `AdminAuditEvent`:
   - Session created/completed/archived
   - Scorecard generated
   - Scenario created/adopted
   - WBS task created/updated/deleted
   - Batch ideas uploaded/ranked/promoted
   - Connector sync triggered
   - User login/logout/failed login
2. Add `GET /api/v1/admin/audit-log` endpoint with filtering (user, action, date range)
3. Enterprise plan: expose audit log in admin UI

### 8.2 — Skeleton Loading States
**Files:**
- New file: `frontend/src/shared/components/SkeletonLoader.jsx`
- `frontend/src/jaspenInterface/Workspace/ScoreDashboard.jsx`
- `frontend/src/jaspenInterface/Workspace/ScenarioModeler.jsx`
- `frontend/src/jaspenInterface/Workspace/components/ExecutionPanel.jsx`
**Steps:**
1. Create reusable skeleton components (score card skeleton, table skeleton, chart skeleton)
2. Use CSS `@keyframes shimmer` animation (gray gradient pulse)
3. Replace spinner/loading states in ScoreDashboard, ScenarioModeler, and ExecutionPanel with skeletons
4. Match skeleton shapes to actual content layout for smooth transition

### 8.3 — Graceful Error Recovery
**Files:**
- `frontend/src/jaspenInterface/Workspace/JaspenClient.jsx`
- New file: `frontend/src/shared/components/ErrorBoundary.jsx`
**Steps:**
1. Add retry logic to JaspenClient for transient failures (5xx, network errors):
   - Exponential backoff: 1s → 2s → 4s, max 3 retries
   - Only retry idempotent requests (GET, and POST where safe)
2. Add React Error Boundary wrapping each major workspace section
3. On API failure, show inline error with "Retry" button instead of crashing
4. Add toast notification system for non-blocking errors

### 8.4 — Connector Credential Encryption Verification
**Files:**
- `backend/app/connectors/` — all connector files
- `backend/app/models.py` — connector-related models
**Steps:**
1. Audit all places where connector credentials (OAuth tokens, API keys) are stored
2. Verify `CONNECTOR_ENCRYPTION_KEY` is used with Fernet symmetric encryption before DB write
3. Verify decryption happens only at point-of-use, never logged
4. If encryption is missing, implement: `cryptography.fernet.Fernet(key).encrypt(token.encode())`
5. Rotate encryption key support: store key version alongside encrypted data

---

## Summary: Execution Order & Dependencies

```
PHASE 1 (Days 1-2)   — Critical fixes: tokens, XSS, CSP, auth, Sentry
                        No dependencies. All parallel-safe.

PHASE 2 (Days 3-6)   — Batch idea upload feature
                        Depends on: Phase 1 (Sentry for error visibility)
                        Steps 2.1→2.2→2.3→2.4→2.5 are sequential
                        Step 2.6 (frontend) can start after 2.1
                        Step 2.7 can happen anytime after 2.4

PHASE 3 (Days 7-8)   — Streaming responses
                        Independent of Phase 2

PHASE 4 (Day 9)      — Context summarization
                        Independent

PHASE 5 (Days 10-11) — Export (PDF/PPTX)
                        Independent

PHASE 6 (Day 12)     — Onboarding wizard
                        Depends on: Phase 2 (to offer batch upload option)

PHASE 7 (Days 13-14) — Backend hardening
                        7.3 (DB migration) should happen before heavy usage
                        7.4 (CI/CD) independent

PHASE 8 (Days 15-17) — Enterprise polish
                        Independent, but best done after core features stable
```

**Total estimated effort: ~17 working days** (solo developer pace)

After this, the remaining items (drawer tab UI, MFA, SSL, Stripe) bring you to enterprise-ready.
