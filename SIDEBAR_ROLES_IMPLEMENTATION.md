# Comprehensive Implementation Instructions: Role-Based Views, Sidebar Identity & Pricing

## Context

This document provides exact, file-by-file implementation instructions for making the Jaspen sidebar, workspace, and admin console role-aware. Every user persona (Owner, Admin, Creator, Collaborator, Viewer) must see a distinct, coherent interface. The Jaspen Admin console must use real controls — not placeholder data — when previewing roles. Pricing and seat models are updated to be market-competitive and self-serve-ready for Team plans.

---

## Architecture Overview

### Two role systems exist — do not conflate them

1. **Organization roles** (stored in DB as `OrganizationMember.role`):
   - `owner`, `admin`, `creator`, `collaborator`, `viewer`
   - Govern sidebar visibility, project access, team management, and workspace landing experience
   - Source of truth: backend `OrganizationMember` model + `organization_access_payload_for_user()`

2. **LSS roles** (stored in localStorage as `USER_ROLES`):
   - `admin`, `project_lead`, `team_member`
   - Govern project-workflow permissions (kanban, tollgates, artifact editing)
   - **Leave these entirely untouched throughout this implementation**

### Permission sets (already defined in Team.jsx and orgs.py)

```
ORG_MANAGE_ROLES = ['owner', 'admin']                        -> invite, remove, change roles, edit org, seat policy
ORG_EDIT_ROLES   = ['owner', 'admin', 'creator', 'collaborator'] -> edit project artifacts, change sharing on own projects
Viewer           = read-only on everything
```

### Creator vs Collaborator — the product distinction

- **Creator** = can originate work that belongs to the organization. Creates new projects scoped to the org. Their projects appear in org reporting and the shared project pool. Can share their projects with others.
- **Collaborator** = can contribute to work someone else originated. Opens projects shared with them. Can edit artifacts and run scenarios within shared projects. Cannot create new org-scoped projects. Cannot change sharing settings on projects they don't own.
- **Viewer** = read-only. Can browse scorecard results, conversation history, reports. Cannot edit anything or start new analyses.

| Capability | Creator | Collaborator | Viewer |
|---|---|---|---|
| Start new analysis / project | Yes | No | No |
| Edit shared project artifacts | Yes | Yes | No |
| Run scenarios on shared projects | Yes | Yes | No |
| Change project visibility/sharing | Own projects | No | No |
| See org Dashboard | Yes | Yes | Yes |
| Comment on shared projects | Yes | Yes | No |

---

## Step 0: Pricing & Seat Model Update

### File: `/backend/app/billing_config.py`

### Current state

Team and Enterprise both have `monthly_price_usd: None`, `monthly_credits: None`, and `sales_only: True`. They use per-role seat caps: `max_admin_seats`, `max_creator_seats`, `max_collaborator_seats`.

### Problem

1. No public price anchor for Team — users see "Contact sales" which kills self-serve conversion
2. Per-role seat caps (`max_creator_seats: 5`, `max_collaborator_seats: 10`) are rigid and don't let orgs allocate as they see fit
3. Not competitive with market pricing for B2B AI tools ($39-75/seat/mo range)

### Changes to `DEFAULT_PLAN_CATALOG`

Replace the `team` and `enterprise` entries:

```python
'team': {
    'label': 'Team',
    'monthly_price_usd': 49,              # per seat
    'price_model': 'per_seat',            # NEW: tells frontend how to display
    'min_seats': 5,                       # NEW: minimum purchase
    'monthly_credits_base': 5000,         # NEW: pooled base
    'monthly_credits_per_seat': 500,      # NEW: additional per paid seat
    'monthly_credits': None,              # computed at provisioning time
    'self_serve': True,                   # CHANGED from False
    'sales_only': False,                  # CHANGED from True
    'description': 'Collaborative workspace for teams with shared projects and pooled credits.',
    'max_admin_seats': 3,                 # CHANGED from 2
    'max_total_paid_seats': None,         # NEW: replaces per-role caps
    'max_viewer_seats': None,             # unchanged: unlimited free
},
'enterprise': {
    'label': 'Enterprise',
    'monthly_price_usd': None,
    'price_model': 'custom',              # NEW
    'monthly_credits': None,
    'self_serve': False,
    'sales_only': True,
    'description': 'Sales-led deployment with governance, SSO, and advanced model access.',
    'max_admin_seats': 10,                # CHANGED from 5
    'max_total_paid_seats': None,         # NEW: negotiated per contract
    'max_viewer_seats': None,
},
```

**Remove these keys from both team and enterprise:**
- `max_creator_seats`
- `max_collaborator_seats`

### Rationale for $49/seat/mo

- Jasper AI: $39-59/seat
- Notion Business: $20/seat (no AI agent)
- Figma Full: $75/seat
- $49/seat at 5-seat minimum = $245/mo floor per org — meaningful revenue without premium sticker shock

### Credit model

- 5,000 pooled base + 500/seat scales naturally
- 5-person team = 7,500 credits/mo
- 15-person team = 12,500 credits/mo
- Overage packs ($12/1K, $50/5K, $180/20K) already exist and need no changes

### Seat enforcement changes

#### File: `/backend/app/orgs.py`

The `DEFAULT_SEAT_POLICIES` dict (line ~30) and `role_has_capacity()` function (line ~347) currently enforce per-role caps. Change to:

