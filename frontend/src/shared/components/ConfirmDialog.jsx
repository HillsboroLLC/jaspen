import React, { useEffect, useId, useRef } from 'react';
import './ConfirmDialog.css';

export default function ConfirmDialog({
  isOpen = false,
  title = 'Confirm action',
  message = '',
  confirmLabel = 'Confirm',
  cancelLabel = 'Cancel',
  confirmVariant = 'danger',
  pending = false,
  onConfirm,
  onCancel,
  // Optional "don't ask me again" inline checkbox. When provided, renders a
  // checkbox below the message; callers control checked state + handler.
  checkboxLabel = null,
  checkboxChecked = false,
  onCheckboxChange = null,
}) {
  const titleId = useId();
  const descriptionId = useId();
  const confirmButtonRef = useRef(null);

  useEffect(() => {
    if (!isOpen) return undefined;
    const onKeyDown = (event) => {
      if (event.key === 'Escape') {
        event.preventDefault();
        if (!pending) onCancel?.();
      }
    };
    window.addEventListener('keydown', onKeyDown);
    return () => window.removeEventListener('keydown', onKeyDown);
  }, [isOpen, onCancel, pending]);

  useEffect(() => {
    if (!isOpen) return;
    confirmButtonRef.current?.focus();
  }, [isOpen]);

  if (!isOpen) return null;

  return (
    <div
      className="jas-confirm-overlay"
      onClick={(event) => {
        if (event.target === event.currentTarget && !pending) onCancel?.();
      }}
    >
      <div
        className="jas-confirm-dialog"
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        aria-describedby={descriptionId}
      >
        <h3 id={titleId} className="jas-confirm-title">{title}</h3>
        <p id={descriptionId} className="jas-confirm-message">{message}</p>
        {checkboxLabel && (
          <label
            style={{
              display: 'flex', alignItems: 'center', gap: 8,
              marginTop: 12, fontSize: 13, color: '#475569',
              cursor: 'pointer', userSelect: 'none',
            }}
          >
            <input
              type="checkbox"
              checked={Boolean(checkboxChecked)}
              onChange={(e) => onCheckboxChange?.(e.target.checked)}
              style={{ cursor: 'pointer' }}
            />
            {checkboxLabel}
          </label>
        )}
        <div className="jas-confirm-actions">
          <button
            type="button"
            className="jas-confirm-btn jas-confirm-btn-cancel"
            onClick={onCancel}
            disabled={pending}
            aria-disabled={pending}
          >
            {cancelLabel}
          </button>
          <button
            ref={confirmButtonRef}
            type="button"
            className={`jas-confirm-btn ${confirmVariant === 'danger' ? 'jas-confirm-btn-danger' : 'jas-confirm-btn-primary'}`}
            onClick={onConfirm}
            disabled={pending}
            aria-disabled={pending}
          >
            {pending ? 'Working...' : confirmLabel}
          </button>
        </div>
      </div>
    </div>
  );
}
