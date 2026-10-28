const ANALYSIS_SETTING = {
  jira_sync: {
    section: 'jira',
    label: 'Jira',
    setting: 'Use Jira data in analysis',
  },
  smartsheet_sync: {
    section: 'smartsheet',
    label: 'Smartsheet',
    setting: 'Use Smartsheet data in analysis',
  },
};

function formatConfirmedDate(value) {
  if (!value) return null;
  const parsed = new Date(value);
  return Number.isNaN(parsed.getTime()) ? null : parsed.toLocaleDateString();
}

export function connectorContextState(connector = {}, fallback = {}) {
  const id = String(connector?.id || fallback?.id || '').trim();
  const label = String(connector?.label || fallback?.label || id || 'connector').trim();
  const connected = Boolean(connector?.connected);
  const lifecycle = String(connector?.lifecycle_status || connector?.status || '').toLowerCase();
  const checkStatus = String(connector?.data_context_check_status || '').toLowerCase();
  const hasProblem = ['error', 'degraded', 'reconnect_required'].includes(lifecycle) || checkStatus === 'failed';
  const reconnectRequired = lifecycle === 'reconnect_required' || Boolean(connector?.data_context_reconnect_required);
  const freshness = connector?.data_context_freshness ?? connector?.freshness;
  const lastConfirmedAt = connector?.data_context_last_confirmed_at ?? connector?.last_confirmed_at;
  const checking = String(freshness || '').toLowerCase() === 'checking' || checkStatus === 'checking';
  const confirmed = String(freshness || '').toLowerCase() === 'confirmed';
  const confirmedDate = formatConfirmedDate(lastConfirmedAt);
  const freshnessTooltip = confirmedDate
    ? `Set up · last confirmed ${confirmedDate}`
    : 'Set up · not confirmed yet';
  const analysisSetting = ANALYSIS_SETTING[id];
  const analysisEnabled = analysisSetting
    ? Boolean(connector?.[analysisSetting.section]?.data_enabled)
    : connected;

  if (!connected) {
    return {
      id, label, connected: false, analysisEnabled: false, selectable: false,
      state: 'disconnected', dot: 'disconnected',
      tooltip: `Connect ${label} in Data Sources`,
    };
  }
  if (hasProblem) {
    return {
      id, label, connected: true, analysisEnabled: false, selectable: false,
      state: 'problem', dot: 'problem',
      tooltip: reconnectRequired
        ? `Reconnect ${label} in Data Sources`
        : `Couldn't verify ${label} data. Check it in Data Sources.`,
    };
  }
  if (!analysisEnabled && analysisSetting) {
    return {
      id, label, connected: true, analysisEnabled: false, selectable: false,
      state: 'analysis-disabled', dot: confirmed ? 'connected' : 'unconfirmed',
      tooltip: `Turn on '${analysisSetting.setting}' in Data Sources to use it here`,
    };
  }
  if (checking) {
    return {
      id, label, connected: true, analysisEnabled: true, selectable: false,
      state: 'checking', dot: 'unconfirmed',
      tooltip: `Checking ${label} data…`,
    };
  }
  if (!confirmed) {
    return {
      id, label, connected: true, analysisEnabled: true, selectable: false,
      state: 'unconfirmed', dot: 'unconfirmed', tooltip: freshnessTooltip,
    };
  }
  return {
    id, label, connected: true, analysisEnabled: true, selectable: true,
    state: 'available', dot: 'connected',
    tooltip: `Add live ${label} data as AI context`,
  };
}
