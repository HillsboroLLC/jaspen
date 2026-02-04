// ============================================================================
// File: ReadinessSidebar.jsx - ENHANCED A+ VERSION
// Purpose: Readiness indicator sidebar with expandable categories and micro elements
// Features:
// - Expandable/collapsible macro categories
// - Hyphen (-) for incomplete, checkmark (✓) for complete
// - Color-coded progress indicators
// - Detailed micro element tracking
// - Foundation for Phase 2/3 enhancements
// ============================================================================
import React, { useState } from 'react';
import { FontAwesomeIcon } from '@fortawesome/react-fontawesome';
import { faCheck, faMinus, faChevronDown, faChevronRight } from '@fortawesome/free-solid-svg-icons';
import '../styles/MarketIQ.css';

// Micro element display names (user-friendly labels)
const MICRO_LABELS = {
  // Business Description
  overview: 'Business Overview',
  mission_vision: 'Mission & Vision',
  product_service: 'Product/Service',
  value_proposition: 'Value Proposition',
  unique_selling_points: 'Unique Selling Points',
  
  // Target Market
  customer_segment: 'Customer Segment',
  demographics: 'Demographics',
  geographic_region: 'Geographic Region',
  industry_vertical: 'Industry Vertical',
  market_size: 'Market Size',
  
  // Revenue Model
  pricing_strategy: 'Pricing Strategy',
  revenue_streams: 'Revenue Streams',
  business_model: 'Business Model',
  unit_economics: 'Unit Economics',
  
  // Financial Metrics
  revenue_figures: 'Revenue Figures',
  profitability: 'Profitability',
  margins: 'Margins',
  growth_rate: 'Growth Rate',
  burn_rate: 'Burn Rate',
  
  // Timeline
  launch_date: 'Launch Date',
  milestones: 'Milestones',
  phases: 'Phases',
  duration: 'Duration',
  
  // Budget
  total_budget: 'Total Budget',
  allocation: 'Budget Allocation',
  funding_source: 'Funding Source',
  cost_structure: 'Cost Structure',
  
  // Competition
  competitors: 'Competitors',
  market_position: 'Market Position',
  differentiation: 'Differentiation',
  
  // Team
  leadership: 'Leadership',
  team_size: 'Team Size',
  key_roles: 'Key Roles',
  expertise: 'Expertise'
};

// Category display names
const CATEGORY_LABELS = {
  business_description: 'Business Description',
  target_market: 'Target Market',
  revenue_model: 'Revenue Model',
  financial_metrics: 'Financial Metrics',
  timeline: 'Timeline',
  budget: 'Budget',
  competition: 'Competition',
  team: 'Team & Resources'
};

