# SEKKI Platform - Frontend Context

**Last Updated:** 2026-02-02
**Purpose:** Backend team reference for frontend integration requirements

---

## Table of Contents
1. [Frontend Structure](#frontend-structure)
2. [What's Working vs What Needs Backend](#whats-working-vs-what-needs-backend)
3. [API Endpoints](#api-endpoints)
4. [Data Models & Interfaces](#data-models--interfaces)
5. [Key Components](#key-components)

---

## 1. Frontend Structure

### Directory Organization

```
frontend/src/
├── All/                          # Shared/common components
│   ├── components/               # Reusable UI components
│   │   ├── Header/
│   │   ├── Hero/
│   │   ├── HomePage/
│   │   └── ...
│   ├── pages/                    # Public pages
│   │   ├── Home/
│   │   ├── Support/
│   │   └── ...
│   ├── shared/                   # Shared utilities
│   │   ├── auth/                # Authentication (AuthContext)
│   │   ├── components/          # Toast notifications, etc.
│   │   └── hooks/               # useChatCommands, etc.
│   ├── services/                # API services
│   │   └── api.js
│   ├── Login/
│   └── SignUp/
│
├── Market/                       # Market-facing features
│   ├── MarketIQ/                # Market IQ Analysis workspace
│   │   ├── workspace/
│   │   │   ├── MarketIQWorkspace.jsx    # Main workspace component
│   │   │   └── threadHydrator.js        # Thread state management
│   │   ├── AnalysisHistory.jsx          # Analysis history viewer
│   │   ├── ComparisonView.jsx           # Compare analyses
│   │   ├── ExploreAnalysis.jsx          # Deep-dive analysis explorer
│   │   ├── ReadinessSidebar.jsx         # Readiness score display
│   │   ├── ScenarioModeler.jsx          # "What-if" scenario editor
│   │   └── ScoreDashboard.jsx           # Score visualization
│   ├── Dashboard/               # User dashboard
│   ├── Sessions/                # Session management
│   ├── Account/                 # Account settings
│   ├── PaymentPage/             # Payment processing
│   └── components/              # Market-specific components
│       └── ThreadEditModal.jsx  # Edit thread/session metadata
│
├── Ops/                         # Operations/PM tools
│   ├── ProjectPlanning/         # Project planning interface
│   │   ├── ProjectPlanning.jsx  # Main planning component
│   │   ├── starterData.js       # Default project template
│   │   └── ProjectPlanning.module.css
│   ├── PMDashboard/             # Project Management dashboard
│   ├── LSSDashboard/            # Lean Six Sigma dashboard
│   ├── Statistics/              # Statistical analysis tools
│   ├── Activities/              # Activity tracking
│   └── [30+ Lean/PM tools]      # SIPOC, DMAIC, Kaizen, etc.
│
├── lib/                         # Core libraries
│   └── MarketIQClient.jsx       # API client & endpoints
│
├── config/                      # Configuration
│   └── apiBase.js
│
├── services/                    # Additional services
│
├── App.js                       # Main app router
└── index.js                     # Entry point
```

### Key Files

| File | Purpose |
|------|---------|
| `lib/MarketIQClient.jsx` | Central API client with all endpoints |
| `Market/MarketIQ/workspace/MarketIQWorkspace.jsx` | Main Market IQ interface (2500+ lines) |
| `Ops/ProjectPlanning/ProjectPlanning.jsx` | Project planning interface (2500+ lines) |
| `All/shared/auth/AuthContext.jsx` | Authentication state management |
| `App.js` | Route definitions and protected routes |

---

## 2. What's Working vs What Needs Backend

### ✅ Fully Integrated (Working)

#### Market IQ Workspace
- ✅ Conversational intake flow (POST `/api/chat`)
- ✅ Analysis generation (POST `/api/market-iq/analyze`)
- ✅ Thread bundle loading (GET `/api/market-iq/threads/:id/bundle`)
- ✅ Scenario creation & application (POST `/api/market-iq/scenarios/*`)
- ✅ Analysis history viewing
- ✅ Project generation trigger (POST `/api/projects/generate/ai`)

#### Authentication
- ✅ Login (JWT tokens)
- ✅ Session management
- ✅ Protected routes

#### Sessions
- ✅ Session listing (with localStorage fallback)
- ✅ Session deletion

### 🟡 Partially Integrated (Needs Work)

#### Project Planning
- 🟡 **Load Plan** - Working but needs proper backend data structure
  - GET `/api/projects/:id/plan`
  - Currently falls back to STARTER_PLAN on 404
- 🟡 **Auto-save** - Frontend implemented, needs backend validation
  - PATCH `/api/projects/:id/plan`
  - Debounced 1-second save
- 🟡 **Validation** - Frontend calls endpoint but needs backend logic
  - POST `/api/projects/:id/plan/validate`
- 🟡 **Templates** - UI complete, backend endpoints may be missing
  - GET `/api/templates`
  - POST `/api/templates`
  - POST `/api/projects/:id/apply-template`

### ❌ Not Yet Implemented (Backend Missing)

#### Project Planning AI Features
- ❌ **AI Assistant** - Endpoint exists but may need implementation
  - POST `/api/projects/:id/ai-assist`
  - Expected: `{ message, plan }` → `{ response, updated_plan? }`
- ❌ **Style Regeneration** - Frontend calls but backend may not exist
  - POST `/api/projects/:id/plan/regenerate`
  - Body: `{ force_style: 'agile' | 'waterfall' | 'hybrid' }`
  - Expected: `{ plan: {...} }`

#### Thread Management
- ❌ **Thread Rename** - Frontend calls but backend may not exist
  - PATCH `/api/sessions/:id`
  - Body: `{ name: string }`
- ❌ **Adopt Analysis** - Frontend calls but backend may not exist
  - POST `/api/market-iq/threads/:threadId/adopt`
  - Body: `{ analysis_id: string }`

#### Export Features
- ❌ **CSV Export** - Frontend has placeholder ("not yet implemented")
- ❌ **MS Project Export** - Frontend has placeholder

#### Dashboard
- ❌ Using mock data - needs real API integration
  - Active projects count
  - Documents created
  - Completion rate
  - Credits usage

---

## 3. API Endpoints

### Base Configuration
```javascript
API_BASE = process.env.REACT_APP_API_BASE || 'https://api.sekki.io'
```

### Authentication
All requests include:
- **Credentials:** `include` (cookies)
- **Authorization Header:** `Bearer ${token}` (from localStorage: `access_token` or `token`)
- **Session Header:** `X-Session-ID: ${sid}` (from localStorage: `miq_sid`)

---

### 3.1 Market IQ Endpoints

#### Chat & Conversation
```javascript
POST /api/chat
POST /api/chat/stream         // SSE streaming
```

**Payload (Conversational Intake):**
```json
{
  "message": "User's description or question",
  "systemPrompt": "You conduct a natural business discovery chat...",
  "session_id": "session_123",
  "conversation_history": [
    { "role": "user", "content": "..." },
    { "role": "assistant", "content": "..." }
  ]
}
```

**Payload (Post-Analysis Chat):**
```json
{
  "message": "User's question about analysis",
  "conversation_history": [...],
  "docType": "market_iq",
  "phase": 3,
  "analysis_context": { /* full scorecard */ },
  "analysis_id": "analysis_123"
}
```

**Response:**
```json
{
  "response": "AI reply text",
  "session_id": "session_123",
  "readiness_score": 85,
  "status": "gathering_info" | "ready_to_analyze"
}
```

#### Analysis
```javascript
POST /api/market-iq/analyze
```

**Payload:**
```json
{
  "session_id": "session_123",
  "thread_id": "session_123",
  "transcript": "Full conversation transcript...",
  "project_name": "My Project",
  "deterministic": true,
  "seed": 42,
  "assumptions": {},
  "docType": "market_iq"
}
```

**Response:**
```json
{
  "analysis_id": "analysis_456",
  "market_iq_score": 78,
  "score_category": "STRONG POTENTIAL",
  "component_scores": {
    "market_demand": { "score": 85, "weight": 0.25, "rationale": "..." },
    "competitive_landscape": { "score": 72, "weight": 0.20, "rationale": "..." },
    // ... more components
  },
  "financial_impact": {
    "revenue_potential": "High",
    "cost_structure": "Moderate",
    "profit_margin_outlook": "Strong"
  },
  "strengths": ["...", "..."],
  "risks": ["...", "..."],
  "strategic_recommendations": ["...", "..."]
}
```

#### Thread Management
```javascript
GET /api/market-iq/threads/:threadId/bundle?msg_limit=50&scn_limit=50
```

**Response:**
```json
{
  "thread_id": "thread_123",
  "messages": [
    { "role": "user", "content": "...", "timestamp": "..." },
    { "role": "assistant", "content": "...", "timestamp": "..." }
  ],
  "analysis_history": [
    {
      "analysis_id": "analysis_456",
      "created_at": "2026-02-01T10:00:00Z",
      "result": {
        "project_name": "My Project",
        "market_iq_score": 78,
        "score_category": "STRONG POTENTIAL"
      }
    }
  ],
  "scenarios": [
    {
      "scenario_id": "scn_789",
      "label": "Optimistic Growth",
      "deltas": { "market_demand.score": 95 },
      "created_at": "2026-02-01T11:00:00Z"
    }
  ],
  "adopted_analysis_id": "analysis_456"
}
```

```javascript
GET /api/market-iq/threads/:threadId/analyses?limit=20&offset=0
GET /api/market-iq/threads/:threadId/analyses/latest
DELETE /api/market-iq/analyses/:analysisId
```

#### 🚧 Thread Operations (May Need Implementation)
```javascript
PATCH /api/sessions/:sessionId
Body: { "name": "New Thread Name" }

POST /api/market-iq/threads/:threadId/adopt
Body: { "analysis_id": "analysis_456" }
```

#### Scenarios
```javascript
POST /api/market-iq/threads/:threadId/scenarios
Body: {
  "deltas": { "market_demand.score": 95, "competitive_landscape.score": 80 },
  "label": "Optimistic Growth",
  "session_id": "thread_123"
}

GET /api/market-iq/threads/:threadId/scenarios?limit=50&offset=0

PUT /api/market-iq/scenarios/:scenarioId?thread_id=:threadId
Body: { "deltas": {...}, "label": "..." }

POST /api/market-iq/scenarios/:scenarioId/apply?thread_id=:threadId
Response: { /* adopted snapshot with updated scores */ }

POST /api/market-iq/scenarios/:scenarioId/adopt
Response: { /* adopted snapshot */ }
```

---

### 3.2 Projects Endpoints

#### Project Generation
```javascript
POST /api/projects/generate/ai
```

**Payload (from MarketIQ):**
```json
{
  "sid": "session_123",
  "project_name": "My Project",
  "scorecard_id": "analysis_456",
  "scorecard": {
    "market_iq_score": 78,
    "component_scores": { /* ... */ },
    "financial_impact": { /* ... */ }
  },
  "dry_run": false,
  "persist": true,
  "mode": "replace",
  "commit_message": "begin-project from MarketIQ"
}
```

**Response:**
```json
{
  "project_id": "proj_789",
  "redirect": "/ops/project-planning?projectId=proj_789"
}
```

#### Project Plan CRUD
```javascript
GET /api/projects/:projectId/plan
```

**Response (Expected Structure):**
```json
{
  "wbs": {
    "style": "agile" | "waterfall" | "hybrid",
    "meta": {
      "style_source": "user" | "heuristic",
      "style_reason": "Based on 6-month timeline...",
      "duration_months": 6
    },
    "items": [
      {
        "id": "phase_1",
        "name": "Initialization",
        "children": [
          {
            "id": "task_1_1",
            "name": "Define scope & objectives",
            "assignee": "Sarah Johnson",
            "priority": "High",
            "status": "todo" | "in_progress" | "completed",
            "due_date": "2025-12-15",
            "notes": "Initial planning phase",
            "lead_time_days": 3,
            "completed": false
          }
        ]
      }
    ]
  },
  "timeline": {
    "start_date": "2025-12-09",
    "end_date": "2026-03-31",
    "duration_months": 4,
    "phases": [
      {
        "id": "timeline_1",
        "name": "Initialization",
        "start_date": "2025-12-09",
        "end_date": "2025-12-20",
        "description": "Project setup and planning phase",
        "progress": 25
      }
    ]
  },
  "objectives": [
    {
      "id": "obj_1",
      "title": "Achieve Market Leadership",
      "description": "Establish our product as the leading solution...",
      "progress": 35,
      "key_results": [
        { "label": "Market Share", "value": "15%" },
        { "label": "Customer Satisfaction", "value": "4.5/5.0" }
      ]
    }
  ],
  "stakeholders": [
    {
      "id": "stake_1",
      "name": "Jennifer Martinez",
      "role": "Chief Executive Officer",
      "role_type": "executive" | "core_team" | "external",
      "email": "jennifer.martinez@company.com",
      "influence": 1 | 2 | 3
    }
  ],
  "risks": [
    {
      "id": "risk_1",
      "name": "Technical Complexity",
      "category": "Technical" | "Resource" | "Market" | "Compliance",
      "likelihood": "Low" | "Medium" | "High",
      "impact": "Low" | "Medium" | "High",
      "severity": "low" | "medium" | "high",
      "owner": "David Chen",
      "status": "Identified" | "Monitoring" | "Mitigating",
      "mitigation": "Implement phased rollout..."
    }
  ],
  "resources": {
    "budget": {
      "total": 500000,
      "spent": 157000,
      "items": [
        {
          "category": "Personnel",
          "description": "Salaries and contractor fees",
          "amount": 250000
        }
      ]
    },
    "team": [
      {
        "name": "Sarah Johnson",
        "role": "Product Manager",
        "availability": "100%"
      }
    ]
  },
  "documents": [
    {
      "id": "doc_1",
      "filename": "Project Charter.pdf",
      "category": "Planning" | "Research" | "Marketing" | "Legal" | "Meetings",
      "size": "2.4 MB",
      "owner": "Sarah Johnson",
      "updated_at": "2025-12-01T10:00:00Z"
    }
  ],
  "assumptions": [
    "Market conditions remain stable throughout project duration",
    "Key team members remain available for project duration"
  ],
  "notes": {
    "general": "Comprehensive project plan generated from Market IQ analysis.",
    "risks": "Regular risk reviews scheduled bi-weekly",
    "budget": "Monthly budget reviews with finance team"
  }
}
```

```javascript
PATCH /api/projects/:projectId/plan
Body: { /* full plan object as shown above */ }
Response: 200 OK (no body needed)
```

#### 🚧 Project Plan Operations (May Need Implementation)

```javascript
POST /api/projects/:projectId/plan/validate
Response: 200 OK or validation errors

POST /api/projects/:projectId/plan/regenerate
Body: { "force_style": "agile" | "waterfall" | "hybrid" }
Response: { "plan": { /* updated plan with new style */ } }

POST /api/projects/:projectId/ai-assist
Body: {
  "message": "Add a high priority task to Initialization phase",
  "plan": { /* current plan state */ }
}
Response: {
  "response": "I've added a new high-priority task...",
  "updated_plan": { /* modified plan (optional) */ }
}

POST /api/projects/:projectId/apply-template
Body: { "template_id": "template_123" }
Response: 200 OK
```

---

### 3.3 Templates Endpoints

#### 🚧 Templates (May Need Implementation)

```javascript
GET /api/templates
Response: [
  {
    "id": "template_123",
    "name": "Software Launch",
    "description": "Standard software product launch template",
    "created_at": "2025-12-01T00:00:00Z",
    "phases": [
      {
        "name": "Planning",
        "tasks": [
          { "name": "Define requirements", "lead_time_days": 5 },
          { "name": "Create roadmap", "lead_time_days": 3 }
        ]
      }
    ]
  }
]

POST /api/templates
Body: {
  "name": "My Custom Template",
  "description": "Description of template",
  "phases": [
    {
      "name": "Phase 1",
      "tasks": [
        { "name": "Task 1", "lead_time_days": 5 }
      ]
    }
  ]
}
Response: { "template_id": "template_456" }
```

---

### 3.4 Sessions Endpoints

```javascript
GET /api/sessions
Response: {
  "success": true,
  "sessions": [
    {
      "session_id": "session_123",
      "name": "Market Analysis Project",
      "document_type": "market_iq",
      "status": "completed" | "in_progress",
      "created": "2025-12-01T10:00:00Z",
      "timestamp": "2025-12-01T11:30:00Z",
      "current_phase": 3,
      "chat_history": [...],
      "notes": { "phase1": "...", "phase2": "..." }
    }
  ]
}

DELETE /api/sessions/:sessionId
Response: 200 OK

PATCH /api/sessions/:sessionId
Body: { "name": "New Session Name" }
Response: { "session_id": "session_123", "name": "New Session Name" }
```

---

## 4. Data Models & Interfaces

### 4.1 Market IQ Analysis (Scorecard)

```javascript
{
  // Core identification
  analysis_id: string,              // Unique analysis identifier
  session_id: string,               // Associated session/thread
  created_at: string,               // ISO timestamp
  project_name: string,             // User-provided project name

  // Scoring
  market_iq_score: number,          // 0-100 overall score
  score_category: string,           // "STRONG POTENTIAL" | "MODERATE POTENTIAL" | "NEEDS WORK"

  // Component scores (weighted)
  component_scores: {
    market_demand: {
      score: number,                // 0-100
      weight: number,               // 0.25 (25%)
      rationale: string,
      factors: {
        target_audience_size: string,
        willingness_to_pay: string,
        urgency: string
      }
    },
    competitive_landscape: {
      score: number,
      weight: number,               // 0.20 (20%)
      rationale: string,
      factors: {
        differentiation: string,
        barriers_to_entry: string,
        competitive_intensity: string
      }
    },
    value_proposition: {
      score: number,
      weight: number,               // 0.20 (20%)
      rationale: string,
      factors: {
        problem_solution_fit: string,
        unique_value: string,
        customer_pain_points: string
      }
    },
    go_to_market: {
      score: number,
      weight: number,               // 0.15 (15%)
      rationale: string,
      factors: {
        channel_strategy: string,
        sales_approach: string,
        marketing_reach: string
      }
    },
    execution_feasibility: {
      score: number,
      weight: number,               // 0.15 (15%)
      rationale: string,
      factors: {
        team_capability: string,
        resource_availability: string,
        technical_complexity: string
      }
    },
    financial_viability: {
      score: number,
      weight: number,               // 0.05 (5%)
      rationale: string,
      factors: {
        revenue_model: string,
        cost_structure: string,
        funding_needs: string
      }
    }
  },

  // Financial summary
  financial_impact: {
    revenue_potential: "Low" | "Moderate" | "High",
    cost_structure: "Low" | "Moderate" | "High",
    profit_margin_outlook: "Weak" | "Moderate" | "Strong",
    break_even_timeline: string,
    scaling_potential: string
  },

  // Insights
  strengths: string[],              // Top 3-5 strengths
  risks: string[],                  // Top 3-5 risks
  opportunities: string[],          // Key opportunities
  strategic_recommendations: string[], // 3-5 recommendations

  // Context (optional)
  assumptions: object,              // User-provided assumptions
  transcript: string                // Original conversation
}
```

### 4.2 Scenario

```javascript
{
  scenario_id: string,
  thread_id: string,
  label: string,                    // "Optimistic Growth", "Conservative Estimate"
  deltas: {
    // Dot-notation paths to values to override
    "market_demand.score": 95,
    "competitive_landscape.factors.differentiation": "Very Strong",
    "financial_impact.revenue_potential": "High"
  },
  created_at: string,
  applied_at?: string               // If this scenario has been applied
}
```

### 4.3 Project Plan (WBS)

See detailed structure in Section 3.2 under `GET /api/projects/:projectId/plan`.

Key nested structures:
- **WBS Items** (Phases & Tasks)
- **Timeline** (Phases with dates & progress)
- **Objectives** (OKRs with key results)
- **Stakeholders** (with influence levels)
- **Risks** (with likelihood, impact, mitigation)
- **Resources** (Budget & Team)
- **Documents** (Attachments metadata)

### 4.4 Session/Thread

```javascript
{
  session_id: string,               // Also used as thread_id
  name?: string,                    // User-provided name (editable)
  document_type: string,            // "market_iq"
  status: "in_progress" | "completed",
  created: string,                  // ISO timestamp
  timestamp: string,                // Last updated
  current_phase: number,            // Conversation phase (1-3)

  // Conversation
  chat_history: [
    {
      type: "user" | "assistant" | "system",
      content: string,
      timestamp: string
    }
  ],

  // User notes
  notes: {
    phase1?: string,
    phase2?: string,
    phase3?: string
  },

  // Associated data (may be in bundle instead)
  analysis_id?: string,
  adopted_analysis_id?: string
}
```

### 4.5 Template

```javascript
{
  id: string,
  name: string,
  description: string,
  created_at: string,
  phases: [
    {
      name: string,
      tasks: [
        {
          name: string,
          lead_time_days: number
        }
      ]
    }
  ]
}
```

---

## 5. Key Components

### 5.1 Market IQ Components

#### MarketIQWorkspace.jsx
**Path:** `frontend/src/Market/MarketIQ/workspace/MarketIQWorkspace.jsx`
**Size:** ~2500 lines
**Purpose:** Main Market IQ interface

**Features:**
- Conversational intake (3-phase chat)
- Analysis generation & display
- Scenario modeling ("what-if" analysis)
- Analysis history management
- Project generation trigger
- Thread/session management

**Key State:**
```javascript
const [sessionId, setSessionId] = useState(null);
const [messages, setMessages] = useState([]);
const [analysisResult, setAnalysisResult] = useState(null);
const [activeScorecard, setActiveScorecard] = useState(null);
const [scorecardSnapshots, setScorecardSnapshots] = useState([]);
const [scenarios, setScenarios] = useState([]);
const [uiReadiness, setUiReadiness] = useState(0);
```

**API Calls:**
- `POST /api/chat` - Conversational intake
- `POST /api/market-iq/analyze` - Generate scorecard
- `GET /api/market-iq/threads/:id/bundle` - Load thread state
- `POST /api/market-iq/scenarios/*` - Scenario operations
- `POST /api/projects/generate/ai` - Begin project

#### ScoreDashboard.jsx
**Path:** `frontend/src/Market/MarketIQ/ScoreDashboard.jsx`
**Purpose:** Visualize Market IQ score & components

**Features:**
- Overall score gauge (0-100)
- Component score breakdown with weights
- Category badge (STRONG/MODERATE/NEEDS WORK)
- Color-coded visual indicators

#### ScenarioModeler.jsx
**Path:** `frontend/src/Market/MarketIQ/ScenarioModeler.jsx`
**Purpose:** "What-if" scenario editor

**Features:**
- Adjust component scores with sliders
- See recalculated overall score in real-time
- Save scenarios for comparison
- Apply scenarios to create new analyses

#### AnalysisHistory.jsx
**Path:** `frontend/src/Market/MarketIQ/AnalysisHistory.jsx`
**Purpose:** View past analyses for a thread

**Features:**
- List all analyses with scores
- Click to view full analysis
- Delete analyses
- Compare analyses

#### ComparisonView.jsx
**Path:** `frontend/src/Market/MarketIQ/ComparisonView.jsx`
**Purpose:** Side-by-side analysis comparison

**Features:**
- Compare 2+ analyses
- Highlight differences in scores
- Show scenario deltas

#### ReadinessSidebar.jsx
**Path:** `frontend/src/Market/MarketIQ/ReadinessSidebar.jsx`
**Purpose:** Display readiness score during intake

**Features:**
- Progress indicator (0-100)
- Phase indicators
- Readiness threshold (85+ to analyze)

---

### 5.2 Project Planning Components

#### ProjectPlanning.jsx
**Path:** `frontend/src/Ops/ProjectPlanning/ProjectPlanning.jsx`
**Size:** ~2500 lines
**Purpose:** Project planning workspace

**Features:**
- WBS editor (phases & tasks)
- Multiple views: List, Board (Kanban), Gantt
- Auto-save (1-second debounce)
- Inline editing (contentEditable cells)
- Drag & drop task reordering
- AI Assistant chat sidebar
- Template save/load
- Style selection (Agile/Waterfall/Hybrid)
- Validation modal

**Key State:**
```javascript
const [plan, setPlan] = useState(null);           // Full plan object
const [currentView, setCurrentView] = useState('list');
const [aiMessages, setAiMessages] = useState([]);
const [autoSaving, setAutoSaving] = useState(false);
const [lastSaved, setLastSaved] = useState(null);
```

**API Calls:**
- `GET /api/projects/:id/plan` - Load plan
- `PATCH /api/projects/:id/plan` - Auto-save
- `POST /api/projects/:id/plan/validate` - Validate
- `POST /api/projects/:id/plan/regenerate` - Regenerate with style
- `POST /api/projects/:id/ai-assist` - AI chat
- `POST /api/projects/:id/apply-template` - Apply template
- `GET /api/templates` - Load templates
- `POST /api/templates` - Save template

**Views:**
1. **List View** - Editable table with phases/tasks
2. **Board View** - Kanban board by status
3. **Gantt View** - Timeline visualization

**Tabs:**
- Tasks (WBS)
- Timeline
- Objectives
- Stakeholders
- Risks
- Budget
- Documents

#### starterData.js
**Path:** `frontend/src/Ops/ProjectPlanning/starterData.js`
**Purpose:** Default project plan template

**Contains:**
- Sample phases & tasks
- Timeline structure
- Objectives with key results
- Stakeholders with influence levels
- Risks with mitigation strategies
- Budget breakdown
- Document examples

---

### 5.3 Session Management Components

#### Sessions.jsx
**Path:** `frontend/src/Market/Sessions/Sessions.jsx`
**Purpose:** Session listing & management

**Features:**
- List all sessions
- Filter by status (completed/in_progress)
- View session details (chat history, notes)
- Delete sessions
- Continue sessions
- Fallback to localStorage if API fails

**API Calls:**
- `GET /api/sessions` - Load sessions
- `DELETE /api/sessions/:id` - Delete session

#### ThreadEditModal.jsx
**Path:** `frontend/src/Market/components/ThreadEditModal.jsx`
**Purpose:** Edit thread/session metadata

**Features:**
- Rename thread
- Adopt analysis (set as AI context)
- Load analysis options from bundle

**API Calls:**
- `GET /api/sessions/:id/bundle` - Load analysis options
- `PATCH /api/sessions/:id` - Rename
- `POST /api/market-iq/threads/:id/adopt` - Adopt analysis

---

### 5.4 Supporting Components

#### MarketIQClient.jsx
**Path:** `frontend/src/lib/MarketIQClient.jsx`
**Purpose:** Central API client library

**Exports:**
- `endpoints` - All API endpoint URLs
- `MarketIQ` - Main API methods
  - `chat()` - Chat API
  - `convoStart()` - Start conversation
  - `convoContinue()` - Continue conversation
  - `analyzeFromConversation()` - Generate analysis
  - `scenario()` - Create/apply scenario
  - `fetchBundle()` - Load thread bundle
  - `beginProject()` - Start project planning
  - `listScorecards()` - List analyses
  - `createScenario()` - Create scenario
  - `applyScenario()` - Apply scenario
  - `adoptScenario()` - Adopt scenario
- `storage` - LocalStorage helpers
  - `pushHistory()` - Save analysis to history
  - `getHistory()` - Load history
  - `saveProject()` - Save project
  - `getProjects()` - Load projects

**Session Management:**
- Generates persistent `miq_sid` in localStorage
- Includes in `X-Session-ID` header
- Survives Safari ITP (Intelligent Tracking Prevention)

#### AuthContext.jsx
**Path:** `frontend/src/All/shared/auth/AuthContext.jsx`
**Purpose:** Authentication state management

**Provides:**
- `user` - Current user object
- `login()` - Login method
- `logout()` - Logout method
- `isAuthenticated` - Boolean flag

#### useChatCommands.js
**Path:** `frontend/src/All/shared/hooks/useChatCommands.js`
**Purpose:** Parse & execute AI chat commands

**Features:**
- Parse structured commands from AI responses
- Execute UI actions (VIEW_SET, WBS_ADD_TASK, etc.)
- Toast notifications for feedback

**Command Types:**
```javascript
ChatActionTypes = {
  VIEW_SET: 'VIEW_SET',               // Switch view mode
  WBS_ADD_TASK: 'WBS_ADD_TASK',       // Add task to WBS
  WBS_UPDATE_TASK: 'WBS_UPDATE_TASK', // Update task
  WBS_ADD_DEPENDENCY: 'WBS_ADD_DEPENDENCY',
  EXPORT: 'EXPORT'                    // Export plan (not yet implemented)
}
```

---

## 6. Integration Checklist for Backend Team

### High Priority (Blocking Frontend)

- [ ] **POST /api/projects/:id/plan/regenerate** - Style regeneration
- [ ] **POST /api/projects/:id/ai-assist** - AI assistant chat
- [ ] **PATCH /api/sessions/:id** - Thread rename
- [ ] **POST /api/market-iq/threads/:id/adopt** - Adopt analysis
- [ ] **GET /api/templates** - Load templates
- [ ] **POST /api/templates** - Save template
- [ ] **POST /api/projects/:id/apply-template** - Apply template

### Medium Priority (Enhanced Features)

- [ ] **POST /api/projects/:id/plan/validate** - Full validation logic
- [ ] **GET /api/sessions** - Return real session data (not localStorage)
- [ ] Dashboard metrics endpoints (active projects, credits, etc.)

### Low Priority (Future Features)

- [ ] CSV/MS Project export endpoints
- [ ] Document upload/storage for project plans
- [ ] Real-time collaboration (WebSocket)
- [ ] Notifications system

---

## 7. Testing Notes

### Frontend expects these HTTP status codes:

- **200 OK** - Success
- **404 Not Found** - Resource doesn't exist (frontend falls back to defaults)
- **401 Unauthorized** - Not authenticated (redirects to login)
- **403 Forbidden** - Not authorized
- **500 Internal Server Error** - Backend error (shows error message)

### Error response format:
```json
{
  "error": "Human-readable error message",
  "detail": "Additional details (optional)",
  "msg": "Alternative error message field"
}
```

Frontend checks for `error`, `detail`, or `msg` fields in error responses.

---

## 8. Environment Variables

### Required:
```bash
REACT_APP_API_BASE=https://api.sekki.io
```

### Optional:
```bash
# Can be set via window.__API_BASE__ in index.html instead
```

---

## 9. Browser Compatibility Notes

- **Speech Recognition** - Used for voice input in AI assistant
  - Requires WebKit Speech Recognition API
  - Falls back gracefully if unavailable

- **LocalStorage** - Critical for session persistence
  - Generates `miq_sid` for session tracking
  - Stores auth tokens (`access_token`, `token`)
  - Caches analysis history

- **EventSource (SSE)** - Used for chat streaming
  - `/api/chat/stream` endpoint
  - Falls back to regular POST if unavailable

---

## 10. Common Integration Patterns

### 1. Authentication Flow
```javascript
// All API calls include:
const token = localStorage.getItem('access_token') || localStorage.getItem('token');
const sid = localStorage.getItem('miq_sid');

fetch(url, {
  credentials: 'include',
  headers: {
    'Authorization': `Bearer ${token}`,
    'X-Session-ID': sid,
    'Content-Type': 'application/json'
  }
});
```

### 2. Auto-save Pattern (ProjectPlanning)
```javascript
// Debounced auto-save (1 second after last edit)
useEffect(() => {
  if (!plan) return;

  if (saveTimeoutRef.current) {
    clearTimeout(saveTimeoutRef.current);
  }

  saveTimeoutRef.current = setTimeout(() => {
    savePlan(); // PATCH /api/projects/:id/plan
  }, 1000);
}, [plan]);
```

### 3. Fallback to Starter Data
```javascript
// ProjectPlanning loads plan or uses default
try {
  const res = await fetch(`/api/projects/${projectId}/plan`);
  if (res.status === 404) {
    setPlan(deepClone(STARTER_PLAN)); // Use default template
    return;
  }
  // ... handle response
} catch (err) {
  setPlan(deepClone(STARTER_PLAN)); // Fallback on error
}
```

### 4. Session ID Persistence
```javascript
// Generate once, reuse across sessions
function getSid() {
  let sid = localStorage.getItem('miq_sid');
  if (!sid) {
    sid = `web-${Math.random().toString(36).slice(2)}-${Date.now()}`;
    localStorage.setItem('miq_sid', sid);
  }
  return sid;
}
```

---

## Contact & Questions

For questions about frontend implementation or integration requirements:
- **Frontend Developer:** Check git history for component authors
- **This Document:** Update as backend integrations are completed
- **API Reference:** See `~/PROJECTS_API_REFERENCE.md` (if available)

---

**End of Frontend Context Document**
