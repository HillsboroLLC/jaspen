# Connector Context Pills Auth Race

Status: resolved in production code on 2026-07-19; runtime verification remains recommended with an account that has connected sources.

Resolution: the connector-status loader now uses the shared retry-aware `authFetch` path, reruns when the authenticated user changes, retains existing connector state on transient failures, and emits development-only status/message warnings without logging connector data.

## Summary

On a fresh login, the workspace Data Context connector pills can temporarily be missing even when the account has connected sources. The objective pills continue to render because they are driven by local/session objective state, while connector pills depend on an async connector-status request.

Observed behavior:

- Fresh login with a different account: Jira, Salesforce, and Snowflake Data Context pills were missing.
- Later in the same session, after navigating around and returning, the pills appeared without code or connector configuration changes.
- Objective pills continued to display normally.

This points to a frontend loading/auth timing bug rather than a backend understanding issue.

## Components Involved

Primary component:

- `frontend/src/jaspenInterface/Workspace/JaspenChat.jsx`

Relevant functions/state:

- `connectedDataSources`
- `activeContextSourceIds`
- `renderConnectorContextTags()`
- `renderSelectedDataContextPills()`
- `loadConnectedSources` effect

Backend endpoint:

- `GET /api/v1/connectors/status`
- implemented in `backend/app/routes/connectors.py`

## Data Flow

1. `connectedDataSources` initializes as an empty array.
2. `JaspenChat.jsx` runs a `useEffect` named `loadConnectedSources`.
3. The effect calls `GET /api/v1/connectors/status`.
4. The response is filtered to connector records that are:
   - `connected === true`
   - one of the allowed connector IDs:
     - `jira_sync`
     - `salesforce_insights`
     - `snowflake_insights`
     - `servicenow_insights`
     - `netsuite_insights`
     - `oracle_fusion_insights`
5. Filtered records become `connectedDataSources`.
6. `renderConnectorContextTags()` returns `null` when `connectedDataSources.length === 0`.

## Conditions That Show The Pills

The Data Context row appears when:

- the user is authenticated,
- `/api/v1/connectors/status` returns `200`,
- at least one connector has `connected: true`,
- that connector ID is in the frontend allowlist,
- `connectedDataSources` is populated.

## Conditions That Hide The Pills

The row is hidden when:

- `connectedDataSources` is empty,
- the connector-status request has not completed yet,
- the request fails,
- the request returns `401` or another non-OK status,
- the backend reports connectors as disconnected, locked, or unavailable,
- the component mounted before auth cookies/session refresh were ready.

## Likely Root Cause

The connector-status loader currently uses raw `fetch` with `buildAuthHeaders`, not the app's shared `authFetch`/cookie refresh path.

That means a fresh-login timing issue can happen:

1. `JaspenChat` mounts.
2. `loadConnectedSources` fires immediately.
3. Auth/session cookies or refresh state are not fully ready.
4. `/api/v1/connectors/status` returns `401`, fails, or returns no connected sources.
5. The effect silently returns or catches the error.
6. `connectedDataSources` stays empty.
7. The UI hides the connector pills.
8. Later navigation/remount or plan/user state changes rerun the effect after auth is ready.
9. The same endpoint succeeds and the pills appear.

This is consistent with the issue resolving itself during the same session.

## Why Objective Pills Still Appear

Objective pills are rendered by `renderObjectiveTags()` and depend on objective/session state, not `/api/v1/connectors/status`.

So objective pills can display normally while connector pills are missing.

## Expected Behavior Or Bug?

Expected behavior:

- If an account truly has no connected connectors, the Data Context row should not appear.

Bug behavior:

- If connected connectors exist but a transient auth/API timing issue leaves `connectedDataSources` empty, hiding the row silently is a frontend state bug.

## Proposed Fix

Smallest safe fix later:

1. Replace the raw `fetch` in `loadConnectedSources` with the existing `authFetch` wrapper used elsewhere in `JaspenChat.jsx`.
2. Include auth/user readiness in the effect dependencies, such as `user?.id` or the relevant auth-loaded signal.
3. Do not silently swallow non-OK responses during development; log a safe warning with status only.
4. Optionally add a tiny loading/error state so the row does not disappear without explanation.
5. Keep the existing backend endpoint and connector filtering behavior unchanged.

Potential implementation direction:

```js
const response = await authFetch(`${API_BASE}/api/v1/connectors/status`, {
  headers: buildAuthHeaders({}, 'GET'),
  credentials: 'include',
});
```

Then handle:

- `401`: let `authFetch` attempt refresh/retry.
- non-OK: leave previous connector state intact if it exists, and warn safely in development.
- success with zero connected connectors: set `connectedDataSources([])` because that is a real state.

## Runtime Proof Checklist

To prove the cause in browser DevTools:

1. Log in fresh with an account known to have connected Jira/Salesforce/Snowflake.
2. Open Network tab.
3. Filter for `/api/v1/connectors/status`.
4. Check the first request after workspace mount.
5. Confirm whether it returns:
   - `401`,
   - non-OK,
   - empty/disconnected connectors,
   - or a successful connected connector payload.
6. Navigate away and back.
7. Compare the later `/api/v1/connectors/status` response.

The bug is confirmed if:

- the first request fails or returns no connected sources,
- a later request returns connected sources,
- and no connector settings changed between those requests.

Useful temporary runtime logging for a later fix branch:

```js
devWarn('[connectors/status]', {
  status: response.status,
  ok: response.ok,
  connectorCount: Array.isArray(data?.connectors) ? data.connectors.length : 0,
  connectedCount: connected.length,
});
```

Do not log connector credentials, tokens, or full connector settings.
