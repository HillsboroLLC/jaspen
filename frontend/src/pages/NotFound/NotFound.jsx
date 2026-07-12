import React from 'react';
import { Link } from 'react-router-dom';
import PublicJaspenHeader from '../../homeSections/HomePage/PublicJaspenHeader';
import './NotFound.css';

export default function NotFoundPage() {
  return (
    <>
      <PublicJaspenHeader />
      <main className="not-found-page" role="main" aria-labelledby="not-found-title">
        <div className="not-found-card">
          <p className="not-found-code">404</p>
          <h1 id="not-found-title">Page not found</h1>
          <p className="not-found-copy">
            We couldn&apos;t find the page you were looking for.
          </p>
          <Link to="/" className="not-found-link">
            Back to home
          </Link>
        </div>
      </main>
    </>
  );
}
