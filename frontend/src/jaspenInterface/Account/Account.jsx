import React, { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { API_BASE } from '../../config/apiBase';
import { getPlanConnectorSentence } from '../../shared/billing/planConnectors';
import './Account.css';

function getToken() {
  return localStorage.getItem('access_token') || localStorage.getItem('token');
}

const PLAN_ORDER = ['free', 'essential', 'team', 'enterprise'];
const PACK_ORDER = ['pack_1000', 'pack_5000', 'pack_20000'];
const MODEL_ORDER = ['pluto', 'orbit', 'titan'];
const PLAN_RANK = {
  free: 0,
  essential: 1,
  team: 2,
  enterprise: 3,
};
const FALLBACK_MODEL_TYPES = {
  pluto: {
    model_type: 'pluto',
    label: 'Pluto',
    version: '1.0',
    description: 'Fastest model for core intake and scorecard workflows.',
    min_plan: 'free',
  },
  orbit: {
    model_type: 'orbit',
    label: 'Orbit',
    version: '1.0',
    description: 'Balanced depth and speed for broader cross-functional synthesis.',
    min_plan: 'team',
  },
  titan: {
    model_type: 'titan',
    label: 'Titan',
    version: '1.0',
    description: 'Highest-depth reasoning for complex multi-team initiatives.',
    min_plan: 'enterprise',
  },
};

export default function Account() {
  const navigate = useNavigate();
  const [status, setStatus] = useState(null);
  const [catalog, setCatalog] = useState({ plans: {}, overage_packs: {}, model_types: FALLBACK_MODEL_TYPES });
  const [connectorState, setConnectorState] = useState({
    loading: true,
    items: [],
  });
  const [loading, setLoading] = useState(true);
  const [pendingAction, setPendingAction] = useState('');
  const [connectorPendingId, setConnectorPendingId] = useState('');
  const [message, setMessage] = useState('');

  useEffect(() => {
    let mounted = true;

    const load = async () => {
      const token = getToken();

      try {
        const [statusRes, catalogRes, connectorsRes] = await Promise.all([
          fetch(`${API_BASE}/api/billing/status`, {
            headers: token ? { Authorization: `Bearer ${token}` } : {},
            credentials: 'include',
          }),
          fetch(`${API_BASE}/api/billing/catalog`, { credentials: 'include' }),
          fetch(`${API_BASE}/api/connectors/status`, {
            headers: token ? { Authorization: `Bearer ${token}` } : {},
            credentials: 'include',
          }),
        ]);

        const statusData = await statusRes.json();
        const catalogData = await catalogRes.json();
        const connectorsData = await connectorsRes.json().catch(() => ({}));

        if (!statusRes.ok) {
          if (statusRes.status === 401) {
            navigate('/?auth=1', { replace: true });
            return;
          }
          throw new Error(statusData?.msg || 'Unable to load billing status.');
        }
        if (!connectorsRes.ok && connectorsRes.status === 401) {
          navigate('/?auth=1', { replace: true });
          return;
        }
        if (mounted) {
          setStatus(statusData);
          setCatalog(catalogData || { plans: {}, overage_packs: {}, model_types: FALLBACK_MODEL_TYPES });
          setConnectorState({
            loading: false,
            items: Array.isArray(connectorsData?.connectors) ? connectorsData.connectors : [],
          });
        }
      } catch (error) {
        if (mounted) {
          setMessage(error.message || 'Unable to load account details.');
          setConnectorState((prev) => ({ ...prev, loading: false }));
        }
      } finally {
        if (mounted) setLoading(false);
      }
    };

    load();
    return () => {
      mounted = false;
    };
  }, [navigate]);

  const refreshStatus = async () => {
    const token = getToken();
    const res = await fetch(`${API_BASE}/api/billing/status`, {
      headers: token ? { Authorization: `Bearer ${token}` } : {},
      credentials: 'include',
    });
    const data = await res.json();
    if (res.ok) setStatus(data);
  };

  const refreshConnectors = async () => {
    const token = getToken();
    const res = await fetch(`${API_BASE}/api/connectors/status`, {
      headers: token ? { Authorization: `Bearer ${token}` } : {},
      credentials: 'include',
    });
    const data = await res.json();
    if (res.ok) {
      setConnectorState({
        loading: false,
        items: Array.isArray(data?.connectors) ? data.connectors : [],
      });
    } else if (res.status === 401) {
      navigate('/?auth=1', { replace: true });
    }
  };

  const startPlanChange = async (planKey) => {
    const token = getToken();

    setPendingAction(planKey);
    setMessage('');

    try {
      const response = await fetch(`${API_BASE}/api/billing/create-checkout-session`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          ...(token ? { Authorization: `Bearer ${token}` } : {}),
        },
        credentials: 'include',
        body: JSON.stringify({ plan_key: planKey }),
      });
      const data = await response.json();

      if (!response.ok) {
        if (response.status === 401) {
          navigate('/?auth=1', { replace: true });
          return;
        }
        throw new Error(data?.msg || 'Unable to start plan change.');
      }

      if (data?.url) {
        window.location.href = data.url;
        return;
      }

      setMessage('Plan updated successfully.');
      await refreshStatus();
    } catch (error) {
      setMessage(error.message || 'Unable to start plan change.');
    } finally {
      setPendingAction('');
    }
  };

  const openBillingPortal = async () => {
    const token = getToken();

    setPendingAction('portal');
    setMessage('');

    try {
      const response = await fetch(`${API_BASE}/api/billing/create-portal-session`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          ...(token ? { Authorization: `Bearer ${token}` } : {}),
        },
        credentials: 'include',
        body: JSON.stringify({ return_url: `${window.location.origin}/account` }),
      });
      const data = await response.json();
      if (!response.ok || !data?.url) {
        if (response.status === 401) {
          navigate('/?auth=1', { replace: true });
          return;
        }
        throw new Error(data?.msg || 'Online billing management is not available for this account yet.');
      }
      window.location.href = data.url;
    } catch (error) {
      setMessage(error.message || 'Unable to open billing settings.');
    } finally {
      setPendingAction('');
    }
  };

  const cancelAtPeriodEnd = async () => {
    const token = getToken();

    setPendingAction('cancel');
    setMessage('');

    try {
      const response = await fetch(`${API_BASE}/api/billing/cancel-subscription`, {
        method: 'POST',
        headers: {
          ...(token ? { Authorization: `Bearer ${token}` } : {}),
        },
        credentials: 'include',
      });
      const data = await response.json();
      if (!response.ok) {
        if (response.status === 401) {
          navigate('/?auth=1', { replace: true });
          return;
        }
        throw new Error(data?.msg || 'Unable to cancel subscription.');
      }
      setMessage('Subscription will cancel at period end.');
      await refreshStatus();
    } catch (error) {
      setMessage(error.message || 'Unable to cancel subscription.');
    } finally {
      setPendingAction('');
    }
  };

  const buyPack = async (packKey) => {
    const token = getToken();

    setPendingAction(packKey);
    setMessage('');

    try {
      const response = await fetch(`${API_BASE}/api/billing/create-overage-checkout-session`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          ...(token ? { Authorization: `Bearer ${token}` } : {}),
        },
        credentials: 'include',
        body: JSON.stringify({ pack_key: packKey }),
      });
      const data = await response.json();
      if (!response.ok || !data?.url) {
        if (response.status === 401) {
          navigate('/?auth=1', { replace: true });
          return;
        }
        throw new Error(data?.msg || 'Unable to start overage checkout.');
      }
      window.location.href = data.url;
    } catch (error) {
      setMessage(error.message || 'Unable to start overage checkout.');
    } finally {
      setPendingAction('');
    }
  };

  const updateConnector = async (connectorId, updates) => {
    const token = getToken();
    setConnectorPendingId(connectorId);
    setMessage('');

    try {
      const response = await fetch(`${API_BASE}/api/connectors/${encodeURIComponent(connectorId)}`, {
        method: 'PATCH',
        headers: {
          'Content-Type': 'application/json',
          ...(token ? { Authorization: `Bearer ${token}` } : {}),
        },
        credentials: 'include',
        body: JSON.stringify(updates || {}),
      });
      const data = await response.json();
      if (!response.ok) {
        if (response.status === 401) {
          navigate('/?auth=1', { replace: true });
          return;
        }
        throw new Error(data?.error || 'Unable to update connector.');
      }

      const updatedConnector = data?.connector;
      if (updatedConnector?.id) {
        setConnectorState((prev) => ({
          ...prev,
          items: (prev.items || []).map((item) => (item.id === updatedConnector.id ? updatedConnector : item)),
        }));
      } else {
        await refreshConnectors();
      }
    } catch (error) {
      setMessage(error.message || 'Unable to update connector.');
    } finally {
      setConnectorPendingId('');
    }
  };

  if (loading) {
    return (
      <div className="account-page">
        <div className="account-panel">Loading account details...</div>
      </div>
    );
  }

  const currentPlan = status?.plan_key || 'free';
  const plans = catalog?.plans || {};
  const packs = catalog?.overage_packs || {};
  const creditsRemainingLabel = status?.credits_remaining == null
    ? 'Contracted'
    : Number(status?.credits_remaining || 0).toLocaleString();
  const monthlyLimitLabel = status?.monthly_credit_limit == null
    ? 'Contracted'
    : Number(status?.monthly_credit_limit || 0).toLocaleString();
  const modelTypes = catalog?.model_types || FALLBACK_MODEL_TYPES;
  const orderedModelTypes = MODEL_ORDER.map((key) => modelTypes?.[key]).filter(Boolean);
  const formatModelDisplayName = (model) => {
    const label = model?.label || model?.model_type || 'Model';
    const version = String(model?.version || '1.0').trim();
    return `${label}-${version}`;
  };
  const isModelAvailableForPlan = (minPlan, planKey) => {
    const requiredRank = PLAN_RANK[String(minPlan || 'free').toLowerCase()] ?? 0;
    const planRank = PLAN_RANK[String(planKey || 'free').toLowerCase()] ?? 0;
    return planRank >= requiredRank;
  };

  return (
    <div className="account-page">
      <div className="account-panel">
        <div className="account-header-row">
          <div className="account-title-wrap">
            <p className="account-eyebrow">Account</p>
            <h1>Billing & Usage</h1>
            <p className="account-subtext">
              Manage plan access, credit usage, and available connectors for your workspace.
            </p>
          </div>
          <button type="button" onClick={() => navigate('/new')} className="account-secondary-btn">
            Back to Jaspen
          </button>
        </div>

        <div className="account-inline-status">
          <span className="account-status-chip">
            <span className="label">Current plan</span>
            <strong>{(plans[currentPlan]?.label || currentPlan).toString()}</strong>
          </span>
          <span className="account-status-chip">
            <span className="label">Credits remaining</span>
            <strong>{creditsRemainingLabel}</strong>
          </span>
          <span className="account-status-chip">
            <span className="label">Monthly limit</span>
            <strong>{monthlyLimitLabel}</strong>
          </span>
        </div>

        {message && <p className="account-message">{message}</p>}

        <section className="account-section">
          <h2>Plans</h2>
          <div className="account-plan-grid">
            {PLAN_ORDER.map((key) => {
              const plan = plans[key];
              if (!plan) return null;
              const isCurrent = currentPlan === key;
              const isSalesOnly = !!plan.sales_only;
              const isPending = pendingAction === key;
              const hasPrice = Number.isFinite(plan.monthly_price_usd);

              return (
                <article className={`account-plan-card ${isCurrent ? 'is-current' : ''}`} key={key}>
                  <h3>{plan.label}</h3>
                  <p className="account-plan-price">
                    {hasPrice ? (plan.monthly_price_usd === 0 ? '$0' : `$${plan.monthly_price_usd}/mo`) : 'Contact sales'}
                  </p>
                  <p>
                    {plan.monthly_credits == null
                      ? 'Contracted pooled usage'
                      : `${Number(plan.monthly_credits).toLocaleString()} credits/month`}
                  </p>
                  <p className="account-plan-connectors">
                    Connectors: {getPlanConnectorSentence(key)}
                  </p>

                  {isCurrent ? (
                    <span className="account-pill">Current</span>
                  ) : isSalesOnly ? (
                    <a href="/login" className="account-primary-btn">Talk to sales</a>
                  ) : (
                    <button
                      type="button"
                      className="account-primary-btn"
                      onClick={() => startPlanChange(key)}
                      disabled={isPending}
                    >
                      {isPending ? 'Redirecting...' : key === 'essential' ? 'Upgrade' : 'Switch'}
                    </button>
                  )}
                </article>
              );
            })}
          </div>
        </section>

        <section className="account-section" id="connectors">
          <h2>Connectors & PM Sync</h2>
          <p className="account-connectors-subtext">
            Configure whether external systems feed Jaspen, Jaspen feeds external systems, or both.
          </p>
          {connectorState.loading ? (
            <p className="account-connectors-loading">Loading connector settings...</p>
          ) : (
            <div className="account-connector-grid">
              {(connectorState.items || []).map((connector) => {
                const locked = connector?.status === 'locked' || !connector?.enabled;
                const connected = Boolean(connector?.connected);
                const pending = connectorPendingId === connector?.id;
                const syncModes = Array.isArray(connector?.available_sync_modes) ? connector.available_sync_modes : [];
                const conflictPolicies = Array.isArray(connector?.available_conflict_policies)
                  ? connector.available_conflict_policies
                  : ['latest_wins', 'prefer_external', 'prefer_jaspen', 'manual_review'];
                const modeValue = connector?.sync_mode || (syncModes.includes('import') ? 'import' : '');
                const policyValue = connector?.conflict_policy || 'prefer_external';

                return (
                  <article className={`account-connector-card ${connected ? 'is-connected' : ''}`} key={connector.id}>
                    <div className="account-connector-head">
                      <h3>{connector.label}</h3>
                      <span className={`account-connector-badge ${locked ? 'is-locked' : connected ? 'is-connected' : 'is-available'}`}>
                        {locked ? `${connector.required_min_tier || 'team'}+` : connected ? 'Connected' : 'Available'}
                      </span>
                    </div>
                    <p className="account-connector-group">{connector.group}</p>
                    <p>{connector.description}</p>

                    {locked ? (
                      <button type="button" className="account-secondary-btn" onClick={() => setMessage('Upgrade plan to unlock this connector.')}>
                        Upgrade to unlock
                      </button>
                    ) : (
                      <>
                        {connector.id === 'jira_sync' && (
                          <div className="account-connector-controls account-jira-config">
                            <label>
                              Jira URL
                              <input
                                type="text"
                                defaultValue={connector?.jira?.base_url || ''}
                                placeholder="https://your-company.atlassian.net"
                                disabled={pending}
                                onBlur={(e) => {
                                  const value = String(e.target.value || '').trim();
                                  const currentValue = String(connector?.jira?.base_url || '').trim();
                                  if (value !== currentValue) {
                                    updateConnector(connector.id, { jira_base_url: value });
                                  }
                                }}
                              />
                            </label>
                            <label>
                              Jira project key
                              <input
                                type="text"
                                defaultValue={connector?.jira?.project_key || ''}
                                placeholder="PROJ"
                                disabled={pending}
                                onBlur={(e) => {
                                  const value = String(e.target.value || '').trim();
                                  const currentValue = String(connector?.jira?.project_key || '').trim();
                                  if (value !== currentValue) {
                                    updateConnector(connector.id, { jira_project_key: value, external_workspace: value });
                                  }
                                }}
                              />
                            </label>
                          </div>
                        )}
                        <div className="account-connector-controls">
                          <label>
                            Sync direction
                            <select
                              value={modeValue}
                              disabled={!connected || pending}
                              onChange={(e) => updateConnector(connector.id, { sync_mode: e.target.value })}
                            >
                              {syncModes.map((mode) => (
                                <option key={mode} value={mode}>
                                  {mode === 'import' ? 'External -> Jaspen' : mode === 'push' ? 'Jaspen -> External' : 'Two-way'}
                                </option>
                              ))}
                            </select>
                          </label>
                          <label>
                            Conflict policy
                            <select
                              value={policyValue}
                              disabled={!connected || pending}
                              onChange={(e) => updateConnector(connector.id, { conflict_policy: e.target.value })}
                            >
                              {conflictPolicies.map((policy) => (
                                <option key={policy} value={policy}>
                                  {policy.replace(/_/g, ' ')}
                                </option>
                              ))}
                            </select>
                          </label>
                        </div>
                        <button
                          type="button"
                          className="account-primary-btn"
                          onClick={() => updateConnector(connector.id, { connection_status: connected ? 'disconnected' : 'connected' })}
                          disabled={pending}
                        >
                          {pending ? 'Saving...' : connected ? 'Disconnect' : 'Connect'}
                        </button>
                      </>
                    )}
                  </article>
                );
              })}
            </div>
          )}
        </section>

        <section className="account-section">
          <h2>One-time credit packs</h2>
          <div className="account-pack-grid">
            {PACK_ORDER.map((key) => {
              const pack = packs[key];
              if (!pack) return null;
              const isPending = pendingAction === key;
              return (
                <article className="account-pack-card" key={key}>
                  <h3>{pack.label}</h3>
                  <p>{Number(pack.credits || 0).toLocaleString()} one-time credits</p>
                  <button
                    type="button"
                    className="account-primary-btn"
                    onClick={() => buyPack(key)}
                    disabled={isPending}
                  >
                    {isPending ? 'Redirecting...' : `Purchase for $${pack.price_usd}`}
                  </button>
                </article>
              );
            })}
          </div>
        </section>

        <section className="account-section">
          <h2>Model access by plan</h2>
          <div className="account-model-table-wrap">
            <table className="account-model-table">
              <thead>
                <tr>
                  <th scope="col">Model</th>
                  {PLAN_ORDER.map((key) => (
                    <th scope="col" key={key}>{plans[key]?.label || key}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {orderedModelTypes.map((model) => (
                  <tr key={model.model_type || model.label}>
                    <th scope="row">
                      <div className="account-model-name">{formatModelDisplayName(model)}</div>
                      <div className="account-model-desc">{model.description || ''}</div>
                    </th>
                    {PLAN_ORDER.map((key) => (
                      <td
                        key={`${model.model_type}-${key}`}
                        className={key === currentPlan ? 'is-current-plan' : ''}
                      >
                        {isModelAvailableForPlan(model.min_plan, key) ? 'Included' : 'Upgrade'}
                      </td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>

        <section className="account-section account-actions-row">
          <button
            type="button"
            className="account-secondary-btn"
            onClick={openBillingPortal}
            disabled={pendingAction === 'portal'}
          >
            {pendingAction === 'portal' ? 'Opening...' : 'Manage billing'}
          </button>
          <button
            type="button"
            className="account-danger-btn"
            onClick={cancelAtPeriodEnd}
            disabled={pendingAction === 'cancel' || !status?.stripe_subscription_id}
          >
            {pendingAction === 'cancel' ? 'Canceling...' : 'Cancel at period end'}
          </button>
        </section>
      </div>
    </div>
  );
}
