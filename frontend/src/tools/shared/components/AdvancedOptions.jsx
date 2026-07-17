import React, { useState } from 'react';
import { ChevronRight } from 'lucide-react';

// Collapsible "Advanced options" disclosure for less-common inputs (e.g. PMI
// removal point). Keeps the default path light while remaining fully accessible.
export default function AdvancedOptions({ label = 'Advanced options', children, defaultOpen = false }) {
  const [open, setOpen] = useState(defaultOpen);
  return (
    <div className="tool-disclosure" data-open={open ? 'true' : 'false'}>
      <button
        type="button"
        className="tool-disclosure-btn"
        aria-expanded={open}
        onClick={() => setOpen((v) => !v)}
      >
        <ChevronRight size={18} strokeWidth={2.25} aria-hidden="true" />
        {label}
      </button>
      {open ? <div className="tool-disclosure-body">{children}</div> : null}
    </div>
  );
}
