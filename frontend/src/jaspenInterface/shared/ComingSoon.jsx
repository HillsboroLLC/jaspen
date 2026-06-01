// =============================================================================
// ComingSoon.jsx
// Lightweight placeholder shown in place of pages that are gated behind a
// "Coming soon" flag for launch. It still renders the shared AppMenu so users
// can navigate away, and it preserves the plan-based access gating applied by
// the route wrappers (ProtectedRoute / RequireDashboardAccess) — this component
// only changes what an *entitled* user sees, never who is allowed in.
// =============================================================================

import React from 'react';
import { useNavigate } from 'react-router-dom';
import { FontAwesomeIcon } from '@fortawesome/react-fontawesome';
import { faWandMagicSparkles, faArrowRight } from '@fortawesome/free-solid-svg-icons';
import AppMenu from './AppMenu';

const COLOR = {
  navy: '#161f3b',
  ink: '#5a6585',
  mute: '#8a93ad',
  line: '#e4e8f0',
  bg: '#f7f8fa',
  rose: '#a0036c',
  roseTint: '#fbeaf3',
  roseLine: '#f1cfe1',
};

export default function ComingSoon({ title = 'This page', blurb }) {
  const navigate = useNavigate();
  const message =
    blurb ||
    `${title} is getting a refresh and will be available shortly. In the meantime, start a new project and Jaspen will guide you through scoring, trade-offs, and your execution plan.`;

  return (
    <div style={{ minHeight: '100vh', background: COLOR.bg }}>
      <AppMenu />
      <div
        style={{
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          minHeight: '100vh',
          padding: '48px 24px',
          boxSizing: 'border-box',
        }}
      >
        <div
          style={{
            maxWidth: 520,
            width: '100%',
            background: '#fff',
            border: `1px solid ${COLOR.line}`,
            borderRadius: 18,
            padding: '40px 36px',
            textAlign: 'center',
            boxShadow: '0 1px 2px rgba(22,31,59,0.04)',
          }}
        >
          <div
            style={{
              display: 'inline-flex',
              alignItems: 'center',
              justifyContent: 'center',
              width: 56,
              height: 56,
              borderRadius: 14,
              background: COLOR.roseTint,
              border: `1px solid ${COLOR.roseLine}`,
              marginBottom: 20,
            }}
          >
            <FontAwesomeIcon icon={faWandMagicSparkles} style={{ fontSize: 22, color: COLOR.rose }} />
          </div>

          <div
            style={{
              fontFamily: 'JetBrains Mono, monospace',
              fontSize: 11,
              letterSpacing: '0.14em',
              textTransform: 'uppercase',
              color: COLOR.rose,
              fontWeight: 600,
              marginBottom: 10,
            }}
          >
            Coming soon
          </div>

          <h1
            style={{
              fontSize: 26,
              fontWeight: 600,
              color: COLOR.navy,
              letterSpacing: '-0.02em',
              margin: '0 0 12px',
            }}
          >
            {title}
          </h1>

          <p style={{ fontSize: 14.5, lineHeight: 1.6, color: COLOR.ink, margin: '0 0 26px' }}>
            {message}
          </p>

          <button
            type="button"
            onClick={() => navigate('/new')}
            style={{
              display: 'inline-flex',
              alignItems: 'center',
              gap: 9,
              padding: '11px 20px',
              borderRadius: 10,
              border: 'none',
              background: COLOR.navy,
              color: '#fff',
              fontSize: 14,
              fontWeight: 600,
              cursor: 'pointer',
            }}
          >
            Start a new project
            <FontAwesomeIcon icon={faArrowRight} style={{ fontSize: 12 }} />
          </button>
        </div>
      </div>
    </div>
  );
}
