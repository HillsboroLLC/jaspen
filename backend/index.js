// backend/index.js
require('dotenv').config();
const express = require('express');

const app = express();

// Trust NGINX for TLS/CORS; only parse JSON here.
app.use(express.json());

// health check
app.get('/health', (_req, res) => {
  res.status(200).json({ ok: true, service: 'sekki-node', ts: Date.now() });
});

// health alias for cases where /api-node prefix isn't stripped
app.get('/api-node/health', (_req, res) => {
  res.status(200).json({ ok: true, service: 'sekki-node', ts: Date.now() });
});


// --- CORS (allow sekki.io frontends to call api.sekki.io) ---
const ALLOWED_ORIGINS = [
  'https://sekki.io',
  'https://www.sekki.io',
  'http://localhost:3000',
];

app.use((req, res, next) => {
  const origin = req.headers.origin;
  if (origin && ALLOWED_ORIGINS.includes(origin)) {
    res.header('Access-Control-Allow-Origin', origin);
    res.header('Vary', 'Origin');
  }
  res.header('Access-Control-Allow-Credentials', 'true');
  res.header('Access-Control-Allow-Headers', 'Content-Type, Authorization');
  res.header('Access-Control-Allow-Methods', 'GET,POST,PUT,PATCH,DELETE,OPTIONS');
  if (req.method === 'OPTIONS') return res.sendStatus(204);
  next();
});

// --- Simple request logger (concise) ---
app.use((req, res, next) => {
  console.log(`${new Date().toISOString()} ${req.method} ${req.originalUrl}`);
  next();
});

// --- Health check (for uptime probes) ---
app.get('/api/health', (req, res) => {
  res.json({ ok: true, service: 'sekki-backend', ts: Date.now() });
});

/**
 * ACCOUNT TAB ENDPOINTS (stubs)
 * These match the three buttons:
 * - Invite User        -> POST /api/account/invite
 * - Manage Plan        -> POST /api/account/plan
 * - View Seat Usage    -> GET  /api/account/usage
 */

// Invite User (stub) — expects { email, role }
app.post('/api/account/invite', (req, res) => {
  const { email, role } = req.body || {};
  if (!email) return res.status(400).json({ ok: false, error: 'email is required' });

  // TODO: insert invite logic (e.g., create token, send mail, persist)
  return res.status(200).json({
    ok: true,
    message: 'Invite created (stub)',
    invite: {
      email,
      role: role || 'viewer',
      invitedAt: new Date().toISOString(),
    },
  });
});

// Manage Plan (stub) — expects { action, plan }
app.post('/api/account/plan', (req, res) => {
  const { action, plan } = req.body || {};
  if (!action) return res.status(400).json({ ok: false, error: 'action is required' });

  // TODO: call billing provider / persist choice
  return res.status(200).json({
    ok: true,
    message: 'Plan action accepted (stub)',
    action,
    plan: plan || 'current',
    processedAt: new Date().toISOString(),
  });
});

// Create Stripe checkout session (demo stub)
app.post('/billing/checkout-session', (req, res) => {
  const { plan } = req.body || {};

  // Normalize & validate
  const key = String(plan || '').toLowerCase();

  // Map plan -> URL (stub for now)
  const PLAN_URLS = {
    standard:   'https://sekki.io/pricing?checkout=standard',
    premium:    'https://sekki.io/pricing?checkout=premium',
    enterprise: 'https://sekki.io/pricing?checkout=enterprise',
  };

  const url = PLAN_URLS[key];
  if (!url) {
    return res
      .status(400)
      .json({ ok: false, error: `unknown plan '${plan}'. Use standard | premium | enterprise` });
  }



app.post('/billing/portal-session', (req, res) => {
  try {
    return res.json({ ok: true, url: 'https://sekki.io/billing-portal' });
  } catch (err) {
    console.error('portal-session error:', err);
    return res.status(500).json({ ok: false, error: 'Portal session failed' });
  }
});


  // In real flow this would be a Stripe Checkout URL
  return res.status(200).json({ ok: true, url });
});

// Also accept the stripped path when NGINX removes /api-node
app.post('/billing/portal-session', (_req, res) => {
  res.json({ ok: true, url: 'https://sekki.io/billing-portal' });
});



// --- Billing: POST /api-node/billing/portal-session ---
app.post('/api-node/billing/portal-session', (req, res) => {
  // TODO: replace with real Stripe Customer Portal session creation.
  // For now, return a stable URL you control.
  res.json({
    ok: true,
    url: 'https://sekki.io/billing-portal'
  });
});


// View Seat Usage (stub) — returns current seats/cap
app.get('/api/account/usage', (_req, res) => {
  // TODO: pull from DB; sample payload for now
  res.json({
    ok: true,
    seats: {
      creators: { used: 3, cap: 5 },
      viewers: { used: 7, cap: 15 },
    },
    integrations: { connected: 4, draft: 2, errors: 1 },
    storage: { parquetGB: 2.4, rawGB: 1.8 },
    asOf: new Date().toISOString(),
  });
});

// --- Manage Plan: GET /api/plan ---
app.get('/api/plan', (req, res) => {
  res.json({
    plan: 'Premium',
    creatorsUsed: 3,
    creatorsCap: 5,
    viewersUsed: 7,
    viewersCap: 15,
    renewalDate: '2025-11-28',
  });
});

// Mirror for NGINX path (/api-node/plan → forwarded as /api-node/plan to Express)
app.get('/api-node/plan', (req, res) => {
  res.json({
    plan: 'Premium',
    creatorsUsed: 3,
    creatorsCap: 5,
    viewersUsed: 7,
    viewersCap: 15,
    renewalDate: '2025-11-28',
  });
});

// --- Manage Plan: GET /account/plan  (and /api/account/plan) ---
app.get(['/account/plan', '/api/account/plan'], (req, res) => {
  res.json({
    plan: 'Premium',
    creatorsUsed: 3,
    creatorsCap: 5,
    viewersUsed: 7,
    viewersCap: 15,
    renewalDate: '2025-11-28',
  });
});

// --- Mirror for NGINX /api-node/account/plan -> Express as-is ---
app.get('/api-node/account/plan', (req, res) => {
  res.json({
    plan: 'Premium',
    creatorsUsed: 3,
    creatorsCap: 5,
    viewersUsed: 7,
    viewersCap: 15,
    renewalDate: '2025-11-28',
  });
});


// --- Start server ---
const PORT = process.env.PORT || 4000;
app.listen(PORT, () => {
  console.log(`SEKKI backend listening on port ${PORT}`);
});


// Alias: also accept /api-node/billing/checkout-session (in case the proxy doesn't strip the prefix)
app.post('/api-node/billing/checkout-session', (req, res) => {
  try {
    const { plan } = req.body || {};
    const key = String(plan || '').toLowerCase();

    const PLAN_URLS = {
      standard:   'https://sekki.io/pricing?checkout=standard',
      premium:    'https://sekki.io/pricing?checkout=premium',
      enterprise: 'https://sekki.io/pricing?checkout=enterprise',
    };

    const url = PLAN_URLS[key];
    if (!url) {
      return res
        .status(400)
        .json({ ok: false, error: `unknown plan '${plan}'. Use standard | premium | enterprise` });
    }

    return res.status(200).json({ ok: true, url });
  } catch (err) {
    console.error('checkout-session alias error:', err);
    res.status(500).json({ ok: false, error: 'Checkout session failed' });
  }
});
