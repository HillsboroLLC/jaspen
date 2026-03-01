import React, { useState, useEffect } from 'react';
import { useAdminSettings } from '../context/AdminContext';
import ResourcePageWrapper from '../../All/components/ResourcePageWrapper';
import styles from './ProjectCharter.module.css';

const ProjectCharter = () => {
  const { adminSettings } = useAdminSettings();

  // Form state for Project Charter fields
  const [charterData, setCharterData] = useState({
    projectName: '',
    projectLead: '',
    sponsor: '',
    teamMembers: [],
    businessCase: '',
    problemStatement: '',
    goalStatement: '',
    scope: {
      inScope: '',
      outOfScope: ''
    },
    timeline: {
      startDate: '',
      endDate: '',
      milestones: []
    },
    resources: {
      budget: '',
      personnel: '',
      equipment: ''
    },
    successMetrics: [],
    risks: [],
    stakeholders: []
  });

  const [completionPercentage, setCompletionPercentage] = useState(0);

  // Mock AI suggestions state (kept — this isn't chat UI)
  const [aiSuggestions, setAiSuggestions] = useState({
    problemStatement: '',
    goalStatement: '',
    scope: '',
    metrics: []
  });

  // Calculate completion percentage
  useEffect(() => {
    const calculateCompletion = () => {
      const requiredFields = [
        charterData.projectName,
        charterData.projectLead,
        charterData.sponsor,
        charterData.businessCase,
        charterData.problemStatement,
        charterData.goalStatement,
        charterData.scope.inScope,
        charterData.timeline.startDate,
        charterData.timeline.endDate
      ];
      const completedFields = requiredFields.filter(field => field && field.trim() !== '').length;
      const percentage = Math.round((completedFields / requiredFields.length) * 100);
      setCompletionPercentage(percentage);
    };

    calculateCompletion();
  }, [charterData]);

  // Handle form field changes
  const handleFieldChange = (field, value) => {
    if (field.includes('.')) {
      const [parent, child] = field.split('.');
      setCharterData(prev => ({
        ...prev,
        [parent]: {
          ...prev[parent],
          [child]: value
        }
      }));
    } else {
      setCharterData(prev => ({
        ...prev,
        [field]: value
      }));
    }
  };

  // Simple suggestion applier (no chat)
  const applySuggestion = (field, suggestion) => {
    handleFieldChange(field, suggestion);
  };

  // Generate basic suggestions from business case (optional helper)
  const generateSuggestions = () => {
    if (charterData.businessCase && !charterData.problemStatement) {
      setAiSuggestions(prev => ({
        ...prev,
        problemStatement: `Based on your business case, consider: "Currently, ${charterData.businessCase.toLowerCase()} is causing delays and inefficiencies, but we need streamlined processes to improve customer satisfaction and reduce costs."`
      }));
    }
  };

  useEffect(() => {
    generateSuggestions();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [charterData.businessCase]);

  // Actions
  const handleSave = () => {
    console.log('Saving Project Charter draft:', charterData);
    // Implement save functionality
  };

  const handleExport = () => {
    console.log('Exporting Project Charter to PDF:', charterData);
    // Implement export functionality
  };

  return (
    <ResourcePageWrapper
      pageName="Project Charter"
      toolName="projectCharter"
      adminSettings={adminSettings}
    >
      <div className={styles.projectCharterContainer || styles.rcaContainer}>
        {/* Header */}
        <div className={styles.header}>
          <div className={styles.headerContent}>
            <h1>Project Charter</h1>
            <div className={styles.progressSection}>
              <div className={styles.progressBar}>
                <div
                  className={styles.progressFill}
                  style={{ width: `${completionPercentage}%` }}
                ></div>
              </div>
              <span className={styles.progressText}>{completionPercentage}% Complete</span>
            </div>
          </div>
          <div className={styles.headerActions}>
            <button className={styles.saveBtn} onClick={handleSave}>
              <i className="fas fa-save"></i> Save Draft
            </button>
            <button className={styles.exportBtn} onClick={handleExport}>
              <i className="fas fa-download"></i> Export PDF
            </button>
          </div>
        </div>

        {/* Main Content (full width; no chat, no two-column wrapper) */}
        <div className={styles.mainContent} style={{ display: 'block' }}>
          {/* Form Section */}
          <div className={styles.formSection}>
            <div className={styles.formCard}>
              <h2>Project Information</h2>

              {/* Project Name */}
              <div className={styles.fieldGroup}>
                <label className={styles.fieldLabel}>
                  Project Name <span className={styles.required}>*</span>
                </label>
                <input
                  type="text"
                  className={styles.textInput}
                  value={charterData.projectName}
                  onChange={(e) => handleFieldChange('projectName', e.target.value)}
                  placeholder="Enter a descriptive project name"
                />
              </div>

              {/* Project Lead & Sponsor */}
              <div className={styles.fieldRow}>
                <div className={styles.fieldGroup}>
                  <label className={styles.fieldLabel}>
                    Project Lead <span className={styles.required}>*</span>
                  </label>
                  <input
                    type="text"
                    className={styles.textInput}
                    value={charterData.projectLead}
                    onChange={(e) => handleFieldChange('projectLead', e.target.value)}
                    placeholder="Project lead name"
                  />
                </div>
                <div className={styles.fieldGroup}>
                  <label className={styles.fieldLabel}>
                    Executive Sponsor <span className={styles.required}>*</span>
                  </label>
                  <input
                    type="text"
                    className={styles.textInput}
                    value={charterData.sponsor}
                    onChange={(e) => handleFieldChange('sponsor', e.target.value)}
                    placeholder="Executive sponsor name"
                  />
                </div>
              </div>

              {/* Business Case */}
              <div className={styles.fieldGroup}>
                <label className={styles.fieldLabel}>
                  Business Case <span className={styles.required}>*</span>
                </label>
                <textarea
                  className={styles.textArea}
                  value={charterData.businessCase}
                  onChange={(e) => handleFieldChange('businessCase', e.target.value)}
                  placeholder="Describe the business justification for this project..."
                  rows={4}
                />
              </div>

              {/* Problem Statement (with optional suggestion) */}
              <div className={styles.fieldGroup}>
                <label className={styles.fieldLabel}>
                  Problem Statement <span className={styles.required}>*</span>
                </label>
                {aiSuggestions.problemStatement && (
                  <div className={styles.aiSuggestion}>
                    <div className={styles.suggestionHeader}>
                      <i className="fas fa-lightbulb"></i>
                      <span>Suggestion</span>
                    </div>
                    <p>{aiSuggestions.problemStatement}</p>
                    <button
                      className={styles.applySuggestionBtn}
                      onClick={() => applySuggestion('problemStatement', aiSuggestions.problemStatement)}
                    >
                      Apply Suggestion
                    </button>
                  </div>
                )}
                <textarea
                  className={styles.textArea}
                  value={charterData.problemStatement}
                  onChange={(e) => handleFieldChange('problemStatement', e.target.value)}
                  placeholder="Clearly define the problem this project will solve..."
                  rows={4}
                />
              </div>

              {/* Goal Statement */}
              <div className={styles.fieldGroup}>
                <label className={styles.fieldLabel}>
                  Goal Statement <span className={styles.required}>*</span>
                </label>
                <textarea
                  className={styles.textArea}
                  value={charterData.goalStatement}
                  onChange={(e) => handleFieldChange('goalStatement', e.target.value)}
                  placeholder="Define SMART goals for this project..."
                  rows={3}
                />
              </div>

              {/* Scope */}
              <div className={styles.scopeSection}>
                <h3>Project Scope</h3>
                <div className={styles.fieldRow}>
                  <div className={styles.fieldGroup}>
                    <label className={styles.fieldLabel}>In Scope</label>
                    <textarea
                      className={styles.textArea}
                      value={charterData.scope.inScope}
                      onChange={(e) => handleFieldChange('scope.inScope', e.target.value)}
                      placeholder="What will be included in this project..."
                      rows={4}
                    />
                  </div>
                  <div className={styles.fieldGroup}>
                    <label className={styles.fieldLabel}>Out of Scope</label>
                    <textarea
                      className={styles.textArea}
                      value={charterData.scope.outOfScope}
                      onChange={(e) => handleFieldChange('scope.outOfScope', e.target.value)}
                      placeholder="What will NOT be included..."
                      rows={4}
                    />
                  </div>
                </div>
              </div>

              {/* Timeline */}
              <div className={styles.timelineSection}>
                <h3>Project Timeline</h3>
                <div className={styles.fieldRow}>
                  <div className={styles.fieldGroup}>
                    <label className={styles.fieldLabel}>Start Date</label>
                    <input
                      type="date"
                      className={styles.dateInput}
                      value={charterData.timeline.startDate}
                      onChange={(e) => handleFieldChange('timeline.startDate', e.target.value)}
                    />
                  </div>
                  <div className={styles.fieldGroup}>
                    <label className={styles.fieldLabel}>Target End Date</label>
                    <input
                      type="date"
                      className={styles.dateInput}
                      value={charterData.timeline.endDate}
                      onChange={(e) => handleFieldChange('timeline.endDate', e.target.value)}
                    />
                  </div>
                </div>
              </div>

              {/* Resources */}
              <div className={styles.resourcesSection}>
                <h3>Required Resources</h3>
                <div className={styles.fieldGroup}>
                  <label className={styles.fieldLabel}>Budget</label>
                  <input
                    type="text"
                    className={styles.textInput}
                    value={charterData.resources.budget}
                    onChange={(e) => handleFieldChange('resources.budget', e.target.value)}
                    placeholder="Estimated budget requirements"
                  />
                </div>
                <div className={styles.fieldGroup}>
                  <label className={styles.fieldLabel}>Personnel</label>
                  <textarea
                    className={styles.textArea}
                    value={charterData.resources.personnel}
                    onChange={(e) => handleFieldChange('resources.personnel', e.target.value)}
                    placeholder="Team members and their roles..."
                    rows={3}
                  />
                </div>
              </div>
            </div>
          </div>
        </div>

        {/* Footer Actions */}
        <div className={styles.footer}>
          <div className={styles.footerContent}>
            <div className={styles.completionStatus}>
              <i className={`fas ${completionPercentage === 100 ? 'fa-check-circle' : 'fa-clock'}`}></i>
              <span>
                {completionPercentage === 100
                  ? 'Charter Complete - Ready for Review'
                  : `${completionPercentage}% Complete`
                }
              </span>
            </div>
            <div className={styles.footerActions}>
              <button className={styles.secondaryBtn}>
                <i className="fas fa-eye"></i> Preview
              </button>
              <button
                className={styles.primaryBtn}
                disabled={completionPercentage < 100}
              >
                <i className="fas fa-check"></i> Submit for Review
              </button>
            </div>
          </div>
        </div>
      </div>
    </ResourcePageWrapper>
  );
};

export default ProjectCharter;
