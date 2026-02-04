// path: src/index.js  (drop-in replacement)

import React from 'react';
import ReactDOM from 'react-dom/client';
import './index.css';
import App from './App';
import reportWebVitals from './reportWebVitals';
import { AuthProvider } from './All/shared/auth/AuthContext'; // keep auth here only
import './overrides.css';

const root = ReactDOM.createRoot(document.getElementById('root'));
root.render(
  <React.StrictMode>
    <AuthProvider>
      <App /> {/* App.js already provides BrowserRouter + other Providers */}
    </AuthProvider>
  </React.StrictMode>
);

reportWebVitals();
