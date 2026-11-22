import React, { useEffect } from 'react';
import { API_BASE } from '../../config/apiBase';

export default function SalesforceOAuthBridge() {
  useEffect(() => {
    const query = window.location.search || '';
    const target = `${API_BASE}/api/v1/connectors/salesforce/oauth/callback${query}`;
    window.location.replace(target);
  }, []);

  return (
    <div style={{ padding: 24 }}>
      Redirecting to Salesforce callback...
    </div>
  );
}

