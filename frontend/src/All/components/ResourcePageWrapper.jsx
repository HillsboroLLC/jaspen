import React, { useState, useEffect } from 'react';
import FloatingAI from './FloatingAI/FloatingAI';

const ResourcePageWrapper = ({ 
  children, 
  pageName, 
  toolName,
  adminSettings = null,
  statisticalContext = null  // NEW: Accept statistical context for Statistics tool
}) => {
  const [isGuidedModeEnabled, setIsGuidedModeEnabled] = useState(false);

  // Check admin settings for guided mode
  useEffect(() => {
    // This would typically come from your admin settings API/context
    const checkGuidedModeSettings = () => {
      try {
        // Only admin can control guided mode - no user override
        const adminGuidedMode = adminSettings?.guidedModeEnabled ?? true; // Default to enabled
        setIsGuidedModeEnabled(adminGuidedMode);
      } catch (error) {
        console.error('Error checking guided mode settings:', error);
        setIsGuidedModeEnabled(false);
      }
    };

    checkGuidedModeSettings();
  }, [adminSettings]);

  return (
    <div style={{ position: 'relative', minHeight: '100vh' }}>
      {/* Main page content */}
      {children}
      
      {/* Floating AI Guide - only shows if admin has enabled guided mode */}
      <FloatingAI 
        isGuidedMode={isGuidedModeEnabled}
        currentPage={pageName}
        currentTool={toolName}
        statisticalContext={statisticalContext}  // Pass statistical context to FloatingAI
      />
    </div>
  );
};

export default ResourcePageWrapper;
