import React, { useState, useEffect, useRef, useCallback } from 'react';
import { useNavigate, useParams, useLocation } from 'react-router-dom';
import { FontAwesomeIcon } from '@fortawesome/react-fontawesome';
import {
  faArrowLeft, faListCheck, faChartGantt, faChartLine, faDollarSign,
  faBullseye, faUsers, faTriangleExclamation, faFileLines, faCheckCircle,
  faClock, faFolder, faBookmark, faWandMagicSparkles, faTimes, faPaperPlane,
  faList, faTableColumns, faPlus, faTrash, faGripVertical, faMicrophone,
  faCog, faEye, faEyeSlash, faSearchPlus, faSearchMinus, faCalendarPlus,
  faChevronDown, faChevronRight, faEnvelope, faHome
} from '@fortawesome/free-solid-svg-icons';
import styles from './ProjectPlanning.module.css';
import { useChatCommands, parseUIActions, ChatActionTypes } from 'All/shared/hooks/useChatCommands';
import { useToast, ToastContainer } from 'All/shared/components/Toast';
import { STARTER_PLAN } from './starterData';

const API_BASE = process.env.REACT_APP_API_BASE || '';

const ProjectPlanning = () => {
  const navigate = useNavigate();
  const { projectId } = useParams();
  const location = useLocation();
  
  // PROMPT ALIGNMENT: Extract scorecard data from navigation state
  const scorecardId = location.state?.scorecardId || null;
  const scorecardData = location.state?.scorecardData || null;

  // ==================== STATE ====================
  const [plan, setPlan] = useState(null);
  const [loading, setLoading] = useState(true);
  const [autoSaving, setAutoSaving] = useState(false);
  const [lastSaved, setLastSaved] = useState(null);
  const [validating, setValidating] = useState(false);

  // UI State
  const [pmMenuOpen, setPmMenuOpen] = useState(false);
  const [aiHelperOpen, setAiHelperOpen] = useState(false);
  const [activeNav, setActiveNav] = useState('tasks');
  const [currentView, setCurrentView] = useState('list');
  const [showSettings, setShowSettings] = useState(false);
// Validation Modal state
const [showValidationModal, setShowValidationModal] = useState(false);
const [styleChoice, setStyleChoice] = useState('agile');  // ui selection
const [styleSource, setStyleSource] = useState(null);     // 'user' | 'heuristic' | null
const [styleReason, setStyleReason] = useState(null);     // string reason(s)
const [styleDuration, setStyleDuration] = useState(null); // numeric months
const [regenBusy, setRegenBusy] = useState(false);

  // Settings State
  const [visibleColumns, setVisibleColumns] = useState({
    task: true,
    assignee: true,
    priority: true,
    status: true,
    dueDate: true,
    notes: true,
    actions: true
  });

  // Gantt State
  const [ganttZoom, setGanttZoom] = useState(1); // 1 = normal, 2 = zoomed in, 0.5 = zoomed out

  // AI State
  const [aiMessages, setAiMessages] = useState([
    { role: 'assistant', content: 'I\'ve created an initial project plan with starter data. You can manually edit any field by clicking on it, or ask me to make changes. Try "Add a high priority task to Initialization phase" or "Apply the Software Launch template".' }
  ]);
  const [aiInput, setAiInput] = useState('');
  const [aiProcessing, setAiProcessing] = useState(false);
  // Toast notifications for chat actions
  const { toasts, showToast, dismissToast } = useToast();

  const [isRecording, setIsRecording] = useState(false);

  // Template State
  const [templates, setTemplates] = useState([]);
  const [showTemplateModal, setShowTemplateModal] = useState(false);
  const [showSaveTemplateModal, setShowSaveTemplateModal] = useState(false);
  const [templateName, setTemplateName] = useState('');
  const [templateDescription, setTemplateDescription] = useState('');

  // Drag State
  const [draggedTask, setDraggedTask] = useState(null);
  const [draggedPhase, setDraggedPhase] = useState(null);

  // Inline Editing State
  const [editingCell, setEditingCell] = useState(null); // { type, id, field }

  // Project Meta
  const [projectName, setProjectName] = useState('SEKKI - Market IQ');
  const projectDate = 'Dec 9, 2025';

  // Refs
  const saveTimeoutRef = useRef(null);
  const recognitionRef = useRef(null);


  // PROMPT ALIGNMENT: Scorecard context for this project
  const [scorecardInfo, setScorecardInfo] = useState(null);
  
  useEffect(() => {
    if (scorecardId && scorecardData) {
      setScorecardInfo({
        id: scorecardId,
        label: scorecardData.label || 'Scorecard',
        source: scorecardData.source || 'baseline',
        timestamp: scorecardData.timestamp
      });
      console.log('[ProjectPlanning] Loaded with scorecard:', scorecardId);
    }
  }, [scorecardId, scorecardData]);


  // === Chat Command Handlers (Lovable-style) ===
  const chatCommandHandlers = {
    [ChatActionTypes.VIEW_SET]: (payload) => {
      const { view } = payload;
      if (['list', 'gantt', 'kanban'].includes(view)) {
        setCurrentView(view);
        showToast(`Switched to ${view} view`, 'success');
      } else {
        showToast('Invalid view type', 'error');
      }
    },
    
    [ChatActionTypes.WBS_ADD_TASK]: (payload) => {
      const { parentTaskId, title, duration, start, end, assignee } = payload;
      
      if (!title) {
        showToast('Task title is required', 'error');
        return;
      }
      
      // Find parent phase or use first phase
      let targetPhaseIndex = 0;
      if (parentTaskId && plan?.phases) {
        targetPhaseIndex = plan.phases.findIndex(p => 
          p.tasks?.some(t => t.id === parentTaskId)
        );
        if (targetPhaseIndex === -1) targetPhaseIndex = 0;
      }
      
      const newTask = {
        id: `task_${Date.now()}`,
        name: title,
        assignee: assignee || 'Unassigned',
        priority: 'Medium',
        status: 'Not Started',
        dueDate: end || start || '',
        duration: duration || '',
        notes: ''
      };
      
      const updatedPlan = { ...plan };
      if (!updatedPlan.phases[targetPhaseIndex].tasks) {
        updatedPlan.phases[targetPhaseIndex].tasks = [];
      }
      updatedPlan.phases[targetPhaseIndex].tasks.push(newTask);
      setPlan(updatedPlan);
      
      showToast(`Added task: ${title}`, 'success');
    },
    
    [ChatActionTypes.WBS_UPDATE_TASK]: (payload) => {
      const { taskId, patch } = payload;
      
      if (!taskId || !patch) {
        showToast('Task ID and updates are required', 'error');
        return;
      }
      
      const updatedPlan = { ...plan };
      let taskFound = false;
      
      updatedPlan.phases?.forEach(phase => {
        phase.tasks?.forEach(task => {
          if (task.id === taskId) {
            Object.assign(task, patch);
            taskFound = true;
          }
        });
      });
      
      if (taskFound) {
        setPlan(updatedPlan);
        showToast('Task updated', 'success');
      } else {
        showToast('Task not found', 'error');
      }
    },
    
    [ChatActionTypes.WBS_ADD_DEPENDENCY]: (payload) => {
      const { fromTaskId, toTaskId, type } = payload;
      
      // This would require a dependencies data structure
      // For now, just acknowledge
      showToast(`Dependency added: ${type || 'FS'}`, 'info');
      console.log('[ProjectPlanning] Add dependency:', payload);
    },
    
    [ChatActionTypes.EXPORT]: (payload) => {
      const { format } = payload;
      
      if (format === 'csv') {
        // Call existing export if available
        showToast('CSV export not yet implemented', 'info');
      } else if (format === 'msproject') {
        showToast('MS Project export not yet implemented', 'info');
      } else {
        showToast('Unknown export format', 'error');
      }
    },
  };
  
  const { dispatchChatActions } = useChatCommands(chatCommandHandlers);

    // ==================== EFFECTS ====================
  useEffect(() => {
    loadPlan();
    loadTemplates();
  }, [projectId]);

  // Auto-save debounce
  useEffect(() => {
    if (!plan) return;
    
    if (saveTimeoutRef.current) {
      clearTimeout(saveTimeoutRef.current);
    }

    saveTimeoutRef.current = setTimeout(() => {
      savePlan();
    }, 1000);

    return () => {
      if (saveTimeoutRef.current) {
        clearTimeout(saveTimeoutRef.current);
      }
    };
  }, [plan]);

  // ==================== DATA LOADING ====================
  const deepClone = (obj) => JSON.parse(JSON.stringify(obj));

  const loadPlan = async () => {
    setLoading(true);
    try {
      if (!projectId) {
        setPlan(deepClone(STARTER_PLAN));
        setLoading(false);
        return;
      }

      const res = await fetch(`${API_BASE}/api/projects/${projectId}/plan`, {
        credentials: 'include'
      });

      if (!res.ok) {
        if (res.status === 404) {
          setPlan(deepClone(STARTER_PLAN));
          setLoading(false);
          return;
        }
        throw new Error('Failed to load plan');
      }

      const data = await res.json();
      const mergedPlan = {
        ...deepClone(STARTER_PLAN),
        ...data,
        wbs: {
          ...STARTER_PLAN.wbs,
          ...(data.wbs || {}),
          items: data.wbs?.items || STARTER_PLAN.wbs.items
        },
        timeline: {
          ...STARTER_PLAN.timeline,
          ...(data.timeline || {})
        },
        objectives: data.objectives || STARTER_PLAN.objectives,
        stakeholders: data.stakeholders || STARTER_PLAN.stakeholders,
        risks: data.risks || STARTER_PLAN.risks,
        resources: {
          ...STARTER_PLAN.resources,
          ...(data.resources || {})
        },
        documents: data.documents || STARTER_PLAN.documents
      };

      setPlan(mergedPlan);
      setLastSaved(new Date());
    } catch (err) {
      console.error('Error loading plan:', err);
      setPlan(deepClone(STARTER_PLAN));
    } finally {
      setLoading(false);
    }
  };

  const loadTemplates = async () => {
    try {
      const res = await fetch(`${API_BASE}/api/templates`, {
        credentials: 'include'
      });
      if (res.ok) {
        const data = await res.json();
        setTemplates(data);
      }
    } catch (err) {
      console.error('Error loading templates:', err);
    }
  };

  const savePlan = async () => {
    if (!projectId || !plan) return;

    setAutoSaving(true);
    try {
      const res = await fetch(`${API_BASE}/api/projects/${projectId}/plan`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'include',
        body: JSON.stringify(plan)
      });

      if (res.ok) {
        setLastSaved(new Date());
      }
    } catch (err) {
      console.error('Auto-save error:', err);
    } finally {
      setAutoSaving(false);
    }
  };

  const validatePlan = async () => {
    setValidating(true);
    try {
      if (projectId) {
        const res = await fetch(`${API_BASE}/api/projects/${projectId}/plan/validate`, {
          method: 'POST',
          credentials: 'include'
        });
        if (res.ok) {
          window.alert('Project plan validated successfully!');
          navigate('/market-iq');
        }
      } else {
        window.alert('Project plan validated!');
        navigate('/market-iq');
      }
    } catch (err) {
      console.error('Validation error:', err);
      window.alert('Error validating plan');
    } finally {
      setValidating(false);
    }
  };
