import React from 'react';

export default function JaspenAssistantTab({
  onClick,
  expanded = false,
  controlsId,
  label = 'Jaspen',
  top,
  className = '',
}) {
  const normalizedTop = typeof top === 'number' ? `${top}px` : top;
  const style = normalizedTop ? { top: normalizedTop } : undefined;
  const classes = ['jas-sidebar-tab', 'jas-tab-assistant', className].filter(Boolean).join(' ');

  return (
    <button
      type="button"
      className={classes}
      style={style}
      onClick={onClick}
      aria-label={label}
      title={label}
      aria-expanded={expanded}
      aria-controls={controlsId}
    >
      <span className="jas-tab-label">{label}</span>
    </button>
  );
}
