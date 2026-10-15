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

export function connectorContextState(connector = {}, fallback = {}) {
  const id = String(connector?.id || fallback?.id || '').trim();
  const label = String(connector?.label || fallback?.label || id || 'connector').trim();
  const connected = Boolean(connector?.connected);
  const lifecycle = String(connector?.lifecycle_status || connector?.status || '').toLowerCase();
  const hasProblem = ['error', 'degraded', 'reconnect_required'].includes(lifecycle);
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
      state: 'problem', dot: 'problem', tooltip: `Reconnect ${label}`,
    };
  }
  if (!analysisEnabled && analysisSetting) {
    return {
      id, label, connected: true, analysisEnabled: false, selectable: false,
      state: 'analysis-disabled', dot: 'connected',
      tooltip: `Turn on '${analysisSetting.setting}' in Data Sources to use it here`,
    };
  }
  return {
    id, label, connected: true, analysisEnabled: true, selectable: true,
    state: 'available', dot: 'connected',
    tooltip: `Add live ${label} data as AI context`,
  };
}
