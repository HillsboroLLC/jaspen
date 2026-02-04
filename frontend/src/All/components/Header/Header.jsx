import React, { useEffect, useRef, useState } from 'react';
import './Header.css';

export default function Header({ onFounderClick }) {
  const [openMobile, setOpenMobile] = useState(false);
  const [openAccount, setOpenAccount] = useState(false);

  const toggleMobile = () => setOpenMobile(o => !o);
  const closeMobile  = () => setOpenMobile(false);

  const accountRef = useRef(null);

  // Close the account popover on outside click or ESC
  useEffect(() => {
    function onDocClick(e) {
      if (!accountRef.current) return;
      if (!accountRef.current.contains(e.target)) setOpenAccount(false);
    }
    function onEsc(e) {
      if (e.key === 'Escape') setOpenAccount(false);
    }
    document.addEventListener('mousedown', onDocClick);
    document.addEventListener('keydown', onEsc);
    return () => {
      document.removeEventListener('mousedown', onDocClick);
      document.removeEventListener('keydown', onEsc);
    };
  }, []);

  return (
    <header className="header">
      <div className="container header-content">
        <a href="/" className="logo-text">SEKKI</a>

        {/* Hamburger (mobile only) */}
        <button
          className={`hamburger ${openMobile ? 'is-open' : ''}`}
          onClick={toggleMobile}
          aria-expanded={openMobile}
          aria-controls="site-mobile-nav"
          aria-label="Toggle navigation"
        >
          <span/><span/><span/>
        </button>

        {/* Desktop nav */}
        <nav className="desktop-nav" aria-label="Primary">
          <ul className="nav-list">
            <li><a href="/" className="nav-link">Home</a></li>
            <li><a href="#tools" className="nav-link">Tools</a></li>
            <li><a href="#pricing" className="nav-link">Pricing</a></li>
            <li><a href="#about" className="nav-link">About</a></li>
            <li><a href="#contact" className="nav-link">Contact</a></li>
          </ul>
        </nav>

        {/* Desktop actions */}
        <div className="header-actions desktop-actions">
          {/* Account trigger with popover */}
          <div className="account" ref={accountRef}>
            <button
              type="button"
              className="btn btn-ghost account-trigger"
              onClick={() => setOpenAccount(o => !o)}
              aria-haspopup="menu"
              aria-expanded={openAccount}
              aria-controls="account-menu"
            >
              Login / Sign Up
              <svg className="chev" width="14" height="14" viewBox="0 0 24 24" aria-hidden="true">
                <path d="M7 10l5 5 5-5" fill="none" stroke="currentColor" strokeWidth="2" />
              </svg>
            </button>

            <div
              id="account-menu"
              role="menu"
              className={`account-menu ${openAccount ? 'open' : ''}`}
            >
              <a role="menuitem" href="/login" className="account-item">Log in</a>
              <a role="menuitem" href="/sign-up" className="account-item">Create account</a>
            </div>
          </div>

          <button
            type="button"
            className="btn btn-primary"
            onClick={onFounderClick}
          >
            Get Founder Access
          </button>
        </div>
      </div>

      {/* Mobile slide-down panel */}
      <div id="site-mobile-nav" className={`mobile-nav ${openMobile ? 'show' : ''}`}>
        <ul className="mobile-nav-list" onClick={closeMobile}>
          <li><a href="/" className="nav-link">Home</a></li>
          <li><a href="#tools" className="nav-link">Tools</a></li>
          <li><a href="#pricing" className="nav-link">Pricing</a></li>
          <li><a href="#about" className="nav-link">About</a></li>
          <li><a href="#contact" className="nav-link">Contact</a></li>
        </ul>

        {/* Mobile actions: show Login & Sign Up side-by-side, Founder full-width */}
        <div className="mobile-actions">
          <a href="/login" className="btn btn-secondary" onClick={closeMobile}>Login</a>
          <a href="/sign-up" className="btn btn-outline" onClick={closeMobile}>Sign Up</a>
          <button
            type="button"
            className="btn btn-primary full"
            onClick={() => { closeMobile(); onFounderClick?.(); }}
          >
            Get Founder Access
          </button>
        </div>
      </div>
    </header>
  );
}
