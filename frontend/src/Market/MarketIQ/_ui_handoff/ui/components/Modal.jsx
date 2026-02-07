/**
 * Modal.jsx — Presentational modal overlay component
 *
 * Controlled externally via `isOpen` and `onClose`.
 *
 * Usage:
 *   <Modal isOpen={showEdit} onClose={() => setShowEdit(false)} title="Edit Analysis" subtitle="Session: abc123">
 *     <Input label="Project name" defaultValue="AI Agent Project" />
 *     <div style={{ display: 'flex', gap: '10px', justifyContent: 'flex-end' }}>
 *       <Button variant="outline" onClick={() => setShowEdit(false)}>Cancel</Button>
 *       <Button variant="primary" onClick={handleSave}>Save changes</Button>
 *     </div>
 *   </Modal>
 */
import React from 'react';

const overlayStyle = {
  position: 'fixed',
  top: 0,
  left: 0,
  right: 0,
  bottom: 0,
  background: 'rgba(22, 31, 59, 0.35)',
  zIndex: 500,
  display: 'flex',
  alignItems: 'center',
  justifyContent: 'center',
};

const modalStyle = {
  background: 'var(--miq-white)',
  borderRadius: 'var(--miq-radius-md)',
  width: '520px',
  maxWidth: '90vw',
  boxShadow: 'var(--miq-shadow-xl)',
};

const headerStyle = {
  padding: '20px 24px 12px',
  display: 'flex',
  alignItems: 'flex-start',
  justifyContent: 'space-between',
};

const titleStyle = {
  fontSize: 'var(--miq-text-xl)',
  fontWeight: 700,
  color: 'var(--miq-navy)',
};

const subtitleStyle = {
  fontSize: 'var(--miq-text-sm)',
  color: 'var(--miq-gray-500)',
  marginTop: '2px',
};

const closeStyle = {
  background: 'none',
  border: 'none',
  color: 'var(--miq-gray-500)',
  cursor: 'pointer',
  fontSize: '1rem',
  padding: '4px',
};

const bodyStyle = {
  padding: '8px 24px 20px',
};

const footerStyle = {
  padding: '12px 24px 20px',
  display: 'flex',
  gap: '10px',
  justifyContent: 'flex-end',
  borderTop: '1px solid var(--miq-border)',
};

export default function Modal({
  isOpen = false,
  onClose,
  title,
  subtitle,
  children,
  footer,
  className = '',
  ...props
}) {
  if (!isOpen) return null;

  return (
    <div
      className={`miq-modal-overlay ${className}`}
      style={overlayStyle}
      onClick={(e) => {
        if (e.target === e.currentTarget) onClose?.();
      }}
      {...props}
    >
      <div className="miq-modal" style={modalStyle}>
        {/* Header */}
        <div style={headerStyle}>
          <div>
            {title && <h3 style={titleStyle}>{title}</h3>}
            {subtitle && <div style={subtitleStyle}>{subtitle}</div>}
          </div>
          <button style={closeStyle} onClick={onClose}>
            <i className="fa-solid fa-xmark" />
          </button>
        </div>

        {/* Body */}
        <div style={bodyStyle}>{children}</div>

        {/* Footer (optional — pass buttons as `footer` prop) */}
        {footer && <div style={footerStyle}>{footer}</div>}
      </div>
    </div>
  );
}