const regenerateWithStyle = async (forced) => {
  if (!projectId || !forced) return false;

  setRegenBusy(true);
  try {
    // NEW endpoint expectation: POST /api/projects/:id/plan/regenerate
    // body: { force_style: 'agile' | 'waterfall' | 'hybrid' }
    const res = await fetch(`${API_BASE}/api/projects/${projectId}/plan/regenerate`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      credentials: 'include',
      body: JSON.stringify({ force_style: forced })
    });

    if (!res.ok) {
      // graceful fallback: directly PATCH local plan style so user isn’t blocked
      setPlan(prev => {
        const next = deepClone(prev);
        if (!next.wbs) next.wbs = { items: [] };
        next.wbs.style = forced;
        // make the reason clear in UI if backend didn't return one
        next.wbs.meta = {
          ...(next.wbs.meta || {}),
          style_source: 'user',
          style_reason: `user override: ${forced}`
        };
        return next;
      });
      return false;
    }
const confirmValidation = async () => {
  const currentStyle = deriveStyleFromPlan(plan);
  const wantStyle = styleChoice;

  // If user changed style, try to regenerate first
  if (currentStyle !== wantStyle) {
    const ok = await regenerateWithStyle(wantStyle);
    if (!ok) {
      // We still proceed to validation so user isn’t blocked
      // but they will see the locally updated style even if backend skipped regeneration
    }
  }

  // Now run your existing validation
  await validatePlan();
  setShowValidationModal(false);
};

const closeValidationModal = () => {
  setShowValidationModal(false);
};

    const data = await res.json();
    // Expect the backend to return the updated plan
    if (data?.plan) {
      setPlan(data.plan);
      const s = deriveStyleFromPlan(data.plan);
      const meta = deriveStyleMeta(data.plan);
      setStyleChoice(s);
      setStyleSource(meta.style_source);
      setStyleReason(meta.style_reason);
      setStyleDuration(meta.duration_months);
    }
    return true;
  } catch (err) {
    console.error('[regenerateWithStyle] failed', err);
    // fallback already handled above if res !ok
    return false;
  } finally {
    setRegenBusy(false);
  }
};
// ---- Validation modal handlers (MUST be inside ProjectPlanning component) ----
const closeValidationModal = () => {
  setShowValidationModal(false);
};

const confirmValidation = async () => {
  // Requires: validatePlan, regenerateWithStyle, deriveStyleFromPlan, plan, styleChoice
  const currentStyle = deriveStyleFromPlan(plan);
  const wantStyle = styleChoice;

  // If user changed the style, regenerate first (best-effort)
  if (currentStyle !== wantStyle) {
    try {
      await regenerateWithStyle(wantStyle);
    } catch (e) {
      console.debug('[confirmValidation] regenerate skipped/failed, proceeding to validate');
    }
  }

  // Then run your existing validation
  await validatePlan();
  setShowValidationModal(false);
};

  const cancelPlan = () => {
    if (window.confirm('Are you sure you want to cancel? Unsaved changes will be lost.')) {
      navigate('/market-iq');
    }
  };

  // ==================== TEMPLATE FUNCTIONS ====================
  const saveAsTemplate = async () => {
    if (!templateName.trim()) {
      window.alert('Please enter a template name');
      return;
    }

    try {
      const templateData = {
        name: templateName,
        description: templateDescription,
        phases: plan.wbs.items.map(phase => ({
          name: phase.name,
          tasks: phase.children.map(task => ({
            name: task.name,
            lead_time_days: task.lead_time_days || 0
          }))
        }))
      };

      const res = await fetch(`${API_BASE}/api/templates`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'include',
        body: JSON.stringify(templateData)
      });

      if (res.ok) {
        window.alert('Template saved successfully!');
        setShowSaveTemplateModal(false);
        setTemplateName('');
        setTemplateDescription('');
        loadTemplates();
      }
    } catch (err) {
      console.error('Error saving template:', err);
      window.alert('Error saving template');
    }
  };

  const applyTemplate = async (templateId) => {
    try {
      const res = await fetch(`${API_BASE}/api/projects/${projectId}/apply-template`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'include',
        body: JSON.stringify({ template_id: templateId })
      });

      if (res.ok) {
        window.alert('Template applied successfully!');
        setShowTemplateModal(false);
        loadPlan();
      }
    } catch (err) {
      console.error('Error applying template:', err);
      window.alert('Error applying template');
    }
  };

  // ==================== AI ASSISTANT ====================
  const sendAIMessage = async () => {
    if (!aiInput.trim() || aiProcessing) return;

    const userMessage = aiInput.trim();
    setAiMessages(prev => [...prev, { role: 'user', content: userMessage }]);
    setAiInput('');
    setAiProcessing(true);

    try {
      const res = await fetch(`${API_BASE}/api/projects/${projectId}/ai-assist`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'include',
        body: JSON.stringify({ message: userMessage, plan })
      });

      if (res.ok) {
        const data = await res.json();
        setAiMessages(prev => [...prev, { role: 'assistant', content: data.response }]);
        if (data.updated_plan) {
          setPlan(data.updated_plan);
        }
      } else {
        setAiMessages(prev => [...prev, { 
          role: 'assistant', 
          content: 'I processed your request. The plan has been updated. (Backend integration pending)' 
        }]);
      }
    } catch (err) {
      console.error('AI error:', err);
      setAiMessages(prev => [...prev, { 
        role: 'assistant', 
        content: 'I understand your request. Once the backend is connected, I\'ll be able to make those changes automatically.' 
      }]);
    } finally {
      setAiProcessing(false);
    }
  };

  // Voice-to-text
  const startVoiceRecording = () => {
    if (!('webkitSpeechRecognition' in window) && !('SpeechRecognition' in window)) {
      window.alert('Speech recognition is not supported in this browser.');
      return;
    }

    const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
    const recognition = new SpeechRecognition();
    recognition.continuous = false;
    recognition.interimResults = false;

    recognition.onstart = () => {
      setIsRecording(true);
    };

    recognition.onresult = (event) => {
      const transcript = event.results[0][0].transcript;
      setAiInput(prev => prev + ' ' + transcript);
    };

    recognition.onerror = (event) => {
      console.error('Speech recognition error:', event.error);
      setIsRecording(false);
    };

    recognition.onend = () => {
      setIsRecording(false);
    };

    recognitionRef.current = recognition;
    recognition.start();
  };

  const stopVoiceRecording = () => {
    if (recognitionRef.current) {
      recognitionRef.current.stop();
    }
    setIsRecording(false);
  };

  // ==================== SIDEBAR TOGGLES ====================
  const togglePmMenu = () => {
    setPmMenuOpen(!pmMenuOpen);
    if (aiHelperOpen) setAiHelperOpen(false);
  };

  const toggleAI = () => {
    setAiHelperOpen(!aiHelperOpen);
    if (pmMenuOpen) setPmMenuOpen(false);
  };

  // ==================== UTILITY FUNCTIONS ====================
  const fmtDate = (dateStr) => {
    if (!dateStr) return '';
    const d = new Date(dateStr);
    return d.toLocaleDateString('en-US', { month: 'short', day: 'numeric' });
  };

  const fmtFullDate = (dateStr) => {
    if (!dateStr) return '';
    const d = new Date(dateStr);
    return d.toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' });
  };

  const generateId = () => {
    return 'id_' + Math.random().toString(36).substr(2, 9);
  };
function deriveStyleFromPlan(p) {
  // Try multiple places plan might carry this — adjust if your backend uses different keys
  const s = (p?.wbs?.style || p?.style || '').toString().toLowerCase();
  return (s === 'agile' || s === 'waterfall' || s === 'hybrid') ? s : 'agile';
}

function deriveStyleMeta(p) {
  // Backends often stash meta in plan or plan.wbs
  const meta = p?.wbs?.meta || p?.meta || {};
  return {
    style_source: meta.style_source || null,
    style_reason: meta.style_reason || null,
    duration_months: p?.timeline?.duration_months ?? p?.duration_months ?? null,
  };
}

