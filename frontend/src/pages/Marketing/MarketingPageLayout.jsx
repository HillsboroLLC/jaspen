import React, { useEffect } from 'react';
import { useLocation } from 'react-router-dom';
import JaspenNav from '../../homeSections/HomePage/JaspenNav';
import './MarketingPages.css';

export default function MarketingPageLayout({ pageClass = '', children }) {
  const location = useLocation();

  useEffect(() => {
    if (!location.hash) return;
    const id = location.hash.replace('#', '');
    const el = document.getElementById(id);
    if (el) {
      setTimeout(() => {
        el.scrollIntoView({ behavior: 'smooth', block: 'start' });
      }, 0);
    }
  }, [location.hash]);

  return (
    <div className="marketing-page">
      <JaspenNav />

      <main className={`marketing-main ${pageClass}`.trim()}>
        <div className="marketing-container marketing-content">
          {children}
        </div>
      </main>
    </div>
  );
}
