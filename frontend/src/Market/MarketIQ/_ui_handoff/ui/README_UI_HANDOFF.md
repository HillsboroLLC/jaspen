# AI Agent — UI Skin + Blueprints Handoff

This package contains a repo-agnostic UI skin and a set of React "blueprint" components for the AI Agent interface. It is designed to be merged into your existing React application by another tool (Codex) or a developer.

**Hard Rules Followed:**
- No API calls, fetching, WebSocket logic, or business logic is included.
- No assumptions were made about your file structure (all paths are relative to the `ui/` directory).
- No external UI libraries were used.
- All output is presentational React components (JSX) and plain CSS.

---

## 1. How to Integrate

Follow these steps to apply the new UI skin to your application.

### Step 1: Add CSS Files

Copy the two CSS files from `ui/styles/` into your project (e.g., into `src/styles/`).

1.  `tokens.css`: This file contains all the design tokens (colors, fonts, spacing, etc.) as CSS variables. It should be imported at the very top of your main global CSS file.

2.  `marketiq.css`: This file contains all the layout primitives and component styles. **All styles are scoped under the `.miq` class.** This is critical to prevent these styles from interfering with the rest of your application.

### Step 2: Apply the Wrapper Class

In your React application, find the top-level component that renders the AI Agent pages and wrap it with a `div` that has the `miq` class.

```jsx
// Example: In your main App.js or a layout component

import "./styles/tokens.css";
import "./styles/marketiq.css";

function App() {
  return (
    <div className="miq">
      {/* Your existing AI Agent router and components go here */}
      <YourMarketIQApplication />
    </div>
  );
}
```

### Step 3: Merge Blueprints into Real Components

The `ui/blueprints/` directory contains layout-only blueprint components. **These are not meant to be used directly.** Instead, their JSX structure should be transplanted into your *existing*, real components that already have state, hooks, and backend connections.

**The process for Codex or a developer should be:**

1.  **Open a blueprint file** (e.g., `ScoreDashboardBlueprint.jsx`).
2.  **Open the corresponding real component** in your codebase (e.g., the component that renders your current Score tab).
3.  **Keep all existing hooks, state management, and data fetching logic** in your real component.
4.  **Replace the JSX** in your real component with the JSX from the blueprint file.
5.  **Connect the real data and handlers** to the new JSX. The blueprints contain comments like `// INTEGRATION: ...` to mark where real data and functions should be wired up.

---

## 2. File Structure

Here is a breakdown of the files included in this package.

### `ui/styles/`

-   `tokens.css`: Design tokens (CSS variables).
-   `marketiq.css`: Scoped styles for all components and layouts.

### `ui/components/` (UI Kit)

These are small, reusable, presentational-only components. They can be copied into your project (e.g., `src/components/miq/`) and used to build the UI.

-   `Button.jsx`
-   `Card.jsx`
-   `Input.jsx`
-   `Badge.jsx`
-   `Tabs.jsx`
-   `Modal.jsx`

### `ui/blueprints/` (Layout Blueprints)

These are high-level layout templates. **Do not use them directly.** Transplant their JSX into your real, stateful components.

-   `MarketIQShell.jsx`: The main layout wrapper with the push-drawer functionality.
-   `ReadinessSidebarBlueprint.jsx`: The content for the "Analysis Readiness" drawer.
-   `ScoreDashboardBlueprint.jsx`: The layout for the main "Score" tab.
-   `ScenarioModelerBlueprint.jsx`: The layout for the "Scenarios" tab.
-   `ExploreAnalysisBlueprint.jsx`: The layout for the "Refine & Rescore" tab.
-   `ComparisonViewBlueprint.jsx`: The content for the "Score Summary" drawer panel.
-   `AnalysisHistoryBlueprint.jsx`: The list of past analyses, used in the History drawer and the full "Analyses" page.

---

## 3. Drawer Behavior Note

As requested, the main layout shell (`MarketIQShell.jsx`) is designed so that when a drawer opens, it **pushes** the main content to the right instead of overlapping it. This is achieved by adding a `margin-left` to the `.miq-main` container when the `.drawer-open` class is present on the `.miq-shell` wrapper. This ensures no content is ever hidden by an open drawer.
