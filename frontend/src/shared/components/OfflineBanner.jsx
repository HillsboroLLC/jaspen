import React, { useEffect, useState } from 'react';
import './OfflineBanner.css';

export default function OfflineBanner() {
  const [isOffline, setIsOffline] = useState(() => !navigator.onLine);

  useEffect(() => {
    const handleOffline = () => setIsOffline(true);
    const handleOnline = () => setIsOffline(false);

    window.addEventListener('offline', handleOffline);
    window.addEventListener('online', handleOnline);

    return () => {
      window.removeEventListener('offline', handleOffline);
      window.removeEventListener('online', handleOnline);
    };
  }, []);

  if (!isOffline) return null;

  return (
    <div className="offline-banner" role="status" aria-live="polite">
      You are offline. Some actions may fail until your connection is restored.
    </div>
  );
}
