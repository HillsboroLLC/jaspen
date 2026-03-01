import React, { createContext, useContext, useState } from 'react';

const AdminContext = createContext();

export const AdminProvider = ({ children }) => {
  const [adminSettings, setAdminSettings] = useState({
    guidedModeEnabled: true, // Global default
    userSettings: {} // Per-user overrides: { userId: { guidedModeEnabled: true/false } }
  });

  return (
    <AdminContext.Provider value={{ adminSettings, setAdminSettings }}>
      {children}
    </AdminContext.Provider>
  );
};

export const useAdminSettings = () => {
  const context = useContext(AdminContext);
  if (!context) {
    throw new Error('useAdminSettings must be used within AdminProvider');
  }
  return context;
};
