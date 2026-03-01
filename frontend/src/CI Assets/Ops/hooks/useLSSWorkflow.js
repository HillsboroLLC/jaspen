import { useContext } from 'react';
import LSSWorkflowContext from '../context/LSSWorkflowContext';

// Custom hook for using LSS Workflow context
export const useLSSWorkflow = () => {
  const context = useContext(LSSWorkflowContext);
  
  if (!context) {
    throw new Error('useLSSWorkflow must be used within a LSSWorkflowProvider');
  }
  
  return context;
};

// Additional helper hooks for specific use cases
export const useCurrentWorkflow = () => {
  const { currentWorkflow, currentPhase, setWorkflow, setPhase } = useLSSWorkflow();
  return { 
    currentWorkflow, 
    currentPhase, 
    setWorkflow, 
    setPhase 
  };
};

export const usePhaseNavigation = () => {
  const { 
    getCurrentPhaseData,
    getNextPhase,
    getPreviousPhase,
    advanceToNextPhase,
    canAdvanceToNextPhase
  } = useLSSWorkflow();
  
  return {
    getCurrentPhaseData,
    getNextPhase,
    getPreviousPhase,
    advanceToNextPhase,
    canAdvanceToNextPhase
  };
};

export const usePhaseProgress = () => {
  const { 
    phaseProgress,
    updatePhaseProgress,
    calculatePhaseProgress
  } = useLSSWorkflow();
  
  return {
    phaseProgress,
    updatePhaseProgress,
    calculatePhaseProgress
  };
};

export const useTollgateManagement = () => {
  const {
    tollgateApprovals,
    approveTollgate,
    rejectTollgate,
    workflowSettings
  } = useLSSWorkflow();
  
  return {
    tollgateApprovals,
    approveTollgate,
    rejectTollgate,
    requireTollgateApproval: workflowSettings.requireTollgateApproval
  };
};

export const useWorkflowSettings = () => {
  const { workflowSettings, updateWorkflowSettings } = useLSSWorkflow();
  return { workflowSettings, updateWorkflowSettings };
};

export const useWorkflowStats = () => {
  const { getWorkflowStats } = useLSSWorkflow();
  return getWorkflowStats;
};

export const useDMAICPhases = () => {
  const { DMAIC_PHASES } = useLSSWorkflow();
  return DMAIC_PHASES;
};

export const useKaizenPhases = () => {
  const { KAIZEN_PHASES } = useLSSWorkflow();
  return KAIZEN_PHASES;
};

export const useWorkflowPhases = (workflowType) => {
  const { getWorkflowPhases } = useLSSWorkflow();
  return getWorkflowPhases(workflowType);
};

export default useLSSWorkflow;

