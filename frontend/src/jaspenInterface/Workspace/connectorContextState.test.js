import { connectorContextState } from './connectorContextState';

describe.each([
  ['Jira', 'jira_sync', 'jira'],
  ['Smartsheet', 'smartsheet_sync', 'smartsheet'],
])('%s Data Context states', (label, id, section) => {
  test('not connected is grey and points the user to Data Sources', () => {
    expect(connectorContextState({ id, label, connected: false })).toEqual(expect.objectContaining({
      state: 'disconnected',
      dot: 'disconnected',
      selectable: false,
      tooltip: `Connect ${label} in Data Sources`,
    }));
  });

  test('connected with analysis off keeps a green dot but cannot be selected', () => {
    const state = connectorContextState({ id, label, connected: true, freshness: 'confirmed', [section]: { data_enabled: false } });
    expect(state).toEqual(expect.objectContaining({
      state: 'analysis-disabled',
      dot: 'connected',
      selectable: false,
    }));
    expect(state.tooltip).toBe(`Turn on 'Use ${label} data in analysis' in Data Sources to use it here`);
  });

  test('connected with analysis on is selectable with a green dot', () => {
    expect(connectorContextState({ id, label, connected: true, freshness: 'confirmed', [section]: { data_enabled: true } })).toEqual(expect.objectContaining({
      state: 'available',
      dot: 'connected',
      selectable: true,
    }));
  });

  test('unconfirmed is disabled with a neutral dot and last-confirmed tooltip', () => {
    const lastConfirmedAt = '2026-10-01T12:00:00Z';
    const expectedDate = new Date(lastConfirmedAt).toLocaleDateString();

    expect(connectorContextState({
      id, label, connected: true, freshness: 'unconfirmed', last_confirmed_at: lastConfirmedAt,
      [section]: { data_enabled: true },
    })).toEqual(expect.objectContaining({
      state: 'unconfirmed',
      dot: 'unconfirmed',
      selectable: false,
      tooltip: `Set up · last confirmed ${expectedDate}`,
    }));
  });

  test('never-confirmed is disabled with the neutral setup tooltip', () => {
    expect(connectorContextState({
      id, label, connected: true, freshness: 'unconfirmed', last_confirmed_at: null,
      [section]: { data_enabled: true },
    })).toEqual(expect.objectContaining({
      dot: 'unconfirmed',
      selectable: false,
      tooltip: 'Set up · not confirmed yet',
    }));
  });

  test('checking and problem states are disabled', () => {
    expect(connectorContextState({
      id, label, connected: true, freshness: 'checking', [section]: { data_enabled: true },
    })).toEqual(expect.objectContaining({ state: 'checking', selectable: false }));
    expect(connectorContextState({
      id, label, connected: true, freshness: 'confirmed', lifecycle_status: 'error', [section]: { data_enabled: true },
    })).toEqual(expect.objectContaining({ state: 'problem', selectable: false }));
  });
});

describe.each([
  ['Salesforce', 'salesforce_insights'],
  ['Snowflake', 'snowflake_insights'],
])('%s Data Context states', (label, id) => {
  test('only a confirmed connection is selectable', () => {
    expect(connectorContextState({ id, label, connected: true, freshness: 'confirmed' })).toEqual(expect.objectContaining({
      state: 'available',
      selectable: true,
    }));
    expect(connectorContextState({ id, label, connected: true, freshness: 'unconfirmed' })).toEqual(expect.objectContaining({
      state: 'unconfirmed',
      selectable: false,
    }));
    expect(connectorContextState({ id, label, connected: false, freshness: 'confirmed' })).toEqual(expect.objectContaining({
      state: 'disconnected',
      selectable: false,
    }));
  });
});
