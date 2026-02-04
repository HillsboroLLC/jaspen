import React, { useState } from 'react';
import { useAdminSettings } from '../../context/AdminContext';
import './AdminSettingsPanel.css';

const AdminSettingsPanel = () => {
  const { adminSettings, updateAdminSettings, resetAdminSettings, loading, isOpsAdmin } = useAdminSettings();
  const [activeTab, setActiveTab] = useState('ai');
  const [saveStatus, setSaveStatus] = useState('');

  if (!isOpsAdmin) {
    return (
      <div className="ops-admin-settings-panel">
        <div className="access-denied">
          <i className="fas fa-lock" />
          <h3>Access Denied</h3>
          <p>You need Ops administrator privileges to access these settings.</p>
        </div>
      </div>
    );
  }

  const handleSettingChange = async (key, value) => {
    const success = await updateAdminSettings({ [key]: value });
    
    if (success) {
      setSaveStatus('saved');
      setTimeout(() => setSaveStatus(''), 2000);
    } else {
      setSaveStatus('error');
      setTimeout(() => setSaveStatus(''), 3000);
    }
  };

  const handleReset = () => {
    if (window.confirm('Are you sure you want to reset all Ops settings to defaults? This cannot be undone.')) {
      resetAdminSettings();
      setSaveStatus('reset');
      setTimeout(() => setSaveStatus(''), 2000);
    }
  };

  return (
    <div className="ops-admin-settings-panel">
      <div className="ops-admin-header">
        <h2>
          <i className="fas fa-cog" />
          Ops Admin Settings
        </h2>
        <div className="ops-admin-actions">
          <button 
            onClick={handleReset}
            className="btn-reset"
            disabled={loading}
          >
            <i className="fas fa-undo" />
            Reset to Defaults
          </button>
          {saveStatus && (
            <div className={`save-status ${saveStatus}`}>
              {saveStatus === 'saved' && <><i className="fas fa-check" /> Saved</>}
              {saveStatus === 'error' && <><i className="fas fa-exclamation-triangle" /> Error saving</>}
              {saveStatus === 'reset' && <><i className="fas fa-undo" /> Reset complete</>}
            </div>
          )}
        </div>
      </div>

      <div className="ops-admin-tabs">
        <button 
          className={`tab ${activeTab === 'ai' ? 'active' : ''}`}
          onClick={() => setActiveTab('ai')}
        >
          <i className="fas fa-robot" />
          AI Assistant
        </button>
        <button 
          className={`tab ${activeTab === 'tools' ? 'active' : ''}`}
          onClick={() => setActiveTab('tools')}
        >
          <i className="fas fa-tools" />
          Ops Tools
        </button>
        <button 
          className={`tab ${activeTab === 'access' ? 'active' : ''}`}
          onClick={() => setActiveTab('access')}
        >
          <i className="fas fa-users" />
          User Access
        </button>
      </div>

      <div className="ops-admin-content">
        {activeTab === 'ai' && (
          <div className="settings-section">
            <h3>AI Assistant Configuration</h3>
            
            <div className="setting-group">
              <label className="setting-label">
                <input
                  type="checkbox"
                  checked={adminSettings.guidedModeEnabled}
                  onChange={(e) => handleSettingChange('guidedModeEnabled', e.target.checked)}
                />
                <span className="checkmark"></span>
                Enable AI Assistant (FloatingAI) for Ops Tools
              </label>
              <p className="setting-description">
                Controls whether the AI assistant appears on Ops tool pages. Users cannot override this setting.
              </p>
            </div>

            <div className="setting-group">
              <label className="setting-label">AI Model</label>
              <select
                value={adminSettings.aiAssistantModel}
                onChange={(e) => handleSettingChange('aiAssistantModel', e.target.value)}
                className="setting-select"
              >
                <option value="gpt-4">GPT-4 (Recommended)</option>
                <option value="gpt-3.5-turbo">GPT-3.5 Turbo</option>
                <option value="claude-3">Claude 3</option>
              </select>
            </div>

            <div className="setting-group">
              <label className="setting-label">AI System Prompt</label>
              <textarea
                value={adminSettings.aiAssistantPrompt}
                onChange={(e) => handleSettingChange('aiAssistantPrompt', e.target.value)}
                className="setting-textarea"
                rows="4"
                placeholder="Enter the system prompt for the AI assistant..."
              />
              <p className="setting-description">
                This prompt defines how the AI assistant behaves across all Ops tools.
              </p>
            </div>
          </div>
        )}

        {activeTab === 'tools' && (
          <div className="settings-section">
            <h3>Ops Tools Controls</h3>
            
            <div className="setting-group">
              <label className="setting-label">
                <input
                  type="checkbox"
                  checked={adminSettings.statisticsEnabled}
                  onChange={(e) => handleSettingChange('statisticsEnabled', e.target.checked)}
                />
                <span className="checkmark"></span>
                Enable Statistics Tool
              </label>
            </div>

            <div className="setting-group">
              <label className="setting-label">
                <input
                  type="checkbox"
                  checked={adminSettings.lssToolsEnabled}
                  onChange={(e) => handleSettingChange('lssToolsEnabled', e.target.checked)}
                />
                <span className="checkmark"></span>
                Enable LSS (Lean Six Sigma) Tools
              </label>
            </div>

            <div className="setting-group">
              <label className="setting-label">
                <input
                  type="checkbox"
                  checked={adminSettings.comprehensiveAnalysisEnabled}
                  onChange={(e) => handleSettingChange('comprehensiveAnalysisEnabled', e.target.checked)}
                />
                <span className="checkmark"></span>
                Enable AI Comprehensive Analysis
              </label>
            </div>

            <div className="setting-group">
              <label className="setting-label">
                <input
                  type="checkbox"
                  checked={adminSettings.dataExportEnabled}
                  onChange={(e) => handleSettingChange('dataExportEnabled', e.target.checked)}
                />
                <span className="checkmark"></span>
                Allow Data Export
              </label>
            </div>

            <div className="setting-group">
              <label className="setting-label">
                <input
                  type="checkbox"
                  checked={adminSettings.advancedFeaturesEnabled}
                  onChange={(e) => handleSettingChange('advancedFeaturesEnabled', e.target.checked)}
                />
                <span className="checkmark"></span>
                Show Advanced Features
              </label>
            </div>

            <div className="setting-group">
              <label className="setting-label">Maximum File Size (MB)</label>
              <input
                type="number"
                value={adminSettings.maxFileSize / 1048576}
                onChange={(e) => handleSettingChange('maxFileSize', e.target.value * 1048576)}
                className="setting-input"
                min="1"
                max="100"
              />
            </div>
          </div>
        )}

        {activeTab === 'access' && (
          <div className="settings-section">
            <h3>User Access Controls</h3>
            
            <div className="setting-group">
              <label className="setting-label">
                <input
                  type="checkbox"
                  checked={adminSettings.allowUserOverride}
                  onChange={(e) => handleSettingChange('allowUserOverride', e.target.checked)}
                />
                <span className="checkmark"></span>
                Allow Users to Disable AI Assistant
              </label>
              <p className="setting-description">
                If enabled, users can turn off the AI assistant for their own sessions.
              </p>
            </div>

            <div className="setting-group">
              <label className="setting-label">
                <input
                  type="checkbox"
                  checked={adminSettings.requireAdminApproval}
                  onChange={(e) => handleSettingChange('requireAdminApproval', e.target.checked)}
                />
                <span className="checkmark"></span>
                Require Admin Approval for Advanced Features
              </label>
            </div>

            <div className="setting-group">
              <label className="setting-label">
                <input
                  type="checkbox"
                  checked={adminSettings.showHelpButtons}
                  onChange={(e) => handleSettingChange('showHelpButtons', e.target.checked)}
                />
                <span className="checkmark"></span>
                Show Help Buttons
              </label>
            </div>

            <div className="setting-group">
              <label className="setting-label">
                <input
                  type="checkbox"
                  checked={adminSettings.showAdvancedOptions}
                  onChange={(e) => handleSettingChange('showAdvancedOptions', e.target.checked)}
                />
                <span className="checkmark"></span>
                Show Advanced Options to Users
              </label>
            </div>
          </div>
        )}
      </div>
    </div>
  );
};

export default AdminSettingsPanel;
