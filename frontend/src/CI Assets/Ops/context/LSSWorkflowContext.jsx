import React, { createContext, useContext, useReducer, useEffect } from 'react';

// Workflow definitions
const DMAIC_PHASES = [
  {
    id: 'define',
    name: 'Define',
    description: 'Define the problem, improvement activity, opportunity for improvement, and project goals',
    requiredArtifacts: ['project_charter', 'sipoc', 'voice_of_customer'],
    optionalArtifacts: ['stakeholder_analysis', 'project_planning'],
    tollgateRequirements: [
      'Problem statement clearly defined',
      'Project scope established',
      'Customer requirements identified',
      'Project charter approved'
    ]
  },
  {
    id: 'measure',
    name: 'Measure',
    description: 'Measure the extent of the problem and collect relevant data',
    requiredArtifacts: ['data_collection_plan', 'process_map', 'baseline_metrics'],
    optionalArtifacts: ['checksheet', 'run_chart', 'histogram'],
    tollgateRequirements: [
      'Current state process mapped',
      'Data collection plan established',
      'Baseline performance measured',
      'Measurement system validated'
    ]
  },
  {
    id: 'analyze',
    name: 'Analyze',
    description: 'Analyze the data to identify and verify root causes',
    requiredArtifacts: ['root_cause_analysis', 'pareto_chart', 'statistical_analysis'],
    optionalArtifacts: ['scatter_plot', 'correlation_analysis', 'hypothesis_testing'],
    tollgateRequirements: [
      'Root causes identified and verified',
      'Data analysis completed',
      'Improvement opportunities prioritized',
      'Solution hypotheses developed'
    ]
  },
  {
    id: 'improve',
    name: 'Improve',
    description: 'Improve the process by implementing solutions',
    requiredArtifacts: ['solution_selection', 'implementation_plan', 'pilot_results'],
    optionalArtifacts: ['fmea', 'cost_benefit_analysis', 'change_management'],
    tollgateRequirements: [
      'Solutions implemented and tested',
      'Improvement results validated',
      'Implementation plan executed',
      'Benefits realized and measured'
    ]
  },
  {
    id: 'control',
    name: 'Control',
    description: 'Control the improved process to sustain gains',
    requiredArtifacts: ['control_plan', 'standard_work', 'monitoring_system'],
    optionalArtifacts: ['control_charts', 'training_materials', 'handoff_documentation'],
    tollgateRequirements: [
      'Control plan implemented',
      'Process monitoring established',
      'Standard work documented',
      'Sustainment plan activated'
    ]
  }
];

const KAIZEN_PHASES = [
  {
    id: 'before',
    name: 'Before',
    description: 'Current state analysis and preparation',
    requiredArtifacts: ['current_state_analysis', 'kaizen_charter', 'team_formation'],
    optionalArtifacts: ['baseline_metrics', 'stakeholder_analysis'],
    tollgateRequirements: [
      'Current state documented',
      'Improvement opportunity identified',
      'Team assembled and trained',
      'Event scope defined'
    ]
  },
  {
    id: 'during',
    name: 'During',
    description: 'Kaizen event execution and improvement implementation',
    requiredArtifacts: ['future_state_design', 'implementation_actions', 'quick_wins'],
    optionalArtifacts: ['value_stream_map', 'waste_identification', 'solution_testing'],
    tollgateRequirements: [
      'Future state designed',
      'Improvements implemented',
      'Results measured',
      'Team consensus achieved'
    ]
  },
  {
    id: 'after',
    name: 'After',
    description: 'Sustainment and continuous improvement',
    requiredArtifacts: ['sustainment_plan', 'results_summary', 'lessons_learned'],
    optionalArtifacts: ['training_plan', 'follow_up_actions', 'celebration'],
    tollgateRequirements: [
      'Results sustained',
      'Standard work established',
      'Team recognition completed',
      'Next steps identified'
    ]
  }
];

// Initial state
const initialState = {
  currentWorkflow: null, // 'dmaic' or 'kaizen'
  currentPhase: null,
  phaseProgress: {},
  tollgateApprovals: {},
  workflowSettings: {
    requireTollgateApproval: false,
    autoAdvancePhases: false,
    mandatoryArtifacts: true
  },
  loading: false,
  error: null
};

// Action types
const actionTypes = {
  SET_LOADING: 'SET_LOADING',
  SET_ERROR: 'SET_ERROR',
  SET_WORKFLOW: 'SET_WORKFLOW',
  SET_PHASE: 'SET_PHASE',
  UPDATE_PHASE_PROGRESS: 'UPDATE_PHASE_PROGRESS',
  APPROVE_TOLLGATE: 'APPROVE_TOLLGATE',
  REJECT_TOLLGATE: 'REJECT_TOLLGATE',
  UPDATE_WORKFLOW_SETTINGS: 'UPDATE_WORKFLOW_SETTINGS',
  RESET_WORKFLOW: 'RESET_WORKFLOW'
};

