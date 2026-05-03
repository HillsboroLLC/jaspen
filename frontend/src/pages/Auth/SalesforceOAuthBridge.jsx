import React, { useEffect } from 'react';

export default function SalesforceOAuthBridge() {
  useEffect(() => {
    const query = window.location.search || '';
    const target = `https://api.jaspen.ai/api/v1/connectors/salesforce/oauth/callback${query}`;
    window.location.replace(target);
  }, []);

  return (
    <div style={{ padding: 24 }}>
      Redirecting to Salesforce callback...
    </div>
  );
}

