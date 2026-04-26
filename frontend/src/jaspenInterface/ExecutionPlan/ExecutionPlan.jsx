import React, { useCallback, useEffect, useMemo, useState } from 'react';
import { useLocation, useNavigate } from 'react-router-dom';
import { FontAwesomeIcon } from '@fortawesome/react-fontawesome';
import { faPaperPlane, faSpinner, faTimes, faWandMagicSparkles } from '@fortawesome/free-solid-svg-icons';
import AppMenu from '../shared/AppMenu';
import JaspenAssistantTab from '../shared/JaspenAssistantTab';
import { Jaspen } from '../Workspace/JaspenClient';
import ExecutionPanel from '../Workspace/components/ExecutionPanel';
import { parseUIActions, ChatActionTypes } from '../../shared/hooks/useChatCommands';
import { useToast, ToastContainer } from '../../shared/components/Toast';
import { authFetch } from '../../shared/auth/http';
import './ExecutionPlan.css';

const GENERATE_PLAN_REGEX = /\b(generate|build|create|draft)\b.*\b(execution|plan|wbs|task)\b/i;

const getThreadIdFromSearch = (search = '') => {
  const params = new URLSearchParams(search);
  return String(params.get('sid') || params.get('session_id') || '').trim();
};

const promptSuggestions = [
  'Generate execution plan from current scorecard',
  'Set owners and due dates for all tasks',
  'Add dependencies between critical tasks',
  'Reprioritize tasks for fastest delivery',
];

const getAssistantStorageKey = (threadId) => `jaspen_execution_assistant_${String(threadId || '').trim()}`;

const buildContextInstructionPrefix = ({ bundle, scorecard, wbs }) => {
  const parts = [];
  const projectName = String(
    scorecard?.project_name ||
    scorecard?.projectName ||
    bundle?.thread?.title ||
    ''
  ).trim();
  if (projectName) parts.push(`Project: ${projectName}`);

  const score = Number(scorecard?.jaspen_score);
  if (Number.isFinite(score) && score > 0) parts.push(`Current scorecard score: ${Math.round(score)}`);

  const activeScenario = String(
    bundle?.active_snapshot?.label ||
    bundle?.active_scenario?.label ||
    ''
  ).trim();
  if (activeScenario) parts.push(`Active scenario: ${activeScenario}`);

  const wbsTasks = Array.isArray(wbs?.tasks) ? wbs.tasks.length : 0;
  if (wbsTasks > 0) parts.push(`Current execution plan tasks: ${wbsTasks}`);

  const historyLines = (Array.isArray(bundle?.messages) ? bundle.messages : [])
    .slice(-8)
    .map((msg) => {
      const role = String(msg?.role || msg?.sender || '').toLowerCase().includes('user') ? 'User' : 'Assistant';
      const text = String(msg?.content || msg?.text || msg?.message || '').replace(/\s+/g, ' ').trim();
      if (!text) return '';
      return `${role}: ${text}`;
    })
    .filter(Boolean);

  if (historyLines.length > 0) {
    parts.push(`Recent conversation:\n${historyLines.join('\n')}`);
  }

  if (parts.length === 0) return '';
  return `Use this thread context when responding and applying edits.\n${parts.join('\n')}`;
};

const buildInitialAssistantMessages = (bundle) => {
  const history = (Array.isArray(bundle?.messages) ? bundle.messages : [])
    .slice(-10)
    .map((msg) => {
      const role = String(msg?.role || msg?.sender || '').toLowerCase().includes('user') ? 'user' : 'assistant';
      const text = String(msg?.content || msg?.text || msg?.message || '').trim();
      if (!text) return null;
      return { role, text };
    })
    .filter(Boolean);

  if (history.length > 0) return history;
  return [
    {
      role: 'assistant',
      text: 'I can help you refine this execution plan. Ask me to add tasks, update owners, or rebuild the timeline.',
    },
  ];
};

