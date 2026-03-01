import React, { createContext, useContext, useReducer, useEffect } from 'react';

// Initial state
const initialState = {
  projects: [],
  currentProject: null,
  loading: false,
  error: null,
  metrics: {
    activeProjects: 0,
    completedProjects: 0,
    totalSavings: 0,
    avgCycleTime: 0
  }
};

// Action types
const actionTypes = {
  SET_LOADING: 'SET_LOADING',
  SET_ERROR: 'SET_ERROR',
  LOAD_PROJECTS: 'LOAD_PROJECTS',
  CREATE_PROJECT: 'CREATE_PROJECT',
  UPDATE_PROJECT: 'UPDATE_PROJECT',
  DELETE_PROJECT: 'DELETE_PROJECT',
  SET_CURRENT_PROJECT: 'SET_CURRENT_PROJECT',
  UPDATE_METRICS: 'UPDATE_METRICS',
  ADD_ARTIFACT: 'ADD_ARTIFACT',
  UPDATE_ARTIFACT: 'UPDATE_ARTIFACT',
  DELETE_ARTIFACT: 'DELETE_ARTIFACT'
};

// Reducer
const projectReducer = (state, action) => {
  switch (action.type) {
    case actionTypes.SET_LOADING:
      return { ...state, loading: action.payload };
    
    case actionTypes.SET_ERROR:
      return { ...state, error: action.payload, loading: false };
    
    case actionTypes.LOAD_PROJECTS:
      return { 
        ...state, 
        projects: action.payload, 
        loading: false,
        error: null 
      };
    
    case actionTypes.CREATE_PROJECT:
      const newProjects = [...state.projects, action.payload];
      return { 
        ...state, 
        projects: newProjects,
        currentProject: action.payload 
      };
    
    case actionTypes.UPDATE_PROJECT:
      const updatedProjects = state.projects.map(project =>
        project.id === action.payload.id ? action.payload : project
      );
      return { 
        ...state, 
        projects: updatedProjects,
        currentProject: state.currentProject?.id === action.payload.id 
          ? action.payload 
          : state.currentProject
      };
    
    case actionTypes.DELETE_PROJECT:
      return { 
        ...state, 
        projects: state.projects.filter(project => project.id !== action.payload),
        currentProject: state.currentProject?.id === action.payload 
          ? null 
          : state.currentProject
      };
    
    case actionTypes.SET_CURRENT_PROJECT:
      return { ...state, currentProject: action.payload };
    
    case actionTypes.UPDATE_METRICS:
      return { ...state, metrics: action.payload };
    
    case actionTypes.ADD_ARTIFACT:
      if (!state.currentProject) return state;
      const projectWithNewArtifact = {
        ...state.currentProject,
        artifacts: [...(state.currentProject.artifacts || []), action.payload]
      };
      return {
        ...state,
        currentProject: projectWithNewArtifact,
        projects: state.projects.map(p => 
          p.id === projectWithNewArtifact.id ? projectWithNewArtifact : p
        )
      };
    
    case actionTypes.UPDATE_ARTIFACT:
      if (!state.currentProject) return state;
      const projectWithUpdatedArtifact = {
        ...state.currentProject,
        artifacts: state.currentProject.artifacts?.map(artifact =>
          artifact.id === action.payload.id ? action.payload : artifact
        ) || []
      };
      return {
        ...state,
        currentProject: projectWithUpdatedArtifact,
        projects: state.projects.map(p => 
          p.id === projectWithUpdatedArtifact.id ? projectWithUpdatedArtifact : p
        )
      };
    
    case actionTypes.DELETE_ARTIFACT:
      if (!state.currentProject) return state;
      const projectWithoutArtifact = {
        ...state.currentProject,
        artifacts: state.currentProject.artifacts?.filter(artifact =>
          artifact.id !== action.payload
        ) || []
      };
      return {
        ...state,
        currentProject: projectWithoutArtifact,
        projects: state.projects.map(p => 
          p.id === projectWithoutArtifact.id ? projectWithoutArtifact : p
        )
      };
    
    default:
      return state;
  }
};

// Context
const LSSProjectContext = createContext();

