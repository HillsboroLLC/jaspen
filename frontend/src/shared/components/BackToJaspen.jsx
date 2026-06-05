import React from 'react';
import { useNavigate } from 'react-router-dom';
import { FontAwesomeIcon } from '@fortawesome/react-fontawesome';
import { faArrowLeft } from '@fortawesome/free-solid-svg-icons';

// Single, consistent "Back to Jaspen" control used on every non-primary page
// (Scores, Team, Account, Admin, Execution plan, …). Matches the subtle left-arrow
// link from the Workspace topbar so there is exactly ONE back-to-Jaspen pattern.
//
// Usage:
//   <BackToJaspen />                                  -> navigates to /new
//   <BackToJaspen to="/new?sid=abc" />                -> custom destination
//   <BackToJaspen onClick={() => guard(() => nav())} /> -> custom handler (e.g. unsaved-changes guard)
export default function BackToJaspen({ to = '/new', onClick, label = 'Back to Jaspen', style }) {
  const navigate = useNavigate();
  const handle = (event) => {
    if (onClick) {
      onClick(event);
      return;
    }
    navigate(to);
  };
  return (
    <button
      type="button"
      onClick={handle}
      style={{
        display: 'inline-flex',
        alignItems: 'center',
        gap: 6,
        background: 'none',
        border: 'none',
        padding: 0,
        cursor: 'pointer',
        color: '#475569',
        fontSize: 13,
        fontFamily: 'inherit',
        ...(style || {}),
      }}
    >
      <FontAwesomeIcon icon={faArrowLeft} />
      {label}
    </button>
  );
}
