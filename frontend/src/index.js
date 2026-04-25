// path: src/index.js  (drop-in replacement)

import React from 'react';
import ReactDOM from 'react-dom/client';
import * as Sentry from '@sentry/react';
import { HelmetProvider } from 'react-helmet-async';
import './index.css';
import './styles/colors.css';
import App from './App';
import reportWebVitals from './reportWebVitals';
import { AuthProvider } from './shared/auth/AuthContext'; // keep auth here only
import './overrides.css';

const sentryDsn = process.env.REACT_APP_SENTRY_DSN || '';
if (sentryDsn) {
  const tracesSampleRate = Number(process.env.REACT_APP_SENTRY_TRACES_SAMPLE_RATE || '0');
  Sentry.init({
    dsn: sentryDsn,
    environment: process.env.REACT_APP_SENTRY_ENVIRONMENT || process.env.NODE_ENV,
    release:
      process.env.REACT_APP_SENTRY_RELEASE ||
      process.env.REACT_APP_VERCEL_GIT_COMMIT_SHA ||
      undefined,
    tracesSampleRate: Number.isFinite(tracesSampleRate) ? tracesSampleRate : 0,
    sendDefaultPii: false,
  });
}

const root = ReactDOM.createRoot(document.getElementById('root'));
root.render(
  <React.StrictMode>
    <HelmetProvider>
      <AuthProvider>
        <App /> {/* App.js already provides BrowserRouter + other Providers */}
      </AuthProvider>
    </HelmetProvider>
  </React.StrictMode>
);

reportWebVitals();
