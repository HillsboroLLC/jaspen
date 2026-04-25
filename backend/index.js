require('dotenv').config();
const express = require('express');

const app = express();
app.use(express.json());

const ALLOWED_ORIGINS = [
  'https://jaspen.ai',
  'https://www.jaspen.ai',
  'http://localhost:3000',
];

const ALLOWED_ROLES = new Set(['owner', 'admin', 'creator', 'collaborator', 'viewer']);
const PLAN_URLS = {
  standard: 'https://jaspen.ai/pricing?checkout=standard',
  premium: 'https://jaspen.ai/pricing?checkout=premium',
  enterprise: 'https://jaspen.ai/pricing?checkout=enterprise',
};

const inMemoryInvites = new Map();
let billingState = {
  plan: 'premium',
  updatedAt: new Date().toISOString(),
};

function isValidEmail(email) {
  const value = String(email || '').trim();
  return /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(value);
}

function normalizeRole(role) {
  const token = String(role || 'viewer').trim().toLowerCase();
  return ALLOWED_ROLES.has(token) ? token : null;
}

function normalizePlan(plan) {
  const key = String(plan || '').trim().toLowerCase();
  return Object.prototype.hasOwnProperty.call(PLAN_URLS, key) ? key : null;
}

function createInvite({ email, role }) {
  const normalizedEmail = String(email || '').trim().toLowerCase();
  const normalizedRole = normalizeRole(role) || 'viewer';
  const inviteToken = `inv_${Math.random().toString(36).slice(2, 12)}`;
  const invite = {
    token: inviteToken,
    email: normalizedEmail,
    role: normalizedRole,
    invitedAt: new Date().toISOString(),
    status: 'pending',
  };
  inMemoryInvites.set(inviteToken, invite);
  return invite;
}

function getPortalUrl() {
  return process.env.BILLING_PORTAL_URL || 'https://jaspen.ai/billing-portal';
}

function createCheckoutSessionUrl(plan) {
  const key = normalizePlan(plan);
  if (!key) return null;
  return PLAN_URLS[key];
}

function usagePayload() {
  return {
    ok: true,
    seats: {
      creators: { used: 3, cap: 5 },
      viewers: { used: 7, cap: 15 },
    },
    integrations: { connected: 4, draft: 2, errors: 1 },
    storage: { parquetGB: 2.4, rawGB: 1.8 },
    asOf: new Date().toISOString(),
  };
}

function planPayload() {
  return {
    plan: String(billingState.plan || 'Premium').replace(/^./, (c) => c.toUpperCase()),
    creatorsUsed: 3,
    creatorsCap: 5,
    viewersUsed: 7,
    viewersCap: 15,
    renewalDate: '2026-11-28',
  };
}

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
  return next();
});

app.use((req, _res, next) => {
  console.log(`${new Date().toISOString()} ${req.method} ${req.originalUrl}`);
  next();
});

app.get('/health', (_req, res) => {
  res.status(200).json({ ok: true, service: 'jaspen-node', ts: Date.now() });
});

app.get('/api-node/health', (_req, res) => {
  res.status(200).json({ ok: true, service: 'jaspen-node', ts: Date.now() });
});

app.get('/api/health', (_req, res) => {
  res.json({ ok: true, service: 'jaspen-backend', ts: Date.now() });
});

app.post('/api/account/invite', (req, res) => {
  const { email, role } = req.body || {};
  if (!isValidEmail(email)) {
    return res.status(400).json({ ok: false, error: 'A valid email is required' });
  }

  const normalizedRole = normalizeRole(role);
  if (role && !normalizedRole) {
    return res.status(400).json({ ok: false, error: 'role must be owner|admin|creator|collaborator|viewer' });
  }

  const invite = createInvite({ email, role: normalizedRole || 'viewer' });
  return res.status(200).json({ ok: true, message: 'Invite created', invite });
});

app.post('/api/account/plan', (req, res) => {
  const { action, plan } = req.body || {};
  const normalizedAction = String(action || '').trim().toLowerCase();
  const allowedActions = new Set(['upgrade', 'downgrade', 'change', 'cancel', 'resume']);
  if (!allowedActions.has(normalizedAction)) {
    return res.status(400).json({ ok: false, error: 'action must be upgrade|downgrade|change|cancel|resume' });
  }

  if (plan) {
    const normalizedPlan = normalizePlan(plan);
    if (!normalizedPlan) {
      return res.status(400).json({ ok: false, error: 'plan must be standard|premium|enterprise' });
    }
    billingState = { ...billingState, plan: normalizedPlan, updatedAt: new Date().toISOString() };
  }

  return res.status(200).json({
    ok: true,
    message: 'Plan action accepted',
    action: normalizedAction,
    plan: billingState.plan,
    processedAt: new Date().toISOString(),
  });
});

app.post(['/billing/checkout-session', '/api-node/billing/checkout-session'], (req, res) => {
  const { plan } = req.body || {};
  const url = createCheckoutSessionUrl(plan);
  if (!url) {
    return res.status(400).json({ ok: false, error: `unknown plan '${plan}'. Use standard | premium | enterprise` });
  }
  return res.status(200).json({ ok: true, url });
});

app.post(['/billing/portal-session', '/api-node/billing/portal-session'], (_req, res) => {
  try {
    return res.json({ ok: true, url: getPortalUrl() });
  } catch (err) {
    console.error('portal-session error:', err);
    return res.status(500).json({ ok: false, error: 'Portal session failed' });
  }
});

app.get('/api/account/usage', (_req, res) => {
  res.json(usagePayload());
});

app.get(['/api/plan', '/api-node/plan', '/account/plan', '/api/account/plan', '/api-node/account/plan'], (_req, res) => {
  res.json(planPayload());
});

const PORT = process.env.PORT || 4000;
const HOST = process.env.HOST || '127.0.0.1';

app.listen(PORT, HOST, () => {
  console.log(`jaspen backend listening on http://${HOST}:${PORT}`);
});
