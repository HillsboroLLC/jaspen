# AI Agent Backend - Project Status

## What We're Building
A conversation-driven business evaluation system where:
- Users create Projects
- Each Project has multiple Threads (different ideas/initiatives)
- Each Thread has Analyses that score ideas using ScoringFrameworks
- An Activities page lets users compare and rank all analyses

## What We Completed Today (Feb 2, 2026)

### 1. Database Models ✅
Added 3 new models to `backend/app/models.py`:
- **ScoringFramework** - defines evaluation criteria (Market IQ, Technical Feasibility, ROI, etc.)
- **AgentThread** - conversation threads for each idea within a project
- **Analysis** - scored evaluations of ideas using a framework

Migration applied successfully. All tables exist in PostgreSQL.

### 2. Seed Data ✅
Created 4 system scoring frameworks:
1. Market IQ Assessment (matches our existing 4-component system)
2. Market Viability Assessment
3. Technical Feasibility  
4. ROI Analysis

### 3. API Endpoints ✅
Created `backend/app/routes/ai_agent.py` with:
- GET /api/ai-agent/frameworks (list frameworks)
- POST/GET/PUT/DELETE for threads
- POST/GET/PUT/DELETE for analyses

Blueprint registered and service restarted successfully.

## Current Files
- **Models:** `backend/app/models.py` (updated)
- **API Routes:** `backend/app/routes/ai_agent.py` (new)
- **Seed Script:** `backend/seed_scoring_frameworks.py` (new)
- **Latest Backup:** `/home/sekki/sekki-platform-backups/backup_20260202_172112.tar.gz`

## Next Steps
1. **Test the API endpoints** - verify they return data correctly
2. **Wire up frontend** - connect React components to new endpoints
3. **Build Activities page** - UI to compare analyses across threads
4. **Implement scoring logic** - calculate scores from conversation inputs

## Key Context
- Backend: DigitalOcean server at 159.65.255.214 (SSH via VS Code)
- Frontend: Separate repo at `/Users/ldbailey/Projects/sekki-platform`
- Service: `sudo systemctl restart gunicorn-sekki.service`
- Backup command: `~/backup.sh`

## Understanding the Two Systems
**Market IQ (existing)** = MiqThread, MiqAnalysis - intake conversation, generates single scorecard
**AI Agent (new)** = AgentThread, Analysis, ScoringFramework - evaluate multiple ideas, compare side-by-side