export default function ReadinessSidebar({ readiness, collectedData, uiReadiness }) {
  // Track which categories are expanded
  const [expandedCategories, setExpandedCategories] = useState({});
  
  // Helper functions
  const clamp = (v, lo = 0, hi = 100) => Math.min(hi, Math.max(lo, v));
  const isNum = (v) => typeof v === 'number' && Number.isFinite(v);

  // Toggle category expansion
  const toggleCategory = (key) => {
    setExpandedCategories(prev => ({
      ...prev,
      [key]: !prev[key]
    }));
  };

  // Extract categories from readiness object
  const categories = readiness?.categories || [];
  
  // Calculate overall readiness percent
  const computeReadinessPercent = (raw) => {
    if (raw && typeof raw === 'object') {
      const c = Number.isFinite(raw.collected) ? raw.collected : 0;
      const t = Number.isFinite(raw.total) ? raw.total : 0;
      if (t > 0) return clamp(Math.round((c / t) * 100));
    }
    if (isNum(raw)) return clamp(Math.round(raw));
    
    // Fallback: calculate from categories
    if (categories.length > 0) {
      const totalWeight = categories.reduce((sum, cat) => sum + (cat.weight || 0), 0);
      const weightedSum = categories.reduce((sum, cat) => {
        const percent = cat.percent || 0;
        const weight = cat.weight || 0;
        return sum + ((percent / 100) * weight);
      }, 0);
      return clamp(Math.round((weightedSum / totalWeight) * 100));
    }
    
    return 0;
  };

const readinessPercent = Number.isFinite(uiReadiness)
  ? clamp(Math.round(uiReadiness))
  : computeReadinessPercent(readiness?.percent ?? readiness);

  // Progress bar color based on percentage
  const getProgressColor = (percent) => {
    if (percent >= 90) return '#10b981'; // Green
    if (percent >= 60) return '#f59e0b'; // Amber
    if (percent >= 25) return '#3b82f6'; // Blue (in progress)
    return '#ef4444'; // Red
  };

  // Get status text
  const getStatusText = (percent) => {
    if (percent >= 90) return 'Ready to analyze';
    if (percent >= 60) return 'Almost ready';
    if (percent >= 25) return 'Making progress';
    return 'Gathering information';
  };

  return (
    <div className="readiness-sidebar">
      <div className="readiness-header">
        <h3>Analysis Readiness</h3>
      </div>

      {/* Overall Progress Bar */}
      <div className="readiness-progress-section">
        <div className="readiness-percentage">{readinessPercent}%</div>
        <div className="readiness-progress-bar">
          <div
            className="readiness-progress-fill"
            style={{
              width: `${readinessPercent}%`,
              backgroundColor: getProgressColor(readinessPercent)
            }}
          />
        </div>
        <div className="readiness-status-text">
          {getStatusText(readinessPercent)}
        </div>
      </div>

      {/* Expandable Categories List */}
      <div className="readiness-categories-section">
        <h4>Information Categories</h4>
        
        {categories.length === 0 ? (
          <div className="readiness-empty">
            Start the conversation to begin tracking progress.
          </div>
        ) : (
          <div className="readiness-categories-list">
            {categories.map((category) => {
              const isExpanded = expandedCategories[category.key];
              const categoryPercent = category.percent || 0;
              const isComplete = categoryPercent >= 100;
              const micros = category.micros || [];
              
              return (
                <div key={category.key} className="readiness-category-item">
                  {/* Category Header - Clickable */}
                  <div 
                    className="readiness-category-header"
                    onClick={() => toggleCategory(category.key)}
                    style={{ cursor: 'pointer' }}
                  >
                    {/* Expand/Collapse Icon */}
                    <FontAwesomeIcon 
                      icon={isExpanded ? faChevronDown : faChevronRight}
                      className="readiness-expand-icon"
                      style={{ 
                        width: '12px',
                        marginRight: '8px',
                        color: '#64748b'
                      }}
                    />
                    
                    {/* Status Icon: Hyphen or Checkmark */}
                    <div className="readiness-category-icon">
                      {isComplete ? (
                        <FontAwesomeIcon 
                          icon={faCheck} 
                          style={{ color: '#10b981', fontSize: '14px' }}
                        />
                      ) : (
                        <FontAwesomeIcon 
                          icon={faMinus} 
                          style={{ color: '#94a3b8', fontSize: '14px' }}
                        />
                      )}
                    </div>
                    
                    {/* Category Label */}
                    <div className="readiness-category-label">
                      {CATEGORY_LABELS[category.key] || category.key}
                    </div>
                    
                    {/* Category Progress Bar (Mini) */}
                    <div className="readiness-category-progress">
                      <div
                        className="readiness-category-progress-bar"
                        style={{
                          width: '60px',
                          height: '6px',
                          borderRadius: '3px',
                          background: '#e5e7eb',
                          overflow: 'hidden',
                          marginLeft: 'auto',
                          marginRight: '8px'
                        }}
                      >
                        <div
                          style={{
                            width: `${categoryPercent}%`,
                            height: '100%',
                            borderRadius: '3px',
                            background: getProgressColor(categoryPercent),
                            transition: 'width 300ms ease'
                          }}
                        />
                      </div>
                      
                      {/* Percentage Text */}
                      <div 
                        className="readiness-category-percent"
                        style={{
                          fontSize: '12px',
                          color: '#64748b',
                          minWidth: '35px',
                          textAlign: 'right'
                        }}
                      >
                        {categoryPercent}%
                      </div>
                    </div>
                  </div>
                  
                  {/* Expandable Micro Elements */}
                  {isExpanded && micros.length > 0 && (
                    <div className="readiness-micro-elements">
                      {micros.map((micro) => {
                        const microCollected = micro.collected || false;
                        const microConfidence = micro.confidence || 0;
                        
                        return (
                          <div 
                            key={micro.key} 
                            className={`readiness-micro-item ${microCollected ? 'collected' : 'pending'}`}
                          >
                            {/* Micro Icon */}
                            <div className="readiness-micro-icon">
                              {microCollected ? (
                                <FontAwesomeIcon 
                                  icon={faCheck} 
                                  style={{ color: '#10b981', fontSize: '11px' }}
                                />
                              ) : (
                                <FontAwesomeIcon 
                                  icon={faMinus} 
                                  style={{ color: '#cbd5e1', fontSize: '11px' }}
                                />
                              )}
                            </div>
                            
                            {/* Micro Label */}
                            <div className="readiness-micro-label">
                              {MICRO_LABELS[micro.key] || micro.key}
                            </div>
                            
                            {/* Confidence Indicator (Optional - shows as mini bar) */}
                            {!microCollected && microConfidence > 0 && (
                              <div 
                                className="readiness-micro-confidence"
                                style={{
                                  width: '30px',
                                  height: '4px',
                                  borderRadius: '2px',
                                  background: '#e5e7eb',
                                  overflow: 'hidden',
                                  marginLeft: 'auto'
                                }}
                              >
                                <div
                                  style={{
                                    width: `${microConfidence * 100}%`,
                                    height: '100%',
                                    background: '#60a5fa',
                                    transition: 'width 200ms ease'
                                  }}
                                />
                              </div>
                            )}
                          </div>
                        );
                      })}
                    </div>
                  )}
                </div>
              );
            })}
          </div>
        )}
      </div>

      {/* Help Text */}
      <div className="readiness-help">
        <small>
          {readinessPercent < 90
            ? 'Continue the conversation to provide more details for a comprehensive analysis.'
            : 'You have enough information. Click "Finish & Analyze" when ready.'}
        </small>
      </div>
    </div>
  );
}
