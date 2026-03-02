// path: src/index.js  (drop-in replacement)

import React from 'react';
import ReactDOM from 'react-dom/client';
import './index.css';
import App from './App';
import reportWebVitals from './reportWebVitals';
import { AuthProvider } from './All/shared/auth/AuthContext'; // keep auth here only
import { SupabaseAuthProvider } from './All/shared/supabase/SupabaseAuthContext';
import './overrides.css';

const root = ReactDOM.createRoot(document.getElementById('root'));
root.render(
  <React.StrictMode>
    <AuthProvider>
      <SupabaseAuthProvider>
        <App /> {/* App.js already provides BrowserRouter + other Providers */}
      </SupabaseAuthProvider>
    </AuthProvider>
  </React.StrictMode>
);

reportWebVitals();