**New seat enforcement logic:**
1. Count total paid seats = admin + creator + collaborator (viewers are free)
2. Compare against `org.max_total_paid_seats` (set during checkout or by admin; None = unlimited)
3. Only enforce admin cap separately (3 for team, 10 for enterprise)

Update `DEFAULT_SEAT_POLICIES` to match new catalog:

```python
DEFAULT_SEAT_POLICIES = {
    'team': {
        'owner': 1,
        'admin': 3,          # hard cap
        'creator': None,     # no per-role cap; total paid seats governs
        'collaborator': None,
        'viewer': None,
    },
    'enterprise': {
        'owner': 1,
        'admin': 10,
        'creator': None,
        'collaborator': None,
        'viewer': None,
    },
    'essential': {
        'owner': 1,
        'admin': 1,
        'creator': 2,
        'collaborator': 3,
        'viewer': None,
    },
    'free': {
        'owner': 1,
        'admin': 1,
        'creator': 1,
        'collaborator': 2,
        'viewer': None,
    },
}
```

Update `role_has_capacity()`:
- For team/enterprise plans: check admin cap from policy, then check total paid seats against `org.max_total_paid_seats`
- For free/essential plans: keep existing per-role caps

Update `build_seat_usage()`:
- Add `total_paid_used` and `total_paid_limit` to the returned dict

#### File: `/backend/app/models.py` — Organization model

Add column:
```python
max_total_paid_seats = db.Column(db.Integer, nullable=True, default=None)
```

This is set during Stripe checkout (for self-serve Team) or by admin (for Enterprise). `None` = unlimited.

**Migration:** Create a new migration to add this column. This is a nullable column so no data backfill needed.

### Frontend pricing display

#### File: `/frontend/src/jaspenInterface/Account/Account.jsx`

The plan card display (around line ~1524) currently shows:
```
hasPrice ? `$${plan.monthly_price_usd}/mo` : 'Contact sales'
```

Update to handle `price_model`:
```javascript
const priceDisplay = (plan) => {
  if (plan.price_model === 'per_seat') {
    return `$${plan.monthly_price_usd}/seat/mo`;
  }
  if (plan.price_model === 'custom') {
    return 'Contact sales';
  }
  if (Number.isFinite(plan.monthly_price_usd)) {
    return plan.monthly_price_usd === 0 ? '$0' : `$${plan.monthly_price_usd}/mo`;
  }
  return 'Contact sales';
};
```

Add a subtitle under Team price: `5 seat minimum · pooled credits scale with team size`

#### File: `/frontend/src/jaspenInterface/Team/Team.jsx`

Update `PLAN_SEAT_MATRIX` to show `total_paid` instead of per-role breakdowns:
- Replace "Creator X/5 · Collaborator X/10" with "Paid seats: X/Y used"
- Keep admin cap display: "Admin: X/3"
- Show viewers separately: "Viewers: X (unlimited)"

Update the seat policy editor cards:
- Remove individual creator/collaborator cap cards for team/enterprise plans
- Add one "Total Paid Seats" card showing current usage vs limit
- Keep admin cap card as the only role-specific limit
- Keep per-role cards only for free/essential plans

---

## Step 1: Backend — Return `active_organization_name` and `active_organization_role`

### File: `/backend/app/orgs.py`

**Function: `organization_access_payload_for_user(user)` (line ~399)**

Current return shape:
```python
{
    "active_organization_plan_key": ...,
    "can_access_team": ...,
    "can_access_enterprise_admin": ...,
}
```

Change to:
```python
active_membership = None
if active_org:
    active_membership = OrganizationMember.query.filter_by(
        organization_id=active_org.id,
        user_id=user.id,
        status="active",
    ).first()

return {
    "active_organization_plan_key": to_public_plan(active_org.plan_key) if active_org else None,
    "active_organization_name": active_org.name if active_org else None,
    "active_organization_role": active_membership.role if active_membership else None,
    "can_access_team": bool(normalized_plans.intersection({"team", "enterprise"})),
    "can_access_enterprise_admin": "enterprise" in normalized_plans,
}
```

### File: `/backend/app/routes/auth.py`

**Function: `_user_payload(user)` (line ~142)**

No structural changes needed — it already spreads `**organization_access_payload_for_user(user)`. The new fields flow through automatically.

**Verification:** After this change, `GET /api/v1/auth/me` returns:
```json
{
  "active_organization_id": "...",
  "active_organization_name": "Acme Team",
  "active_organization_role": "collaborator",
  "active_organization_plan_key": "team",
  "can_access_team": true,
  "can_access_enterprise_admin": false,
  "is_admin": false
}
```

For a user with no org:
```json
{
  "active_organization_id": null,
  "active_organization_name": null,
  "active_organization_role": null,
  "active_organization_plan_key": null,
  "can_access_team": false,
  "can_access_enterprise_admin": false
}
```

**Important:** Verify that login and signup routes also call `_user_payload`. If they return a minimal `{ user: { email } }` shape, the new fields won't be there on first load. The frontend `checkAuthStatus()` fires on mount and refreshes via `/auth/me`, so this is acceptable — but note there may be a brief flash where `orgDisplayName` shows `'Organization'` before the `/auth/me` response populates it.

---

## Step 2: AuthContext — Add derived org role values

### File: `/frontend/src/shared/auth/AuthContext.jsx`

