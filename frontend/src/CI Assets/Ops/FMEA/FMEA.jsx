// ============================================================================
// File: src/Ops/FMEA/FMEA.jsx
// Purpose: FMEA tool page with floating chat via ResourcePageWrapper (parent),
//          full-width info card, and solid progress bar (no gradients).
// ============================================================================

import React, { useState, useCallback, useEffect } from 'react';
import { useAdminSettings } from '../context/AdminContext';
import ResourcePageWrapper from '../../All/components/ResourcePageWrapper';
import '../styles/index.css';
import '@fortawesome/fontawesome-free/css/all.min.css'; // icons

const FMEA = () => {
  const { adminSettings } = useAdminSettings(); // why: wrapper reads admin flags

  const [fmeaData, setFmeaData] = useState({
    processName: '',
    processOwner: '',
    fmeaTeam: '',
    dateCreated: new Date().toISOString().split('T')[0],
    lastUpdated: new Date().toISOString().split('T')[0],
    fmeaItems: [
      {
        id: 1,
        processStep: '',
        processFunction: '',
        failureMode: '',
        effectsOfFailure: '',
        severity: 1,
        causes: '',
        occurrence: 1,
        currentControls: '',
        detection: 1,
        rpn: 1,
        recommendedActions: '',
        responsibility: '',
        targetDate: '',
        actionsTaken: '',
        newSeverity: 1,
        newOccurrence: 1,
        newDetection: 1,
        newRpn: 1
      }
    ]
  });

  const [completionPercentage, setCompletionPercentage] = useState(0);

  // Optional: Kii/AI data integration
  const handleKiiDataUpdate = useCallback((extracted) => {
    const updates = {};
    if (extracted.processName) updates.processName = extracted.processName;
    if (extracted.processOwner) updates.processOwner = extracted.processOwner;
    if (extracted.team || extracted.fmeaTeam) updates.fmeaTeam = extracted.team || extracted.fmeaTeam;

    // Example: append a new item if extracted failure mode is provided
    if (extracted.failureMode) {
      const nextId = Math.max(...fmeaData.fmeaItems.map(i => i.id)) + 1;
      updates.fmeaItems = [
        ...fmeaData.fmeaItems,
        {
          id: nextId,
          processStep: extracted.processStep || '',
          processFunction: extracted.processFunction || '',
          failureMode: extracted.failureMode || '',
          effectsOfFailure: extracted.effects || '',
          severity: typeof extracted.severity === 'number' ? extracted.severity : 1,
          causes: extracted.causes || '',
          occurrence: typeof extracted.occurrence === 'number' ? extracted.occurrence : 1,
          currentControls: extracted.currentControls || '',
          detection: typeof extracted.detection === 'number' ? extracted.detection : 1,
          rpn: 1,
          recommendedActions: extracted.recommendedActions || '',
          responsibility: extracted.responsibility || '',
          targetDate: extracted.targetDate || '',
          actionsTaken: extracted.actionsTaken || '',
          newSeverity: 1,
          newOccurrence: 1,
          newDetection: 1,
          newRpn: 1
        }
      ];
    }

    if (Object.keys(updates).length) {
      setFmeaData(prev => ({
        ...prev,
        ...updates,
        lastUpdated: new Date().toISOString().split('T')[0]
      }));
    }
  }, [fmeaData.fmeaItems]);

  const calculateRPN = useCallback((s, o, d) => s * o * d, []);

  useEffect(() => {
    let total = 0;
    let done = 0;

    total += 4;
    if (fmeaData.processName) done++;
    if (fmeaData.processOwner) done++;
    if (fmeaData.fmeaTeam) done++;
    if (fmeaData.dateCreated) done++;

    fmeaData.fmeaItems.forEach(item => {
      const fields = ['processStep', 'failureMode', 'effectsOfFailure', 'causes', 'currentControls'];
      total += fields.length + 3;
      fields.forEach(f => { if (item[f] && item[f].trim() !== '') done++; });
      done += 3;
    });

    setCompletionPercentage(total > 0 ? Math.round((done / total) * 100) : 0);
  }, [fmeaData]);

  const handleProcessInfoChange = useCallback((field, value) => {
    setFmeaData(prev => ({
      ...prev,
      [field]: value,
      lastUpdated: new Date().toISOString().split('T')[0]
    }));
  }, []);

  const handleFmeaItemChange = useCallback((id, field, value) => {
    setFmeaData(prev => ({
      ...prev,
      fmeaItems: prev.fmeaItems.map(item => {
        if (item.id !== id) return item;
        const next = { ...item, [field]: value };

        // keep risk scores in sync
        if (['severity', 'occurrence', 'detection'].includes(field)) {
          next.rpn = calculateRPN(
            field === 'severity' ? parseInt(value) : item.severity,
            field === 'occurrence' ? parseInt(value) : item.occurrence,
            field === 'detection' ? parseInt(value) : item.detection
          );
        }
        if (['newSeverity', 'newOccurrence', 'newDetection'].includes(field)) {
          next.newRpn = calculateRPN(
            field === 'newSeverity' ? parseInt(value) : item.newSeverity,
            field === 'newOccurrence' ? parseInt(value) : item.newOccurrence,
            field === 'newDetection' ? parseInt(value) : item.newDetection
          );
        }
        return next;
      }),
      lastUpdated: new Date().toISOString().split('T')[0]
    }));
  }, [calculateRPN]);

  const addFmeaItem = useCallback(() => {
    const newId = Math.max(...fmeaData.fmeaItems.map(i => i.id)) + 1;
    setFmeaData(prev => ({
      ...prev,
      fmeaItems: [
        ...prev.fmeaItems,
        {
          id: newId,
          processStep: '',
          processFunction: '',
          failureMode: '',
          effectsOfFailure: '',
          severity: 1,
          causes: '',
          occurrence: 1,
          currentControls: '',
          detection: 1,
          rpn: 1,
          recommendedActions: '',
          responsibility: '',
          targetDate: '',
          actionsTaken: '',
          newSeverity: 1,
          newOccurrence: 1,
          newDetection: 1,
          newRpn: 1
        }
      ],
      lastUpdated: new Date().toISOString().split('T')[0]
    }));
  }, [fmeaData.fmeaItems]);

  const removeFmeaItem = useCallback((id) => {
    if (fmeaData.fmeaItems.length <= 1) return;
    setFmeaData(prev => ({
      ...prev,
      fmeaItems: prev.fmeaItems.filter(i => i.id !== id),
      lastUpdated: new Date().toISOString().split('T')[0]
    }));
  }, [fmeaData.fmeaItems.length]);

  const getRpnRiskLevel = useCallback((rpn) => {
    if (rpn >= 300) return { level: 'High', color: 'var(--lss-error)' };
    if (rpn >= 100) return { level: 'Medium', color: 'var(--lss-warning)' };
    return { level: 'Low', color: 'var(--lss-success)' };
  }, []);

  const riskSummary = (() => {
    const s = { high: 0, medium: 0, low: 0 };
    fmeaData.fmeaItems.forEach(item => {
      const risk = getRpnRiskLevel(item.rpn);
      if (risk.level === 'High') s.high++;
      else if (risk.level === 'Medium') s.medium++;
      else s.low++;
    });
    return s;
  })();

  const handleSave = () => console.log('Saving FMEA draft:', fmeaData);
  const handleExport = () => console.log('Exporting FMEA to PDF:', fmeaData);

  return (
    <ResourcePageWrapper
      pageName="FMEA"
      toolName="FMEA"
      adminSettings={adminSettings}
      currentData={fmeaData}
      onDataUpdate={handleKiiDataUpdate}
    >
      <div className="tool-container">
        {/* Header */}
        <div className="tool-header">
          <div className="tool-header-content">
            <h1>FMEA Analysis</h1>
            <div className="tool-progress-section">
              <div
                className="tool-progress-bar"
                style={{ background: 'var(--lss-gray-200)', backgroundImage: 'none' }}
              >
                <div
                  className="tool-progress-fill"
                  style={{ width: `${completionPercentage}%`, background: 'var(--lss-primary)', backgroundImage: 'none' }}
                />
              </div>
              <span className="tool-progress-text">{completionPercentage}% Complete</span>
            </div>
          </div>
          <div className="tool-header-actions">
            <button className="tool-btn tool-btn-primary" onClick={handleSave}>
              <i className="fas fa-save"></i> Save Draft
            </button>
            <button className="tool-btn tool-btn-accent" onClick={handleExport}>
              <i className="fas fa-download"></i> Export PDF
            </button>
          </div>
        </div>

        {/* Main Content */}
        <div className="tool-main-content">
          {/* Top Section — single column, full width */}
          <div className="tool-top-section" style={{ display: 'block', marginBottom: 0 }}>
            <div className="tool-process-info-card" style={{ width: '100%' }}>
              <h2>FMEA Information</h2>

              <div className="tool-field-group">
                <label className="tool-field-label">
                  Process Name <span className="tool-field-required">*</span>
                </label>
                <input
                  type="text"
                  className="tool-input"
                  value={fmeaData.processName}
                  onChange={(e) => handleProcessInfoChange('processName', e.target.value)}
                  placeholder="Enter the process name for FMEA analysis"
                />
              </div>

              <div className="tool-field-row">
                <div className="tool-field-group">
                  <label className="tool-field-label">
                    Process Owner <span className="tool-field-required">*</span>
                  </label>
                  <input
                    type="text"
                    className="tool-input"
                    value={fmeaData.processOwner}
                    onChange={(e) => handleProcessInfoChange('processOwner', e.target.value)}
                    placeholder="Who owns this process?"
                  />
                </div>
                <div className="tool-field-group">
                  <label className="tool-field-label">
                    FMEA Team <span className="tool-field-required">*</span>
                  </label>
                  <input
                    type="text"
                    className="tool-input"
                    value={fmeaData.fmeaTeam}
                    onChange={(e) => handleProcessInfoChange('fmeaTeam', e.target.value)}
                    placeholder="List team members involved in this FMEA"
                  />
                </div>
              </div>

              <div className="tool-field-row">
                <div className="tool-field-group">
                  <label className="tool-field-label">Date Created</label>
                  <input
                    type="date"
                    className="tool-input"
                    value={fmeaData.dateCreated}
                    onChange={(e) => handleProcessInfoChange('dateCreated', e.target.value)}
                  />
                </div>
                <div className="tool-field-group">
                  <label className="tool-field-label">Last Updated</label>
                  <input type="date" className="tool-input" value={fmeaData.lastUpdated} readOnly />
                </div>
              </div>
            </div>
          </div>

          {/* Risk Summary */}
          <div className="tool-card">
            <h2>Risk Summary</h2>
            <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
              <div className="text-center p-6 bg-gray-50 rounded-xl border">
                <div className="text-4xl font-bold mb-2 risk-high">{riskSummary.high}</div>
                <div className="text-sm font-semibold text-gray-600">High Risk Items</div>
                <div className="text-xs text-gray-500 mt-1">RPN ≥ 300</div>
              </div>
              <div className="text-center p-6 bg-gray-50 rounded-xl border">
                <div className="text-4xl font-bold mb-2 risk-medium">{riskSummary.medium}</div>
                <div className="text-sm font-semibold text-gray-600">Medium Risk Items</div>
                <div className="text-xs text-gray-500 mt-1">RPN 100-299</div>
              </div>
              <div className="text-center p-6 bg-gray-50 rounded-xl border">
                <div className="text-4xl font-bold mb-2 risk-low">{riskSummary.low}</div>
                <div className="text-sm font-semibold text-gray-600">Low Risk Items</div>
                <div className="text-xs text-gray-500 mt-1">RPN &lt; 100</div>
              </div>
            </div>
          </div>

          {/* FMEA Table */}
          <div className="tool-card">
            <div className="tool-table-header">
              <h2>FMEA Analysis Table</h2>
              <button className="tool-btn tool-btn-success" onClick={addFmeaItem}>
                <i className="fas fa-plus"></i> Add FMEA Item
              </button>
            </div>

            <div className="tool-table-container">
              <div className="tool-table" style={{ minWidth: '1400px' }}>
                {/* Header */}
                <div
                  className="grid"
                  style={{
                    gridTemplateColumns:
                      '150px 150px 150px 50px 150px 50px 150px 50px 80px 200px 80px',
                    backgroundColor: 'var(--lss-gray-100)',
                    borderBottom: '1px solid var(--lss-gray-200)'
                  }}
                >
                  <div className="p-4 text-xs font-semibold text-gray-700 text-center border-r border-gray-200">Process Step</div>
                  <div className="p-4 text-xs font-semibold text-gray-700 text-center border-r border-gray-200">Failure Mode</div>
                  <div className="p-4 text-xs font-semibold text-gray-700 text-center border-r border-gray-200">Effects</div>
                  <div className="p-4 text-xs font-semibold text-gray-700 text-center border-r border-gray-200">S</div>
                  <div className="p-4 text-xs font-semibold text-gray-700 text-center border-r border-gray-200">Causes</div>
                  <div className="p-4 text-xs font-semibold text-gray-700 text-center border-r border-gray-200">O</div>
                  <div className="p-4 text-xs font-semibold text-gray-700 text-center border-r border-gray-200">Controls</div>
                  <div className="p-4 text-xs font-semibold text-gray-700 text-center border-r border-gray-200">D</div>
                  <div className="p-4 text-xs font-semibold text-gray-700 text-center border-r border-gray-200">RPN</div>
                  <div className="p-4 text-xs font-semibold text-gray-700 text-center border-r border-gray-200">Recommended Actions</div>
                  <div className="p-4 text-xs font-semibold text-gray-700 text-center">Actions</div>
                </div>

                {/* Rows */}
                <div className="flex flex-col">
                  {fmeaData.fmeaItems.map((item, index) => {
                    const riskLevel = getRpnRiskLevel(item.rpn);
                    return (
                      <div
                        key={item.id}
                        className={`grid hover:bg-gray-50 ${index !== fmeaData.fmeaItems.length - 1 ? 'border-b border-gray-200' : ''}`}
                        style={{ gridTemplateColumns: '150px 150px 150px 50px 150px 50px 150px 50px 80px 200px 80px' }}
                      >
                        <div className="p-3 border-r border-gray-200 flex items-center">
                          <textarea
                            className="w-full text-xs border border-gray-300 rounded p-2 resize-none"
                            value={item.processStep}
                            onChange={(e) => handleFmeaItemChange(item.id, 'processStep', e.target.value)}
                            placeholder="Process step"
                            rows={2}
                          />
                        </div>
                        <div className="p-3 border-r border-gray-200 flex items-center">
                          <textarea
                            className="w-full text-xs border border-gray-300 rounded p-2 resize-none"
                            value={item.failureMode}
                            onChange={(e) => handleFmeaItemChange(item.id, 'failureMode', e.target.value)}
                            placeholder="Failure mode"
                            rows={2}
                          />
                        </div>
                        <div className="p-3 border-r border-gray-200 flex items-center">
                          <textarea
                            className="w-full text-xs border border-gray-300 rounded p-2 resize-none"
                            value={item.effectsOfFailure}
                            onChange={(e) => handleFmeaItemChange(item.id, 'effectsOfFailure', e.target.value)}
                            placeholder="Effects"
                            rows={2}
                          />
                        </div>
                        <div className="p-3 border-r border-gray-200 flex items-center justify-center">
                          <select
                            className="w-full text-xs border border-gray-300 rounded p-1"
                            value={item.severity}
                            onChange={(e) => handleFmeaItemChange(item.id, 'severity', parseInt(e.target.value))}
                          >
                            {[1,2,3,4,5,6,7,8,9,10].map(num => (<option key={num} value={num}>{num}</option>))}
                          </select>
                        </div>
                        <div className="p-3 border-r border-gray-200 flex items-center">
                          <textarea
                            className="w-full text-xs border border-gray-300 rounded p-2 resize-none"
                            value={item.causes}
                            onChange={(e) => handleFmeaItemChange(item.id, 'causes', e.target.value)}
                            placeholder="Causes"
                            rows={2}
                          />
                        </div>
                        <div className="p-3 border-r border-gray-200 flex items-center justify-center">
                          <select
                            className="w-full text-xs border border-gray-300 rounded p-1"
                            value={item.occurrence}
                            onChange={(e) => handleFmeaItemChange(item.id, 'occurrence', parseInt(e.target.value))}
                          >
                            {[1,2,3,4,5,6,7,8,9,10].map(num => (<option key={num} value={num}>{num}</option>))}
                          </select>
                        </div>
                        <div className="p-3 border-r border-gray-200 flex items-center">
                          <textarea
                            className="w-full text-xs border border-gray-300 rounded p-2 resize-none"
                            value={item.currentControls}
                            onChange={(e) => handleFmeaItemChange(item.id, 'currentControls', e.target.value)}
                            placeholder="Controls"
                            rows={2}
                          />
                        </div>
                        <div className="p-3 border-r border-gray-200 flex items-center justify-center">
                          <select
                            className="w-full text-xs border border-gray-300 rounded p-1"
                            value={item.detection}
                            onChange={(e) => handleFmeaItemChange(item.id, 'detection', parseInt(e.target.value))}
                          >
                            {[1,2,3,4,5,6,7,8,9,10].map(num => (<option key={num} value={num}>{num}</option>))}
                          </select>
                        </div>
                        <div className="p-3 border-r border-gray-200 flex items-center justify-center">
                          <div className="text-lg font-bold" style={{ color: riskLevel.color }}>
                            {item.rpn}
                          </div>
                        </div>
                        <div className="p-3 border-r border-gray-200 flex items-center">
                          <textarea
                            className="w-full text-xs border border-gray-300 rounded p-2 resize-none"
                            value={item.recommendedActions}
                            onChange={(e) => handleFmeaItemChange(item.id, 'recommendedActions', e.target.value)}
                            placeholder="Recommended actions"
                            rows={2}
                          />
                        </div>
                        <div className="p-3 flex items-center justify-center">
                          <button
                            type="button"
                            className="tool-remove-btn"
                            onClick={() => removeFmeaItem(item.id)}
                            disabled={fmeaData.fmeaItems.length <= 1}
                          >
                            <i className="fas fa-times"></i>
                          </button>
                        </div>
                      </div>
                    );
                  })}
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>
    </ResourcePageWrapper>
  );
};

export default FMEA;