// Called instead of validatePlan (opens the modal)
function openValidationModal() {
  if (!plan) return;
  const s = deriveStyleFromPlan(plan);
  const meta = deriveStyleMeta(plan);
  setStyleChoice(s);
  setStyleSource(meta.style_source);
  setStyleReason(meta.style_reason);
  setStyleDuration(meta.duration_months);
  setShowValidationModal(true);
}

  // ==================== INLINE EDITING ====================
  const startEdit = (type, id, field) => {
    setEditingCell({ type, id, field });
  };

  const stopEdit = () => {
    setEditingCell(null);
  };

  const updateCellValue = (type, id, field, value) => {
    if (type === 'task') {
      const [phaseId, taskId] = id.split('|');
      updateTaskField(phaseId, taskId, { [field]: value });
    } else if (type === 'phase') {
      updatePhase(id, { [field]: value });
    } else if (type === 'risk') {
      updateRisk(id, { [field]: value });
    } else if (type === 'objective') {
      updateObjective(id, { [field]: value });
    } else if (type === 'stakeholder') {
      updateStakeholder(id, { [field]: value });
    } else if (type === 'budget') {
      updateBudgetItem(id, { [field]: value });
    }
    stopEdit();
  };

  // ==================== TASK CRUD ====================
  const addTask = (phaseId) => {
    const newTask = {
      id: generateId(),
      name: 'New Task',
      assignee: 'Unassigned',
      priority: '',
      status: 'todo',
      due_date: '',
      notes: '',
      lead_time_days: 0,
      completed: false
    };

    setPlan(prev => ({
      ...prev,
      wbs: {
        ...prev.wbs,
        items: prev.wbs.items.map(phase =>
          phase.id === phaseId
            ? { ...phase, children: [...phase.children, newTask] }
            : phase
        )
      }
    }));
  };

  const updateTaskField = (phaseId, taskId, updates) => {
    setPlan(prev => ({
      ...prev,
      wbs: {
        ...prev.wbs,
        items: prev.wbs.items.map(phase =>
          phase.id === phaseId
            ? {
                ...phase,
                children: phase.children.map(task =>
                  task.id === taskId ? { ...task, ...updates } : task
                )
              }
            : phase
        )
      }
    }));
  };

  const deleteTask = (phaseId, taskId) => {
    setPlan(prev => ({
      ...prev,
      wbs: {
        ...prev.wbs,
        items: prev.wbs.items.map(phase =>
          phase.id === phaseId
            ? { ...phase, children: phase.children.filter(t => t.id !== taskId) }
            : phase
        )
      }
    }));
  };

  // ==================== PHASE CRUD ====================
  const addPhase = () => {
    const newPhase = {
      id: generateId(),
      name: 'New Phase',
      children: []
    };

    setPlan(prev => ({
      ...prev,
      wbs: {
        ...prev.wbs,
        items: [...prev.wbs.items, newPhase]
      }
    }));
  };

  const updatePhase = (phaseId, updates) => {
    setPlan(prev => ({
      ...prev,
      wbs: {
        ...prev.wbs,
        items: prev.wbs.items.map(phase =>
          phase.id === phaseId ? { ...phase, ...updates } : phase
        )
      }
    }));
  };

  const deletePhase = (phaseId) => {
    if (!window.confirm('Delete this phase and all its tasks?')) return;
    
    setPlan(prev => ({
      ...prev,
      wbs: {
        ...prev.wbs,
        items: prev.wbs.items.filter(p => p.id !== phaseId)
      }
    }));
  };

  // ==================== RISK CRUD ====================
  const addRisk = () => {
    const newRisk = {
      id: generateId(),
      name: 'New Risk',
      category: 'General',
      likelihood: 'Medium',
      impact: 'Medium',
      owner: 'Unassigned',
      mitigation: '',
      status: 'Identified'
    };

    setPlan(prev => ({
      ...prev,
      risks: [...(prev.risks || []), newRisk]
    }));
  };

  const updateRisk = (riskId, updates) => {
    setPlan(prev => ({
      ...prev,
      risks: (prev.risks || []).map(risk =>
        risk.id === riskId ? { ...risk, ...updates } : risk
      )
    }));
  };

  const deleteRisk = (riskId) => {
    setPlan(prev => ({
      ...prev,
      risks: (prev.risks || []).filter(r => r.id !== riskId)
    }));
  };

  // ==================== OBJECTIVE CRUD ====================
  const addObjective = () => {
    const newObjective = {
      id: generateId(),
      title: 'New Objective',
      description: '',
      progress: 0,
      key_results: []
    };

    setPlan(prev => ({
      ...prev,
      objectives: [...(prev.objectives || []), newObjective]
    }));
  };

  const updateObjective = (objId, updates) => {
    setPlan(prev => ({
      ...prev,
      objectives: (prev.objectives || []).map(obj =>
        obj.id === objId ? { ...obj, ...updates } : obj
      )
    }));
  };

  const deleteObjective = (objId) => {
    setPlan(prev => ({
      ...prev,
      objectives: (prev.objectives || []).filter(o => o.id !== objId)
    }));
  };

  // ==================== STAKEHOLDER CRUD ====================
  const addStakeholder = (roleType = 'core_team') => {
    const newStakeholder = {
      id: generateId(),
      name: 'New Stakeholder',
      role: 'Role',
      role_type: roleType,
      email: '',
      influence: 2
    };

    setPlan(prev => ({
      ...prev,
      stakeholders: [...(prev.stakeholders || []), newStakeholder]
    }));
  };

  const updateStakeholder = (stakeholderId, updates) => {
    setPlan(prev => ({
      ...prev,
      stakeholders: (prev.stakeholders || []).map(s =>
        s.id === stakeholderId ? { ...s, ...updates } : s
      )
    }));
  };

  const deleteStakeholder = (stakeholderId) => {
    setPlan(prev => ({
      ...prev,
      stakeholders: (prev.stakeholders || []).filter(s => s.id !== stakeholderId)
    }));
  };

  // ==================== BUDGET CRUD ====================
  const addBudgetItem = () => {
    const newItem = {
      id: generateId(),
      category: 'New Category',
      description: '',
      amount: 0
    };

    setPlan(prev => ({
      ...prev,
      resources: {
        ...prev.resources,
        budget: {
          ...prev.resources.budget,
          items: [...(prev.resources.budget.items || []), newItem]
        }
      }
    }));
  };

  const updateBudgetItem = (itemId, updates) => {
    setPlan(prev => ({
      ...prev,
      resources: {
        ...prev.resources,
        budget: {
          ...prev.resources.budget,
          items: (prev.resources.budget.items || []).map(item =>
            item.id === itemId ? { ...item, ...updates } : item
          )
        }
      }
    }));
  };

  const deleteBudgetItem = (itemId) => {
    setPlan(prev => ({
      ...prev,
      resources: {
        ...prev.resources,
        budget: {
          ...prev.resources.budget,
          items: (prev.resources.budget.items || []).filter(i => i.id !== itemId)
        }
      }
    }));
  };

  // ==================== DOCUMENT CRUD ====================
  const addDocument = () => {
    const newDoc = {
      id: generateId(),
      filename: 'New Document.pdf',
      category: 'Planning',
      size: '0 KB',
      owner: 'You',
      uploaded_at: new Date().toISOString()
    };

    setPlan(prev => ({
      ...prev,
      documents: [...(prev.documents || []), newDoc]
    }));
  };

  const deleteDocument = (docId) => {
    setPlan(prev => ({
      ...prev,
      documents: (prev.documents || []).filter(d => d.id !== docId)
    }));
  };

  // ==================== DRAG AND DROP ====================
  const handleTaskDragStart = (e, phaseId, task) => {
    setDraggedTask({ phaseId, task });
    e.dataTransfer.effectAllowed = 'move';
  };

  const handleTaskDragOver = (e) => {
    e.preventDefault();
    e.dataTransfer.dropEffect = 'move';
  };

  const handleTaskDrop = (e, targetPhaseId) => {
    e.preventDefault();
    if (!draggedTask) return;

    const { phaseId: sourcePhaseId, task } = draggedTask;

    if (sourcePhaseId === targetPhaseId) {
      setDraggedTask(null);
      return;
    }

    // Remove from source
    setPlan(prev => {
      const items = prev.wbs.items.map(phase => {
        if (phase.id === sourcePhaseId) {
          return { ...phase, children: phase.children.filter(t => t.id !== task.id) };
        }
        if (phase.id === targetPhaseId) {
          return { ...phase, children: [...phase.children, task] };
        }
        return phase;
      });

      return {
        ...prev,
        wbs: { ...prev.wbs, items }
      };
    });

    setDraggedTask(null);
  };

  const handleBoardCardDragStart = (e, task) => {
    setDraggedTask({ task });
    e.dataTransfer.effectAllowed = 'move';
  };

  const handleBoardColumnDrop = (e, newStatus) => {
    e.preventDefault();
    if (!draggedTask) return;

    const { task } = draggedTask;
    
    // Find task and update status
    setPlan(prev => ({
      ...prev,
      wbs: {
        ...prev.wbs,
        items: prev.wbs.items.map(phase => ({
          ...phase,
          children: phase.children.map(t =>
            t.id === task.id ? { ...t, status: newStatus } : t
          )
        }))
      }
    }));

    setDraggedTask(null);
  };

  // ==================== GANTT FUNCTIONS ====================
  const zoomGanttIn = () => {
    setGanttZoom(prev => Math.min(prev * 1.5, 3));
  };

  const zoomGanttOut = () => {
    setGanttZoom(prev => Math.max(prev / 1.5, 0.5));
  };

  const addMilestone = () => {
    const milestoneName = window.prompt('Enter milestone name:');
    if (!milestoneName) return;

    const milestoneDate = window.prompt('Enter milestone date (YYYY-MM-DD):');
    if (!milestoneDate) return;

    // Add to timeline
    setPlan(prev => ({
      ...prev,
      timeline: {
        ...prev.timeline,
        milestones: [
          ...(prev.timeline.milestones || []),
          {
            id: generateId(),
            name: milestoneName,
            date: milestoneDate
          }
        ]
      }
    }));

    window.alert('Milestone added!');
  };

  // ==================== RENDER: DENSE TASK LIST ====================
  const renderDenseList = () => {
    if (!plan?.wbs?.items) return null;

    return (
      <div className={styles.denseTableWrapper}>
        <div className={styles.denseTableHeader}>
          <button className={styles.iconBtn} onClick={() => setShowSettings(!showSettings)} title="Settings">
            <FontAwesomeIcon icon={faCog} />
          </button>
        </div>

        {/* Settings Panel */}
        {showSettings && (
          <div className={styles.settingsPanel}>
            <div className={styles.settingsPanelHeader}>
              <div className={styles.settingsPanelTitle}>Column Visibility</div>
              <button className={styles.closeBtn} onClick={() => setShowSettings(false)}>
                <FontAwesomeIcon icon={faTimes} />
              </button>
            </div>
            <div className={styles.settingsPanelBody}>
              {Object.keys(visibleColumns).map(col => (
                <label key={col} className={styles.settingsCheckbox}>
                  <input
                    type="checkbox"
                    checked={visibleColumns[col]}
                    onChange={(e) => setVisibleColumns(prev => ({ ...prev, [col]: e.target.checked }))}
                  />
                  <span>{col.charAt(0).toUpperCase() + col.slice(1).replace(/([A-Z])/g, ' $1')}</span>
                </label>
              ))}
            </div>
          </div>
        )}

        <table className={styles.denseTable}>
          <thead>
            <tr>
              <th style={{ width: '30px' }}></th>
              {visibleColumns.task && <th style={{ width: '30%' }}>Task</th>}
              {visibleColumns.assignee && <th style={{ width: '15%' }}>Assignee</th>}
              {visibleColumns.priority && <th style={{ width: '10%' }}>Priority</th>}
              {visibleColumns.status && <th style={{ width: '12%' }}>Status</th>}
              {visibleColumns.dueDate && <th style={{ width: '12%' }}>Due Date</th>}
              {visibleColumns.notes && <th style={{ width: '15%' }}>Notes</th>}
              {visibleColumns.actions && <th style={{ width: '6%' }}>Actions</th>}
            </tr>
          </thead>
          <tbody>
            {plan.wbs.items.map(phase => (
              <React.Fragment key={phase.id}>
                {/* Phase Row */}
                <tr className={styles.phaseRow}>
                  <td colSpan={Object.values(visibleColumns).filter(Boolean).length + 1}>
                    <div className={styles.phaseRowContent}>
                      <FontAwesomeIcon icon={faGripVertical} className={styles.gripHandle} />
                      <span
                        className={styles.editableCell}
                        contentEditable
                        suppressContentEditableWarning
                        onBlur={(e) => updatePhase(phase.id, { name: e.target.textContent })}
                      >
                        {phase.name}
                      </span>
                      <span className={styles.phaseTaskCount}>({phase.children.length} tasks)</span>
                      <div className={styles.phaseActions}>
                        <button className={styles.iconBtn} onClick={() => addTask(phase.id)} title="Add Task">
                          <FontAwesomeIcon icon={faPlus} />
                        </button>
                        <button className={styles.iconBtn} onClick={() => deletePhase(phase.id)} title="Delete Phase">
                          <FontAwesomeIcon icon={faTrash} />
                        </button>
                      </div>
                    </div>
                  </td>
                </tr>

                {/* Task Rows */}
                {phase.children.map(task => (
                  <tr
                    key={task.id}
                    className={styles.taskRow}
                    draggable
                    onDragStart={(e) => handleTaskDragStart(e, phase.id, task)}
                    onDragOver={handleTaskDragOver}
                    onDrop={(e) => handleTaskDrop(e, phase.id)}
                  >
                    <td>
                      <FontAwesomeIcon icon={faGripVertical} className={styles.gripHandle} />
                    </td>
                    
                    {visibleColumns.task && (
                      <td>
                        <span
                          className={styles.editableCell}
                          contentEditable
                          suppressContentEditableWarning
                          onBlur={(e) => updateTaskField(phase.id, task.id, { name: e.target.textContent })}
                        >
                          {task.name}
                        </span>
                      </td>
                    )}

                    {visibleColumns.assignee && (
                      <td>
                        <span
                          className={styles.editableCell}
                          contentEditable
                          suppressContentEditableWarning
                          onBlur={(e) => updateTaskField(phase.id, task.id, { assignee: e.target.textContent })}
                        >
                          {task.assignee}
                        </span>
                      </td>
                    )}

                    {visibleColumns.priority && (
                      <td>
                        {task.priority ? (
                          <span className={`${styles.priorityBadge} ${styles[task.priority]}`}>
                            {task.priority}
                            <button
                              className={styles.badgeRemove}
                              onClick={() => updateTaskField(phase.id, task.id, { priority: '' })}
                            >
                              ×
                            </button>
                          </span>
                        ) : (
                          <button
                            className={styles.addPriorityBtn}
                            onClick={() => {
                              const priority = window.prompt('Enter priority (high/medium/low):');
                              if (priority) updateTaskField(phase.id, task.id, { priority: priority.toLowerCase() });
                            }}
                          >
                            + Add Priority
                          </button>
                        )}
                      </td>
                    )}

                    {visibleColumns.status && (
                      <td>
                        <select
                          className={styles.statusSelect}
                          value={task.status}
                          onChange={(e) => updateTaskField(phase.id, task.id, { status: e.target.value })}
                        >
                          <option value="todo">To Do</option>
                          <option value="in-progress">In Progress</option>
                          <option value="done">Done</option>
                          <option value="blocked">Blocked</option>
                        </select>
                      </td>
                    )}

                    {visibleColumns.dueDate && (
                      <td>
                        <input
                          type="date"
                          className={styles.dateInput}
                          value={task.due_date || ''}
                          onChange={(e) => updateTaskField(phase.id, task.id, { due_date: e.target.value })}
                        />
                      </td>
                    )}

                    {visibleColumns.notes && (
                      <td>
                        <input
                          type="text"
                          className={styles.notesInput}
                          value={task.notes || ''}
                          onChange={(e) => updateTaskField(phase.id, task.id, { notes: e.target.value })}
                          placeholder="Add notes..."
                        />
                      </td>
                    )}

                    {visibleColumns.actions && (
                      <td>
                        <button
                          className={styles.iconBtn}
                          onClick={() => deleteTask(phase.id, task.id)}
                          title="Delete Task"
                        >
                          <FontAwesomeIcon icon={faTrash} />
                        </button>
                      </td>
                    )}
                  </tr>
                ))}
              </React.Fragment>
            ))}
          </tbody>
        </table>

        <button className={styles.addPhaseBtn} onClick={addPhase}>
          <FontAwesomeIcon icon={faPlus} /> Add Phase
        </button>
      </div>
    );
  };

  // ==================== RENDER: BOARD VIEW ====================
  const renderBoard = () => {
    if (!plan?.wbs?.items) return null;

    const allTasks = plan.wbs.items.flatMap(phase =>
      phase.children.map(task => ({ ...task, phaseId: phase.id }))
    );

    const columns = {
      todo: allTasks.filter(t => t.status === 'todo'),
      'in-progress': allTasks.filter(t => t.status === 'in-progress'),
      done: allTasks.filter(t => t.status === 'done'),
      blocked: allTasks.filter(t => t.status === 'blocked')
    };

    const columnTitles = {
      todo: 'To Do',
      'in-progress': 'In Progress',
      done: 'Done',
      blocked: 'Blocked'
    };

    return (
      <div className={styles.boardView}>
        {Object.keys(columns).map(status => (
          <div
            key={status}
            className={styles.boardColumn}
            onDragOver={handleTaskDragOver}
            onDrop={(e) => handleBoardColumnDrop(e, status)}
          >
            <div className={styles.boardColumnHeader}>
              <div className={styles.boardColumnTitle}>{columnTitles[status]}</div>
              <div className={styles.boardColumnCount}>{columns[status].length}</div>
            </div>
            <div className={styles.boardColumnContent}>
              {columns[status].map(task => (
                <div
                  key={task.id}
                  className={styles.boardCard}
                  draggable
                  onDragStart={(e) => handleBoardCardDragStart(e, task)}
                >
                  <div className={styles.boardCardTitle}>{task.name}</div>
                  <div className={styles.boardCardMeta}>
                    <span className={styles.boardCardAssignee}>{task.assignee}</span>
                    {task.priority && (
                      <span className={`${styles.priorityBadge} ${styles[task.priority]}`}>
                        {task.priority}
                      </span>
                    )}
                  </div>
                  {task.due_date && (
                    <div className={styles.boardCardDue}>{fmtDate(task.due_date)}</div>
                  )}
                </div>
              ))}
            </div>
          </div>
        ))}
      </div>
    );
  };

  // ==================== RENDER: GANTT VIEW ====================
  const renderGantt = () => {
    if (!plan?.wbs?.items) return null;

    const allTasks = plan.wbs.items.flatMap(phase =>
      phase.children.filter(t => t.due_date).map(task => ({
        ...task,
        phaseName: phase.name
      }))
    );

    if (allTasks.length === 0) {
      return <div className={styles.emptyState}>No tasks with due dates to display in Gantt view.</div>;
    }

    // Calculate date range
    const dates = allTasks.map(t => new Date(t.due_date));
    const minDate = new Date(Math.min(...dates));
    const maxDate = new Date(Math.max(...dates));
    const daysDiff = Math.ceil((maxDate - minDate) / (1000 * 60 * 60 * 24)) + 7;
    const weeks = Math.ceil(daysDiff / 7);

    const weekLabels = [];
    for (let i = 0; i < weeks; i++) {
      const weekStart = new Date(minDate);
      weekStart.setDate(minDate.getDate() + i * 7);
      weekLabels.push(weekStart);
    }

    return (
      <div className={styles.ganttView}>
        <div className={styles.ganttControls}>
          <button className={styles.ganttBtn} onClick={zoomGanttOut} title="Zoom Out">
            <FontAwesomeIcon icon={faSearchMinus} /> Zoom Out
          </button>
          <button className={styles.ganttBtn} onClick={zoomGanttIn} title="Zoom In">
            <FontAwesomeIcon icon={faSearchPlus} /> Zoom In
          </button>
          <button className={styles.ganttBtn} onClick={addMilestone} title="Add Milestone">
            <FontAwesomeIcon icon={faCalendarPlus} /> Add Milestone
          </button>
        </div>

        <div className={styles.ganttChart} style={{ transform: `scaleX(${ganttZoom})`, transformOrigin: 'left' }}>
          <div className={styles.ganttHeader}>
            <div className={styles.ganttTaskColumn}>Task</div>
            <div className={styles.ganttTimelineColumn}>
              {weekLabels.map((date, idx) => (
                <div key={idx} className={styles.ganttWeek}>
                  Week {idx + 1}<br />
                  {fmtDate(date.toISOString())}
                </div>
              ))}
            </div>
          </div>

          <div className={styles.ganttBody}>
            {allTasks.map(task => {
              const taskDate = new Date(task.due_date);
              const daysFromStart = Math.ceil((taskDate - minDate) / (1000 * 60 * 60 * 24));
              const leftPercent = (daysFromStart / daysDiff) * 100;
              const widthPercent = ((task.lead_time_days || 1) / daysDiff) * 100;

              return (
                <div key={task.id} className={styles.ganttRow}>
                  <div className={styles.ganttTaskColumn}>
                    <div className={styles.ganttTaskName}>{task.name}</div>
                    <div className={styles.ganttTaskMeta}>{task.phaseName}</div>
                  </div>
                  <div className={styles.ganttTimelineColumn}>
                    <div
                      className={styles.ganttBar}
                      style={{
                        left: `${leftPercent}%`,
                        width: `${Math.max(widthPercent, 2)}%`
                      }}
                      title={`${task.name} - ${fmtDate(task.due_date)}`}
                    >
                      <span className={styles.ganttBarLabel}>{task.lead_time_days || 1}d</span>
                    </div>
                  </div>
                </div>
              );
            })}
          </div>
        </div>
      </div>
    );
  };

  // ==================== RENDER: TIMELINE ====================
  const renderTimeline = () => {
    if (!plan?.timeline?.phases) return null;

    return (
      <div className={styles.timelineView}>
        <div className={styles.timelineHeader}>
          <h2>Project Timeline</h2>
          <div className={styles.timelineSortBtns}>
            <button className={styles.sortBtn}>A-Z</button>
            <button className={styles.sortBtn}>Z-A</button>
          </div>
        </div>

        <div className={styles.timelineList}>
          {plan.timeline.phases.map(phase => (
            <div key={phase.id} className={styles.timelineCard}>
              <div className={styles.timelineCardHeader}>
                <div className={styles.timelineCardTitle}>{phase.name}</div>
                <div className={styles.timelineCardProgress}>{phase.progress}%</div>
              </div>
              <div className={styles.timelineCardDates}>
                {fmtFullDate(phase.start_date)} - {fmtFullDate(phase.end_date)}
              </div>
              <div className={styles.progressBar}>
                <div className={styles.progressFill} style={{ width: `${phase.progress}%` }} />
              </div>
              <div className={styles.timelineCardDescription}>{phase.description}</div>
            </div>
          ))}
        </div>
      </div>
    );
  };

  // ==================== RENDER: PROGRESS ====================
  const renderProgress = () => {
    if (!plan) return null;

    const totalTasks = plan.wbs.items.reduce((sum, phase) => sum + phase.children.length, 0);
    const completedTasks = plan.wbs.items.reduce(
      (sum, phase) => sum + phase.children.filter(t => t.status === 'done').length,
      0
    );
    const overallProgress = totalTasks > 0 ? Math.round((completedTasks / totalTasks) * 100) : 0;

    return (
      <div className={styles.progressView}>
        <div className={styles.progressCards}>
          <div className={styles.progressCard}>
            <div className={styles.progressCardLabel}>Overall Progress</div>
            <div className={styles.progressCardValue}>{overallProgress}%</div>
            <div className={styles.progressBar}>
              <div className={styles.progressFill} style={{ width: `${overallProgress}%` }} />
            </div>
          </div>

          <div className={styles.progressCard}>
            <div className={styles.progressCardLabel}>Completed Tasks</div>
            <div className={styles.progressCardValue}>{completedTasks} / {totalTasks}</div>
          </div>
        </div>

        <div className={styles.phaseProgressTable}>
          <h3>Phase Progress</h3>
          <table className={styles.denseTable}>
            <thead>
              <tr>
                <th>Phase</th>
                <th>Tasks</th>
                <th>Completed</th>
                <th>Progress</th>
              </tr>
            </thead>
            <tbody>
              {plan.wbs.items.map(phase => {
                const total = phase.children.length;
                const completed = phase.children.filter(t => t.status === 'done').length;
                const progress = total > 0 ? Math.round((completed / total) * 100) : 0;

                return (
                  <tr key={phase.id}>
                    <td>{phase.name}</td>
                    <td>{total}</td>
                    <td>{completed}</td>
                    <td>
                      <div className={styles.progressBar}>
                        <div className={styles.progressFill} style={{ width: `${progress}%` }} />
                      </div>
                      <span className={styles.progressPercent}>{progress}%</span>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </div>
    );
  };

  // ==================== RENDER: BUDGET ====================
  const renderBudget = () => {
    if (!plan?.resources?.budget) return null;

    const budget = plan.resources.budget;
    const totalAllocated = (budget.items || []).reduce((sum, item) => sum + item.amount, 0);
    const remaining = budget.total - budget.spent;
    const utilizationPercent = budget.total > 0 ? Math.round((budget.spent / budget.total) * 100) : 0;

    return (
      <div className={styles.budgetView}>
        <div className={styles.budgetCards}>
          <div className={styles.budgetCard}>
            <div className={styles.budgetCardLabel}>Total Budget</div>
            <div className={styles.budgetCardValue}>${budget.total.toLocaleString()}</div>
          </div>
          <div className={styles.budgetCard}>
            <div className={styles.budgetCardLabel}>Spent</div>
            <div className={styles.budgetCardValue}>${budget.spent.toLocaleString()}</div>
          </div>
          <div className={styles.budgetCard}>
            <div className={styles.budgetCardLabel}>Remaining</div>
            <div className={styles.budgetCardValue}>${remaining.toLocaleString()}</div>
          </div>
          <div className={styles.budgetCard}>
            <div className={styles.budgetCardLabel}>Utilization</div>
            <div className={styles.budgetCardValue}>{utilizationPercent}%</div>
          </div>
        </div>

        <div className={styles.budgetTable}>
          <div className={styles.tableHeader}>
            <h3>Budget Breakdown</h3>
            <button className={styles.addBtn} onClick={addBudgetItem}>
              <FontAwesomeIcon icon={faPlus} /> Add Item
            </button>
          </div>

          <table className={styles.denseTable}>
            <thead>
              <tr>
                <th>Category</th>
                <th>Description</th>
                <th>Amount</th>
                <th>Actions</th>
              </tr>
            </thead>
            <tbody>
              {(budget.items || []).map(item => (
                <tr key={item.id}>
                  <td>
                    <span
                      className={styles.editableCell}
                      contentEditable
                      suppressContentEditableWarning
                      onBlur={(e) => updateBudgetItem(item.id, { category: e.target.textContent })}
                    >
                      {item.category}
                    </span>
                  </td>
                  <td>
                    <span
                      className={styles.editableCell}
                      contentEditable
                      suppressContentEditableWarning
                      onBlur={(e) => updateBudgetItem(item.id, { description: e.target.textContent })}
                    >
                      {item.description}
                    </span>
                  </td>
                  <td>
                    <input
                      type="number"
                      className={styles.numberInput}
                      value={item.amount}
                      onChange={(e) => updateBudgetItem(item.id, { amount: parseFloat(e.target.value) || 0 })}
                    />
                  </td>
                  <td>
                    <button className={styles.iconBtn} onClick={() => deleteBudgetItem(item.id)}>
                      <FontAwesomeIcon icon={faTrash} />
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    );
  };

  // ==================== RENDER: OBJECTIVES ====================
  const renderObjectives = () => {
    if (!plan?.objectives) return null;

    return (
      <div className={styles.objectivesView}>
        <div className={styles.tableHeader}>
          <h2>Objectives & Key Results</h2>
          <button className={styles.addBtn} onClick={addObjective}>
            <FontAwesomeIcon icon={faPlus} /> Add Objective
          </button>
        </div>

        <div className={styles.objectivesList}>
          {plan.objectives.map(obj => (
            <div key={obj.id} className={styles.objectiveCard}>
              <div className={styles.objectiveHeader}>
                <span
                  className={styles.objectiveTitle}
                  contentEditable
                  suppressContentEditableWarning
                  onBlur={(e) => updateObjective(obj.id, { title: e.target.textContent })}
                >
                  {obj.title}
                </span>
                <div className={styles.objectiveProgress}>{obj.progress}%</div>
                <button className={styles.iconBtn} onClick={() => deleteObjective(obj.id)}>
                  <FontAwesomeIcon icon={faTrash} />
                </button>
              </div>
              <div
                className={styles.objectiveDescription}
                contentEditable
                suppressContentEditableWarning
                onBlur={(e) => updateObjective(obj.id, { description: e.target.textContent })}
              >
                {obj.description}
              </div>
              <div className={styles.progressBar}>
                <div className={styles.progressFill} style={{ width: `${obj.progress}%` }} />
              </div>
              <div className={styles.keyResults}>
                {obj.key_results?.map((kr, idx) => (
                  <div key={idx} className={styles.keyResult}>
                    <FontAwesomeIcon icon={faCheckCircle} className={styles.krIcon} />
                    <span>{kr.metric}: {kr.value}</span>
                  </div>
                ))}
              </div>
            </div>
          ))}
        </div>
      </div>
    );
  };

  // ==================== RENDER: STAKEHOLDERS (ACCORDION) ====================
  const [expandedStakeholderSections, setExpandedStakeholderSections] = useState({
    executive: true,
    core_team: true,
    external: true
  });

  const toggleStakeholderSection = (section) => {
    setExpandedStakeholderSections(prev => ({
      ...prev,
      [section]: !prev[section]
    }));
  };

  const renderStakeholders = () => {
    if (!plan?.stakeholders) return null;

    const grouped = {
      executive: plan.stakeholders.filter(s => s.role_type === 'executive'),
      core_team: plan.stakeholders.filter(s => s.role_type === 'core_team'),
      external: plan.stakeholders.filter(s => s.role_type === 'external')
    };

    const sectionTitles = {
      executive: 'Executive Sponsors',
      core_team: 'Core Team',
      external: 'External Stakeholders'
    };

    return (
      <div className={styles.stakeholdersView}>
        <h2>Stakeholders</h2>

        {Object.keys(grouped).map(section => (
          <div key={section} className={styles.accordionSection}>
            <div
              className={styles.accordionHeader}
              onClick={() => toggleStakeholderSection(section)}
            >
              <FontAwesomeIcon
                icon={expandedStakeholderSections[section] ? faChevronDown : faChevronRight}
                className={styles.accordionIcon}
              />
              <span className={styles.accordionTitle}>{sectionTitles[section]}</span>
              <span className={styles.accordionCount}>({grouped[section].length})</span>
              <button
                className={styles.addBtn}
                onClick={(e) => {
                  e.stopPropagation();
                  addStakeholder(section);
                }}
              >
                <FontAwesomeIcon icon={faPlus} />
              </button>
            </div>

            {expandedStakeholderSections[section] && (
              <div className={styles.accordionContent}>
                <table className={styles.denseTable}>
                  <thead>
                    <tr>
                      <th>Name</th>
                      <th>Role</th>
                      <th>Email</th>
                      <th>Influence</th>
                      <th>Actions</th>
                    </tr>
                  </thead>
                  <tbody>
                    {grouped[section].map(stakeholder => (
                      <tr key={stakeholder.id}>
                        <td>
                          <span
                            className={styles.editableCell}
                            contentEditable
                            suppressContentEditableWarning
                            onBlur={(e) => updateStakeholder(stakeholder.id, { name: e.target.textContent })}
                          >
                            {stakeholder.name}
                          </span>
                        </td>
                        <td>
                          <span
                            className={styles.editableCell}
                            contentEditable
                            suppressContentEditableWarning
                            onBlur={(e) => updateStakeholder(stakeholder.id, { role: e.target.textContent })}
                          >
                            {stakeholder.role}
                          </span>
                        </td>
                        <td>
                          <span
                            className={styles.editableCell}
                            contentEditable
                            suppressContentEditableWarning
                            onBlur={(e) => updateStakeholder(stakeholder.id, { email: e.target.textContent })}
                          >
                            {stakeholder.email}
                          </span>
                        </td>
                        <td>
                          <select
                            className={styles.influenceSelect}
                            value={stakeholder.influence}
                            onChange={(e) => updateStakeholder(stakeholder.id, { influence: parseInt(e.target.value) })}
                          >
                            <option value="1">Low</option>
                            <option value="2">Medium</option>
                            <option value="3">High</option>
                          </select>
                        </td>
                        <td>
                          <button className={styles.iconBtn} onClick={() => deleteStakeholder(stakeholder.id)}>
                            <FontAwesomeIcon icon={faTrash} />
                          </button>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </div>
        ))}
      </div>
    );
  };

  // ==================== RENDER: RISKS (INLINE EDITING) ====================
  const renderRisks = () => {
    if (!plan?.risks) return null;

    return (
      <div className={styles.risksView}>
        <div className={styles.tableHeader}>
          <h2>Risk Management</h2>
          <button className={styles.addBtn} onClick={addRisk}>
            <FontAwesomeIcon icon={faPlus} /> Add Risk
          </button>
        </div>

        <table className={styles.denseTable}>
          <thead>
            <tr>
              <th>Risk</th>
              <th>Category</th>
              <th>Likelihood</th>
              <th>Impact</th>
              <th>Severity</th>
              <th>Owner</th>
              <th>Status</th>
              <th>Actions</th>
            </tr>
          </thead>
          <tbody>
            {plan.risks.map(risk => {
              const severityMap = { Low: 1, Medium: 2, High: 3 };
              const severity = severityMap[risk.likelihood] * severityMap[risk.impact];
              const severityLabel = severity >= 6 ? 'High' : severity >= 3 ? 'Medium' : 'Low';

              return (
                <tr key={risk.id}>
                  <td>
                    <span
                      className={styles.editableCell}
                      contentEditable
                      suppressContentEditableWarning
                      onBlur={(e) => updateRisk(risk.id, { name: e.target.textContent })}
                    >
                      {risk.name}
                    </span>
                  </td>
                  <td>
                    <span
                      className={styles.editableCell}
                      contentEditable
                      suppressContentEditableWarning
                      onBlur={(e) => updateRisk(risk.id, { category: e.target.textContent })}
                    >
                      {risk.category}
                    </span>
                  </td>
                  <td>
                    <select
                      className={styles.riskSelect}
                      value={risk.likelihood}
                      onChange={(e) => updateRisk(risk.id, { likelihood: e.target.value })}
                    >
                      <option value="Low">Low</option>
                      <option value="Medium">Medium</option>
                      <option value="High">High</option>
                    </select>
                  </td>
                  <td>
                    <select
                      className={styles.riskSelect}
                      value={risk.impact}
                      onChange={(e) => updateRisk(risk.id, { impact: e.target.value })}
                    >
                      <option value="Low">Low</option>
                      <option value="Medium">Medium</option>
                      <option value="High">High</option>
                    </select>
                  </td>
                  <td>
                    <span className={`${styles.severityBadge} ${styles[severityLabel.toLowerCase()]}`}>
                      {severityLabel}
                    </span>
                  </td>
                  <td>
                    <span
                      className={styles.editableCell}
                      contentEditable
                      suppressContentEditableWarning
                      onBlur={(e) => updateRisk(risk.id, { owner: e.target.textContent })}
                    >
                      {risk.owner}
                    </span>
                  </td>
                  <td>
                    <select
                      className={styles.statusSelect}
                      value={risk.status}
                      onChange={(e) => updateRisk(risk.id, { status: e.target.value })}
                    >
                      <option value="Identified">Identified</option>
                      <option value="Mitigating">Mitigating</option>
                      <option value="Resolved">Resolved</option>
                    </select>
                  </td>
                  <td>
                    <button className={styles.iconBtn} onClick={() => deleteRisk(risk.id)}>
                      <FontAwesomeIcon icon={faTrash} />
                    </button>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>

        <div className={styles.mitigationSection}>
          <h3>Mitigation Strategies</h3>
          {plan.risks.map(risk => (
            <div key={risk.id} className={styles.mitigationCard}>
              <div className={styles.mitigationHeader}>{risk.name}</div>
              <textarea
                className={styles.mitigationTextarea}
                value={risk.mitigation || ''}
                onChange={(e) => updateRisk(risk.id, { mitigation: e.target.value })}
                placeholder="Enter mitigation strategy..."
              />
            </div>
          ))}
        </div>
      </div>
    );
  };

  // ==================== RENDER: DOCUMENTS ====================
  const renderDocuments = () => {
    if (!plan?.documents) return null;

    const grouped = {};
    plan.documents.forEach(doc => {
      if (!grouped[doc.category]) grouped[doc.category] = [];
      grouped[doc.category].push(doc);
    });

    return (
      <div className={styles.documentsView}>
        <div className={styles.tableHeader}>
          <h2>Documents</h2>
          <button className={styles.addBtn} onClick={addDocument}>
            <FontAwesomeIcon icon={faPlus} /> Add Document
          </button>
        </div>

        {Object.keys(grouped).map(category => (
          <div key={category} className={styles.documentCategory}>
            <h3>{category}</h3>
            <table className={styles.denseTable}>
              <thead>
                <tr>
                  <th>Filename</th>
                  <th>Size</th>
                  <th>Owner</th>
                  <th>Uploaded</th>
                  <th>Actions</th>
                </tr>
              </thead>
              <tbody>
                {grouped[category].map(doc => (
                  <tr key={doc.id}>
                    <td>
                      <FontAwesomeIcon icon={faFileLines} className={styles.fileIcon} />
                      {doc.filename}
                    </td>
                    <td>{doc.size}</td>
                    <td>{doc.owner}</td>
                    <td>{fmtFullDate(doc.uploaded_at)}</td>
                    <td>
                      <button className={styles.iconBtn} onClick={() => deleteDocument(doc.id)}>
                        <FontAwesomeIcon icon={faTrash} />
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ))}
      </div>
    );
  };

  // ==================== SETTINGS RENDER ====================
  const renderSettings = () => {
    return (
      <div className={styles.settingsView}>
        <div className={styles.pmBoardHeader}>
          <h2 className={styles.pmBoardTitle}>Project Settings</h2>
        </div>

        <div className={styles.settingsContent}>
          <div className={styles.settingsSection}>
            <h3 className={styles.settingsSectionTitle}>Project Information</h3>
            <div className={styles.formGroup}>
              <label className={styles.formLabel}>Project Name</label>
              <input
                type="text"
                className={styles.formInput}
                value={projectName}
                onChange={(e) => setProjectName(e.target.value)}
              />
            </div>
            <div className={styles.formGroup}>
              <label className={styles.formLabel}>Project Description</label>
              <textarea
                className={styles.formTextarea}
                placeholder="Enter project description..."
                rows={4}
              />
            </div>
            <div className={styles.formGroup}>
              <label className={styles.formLabel}>Start Date</label>
              <input
                type="date"
                className={styles.formInput}
              />
            </div>
            <div className={styles.formGroup}>
              <label className={styles.formLabel}>End Date</label>
              <input
                type="date"
                className={styles.formInput}
              />
            </div>
          </div>

          <div className={styles.settingsSection}>
            <h3 className={styles.settingsSectionTitle}>Team Settings</h3>
            <div className={styles.formGroup}>
              <label className={styles.formLabel}>Default Assignee</label>
              <select className={styles.formSelect}>
                <option value="">Unassigned</option>
                <option value="user1">Sarah Johnson</option>
                <option value="user2">David Chen</option>
                <option value="user3">Michael Torres</option>
              </select>
            </div>
            <div className={styles.formGroup}>
              <label className={styles.formLabel}>Project Owner</label>
              <select className={styles.formSelect}>
                <option value="user1">Sarah Johnson</option>
                <option value="user2">David Chen</option>
              </select>
            </div>
          </div>

          <div className={styles.settingsSection}>
            <h3 className={styles.settingsSectionTitle}>Notifications</h3>
            <div className={styles.settingsCheckbox}>
              <input type="checkbox" id="notify-tasks" defaultChecked />
              <label htmlFor="notify-tasks">Notify me when tasks are assigned to me</label>
            </div>
            <div className={styles.settingsCheckbox}>
              <input type="checkbox" id="notify-deadlines" defaultChecked />
              <label htmlFor="notify-deadlines">Send deadline reminders</label>
            </div>
            <div className={styles.settingsCheckbox}>
              <input type="checkbox" id="notify-updates" />
              <label htmlFor="notify-updates">Notify me of project updates</label>
            </div>
          </div>

          <div className={styles.settingsSection}>
            <h3 className={styles.settingsSectionTitle}>Display Preferences</h3>
            <div className={styles.formGroup}>
              <label className={styles.formLabel}>Default View</label>
              <select className={styles.formSelect} value={currentView} onChange={(e) => setCurrentView(e.target.value)}>
                <option value="list">List View</option>
                <option value="board">Board View</option>
                <option value="gantt">Gantt View</option>
              </select>
            </div>
            <div className={styles.formGroup}>
              <label className={styles.formLabel}>Date Format</label>
              <select className={styles.formSelect}>
                <option value="mdy">MM/DD/YYYY</option>
                <option value="dmy">DD/MM/YYYY</option>
                <option value="ymd">YYYY-MM-DD</option>
              </select>
            </div>
          </div>

          <div className={styles.settingsActions}>
            <button className={`${styles.pmBtn} ${styles.pmBtnPrimary}`}>
              <FontAwesomeIcon icon={faCheckCircle} /> Save Settings
            </button>
            <button className={`${styles.pmBtn} ${styles.pmBtnSecondary}`} onClick={() => setActiveNav('tasks')}>
              Cancel
            </button>
          </div>
        </div>
      </div>
    );
  };

  // ==================== MAIN RENDER ====================
  if (loading) {
    return (
      <div className={styles.pmContainer}>
        <div className={styles.loadingState}>Loading project plan...</div>
      </div>
    );
  }

  if (!plan) {
    return (
      <div className={styles.pmContainer}>
        <div className={styles.emptyState}>No plan data available.</div>
      </div>
    );
  }

  return (
    <>
      <ToastContainer toasts={toasts} onDismiss={dismissToast} />
      <div className={styles.pmContainer}>
        {/* Backdrop */}
      {(pmMenuOpen || aiHelperOpen) && (
        <div className={styles.backdrop} onClick={() => { setPmMenuOpen(false); setAiHelperOpen(false); }} />
      )}

      {/* PM Menu Sidebar */}
      <div className={`${styles.pmSidebar} ${pmMenuOpen ? styles.open : ''}`}>
        <div className={styles.pmSidebarHeader}>
          <button className={styles.closeBtn} onClick={() => setPmMenuOpen(false)}>
            <FontAwesomeIcon icon={faTimes} />
          </button>
          <div className={styles.projectName}>{projectName}</div>
          <div className={styles.projectMeta}>{projectDate}</div>
        </div>

        <div className={styles.pmNavButtons}>
          <button className={styles.navBackBtn} onClick={() => navigate('/ops/pm')}>
            <FontAwesomeIcon icon={faChartLine} />
            PM Dashboard
          </button>
          <button className={styles.navBackBtn} onClick={() => navigate('/market-iq')}>
            <FontAwesomeIcon icon={faHome} />
            Back to Market IQ
          </button>
        </div>

        <div className={styles.pmNav}>
          <div className={styles.pmNavSection}>
            <div className={styles.pmNavTitle}>Navigation</div>
            <div className={`${styles.pmNavItem} ${activeNav === 'tasks' ? styles.active : ''}`} onClick={() => setActiveNav('tasks')}>
              <div className={styles.pmNavIcon}><FontAwesomeIcon icon={faListCheck} /></div>
              <div>Tasks</div>
            </div>
            <div className={`${styles.pmNavItem} ${activeNav === 'timeline' ? styles.active : ''}`} onClick={() => setActiveNav('timeline')}>
              <div className={styles.pmNavIcon}><FontAwesomeIcon icon={faChartGantt} /></div>
              <div>Timeline</div>
            </div>
            <div className={`${styles.pmNavItem} ${activeNav === 'progress' ? styles.active : ''}`} onClick={() => setActiveNav('progress')}>
              <div className={styles.pmNavIcon}><FontAwesomeIcon icon={faChartLine} /></div>
              <div>Progress</div>
            </div>
            <div className={`${styles.pmNavItem} ${activeNav === 'budget' ? styles.active : ''}`} onClick={() => setActiveNav('budget')}>
              <div className={styles.pmNavIcon}><FontAwesomeIcon icon={faDollarSign} /></div>
              <div>Budget</div>
            </div>
            <div className={`${styles.pmNavItem} ${activeNav === 'objectives' ? styles.active : ''}`} onClick={() => setActiveNav('objectives')}>
              <div className={styles.pmNavIcon}><FontAwesomeIcon icon={faBullseye} /></div>
              <div>Objectives</div>
            </div>
            <div className={`${styles.pmNavItem} ${activeNav === 'stakeholders' ? styles.active : ''}`} onClick={() => setActiveNav('stakeholders')}>
              <div className={styles.pmNavIcon}><FontAwesomeIcon icon={faUsers} /></div>
              <div>Stakeholders</div>
            </div>
            <div className={`${styles.pmNavItem} ${activeNav === 'risks' ? styles.active : ''}`} onClick={() => setActiveNav('risks')}>
              <div className={styles.pmNavIcon}><FontAwesomeIcon icon={faTriangleExclamation} /></div>
              <div>Risks</div>
            </div>
            <div className={`${styles.pmNavItem} ${activeNav === 'documents' ? styles.active : ''}`} onClick={() => setActiveNav('documents')}>
              <div className={styles.pmNavIcon}><FontAwesomeIcon icon={faFileLines} /></div>
              <div>Documents</div>
            </div>
          </div>

          <div className={styles.pmNavSection}>
            <div className={styles.pmNavTitle}>Templates</div>
            <div className={styles.pmNavItem} onClick={() => setShowTemplateModal(true)}>
              <div className={styles.pmNavIcon}><FontAwesomeIcon icon={faFolder} /></div>
              <div>Load Template</div>
            </div>
            <div className={styles.pmNavItem} onClick={() => setShowSaveTemplateModal(true)}>
              <div className={styles.pmNavIcon}><FontAwesomeIcon icon={faBookmark} /></div>
              <div>Save as Template</div>
            </div>
          </div>

          <div className={styles.pmNavSection}>
            <div className={styles.pmNavTitle}>Settings</div>
            <div className={styles.pmNavItem} onClick={() => setActiveNav('settings')}>
              <div className={styles.pmNavIcon}><FontAwesomeIcon icon={faCog} /></div>
              <div>Project Settings</div>
            </div>
          </div>
        </div>
      </div>

      {/* AI Assistant Sidebar */}
      <div className={`${styles.pmAiHelper} ${aiHelperOpen ? styles.sidebarOpen : ''}`}>
        <div className={styles.pmAiHeader}>
          <div className={styles.pmAiTitle}>
            <FontAwesomeIcon icon={faWandMagicSparkles} />
            AI Assistant
          </div>
          <button className={styles.closeBtn} onClick={() => setAiHelperOpen(false)}>
            <FontAwesomeIcon icon={faTimes} />
          </button>
        </div>

        <div className={styles.pmAiMessages}>
          {aiMessages.map((msg, idx) => (
            <div key={idx} className={`${styles.pmAiMessage} ${msg.role}`}>
              <div className={styles.pmAiBubble}>{msg.content}</div>
            </div>
          ))}
          {aiProcessing && (
            <div className={`${styles.pmAiMessage} assistant`}>
              <div className={styles.pmAiBubble}>Thinking...</div>
            </div>
          )}
        </div>

        <div className={styles.pmAiInput}>
          <div className={styles.pmAiInputWrapper}>
            <textarea
              className={styles.pmAiTextarea}
              placeholder="Ask me to update the project..."
              value={aiInput}
              onChange={(e) => setAiInput(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === 'Enter' && !e.shiftKey) {
                  e.preventDefault();
                  sendAIMessage();
                }
              }}
              rows={2}
            />
            <div className={styles.pmAiActions}>
              <button
                className={`${styles.pmAiMicBtn} ${isRecording ? styles.recording : ''}`}
                onClick={isRecording ? stopVoiceRecording : startVoiceRecording}
                title={isRecording ? 'Stop Recording' : 'Voice Input'}
              >
                <FontAwesomeIcon icon={faMicrophone} />
              </button>
              <button
                className={styles.pmAiSend}
                onClick={sendAIMessage}
                disabled={aiProcessing || !aiInput.trim()}
              >
                <FontAwesomeIcon icon={faPaperPlane} />
              </button>
            </div>
          </div>
        </div>
      </div>

      {/* Sidebar Tabs */}
      <div className={`${styles.sidebarTab} ${styles.tabPmMenu}`} onClick={togglePmMenu}>
        <FontAwesomeIcon icon={faListCheck} />
        <div className={styles.tabLabel}>PM Menu</div>
      </div>

      <div className={`${styles.sidebarTab} ${styles.tabAiAssistant}`} onClick={toggleAI}>
        <FontAwesomeIcon icon={faWandMagicSparkles} />
        <div className={styles.tabLabel}>AI Assistant</div>
      </div>

      {/* Main Content */}
      <div className={`${styles.pmMain} ${pmMenuOpen || aiHelperOpen ? styles.sidebarOpen : ''}`}>
        {/* Top Bar */}
        <div className={styles.pmTopbar}>
          <div className={styles.pmTopbarLeft}>
            <button className={styles.backButton} onClick={() => navigate('/market-iq')}>
              <FontAwesomeIcon icon={faArrowLeft} />
              Back
            </button>
          </div>

          <div className={styles.pmTopbarActions}>
            {autoSaving ? (
              <div className={styles.autoSaveIndicator} style={{ background: '#fef3c7', color: '#92400e' }}>
                <FontAwesomeIcon icon={faClock} />
                Saving...
              </div>
            ) : lastSaved ? (
              <div className={styles.autoSaveIndicator}>
                <FontAwesomeIcon icon={faCheckCircle} />
                All changes saved
              </div>
            ) : null}

            <button className={`${styles.pmBtn} ${styles.pmBtnSecondary}`} onClick={() => setShowTemplateModal(true)}>
              <FontAwesomeIcon icon={faFolder} /> Templates
            </button>

            <button className={`${styles.pmBtn} ${styles.pmBtnSecondary}`} onClick={() => setShowSaveTemplateModal(true)}>
              <FontAwesomeIcon icon={faBookmark} /> Save as Template
            </button>

<button
  className={`${styles.pmBtn} ${styles.pmBtnPrimary}`}
  onClick={openValidationModal}
  disabled={validating}
>
  <FontAwesomeIcon icon={faCheckCircle} /> Validate Plan
</button>

            <a className={styles.cancelLink} onClick={cancelPlan}>Cancel</a>
          </div>
        </div>

        {/* Content Area */}
        <div className={styles.pmContentWrapper}>
          <div className={styles.pmBoard}>
            {/* Tasks Tab */}
            {activeNav === 'tasks' && (
              <>
                <div className={styles.pmBoardHeader}>
                  <h2 className={styles.pmBoardTitle}>Project Tasks</h2>
                  <div className={styles.pmBoardHeaderRight}>
                    <div className={styles.pmViewToggle}>
                      <button className={`${styles.pmViewBtn} ${currentView === 'list' ? styles.active : ''}`} onClick={() => setCurrentView('list')}>
                        <FontAwesomeIcon icon={faList} /> List
                      </button>
                      <button className={`${styles.pmViewBtn} ${currentView === 'board' ? styles.active : ''}`} onClick={() => setCurrentView('board')}>
                        <FontAwesomeIcon icon={faTableColumns} /> Board
                      </button>
                      <button className={`${styles.pmViewBtn} ${currentView === 'gantt' ? styles.active : ''}`} onClick={() => setCurrentView('gantt')}>
                        <FontAwesomeIcon icon={faChartGantt} /> Gantt
                      </button>
                    </div>
                  </div>
                </div>

                {currentView === 'list' && renderDenseList()}
                {currentView === 'board' && renderBoard()}
                {currentView === 'gantt' && renderGantt()}
              </>
            )}

            {/* Other Tabs */}
            {activeNav === 'timeline' && renderTimeline()}
            {activeNav === 'progress' && renderProgress()}
            {activeNav === 'budget' && renderBudget()}
            {activeNav === 'objectives' && renderObjectives()}
            {activeNav === 'stakeholders' && renderStakeholders()}
            {activeNav === 'risks' && renderRisks()}
            {activeNav === 'documents' && renderDocuments()}
            {activeNav === 'settings' && renderSettings()}
          </div>
        </div>
      </div>

      {/* Template Library Modal */}
      {showTemplateModal && (
        <div className={styles.modalOverlay} onClick={() => setShowTemplateModal(false)}>
          <div className={styles.modal} onClick={(e) => e.stopPropagation()}>
            <div className={styles.modalHeader}>
              <div className={styles.modalTitle}>Template Library</div>
              <button className={styles.closeBtn} onClick={() => setShowTemplateModal(false)}>
                <FontAwesomeIcon icon={faTimes} />
              </button>
            </div>
            <div className={styles.modalBody}>
              {templates.length === 0 ? (
                <div className={styles.emptyState}>No templates available yet.</div>
              ) : (
                templates.map((tpl, idx) => (
                  <div className={styles.templateCard} key={idx}>
                    <div className={styles.templateInfo}>
                      <div className={styles.templateName}>{tpl.name}</div>
                      <div className={styles.templateDescription}>{tpl.description || 'No description'}</div>
                      <div className={styles.templateMeta}>
                        {tpl.phases?.length || 0} phases • {tpl.created_at && fmtFullDate(tpl.created_at)}
                      </div>
                    </div>
                    <button className={`${styles.pmBtn} ${styles.pmBtnPrimary}`} onClick={() => applyTemplate(tpl.id)}>
                      Apply
                    </button>
                  </div>
                ))
              )}
            </div>
            <div className={styles.modalFooter}>
              <button className={`${styles.pmBtn} ${styles.pmBtnSecondary}`} onClick={() => setShowTemplateModal(false)}>
                Close
              </button>
            </div>
          </div>
        </div>
      )}
{/* ===== Validation Modal ===== */}
{showValidationModal && (
  <div className={styles.modalOverlay} onClick={closeValidationModal}>
    <div className={styles.modal} onClick={(e) => e.stopPropagation()}>
      <div className={styles.modalHeader}>
        <div className={styles.modalTitle}>Review Plan Type</div>
        <button className={styles.closeBtn} onClick={closeValidationModal}>
          <FontAwesomeIcon icon={faTimes} />
        </button>
      </div>

      <div className={styles.modalBody}>
        <div style={{ marginBottom: 12 }}>
          <div style={{ fontWeight: 600, marginBottom: 6 }}>Detected style</div>
          <div>
            <span style={{
              display: 'inline-block',
              padding: '6px 10px',
              borderRadius: 8,
              border: '1px solid #e5e7eb',
              background: '#f8fafc',
              marginRight: 8,
              textTransform: 'capitalize'
            }}>
              {deriveStyleFromPlan(plan)}
            </span>
            {styleSource && (
              <span style={{
                fontSize: 12,
                padding: '3px 8px',
                borderRadius: 999,
                border: '1px solid #cbd5e1',
                color: '#475569',
                background: '#fff'
              }}>
                source: {String(styleSource).toUpperCase()}
              </span>
            )}
          </div>
        </div>

        <div style={{ marginBottom: 12 }}>
          <div style={{ fontWeight: 600, marginBottom: 6 }}>Why this style?</div>
          <div style={{
            border: '1px solid #e5e7eb',
            borderRadius: 8,
            padding: '10px 12px',
            background: '#fff'
          }}>
            {styleReason || 'Heuristic default'}
          </div>
        </div>

        <div style={{ display: 'flex', gap: 12, marginBottom: 12 }}>
          <div style={{ flex: 1 }}>
            <label style={{ display: 'block', fontWeight: 600, marginBottom: 6 }}>
              Change plan type
            </label>
            <select
              className={styles.formSelect}
              value={styleChoice}
              onChange={(e) => setStyleChoice(e.target.value)}
            >
              <option value="agile">Agile</option>
              <option value="waterfall">Waterfall</option>
              <option value="hybrid">Hybrid</option>
            </select>
          </div>

          <div style={{ flex: 1 }}>
            <label style={{ display: 'block', fontWeight: 600, marginBottom: 6 }}>
              Estimated Duration
            </label>
            <input
              className={styles.formInput}
              value={
                (styleDuration != null && Number.isFinite(Number(styleDuration)))
                  ? `${styleDuration} months`
                  : '—'
              }
              readOnly
            />
          </div>
        </div>

        {(deriveStyleFromPlan(plan) !== styleChoice) && (
          <div style={{
            fontSize: 13,
            color: '#6b7280',
            marginBottom: 6
          }}>
            Changing the plan type will regenerate the WBS before validation.
          </div>
        )}
      </div>

      <div className={styles.modalFooter}>
        <button className={`${styles.pmBtn} ${styles.pmBtnSecondary}`} onClick={closeValidationModal}>
          Cancel
        </button>
        <button
          className={`${styles.pmBtn} ${styles.pmBtnPrimary}`}
          onClick={confirmValidation}
          disabled={regenBusy || validating}
        >
          {regenBusy ? 'Regenerating…' : (validating ? 'Validating…' : 'Continue & Validate')}
        </button>
      </div>
    </div>
  </div>
)}

      {/* Save Template Modal */}
      {showSaveTemplateModal && (
        <div className={styles.modalOverlay} onClick={() => setShowSaveTemplateModal(false)}>
          <div className={styles.modal} onClick={(e) => e.stopPropagation()}>
            <div className={styles.modalHeader}>
              <div className={styles.modalTitle}>Save as Template</div>
              <button className={styles.closeBtn} onClick={() => setShowSaveTemplateModal(false)}>
                <FontAwesomeIcon icon={faTimes} />
              </button>
            </div>
            <div className={styles.modalBody}>
              <div className={styles.formGroup}>
                <label className={styles.formLabel}>Template Name *</label>
                <input
                  type="text"
                  className={styles.formInput}
                  value={templateName}
                  onChange={(e) => setTemplateName(e.target.value)}
                  placeholder="e.g., Software Launch"
                />
              </div>
              <div className={styles.formGroup}>
                <label className={styles.formLabel}>Description</label>
                <textarea
                  className={styles.formTextarea}
                  value={templateDescription}
                  onChange={(e) => setTemplateDescription(e.target.value)}
                  placeholder="Describe this template..."
                />
              </div>
            </div>
            <div className={styles.modalFooter}>
              <button className={`${styles.pmBtn} ${styles.pmBtnSecondary}`} onClick={() => setShowSaveTemplateModal(false)}>
                Cancel
              </button>
              <button className={`${styles.pmBtn} ${styles.pmBtnPrimary}`} onClick={saveAsTemplate}>
                Save Template
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
    </>
  );
};

export default ProjectPlanning;
