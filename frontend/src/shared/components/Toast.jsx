// ============================================================================
// File: src/components/Toast.jsx
// Purpose: Simple toast notification for chat action feedback
// ============================================================================

import React, { useCallback, useEffect, useRef, useState } from 'react';

const MAX_VISIBLE_TOASTS = 4;
const DEFAULT_TOAST_DURATION_MS = 3000;

export function useToast() {
  const [toasts, setToasts] = useState([]);
  const queuedToastsRef = useRef([]);
  const timeoutMapRef = useRef(new Map());
  const idCounterRef = useRef(0);

  const scheduleDismiss = useCallback((toast) => {
    const duration = Number.isFinite(toast.durationMs) ? toast.durationMs : DEFAULT_TOAST_DURATION_MS;
    if (duration <= 0) return;
    const timeoutId = window.setTimeout(() => {
      setToasts((prev) => {
        const nextVisible = prev.filter((item) => item.id !== toast.id);
        if (nextVisible.length >= MAX_VISIBLE_TOASTS) return nextVisible;
        const queued = queuedToastsRef.current.shift();
        if (!queued) return nextVisible;
        scheduleDismiss(queued);
        return [...nextVisible, queued];
      });
      timeoutMapRef.current.delete(toast.id);
    }, duration);
    timeoutMapRef.current.set(toast.id, timeoutId);
  }, []);

  const showToast = useCallback((message, type = 'info', options = {}) => {
    const nextId = Date.now() + idCounterRef.current;
    idCounterRef.current += 1;
    const nextToast = {
      id: nextId,
      message,
      type,
      actionLabel: options?.actionLabel ? String(options.actionLabel) : '',
      onAction: typeof options?.onAction === 'function' ? options.onAction : null,
      durationMs: Number(options?.durationMs),
      dismissOnAction: options?.dismissOnAction !== false,
    };

    setToasts((prev) => {
      if (prev.length >= MAX_VISIBLE_TOASTS) {
        queuedToastsRef.current.push(nextToast);
        return prev;
      }
      scheduleDismiss(nextToast);
      return [...prev, nextToast];
    });
  }, [scheduleDismiss]);

  const dismissToast = useCallback((id) => {
    const activeTimeout = timeoutMapRef.current.get(id);
    if (activeTimeout) {
      window.clearTimeout(activeTimeout);
      timeoutMapRef.current.delete(id);
    }
    setToasts((prev) => {
      const nextVisible = prev.filter((item) => item.id !== id);
      if (nextVisible.length >= MAX_VISIBLE_TOASTS) return nextVisible;
      const queued = queuedToastsRef.current.shift();
      if (!queued) return nextVisible;
      scheduleDismiss(queued);
      return [...nextVisible, queued];
    });
  }, [scheduleDismiss]);

  useEffect(() => {
    const timeoutMap = timeoutMapRef.current;
    const queuedToasts = queuedToastsRef;
    return () => {
      timeoutMap.forEach((timeoutId) => window.clearTimeout(timeoutId));
      timeoutMap.clear();
      queuedToasts.current = [];
    };
  }, []);

  return { toasts, showToast, dismissToast };
}

export function ToastContainer({ toasts, onDismiss }) {
  if (!toasts || toasts.length === 0) return null;

  return (
    <div style={{
      position: 'fixed',
      bottom: '24px',
      right: '24px',
      zIndex: 9999,
      display: 'flex',
      flexDirection: 'column',
      gap: '8px',
      maxWidth: '400px'
    }}
      role="status"
      aria-live="polite"
      aria-atomic="false"
      aria-label="Notifications"
    >
      {toasts.map(toast => (
        <Toast key={toast.id} {...toast} onDismiss={() => onDismiss(toast.id)} />
      ))}
    </div>
  );
}

function Toast({ message, type, onDismiss, actionLabel = '', onAction = null, dismissOnAction = true }) {
  const bgColors = {
    success: 'var(--color-status-success)',
    error: 'var(--color-status-danger)',
    info: 'var(--color-brand-navy)',
    warning: 'var(--color-status-warning)'
  };

  return (
    <div
      style={{
        background: bgColors[type] || bgColors.info,
        color: 'var(--color-text-inverse)',
        padding: '12px 16px',
        borderRadius: '8px',
        boxShadow: '0 4px 12px rgba(0,0,0,0.15)',
        cursor: 'default',
        fontSize: '14px',
        fontWeight: '500',
        display: 'flex',
        alignItems: 'center',
        gap: '8px'
      }}
    >
      <span style={{ flex: 1 }}>{message}</span>
      {actionLabel && onAction && (
        <button
          type="button"
          onClick={() => {
            onAction();
            if (dismissOnAction) onDismiss();
          }}
          style={{
            border: '1px solid rgba(255,255,255,0.5)',
            background: 'transparent',
            color: 'var(--color-text-inverse)',
            borderRadius: '999px',
            padding: '4px 10px',
            fontSize: '12px',
            fontWeight: '700',
            cursor: 'pointer'
          }}
        >
          {actionLabel}
        </button>
      )}
      <button
        type="button"
        onClick={onDismiss}
        aria-label="Dismiss notification"
        style={{
          opacity: 0.75,
          fontSize: '14px',
          border: 'none',
          background: 'transparent',
          color: 'var(--color-text-inverse)',
          cursor: 'pointer',
          padding: 0,
          lineHeight: 1
        }}
      >
        ×
      </button>
    </div>
  );
}
