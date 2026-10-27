import { readConnectorCheckResponse, verifyUnconfirmedContextSources } from './connectorContextVerification';

const jira = {
  id: 'jira_sync', label: 'Jira', connected: true, freshness: 'unconfirmed', jira: { data_enabled: true },
};

test('checks an eligible unconfirmed source once and reports success', async () => {
  const checkConnector = jest.fn().mockResolvedValue({ status: 'confirmed', last_verified_at: '2026-10-27T12:00:00Z' });
  const onChecking = jest.fn();
  const onResult = jest.fn();
  const inFlight = new Set();

  await Promise.all([
    verifyUnconfirmedContextSources({ connectors: [jira], checkConnector, onChecking, onResult, inFlight }),
    verifyUnconfirmedContextSources({ connectors: [jira], checkConnector, onChecking, onResult, inFlight }),
  ]);

  expect(checkConnector).toHaveBeenCalledTimes(1);
  expect(onChecking).toHaveBeenCalledWith('jira_sync');
  expect(onResult).toHaveBeenCalledWith('jira_sync', expect.objectContaining({ status: 'confirmed' }));
});

test('reports a failed verification without making the source selectable', async () => {
  const onResult = jest.fn();
  await verifyUnconfirmedContextSources({
    connectors: [jira],
    checkConnector: jest.fn().mockRejectedValue(new Error('read failed')),
    onResult,
    inFlight: new Set(),
  });

  expect(onResult).toHaveBeenCalledWith('jira_sync', expect.objectContaining({ status: 'failed' }));
});

test('reads a failed verification as a normal result even when the response is not ok', async () => {
  const response = {
    ok: false,
    status: 503,
    json: jest.fn().mockResolvedValue({ status: 'failed', error: 'synthetic read failed' }),
  };

  await expect(readConnectorCheckResponse(response)).resolves.toEqual({
    status: 'failed',
    error: 'synthetic read failed',
  });
});
