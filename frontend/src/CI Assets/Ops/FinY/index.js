// ==========================================
// File: src/Ops/FinY/index.jsx (this file)
// Why: Ensure FinY runs inside AdminProvider (and Router).
// ==========================================
import React from 'react';
import ReactDOM from 'react-dom/client';
import { AdminProvider } from '../context';            // why: use the barrel to avoid duplicate contexts
import { BrowserRouter } from 'react-router-dom';      // why: ResourcePageWrapper likely needs routing
import FinY from './FinY';

// Global Font Awesome (ok to keep if not already global)
import '@fortawesome/fontawesome-free/css/all.min.css';

// ❌ Remove this line if FinY already imports its CSS module internally:
// import './FinY.module.css';

const root = ReactDOM.createRoot(document.getElementById('root'));
root.render(
  <React.StrictMode>
    <AdminProvider>               {/* why: provides adminSettings to useAdminSettings() */}
      <BrowserRouter>             {/* why: provides router context to children if they use it */}
        <FinY />
      </BrowserRouter>
    </AdminProvider>
  </React.StrictMode>
);

export default FinY; // optional; safe to remove if not imported elsewhere