export default function ExecutionPlan() {
  const location = useLocation();
  const navigate = useNavigate();
  const { toasts, showToast, dismissToast } = useToast();

  const [threadId, setThreadId] = useState(() => getThreadIdFromSearch(window.location.search));
  const [threadBundle, setThreadBundle] = useState(null);
  const [threadWbs, setThreadWbs] = useState(null);
  const [wbsLoading, setWbsLoading] = useState(false);
  const [loadingBundle, setLoadingBundle] = useState(false);
  const [assistantOpen, setAssistantOpen] = useState(false);
  const [assistantInput, setAssistantInput] = useState('');
  const [assistantMessages, setAssistantMessages] = useState([]);
  const [assistantBusy, setAssistantBusy] = useState(false);
  const [planBusy, setPlanBusy] = useState(false);

  useEffect(() => {
    const nextThreadId = getThreadIdFromSearch(location.search);
    setThreadId(nextThreadId);
  }, [location.search]);

  const scorecardContext = useMemo(() => {
    if (!threadBundle || typeof threadBundle !== 'object') return null;
    return threadBundle.current_scorecard || threadBundle.baseline_scorecard || null;
  }, [threadBundle]);
  const hasExistingPlan = useMemo(
    () => Array.isArray(threadWbs?.tasks) && threadWbs.tasks.length > 0,
    [threadWbs]
  );

  const loadThreadBundle = useCallback(async (targetThreadId) => {
    const tid = String(targetThreadId || '').trim();
    if (!tid) return null;
    setLoadingBundle(true);
    try {
      const payload = await Jaspen.getThreadBundle(tid, { msg_limit: 50, scn_limit: 50 });
      setThreadBundle(payload || null);
      return payload || null;
    } catch (error) {
      showToast(error?.message || 'Unable to load thread context.', 'error');
      setThreadBundle(null);
      return null;
    } finally {
      setLoadingBundle(false);
    }
  }, [showToast]);

  const refreshThreadWbs = useCallback(async (targetThreadId) => {
    const tid = String(targetThreadId || '').trim();
    if (!tid) {
      setThreadWbs(null);
      return null;
    }
    setWbsLoading(true);
    try {
      const response = await Jaspen.getThreadWbs(tid);
      const projectWbs = response?.project_wbs && typeof response.project_wbs === 'object'
        ? response.project_wbs
        : null;
      setThreadWbs(projectWbs);
      return projectWbs;
    } catch (error) {
      showToast(error?.message || 'Unable to load execution plan.', 'error');
      setThreadWbs(null);
      return null;
    } finally {
      setWbsLoading(false);
    }
  }, [showToast]);

  useEffect(() => {
    if (!threadId) {
      setThreadBundle(null);
      setThreadWbs(null);
      setAssistantMessages([]);
      return;
    }
    const stored = (() => {
      try {
        const raw = localStorage.getItem(getAssistantStorageKey(threadId));
        const parsed = raw ? JSON.parse(raw) : null;
        if (!Array.isArray(parsed)) return null;
        const normalized = parsed
          .map((entry) => ({
            role: entry?.role === 'user' ? 'user' : 'assistant',
            text: String(entry?.text || '').trim(),
          }))
          .filter((entry) => entry.text);
        return normalized.length > 0 ? normalized : null;
      } catch {
        return null;
      }
    })();
    if (stored) {
      setAssistantMessages(stored);
    } else {
      setAssistantMessages([]);
    }
    void (async () => {
      const bundle = await loadThreadBundle(threadId);
      await refreshThreadWbs(threadId);
      if (!stored) {
        setAssistantMessages(buildInitialAssistantMessages(bundle));
      }
    })();
  }, [threadId, loadThreadBundle, refreshThreadWbs]);

  useEffect(() => {
    const tid = String(threadId || '').trim();
    if (!tid) return;
    try {
      localStorage.setItem(getAssistantStorageKey(tid), JSON.stringify(assistantMessages.slice(-80)));
    } catch {}
  }, [assistantMessages, threadId]);

  const resolveThreadWbsState = useCallback(async (targetThreadId) => {
    const response = await Jaspen.getThreadWbs(targetThreadId);
    const currentWbs = (response?.project_wbs && typeof response.project_wbs === 'object')
      ? response.project_wbs
      : { name: 'Execution Plan', tasks: [] };
    const tasks = Array.isArray(currentWbs.tasks) ? [...currentWbs.tasks] : [];
    return { currentWbs, tasks };
  }, []);

  const handleExecutionTaskUpdate = useCallback(async (taskId, patch = {}) => {
    const tid = String(threadId || '').trim();
    if (!tid) throw new Error('No active thread.');
    const { currentWbs, tasks } = await resolveThreadWbsState(tid);
    const idx = tasks.findIndex((task) => String(task?.id || '') === String(taskId || ''));
    if (idx < 0) throw new Error('Task not found.');
    tasks[idx] = { ...tasks[idx], ...(patch && typeof patch === 'object' ? patch : {}) };
    await Jaspen.upsertThreadWbs(tid, { ...currentWbs, tasks });
    await refreshThreadWbs(tid);
  }, [refreshThreadWbs, resolveThreadWbsState, threadId]);

  const handleExecutionTaskAdd = useCallback(async (payload = {}) => {
    const tid = String(threadId || '').trim();
    if (!tid) throw new Error('No active thread.');
    const { currentWbs, tasks } = await resolveThreadWbsState(tid);
    const title = String(payload?.title || '').trim();
    if (!title) throw new Error('Task title is required.');
    const task = {
      id: String(payload?.id || `task_${Date.now()}`),
      title,
      status: String(payload?.status || 'todo').toLowerCase(),
      owner: String(payload?.owner || ''),
      due_date: payload?.due_date || payload?.dueDate || null,
      phase: String(payload?.phase || payload?.phase_name || 'Execution'),
      description: String(payload?.description || ''),
      priority: String(payload?.priority || 'medium').toLowerCase(),
      estimated_days: Number(payload?.estimated_days || payload?.timeline_days || 1),
      timeline_days: Number(payload?.timeline_days || payload?.estimated_days || 1),
      depends_on: Array.isArray(payload?.depends_on) ? payload.depends_on : [],
    };
    tasks.push(task);
    await Jaspen.upsertThreadWbs(tid, { ...currentWbs, tasks });
    await refreshThreadWbs(tid);
  }, [refreshThreadWbs, resolveThreadWbsState, threadId]);

  const handleExecutionTaskRemove = useCallback(async (taskId) => {
    const tid = String(threadId || '').trim();
    if (!tid) throw new Error('No active thread.');
    const removeId = String(taskId || '').trim();
    if (!removeId) throw new Error('Task id is required.');
    const { currentWbs, tasks } = await resolveThreadWbsState(tid);
    const filtered = tasks.filter((task) => String(task?.id || '') !== removeId);
    if (filtered.length === tasks.length) throw new Error('Task not found.');
    const normalized = filtered.map((task) => ({
      ...task,
      depends_on: Array.isArray(task?.depends_on)
        ? task.depends_on.filter((depId) => String(depId || '') !== removeId)
        : [],
    }));
    await Jaspen.upsertThreadWbs(tid, { ...currentWbs, tasks: normalized });
    await refreshThreadWbs(tid);
  }, [refreshThreadWbs, resolveThreadWbsState, threadId]);

  const handleExecutionDependencyAdd = useCallback(async (taskId, dependsOnId) => {
    const tid = String(threadId || '').trim();
    if (!tid) throw new Error('No active thread.');
    const sourceTaskId = String(taskId || '').trim();
    const depId = String(dependsOnId || '').trim();
    if (!sourceTaskId || !depId || sourceTaskId === depId) return;
    const { currentWbs, tasks } = await resolveThreadWbsState(tid);
    const idx = tasks.findIndex((task) => String(task?.id || '') === sourceTaskId);
    if (idx < 0) throw new Error('Task not found.');
    const deps = Array.isArray(tasks[idx]?.depends_on) ? [...tasks[idx].depends_on] : [];
    if (!deps.includes(depId)) deps.push(depId);
    tasks[idx] = { ...tasks[idx], depends_on: deps };
    await Jaspen.upsertThreadWbs(tid, { ...currentWbs, tasks });
    await refreshThreadWbs(tid);
  }, [refreshThreadWbs, resolveThreadWbsState, threadId]);

  const applyUiAction = useCallback(async (action) => {
    if (!action || !action.type) return false;
    const payload = action.payload || {};
    switch (action.type) {
      case ChatActionTypes.WBS_ADD_TASK:
        await handleExecutionTaskAdd(payload);
        return true;
      case ChatActionTypes.WBS_UPDATE_TASK:
        await handleExecutionTaskUpdate(payload.id || payload.task_id, payload);
        return true;
      case ChatActionTypes.WBS_REMOVE_TASK:
        await handleExecutionTaskRemove(payload.id || payload.task_id);
        return true;
      case ChatActionTypes.WBS_ADD_DEPENDENCY:
        await handleExecutionDependencyAdd(payload.task_id || payload.taskId || payload.id, payload.depends_on || payload.dependsOn);
        return true;
      case ChatActionTypes.PROJECT_BEGIN:
        await Jaspen.generateAiWbs(threadId, { commit: true });
        await refreshThreadWbs(threadId);
        return true;
      default:
        return false;
    }
  }, [
    handleExecutionDependencyAdd,
    handleExecutionTaskAdd,
    handleExecutionTaskRemove,
    handleExecutionTaskUpdate,
    refreshThreadWbs,
    threadId,
  ]);

  const handleGeneratePlan = useCallback(async (
    instruction = 'Generate execution plan from current scorecard.',
    { confirmRegenerate = false } = {}
  ) => {
    const tid = String(threadId || '').trim();
    if (!tid || planBusy) return 'failed';
    if (confirmRegenerate && hasExistingPlan) {
      const ok = window.confirm(
        'Regenerate the execution plan?\n\nThis will replace your current plan and overwrite task edits.'
      );
      if (!ok) return 'cancelled';
    }
    setPlanBusy(true);
    try {
      const response = await Jaspen.generateAiWbs(tid, { commit: true, prompt: instruction });
      const count = Array.isArray(response?.project_wbs?.tasks) ? response.project_wbs.tasks.length : null;
      await refreshThreadWbs(tid);
      showToast(count != null ? `Execution plan generated (${count} tasks)` : 'Execution plan generated', 'success');
      return 'success';
    } catch (error) {
      showToast(error?.message || 'Could not generate execution plan.', 'error');
      return 'failed';
    } finally {
      setPlanBusy(false);
    }
  }, [hasExistingPlan, planBusy, refreshThreadWbs, showToast, threadId]);

  const sendAssistantMessage = useCallback(async () => {
    const text = String(assistantInput || '').trim();
    const tid = String(threadId || '').trim();
    if (!text || !tid || assistantBusy) return;

    setAssistantInput('');
    setAssistantBusy(true);
    setAssistantMessages((prev) => [...prev, { role: 'user', text }]);

    try {
      if (GENERATE_PLAN_REGEX.test(text)) {
        const generated = await handleGeneratePlan(text, { confirmRegenerate: hasExistingPlan });
        setAssistantMessages((prev) => [
          ...prev,
          {
            role: 'assistant',
            text: generated === 'success'
              ? 'Execution plan generated. I refreshed the board so you can keep editing.'
              : generated === 'cancelled'
              ? 'Plan regeneration canceled.'
              : 'I could not generate the plan right now.',
          },
        ]);
        return;
      }

      let bundle = threadBundle;
      if (!bundle) {
        bundle = await loadThreadBundle(tid);
      }
      const scorecard = bundle?.current_scorecard || bundle?.baseline_scorecard || scorecardContext || null;
      const contextPrefix = buildContextInstructionPrefix({
        bundle,
        scorecard,
        wbs: threadWbs,
      });

      const response = await Jaspen.scorecardAssistant(tid, {
        instruction: contextPrefix ? `${contextPrefix}\n\nUser request: ${text}` : text,
        scorecard,
        scorecard_id: scorecard?.analysis_id || scorecard?.id || null,
      });

      const uiActions = parseUIActions(response);
      let appliedCount = 0;
      for (const action of uiActions) {
        try {
          const applied = await applyUiAction(action);
          if (applied) appliedCount += 1;
        } catch (actionError) {
          console.error('[ExecutionPlan] action failed', actionError);
        }
      }
      if (appliedCount > 0) {
        await refreshThreadWbs(tid);
      }

      const reply = String(response?.reply || '').trim()
        || (appliedCount > 0
          ? `Applied ${appliedCount} execution update${appliedCount === 1 ? '' : 's'}.`
          : 'I reviewed the plan. Tell me what to change and I will apply it.');

      setAssistantMessages((prev) => [...prev, { role: 'assistant', text: reply }]);
    } catch (error) {
      const message = error?.message || 'I could not process that request right now.';
      setAssistantMessages((prev) => [...prev, { role: 'assistant', text: message }]);
    } finally {
      setAssistantBusy(false);
    }
  }, [
    assistantBusy,
    assistantInput,
    applyUiAction,
    hasExistingPlan,
    handleGeneratePlan,
    loadThreadBundle,
    refreshThreadWbs,
    scorecardContext,
    threadBundle,
    threadWbs,
    threadId,
  ]);

  const openAssistant = useCallback((prefill = 'Edit this execution plan: update phases, owners, due dates, dependencies, and priorities.') => {
    setAssistantOpen(true);
    setAssistantInput(prefill);
  }, []);

  const pageActions = (
    <div className="execution-plan-actions">
      <button
        type="button"
        className="int-btn int-btn-ghost"
        onClick={() => navigate(threadId ? `/new?sid=${encodeURIComponent(threadId)}` : '/new')}
      >
        Back to Jaspen
      </button>
      <button
        type="button"
        className="int-btn int-btn-primary"
        onClick={() => { void handleGeneratePlan('Generate execution plan from current scorecard.', { confirmRegenerate: true }); }}
        disabled={!threadId || planBusy}
        aria-disabled={!threadId || planBusy}
      >
        <FontAwesomeIcon icon={planBusy ? faSpinner : faWandMagicSparkles} spin={planBusy} />
        <span>{planBusy ? 'Building…' : (hasExistingPlan ? 'Regenerate Plan' : 'Build Plan')}</span>
      </button>
    </div>
  );

  return (
    <div className="execution-plan-page int-page">
      <AppMenu />
      <ToastContainer toasts={toasts} onDismiss={dismissToast} />

      <section className="execution-plan-main int-page-inner">
        <header className="int-page-head execution-plan-head">
          <div>
            <p className="int-eyebrow">Execution</p>
            <h1>Execution Plan</h1>
            <p>Track tasks, owners, and milestones from this project. Use the Jaspen assistant on the left to modify the plan with natural language.</p>
          </div>
          {pageActions}
        </header>

        {!threadId ? (
          <div className="int-card execution-plan-empty">
            <h2>No active project thread selected.</h2>
            <p>Open Execution Plan from a scored project so Jaspen can load the correct thread context.</p>
            <button type="button" className="int-btn int-btn-primary" onClick={() => navigate('/new')}>
              Go to Jaspen
            </button>
          </div>
        ) : (
          <ExecutionPanel
            threadId={threadId}
            wbs={threadWbs}
            authFetch={authFetch}
            onRefresh={() => Promise.all([refreshThreadWbs(threadId), loadThreadBundle(threadId)])}
            onUpdateTask={handleExecutionTaskUpdate}
            onAddTask={handleExecutionTaskAdd}
            onRemoveTask={handleExecutionTaskRemove}
            onAddDependency={handleExecutionDependencyAdd}
            canEditFields={true}
            canEditStructure={true}
            canEditDependencies={true}
            isViewer={false}
            isLocked={false}
            onOpenChat={() => openAssistant()}
            onOpenBilling={() => showToast('Billing controls are available in Account.', 'info')}
            loading={wbsLoading || loadingBundle}
          />
        )}
      </section>

      {!assistantOpen && (
        <JaspenAssistantTab
          onClick={() => openAssistant('Edit this execution plan using the current context.')}
          expanded={assistantOpen}
          controlsId="execution-plan-chat-drawer"
          top={258}
        />
      )}

      <aside
        id="execution-plan-chat-drawer"
        className={`execution-plan-chat-drawer ${assistantOpen ? 'is-open' : ''}`}
        aria-label="Jaspen execution assistant"
      >
        <div className="execution-plan-chat-head">
          <h3>Jaspen</h3>
          <button type="button" onClick={() => setAssistantOpen(false)} aria-label="Close assistant">
            <FontAwesomeIcon icon={faTimes} />
          </button>
        </div>

        <div className="execution-plan-chat-suggestions">
          {promptSuggestions.map((prompt) => (
            <button key={prompt} type="button" onClick={() => setAssistantInput(prompt)}>
              {prompt}
            </button>
          ))}
        </div>

        <div className="execution-plan-chat-messages">
          {assistantMessages.map((message, index) => (
            <div key={`${message.role}-${index}`} className={`execution-plan-chat-message ${message.role}`}>
              {message.text}
            </div>
          ))}
        </div>

        <div className="execution-plan-chat-input">
          <textarea
            value={assistantInput}
            onChange={(event) => setAssistantInput(event.target.value)}
            placeholder="Ask Jaspen to edit this execution plan..."
            rows={3}
          />
          <button
            type="button"
            onClick={() => { void sendAssistantMessage(); }}
            disabled={!assistantInput.trim() || assistantBusy || !threadId}
            aria-disabled={!assistantInput.trim() || assistantBusy || !threadId}
            aria-label="Send message"
          >
            <FontAwesomeIcon icon={assistantBusy ? faSpinner : faPaperPlane} spin={assistantBusy} />
          </button>
        </div>
      </aside>
    </div>
  );
}
