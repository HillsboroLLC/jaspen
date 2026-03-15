import React, { createPortal, useCallback, useEffect, useRef, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { FontAwesomeIcon } from '@fortawesome/react-fontawesome';
import {
  faChevronDown,
  faChevronUp,
  faDownload,
} from '@fortawesome/free-solid-svg-icons';

import { useAuth } from '../../../shared/auth/AuthContext';

function getInitials(name) {
  if (!name) return 'U';
  const parts = String(name).trim().split(/\s+/);
  if (parts.length >= 2) return `${parts[0][0]}${parts[1][0]}`.toUpperCase();
  return String(name).substring(0, 2).toUpperCase();
}

function openExternal(path) {
  window.open(path, '_blank', 'noopener,noreferrer');
}

export default function SidebarIdentityFooter({
  displayName,
  planLabel,
  onOpenDisplayNameEditor,
  onOpenBilling,
  onLogout,
  onClose,
}) {
  const navigate = useNavigate();
  const {
    user,
    orgDisplayName,
    isPlatformAdmin,
    isEnterpriseAdmin,
    canAccessOrgSettings,
  } = useAuth();

  const [accountQuickMenuOpen, setAccountQuickMenuOpen] = useState(false);
  const [knowledgeMenuOpen, setKnowledgeMenuOpen] = useState(false);
  const [knowledgeMenuStyle, setKnowledgeMenuStyle] = useState(null);
  const knowledgeSubmenuWrapRef = useRef(null);
  const knowledgeSubmenuRef = useRef(null);
  const knowledgeMenuCloseTimerRef = useRef(null);

  const userEmail = user?.email || 'user@example.com';
  const userName = displayName || user?.name || userEmail.split('@')[0] || 'User';
  const currentPlanLabel = String(planLabel || '').trim() || 'Individual';
  const userInitials = getInitials(userName);

  const clearKnowledgeMenuCloseTimer = useCallback(() => {
    if (knowledgeMenuCloseTimerRef.current) {
      clearTimeout(knowledgeMenuCloseTimerRef.current);
      knowledgeMenuCloseTimerRef.current = null;
    }
  }, []);

  const scheduleKnowledgeMenuClose = useCallback(() => {
    clearKnowledgeMenuCloseTimer();
    knowledgeMenuCloseTimerRef.current = setTimeout(() => {
      setKnowledgeMenuOpen(false);
    }, 180);
  }, [clearKnowledgeMenuCloseTimer]);

  useEffect(() => () => {
    clearKnowledgeMenuCloseTimer();
  }, [clearKnowledgeMenuCloseTimer]);

  useEffect(() => {
    if (!accountQuickMenuOpen) return;
    const onPointerDown = (event) => {
      if (!(event.target instanceof Element)) return;
      if (event.target.closest('.jas-ud-submenu-portal')) return;
      if (!event.target.closest('.jas-ud-footer')) {
        setAccountQuickMenuOpen(false);
        setKnowledgeMenuOpen(false);
        clearKnowledgeMenuCloseTimer();
      }
    };
    document.addEventListener('mousedown', onPointerDown);
    return () => document.removeEventListener('mousedown', onPointerDown);
  }, [accountQuickMenuOpen, clearKnowledgeMenuCloseTimer]);

  const updateKnowledgeMenuPosition = useCallback(() => {
    if (!knowledgeSubmenuWrapRef.current) return;
    const rect = knowledgeSubmenuWrapRef.current.getBoundingClientRect();
    const menuWidth = 260;
    const viewportPadding = 8;
    const estimatedHeight = 360;
    const left = Math.min(
      Math.max(viewportPadding, rect.right + 4),
      window.innerWidth - menuWidth - viewportPadding
    );
    const top = Math.min(
      Math.max(viewportPadding, rect.top + 12),
      Math.max(viewportPadding, window.innerHeight - estimatedHeight - viewportPadding)
    );
    const maxHeight = Math.max(180, window.innerHeight - top - viewportPadding);
    setKnowledgeMenuStyle({
      left: `${left}px`,
      top: `${top}px`,
      maxHeight: `${maxHeight}px`,
    });
  }, []);

  useEffect(() => {
    if (!knowledgeMenuOpen || !accountQuickMenuOpen) {
      setKnowledgeMenuStyle(null);
      return;
    }
    updateKnowledgeMenuPosition();
    const onReposition = () => updateKnowledgeMenuPosition();
    window.addEventListener('resize', onReposition);
    window.addEventListener('scroll', onReposition, true);
    return () => {
      window.removeEventListener('resize', onReposition);
      window.removeEventListener('scroll', onReposition, true);
    };
  }, [knowledgeMenuOpen, accountQuickMenuOpen, updateKnowledgeMenuPosition]);

  const closeMenus = useCallback(() => {
    setAccountQuickMenuOpen(false);
    setKnowledgeMenuOpen(false);
    clearKnowledgeMenuCloseTimer();
  }, [clearKnowledgeMenuCloseTimer]);

  const navigateInternal = useCallback((path) => {
    navigate(path);
    closeMenus();
  }, [navigate, closeMenus]);

  return (
    <div className="jas-ud-footer">
      <button
        type="button"
        className="jas-ud-footer-profile"
        onClick={() => {
          setAccountQuickMenuOpen((prev) => !prev);
          setKnowledgeMenuOpen(false);
        }}
      >
        <div className="jas-ud-footer-avatar">{userInitials}</div>
        <div className="jas-ud-footer-meta">
          <span className="jas-ud-footer-name">{userName}</span>
          <span className="jas-ud-footer-org">{orgDisplayName}</span>
          <span className="jas-ud-footer-plan">{currentPlanLabel}</span>
        </div>
      </button>
      <div className="jas-ud-footer-actions">
        <button
          type="button"
          className="jas-ud-footer-icon"
          title="Get apps and extensions"
          aria-label="Get apps and extensions"
          onClick={() => navigateInternal('/connectors-manage')}
        >
          <FontAwesomeIcon icon={faDownload} />
        </button>
        <button
          type="button"
          className="jas-ud-footer-icon"
          title="Account menu"
          aria-label="Account menu"
          onClick={() => {
            setAccountQuickMenuOpen((prev) => !prev);
            setKnowledgeMenuOpen(false);
          }}
        >
          <FontAwesomeIcon icon={accountQuickMenuOpen ? faChevronUp : faChevronDown} />
        </button>
      </div>
      {accountQuickMenuOpen && (
        <div className="jas-ud-footer-menu">
          <div className="jas-ud-footer-email">{userEmail}</div>
          <button
            type="button"
            onClick={() => {
              closeMenus();
              onOpenDisplayNameEditor?.();
            }}
          >
            Edit display name
          </button>
          <button
            type="button"
            onClick={() => {
              closeMenus();
              onOpenBilling?.();
            }}
          >
            Upgrade plan
          </button>
          {isPlatformAdmin && (
            <button type="button" onClick={() => navigateInternal('/jaspen-admin')}>
              Jaspen Admin
            </button>
          )}
          <button type="button" onClick={() => { openExternal('/login'); closeMenus(); }}>
            Gift Jaspen
          </button>
          {canAccessOrgSettings && (
            <button type="button" onClick={() => navigateInternal('/team')}>
              Organization
            </button>
          )}
          {isEnterpriseAdmin && (
            <button type="button" onClick={() => navigateInternal('/enterprise-admin')}>
              Enterprise Admin
            </button>
          )}
          <div
            className="jas-ud-submenu-wrap"
            ref={knowledgeSubmenuWrapRef}
            onMouseEnter={() => {
              clearKnowledgeMenuCloseTimer();
              setKnowledgeMenuOpen(true);
            }}
            onMouseLeave={(event) => {
              const nextTarget = event.relatedTarget;
              if (nextTarget instanceof Node && knowledgeSubmenuRef.current?.contains(nextTarget)) return;
              scheduleKnowledgeMenuClose();
            }}
          >
            <button
              type="button"
              className="jas-ud-submenu-trigger"
              onClick={(e) => {
                e.preventDefault();
                e.stopPropagation();
                setKnowledgeMenuOpen((prev) => !prev);
              }}
            >
              <span>Knowledge</span>
              <span className="jas-ud-submenu-caret">›</span>
            </button>
            {knowledgeMenuOpen && accountQuickMenuOpen && knowledgeMenuStyle && createPortal(
              <div
                className="jas-ud-submenu jas-ud-submenu-portal"
                ref={knowledgeSubmenuRef}
                style={knowledgeMenuStyle}
                onMouseEnter={() => {
                  clearKnowledgeMenuCloseTimer();
                  setKnowledgeMenuOpen(true);
                }}
                onMouseLeave={(event) => {
                  const nextTarget = event.relatedTarget;
                  if (nextTarget instanceof Node && knowledgeSubmenuWrapRef.current?.contains(nextTarget)) return;
                  scheduleKnowledgeMenuClose();
                }}
              >
                <button type="button" onClick={() => navigateInternal('/knowledge')}>Tutorials</button>
                <button type="button" onClick={() => { openExternal('/pages/api'); closeMenus(); }}>API console</button>
                <button type="button" onClick={() => { openExternal('/#about'); closeMenus(); }}>About Jaspen</button>
                <button type="button" onClick={() => { openExternal('/pages/terms'); closeMenus(); }}>Usage policy</button>
                <button type="button" onClick={() => { openExternal('/pages/privacy'); closeMenus(); }}>Privacy policy</button>
                <button type="button" onClick={() => { openExternal('/pages/privacy#choices'); closeMenus(); }}>Your privacy choices</button>
              </div>,
              document.body
            )}
          </div>
          <button type="button" onClick={() => { openExternal('/pages/support'); closeMenus(); }}>
            Get help
          </button>
          <button
            type="button"
            onClick={() => {
              closeMenus();
              onClose?.();
              onLogout?.();
            }}
            className="danger"
          >
            Log out
          </button>
        </div>
      )}
    </div>
  );
}