// Reducer
const workflowReducer = (state, action) => {
  switch (action.type) {
    case actionTypes.SET_LOADING:
      return { ...state, loading: action.payload };
    
    case actionTypes.SET_ERROR:
      return { ...state, error: action.payload, loading: false };
    
    case actionTypes.SET_WORKFLOW:
      return { 
        ...state, 
        currentWorkflow: action.payload,
        currentPhase: action.payload === 'dmaic' ? 'define' : 'before',
        phaseProgress: {},
        tollgateApprovals: {}
      };
    
    case actionTypes.SET_PHASE:
      return { ...state, currentPhase: action.payload };
    
    case actionTypes.UPDATE_PHASE_PROGRESS:
      return {
        ...state,
        phaseProgress: {
          ...state.phaseProgress,
          [action.payload.phase]: action.payload.progress
        }
      };
    
    case actionTypes.APPROVE_TOLLGATE:
      return {
        ...state,
        tollgateApprovals: {
          ...state.tollgateApprovals,
          [action.payload.phase]: {
            approved: true,
            approvedBy: action.payload.approvedBy,
            approvedAt: action.payload.approvedAt,
            comments: action.payload.comments
          }
        }
      };
    
    case actionTypes.REJECT_TOLLGATE:
      return {
        ...state,
        tollgateApprovals: {
          ...state.tollgateApprovals,
          [action.payload.phase]: {
            approved: false,
            rejectedBy: action.payload.rejectedBy,
            rejectedAt: action.payload.rejectedAt,
            comments: action.payload.comments,
            requiredActions: action.payload.requiredActions
          }
        }
      };
    
    case actionTypes.UPDATE_WORKFLOW_SETTINGS:
      return {
        ...state,
        workflowSettings: {
          ...state.workflowSettings,
          ...action.payload
        }
      };
    
    case actionTypes.RESET_WORKFLOW:
      return {
        ...state,
        currentWorkflow: null,
        currentPhase: null,
        phaseProgress: {},
        tollgateApprovals: {}
      };
    
    default:
      return state;
  }
};

// Context
const LSSWorkflowContext = createContext();

