import { connectorContextState } from './connectorContextState';

describe.each([
  ['Jira', 'jira_sync', 'jira'],
  ['Smartsheet', 'smartsheet_sync', 'smartsheet'],
])('%s Data Context states', (label, id, section) => {
  test('not connected is grey and routes the user to Data Sources', () => {
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

  test('unconfirmed remains selectable with a neutral dot and last-confirmed tooltip', () => {
    const lastConfirmedAt = '2026-10-01T12:00:00Z';
    const expectedDate = new Date(lastConfirmedAt).toLocaleDateString();

    expect(connectorContextState({
      id, label, connected: true, freshness: 'unconfirmed', last_confirmed_at: lastConfirmedAt,
      [section]: { data_enabled: true },
    })).toEqual(expect.objectContaining({
      state: 'available',
      dot: 'unconfirmed',
      selectable: true,
      tooltip: `Set up · last confirmed ${expectedDate}`,
    }));
  });

  test('never-confirmed remains selectable with the neutral setup tooltip', () => {
    expect(connectorContextState({
      id, label, connected: true, freshness: 'unconfirmed', last_confirmed_at: null,
      [section]: { data_enabled: true },
    })).toEqual(expect.objectContaining({
      dot: 'unconfirmed',
      selectable: true,
      tooltip: 'Set up · not confirmed yet',
    }));
  });
});
