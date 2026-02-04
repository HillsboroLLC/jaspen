// ============================================================================
// File: src/components/Toast.jsx
// Purpose: Simple toast notification for chat action feedback
// ============================================================================

import React, { useEffect, useState } from 'react';

export function useToast() {
  const [toasts, setToasts] = useState([]);

  const showToast = (message, type = 'info') => {
    const id = Date.now();
    setToasts(prev => [...prev, { id, message, type }]);
    
    // Auto-dismiss after 3 seconds
    setTimeout(() => {
      setToasts(prev => prev.filter(t => t.id !== id));
    }, 3000);
  };

  const dismissToast = (id) => {
    setToasts(prev => prev.filter(t => t.id !== id));
  };

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
    }}>
      {toasts.map(toast => (
        <Toast key={toast.id} {...toast} onDismiss={() => onDismiss(toast.id)} />
      ))}
    </div>
  );
}

function Toast({ message, type, onDismiss }) {
  const [isExiting, setIsExiting] = useState(false);

  useEffect(() => {
    const timer = setTimeout(() => {
      setIsExiting(true);
      setTimeout(onDismiss, 200); // Wait for exit animation
    }, 2800);
    return () => clearTimeout(timer);
  }, [onDismiss]);

  const bgColors = {
    success: '#10b981',
    error: '#ef4444',
    info: '#161f3b',
    warning: '#f59e0b'
  };

  return (
    <div
      onClick={onDismiss}
      style={{
        background: bgColors[type] || bgColors.info,
        color: '#fff',
        padding: '12px 16px',
        borderRadius: '8px',
        boxShadow: '0 4px 12px rgba(0,0,0,0.15)',
        cursor: 'pointer',
        fontSize: '14px',
        fontWeight: '500',
        opacity: isExiting ? 0 : 1,
        transform: isExiting ? 'translateX(20px)' : 'translateX(0)',
        transition: 'all 0.2s ease-out',
        display: 'flex',
        alignItems: 'center',
        gap: '8px'
      }}
    >
      <span style={{ flex: 1 }}>{message}</span>
      <span style={{ opacity: 0.7, fontSize: '12px' }}>×</span>
    </div>
  );
}
