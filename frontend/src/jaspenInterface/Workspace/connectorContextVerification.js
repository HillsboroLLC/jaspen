import { connectorContextState } from './connectorContextState';

export async function verifyUnconfirmedContextSources({ connectors, checkConnector, onChecking, onResult, inFlight }) {
  const checks = (Array.isArray(connectors) ? connectors : [])
    .filter((connector) => connectorContextState(connector).state === 'unconfirmed')
    .filter((connector) => !inFlight?.has(connector.id))
    .map(async (connector) => {
      inFlight?.add(connector.id);
      onChecking?.(connector.id);
      try {
        const result = await checkConnector(connector.id);
        onResult?.(connector.id, result);
      } catch (error) {
        onResult?.(connector.id, {
          status: 'failed',
          error: error?.message || `Could not verify ${connector.label || connector.id}`,
        });
      } finally {
        inFlight?.delete(connector.id);
      }
    });

  await Promise.all(checks);
}
