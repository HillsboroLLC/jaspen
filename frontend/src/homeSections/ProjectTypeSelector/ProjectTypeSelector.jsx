import React, { useState, useEffect } from 'react';
import styles from './ProjectTypeSelector.module.css';

const ProjectTypeSelector = ({ onProjectSelect, initialContext = null, showModeSelection = true }) => {
  const [selectedProjectType, setSelectedProjectType] = useState('');
  const [selectedMode, setSelectedMode] = useState('guided');
  const [showDetails, setShowDetails] = useState(false);
  const [searchTerm, setSearchTerm] = useState('');

  // Project types with detailed information
  const projectTypes = [
    {
      id: 'dmaic',
      name: 'DMAIC Project',
      category: 'Process Improvement',
      description: 'Define, Measure, Analyze, Improve, Control - Structured approach for process improvement',
      icon: 'fas fa-project-diagram',
      duration: '3-6 months',
      complexity: 'Medium',
      benefits: ['Systematic problem solving', 'Data-driven decisions', 'Sustainable improvements'],
      tools: ['Project Charter', 'SIPOC', 'Process Map', 'Statistical Analysis', 'Control Plan'],
      bestFor: 'Existing processes with performance issues or improvement opportunities'
    },
    {
      id: 'dmadv',
      name: 'DMADV Project',
      category: 'Design for Six Sigma',
      description: 'Define, Measure, Analyze, Design, Verify - For new process or product design',
      icon: 'fas fa-drafting-compass',
      duration: '4-8 months',
      complexity: 'High',
      benefits: ['Right first time design', 'Customer-focused solutions', 'Reduced rework'],
      tools: ['Voice of Customer', 'QFD', 'Design of Experiments', 'Pilot Planning', 'Verification'],
      bestFor: 'New products, services, or processes that need to be designed from scratch'
    },
    {
      id: 'kaizen',
      name: 'Kaizen Event',
      category: 'Rapid Improvement',
      description: 'Focused, short-term improvement event targeting specific issues',
      icon: 'fas fa-bolt',
      duration: '3-5 days',
      complexity: 'Low',
      benefits: ['Quick wins', 'Team engagement', 'Immediate results'],
      tools: ['5S', 'Value Stream Map', 'Root Cause Analysis', 'Standard Work', 'Visual Management'],
      bestFor: 'Specific, well-defined problems that can be solved quickly'
    },
    {
      id: 'lean_transformation',
      name: 'Lean Transformation',
      category: 'Organizational Change',
      description: 'Comprehensive organizational transformation using Lean principles',
      icon: 'fas fa-arrows-alt',
      duration: '12-24 months',
      complexity: 'High',
      benefits: ['Cultural change', 'Waste elimination', 'Flow optimization'],
      tools: ['Value Stream Mapping', 'Gemba Walks', 'A3 Problem Solving', 'Hoshin Kanri', 'Leader Standard Work'],
      bestFor: 'Organizations ready for comprehensive operational excellence transformation'
    },
    {
      id: 'process_design',
      name: 'Process Design',
      category: 'Process Development',
      description: 'Design new processes or completely redesign existing ones',
      icon: 'fas fa-cogs',
      duration: '2-4 months',
      complexity: 'Medium',
      benefits: ['Optimized workflows', 'Reduced cycle time', 'Better quality'],
      tools: ['Process Mapping', 'SIPOC', 'FMEA', 'Simulation', 'Pilot Testing'],
      bestFor: 'Creating new processes or major process redesign initiatives'
    },
    {
      id: 'quality_improvement',
      name: 'Quality Improvement',
      category: 'Quality Management',
      description: 'Focus on reducing defects and improving quality metrics',
      icon: 'fas fa-award',
      duration: '2-4 months',
      complexity: 'Medium',
      benefits: ['Reduced defects', 'Customer satisfaction', 'Cost savings'],
      tools: ['Statistical Process Control', 'DOE', 'MSA', 'FMEA', 'Quality Planning'],
      bestFor: 'Quality issues, high defect rates, or customer complaints'
    },
    {
      id: 'cost_reduction',
      name: 'Cost Reduction',
      category: 'Financial Improvement',
      description: 'Systematic approach to identify and eliminate unnecessary costs',
      icon: 'fas fa-dollar-sign',
      duration: '2-3 months',
      complexity: 'Medium',
      benefits: ['Direct cost savings', 'Improved margins', 'Resource optimization'],
      tools: ['Value Analysis', 'Cost Modeling', 'Pareto Analysis', 'Benchmarking', 'Financial Analysis'],
      bestFor: 'High costs, budget pressures, or margin improvement needs'
    },
    {
      id: 'customer_experience',
      name: 'Customer Experience',
      category: 'Customer Focus',
      description: 'Improve customer journey and satisfaction through process optimization',
      icon: 'fas fa-users',
      duration: '3-5 months',
      complexity: 'Medium',
      benefits: ['Higher satisfaction', 'Increased loyalty', 'Revenue growth'],
      tools: ['Voice of Customer', 'Journey Mapping', 'Touchpoint Analysis', 'Service Design', 'Feedback Systems'],
      bestFor: 'Customer complaints, low satisfaction scores, or competitive pressure'
    },
    {
      id: 'digital_transformation',
      name: 'Digital Transformation',
      category: 'Technology Integration',
      description: 'Integrate digital technologies to improve processes and customer value',
      icon: 'fas fa-laptop-code',
      duration: '6-12 months',
      complexity: 'High',
      benefits: ['Automation', 'Data insights', 'Scalability'],
      tools: ['Process Mining', 'Automation Assessment', 'Digital Roadmap', 'Change Management', 'ROI Analysis'],
      bestFor: 'Manual processes, data silos, or digital modernization needs'
    },
    {
      id: 'supply_chain',
      name: 'Supply Chain Optimization',
      category: 'Operations',
      description: 'Optimize supply chain processes for efficiency and reliability',
      icon: 'fas fa-truck',
      duration: '4-6 months',
      complexity: 'High',
      benefits: ['Reduced lead times', 'Lower inventory', 'Better reliability'],
      tools: ['Value Stream Mapping', 'Supplier Analysis', 'Inventory Optimization', 'Risk Assessment', 'Performance Metrics'],
      bestFor: 'Supply chain issues, inventory problems, or supplier performance concerns'
    }
  ];

  // Mode descriptions
  const modes = {
    guided: {
      name: 'Guided Mode',
      icon: 'fas fa-route',
      description: 'Step-by-step guidance with templates, checklists, and AI assistance',
      features: [
        'Interactive templates and forms',
        'AI-powered recommendations',
        'Built-in best practices',
        'Progress tracking and milestones',
        'Automated report generation'
      ],
      bestFor: 'New practitioners, complex projects, or when following standard methodologies'
    },
    solo: {
      name: 'Solo Mode',
      icon: 'fas fa-user',
      description: 'Flexible workspace with tools and resources for experienced practitioners',
      features: [
        'Full customization freedom',
        'Advanced tool access',
        'Blank canvas approach',
        'Expert-level features',
        'Custom workflow creation'
      ],
      bestFor: 'Experienced practitioners, unique situations, or custom methodologies'
    }
  };

  // Filter project types based on search
  const filteredProjectTypes = projectTypes.filter(project =>
    project.name.toLowerCase().includes(searchTerm.toLowerCase()) ||
    project.category.toLowerCase().includes(searchTerm.toLowerCase()) ||
    project.description.toLowerCase().includes(searchTerm.toLowerCase())
  );

  // Auto-select based on initial context
  useEffect(() => {
    if (initialContext && !selectedProjectType) {
      const contextMap = {
        'dmaic': 'dmaic',
        'sipoc': 'dmaic',
        'process-improvement': 'dmaic',
        'design': 'dmadv',
        'new-product': 'dmadv',
        'kaizen': 'kaizen',
        'quick-win': 'kaizen',
        'quality': 'quality_improvement',
        'defects': 'quality_improvement',
        'cost': 'cost_reduction',
        'savings': 'cost_reduction',
        'customer': 'customer_experience',
        'satisfaction': 'customer_experience'
      };
      
      const suggestedType = contextMap[initialContext.toLowerCase()];
      if (suggestedType) {
        setSelectedProjectType(suggestedType);
      }
    }
  }, [initialContext, selectedProjectType]);

  const handleProjectSelect = () => {
    if (selectedProjectType) {
      const project = projectTypes.find(p => p.id === selectedProjectType);
      const mode = modes[selectedMode];
      
      onProjectSelect({
        projectType: project,
        mode: mode,
        modeId: selectedMode
      });
    }
  };

  const getComplexityColor = (complexity) => {
    switch (complexity.toLowerCase()) {
      case 'low': return '#10b981';
      case 'medium': return '#f59e0b';
      case 'high': return '#ef4444';
      default: return '#6b7280';
    }
  };

  return (
    <div className={styles.projectTypeSelector}>
      <div className={styles.header}>
        <h2>
          <i className="fas fa-rocket"></i>
          Start Your Improvement Project
        </h2>
        <p>Choose your project type and working mode to get started with the right tools and guidance.</p>
      </div>

      {/* Search and Filter */}
      <div className={styles.searchSection}>
        <div className={styles.searchBox}>
          <i className="fas fa-search"></i>
          <input
            type="text"
            placeholder="Search project types..."
            value={searchTerm}
            onChange={(e) => setSearchTerm(e.target.value)}
          />
        </div>
      </div>

      {/* Project Type Selection */}
      <div className={styles.projectTypesSection}>
        <h3>Select Project Type</h3>
        <div className={styles.projectTypesGrid}>
          {filteredProjectTypes.map(project => (
            <div
              key={project.id}
              className={`${styles.projectTypeCard} ${selectedProjectType === project.id ? styles.selected : ''}`}
              onClick={() => setSelectedProjectType(project.id)}
            >
              <div className={styles.cardHeader}>
                <div className={styles.cardIcon}>
                  <i className={project.icon}></i>
                </div>
                <div className={styles.cardTitle}>
                  <h4>{project.name}</h4>
                  <span className={styles.category}>{project.category}</span>
                </div>
                <div className={styles.cardMeta}>
                  <span 
                    className={styles.complexity}
                    style={{ color: getComplexityColor(project.complexity) }}
                  >
                    {project.complexity}
                  </span>
                  <span className={styles.duration}>{project.duration}</span>
                </div>
              </div>
              
              <p className={styles.description}>{project.description}</p>
              
              <div className={styles.cardFooter}>
                <div className={styles.tools}>
                  <strong>Key Tools:</strong>
                  <div className={styles.toolsList}>
                    {project.tools.slice(0, 3).map(tool => (
                      <span key={tool} className={styles.tool}>{tool}</span>
                    ))}
                    {project.tools.length > 3 && (
                      <span className={styles.moreTools}>+{project.tools.length - 3} more</span>
                    )}
                  </div>
                </div>
                <button
                  className={styles.detailsButton}
                  onClick={(e) => {
                    e.stopPropagation();
                    setShowDetails(project.id);
                  }}
                >
                  <i className="fas fa-info-circle"></i>
                  Details
                </button>
              </div>
            </div>
          ))}
        </div>
      </div>

      {/* Mode Selection */}
      {showModeSelection && selectedProjectType && (
        <div className={styles.modeSection}>
          <h3>Choose Your Working Mode</h3>
          <div className={styles.modesGrid}>
            {Object.entries(modes).map(([modeId, mode]) => (
              <div
                key={modeId}
                className={`${styles.modeCard} ${selectedMode === modeId ? styles.selected : ''}`}
                onClick={() => setSelectedMode(modeId)}
              >
                <div className={styles.modeHeader}>
                  <div className={styles.modeIcon}>
                    <i className={mode.icon}></i>
                  </div>
                  <h4>{mode.name}</h4>
                </div>
                
                <p className={styles.modeDescription}>{mode.description}</p>
                
                <div className={styles.modeFeatures}>
                  <strong>Features:</strong>
                  <ul>
                    {mode.features.map(feature => (
                      <li key={feature}>{feature}</li>
                    ))}
                  </ul>
                </div>
                
                <div className={styles.modeBestFor}>
                  <strong>Best for:</strong>
                  <p>{mode.bestFor}</p>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Action Buttons */}
      <div className={styles.actionSection}>
        <button
          className={styles.startButton}
          onClick={handleProjectSelect}
          disabled={!selectedProjectType} aria-disabled={!selectedProjectType}
        >
          <i className="fas fa-play"></i>
          Start Project
        </button>
        
        {selectedProjectType && (
          <div className={styles.selectionSummary}>
            <div className={styles.summaryItem}>
              <strong>Project:</strong>
              <span>{projectTypes.find(p => p.id === selectedProjectType)?.name}</span>
            </div>
            {showModeSelection && (
              <div className={styles.summaryItem}>
                <strong>Mode:</strong>
                <span>{modes[selectedMode]?.name}</span>
              </div>
            )}
          </div>
        )}
      </div>

      {/* Project Details Modal */}
      {showDetails && (
        <div className={styles.modal} onClick={() => setShowDetails(null)}>
          <div className={styles.modalContent} onClick={(e) => e.stopPropagation()}>
            {(() => {
              const project = projectTypes.find(p => p.id === showDetails);
              return project ? (
                <>
                  <div className={styles.modalHeader}>
                    <h3>
                      <i className={project.icon}></i>
                      {project.name}
                    </h3>
                    <button
                      className={styles.closeButton}
                      onClick={() => setShowDetails(null)}
                    >
                      <i className="fas fa-times"></i>
                    </button>
                  </div>
                  
                  <div className={styles.modalBody}>
                    <div className={styles.projectOverview}>
                      <p><strong>Category:</strong> {project.category}</p>
                      <p><strong>Duration:</strong> {project.duration}</p>
                      <p><strong>Complexity:</strong> 
                        <span style={{ color: getComplexityColor(project.complexity) }}>
                          {project.complexity}
                        </span>
                      </p>
                      <p><strong>Best for:</strong> {project.bestFor}</p>
                    </div>
                    
                    <div className={styles.projectBenefits}>
                      <h4>Key Benefits</h4>
                      <ul>
                        {project.benefits.map(benefit => (
                          <li key={benefit}>{benefit}</li>
                        ))}
                      </ul>
                    </div>
                    
                    <div className={styles.projectTools}>
                      <h4>Tools & Methods</h4>
                      <div className={styles.toolsGrid}>
                        {project.tools.map(tool => (
                          <span key={tool} className={styles.toolTag}>{tool}</span>
                        ))}
                      </div>
                    </div>
                  </div>
                  
                  <div className={styles.modalFooter}>
                    <button
                      className={styles.selectProjectButton}
                      onClick={() => {
                        setSelectedProjectType(project.id);
                        setShowDetails(null);
                      }}
                    >
                      Select This Project Type
                    </button>
                  </div>
                </>
              ) : null;
            })()}
          </div>
        </div>
      )}
    </div>
  );
};

export default ProjectTypeSelector;
