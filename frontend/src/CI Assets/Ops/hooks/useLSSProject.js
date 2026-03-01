import { useContext } from 'react';
import LSSProjectContext from '../context/LSSProjectContext';

// Custom hook for using LSS Project context
export const useLSSProject = () => {
  const context = useContext(LSSProjectContext);
  
  if (!context) {
    throw new Error('useLSSProject must be used within a LSSProjectProvider');
  }
  
  return context;
};

// Additional helper hooks for specific use cases
export const useProjectMetrics = () => {
  const { metrics } = useLSSProject();
  return metrics;
};

export const useCurrentProject = () => {
  const { currentProject, setCurrentProject } = useLSSProject();
  return { currentProject, setCurrentProject };
};

export const useProjectsByStatus = (status) => {
  const { getProjectsByStatus } = useLSSProject();
  return getProjectsByStatus(status);
};

export const useProjectsByPhase = (phase) => {
  const { getProjectsByPhase } = useLSSProject();
  return getProjectsByPhase(phase);
};

export const useRecentArtifacts = (limit = 10) => {
  const { getRecentArtifacts } = useLSSProject();
  return getRecentArtifacts(limit);
};

export const useProjectActions = () => {
  const { 
    createProject, 
    updateProject, 
    deleteProject,
    addArtifact,
    updateArtifact,
    deleteArtifact
  } = useLSSProject();
  
  return {
    createProject,
    updateProject,
    deleteProject,
    addArtifact,
    updateArtifact,
    deleteArtifact
  };
};

export default useLSSProject;

