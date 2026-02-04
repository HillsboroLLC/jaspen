// File: frontend/src/Market/components/Icons/CustomIcons.jsx
import React, { forwardRef } from "react";
import "./CustomIcons.css";

const base = ({ size = 32, strokeWidth = 1.4, title, className, ...rest }) => ({
  width: size,
  height: size,
  viewBox: "0 0 24 24",
  xmlns: "http://www.w3.org/2000/svg",
  role: "img",
  "aria-label": title,
  className: ["miq-icon", className].filter(Boolean).join(" "),
  fill: "none",                // default: no fills for stroked shapes
  stroke: "currentColor",
  strokeWidth,
  strokeLinecap: "round",
  strokeLinejoin: "round",
  vectorEffect: "non-scaling-stroke",
  shapeRendering: "geometricPrecision",
  style: { overflow: "visible" },
  ...rest,
});

/** Project Management (Kanban) */
export const IconPM = forwardRef(function IconPM(
  { size, strokeWidth, title = "Project Management Tools", className, ...rest },
  ref
) {
  const props = base({ size, strokeWidth, title, className, ...rest });
  return (
    <svg ref={ref} {...props}>
      {title ? <title>{title}</title> : null}
      {/* Frame */}
      <rect x="3" y="4" width="18" height="16" rx="2.2" fill="none" />
      {/* Columns */}
      <path d="M9 4v16M15 4v16" fill="none" />
      {/* Cards */}
      <rect x="4.7"  y="6.2" width="2.7" height="3.7" rx="0.6" fill="none" />
      <rect x="10.6" y="8.2" width="2.8" height="5.9" rx="0.6" fill="none" />
      <rect x="16.5" y="10.3" width="2.8" height="3.7" rx="0.6" fill="none" />
      {/* Column labels */}
      <path d="M4.7 5.3h2.7M10.6 5.3h2.8M16.5 5.3h2.8" fill="none" />
    </svg>
  );
});

/** Lean Six Sigma (loop + 3×3 dot grid) */
export const IconLSS = forwardRef(function IconLSS(
  { size, strokeWidth, title = "Lean Six Sigma Tools", className, dotRadius = 0.9, ...rest },
  ref
) {
  const props = base({ size, strokeWidth, title, className, ...rest });
  return (
    <svg ref={ref} {...props}>
      {title ? <title>{title}</title> : null}
      {/* Smooth loop */}
      <circle cx="12" cy="12" r="8" fill="none" />
      {/* Arrowheads */}
      <path d="M7 6.9l1.05-2.6 2.55 1.1" fill="none" />
      <path d="M17 17.1l-1.05 2.6-2.55-1.1" fill="none" />
      {/* 3×3 dot grid (filled) */}
      {[
        [8,8],[12,8],[16,8],
        [8,12],[12,12],[16,12],
        [8,16],[12,16],[16,16],
      ].map(([cx,cy],i)=>(
        <circle key={i} cx={cx} cy={cy} r={dotRadius} fill="currentColor" stroke="none" />
      ))}
    </svg>
  );
});
