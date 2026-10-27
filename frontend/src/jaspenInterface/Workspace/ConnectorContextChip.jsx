import React from 'react';
import { FontAwesomeIcon } from '@fortawesome/react-fontawesome';
import { faCheck } from '@fortawesome/free-solid-svg-icons';

import { connectorContextState } from './connectorContextState';

export default function ConnectorContextChip({ source, connector, active = false, onToggle }) {
  const contextState = connectorContextState(connector, source);
  const isActive = contextState.selectable && active;

  return (
    <button
      type="button"
      className={`jas-connector-context-chip ${isActive ? 'active' : ''} ${contextState.state}`}
      onClick={contextState.selectable ? () => onToggle?.(source.id, source.label) : undefined}
      title={isActive ? `Remove ${source.label} context` : contextState.tooltip}
      disabled={!contextState.selectable}
      aria-disabled={!contextState.selectable}
    >
      <span className={`jas-connector-status-dot ${contextState.dot}`} aria-hidden="true" />
      {isActive && <FontAwesomeIcon icon={faCheck} />}
      {source.label}
    </button>
  );
}