// Provider component
export const LSSWorkflowProvider = ({ children }) => {
  const [state, dispatch] = useReducer(workflowReducer, initialState);

  // Load workflow settings from localStorage on mount
  useEffect(() => {
    const savedSettings = localStorage.getItem('lss_workflow_settings');
    if (savedSettings) {
      const settings = JSON.parse(savedSettings);
      dispatch({ type: actionTypes.UPDATE_WORKFLOW_SETTINGS, payload: settings });
    }
  }, []);

  // Save workflow settings to localStorage whenever they change
  useEffect(() => {
    localStorage.setItem('lss_workflow_settings', JSON.stringify(state.workflowSettings));
  }, [state.workflowSettings]);

  // Helper functions
  const getWorkflowPhases = (workflowType) => {
    return workflowType === 'dmaic' ? DMAIC_PHASES : KAIZEN_PHASES;
  };

  const getCurrentPhaseData = () => {
    if (!state.currentWorkflow || !state.currentPhase) return null;
    const phases = getWorkflowPhases(state.currentWorkflow);
    return phases.find(phase => phase.id === state.currentPhase);
  };

  const getNextPhase = () => {
    if (!state.currentWorkflow || !state.currentPhase) return null;
    const phases = getWorkflowPhases(state.currentWorkflow);
    const currentIndex = phases.findIndex(phase => phase.id === state.currentPhase);
    return currentIndex < phases.length - 1 ? phases[currentIndex + 1] : null;
  };

  const getPreviousPhase = () => {
    if (!state.currentWorkflow || !state.currentPhase) return null;
    const phases = getWorkflowPhases(state.currentWorkflow);
    const currentIndex = phases.findIndex(phase => phase.id === state.currentPhase);
    return currentIndex > 0 ? phases[currentIndex - 1] : null;
  };

  const canAdvanceToNextPhase = (artifacts = []) => {
    const currentPhaseData = getCurrentPhaseData();
    if (!currentPhaseData) return false;

    // Check if tollgate approval is required and approved
    if (state.workflowSettings.requireTollgateApproval) {
      const approval = state.tollgateApprovals[state.currentPhase];
      if (!approval || !approval.approved) return false;
    }

    // Check if mandatory artifacts are completed
    if (state.workflowSettings.mandatoryArtifacts) {
      const completedArtifactTypes = artifacts
        .filter(artifact => artifact.status === 'completed')
        .map(artifact => artifact.type);
      
      const missingRequired = currentPhaseData.requiredArtifacts.filter(
        required => !completedArtifactTypes.includes(required)
      );
      
      if (missingRequired.length > 0) return false;
    }

    return true;
  };

  const calculatePhaseProgress = (artifacts = []) => {
    const currentPhaseData = getCurrentPhaseData();
    if (!currentPhaseData) return 0;

    const allArtifacts = [...currentPhaseData.requiredArtifacts, ...currentPhaseData.optionalArtifacts];
    const phaseArtifacts = artifacts.filter(artifact => 
      allArtifacts.includes(artifact.type)
    );

    if (phaseArtifacts.length === 0) return 0;

    const completedCount = phaseArtifacts.filter(artifact => 
      artifact.status === 'completed'
    ).length;

    return Math.round((completedCount / phaseArtifacts.length) * 100);
  };

  // Actions
  const setWorkflow = (workflowType) => {
    try {
      if (!['dmaic', 'kaizen'].includes(workflowType)) {
        throw new Error('Invalid workflow type');
      }
      dispatch({ type: actionTypes.SET_WORKFLOW, payload: workflowType });
    } catch (error) {
      dispatch({ type: actionTypes.SET_ERROR, payload: error.message });
    }
  };

  const setPhase = (phaseId) => {
    try {
      const phases = getWorkflowPhases(state.currentWorkflow);
      const phase = phases.find(p => p.id === phaseId);
      if (!phase) {
        throw new Error('Invalid phase');
      }
      dispatch({ type: actionTypes.SET_PHASE, payload: phaseId });
    } catch (error) {
      dispatch({ type: actionTypes.SET_ERROR, payload: error.message });
    }
  };

  const advanceToNextPhase = (artifacts = []) => {
    try {
      if (!canAdvanceToNextPhase(artifacts)) {
        throw new Error('Cannot advance to next phase. Requirements not met.');
      }
      
      const nextPhase = getNextPhase();
      if (!nextPhase) {
        throw new Error('Already at final phase');
      }
      
      dispatch({ type: actionTypes.SET_PHASE, payload: nextPhase.id });
      return nextPhase;
    } catch (error) {
      dispatch({ type: actionTypes.SET_ERROR, payload: error.message });
      return null;
    }
  };

  const updatePhaseProgress = (phase, progress) => {
    dispatch({ 
      type: actionTypes.UPDATE_PHASE_PROGRESS, 
      payload: { phase, progress } 
    });
  };

  const approveTollgate = (phase, approvedBy, comments = '') => {
    dispatch({
      type: actionTypes.APPROVE_TOLLGATE,
      payload: {
        phase,
        approvedBy,
        approvedAt: new Date().toISOString(),
        comments
      }
    });
  };

  const rejectTollgate = (phase, rejectedBy, comments = '', requiredActions = []) => {
    dispatch({
      type: actionTypes.REJECT_TOLLGATE,
      payload: {
        phase,
        rejectedBy,
        rejectedAt: new Date().toISOString(),
        comments,
        requiredActions
      }
    });
  };

  const updateWorkflowSettings = (settings) => {
    dispatch({ type: actionTypes.UPDATE_WORKFLOW_SETTINGS, payload: settings });
  };

  const resetWorkflow = () => {
    dispatch({ type: actionTypes.RESET_WORKFLOW });
  };

  // Get workflow statistics
  const getWorkflowStats = (projects = []) => {
    const dmiacProjects = projects.filter(p => p.workflowType === 'dmaic');
    const kaizenProjects = projects.filter(p => p.workflowType === 'kaizen');
    
    const phaseDistribution = {};
    const phases = state.currentWorkflow ? getWorkflowPhases(state.currentWorkflow) : DMAIC_PHASES;
    
    phases.forEach(phase => {
      phaseDistribution[phase.id] = projects.filter(p => p.currentPhase === phase.id).length;
    });

    return {
      dmiacProjects: dmiacProjects.length,
      kaizenProjects: kaizenProjects.length,
      phaseDistribution,
      avgPhaseTime: calculateAveragePhaseTime(projects),
      tollgateApprovalRate: calculateTollgateApprovalRate()
    };
  };

  const calculateAveragePhaseTime = (projects) => {
    // Implementation for calculating average time spent in each phase
    // This would require tracking phase entry/exit times
    return {};
  };

  const calculateTollgateApprovalRate = () => {
    const totalTollgates = Object.keys(state.tollgateApprovals).length;
    if (totalTollgates === 0) return 0;
    
    const approvedTollgates = Object.values(state.tollgateApprovals)
      .filter(approval => approval.approved).length;
    
    return Math.round((approvedTollgates / totalTollgates) * 100);
  };

  const value = {
    // State
    ...state,
    
    // Workflow definitions
    DMAIC_PHASES,
    KAIZEN_PHASES,
    
    // Actions
    setWorkflow,
    setPhase,
    advanceToNextPhase,
    updatePhaseProgress,
    approveTollgate,
    rejectTollgate,
    updateWorkflowSettings,
    resetWorkflow,
    
    // Helpers
    getWorkflowPhases,
    getCurrentPhaseData,
    getNextPhase,
    getPreviousPhase,
    canAdvanceToNextPhase,
    calculatePhaseProgress,
    getWorkflowStats
  };

  return (
    <LSSWorkflowContext.Provider value={value}>
      {children}
    </LSSWorkflowContext.Provider>
  );
};

// Custom hook
export const useLSSWorkflow = () => {
  const context = useContext(LSSWorkflowContext);
  if (!context) {
    throw new Error('useLSSWorkflow must be used within a LSSWorkflowProvider');
  }
  return context;
};

export default LSSWorkflowContext;