// Provider component
export const LSSProjectProvider = ({ children }) => {
  const [state, dispatch] = useReducer(projectReducer, initialState);

  // Load projects from localStorage on mount
  useEffect(() => {
    loadProjects();
  }, []);

  // Save projects to localStorage whenever projects change
  useEffect(() => {
    if (state.projects.length > 0) {
      localStorage.setItem('lss_projects', JSON.stringify(state.projects));
    }
    updateMetrics();
  }, [state.projects]);

  // Helper functions
  const generateId = () => {
    return Date.now().toString(36) + Math.random().toString(36).substr(2);
  };

  const calculateMetrics = (projects) => {
    const activeProjects = projects.filter(p => p.status !== 'completed').length;
    const completedProjects = projects.filter(p => p.status === 'completed').length;
    const totalSavings = projects.reduce((sum, p) => sum + (p.savings || 0), 0);
    
    // Calculate average cycle time for completed projects
    const completedWithDates = projects.filter(p => 
      p.status === 'completed' && p.startDate && p.endDate
    );
    const avgCycleTime = completedWithDates.length > 0
      ? completedWithDates.reduce((sum, p) => {
          const start = new Date(p.startDate);
          const end = new Date(p.endDate);
          const days = Math.ceil((end - start) / (1000 * 60 * 60 * 24));
          return sum + days;
        }, 0) / completedWithDates.length
      : 0;

    return {
      activeProjects,
      completedProjects,
      totalSavings,
      avgCycleTime: Math.round(avgCycleTime)
    };
  };

  // Actions
  const loadProjects = () => {
    try {
      dispatch({ type: actionTypes.SET_LOADING, payload: true });
      const savedProjects = localStorage.getItem('lss_projects');
      const projects = savedProjects ? JSON.parse(savedProjects) : [];
      dispatch({ type: actionTypes.LOAD_PROJECTS, payload: projects });
    } catch (error) {
      dispatch({ type: actionTypes.SET_ERROR, payload: 'Failed to load projects' });
    }
  };

  const createProject = (projectData) => {
    try {
      const newProject = {
        id: generateId(),
        ...projectData,
        createdAt: new Date().toISOString(),
        updatedAt: new Date().toISOString(),
        status: 'active',
        currentPhase: 'define',
        progress: 0,
        artifacts: [],
        team: projectData.team || [],
        savings: 0,
        startDate: projectData.startDate || new Date().toISOString()
      };
      
      dispatch({ type: actionTypes.CREATE_PROJECT, payload: newProject });
      return newProject;
    } catch (error) {
      dispatch({ type: actionTypes.SET_ERROR, payload: 'Failed to create project' });
      return null;
    }
  };

  const updateProject = (projectId, updates) => {
    try {
      const project = state.projects.find(p => p.id === projectId);
      if (!project) {
        throw new Error('Project not found');
      }

      const updatedProject = {
        ...project,
        ...updates,
        updatedAt: new Date().toISOString()
      };

      dispatch({ type: actionTypes.UPDATE_PROJECT, payload: updatedProject });
      return updatedProject;
    } catch (error) {
      dispatch({ type: actionTypes.SET_ERROR, payload: 'Failed to update project' });
      return null;
    }
  };

  const deleteProject = (projectId) => {
    try {
      dispatch({ type: actionTypes.DELETE_PROJECT, payload: projectId });
      return true;
    } catch (error) {
      dispatch({ type: actionTypes.SET_ERROR, payload: 'Failed to delete project' });
      return false;
    }
  };

  const setCurrentProject = (project) => {
    dispatch({ type: actionTypes.SET_CURRENT_PROJECT, payload: project });
  };

  const updateMetrics = () => {
    const metrics = calculateMetrics(state.projects);
    dispatch({ type: actionTypes.UPDATE_METRICS, payload: metrics });
  };

  // Artifact management
  const addArtifact = (artifactData) => {
    try {
      const newArtifact = {
        id: generateId(),
        ...artifactData,
        createdAt: new Date().toISOString(),
        updatedAt: new Date().toISOString()
      };
      
      dispatch({ type: actionTypes.ADD_ARTIFACT, payload: newArtifact });
      return newArtifact;
    } catch (error) {
      dispatch({ type: actionTypes.SET_ERROR, payload: 'Failed to add artifact' });
      return null;
    }
  };

  const updateArtifact = (artifactId, updates) => {
    try {
      const artifact = state.currentProject?.artifacts?.find(a => a.id === artifactId);
      if (!artifact) {
        throw new Error('Artifact not found');
      }

      const updatedArtifact = {
        ...artifact,
        ...updates,
        updatedAt: new Date().toISOString()
      };

      dispatch({ type: actionTypes.UPDATE_ARTIFACT, payload: updatedArtifact });
      return updatedArtifact;
    } catch (error) {
      dispatch({ type: actionTypes.SET_ERROR, payload: 'Failed to update artifact' });
      return null;
    }
  };

  const deleteArtifact = (artifactId) => {
    try {
      dispatch({ type: actionTypes.DELETE_ARTIFACT, payload: artifactId });
      return true;
    } catch (error) {
      dispatch({ type: actionTypes.SET_ERROR, payload: 'Failed to delete artifact' });
      return false;
    }
  };

  // Get projects by status
  const getProjectsByStatus = (status) => {
    return state.projects.filter(project => project.status === status);
  };

  // Get projects by phase
  const getProjectsByPhase = (phase) => {
    return state.projects.filter(project => project.currentPhase === phase);
  };

  // Get recent artifacts across all projects
  const getRecentArtifacts = (limit = 10) => {
    const allArtifacts = state.projects.flatMap(project => 
      (project.artifacts || []).map(artifact => ({
        ...artifact,
        projectName: project.name,
        projectId: project.id
      }))
    );
    
    return allArtifacts
      .sort((a, b) => new Date(b.updatedAt) - new Date(a.updatedAt))
      .slice(0, limit);
  };

  const value = {
    // State
    ...state,
    
    // Actions
    loadProjects,
    createProject,
    updateProject,
    deleteProject,
    setCurrentProject,
    addArtifact,
    updateArtifact,
    deleteArtifact,
    
    // Getters
    getProjectsByStatus,
    getProjectsByPhase,
    getRecentArtifacts
  };

  return (
    <LSSProjectContext.Provider value={value}>
      {children}
    </LSSProjectContext.Provider>
  );
};

// Custom hook
export const useLSSProject = () => {
  const context = useContext(LSSProjectContext);
  if (!context) {
    throw new Error('useLSSProject must be used within a LSSProjectProvider');
  }
  return context;
};

export default LSSProjectContext;

