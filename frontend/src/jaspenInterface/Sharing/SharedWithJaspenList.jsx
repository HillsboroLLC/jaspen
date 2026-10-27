import React, { useCallback, useEffect, useState } from 'react';

import { Jaspen } from '../Workspace/JaspenClient';

function formatDate(value) {
  if (!value) return '—';
  const parsed = new Date(value);
  return Number.isFinite(parsed.getTime()) ? parsed.toLocaleDateString() : '—';
}

export default function SharedWithJaspenList({ disabled = false, onNotice = () => {}, onError = () => {} }) {
  const [shares, setShares] = useState([]);
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    try {
      const result = await Jaspen.listDecisionShares();
      setShares(Array.isArray(result?.shares) ? result.shares : []);
    } catch (_error) {
      setShares([]);
    }
  }, []);

  useEffect(() => { void load(); }, [load]);

  const withdraw = async (share) => {
    setBusy(true);
    onError('');
    try {
      await Jaspen.withdrawDecisionShare(share.id);
      await load();
      onNotice('Decision share withdrawn.');
    } catch (error) {
      onError(error?.message || 'Failed to withdraw decision share');
    } finally {
      setBusy(false);
    }
  };

  return (
    <>
      <h3>Shared with Jaspen</h3>
      <div className="team-table-wrap">
        <table className="team-table">
          <thead><tr><th>Decision</th><th>Shared by</th><th>Shared</th><th>Status</th><th>Actions</th></tr></thead>
          <tbody>
            {shares.map((share) => (
              <tr key={share.id}>
                <td>{share.title || (share.status === 'withdrawn' ? 'Withdrawn decision' : 'Untitled decision')}</td>
                <td>{share.shared_by || '—'}</td>
                <td>{formatDate(share.created_at)}</td>
                <td>{share.status === 'withdrawn' ? 'Withdrawn' : 'Shared'}</td>
                <td>
                  {share.status !== 'withdrawn' ? (
                    <button type="button" className="team-btn tiny danger" onClick={() => withdraw(share)} disabled={disabled || busy}>Withdraw</button>
                  ) : '—'}
                </td>
              </tr>
            ))}
            {shares.length === 0 && <tr><td colSpan={5}><p className="team-empty">No decisions have been shared with Jaspen.</p></td></tr>}
          </tbody>
        </table>
      </div>
    </>
  );
}
