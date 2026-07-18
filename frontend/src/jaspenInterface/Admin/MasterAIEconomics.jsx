import React, { useCallback, useEffect, useMemo, useState } from 'react';
import { FontAwesomeIcon } from '@fortawesome/react-fontawesome';
import { faCoins, faMicrochip, faRotateRight, faScaleBalanced } from '@fortawesome/free-solid-svg-icons';
import { API_BASE } from '../../config/apiBase';
import { authFetch, buildAuthHeaders } from '../../shared/auth/http';
import AppMenu from '../shared/AppMenu';
import MasterAdminGuard from './MasterAdminGuard';
import './MasterObservability.css';

const currency = (value, digits = 2) => new Intl.NumberFormat('en-US', {
  style: 'currency', currency: 'USD', minimumFractionDigits: digits, maximumFractionDigits: digits,
}).format(Number(value || 0));
const number = (value) => Number(value || 0).toLocaleString();

export default function MasterAIEconomics() {
  const [days, setDays] = useState(30);
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const load = useCallback(async () => {
    setLoading(true); setError('');
    try {
      const response = await authFetch(`${API_BASE}/api/v1/admin/master/ai-economics?days=${days}`, {
        credentials: 'include', headers: buildAuthHeaders({ 'Content-Type': 'application/json' }, 'GET'),
      });
      const payload = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(payload.error || `Unable to load AI economics (${response.status})`);
      setData(payload);
    } catch (err) { setError(err.message || 'Unable to load AI economics.'); }
    finally { setLoading(false); }
  }, [days]);
  useEffect(() => { load(); }, [load]);

  const metrics = data?.metrics || {};
  const tables = useMemo(() => [
    ['Provider cost', 'provider', data?.providers || []],
    ['Cost by model', 'model', data?.models || []],
    ['Cost by customer plan', 'plan', data?.plans || []],
  ], [data]);

  return <MasterAdminGuard><div className="master-admin-page int-page"><AppMenu />
    <main className="master-admin-inner int-page-inner">
      <header className="master-admin-head int-page-head"><div><p className="int-eyebrow">Master Admin</p><h1>AI Economics</h1>
        <p>Provider exposure, consumed thinking capacity, and estimated AI gross margin in one operating view.</p></div>
        <div className="ai-econ-controls"><select aria-label="Reporting period" value={days} onChange={e => setDays(Number(e.target.value))}>
          <option value="7">Last 7 days</option><option value="30">Last 30 days</option><option value="90">Last 90 days</option><option value="365">Last year</option>
        </select><button type="button" className="master-admin-refresh" onClick={load} disabled={loading}><FontAwesomeIcon icon={faRotateRight} />{loading ? 'Refreshing' : 'Refresh'}</button></div>
      </header>
      {error && <div className="master-admin-state is-error">{error}</div>}
      {loading && !data && <div className="master-admin-state">Calculating AI economics…</div>}
      {data && <>
        <section className="master-metric-grid ai-econ-metrics" aria-label="AI economics summary">
          <article className="master-metric-card"><span>AI provider cost</span><strong>{currency(metrics.provider_cost_usd, 4)}</strong><p>Claude + Gemini token cost</p></article>
          <article className="master-metric-card"><span>Estimated revenue</span><strong>{currency(metrics.estimated_revenue_usd)}</strong><p>Active plan list-price estimate</p></article>
          <article className="master-metric-card"><span>AI gross profit</span><strong>{currency(metrics.ai_gross_profit_usd)}</strong><p>Revenue estimate less AI cost</p></article>
          <article className="master-metric-card"><span>AI gross margin</span><strong>{metrics.ai_gross_margin_percent == null ? 'Not available' : `${metrics.ai_gross_margin_percent}%`}</strong><p>AI cost only, not company margin</p></article>
          <article className="master-metric-card"><span>Credits consumed</span><strong>{number(metrics.credits_consumed)}</strong><p>Customer-facing Jaspen credits</p></article>
          <article className="master-metric-card"><span>AI calls</span><strong>{number(metrics.events)}</strong><p>Recorded completion events</p></article>
          <article className="master-metric-card"><span>Input tokens</span><strong>{number(metrics.input_tokens)}</strong></article>
          <article className="master-metric-card"><span>Output + thinking tokens</span><strong>{number(metrics.output_tokens)}</strong></article>
        </section>
        <section className="master-admin-columns ai-econ-columns">
          {tables.map(([title, key, rows], index) => <article className="master-admin-panel" key={key}><div className="master-panel-title"><FontAwesomeIcon icon={index === 0 ? faCoins : index === 1 ? faMicrochip : faScaleBalanced} /><h2>{title}</h2></div>
            {rows.length === 0 ? <p className="master-empty">No usage recorded in this period.</p> : <div className="master-table-wrap"><table className="master-table"><thead><tr><th>{key}</th>{key === 'plan' && <th>Active accounts</th>}<th>Cost</th><th>Calls</th><th>Credits</th></tr></thead><tbody>{rows.map(row => <tr key={row[key]}><td>{row[key]}</td>{key === 'plan' && <td>{number(row.active_accounts)}</td>}<td>{currency(row.cost_usd, 4)}</td><td>{number(row.events)}</td><td>{number(row.credits)}</td></tr>)}</tbody></table></div>}
          </article>)}
        </section>
        <section className="master-admin-panel ai-econ-notes"><div className="master-panel-title"><FontAwesomeIcon icon={faScaleBalanced} /><h2>How to read this page</h2></div>
          {metrics.unpriced_events > 0 && <p className="master-admin-state is-error"><strong>Attention:</strong> {number(metrics.unpriced_events)} metered AI event{metrics.unpriced_events === 1 ? '' : 's'} could not be priced. Review the model table before relying on the cost total.</p>}
          <p><strong>Revenue:</strong> {data.notes?.revenue}</p><p><strong>Provider cost:</strong> {data.notes?.cost}</p><p><strong>Margin:</strong> {data.notes?.margin}</p>
        </section>
      </>}
    </main>
  </div></MasterAdminGuard>;
}