The following already exist (user's recent edit at line ~118-553):
- `resolvePlanCategory()` helper
- `planCategory`, `orgDisplayName`, `isPlatformAdmin`, `isEnterpriseAdmin`, `canAccessOrgSettings`

**Add these new derived values** immediately after the existing block (after line 553):

```javascript
// Organization role from auth payload (owner/admin/creator/collaborator/viewer/null)
const orgRole = String(user?.active_organization_role || '').toLowerCase() || null;

// Role-based capability flags for sidebar and workspace gating
const canManageOrg = orgRole === 'owner' || orgRole === 'admin' || isPlatformAdmin;
const canEditProjects = ['owner', 'admin', 'creator', 'collaborator'].includes(orgRole) || isPlatformAdmin;
const isOrgViewer = orgRole === 'viewer';
const isOrgCollaborator = orgRole === 'collaborator';
const isOrgCreator = orgRole === 'creator' || orgRole === 'owner' || orgRole === 'admin';
```

Note: `isOrgCreator` includes owner/admin because they have all creator capabilities plus more.

**Add all new values to the context `value` object** (the block starting at line ~555):

```javascript
const value = {
    // ... existing values ...
    planCategory,
    orgDisplayName,
    isPlatformAdmin,
    isEnterpriseAdmin,
    canAccessOrgSettings,

    // NEW: org role fields
    orgRole,
    canManageOrg,
    canEditProjects,
    isOrgViewer,
    isOrgCollaborator,
    isOrgCreator,

    // ... rest of existing values (LSS, etc.) ...
};
```

**Do not touch** `USER_ROLES`, `PERMISSIONS`, `ROLE_PERMISSIONS`, `hasPermission`, `hasRole`, `isAdmin`, `isProjectLead`, `isTeamMember`, or any LSS-related code.

---

## Step 3: Extract `SidebarIdentityFooter` component

### Create directory and file

```
mkdir -p /frontend/src/jaspenInterface/Workspace/components/
```

Create: `/frontend/src/jaspenInterface/Workspace/components/SidebarIdentityFooter.jsx`

This component extracts the repeated `renderSidebarFooter` block from `JaspenWorkspace.jsx` (currently at line ~1588, called at lines ~1918, ~5019, ~5280, ~5844).

### Component design

The component calls `useAuth()` internally for identity data and accepts only workspace-local state as props:

```jsx
import React from 'react';
import { useAuth } from '../../../shared/auth/AuthContext';
import { FontAwesomeIcon } from '@fortawesome/react-fontawesome';
import { faChevronUp, faChevronDown, faDownload } from '@fortawesome/free-solid-svg-icons';

export default function SidebarIdentityFooter({
  // Workspace-local state only — identity comes from useAuth()
  userName,
  userEmail,
  userInitials,
  planLabel,
  accountQuickMenuOpen,
  onToggleQuickMenu,
  onConnectorsClick,
  // Render props for complex content that stays in parent
  quickMenuContent,
}) {
  const { orgDisplayName } = useAuth();

  return (
    <div className="jas-ud-footer">
      <button
        type="button"
        className="jas-ud-footer-profile"
        onClick={onToggleQuickMenu}
      >
        <div className="jas-ud-footer-avatar">{userInitials}</div>
        <div className="jas-ud-footer-meta">
          <span className="jas-ud-footer-name">{userName}</span>
          <span className="jas-ud-footer-org">{orgDisplayName}</span>
          <span className="jas-ud-footer-plan">{planLabel}</span>
        </div>
      </button>
      <div className="jas-ud-footer-actions">
        <button
          type="button"
          className="jas-ud-footer-icon"
          title="Get apps and extensions"
          aria-label="Get apps and extensions"
          onClick={onConnectorsClick}
        >
          <FontAwesomeIcon icon={faDownload} />
        </button>
        <button
          type="button"
          className="jas-ud-footer-icon"
          title="Account menu"
          aria-label="Account menu"
          onClick={onToggleQuickMenu}
        >
          <FontAwesomeIcon icon={accountQuickMenuOpen ? faChevronUp : faChevronDown} />
        </button>
      </div>
      {accountQuickMenuOpen && quickMenuContent}
    </div>
  );
}
```

### Key rules for extraction

1. The `jas-ud-footer-meta` div changes from 2 spans to 3 spans:
   - Line 1: `userName` (display name, existing)
   - Line 2: `orgDisplayName` (NEW — from auth context)
   - Line 3: `planLabel` (existing `currentPlanLabel`)

2. The Knowledge submenu (lines ~1661-1718 in JaspenWorkspace.jsx) uses `createPortal`, refs (`knowledgeSubmenuRef`, `knowledgeSubmenuWrapRef`), and timer-based open/close. **The parent (JaspenWorkspace) keeps the refs and timers and passes the entire rendered quick menu as `quickMenuContent`.** The child component just renders it conditionally.

3. Email stays in the expanded quick menu (`jas-ud-footer-email`), NOT in the main footer body.

### Integration in JaspenWorkspace.jsx

Replace every call to `renderSidebarFooter(onClose)` with the extracted component. All 4 call sites (~1918, ~5019, ~5280, ~5844) get replaced. The `renderSidebarFooter` function is removed.

---

## Step 4: Role-gated sidebar navigation

### File: `/frontend/src/jaspenInterface/Workspace/JaspenWorkspace.jsx`

### 4a. Pull new auth values

At the top of the component where `useAuth()` is destructured, add the new fields:

```javascript
const {
  user, login, logout, /* ...existing... */
  planCategory, orgDisplayName, isPlatformAdmin, isEnterpriseAdmin, canAccessOrgSettings,
  orgRole, canManageOrg, canEditProjects, isOrgViewer, isOrgCollaborator, isOrgCreator,
} = useAuth();
```

### 4b. Replace scattered inline derivations

The following existing computed values (lines ~838-848) can now use auth context:

```javascript
// BEFORE (scattered):
const isGlobalAdmin = Boolean(user?.is_admin || billingStatus?.is_admin);
const userOrganizationPlanKey = String(user?.active_organization_plan_key || '').toLowerCase();
const canAccessDashboard = isGlobalAdmin || ['team', 'enterprise'].includes(currentPlanKey) || ...;
const canAccessTeamAdmin = isGlobalAdmin || Boolean(user?.can_access_team);
const canAccessEnterpriseAdmin = isGlobalAdmin || Boolean(user?.can_access_enterprise_admin) || ...;

// AFTER (clean):
const isGlobalAdmin = isPlatformAdmin || Boolean(billingStatus?.is_admin);
const showRealDashboard = planCategory !== 'individual' || isPlatformAdmin;
const showLockedDashboard = planCategory === 'individual' && !isPlatformAdmin;
const canAccessTeamAdmin = canAccessOrgSettings;
const canAccessEnterpriseAdmin = isEnterpriseAdmin;
```

### 4c. Rename labels

In `renderUserMenuContent` (line ~1722) and the quick menu (line ~1632):

| Current label | New label | Condition |
|---|---|---|
| `Team Admin` | `Organization` | `canAccessOrgSettings` |
| `Enterprise Admin` | `Enterprise Admin` (unchanged) | `isEnterpriseAdmin` |
| `Admin` (in main nav) | `Jaspen Admin` | `isPlatformAdmin` |

Find every string `"Team Admin"` in this file and replace with `"Organization"`. There are occurrences at:
- Line ~1653 (quick menu)
- Line ~1760 (main nav)

### 4d. Locked Dashboard for individuals

Replace the conditional Dashboard rendering (line ~1727):

```jsx
{/* Real Dashboard for team/enterprise users */}
{showRealDashboard && (
  <button className="jas-ud-item" onClick={() => { onClose?.(); navigate('/dashboard'); }}>
    <FontAwesomeIcon icon={faListCheck} />
    <span className="jas-ud-item-label">Dashboard</span>
  </button>
)}

{/* Locked Dashboard upsell for individual users */}
{showLockedDashboard && (
  <button
    className="jas-ud-item jas-ud-item-locked"
    onClick={() => { setBillingModalOpen(true); }}
    title="Upgrade to Team to unlock shared dashboards"
  >
    <FontAwesomeIcon icon={faListCheck} />
    <span className="jas-ud-item-label">Dashboard</span>
    <FontAwesomeIcon icon={faLock} className="jas-ud-item-lock-icon" />
  </button>
)}
```

Import `faLock` from `@fortawesome/free-solid-svg-icons` at the top of the file.

### 4e. Hide structurally irrelevant items

For the main nav and quick menu, hide these entirely for individuals:
- `Organization` — only show when `canAccessOrgSettings` is true
- `Enterprise Admin` — only show when `isEnterpriseAdmin` is true
- `Jaspen Admin` — only show when `isPlatformAdmin` is true

---

## Step 5: Each persona's workspace experience

### File: `/frontend/src/jaspenInterface/Workspace/JaspenWorkspace.jsx`

### 5a. Owner / Admin / Creator experience

**This is the current default experience.** No landing changes needed. Creators:
- See the full intake form and can start new projects
- See their own projects in the history sidebar
- See scored sessions on the Scores page
- Can create scenarios, edit artifacts, manage their projects
- Can share projects they own

### 5b. Collaborator experience

Collaborators can interact with shared projects but **cannot create new projects from the intake form**.

**Changes needed:**

1. **Replace intake form with shared projects landing.** When `isOrgCollaborator && !sessionId`:
   - Do NOT show the intake form
   - Show a "Shared with me" project list loaded from `GET /api/v1/team/projects`
   - Each card shows: project name, owner name, status, last updated, "Can edit" badge
   - Clicking a card navigates to the project in the workspace

2. **Empty state when no projects are shared:**
   ```
   You haven't been invited to collaborate on any projects yet.
   When a project owner shares a project with you, it will appear here.
   ```

3. **When viewing a shared project** (collaborator has a sessionId loaded):
   - Full edit access: can interact with scorecard, run scenarios, edit artifacts
   - Cannot change project sharing/visibility settings
   - Cannot delete the project

### 5c. Viewer experience

Viewers are read-only. They can see but not touch.

**Changes needed:**

1. **Replace intake form with shared projects landing.** When `isOrgViewer && !sessionId`:
   - Same layout as collaborator but cards say "View only" instead of "Can edit"

2. **Empty state:**
   ```
   You haven't been invited to view any projects yet.
   When a project owner shares a project with you, it will appear here.
   ```

3. **When viewing a shared project** (viewer has a sessionId loaded):
   - Read-only mode: disable all mutating controls
   - Show a `Viewing as read-only` badge at the top
   - Disable the send/submit button in the chat input
   - Disable scenario creation buttons
   - Disable artifact editing
   - Disable readiness checklist editing

### 5d. Individual (no org) experience

**No changes from current behavior.** They see the intake form, their own projects, and the locked Dashboard upsell. No shared project features.

### 5e. Shared projects loading

Add state and effect for loading shared projects:

```javascript
const [sharedProjects, setSharedProjects] = useState([]);
const [sharedProjectsLoading, setSharedProjectsLoading] = useState(false);

useEffect(() => {
  if (planCategory === 'individual' || !user) return;
  if (!isOrgCollaborator && !isOrgViewer) return;

  let cancelled = false;
  setSharedProjectsLoading(true);

  authFetch('/api/v1/team/projects')
    .then(res => res.json())
    .then(data => {
      if (!cancelled) {
        setSharedProjects(Array.isArray(data?.projects) ? data.projects : []);
      }
    })
    .catch(() => { if (!cancelled) setSharedProjects([]); })
    .finally(() => { if (!cancelled) setSharedProjectsLoading(false); });

  return () => { cancelled = true; };
}, [planCategory, user, isOrgCollaborator, isOrgViewer, authFetch]);
```

### 5f. Shared projects landing JSX

```jsx
{(isOrgCollaborator || isOrgViewer) && !sessionId && (
  <div className="jas-shared-projects-landing">
    <h2>Shared Projects</h2>
    <p className="jas-shared-projects-sub">
      {isOrgViewer
        ? 'Projects shared with you for viewing.'
        : 'Projects shared with you for collaboration.'}
    </p>

    {sharedProjectsLoading && (
      <p className="jas-shared-projects-empty">Loading shared projects...</p>
    )}

    {!sharedProjectsLoading && sharedProjects.length === 0 && (
      <div className="jas-shared-projects-empty-state">
        <p>
          {isOrgViewer
            ? "You haven't been invited to view any projects yet."
            : "You haven't been invited to collaborate on any projects yet."}
        </p>
        <p>When a project owner shares a project with you, it will appear here.</p>
      </div>
    )}

    {!sharedProjectsLoading && sharedProjects.length > 0 && (
      <div className="jas-shared-projects-list">
        {sharedProjects.map((project) => (
          <button
            key={project.session_id}
            className="jas-shared-project-card"
            onClick={() => navigate(`/new?session_id=${encodeURIComponent(project.session_id)}`)}
          >
            <strong>{project.name || 'Untitled Project'}</strong>
            <span>Owner: {project.owner_name || 'Unknown'}</span>
            <span>Status: {project.status || 'active'}</span>
            <span>Updated: {project.updated_at ? new Date(project.updated_at).toLocaleString() : '—'}</span>
            <span className="jas-shared-project-access">
              {isOrgViewer ? 'View only' : 'Can edit'}
            </span>
          </button>
        ))}
      </div>
    )}
  </div>
)}
```

### 5g. Gate the intake form

The existing intake form should only show for users who can create:

```jsx
{isOrgCreator && !sessionId && (
  {/* existing intake form JSX */}
)}

{planCategory === 'individual' && !sessionId && (
  {/* existing intake form JSX — individuals can always create */}
)}
```

### 5h. Viewer read-only enforcement

When `isOrgViewer` is true and a session is loaded:

1. **Disable the send/submit button:**
   ```javascript
   if (isOrgViewer) return; // Block submission for viewers
   ```

2. **Show read-only indicator:**
   ```jsx
   {isOrgViewer && sessionId && (
     <div className="jas-viewer-badge">
       <FontAwesomeIcon icon={faLock} />
       Viewing as read-only
     </div>
   )}
   ```

3. **Disable scenario controls** — any create/apply/adopt scenario button checks `!isOrgViewer`
4. **Disable readiness checklist editing** — render but don't allow toggles

---

## Step 6: Jaspen Admin — Remove placeholders, use real controls

### File: `/frontend/src/jaspenInterface/Admin/JaspenAdmin.jsx`

### Problem

The Experience Preview section (lines ~456-510) launches preview links that navigate away from the admin console. The buttons don't explain what each role actually sees. When previewing roles like Viewer or Collaborator, the admin is sent to the Team management page — which is not what those users see.

### 6a. Replace Experience Preview with descriptive role cards

Replace the three button groups (Workspace, Team, Enterprise) with a single unified grid that explains what each persona sees:

```javascript
const ROLE_EXPERIENCE_OPTIONS = [
  {
    label: 'Individual · Free',
    description: 'Personal workspace, 300 credits/mo, Pluto model only. No org features.',
    path: '/new?admin_preview=workspace&plan_key=free',
  },
  {
    label: 'Individual · Essential',
    description: 'Personal workspace, 3,000 credits/mo, Pluto model. No org features.',
    path: '/new?admin_preview=workspace&plan_key=essential',
  },
  {
    label: 'Team · Owner',
    description: 'Full org control: manage members, seat policy, billing. Creates projects, sees all org projects.',
    path: '/new?admin_preview=workspace&plan_key=team&role=owner',
  },
  {
    label: 'Team · Admin',
    description: 'Org management: invite/remove members, change roles. Creates projects, sees all org projects.',
    path: '/new?admin_preview=workspace&plan_key=team&role=admin',
  },
  {
    label: 'Team · Creator',
    description: 'Creates new projects, shares them with org. Cannot manage members or seat policy.',
    path: '/new?admin_preview=workspace&plan_key=team&role=creator',
  },
  {
    label: 'Team · Collaborator',
    description: 'Edits projects shared with them. Cannot create new projects or manage org.',
    path: '/new?admin_preview=workspace&plan_key=team&role=collaborator',
  },
  {
    label: 'Team · Viewer',
    description: 'Read-only access to shared projects. Cannot edit, create, or manage anything.',
    path: '/new?admin_preview=workspace&plan_key=team&role=viewer',
  },
  {
    label: 'Enterprise · Admin',
    description: 'Enterprise governance: SSO/SAML, data retention, audit logs, compliance. Plus full org control.',
    path: '/enterprise-admin?admin_preview=enterprise&role=admin',
  },
];
```

Render as a grid of cards with label, description, and Preview button:

```jsx
<section className="jas-admin-subsection">
  <h3>Role Experience Preview</h3>
  <p className="jas-admin-sub">
    Preview the Jaspen interface as each user persona sees it.
    Workspace previews show the actual landing experience for that role.
    All data is synthetic and mutating actions are disabled.
  </p>
  <div className="jas-admin-role-grid">
    {ROLE_EXPERIENCE_OPTIONS.map((option) => (
      <div key={option.label} className="jas-admin-role-card">
        <strong>{option.label}</strong>
        <p>{option.description}</p>
        <button
          type="button"
          className="jas-admin-secondary"
          onClick={() => openPreview(option.path)}
        >
          Preview
        </button>
      </div>
    ))}
  </div>
</section>
```

### 6b. What the admin should see when previewing each role

The key change is that **all team role previews now route to the workspace** (`/new?admin_preview=workspace&plan_key=team&role=...`) instead of routing viewers and collaborators to the team management page. This means:

- **Owner/Admin preview:** Shows workspace with full intake form + sidebar shows Organization and admin links. The admin can then navigate to `/team` from there to see the team management page.
- **Creator preview:** Shows workspace with full intake form. No Organization link in sidebar.
- **Collaborator preview:** Shows the shared projects landing page (with synthetic demo projects). No intake form.
- **Viewer preview:** Shows the shared projects landing page (with synthetic demo projects). All controls disabled. Read-only badge visible.

### 6c. Synthetic data for workspace role previews

When the workspace detects `admin_preview=workspace` with a `role` param, it needs to generate synthetic shared projects for the collaborator and viewer previews. Add to JaspenWorkspace.jsx:

```javascript
const SYNTHETIC_SHARED_PROJECTS = [
  {
    session_id: 'preview-project-1',
    name: 'Q3 Strategic Initiative Assessment',
    owner_name: 'Avery Admin',
    status: 'completed',
    updated_at: new Date(Date.now() - 2 * 60 * 60 * 1000).toISOString(),
    visibility: 'team',
  },
  {
    session_id: 'preview-project-2',
    name: 'Product Launch Readiness Scorecard',
    owner_name: 'Olivia Owner',
    status: 'active',
    updated_at: new Date(Date.now() - 24 * 60 * 60 * 1000).toISOString(),
    visibility: 'specific',
  },
  {
    session_id: 'preview-project-3',
    name: 'Annual Budget Risk Analysis',
    owner_name: 'Chris Creator',
    status: 'active',
    updated_at: new Date(Date.now() - 3 * 24 * 60 * 60 * 1000).toISOString(),
    visibility: 'team',
  },
];
```

When in preview mode with role=collaborator or role=viewer, use `SYNTHETIC_SHARED_PROJECTS` instead of fetching from the API. Show a preview banner at the top.

### 6d. Fix `SUPPORT_ROLE_SWITCH_OPTIONS` in workspace

```javascript
const SUPPORT_ROLE_SWITCH_OPTIONS = [
  { value: 'actual', label: 'Actual account', path: '/new' },
  { value: 'workspace:free', label: 'Personal · Free', path: '/new?admin_preview=workspace&plan_key=free' },
  { value: 'workspace:essential', label: 'Personal · Essential', path: '/new?admin_preview=workspace&plan_key=essential' },
  // Team roles — all route to workspace, not team management page
  { value: 'workspace:viewer', label: 'Team · Viewer', path: '/new?admin_preview=workspace&plan_key=team&role=viewer' },
  { value: 'workspace:collaborator', label: 'Team · Collaborator', path: '/new?admin_preview=workspace&plan_key=team&role=collaborator' },
  { value: 'workspace:creator', label: 'Team · Creator', path: '/new?admin_preview=workspace&plan_key=team&role=creator' },
  { value: 'workspace:admin', label: 'Team · Admin', path: '/new?admin_preview=workspace&plan_key=team&role=admin' },
  { value: 'workspace:owner', label: 'Team · Owner', path: '/new?admin_preview=workspace&plan_key=team&role=owner' },
  { value: 'enterprise:admin', label: 'Enterprise · Admin', path: '/enterprise-admin?admin_preview=enterprise&role=admin' },
];
```

Update `resolveSupportRoleSwitchValue()` to also parse the `role` param from workspace preview URLs.

### 6e. Workspace preview role resolution

When in admin preview mode, the workspace needs to simulate the org role. Add after the existing `adminWorkspacePreviewPlan` resolution:

```javascript
const adminPreviewRole = useMemo(() => {
  if (!isPlatformAdmin) return null;
  const params = new URLSearchParams(location.search);
  if (String(params.get('admin_preview') || '').trim().toLowerCase() !== 'workspace') return null;
  const role = String(params.get('role') || '').trim().toLowerCase();
  return ['owner', 'admin', 'creator', 'collaborator', 'viewer'].includes(role) ? role : null;
}, [location.search, isPlatformAdmin]);

// Use preview role to override auth-derived flags when in preview mode
const effectiveIsViewer = adminPreviewRole === 'viewer' || (!adminPreviewRole && isOrgViewer);
const effectiveIsCollaborator = adminPreviewRole === 'collaborator' || (!adminPreviewRole && isOrgCollaborator);
const effectiveIsCreator = !adminPreviewRole
  ? isOrgCreator
  : ['owner', 'admin', 'creator'].includes(adminPreviewRole);
const effectiveCanManageOrg = !adminPreviewRole
  ? canManageOrg
  : ['owner', 'admin'].includes(adminPreviewRole);
```

Use the `effective*` versions throughout the workspace render for gating intake form, shared projects landing, viewer badge, etc.

---

## Step 7: Team.jsx — Role-gated UI within Team management page

### File: `/frontend/src/jaspenInterface/Team/Team.jsx`

The current code already has `effectiveRole`, `canManageMembers`, and `canEditProjects`. The UI already disables controls based on these. However, section visibility doesn't change per role.

### Changes by role:

**Owner / Admin (`canManageMembers = true`):**
- See everything: members table with role dropdowns, invitation form, seat policy editor, sharing controls, org name editor
- All controls enabled (unless in preview mode)
- This is the current behavior — no changes needed

**Creator (`canEditProjects = true`, `canManageMembers = false`):**
- See members table with role column as read-only pills (no dropdown) — already handled
- See shared projects table with sharing controls only for their own projects
- Do NOT see the seat policy editor section
- Do NOT see the org name editor (disable input and hide Save button)
- Do NOT see the invite form

**Collaborator (`canEditProjects = true`, `canManageMembers = false`):**
- Same as Creator, except:
- In shared projects table, only see projects shared with them (not all org projects)
- Cannot change visibility/sharing on any project

**Viewer (`canEditProjects = false`, `canManageMembers = false`):**
- See members table as read-only — already handled
- See shared projects as read-only (no visibility dropdowns, no sharing inputs)
- Do NOT see the seat policy editor
- Do NOT see the invite form
- Org name field disabled — already handled

### Implementation

Add derived booleans after existing permission checks:

```javascript
const showSeatPolicy = canManageMembers;
const showInviteForm = canManageMembers;
const showOrgNameSave = canManageMembers && !previewModeActive;
```

Wrap seat policy section with `{showSeatPolicy && (...)}`.
Wrap invite form section with `{showInviteForm && (...)}`.

Filter shared projects by access:

```javascript
const visibleProjects = useMemo(() => {
  if (canManageMembers) return projects; // Admins see all
  const currentUserId = String(summary?.membership?.user_id || '');
  return (projects || []).filter((project) => {
    if (String(project?.created_by_user_id || '') === currentUserId) return true;
    if (project.visibility === 'team') return true;
    if (project.visibility === 'specific') {
      return (project.shared_with_user_ids || []).includes(currentUserId);
    }
    return false;
  });
}, [projects, canManageMembers, summary?.membership?.user_id]);
```

Use `visibleProjects` instead of `projects` in the shared projects table.

### Update seat policy UI for new total-seat model

Replace per-role seat cards (creator, collaborator) with a single "Total Paid Seats" card for team/enterprise plans:

```jsx
{showSeatPolicy && isTeamOrEnterprise && (
  <div className="jas-seat-policy-card">
    <div className="jas-seat-card-label">Paid Seats (Admin + Creator + Collaborator)</div>
    <div className="jas-seat-card-usage">
      {seatUsage.total_paid_used} / {seatUsage.total_paid_limit || '∞'}
    </div>
    {/* Admin cap card still shown separately */}
  </div>
)}
```

Keep per-role cards only for free/essential plans that still use per-role caps.

---

## Step 8: CSS additions

### File: `/frontend/src/jaspenInterface/Workspace/JaspenWorkspace.css`

```css
/* Footer identity block — 3-line layout */
.jas-ud-footer-meta {
  display: flex;
  flex-direction: column;
  gap: 1px;
  overflow: hidden;
}

.jas-ud-footer-name {
  font-weight: 600;
  font-size: 13px;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.jas-ud-footer-org {
  font-size: 11px;
  opacity: 0.7;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.jas-ud-footer-plan {
  font-size: 10px;
  opacity: 0.5;
  text-transform: uppercase;
  letter-spacing: 0.5px;
}

/* Locked nav item */
.jas-ud-item-locked {
  opacity: 0.5;
  cursor: pointer;
}

.jas-ud-item-locked:hover {
  opacity: 0.7;
}

.jas-ud-item-lock-icon {
  margin-left: auto;
  font-size: 10px;
  opacity: 0.6;
}

/* Shared projects landing */
.jas-shared-projects-landing {
  padding: 32px 24px;
  max-width: 800px;
  margin: 0 auto;
}

.jas-shared-projects-landing h2 {
  margin: 0 0 8px;
}

.jas-shared-projects-sub {
  opacity: 0.7;
  margin: 0 0 24px;
}

.jas-shared-projects-empty-state {
  text-align: center;
  padding: 48px 24px;
  opacity: 0.6;
}

.jas-shared-projects-list {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.jas-shared-project-card {
  display: flex;
  flex-direction: column;
  gap: 4px;
  padding: 16px;
  border: 1px solid var(--border-color, rgba(0,0,0,0.1));
  border-radius: 8px;
  background: transparent;
  cursor: pointer;
  text-align: left;
  transition: background 0.15s;
}

.jas-shared-project-card:hover {
  background: var(--hover-bg, rgba(0,0,0,0.03));
}

.jas-shared-project-access {
  font-size: 11px;
  text-transform: uppercase;
  letter-spacing: 0.5px;
  opacity: 0.5;
}

/* Read-only viewer badge */
.jas-viewer-badge {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 2px 8px;
  font-size: 10px;
  text-transform: uppercase;
  letter-spacing: 0.5px;
  border-radius: 4px;
  background: var(--badge-bg, rgba(0,0,0,0.05));
  opacity: 0.7;
}
```

### File: `/frontend/src/jaspenInterface/Admin/JaspenAdmin.css`

```css
.jas-admin-role-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(240px, 1fr));
  gap: 12px;
  margin-top: 12px;
}

.jas-admin-role-card {
  padding: 16px;
  border: 1px solid var(--border-color, rgba(0,0,0,0.1));
  border-radius: 8px;
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.jas-admin-role-card p {
  font-size: 12px;
  opacity: 0.7;
  margin: 0;
}

.jas-admin-role-card .jas-admin-secondary {
  align-self: flex-start;
  margin-top: auto;
}
```

---

## Verification Matrix

After all changes, verify each persona sees the correct experience:

| Feature | Owner | Admin | Creator | Collaborator | Viewer | Individual |
|---|---|---|---|---|---|---|
| **Sidebar footer** | Name + Org + Plan | Name + Org + Plan | Name + Org + Plan | Name + Org + Plan | Name + Org + Plan | Name + Personal Workspace + Plan |
| **Dashboard nav** | Real | Real | Real | Real | Real | Locked (upsell) |
| **Organization nav** | Yes | Yes | Hidden | Hidden | Hidden | Hidden |
| **Enterprise Admin nav** | If enterprise | If enterprise | Hidden | Hidden | Hidden | Hidden |
| **Jaspen Admin nav** | If platform admin | If platform admin | Hidden | Hidden | Hidden | Hidden |
| **Workspace landing** | Intake form | Intake form | Intake form | Shared projects list | Shared projects list (read-only) | Intake form |
| **Create new project** | Yes | Yes | Yes | No | No | Yes |
| **View shared projects** | All org projects | All org projects | Own + shared | Shared only | Shared only | N/A |
| **Edit shared projects** | Yes | Yes | Own projects | Projects shared to them | No | N/A |
| **Manage members** | Yes | Yes | No | No | No | N/A |
| **Invite members** | Yes | Yes | No | No | No | N/A |
| **Seat policy** | Yes | Yes | No | No | No | N/A |
| **Scenario tools** | Yes | Yes | Yes | Yes | No | Plan-gated |
| **Empty state (no shared)** | N/A | N/A | N/A | "No projects shared yet" | "No projects shared yet" | N/A |

### Edge cases to test

1. **Downgraded user**: `subscription_plan = free`, `active_organization_id` set (org was downgraded). Should resolve to `planCategory = 'individual'`, `orgDisplayName = 'Personal Workspace'`, locked Dashboard.

2. **Collaborator with no shared projects**: Should see the empty state message, not a blank page.

3. **Viewer navigating directly to a project URL**: Should load the project in read-only mode if they have access, or redirect to the shared projects landing.

4. **Platform admin in preview mode**: Each role switcher option should show the correct workspace experience — collaborator/viewer see shared projects landing, creator sees intake form.

5. **Invited but not yet joined**: User has received invitation but hasn't accepted. They should see the individual experience until they accept. After accepting, they should immediately see their org role's experience on next `/auth/me` refresh.

6. **Admin previewing collaborator**: The admin clicks "Team · Collaborator" in the role switcher. They should see the shared projects landing with synthetic demo projects, not the team management page.

---

## Build Sequence

1. Backend: Update `billing_config.py` — new pricing model, remove per-role caps, add `max_total_paid_seats`
2. Backend: Add `max_total_paid_seats` column to Organization model (migration)
3. Backend: Update `orgs.py` — new seat enforcement logic, add `active_organization_name` and `active_organization_role` to payload
4. Backend: Verify `_user_payload()` in `auth.py` propagates new fields
5. Frontend: AuthContext — add `orgRole`, `canManageOrg`, `canEditProjects`, `isOrgViewer`, `isOrgCollaborator`, `isOrgCreator`
6. Frontend: Extract `SidebarIdentityFooter` component (create `components/` directory)
7. Frontend: Integrate footer with 3-line identity (name + org + plan) across all 4 call sites
8. Frontend: Rename `Team Admin` to `Organization` in nav and quick menu
9. Frontend: Add locked Dashboard for individuals, hide irrelevant items
10. Frontend: Add shared projects loading for collaborator/viewer
11. Frontend: Add shared projects landing page with empty states
12. Frontend: Add viewer read-only enforcement in workspace
13. Frontend: Gate intake form — show only for creators and individuals
14. Frontend: Update Team.jsx — gate sections by role, filter projects by access, update seat UI
15. Frontend: Update JaspenAdmin.jsx — replace preview buttons with descriptive role cards
16. Frontend: Fix `SUPPORT_ROLE_SWITCH_OPTIONS` routing and add preview role resolution
17. Frontend: Add synthetic shared projects for admin preview mode
18. Frontend: Update Account.jsx — per-seat pricing display for Team plan
19. CSS for all new elements
20. Test all personas from the verification matrix

---

## Out of scope for this pass

- Real per-project role assignments (separate from org role)
- Comment UI integration in workspace view (comments exist in Team.jsx but not in workspace)
- Notification system for when projects are shared with you
- Multi-org switcher in sidebar
- Enterprise sub-team model
- Quick menu / nav consolidation (Phase 2)
- New nav items like `Sessions` or `Data Sources`
- Stripe checkout integration for self-serve Team (requires Stripe configuration)
- Renaming `Projects` to `Sessions` or `Connectors` to `Data Sources`
