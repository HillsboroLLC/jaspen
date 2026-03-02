# Frontend Structure

This repo's frontend lives under `frontend/src/` and is organized by product area plus a small shared component layer.

## Where Things Live
- `frontend/src/App.js`: Route definitions and top-level providers.
- `frontend/src/All/`: Shared marketing/auth pages and common UI used across the site.
- `frontend/src/Market/`: Market-facing pages (e.g., dashboards, MarketIQ, pricing).
- `frontend/src/Ops/`: Operations tools and workflows.
- `frontend/src/components/`: Small shared layout and UI wrappers used across pages.
- `frontend/src/lib/`: Frontend helpers and client utilities.
- `frontend/src/services/`: API clients and data access.
- `frontend/src/config/`: Frontend config (API base, feature flags, etc.).
- `frontend/src/*.css`: Global styles and shared tokens.

## Rules Of The Road
- Route-level pages should be wrapped with `AppShell` for consistent padding and headers.
- Prefer `components/ui` wrappers (`Button`, `Card`, `Input`, `SectionHeader`, `EmptyState`) for new UI so spacing and typography stay consistent.
- Keep MarketIQ styles scoped under `.miq` and avoid importing legacy MarketIQ CSS into MarketIQ components.
- Avoid editing backend/data wiring from the frontend (API calls, auth, persistence) unless explicitly requested.
- Keep changes small and localized; update imports only in files you touch.
