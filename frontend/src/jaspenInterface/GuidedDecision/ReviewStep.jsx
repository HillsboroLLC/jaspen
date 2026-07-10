import React from 'react';

// Controlled review surface. The wizard owns `value`, `editing`, and the
// Edit / Use This actions in the footer so the final (possibly edited) text
// is what flows to the composer.
export default function ReviewStep({ value, editing, onChange }) {
  return (
    <div className="gd-step">
      <h2 className="gd-step-title">Here&apos;s what Jaspen understands</h2>

      {editing ? (
        <textarea
          className="gd-textarea gd-review-edit"
          rows={14}
          value={value}
          onChange={(e) => onChange(e.target.value)}
          aria-label="Edit the generated context"
        />
      ) : (
        <pre className="gd-review-preview">{value}</pre>
      )}
    </div>
  );
}
