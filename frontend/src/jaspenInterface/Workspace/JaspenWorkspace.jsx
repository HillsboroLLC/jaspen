// ============================================================================
// File: frontend/src/Market/Jaspen/workspace/JaspenWorkspace.jsx
// Purpose: Keep original drawer behavior, FIX readiness "snap" issue,
//          and show tabs AFTER Finish & Analyze.
// ============================================================================

import React, { useEffect, useLayoutEffect, useRef, useState, useMemo, useReducer, useCallback } from 'react';
import { Link, useLocation, useNavigate } from 'react-router-dom';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { API_BASE } from '../../config/apiBase';
import { useChatCommands, parseUIActions, ChatActionTypes } from "../../shared/hooks/useChatCommands"
import ErrorBoundary from '../../shared/components/ErrorBoundary';
import ConfirmDialog from '../../shared/components/ConfirmDialog';
import { useToast, ToastContainer } from '../../shared/components/Toast';
import { useAuth } from 'shared/auth/AuthContext';
import { authFetch as cookieAuthFetch, buildAuthHeaders } from '../../shared/auth/http';
import { getPlanConnectorSentence } from '../../shared/billing/planConnectors';

import { FontAwesomeIcon } from '@fortawesome/react-fontawesome';
import {
  faQuestionCircle,
  faPaperPlane, faSpinner, faTimes, faBars, faCheck, faExclamationTriangle,
  faChartLine, faTrash, faPlus, faMinus, faMicrophone,
  faBolt, faLayerGroup, faPlay, faListCheck, faArrowUpRightFromSquare, faGaugeHigh, faClockRotateLeft, faPaperclip, faArrowUp,
  faDownload, faChevronDown, faUser, faBell, faLock, faCopy, faThumbsUp, faThumbsDown, faRotate, faPen, faArrowRightArrowLeft
} from '@fortawesome/free-solid-svg-icons';
import {
  MonitorCheck, MessageCircleQuestion,
  Sigma, Plus as LucidePlus, BarChart3
} from 'lucide-react';

// Data / storage
import { Jaspen, storage } from './JaspenClient';

// Tab components
import ScoreDashboard   from './ScoreDashboard';
import ScenarioModeler  from './ScenarioModeler';
import ComparisonView   from './ComparisonView';
import BatchIdeaManager from './components/BatchIdeaManager';
import Onboarding from './components/Onboarding';
import SidebarIdentityFooter from './components/SidebarIdentityFooter';
import JaspenAiDrawer from './JaspenAiDrawer';
import ThreadEditModal from '../components/ThreadEditModal';
import { buildInviteDisplay, buildInviteLink } from '../../shared/inviteLink';
import { PLAN_ORDER, PLAN_RANK } from '../../shared/constants/appConstants';

// Styles - Single source of truth
import "./JaspenWorkspace.css";

const IS_DEV = process.env.NODE_ENV !== 'production';
const devWarn = (...args) => {
  if (IS_DEV) console.warn(...args);
};

const getRestorableSessionIdFromLocation = () => {
  try {
    const params = new URLSearchParams(window.location.search);
    return params.get('sid') || params.get('session_id') || null;
  } catch {
    return null;
  }
};

const objectHasMeaningfulValue = (value) => {
  if (value == null) return false;
  if (typeof value === 'string') return value.trim().length > 0;
  if (typeof value === 'number') return Number.isFinite(value) && value !== 0;
  if (typeof value === 'boolean') return value;
  if (Array.isArray(value)) return value.some((entry) => objectHasMeaningfulValue(entry));
  if (typeof value === 'object') return Object.values(value).some((entry) => objectHasMeaningfulValue(entry));
  return false;
};

const hasMeaningfulScorecardData = (value) => {
  if (!value || typeof value !== 'object') return false;

  const explicitScore = Number(value.jaspen_score ?? value.score ?? value?.compat?.score);
  if (Number.isFinite(explicitScore) && explicitScore > 0) return true;

  if (typeof value.score_category === 'string' && value.score_category.trim()) {
    const nonDefaultCategories = new Set(['excellent', 'good', 'fair', 'at risk', 'needs improvement']);
    if (!nonDefaultCategories.has(value.score_category.trim().toLowerCase())) return true;
  }

  const componentScores = value.component_scores || value?.compat?.components;
  if (componentScores && typeof componentScores === 'object') {
    const scoreValues = Object.values(componentScores)
      .map((entry) => Number(entry))
      .filter((entry) => Number.isFinite(entry));
    if (scoreValues.some((entry) => entry > 0)) return true;
  }

  if (objectHasMeaningfulValue(value.financial_impact || value?.compat?.financials)) return true;
  if (Array.isArray(value.key_insights) && value.key_insights.length > 0) return true;
  if (Array.isArray(value.top_risks) && value.top_risks.length > 0) return true;
  if (Array.isArray(value.recommendations) && value.recommendations.length > 0) return true;
  if (typeof value.executive_summary === 'string' && value.executive_summary.trim()) return true;
  if (typeof value.executive_narrative === 'string' && value.executive_narrative.trim()) return true;
  if (objectHasMeaningfulValue(value.before_after_financials)) return true;
  if (objectHasMeaningfulValue(value.investment_analysis)) return true;
  if (objectHasMeaningfulValue(value.npv_irr_analysis)) return true;
  if (objectHasMeaningfulValue(value.valuation)) return true;
  if (objectHasMeaningfulValue(value.decision_framework)) return true;
  if (hasMeaningfulScorecardData(value._baseline_scorecard)) return true;
  if (Array.isArray(value.scorecard_snapshots) && value.scorecard_snapshots.some((entry) => hasMeaningfulScorecardData(entry))) return true;

  return false;
};

const extractMeaningfulHistoryResult = (history) => {
  if (!Array.isArray(history)) return null;
  for (const entry of history) {
    if (entry && typeof entry === 'object' && hasMeaningfulScorecardData(entry.result)) {
      return entry.result;
    }
  }
  return null;
};

const getMeaningfulBundleScorecard = (bundle) => {
  if (!bundle || typeof bundle !== 'object') return null;
  const currentScorecard = bundle.current_scorecard;
  const baselineScorecard = bundle.baseline_scorecard;
  if (hasMeaningfulScorecardData(currentScorecard)) return currentScorecard;
  if (hasMeaningfulScorecardData(baselineScorecard)) return baselineScorecard;
  return null;
};

const getDisplayScorecardResult = (result, threadId = '') => {
  if (!result || typeof result !== 'object') return result;

  const snapshots = Array.isArray(result.scorecard_snapshots) ? result.scorecard_snapshots : [];
  const selectedId = String(result.selected_scorecard_id || '').trim();
  const selectedSnapshot = selectedId
    ? snapshots.find((snapshot) => String(snapshot?.id || snapshot?.analysis_id || '').trim() === selectedId)
    : null;
  const baselineScorecard = result._baseline_scorecard && typeof result._baseline_scorecard === 'object'
    ? result._baseline_scorecard
    : null;

  const chosen = hasMeaningfulScorecardData(selectedSnapshot)
    ? selectedSnapshot
    : hasMeaningfulScorecardData(baselineScorecard)
      ? baselineScorecard
      : null;

  if (!chosen) return result;

  return {
    ...result,
    ...chosen,
    _owner_thread_id: String(threadId || chosen._owner_thread_id || result._owner_thread_id || '').trim() || undefined,
    project_name: chosen.project_name || result.project_name,
    analysis_id: chosen.analysis_id || chosen.id || result.analysis_id,
  };
};

const resolveHistoryOwnerId = (analysisHistory = [], ...candidateIds) => {
  const candidates = candidateIds
    .map((value) => String(value || '').trim())
    .filter(Boolean);

  if (candidates.length === 0) return '';

  for (const tid of candidates) {
    const exactEntry = analysisHistory.find((entry) => String(entry?.id || '').trim() === tid);
    if (exactEntry?.id) return String(exactEntry.id).trim();

    const byAnalysis = analysisHistory.find((entry) => {
      const result = entry?.result;
      if (!result || typeof result !== 'object') return false;
      const resultIds = [
        result.analysis_id,
        result.id,
        result.session_id,
        result.thread_id,
        result?._owner_thread_id,
        result?.meta?.thread_id,
      ].map((value) => String(value || '').trim()).filter(Boolean);
      return resultIds.includes(tid);
    });
    if (byAnalysis?.id) return String(byAnalysis.id).trim();
  }

  return candidates[0];
};

const buildMergedScorecardSnapshots = ({
  analysisResult = null,
  bundleBaselineScorecard = null,
  baselineScorecardId = '',
  scorecardSnapshots = [],
  sessionId = '',
}) => {
  const baselineSource =
    (analysisResult?._baseline_scorecard && typeof analysisResult._baseline_scorecard === 'object'
      ? analysisResult._baseline_scorecard
      : null) ||
    bundleBaselineScorecard ||
    analysisResult ||
    null;

  const baselineId = String(
    baselineScorecardId ||
    baselineSource?.analysis_id ||
    baselineSource?.id ||
    baselineSource?.analysisId ||
    sessionId ||
    ''
  ).trim();

  const baselineSnapshot =
    baselineSource && typeof baselineSource === 'object' && baselineId
      ? {
          ...baselineSource,
          id: baselineId,
          analysis_id: baselineSource.analysis_id || baselineId,
          label: 'Baseline',
          isBaseline: true,
        }
      : null;

  const merged = [];
  const seen = new Set();
  const pushSnapshot = (snapshot) => {
    if (!snapshot || typeof snapshot !== 'object') return;
    const snapshotId = String(
      snapshot.id || snapshot.analysis_id || snapshot.analysisId || ''
    ).trim();
    if (!snapshotId || seen.has(snapshotId)) return;
    seen.add(snapshotId);
    merged.push({
      ...snapshot,
      id: snapshotId,
      analysis_id: snapshot.analysis_id || snapshotId,
      isBaseline: Boolean(snapshot.isBaseline),
    });
  };

  pushSnapshot(baselineSnapshot);
  (Array.isArray(scorecardSnapshots) ? scorecardSnapshots : []).forEach((snapshot) => {
    if (!snapshot || typeof snapshot !== 'object') return;
    const snapshotId = String(snapshot.id || snapshot.analysis_id || '').trim();
    if (baselineSnapshot && snapshotId === String(baselineSnapshot.id || '').trim()) {
      pushSnapshot({
        ...snapshot,
        ...baselineSnapshot,
        isBaseline: true,
        label: 'Baseline',
      });
      return;
    }
    pushSnapshot(snapshot);
  });

  return merged;
};

const resolveScoreWorkspaceContext = ({
  analysisHistory = [],
  sessionId = '',
  currentSessionId = '',
  selectedScorecardId = '',
  baselineScorecardId = '',
  scorecardSnapshots = [],
  selectedVariant = null,
  analysisResult = null,
  bundleCurrentScorecard = null,
  bundleBaselineScorecard = null,
  view = 'intake',
  activeTab = 'summary',
}) => {
  const snapshots = buildMergedScorecardSnapshots({
    analysisResult,
    bundleBaselineScorecard,
    baselineScorecardId,
    scorecardSnapshots,
    sessionId,
  });
  const snapshotMatch = selectedScorecardId
    ? snapshots.find((snapshot) => snapshot?.id === selectedScorecardId)
    : null;

  const baselineSnapshot = snapshots.find((snapshot) => snapshot?.isBaseline) || snapshots[0] || null;
  const scorecard =
    snapshotMatch ||
    (snapshots.length > 0
      ? baselineSnapshot
      : null) ||
    (hasMeaningfulScorecardData(selectedVariant) ? selectedVariant : null) ||
    (hasMeaningfulScorecardData(analysisResult) ? analysisResult : null) ||
    (hasMeaningfulScorecardData(bundleCurrentScorecard) ? bundleCurrentScorecard : null) ||
    (hasMeaningfulScorecardData(bundleBaselineScorecard) ? bundleBaselineScorecard : null) ||
    selectedVariant ||
    analysisResult ||
    bundleCurrentScorecard ||
    bundleBaselineScorecard ||
    null;

  const scorecardId = String(
    selectedScorecardId ||
    scorecard?.analysis_id ||
    scorecard?.id ||
    scorecard?.analysisId ||
    ''
  ).trim();

  const ownerThreadId = resolveHistoryOwnerId(
    analysisHistory,
    sessionId,
    currentSessionId,
    scorecard?.thread_id,
    scorecard?.session_id,
    scorecard?._owner_thread_id,
    scorecard?.meta?.thread_id,
    scorecard?.analysis_id,
    scorecard?.id,
    analysisResult?.thread_id,
    analysisResult?.session_id,
    analysisResult?._owner_thread_id,
    analysisResult?.meta?.thread_id,
    analysisResult?.analysis_id,
    analysisResult?.id,
    bundleCurrentScorecard?.thread_id,
    bundleCurrentScorecard?.session_id,
    bundleBaselineScorecard?.thread_id,
    bundleBaselineScorecard?.session_id,
  );

  const hasScorecard = hasMeaningfulScorecardData(scorecard);
  const mode = activeTab === 'scenario'
    ? 'scenario'
    : hasScorecard || view === 'summary'
      ? 'summary'
      : 'intake';

  return {
    ownerThreadId,
    scorecard,
    scorecardId,
    hasScorecard,
    mode,
  };
};

const buildScorecardSnapshots = ({
  threadId = '',
  baselineScorecard = null,
  currentScorecard = null,
  scenarioScorecards = [],
}) => {
  const snapshots = [];
  const normalizedThreadId = String(threadId || '').trim();

  if (baselineScorecard && typeof baselineScorecard === 'object') {
    snapshots.push({
      ...baselineScorecard,
      id:
        baselineScorecard.analysis_id ||
        baselineScorecard.id ||
        baselineScorecard.analysisId ||
        `baseline_${normalizedThreadId || Date.now()}`,
      label: baselineScorecard.label || 'Baseline',
      isBaseline: true,
    });
  }

  if (currentScorecard && typeof currentScorecard === 'object') {
    const currentId =
      currentScorecard.analysis_id ||
      currentScorecard.id ||
      currentScorecard.analysisId ||
      `current_${normalizedThreadId || Date.now()}`;
    const baselineId =
      baselineScorecard?.analysis_id ||
      baselineScorecard?.id ||
      baselineScorecard?.analysisId ||
      null;

    if (!baselineId || currentId !== baselineId) {
      snapshots.push({
        ...currentScorecard,
        id: currentId,
        label: currentScorecard.label || currentScorecard.project_name || 'Current',
        isBaseline: Boolean(currentScorecard.isBaseline),
      });
    }
  }

  (Array.isArray(scenarioScorecards) ? scenarioScorecards : []).forEach((scorecard, idx) => {
    if (!scorecard || typeof scorecard !== 'object') return;
    snapshots.push({
      ...scorecard,
      id:
        scorecard.analysis_id ||
        scorecard.id ||
        scorecard.analysisId ||
        `scenario_${idx}_${normalizedThreadId || Date.now()}`,
      label: scorecard.label || scorecard.project_name || `Scenario ${idx + 1}`,
      isBaseline: false,
    });
  });

  return snapshots;
};

const parseHistoryTimestamp = (value) => {
  const text = String(value || '').trim();
  const normalized = text && /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?$/.test(text)
    ? `${text}Z`
    : value;
  const ts = new Date(normalized || 0).getTime();
  return Number.isFinite(ts) ? ts : 0;
};

// === Header Icon Helpers =====================================================
const PM_VARIANT  = "monitor-check";
const LSS_VARIANT = "chart-scatter";
const MODEL_DISPLAY_ORDER = ['pluto', 'orbit', 'titan'];
const MODEL_VERSION_BY_TYPE = { pluto: '1.0', orbit: '1.0', titan: '1.0' };
const ADMIN_PREVIEW_PLAN_KEYS = new Set(['free', 'essential', 'team', 'enterprise']);
const OBJECTIVE_OPTIONS = [
  { key: 'balanced', label: 'Balanced' },
  { key: 'cost', label: 'Cost Optimization' },
  { key: 'speed', label: 'Speed to Market' },
  { key: 'growth', label: 'Growth' },
];
const OBJECTIVE_LABEL_BY_KEY = OBJECTIVE_OPTIONS.reduce((acc, option) => {
  acc[option.key] = option.label;
  return acc;
}, {});
const OBJECTIVE_ALIAS = {
  balanced: 'balanced',
  default: 'balanced',
  general: 'balanced',
  cost: 'cost',
  'cost optimization': 'cost',
  'cost-optimization': 'cost',
  efficiency: 'cost',
  profitability: 'cost',
  speed: 'speed',
  'speed to market': 'speed',
  'speed-to-market': 'speed',
  timeline: 'speed',
  delivery: 'speed',
  growth: 'growth',
  revenue: 'growth',
  expansion: 'growth',
};
const ONBOARDING_STORAGE_KEY = 'jaspen_onboarded';
const GUIDED_FLOW_STORAGE_KEY = 'jaspen_guided_flow_state_v1';
const GUIDED_FLOW_TEMPLATE_PROMPT = 'I need help evaluating a new initiative. Ask me the essential questions, then generate a scorecard, propose scenarios, and recommend an execution plan.';
const ONBOARDING_ROLE_LABELS = {
  executive: 'Executive',
  pm: 'PM',
  analyst: 'Analyst',
  other: 'Other',
};
const ONBOARDING_EVALUATION_LABELS = {
  new_initiative: 'New initiative',
  cost_optimization: 'Cost optimization',
  growth_strategy: 'Growth strategy',
  operational_improvement: 'Operational improvement',
};
const ONBOARDING_START_LABELS = {
  conversation: 'Start a conversation',
  batch_ideas: 'Upload a list of ideas',
  data_upload: 'Upload data for analysis',
};
const ONBOARDING_OBJECTIVE_BY_EVALUATION = {
  new_initiative: 'balanced',
  cost_optimization: 'cost',
  growth_strategy: 'growth',
  operational_improvement: 'speed',
};
const INITIAL_NOTIFICATION_UPDATES = [
  {
    id: 'notif-model-access',
    title: 'Model access by plan',
    body: 'Pluto-1.0 is available now. Orbit-1.0 and Titan-1.0 show upgrade guidance when locked.',
    stamp: 'Today',
  },
  {
    id: 'notif-readiness',
    title: 'Readiness checklist sync',
    body: 'Frontend and backend checklist signals are now aligned to reduce score drift.',
    stamp: 'Today',
  },
  {
    id: 'notif-account',
    title: 'Account settings update',
    body: 'Display name editing is available in User Settings so you can control how you are addressed.',
    stamp: 'Today',
  },
];
const SETUP_REMINDER_NOTIFICATION = {
  id: 'notif-setup-reminder',
  title: 'Tailor Jaspen later',
  body: 'You can come back anytime from Account settings to update your display name, role, and starting preference.',
  stamp: 'Now',
};

const buildDefaultNotifications = () =>
  INITIAL_NOTIFICATION_UPDATES.map((item) => ({ ...item }));

const normalizeNotificationFeed = (value) =>
  (Array.isArray(value) ? value : [])
    .map((item, idx) => {
      if (!item || typeof item !== 'object') return null;
      const fallback = INITIAL_NOTIFICATION_UPDATES[idx] || {};
      const id = String(item.id || fallback.id || `notif-${idx + 1}`).trim();
      if (!id) return null;
      return {
        id,
        title: String(item.title || fallback.title || 'Notification').trim(),
        body: String(item.body || fallback.body || '').trim(),
        stamp: String(item.stamp || fallback.stamp || 'Today').trim(),
      };
    })
    .filter(Boolean);

// ============================================================================
// Readiness Normalization Helpers (Backend Contract Compliance)
// ============================================================================

/**
 * Normalize readiness value to standard object shape
 * Per backend contract: readiness can be int, float, string, or object
 * Matches sessions.py normalization behavior
 */
function normalizeReadiness(value) {
  if (value && typeof value === 'object') {
    const percent = Math.max(0, Math.min(100, Math.round(Number(value.percent) || 0)));
    const categories = Array.isArray(value.categories) ? value.categories : [];
    const items = Array.isArray(value.items) ? value.items : [];
    const checklist_summary = value.checklist_summary && typeof value.checklist_summary === 'object'
      ? value.checklist_summary
      : null;
    const updated_at = value.updated_at || null;
    const version = value.version || null;
    const objective_profile = value.objective_profile || null;
    return { percent, categories, items, checklist_summary, updated_at, version, objective_profile };
  }
  
  // Primitive value (int/float/string)
  const pct = Math.max(0, Math.min(100, Math.round(Number(value) || 0)));
  return { percent: pct, categories: [], items: [], checklist_summary: null, updated_at: null, version: null, objective_profile: null };
}

/**
 * Clamp percentage to valid range [0, 100]
 */
function clampPercent(p) {
  return Math.max(0, Math.min(100, Math.round(Number(p) || 0)));
}

function formatHistoryLastUsed(value) {
  const ts = parseHistoryTimestamp(value);
  if (!ts) return '';
  const date = new Date(ts);
  return date.toLocaleString('en-US', {
    month: 'short',
    day: 'numeric',
    hour: 'numeric',
    minute: '2-digit',
  });
}

function getLastUserMessageTimestamp(chatHistory, fallbackValue = null) {
  if (Array.isArray(chatHistory)) {
    for (let index = chatHistory.length - 1; index >= 0; index -= 1) {
      const entry = chatHistory[index];
      const role = String(entry?.role || entry?.sender || '').trim().toLowerCase();
      if (role !== 'user') continue;
      const ts = parseHistoryTimestamp(
        entry?.timestamp || entry?.created_at || entry?.createdAt || entry?.updated_at || null
      );
      if (ts) return ts;
    }
  }
  return parseHistoryTimestamp(fallbackValue);
}

function normalizeStrategyObjective(value, fallback = 'balanced') {
  const text = String(value || '').trim().toLowerCase();
  if (!text) return fallback;
  if (OBJECTIVE_ALIAS[text]) return OBJECTIVE_ALIAS[text];
  const compact = text.replace(/[_-]+/g, ' ');
  return OBJECTIVE_ALIAS[compact] || fallback;
}

function getOnboardingOwnerKey(user) {
  if (user?.id) return `id:${user.id}`;
  if (user?.email) return `email:${String(user.email).toLowerCase()}`;
  return '';
}

const NAME_PROMPT_STORAGE_KEY = 'jaspen_name_prompt_state_v1';

function readOnboardingState(user) {
  const ownerKey = getOnboardingOwnerKey(user);
  const profilePrefs = user?.ui_preferences && typeof user.ui_preferences === 'object'
    ? user.ui_preferences
    : {};
  const profileOnboarding = profilePrefs?.onboarding && typeof profilePrefs.onboarding === 'object'
    ? profilePrefs.onboarding
    : null;
  const profileFallbackCompleted = typeof profilePrefs?.onboarding_complete === 'boolean'
    ? profilePrefs.onboarding_complete
    : null;
  if (!ownerKey) {
    if (profileOnboarding) {
      return {
        completed: Boolean(profileOnboarding.completed),
        deferred: Boolean(profileOnboarding.deferred),
        selection: profileOnboarding.selection && typeof profileOnboarding.selection === 'object'
          ? { ...profileOnboarding.selection }
          : null,
      };
    }
    if (typeof profileFallbackCompleted === 'boolean') {
      return { completed: profileFallbackCompleted, deferred: false, selection: null };
    }
    return null;
  }
  try {
    const raw = localStorage.getItem(ONBOARDING_STORAGE_KEY);
    if (!raw) {
      if (profileOnboarding) {
        return {
          completed: Boolean(profileOnboarding.completed),
          deferred: Boolean(profileOnboarding.deferred),
          selection: profileOnboarding.selection && typeof profileOnboarding.selection === 'object'
            ? { ...profileOnboarding.selection }
            : null,
        };
      }
      if (typeof profileFallbackCompleted === 'boolean') {
        return { completed: profileFallbackCompleted, deferred: false, selection: null };
      }
      return null;
    }
    if (raw === 'true') return { completed: true, deferred: false, selection: null };
    const parsed = JSON.parse(raw);
    const entry = parsed?.[ownerKey];
    if (typeof entry === 'boolean') return { completed: entry, deferred: false, selection: null };
    if (entry && typeof entry === 'object') return entry;
    if (profileOnboarding) {
      return {
        completed: Boolean(profileOnboarding.completed),
        deferred: Boolean(profileOnboarding.deferred),
        selection: profileOnboarding.selection && typeof profileOnboarding.selection === 'object'
          ? { ...profileOnboarding.selection }
          : null,
      };
    }
    if (typeof profileFallbackCompleted === 'boolean') {
      return { completed: profileFallbackCompleted, deferred: false, selection: null };
    }
    return null;
  } catch (error) {
    devWarn('[onboarding] Failed to read onboarding completion state', error);
    if (profileOnboarding) {
      return {
        completed: Boolean(profileOnboarding.completed),
        deferred: Boolean(profileOnboarding.deferred),
        selection: profileOnboarding.selection && typeof profileOnboarding.selection === 'object'
          ? { ...profileOnboarding.selection }
          : null,
      };
    }
    if (typeof profileFallbackCompleted === 'boolean') {
      return { completed: profileFallbackCompleted, deferred: false, selection: null };
    }
    return null;
  }
}

function readOnboardingCompletion(user) {
  return Boolean(readOnboardingState(user)?.completed);
}

function writeOnboardingState(user, payload = {}) {
  const ownerKey = getOnboardingOwnerKey(user);
  if (!ownerKey) return;
  try {
    const raw = localStorage.getItem(ONBOARDING_STORAGE_KEY);
    const parsed = raw ? JSON.parse(raw) : {};
    const next = parsed && typeof parsed === 'object' ? { ...parsed } : {};
    next[ownerKey] = {
      completed: Boolean(payload?.completed),
      deferred: Boolean(payload?.deferred),
      selection: payload?.selection && typeof payload.selection === 'object'
        ? { ...payload.selection }
        : null,
    };
    localStorage.setItem(ONBOARDING_STORAGE_KEY, JSON.stringify(next));
  } catch (error) {
    devWarn('[onboarding] Failed to persist onboarding completion state', error);
  }
}

function readNamePromptDeferred(user) {
  const ownerKey = getOnboardingOwnerKey(user);
  if (!ownerKey) return false;
  try {
    const raw = localStorage.getItem(NAME_PROMPT_STORAGE_KEY);
    if (!raw) return false;
    const parsed = JSON.parse(raw);
    return Boolean(parsed?.[ownerKey]?.deferred);
  } catch (error) {
    devWarn('[onboarding] Failed to read name prompt state', error);
    return false;
  }
}

function writeNamePromptDeferred(user, deferred) {
  const ownerKey = getOnboardingOwnerKey(user);
  if (!ownerKey) return;
  try {
    const raw = localStorage.getItem(NAME_PROMPT_STORAGE_KEY);
    const parsed = raw ? JSON.parse(raw) : {};
    const next = parsed && typeof parsed === 'object' ? { ...parsed } : {};
    next[ownerKey] = { deferred: Boolean(deferred) };
    localStorage.setItem(NAME_PROMPT_STORAGE_KEY, JSON.stringify(next));
  } catch (error) {
    devWarn('[onboarding] Failed to persist name prompt state', error);
  }
}

function readGuidedFlowDismissed(user) {
  const ownerKey = getOnboardingOwnerKey(user);
  if (!ownerKey) return false;
  try {
    const raw = localStorage.getItem(GUIDED_FLOW_STORAGE_KEY);
    if (!raw) return false;
    const parsed = JSON.parse(raw);
    return Boolean(parsed?.[ownerKey]?.dismissed);
  } catch (error) {
    devWarn('[onboarding] Failed to read guided flow state', error);
    return false;
  }
}

function writeGuidedFlowDismissed(user, dismissed) {
  const ownerKey = getOnboardingOwnerKey(user);
  if (!ownerKey) return;
  try {
    const raw = localStorage.getItem(GUIDED_FLOW_STORAGE_KEY);
    const parsed = raw ? JSON.parse(raw) : {};
    const next = parsed && typeof parsed === 'object' ? { ...parsed } : {};
    next[ownerKey] = { dismissed: Boolean(dismissed) };
    localStorage.setItem(GUIDED_FLOW_STORAGE_KEY, JSON.stringify(next));
  } catch (error) {
    devWarn('[onboarding] Failed to persist guided flow state', error);
  }
}

function isContextSyncMessage(text) {
  return String(text || '').trim().toLowerCase() === '[context-sync]';
}

function isPdfLikeFile(fileLike) {
  const type = String(fileLike?.type || '').toLowerCase();
  const name = String(fileLike?.name || '').toLowerCase();
  return type === 'application/pdf' || name.endsWith('.pdf');
}

function isWordLikeFile(fileLike) {
  const type = String(fileLike?.type || '').toLowerCase();
  const name = String(fileLike?.name || '').toLowerCase();
  return (
    type === 'application/vnd.openxmlformats-officedocument.wordprocessingml.document'
    || type === 'application/msword'
    || name.endsWith('.docx')
    || name.endsWith('.doc')
  );
}

function isImageLikeFile(fileLike) {
  const type = String(fileLike?.type || '').toLowerCase();
  const name = String(fileLike?.name || '').toLowerCase();
  return type.startsWith('image/') || /\.(png|jpe?g|gif|webp)$/i.test(name);
}

function isChatAttachmentFile(fileLike) {
  return isImageLikeFile(fileLike) || isPdfLikeFile(fileLike) || isWordLikeFile(fileLike);
}

function buildMessageAttachmentMeta(fileLike) {
  const fallbackType = isPdfLikeFile(fileLike)
    ? 'application/pdf'
    : isWordLikeFile(fileLike)
      ? 'application/vnd.openxmlformats-officedocument.wordprocessingml.document'
      : 'application/octet-stream';
  return {
    name: fileLike?.name || 'attachment',
    size: Number(fileLike?.size || 0),
    type: fileLike?.type || fallbackType,
    preview: fileLike?.preview || null,
    uploading: Boolean(fileLike?.uploading),
  };
}

const SCORE_COMPONENT_PROMPT_ROWS = [
  { key: 'financial_health', label: 'Financial Health', aliases: ['financial_health', 'financialHealth', 'financial', 'economics'] },
  { key: 'operational_efficiency', label: 'Operational Efficiency', aliases: ['operational_efficiency', 'operationalEfficiency', 'operations', 'execution'] },
  { key: 'market_position', label: 'Market Position', aliases: ['market_position', 'marketPosition', 'market', 'strategy'] },
  { key: 'execution_readiness', label: 'Execution Readiness', aliases: ['execution_readiness', 'executionReadiness', 'readiness', 'team'] },
];

function extractScoreComponentRows(scorecard) {
  const comps = scorecard?.component_scores || scorecard?.scores || scorecard?.compat?.components || {};
  return SCORE_COMPONENT_PROMPT_ROWS.map((row) => {
    const rawValue = row.aliases
      .map((alias) => comps?.[alias])
      .find((value) => value !== undefined && value !== null);
    const numeric = Number(rawValue);
    return {
      key: row.key,
      label: row.label,
      value: Number.isFinite(numeric) ? Math.max(0, Math.min(100, Math.round(numeric))) : 0,
    };
  });
}

function scorecardRiskPromptText(scorecard) {
  const risks = Array.isArray(scorecard?.risks) ? scorecard.risks : (Array.isArray(scorecard?.top_risks) ? scorecard.top_risks : []);
  if (!risks.length) return '';
  const first = risks[0];
  if (typeof first === 'string') return first.trim().slice(0, 120);
  if (first && typeof first === 'object') {
    const candidate = String(first.title || first.risk || first.summary || first.description || '').trim();
    return candidate.slice(0, 120);
  }
  return '';
}

function buildScorecardFollowUpPrompts(scorecard, projectTitle) {
  if (!scorecard || typeof scorecard !== 'object') return [];
  const rows = extractScoreComponentRows(scorecard).sort((a, b) => a.value - b.value);
  const weakest = rows[0];
  const riskText = scorecardRiskPromptText(scorecard);
  const safeTitle = String(projectTitle || scorecard?.project_name || 'this initiative').trim() || 'this initiative';

  const prompts = [
    weakest
      ? `What are the top 3 actions to lift ${weakest.label} from ${weakest.value} to 70 in the next 90 days?`
      : 'What are the top 3 actions that would raise this score fastest?',
    riskText
      ? `Pressure-test this risk and propose mitigations: "${riskText}"`
      : 'What assumptions are most likely to fail, and how should we de-risk them?',
    `Give me an executive-ready 30-60-90 day plan for ${safeTitle}.`,
  ];

  return prompts.filter(Boolean);
}

const SCORECARD_PATCHABLE_FIELDS = [
  'executive_summary',
  'executive_narrative',
  'top_risks',
  'risks',
  'recommendations',
  'assumptions',
  'key_insights',
  'component_rationale',
  'decision_framework',
  'financial_impact',
  'investment_analysis',
  'npv_irr_analysis',
  'valuation',
];

function buildScorecardRestorePatch(snapshot) {
  if (!snapshot || typeof snapshot !== 'object') return {};
  const payload = {};
  SCORECARD_PATCHABLE_FIELDS.forEach((key) => {
    if (snapshot[key] !== undefined) payload[key] = snapshot[key];
  });
  if (payload.risks !== undefined && payload.top_risks === undefined) {
    payload.top_risks = payload.risks;
  }
  delete payload.risks;
  return payload;
}

function cloneScorecardSnapshot(snapshot) {
  if (!snapshot || typeof snapshot !== 'object') return null;
  try {
    return JSON.parse(JSON.stringify(snapshot));
  } catch {
    return { ...snapshot };
  }
}

function toUiMessages(history = []) {
  return (Array.isArray(history) ? history : [])
    .map((msg, historyIndex) => ({
      role: msg?.role === 'user' ? 'user' : 'ai',
      text: (msg?.content || msg?.text || '').trim(),
      historyIndex,
      feedbackValue: String(msg?.feedback?.value || '').trim().toLowerCase() || null,
      hasMutations: Array.isArray(msg?.mutations) && msg.mutations.length > 0,
      canUndo: Boolean(msg?.undo?.available),
      undoApplied: Boolean(msg?.undo?.applied),
      regenerated: Boolean(msg?.regenerated),
      alternativesCount: Array.isArray(msg?.alternatives) ? msg.alternatives.length : 0,
      attachments: Array.isArray(msg?.attachments)
        ? msg.attachments
          .map((attachment) => buildMessageAttachmentMeta(attachment))
          .filter((attachment) => attachment.name)
        : [],
    }))
    .filter((m) => m.text.length > 0 && !isContextSyncMessage(m.text));
}

function deriveIdeaTitle({ result = null, messages = [], fallback = 'Untitled Idea' } = {}) {
  const projectName = String(
    result?.project_name ||
    result?.name ||
    result?.title ||
    result?.compat?.title ||
    ''
  ).trim();
  if (projectName) return projectName;

  const firstUserIdea = (Array.isArray(messages) ? messages : [])
    .find((m) => m?.role === 'user' && String(m?.text || '').trim().length > 0);

  if (firstUserIdea?.text) {
    return String(firstUserIdea.text).trim().slice(0, 72);
  }

  return fallback;
}

function normalizeSearchableText(value) {
  return String(value || '')
    .replace(/\s+/g, ' ')
    .trim();
}

function extractHistoryScoreMetrics(item) {
  const result = item?.result && typeof item.result === 'object' ? item.result : {};
  const componentScores = result?.component_scores && typeof result.component_scores === 'object'
    ? result.component_scores
    : {};
  const toNumber = (value) => {
    const numeric = Number(value);
    return Number.isFinite(numeric) ? numeric : null;
  };
  const overallScore = toNumber(result?.jaspen_score);
  return {
    overall_score: overallScore,
    risk_score: Number.isFinite(overallScore) ? Math.max(0, 100 - overallScore) : null,
    financial_health: toNumber(componentScores?.financial_health),
    operational_efficiency: toNumber(componentScores?.operational_efficiency),
    market_position: toNumber(componentScores?.market_position),
    execution_readiness: toNumber(componentScores?.execution_readiness),
  };
}

function parseHistorySemanticFilter(query = '') {
  const normalized = normalizeSearchableText(query).toLowerCase();
  if (!normalized) return null;

  const pattern = /\b((?:risk(?:\s+score)?|overall(?:\s+score)?|jaspen(?:\s+score)?|financial(?:\s+health)?|operational(?:\s+efficiency)?|market(?:\s+position)?|execution(?:\s+readiness)?|readiness))\b\s*(?:score\s*)?(below|under|less than|at most|<=|above|over|greater than|at least|>=)\s*(\d{1,3}(?:\.\d+)?)/i;
  const match = normalized.match(pattern);
  if (!match) return null;

  const metricText = String(match[1] || '').toLowerCase();
  const comparatorText = String(match[2] || '').toLowerCase();
  const threshold = Number(match[3]);
  if (!Number.isFinite(threshold)) return null;

  const metric = (() => {
    if (metricText.includes('risk')) return 'risk_score';
    if (metricText.includes('overall') || metricText.includes('jaspen')) return 'overall_score';
    if (metricText.includes('financial')) return 'financial_health';
    if (metricText.includes('operational')) return 'operational_efficiency';
    if (metricText.includes('market')) return 'market_position';
    if (metricText.includes('execution') || metricText.includes('readiness')) return 'execution_readiness';
    return null;
  })();
  if (!metric) return null;

  const comparator = ['below', 'under', 'less than', 'at most', '<='].includes(comparatorText)
    ? 'lte'
    : 'gte';

  const residualQuery = normalizeSearchableText(
    normalized.replace(match[0], '').replace(/\s+/g, ' ')
  ).toLowerCase();

  return { metric, comparator, threshold, residualQuery };
}

function metricLabelForHistory(metricKey = '') {
  const key = String(metricKey || '').toLowerCase();
  if (key === 'risk_score') return 'Risk Score';
  if (key === 'overall_score') return 'Jaspen Score';
  if (key === 'financial_health') return 'Financial Health';
  if (key === 'operational_efficiency') return 'Operational Efficiency';
  if (key === 'market_position') return 'Market Position';
  if (key === 'execution_readiness') return 'Execution Readiness';
  return 'Score';
}

function buildHistorySearchRecord(item, query = '') {
  const normalizedQuery = normalizeSearchableText(query).toLowerCase();
  const rawHistory = Array.isArray(item?.result?.chat_history) ? item.result.chat_history : [];
  const messages = rawHistory
    .map((msg) => normalizeSearchableText(msg?.content || msg?.text || ''))
    .filter(Boolean);
  const title = deriveIdeaTitle({
    result: item?.result,
    messages: rawHistory.map((msg) => ({
      role: msg?.role === 'user' ? 'user' : 'ai',
      text: normalizeSearchableText(msg?.content || msg?.text || ''),
    })),
    fallback: `Analysis ${item?.id?.slice(-8) || ''}`.trim(),
  });
  const result = item?.result && typeof item.result === 'object' ? item.result : {};
  const auxiliaryText = [
    ...((Array.isArray(result?.key_insights) ? result.key_insights : []).map((value) => normalizeSearchableText(value))),
    ...((Array.isArray(result?.recommendations) ? result.recommendations : []).map((value) => {
      if (typeof value === 'string') return normalizeSearchableText(value);
      if (value && typeof value === 'object') {
        return normalizeSearchableText(value?.action || value?.recommendation || value?.title || value?.summary || '');
      }
      return '';
    })),
    ...((Array.isArray(result?.top_risks) ? result.top_risks : Array.isArray(result?.risks) ? result.risks : []).map((value) => {
      if (typeof value === 'string') return normalizeSearchableText(value);
      if (value && typeof value === 'object') {
        return normalizeSearchableText(value?.risk || value?.title || value?.summary || value?.description || '');
      }
      return '';
    })),
  ].filter(Boolean);
  const searchableCorpus = [title, ...messages, ...auxiliaryText];

  if (!normalizedQuery) {
    return { item, title, matchSnippet: '' };
  }

  const semanticFilter = parseHistorySemanticFilter(normalizedQuery);
  const metrics = extractHistoryScoreMetrics(item);
  if (semanticFilter) {
    const metricValue = Number(metrics?.[semanticFilter.metric]);
    if (!Number.isFinite(metricValue)) return null;
    const passesNumeric = semanticFilter.comparator === 'lte'
      ? metricValue <= semanticFilter.threshold
      : metricValue >= semanticFilter.threshold;
    if (!passesNumeric) return null;

    const residual = normalizeSearchableText(semanticFilter.residualQuery).toLowerCase();
    if (residual) {
      const hasResidualMatch = searchableCorpus.some((segment) =>
        String(segment || '').toLowerCase().includes(residual)
      );
      if (!hasResidualMatch) return null;
    }
    return {
      item,
      title,
      matchSnippet: `${metricLabelForHistory(semanticFilter.metric)}: ${Math.round(metricValue)}`,
    };
  }

  const titleLower = title.toLowerCase();
  if (titleLower.includes(normalizedQuery)) {
    return { item, title, matchSnippet: title };
  }

  const matchedMessage = searchableCorpus.find((message) => message.toLowerCase().includes(normalizedQuery));
  if (!matchedMessage) return null;

  const lowerMessage = matchedMessage.toLowerCase();
  const matchIndex = lowerMessage.indexOf(normalizedQuery);
  const start = Math.max(0, matchIndex - 48);
  const end = Math.min(matchedMessage.length, matchIndex + normalizedQuery.length + 72);
  const prefix = start > 0 ? '...' : '';
  const suffix = end < matchedMessage.length ? '...' : '';
  const snippet = `${prefix}${matchedMessage.slice(start, end)}${suffix}`;

  return { item, title, matchSnippet: snippet };
}

// ============================================================================
// Sidebar State Reducer
// ============================================================================
const sidebarReducer = (state, action) => {
  switch (action.type) {
    case 'OPEN_HISTORY':
      return { ...state, history: true, readiness: false, settings: false, userDismissedReadiness: true };
    case 'OPEN_READINESS':
      return { ...state, history: false, readiness: true, settings: false };
    case 'OPEN_SETTINGS':
      return { ...state, history: false, readiness: false, settings: true };
    case 'CLOSE_HISTORY':
      return { ...state, history: false };
    case 'CLOSE_READINESS':
      return { ...state, readiness: false, userDismissedReadiness: true };
    case 'CLOSE_SETTINGS':
      return { ...state, settings: false };
    case 'CLOSE_ALL':
      return { ...state, history: false, readiness: false, settings: false };
    case 'TOGGLE_HISTORY':
      return { ...state, history: !state.history, readiness: false, settings: false };
    case 'TOGGLE_READINESS':
      return { ...state, history: false, readiness: !state.readiness, settings: false };
    case 'TOGGLE_SETTINGS':
      return { ...state, history: false, readiness: false, settings: !state.settings };
    case 'NEW_SESSION':
      return { ...state, userDismissedReadiness: false };
    default:
      return state;
  }
};

// --- Normalize any session/result into today's scorecard shape ---
function normalizeAnalysis(raw = {}) {
  const compat = raw.compat || {};
  const comps  = raw.component_scores || compat.components || {};
  const fin    = raw.financial_impact || compat.financials || {};

  const toInt = (v) => {
    const n = parseInt(Number(v), 10);
    return Number.isFinite(n) ? n : 0;
  };

  const score = toInt(raw.jaspen_score ?? raw.score ?? compat.score);
  const score_category =
    raw.score_category ||
    (score >= 80 ? 'Excellent' : score >= 60 ? 'Good' : score >= 40 ? 'Fair' : 'At Risk');

return {
  ...raw,  // Keep all original fields
  jaspen_score: score,
  score_category,
  component_scores: {
    financial_health:       toInt(comps.financial_health       ?? comps.financialHealth       ?? comps.financial   ?? comps.economics),
    operational_efficiency: toInt(comps.operational_efficiency ?? comps.operationalEfficiency ?? comps.execution   ?? comps.operations),
    market_position:        toInt(comps.market_position        ?? comps.marketPosition        ?? comps.market      ?? comps.strategy),
    execution_readiness:    toInt(comps.execution_readiness    ?? comps.executionReadiness    ?? comps.team        ?? comps.readiness),
  },
  financial_impact: {
    ebitda_at_risk:   fin.ebitda_at_risk   ?? fin.ebitdaAtRisk   ?? null,
    potential_loss:   fin.potential_loss   ?? fin.potentialLoss  ?? null,
    roi_opportunity:  fin.roi_opportunity  ?? fin.roiOpportunity ?? null,
    projected_ebitda: fin.projected_ebitda ?? fin.projectedEbitda?? null,
  },
  project_name: raw.project_name || compat.title || raw.title || 'Untitled Idea',
  risks: Array.isArray(raw.risks) ? raw.risks : (raw.top_risks || []),
  // Explicitly preserve detailed sections
  decision_framework: raw.decision_framework || raw.strategic_decision_framework || null,
  investment_analysis: raw.investment_analysis || null,
  npv_irr_analysis: raw.npv_irr_analysis || null,
  valuation: raw.valuation || null,
  before_after_financials: raw.before_after_financials || null,
};
}

function buildProjectScoreResult({
  baselineScorecard = null,
  snapshots = [],
  selectedScorecardId = null,
  ownerThreadId = '',
  existingResult = null,
  fallbackScorecard = null,
}) {
  const baselineSource =
    (baselineScorecard && typeof baselineScorecard === 'object' && Object.keys(baselineScorecard).length > 0
      ? baselineScorecard
      : null) ||
    (existingResult?._baseline_scorecard && typeof existingResult._baseline_scorecard === 'object'
      ? existingResult._baseline_scorecard
      : null) ||
    existingResult ||
    fallbackScorecard ||
    {};

  const normalizedBaseline = normalizeAnalysis(baselineSource);
  const baselineId = String(
    normalizedBaseline.analysis_id ||
    normalizedBaseline.id ||
    ownerThreadId ||
    ''
  ).trim();
  const canonicalSnapshots = buildMergedScorecardSnapshots({
    analysisResult: {
      ...normalizedBaseline,
      _baseline_scorecard: normalizedBaseline,
    },
    bundleBaselineScorecard: normalizedBaseline,
    baselineScorecardId: baselineId,
    scorecardSnapshots: snapshots,
    sessionId: ownerThreadId,
  });
  const nextSelectedId = String(
    selectedScorecardId ||
    baselineId ||
    ''
  ).trim() || null;

  return {
    ...(existingResult && typeof existingResult === 'object' ? existingResult : {}),
    ...normalizedBaseline,
    project_name:
      normalizedBaseline.project_name ||
      existingResult?.project_name ||
      fallbackScorecard?.project_name ||
      'Untitled Idea',
    _baseline_scorecard: normalizedBaseline,
    scorecard_snapshots: canonicalSnapshots,
    selected_scorecard_id: nextSelectedId,
    _owner_thread_id: String(
      ownerThreadId ||
      existingResult?._owner_thread_id ||
      normalizedBaseline._owner_thread_id ||
      ''
    ).trim() || undefined,
    thread_id: String(
      ownerThreadId ||
      existingResult?.thread_id ||
      normalizedBaseline.thread_id ||
      ''
    ).trim() || undefined,
  };
}

function normalizePlanKey(plan) {
  return String(plan || '').trim().toLowerCase();
}

function isSelfServePlan(plan) {
  return ['free', 'essential'].includes(normalizePlanKey(plan));
}

const SUPPORT_ROLE_SWITCH_OPTIONS = [
  { value: 'actual', label: 'Actual account', path: '/new' },
  { value: 'workspace:free', label: 'Personal · Free', path: '/new?admin_preview=workspace&plan_key=free' },
  { value: 'workspace:essential', label: 'Personal · Essential', path: '/new?admin_preview=workspace&plan_key=essential' },
  { value: 'workspace:team:viewer', label: 'Team · Viewer', path: '/new?admin_preview=workspace&plan_key=team&role=viewer' },
  { value: 'workspace:team:collaborator', label: 'Team · Collaborator', path: '/new?admin_preview=workspace&plan_key=team&role=collaborator' },
  { value: 'workspace:team:creator', label: 'Team · Creator', path: '/new?admin_preview=workspace&plan_key=team&role=creator' },
  { value: 'workspace:team:admin', label: 'Team · Admin', path: '/new?admin_preview=workspace&plan_key=team&role=admin' },
  { value: 'workspace:enterprise:viewer', label: 'Enterprise · Viewer', path: '/new?admin_preview=workspace&plan_key=enterprise&role=viewer' },
  { value: 'workspace:enterprise:collaborator', label: 'Enterprise · Collaborator', path: '/new?admin_preview=workspace&plan_key=enterprise&role=collaborator' },
  { value: 'workspace:enterprise:creator', label: 'Enterprise · Creator', path: '/new?admin_preview=workspace&plan_key=enterprise&role=creator' },
  { value: 'enterprise:admin', label: 'Enterprise · Admin', path: '/enterprise-admin?admin_preview=enterprise&role=admin' },
];
const MFA_ROLLOUT_TARGET_PLANS = new Set(['team', 'enterprise']);
const MFA_ROLLOUT_DISMISS_KEY_PREFIX = 'jas_mfa_rollout_banner_dismissed_v1';
const MFA_ROLLOUT_ENFORCE_AT = '2026-12-16T00:00:00Z';
const MFA_ROLLOUT_NOTICE_DATE_LABEL = 'December 15, 2026';
const LOW_CREDITS_DISMISS_KEY_PREFIX = 'jas_low_credits_banner_dismissed_v1';

function highestPlanKey(...plans) {
  return plans
    .map((plan) => normalizePlanKey(plan))
    .filter((plan) => Object.prototype.hasOwnProperty.call(PLAN_RANK, plan))
    .sort((a, b) => PLAN_RANK[b] - PLAN_RANK[a])[0] || 'free';
}

function resolveSupportRoleSwitchValue(location) {
  const params = new URLSearchParams(location.search);
  const previewType = String(params.get('admin_preview') || '').trim().toLowerCase();
  if (previewType === 'workspace') {
    const planKey = normalizePlanKey(params.get('plan_key'));
    if (!ADMIN_PREVIEW_PLAN_KEYS.has(planKey)) return 'actual';
    const role = String(params.get('role') || '').trim().toLowerCase();
    if (['team', 'enterprise'].includes(planKey) && ['viewer', 'collaborator', 'creator', 'admin'].includes(role)) {
      return `workspace:${planKey}:${role}`;
    }
    return `workspace:${planKey}`;
  }
  if (previewType === 'team' || previewType === 'enterprise') {
    const role = String(params.get('role') || '').trim().toLowerCase();
    if (role) return `${previewType}:${role}`;
  }
  return 'actual';
}

const WORKSPACE_TIPS = [
  {
    id: 'tip1',
    title: 'Start with your goal',
    body: 'Be specific — "Launch B2B SaaS for logistics" beats "build a startup". Jaspen builds a full strategy from your description.',
  },
  {
    id: 'tip2',
    title: 'Score before you plan',
    body: 'Run the Jaspen Score to validate viability across financial health, market position, and execution readiness.',
  },
  {
    id: 'tip3',
    title: 'Model what-if scenarios',
    body: 'Use the Scenarios tab to adjust cost, growth, and timeline levers and find your optimal path.',
  },
  {
    id: 'tip4',
    title: 'Generate your execution plan',
    body: 'Say "Build my project plan" after scoring to get a full WBS with tasks, owners, and milestones.',
  },
  {
    id: 'tip5',
    title: 'Connect your data sources',
    body: 'Link Snowflake or Salesforce in Data Sources to power AI recommendations from real operational data.',
  },
];

export default function JaspenWorkspace() {
  // View states: intake | summary | scenario | comparison | execution
  const [view, setView] = useState('intake');
  const [activeTab, setActiveTab] = useState('summary');

  const {
    user,
    logout,
    checkAuthStatus,
    updateDisplayName,
    updateUiPreferences,
    planCategory,
    isPlatformAdmin,
    isEnterpriseAdmin,
    canManageOrg,
    isOrgViewer,
    isOrgCollaborator,
    isOrgCreator,
  } = useAuth();
  const { toasts, showToast, dismissToast } = useToast();

  // Imperative control for scenario modeling (used by interactive chat actions)
  const scenarioModelerRef = useRef(null);

  const [sidebarState, dispatchSidebar] = useReducer(sidebarReducer, {
    history: false,
    readiness: false,
    settings: true,
    userDismissedReadiness: false
  });
  const didAutoOpenSettingsRef = useRef(false);
  const copyResetTimeoutRef = useRef(null);

  useEffect(() => {
    if (didAutoOpenSettingsRef.current) return;
    didAutoOpenSettingsRef.current = true;
    dispatchSidebar({ type: 'OPEN_SETTINGS' });
  }, []);

  useEffect(() => () => {
    if (copyResetTimeoutRef.current) {
      window.clearTimeout(copyResetTimeoutRef.current);
    }
  }, []);

  const [sessionId, setSessionId] = useState(null);
  const [currentSessionId, setCurrentSessionId] = useState(null);
  const [sessionsLoading, setSessionsLoading] = useState(true);
  const [messages, setMessages] = useState([]);

  // Readiness core state - SINGLE SOURCE OF TRUTH
  const [readinessAudit, setReadinessAudit] = useState(null); // ONLY source: GET /api/v1/readiness/audit (authoritative)
  const [collectedData, setCollectedData] = useState({});
  const READINESS_CIRC = 2 * Math.PI * 52; // r=52 -> circumference ~326.7

  const [input, setInput] = useState('');
  const [pendingFiles, setPendingFiles] = useState([]);
  const [sharedProjects, setSharedProjects] = useState([]);
  const [sharedProjectsLoading, setSharedProjectsLoading] = useState(false);
  const [strategyObjective, setStrategyObjective] = useState('balanced');
  const [objectiveExplicitlySet, setObjectiveExplicitlySet] = useState(false);

  const [busy, setBusy] = useState(false);
  const [isStreamingReply, setIsStreamingReply] = useState(false);
  const [regenerating, setRegenerating] = useState(false);
  const [undoingMutation, setUndoingMutation] = useState(false);
  const [streamToolStatus, setStreamToolStatus] = useState('');
  const manualProgressTimerRef = useRef(null);
  const [copiedMessageKey, setCopiedMessageKey] = useState(null);
  const [feedbackBusyKey, setFeedbackBusyKey] = useState(null);
  const [isRecording, setIsRecording] = useState(false);
  const [error, setError] = useState(null);
  const recognitionRef = useRef(null);
  const historySearchInputRef = useRef(null);

  const [analysisResult, setAnalysisResult] = useState(null);
  // Scenario results kept at the Workspace level (so Score tab can switch)
const [resultA, setResultA] = useState(null);
const [resultB, setResultB] = useState(null);
const [resultC, setResultC] = useState(null);
// Backend truth for macro categories + weights + version
const [readinessSpec, setReadinessSpec] = useState(null);   // full spec payload
const [specMap, setSpecMap] = useState({});                 // key -> {label, weight}
const [readinessSource, setReadinessSource] = useState(null); // "ml" or "heuristic"
const [readinessVersion, setReadinessVersion] = useState(null);

const clearManualProgressStatus = useCallback(() => {
  if (manualProgressTimerRef.current) {
    window.clearInterval(manualProgressTimerRef.current);
    manualProgressTimerRef.current = null;
  }
}, []);

const startManualProgressStatus = useCallback((steps = [], intervalMs = 2200) => {
  clearManualProgressStatus();
  const normalizedSteps = (Array.isArray(steps) ? steps : [])
    .map((step) => String(step || '').trim())
    .filter(Boolean);
  if (normalizedSteps.length === 0) {
    setStreamToolStatus('');
    return () => {};
  }
  let index = 0;
  setStreamToolStatus(normalizedSteps[index]);
  if (normalizedSteps.length > 1) {
    manualProgressTimerRef.current = window.setInterval(() => {
      index = Math.min(index + 1, normalizedSteps.length - 1);
      setStreamToolStatus(normalizedSteps[index]);
    }, Math.max(900, Number(intervalMs) || 2200));
  }
  return clearManualProgressStatus;
}, [clearManualProgressStatus]);

const applyPersistedReadinessSnapshot = useCallback((snapshot) => {
  const normalized = normalizeReadiness(snapshot);
  const hasMeaningfulReadiness = Boolean(
    normalized.percent > 0 ||
    normalized.categories.length > 0 ||
    normalized.items.length > 0 ||
    normalized.checklist_summary
  );
  if (!hasMeaningfulReadiness) return false;

  setReadinessAudit({
    overall: {
      percent: normalized.percent,
      source: 'persisted',
      heur_overall: normalized.percent,
    },
    categories: normalized.categories,
    items: normalized.items,
    checklist_summary: normalized.checklist_summary,
    version: normalized.version,
    objective_profile: normalized.objective_profile,
  });
  setReadinessSource('persisted');
  setReadinessVersion(normalized.version || readinessVersion || null);
  return true;
}, [readinessVersion]);

// Variant selector (Baseline, Scenario A/B/C)
const [scoreVariants, setScoreVariants] = useState([]);
const [selectedVariantId, setSelectedVariantId] = useState('baseline');
// Keep the list of selectable score variants in sync
useEffect(() => {
  const opts = [
    analysisResult ? { id: 'baseline',  label: 'Baseline',   result: analysisResult } : null,
    resultA        ? { id: 'scenarioA', label: 'Scenario A', result: resultA }        : null,
    resultB        ? { id: 'scenarioB', label: 'Scenario B', result: resultB }        : null,
    resultC        ? { id: 'scenarioC', label: 'Scenario C', result: resultC }        : null,
  ].filter(Boolean);

  setScoreVariants(opts);

  // if current selection vanished (e.g., cleared a scenario), default to Baseline
  const stillExists = opts.some(o => o.id === selectedVariantId);
  if (!stillExists) setSelectedVariantId('baseline');
}, [analysisResult, resultA, resultB, resultC]); 
useEffect(() => () => {
  clearManualProgressStatus();
}, [clearManualProgressStatus]);
const selectedVariant = useMemo(() => {
  return (
    scoreVariants.find(v => v.id === selectedVariantId)?.result ||
    analysisResult
  );
}, [scoreVariants, selectedVariantId, analysisResult]);

  const [analysisHistory, setAnalysisHistory] = useState([]);
  const [historySearch, setHistorySearch] = useState('');
  const [clearingHistory, setClearingHistory] = useState(false);
const [savedScenarios, setSavedScenarios] = useState([]);
  const [scenarioMutationVersion, setScenarioMutationVersion] = useState(0);
  const [wbsMutationVersion, setWbsMutationVersion] = useState(0);
  const [threadWbs, setThreadWbs] = useState(null);
  const [bundleLoading, setBundleLoading] = useState(false);
  const [wbsLoading, setWbsLoading] = useState(false);
  const [exportBusyType, setExportBusyType] = useState(null);
  const [savedStarterConfigs, setSavedStarterConfigs] = useState([]);
  const [startersLoading, setStartersLoading] = useState(false);
  const [selectedStarterId, setSelectedStarterId] = useState('');
  const [saveStarterModalOpen, setSaveStarterModalOpen] = useState(false);
  const [newStarterName, setNewStarterName] = useState('');
  const [newStarterDescription, setNewStarterDescription] = useState('');
  const [savingStarter, setSavingStarter] = useState(false);
  const [helpOpen, setHelpOpen] = useState(false);
  const [helpMessages, setHelpMessages] = useState([]);
const [helpInput, setHelpInput] = useState('');
const [helpLoading, setHelpLoading] = useState(false);
  const [confirmDialog, setConfirmDialog] = useState(null);
  const [commandPaletteOpen, setCommandPaletteOpen] = useState(false);
  const [commandQuery, setCommandQuery] = useState('');
  const commandPaletteInputRef = useRef(null);
  const workspaceTabRefs = useRef({});
// Score view dropdown state (baseline + up to 3 scenarios)
const [scenarioOptions, setScenarioOptions] = useState([]);
const [activeScenarioId, setActiveScenarioId] = useState('baseline');
const [scenarioDrawerView, setScenarioDrawerView] = useState('assistant');
const [aiWbsBusy, setAiWbsBusy] = useState(false);
const [pendingWbsConfirmation, setPendingWbsConfirmation] = useState(null);
  const [scenarioLevers, setScenarioLevers] = useState([]);
  const [leverCatalog, setLeverCatalog] = useState([]);
  const [scenarioOutputMetrics, setScenarioOutputMetrics] = useState([]);
  const [threadEditOpen, setThreadEditOpen] = useState(false);
  const [postAdoptWbsPrompt, setPostAdoptWbsPrompt] = useState(null);
  const [bundleCurrentScorecard, setBundleCurrentScorecard] = useState(null);
  const [bundleBaselineScorecard, setBundleBaselineScorecard] = useState(null);
  const hasHistory = analysisHistory.length > 0;
  const filteredAnalysisHistory = useMemo(() => {
    const query = normalizeSearchableText(historySearch);
    return analysisHistory
      .map((item) => buildHistorySearchRecord(item, query))
      .filter(Boolean);
  }, [analysisHistory, historySearch]);

  // PROMPT ALIGNMENT: Scorecard snapshots (baseline + adopted scenarios)
  const [scorecardSnapshots, setScorecardSnapshots] = useState([]);
  const [selectedScorecardId, setSelectedScorecardId] = useState(null);
  const [activeSnapshotId, setActiveSnapshotId] = useState(null);
  const [baselineScorecardId, setBaselineScorecardId] = useState(null);
  const [scorecardUndoStack, setScorecardUndoStack] = useState([]);
  const [scorecardRedoStack, setScorecardRedoStack] = useState([]);
  const [scorecardEditHistoryBusy, setScorecardEditHistoryBusy] = useState(false);

  useEffect(() => {
    setPendingWbsConfirmation(null);
  }, [currentSessionId, sessionId]);
  useEffect(() => {
    setScorecardUndoStack([]);
    setScorecardRedoStack([]);
  }, [currentSessionId, sessionId]);
  // Ensure we always have a baseline scorecard id + snapshot once analysisResult exists
  useEffect(() => {
    if (!analysisResult) return;

    const baselineSource =
      (analysisResult?._baseline_scorecard && typeof analysisResult._baseline_scorecard === 'object'
        ? analysisResult._baseline_scorecard
        : null) ||
      analysisResult;
    const baseId =
      baselineSource?.analysis_id ||
      baselineSource?.id ||
      baselineSource?.analysisId ||
      sessionId;
    if (!baseId) return;

    // If backend provided snapshots, hydrate them once
    const persistedRawSnaps = Array.isArray(analysisResult?.scorecard_snapshots)
      ? analysisResult.scorecard_snapshots
      : null;
    const persistedSnaps = persistedRawSnaps && persistedRawSnaps.length > 0
      ? buildMergedScorecardSnapshots({
          analysisResult,
          bundleBaselineScorecard: null,
          baselineScorecardId: baseId,
          scorecardSnapshots: persistedRawSnaps,
          sessionId: baseId,
        })
      : null;

    setBaselineScorecardId(baseId);

    setScorecardSnapshots((prev) => {
      if (persistedSnaps && persistedSnaps.length > 0) {
        return persistedSnaps;
      }

      if (Array.isArray(prev) && prev.length > 0) return prev;

      return [
        {
          ...baselineSource,
          id: baseId,
          label: 'Baseline',
          isBaseline: true,
          createdAt: Date.now(),
        },
      ];
    });

    // Select something sensible on load:
    // - if backend has snapshots and previously selected is missing, select baseline
    const persistedSelectedId = String(analysisResult?.selected_scorecard_id || '').trim();
    if (persistedSelectedId) {
      setActiveSnapshotId(persistedSelectedId);
      setSelectedScorecardId(persistedSelectedId);
      return;
    }
    if (persistedSnaps?.length) {
      const baseline = persistedSnaps.find((s) => s.isBaseline) || persistedSnaps[0];
      const fallbackId = baseline?.id || baseId;
      setSelectedScorecardId(fallbackId);
      return;
    }
    setSelectedScorecardId(baseId);
  }, [analysisResult, sessionId]);

  // Restore selected scorecard on refresh (if backend provided it)
  useEffect(() => {
    if (!analysisResult) return;
    if (analysisResult?.selected_scorecard_id) {
      setActiveSnapshotId(analysisResult.selected_scorecard_id);
    }
  }, [analysisResult]);

  const mergedScoreWorkspaceSnapshots = useMemo(() => buildMergedScorecardSnapshots({
    analysisResult,
    bundleBaselineScorecard,
    baselineScorecardId,
    scorecardSnapshots,
    sessionId,
  }), [analysisResult, baselineScorecardId, bundleBaselineScorecard, scorecardSnapshots, sessionId]);

  const effectiveSelectedScorecardId = useMemo(() => {
    const snapshotIds = new Set(
      mergedScoreWorkspaceSnapshots
        .map((snapshot) => String(snapshot?.id || snapshot?.analysis_id || '').trim())
        .filter(Boolean)
    );
    const selectedId = String(selectedScorecardId || '').trim();
    const activeId = String(activeSnapshotId || '').trim();
    const baselineId = String(baselineScorecardId || '').trim();

    if (selectedId && (snapshotIds.size === 0 || snapshotIds.has(selectedId))) {
      return selectedId;
    }
    if (activeId && (snapshotIds.size === 0 || snapshotIds.has(activeId))) {
      return activeId;
    }
    if (baselineId && (snapshotIds.size === 0 || snapshotIds.has(baselineId))) {
      return baselineId;
    }
    return selectedId || activeId || baselineId || '';
  }, [activeSnapshotId, baselineScorecardId, mergedScoreWorkspaceSnapshots, selectedScorecardId]);

const scoreWorkspace = useMemo(() => resolveScoreWorkspaceContext({
  analysisHistory,
  sessionId,
  currentSessionId,
  selectedScorecardId: effectiveSelectedScorecardId,
  baselineScorecardId,
  scorecardSnapshots,
  selectedVariant: mergedScoreWorkspaceSnapshots.length > 0 ? null : selectedVariant,
  analysisResult,
  bundleCurrentScorecard,
  bundleBaselineScorecard,
  view,
  activeTab,
}), [
  analysisHistory,
  sessionId,
  currentSessionId,
  effectiveSelectedScorecardId,
  scorecardSnapshots,
  selectedVariant,
  analysisResult,
  bundleCurrentScorecard,
  bundleBaselineScorecard,
  mergedScoreWorkspaceSnapshots.length,
  view,
  activeTab,
]);

const activeScorecard = scoreWorkspace.scorecard;
const editableThreadId = scoreWorkspace.ownerThreadId;
const activeScorecardId = scoreWorkspace.scorecardId;
const scoreWorkspaceMode = scoreWorkspace.mode;
const chatViewContext = useMemo(() => {
  const normalizeToken = (value) => String(value || '').trim().toLowerCase().replace(/\s+/g, '_').replace(/-/g, '_');
  const inferCurrentView = () => {
    const candidates = [view, activeTab];
    for (const candidate of candidates) {
      const token = normalizeToken(candidate);
      if (!token) continue;
      if (token === 'intake' || token === 'chat') return 'intake';
      if (token === 'summary' || token === 'score' || token === 'scorecard') return 'summary';
      if (token === 'scenario' || token === 'scenarios' || token === 'comparison') return 'scenario';
      if (token === 'execution' || token === 'execution_plan' || token === 'wbs' || token === 'timeline' || token === 'board' || token === 'list') return 'execution';
    }
    return 'intake';
  };

  const resolvedActiveTab = activeTab === 'scenario'
    ? normalizeToken(scenarioDrawerView || activeTab)
    : normalizeToken(activeTab || view || 'intake');

  const rawTasks = Array.isArray(threadWbs?.tasks) ? threadWbs.tasks : [];
  const byStatus = rawTasks.reduce((acc, task) => {
    const key = normalizeToken(task?.status || 'todo');
    if (key === 'todo' || key === 'in_progress' || key === 'blocked' || key === 'done') {
      acc[key] = (acc[key] || 0) + 1;
    }
    return acc;
  }, {});
  const wbsSummary = rawTasks.length > 0
    ? {
        total_tasks: rawTasks.length,
        by_status: byStatus,
      }
    : null;

  return {
    current_view: inferCurrentView(),
    active_tab: resolvedActiveTab || 'intake',
    active_scorecard_id: String(effectiveSelectedScorecardId || activeScorecardId || '').trim() || undefined,
    active_scenario_id: String(activeScenarioId || '').trim() || undefined,
    wbs_summary: wbsSummary || undefined,
  };
}, [
  view,
  activeTab,
  scenarioDrawerView,
  effectiveSelectedScorecardId,
  activeScorecardId,
  activeScenarioId,
  threadWbs,
]);

// Preserve the original/baseline analysis result for quick switching
const baselineRef = useRef(null);
  // GOAL B: Track which sessionIds have had their scorecard hydrated
  const hydratedScorecardRef = useRef(new Set());

  // Pull messages, latest analysis id, and saved scenarios from backend
const refreshBundle = async (tid) => {
  if (!tid) return;
  setBundleLoading(true);
  try {
    const bundle = await Jaspen.getThreadBundle(tid, { msg_limit: 50, scn_limit: 50 });

    // scenarios -> normalize to local shape used by ComparisonView / list
    const serverScenarios = Array.isArray(bundle.scenarios) ? bundle.scenarios : [];
    const normalized = serverScenarios.map((s) => ({
      id: s.scenario_id,
      label: s.label || 'Scenario',
      values: s.deltas || {},
      result: s.result || null,
      timestamp: new Date(s.created_at || Date.now()).getTime(),
    }));

    const bundleObjective = normalizeStrategyObjective(
      bundle?.strategy_objective || bundle?.thread?.strategy_objective || 'balanced'
    );
    setStrategyObjective(bundleObjective);

    setSavedScenarios(normalized);
    const bundleLeverCatalog = Array.isArray(bundle?.lever_catalog) ? bundle.lever_catalog : [];
    const bundleOutputMetrics = Array.isArray(bundle?.output_metrics) ? bundle.output_metrics : [];
    const bundleLevers = Array.isArray(bundle?.scenario_levers) ? bundle.scenario_levers : [];
    setLeverCatalog(bundleLeverCatalog);
    setScenarioOutputMetrics(bundleOutputMetrics);
    setScenarioLevers(bundleLevers);

    const currentScorecard = bundle?.current_scorecard || null;
    const baselineScorecard = bundle?.baseline_scorecard || null;
    const persistedSnapshots = Array.isArray(bundle?.scorecard_snapshots)
      ? bundle.scorecard_snapshots
      : [];
    setBundleCurrentScorecard(currentScorecard);
    setBundleBaselineScorecard(baselineScorecard);
    const scenarioScorecards = persistedSnapshots.length > 0
      ? []
      : serverScenarios
          .map((s) => s?.scorecard || s?.analysis_result || s?.result || null)
          .filter((s) => s && typeof s === 'object');

    // Always merge baseline into the snapshot list. When the backend returns
    // persistedSnapshots they may NOT include the baseline (it's stored
    // separately as _baseline_scorecard). Without this merge the Score
    // dropdown loses the Baseline option after a refresh.
    const bundleSnapshots = persistedSnapshots.length > 0
      ? buildMergedScorecardSnapshots({
          analysisResult: null,
          bundleBaselineScorecard: baselineScorecard,
          baselineScorecardId: baselineScorecard?.analysis_id || baselineScorecard?.id || tid,
          scorecardSnapshots: persistedSnapshots,
          sessionId: tid,
        })
      : buildScorecardSnapshots({
          threadId: tid,
          baselineScorecard,
          currentScorecard,
          scenarioScorecards,
        });

    const baselineId =
      baselineScorecard?.analysis_id ||
      baselineScorecard?.id ||
      baselineScorecard?.analysisId ||
      bundleSnapshots.find((snap) => snap?.isBaseline)?.id ||
      null;
    const bundleSelectedId = String(
      bundle?.selected_scorecard_id ||
      currentScorecard?.analysis_id ||
      currentScorecard?.id ||
      currentScorecard?.analysisId ||
      baselineId ||
      ''
    ).trim();

    if (bundleSnapshots.length > 0) {
      setScorecardSnapshots(bundleSnapshots);
    }
    if (baselineId) setBaselineScorecardId(baselineId);
    if (bundleSelectedId) {
      setActiveSnapshotId(bundleSelectedId);
      setSelectedScorecardId(bundleSelectedId);
    }

    const resolvedBaselineScorecard =
      (baselineScorecard && typeof baselineScorecard === 'object' && Object.keys(baselineScorecard).length > 0)
        ? baselineScorecard
        : bundleSnapshots.find((snap) => snap?.isBaseline) || null;
    const selectedBundleSnapshot = bundleSelectedId
      ? bundleSnapshots.find((snap) => String(snap?.id || snap?.analysis_id || '').trim() === bundleSelectedId)
      : null;
    const resolvedBundleScorecard =
      (selectedBundleSnapshot && hasMeaningfulScorecardData(selectedBundleSnapshot))
        ? selectedBundleSnapshot
        : (resolvedBaselineScorecard && hasMeaningfulScorecardData(resolvedBaselineScorecard))
        ? resolvedBaselineScorecard
        : (currentScorecard && hasMeaningfulScorecardData(currentScorecard))
          ? currentScorecard
          : null;

    if (hasMeaningfulScorecardData(resolvedBundleScorecard)) {
      const rootedScoreResult = buildProjectScoreResult({
        baselineScorecard: resolvedBaselineScorecard || resolvedBundleScorecard,
        snapshots: bundleSnapshots,
        selectedScorecardId: bundleSelectedId || baselineId || null,
        ownerThreadId: tid,
        existingResult: analysisResult,
        fallbackScorecard: resolvedBundleScorecard,
      });
      baselineRef.current = rootedScoreResult._baseline_scorecard;
      setAnalysisResult((prev) => {
        return {
          ...(prev && typeof prev === 'object' ? prev : {}),
          ...rootedScoreResult,
          _baseline_scorecard: rootedScoreResult._baseline_scorecard,
          scorecard_snapshots: rootedScoreResult.scorecard_snapshots,
          selected_scorecard_id: rootedScoreResult.selected_scorecard_id,
        };
      });
      if (view === 'intake') {
        setView('summary');
        setActiveTab('summary');
      }
    }

    const bundleMessages = toUiMessages(
      (Array.isArray(bundle?.messages) ? bundle.messages : []).map((m) => ({
        role: m?.role || (m?.sender === 'user' ? 'user' : 'assistant'),
        content: m?.content || m?.text || m?.message || '',
      }))
    );
    if ((messages?.length || 0) === 0 && bundleMessages.length > 0) {
      setMessages(bundleMessages);
    }
  } catch (e) {
    showToast(e?.message || 'We could not refresh this thread right now.', 'error', {
      actionLabel: 'Retry',
      onAction: () => {
        void refreshBundle(tid);
      },
    });
  } finally {
    setBundleLoading(false);
  }
};

const refreshThreadWbs = useCallback(async (tid) => {
  if (!tid) return null;
  setWbsLoading(true);
  try {
    const response = await Jaspen.getThreadWbs(tid);
    const nextWbs = (response?.project_wbs && typeof response.project_wbs === 'object')
      ? response.project_wbs
      : null;
    setThreadWbs(nextWbs);
    return nextWbs;
  } catch (e) {
    showToast(e?.message || 'We could not refresh the execution plan right now.', 'error', {
      actionLabel: 'Retry',
      onAction: () => {
        void refreshThreadWbs(tid);
      },
    });
    return null;
  } finally {
    setWbsLoading(false);
  }
}, [showToast]);

const normalizeMutationResults = (payload) => {
  if (!payload || typeof payload !== 'object') return [];

  const out = [];
  const seen = new Set();
  const pushMutation = (entry) => {
    if (!entry || typeof entry !== 'object') return;
    const result = entry.result && typeof entry.result === 'object' ? entry.result : {};
    const tool = String(
      entry.tool ||
      entry.name ||
      entry?.result?.tool ||
      entry?.result_summary?.tool ||
      ''
    ).trim();
    if (!tool) return;

    const success = typeof entry.success === 'boolean'
      ? entry.success
      : (typeof result.success === 'boolean'
        ? result.success
        : (typeof result.ok === 'boolean'
          ? result.ok
          : !(entry.error || result.error)));

    const normalized = {
      tool,
      success,
      result_summary: entry.result_summary || result || {},
      error: entry.error || result.error || null,
      code: entry.code || result.code || null,
    };

    const sig = `${normalized.tool}:${JSON.stringify(normalized.result_summary || {})}`;
    if (seen.has(sig)) return;
    seen.add(sig);
    out.push(normalized);
  };

  const directMutations = Array.isArray(payload.mutations) ? payload.mutations : [];
  const toolResults = Array.isArray(payload.tool_results)
    ? payload.tool_results
    : (Array.isArray(payload.toolResults) ? payload.toolResults : []);
  const actionRows = Array.isArray(payload.actions) ? payload.actions : [];

  directMutations.forEach(pushMutation);
  toolResults.forEach(pushMutation);
  actionRows.forEach(pushMutation);

  return out;
};

const renderConversationMessage = (message) => {
  const text = String(message?.text || '');
  if (message?.role === 'user') return text;

  return (
    <ReactMarkdown
      remarkPlugins={[remarkGfm]}
      components={{
        p: ({ children }) => <p className="jas-md-paragraph">{children}</p>,
        pre: ({ children }) => <pre className="jas-md-pre">{children}</pre>,
        code: ({ inline, className, children, ...props }) => (
          inline ? (
            <code className={`jas-md-inline-code ${className || ''}`.trim()} {...props}>{children}</code>
          ) : (
            <code className={`jas-md-code ${className || ''}`.trim()} {...props}>{children}</code>
          )
        ),
        ul: ({ children }) => <ul className="jas-md-list">{children}</ul>,
        ol: ({ children }) => <ol className="jas-md-list jas-md-list-ordered">{children}</ol>,
        table: ({ children }) => <div className="jas-md-table-wrap"><table className="jas-md-table">{children}</table></div>,
        a: ({ children, ...props }) => <a {...props} target="_blank" rel="noreferrer">{children}</a>,
      }}
    >
      {text}
    </ReactMarkdown>
  );
};

const renderMessageAttachments = (message) => {
  if (!Array.isArray(message?.attachments) || message.attachments.length === 0) return null;
  return (
    <div className="message-attachments">
      {message.attachments.map((attachment, index) => {
        const isImage = attachment?.preview && String(attachment?.type || '').startsWith('image/');
        return (
          <div key={`${attachment?.name || 'attachment'}-${index}`} className="message-attachment">
            {isImage ? (
              <img
                className="attachment-thumb"
                src={attachment.preview}
                alt={attachment?.name ? `Attachment preview: ${attachment.name}` : 'Attachment preview'}
                onLoad={() => {
                  try { if (attachment.preview?.startsWith?.('blob:')) URL.revokeObjectURL(attachment.preview); } catch {}
                }}
              />
            ) : (
              <span className="attachment-link" title={attachment?.name}>{attachment?.name}</span>
            )}
            <span className="attachment-meta">
              {Math.max(1, Math.round((attachment?.size || 0) / 1024))} KB
            </span>
          </div>
        );
      })}
      <div className="attachments-caption">
        Attached {message.attachments.length} {message.attachments.length === 1 ? 'file' : 'files'}
      </div>
    </div>
  );
};

const copyTextToClipboard = async (text) => {
  const normalized = String(text || '');
  if (!normalized) return;
  if (navigator?.clipboard?.writeText) {
    await navigator.clipboard.writeText(normalized);
    return;
  }
  const textarea = document.createElement('textarea');
  textarea.value = normalized;
  textarea.setAttribute('readonly', 'readonly');
  textarea.style.position = 'absolute';
  textarea.style.left = '-9999px';
  document.body.appendChild(textarea);
  textarea.select();
  document.execCommand('copy');
  document.body.removeChild(textarea);
};

const handleCopyMessage = async (messageKey, text) => {
  try {
    await copyTextToClipboard(text);
    setCopiedMessageKey(messageKey);
    if (copyResetTimeoutRef.current) {
      window.clearTimeout(copyResetTimeoutRef.current);
    }
    copyResetTimeoutRef.current = window.setTimeout(() => {
      setCopiedMessageKey((current) => (current === messageKey ? null : current));
    }, 1600);
  } catch (copyError) {
    showToast('Failed to copy message.', 'error');
  }
};

const handleCopyInviteLink = async () => {
  if (!inviteLink) {
    showToast('Invite link is not ready yet.', 'info');
    return;
  }
  try {
    await copyTextToClipboard(inviteLink);
    showToast('Copied your invite link.', 'success');
  } catch (copyError) {
    showToast('Failed to copy invite link.', 'error');
  }
};

const renderMessageActions = (message, messageKey, idx, total) => {
  if (message?.role === 'user') return null;
  const isCopied = copiedMessageKey === messageKey;
  const canFeedback = Number.isInteger(message?.historyIndex) && Boolean(activeThreadId);
  const isLatestAssistant = idx === total - 1;
  const feedbackKey = `${messageKey}:feedback`;
  const isFeedbackBusy = feedbackBusyKey === feedbackKey;
  const canRegenerate = Boolean(activeThreadId)
    && isLatestAssistant
    && !isStreamingReply
    && !busy
    && !regenerating
    && !message?.streaming
    && !message?.hasMutations
    && !(message?.text || '').includes('Applied changes:');
  const canUndoMutation = Boolean(activeThreadId)
    && isLatestAssistant
    && !isStreamingReply
    && !busy
    && !regenerating
    && !undoingMutation
    && !message?.streaming
    && Boolean(message?.hasMutations)
    && Boolean(message?.canUndo);
  return (
    <div className="jas-message-actions">
      <button
        type="button"
        className={`jas-message-copy-btn ${isCopied ? 'is-copied' : ''}`}
        onClick={() => handleCopyMessage(messageKey, message?.text || '')}
        aria-label={isCopied ? 'Copied message' : 'Copy message'}
        title={isCopied ? 'Copied' : 'Copy'}
      >
        <FontAwesomeIcon icon={isCopied ? faCheck : faCopy} />
      </button>
      <button
        type="button"
        className={`jas-message-feedback-btn ${message?.feedbackValue === 'up' ? 'is-active' : ''}`}
        onClick={async () => {
          if (!canFeedback || isFeedbackBusy) return;
          setFeedbackBusyKey(feedbackKey);
          try {
            await Jaspen.messageFeedback(activeThreadId, message.historyIndex, 'up');
            setMessages((prev) => prev.map((entry) => (
              entry?.historyIndex === message.historyIndex ? { ...entry, feedbackValue: 'up' } : entry
            )));
            showToast('Feedback saved.', 'success');
          } catch (feedbackError) {
            showToast('Failed to save feedback.', 'error');
          } finally {
            setFeedbackBusyKey((current) => (current === feedbackKey ? null : current));
          }
        }}
        aria-label="Thumbs up"
        title="Thumbs up"
        disabled={!canFeedback || isFeedbackBusy} aria-disabled={!canFeedback || isFeedbackBusy}
      >
        <FontAwesomeIcon icon={faThumbsUp} />
      </button>
      <button
        type="button"
        className={`jas-message-feedback-btn ${message?.feedbackValue === 'down' ? 'is-active is-negative' : ''}`}
        onClick={async () => {
          if (!canFeedback || isFeedbackBusy) return;
          setFeedbackBusyKey(feedbackKey);
          try {
            await Jaspen.messageFeedback(activeThreadId, message.historyIndex, 'down');
            setMessages((prev) => prev.map((entry) => (
              entry?.historyIndex === message.historyIndex ? { ...entry, feedbackValue: 'down' } : entry
            )));
            showToast('Feedback saved.', 'success');
          } catch (feedbackError) {
            showToast('Failed to save feedback.', 'error');
          } finally {
            setFeedbackBusyKey((current) => (current === feedbackKey ? null : current));
          }
        }}
        aria-label="Thumbs down"
        title="Thumbs down"
        disabled={!canFeedback || isFeedbackBusy} aria-disabled={!canFeedback || isFeedbackBusy}
      >
        <FontAwesomeIcon icon={faThumbsDown} />
      </button>
      {canRegenerate && (
        <button
          type="button"
          className="jas-message-regen-btn"
          onClick={regenerateLastResponse}
          aria-label="Regenerate response"
          title="Regenerate"
          disabled={regenerating} aria-disabled={regenerating}
        >
          <FontAwesomeIcon icon={faRotate} />
        </button>
      )}
      {canUndoMutation && (
        <button
          type="button"
          className="jas-message-undo-btn"
          onClick={undoLastMutationTurn}
          aria-label="Undo changes"
          title="Undo changes"
          disabled={undoingMutation} aria-disabled={undoingMutation}
        >
          <FontAwesomeIcon icon={faClockRotateLeft} />
        </button>
      )}
    </div>
  );
};

const applyMutationRefreshes = async (payload, fallbackThreadId = null) => {
  const mutations = normalizeMutationResults(payload);
  if (!mutations.length) return;

  let scenarioChanged = false;
  let wbsChanged = false;
  let threadRenamed = false;
  mutations.forEach((mutation) => {
    const tool = String(mutation?.tool || '').trim();
    const success = mutation?.success !== false;
    if (!success) return;
    if (tool === 'create_scenario') {
      scenarioChanged = true;
    }
    if (['update_wbs_task', 'add_wbs_task', 'add_wbs_dependency', 'remove_wbs_task', 'generate_execution_plan'].includes(tool)) {
      wbsChanged = true;
    }
    if (tool === 'rename_thread') {
      threadRenamed = true;
    }
  });

  if (!scenarioChanged && !wbsChanged && !threadRenamed) return;

  const threadIdForRefresh = String(
    payload?.thread_id ||
    payload?.session_id ||
    payload?.sessionId ||
    fallbackThreadId ||
    currentSessionId ||
    sessionId ||
    ''
  ).trim();
  if (!threadIdForRefresh) return;

  if (scenarioChanged) setScenarioMutationVersion((prev) => prev + 1);
  if (wbsChanged) setWbsMutationVersion((prev) => prev + 1);

  await refreshBundle(threadIdForRefresh);
};

useEffect(() => {
  if (wbsMutationVersion <= 0) return;
  const tid = String(currentSessionId || sessionId || '').trim();
  if (!tid) return;
  refreshThreadWbs(tid);
}, [wbsMutationVersion, currentSessionId, sessionId, refreshThreadWbs]);

  const navigate = useNavigate();
  const location = useLocation();
  const requestedTab = useMemo(() => {
    const params = new URLSearchParams(location.search);
    const tab = String(params.get('tab') || '').trim().toLowerCase();
    if (['summary', 'scenario', 'comparison', 'execution'].includes(tab)) return tab;
    return '';
  }, [location.search]);

  useEffect(() => {
    const prefill = location.state?.prefillMessage;
    if (prefill && typeof prefill === 'string' && prefill.trim()) {
      setInput(prefill.trim());
      navigate(location.pathname + location.search, { replace: true, state: {} });
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);
  const handleUnauthorized = useCallback(async () => {
    const status = await checkAuthStatus({ silent: true });
    if (!status?.authenticated) {
      navigate('/?auth=1', { replace: true });
    }
  }, [checkAuthStatus, navigate]);

  useEffect(() => {
    if (!requestedTab) return;
    if (requestedTab === 'execution') {
      const params = new URLSearchParams(location.search);
      const sid = String(params.get('sid') || params.get('session_id') || '').trim();
      if (!sid) return;
      const nextParams = new URLSearchParams();
      nextParams.set('sid', sid);
      ['admin_preview', 'plan_key', 'role'].forEach((key) => {
        const value = String(params.get(key) || '').trim();
        if (value) nextParams.set(key, value);
      });
      navigate(`/execution-plan?${nextParams.toString()}`, { replace: true });
      return;
    }
    if (requestedTab === 'summary') {
      setActiveTab('summary');
      setView('summary');
      return;
    }
    if (requestedTab === 'scenario') {
      setActiveTab('scenario');
      setView('scenario');
      return;
    }
    if (requestedTab === 'comparison') {
      setActiveTab('scenario');
      setView('comparison');
    }
  }, [requestedTab, location.search, navigate]);

  const authFetch = useCallback((url, options = {}) => {
    const apiBase = API_BASE;
    const fullUrl = url.startsWith('http') ? url : `${apiBase}${url}`;
    return cookieAuthFetch(fullUrl, { credentials: 'include', ...options });
  }, []);

  const getUserStorageKeys = (u) => {
    const keys = [];
    if (u?.id) keys.push(`jaspen_display_name_id_${u.id}`);
    if (u?.email) keys.push(`jaspen_display_name_email_${String(u.email).toLowerCase()}`);
    keys.push('jaspen_display_name_last');
    return keys;
  };
  const [displayName, setDisplayName] = useState('');
  const [nameInput, setNameInput] = useState('');
  const [nameModalOpen, setNameModalOpen] = useState(false);
  const [nameModalMode, setNameModalMode] = useState('required');
  const [nameSaving, setNameSaving] = useState(false);
  const [nameError, setNameError] = useState('');
  const [billingStatus, setBillingStatus] = useState(null);
  const [billingCatalog, setBillingCatalog] = useState({ plans: {}, overage_packs: {}, model_types: {} });
  const [selectedModelType, setSelectedModelType] = useState('pluto');
  const [modelMenuOpen, setModelMenuOpen] = useState(false);
  const [billingLoading, setBillingLoading] = useState(true);
  const [billingMessage, setBillingMessage] = useState('');
  const [billingActionLoading, setBillingActionLoading] = useState('');
  const [billingModalOpen, setBillingModalOpen] = useState(false);
  const [mfaRolloutBannerDismissed, setMfaRolloutBannerDismissed] = useState(false);
  const [lowCreditsBannerDismissed, setLowCreditsBannerDismissed] = useState(false);
  const [batchIdeasOpen, setBatchIdeasOpen] = useState(false);
  const [onboardingOpen, setOnboardingOpen] = useState(false);
  const [onboardingMode, setOnboardingMode] = useState('entry');
  const [onboardingInitialSelection, setOnboardingInitialSelection] = useState(null);
  const [pendingOnboardingContext, setPendingOnboardingContext] = useState(null);
  const [onboardingLaunchLabel, setOnboardingLaunchLabel] = useState('');
  const [guidedFlowDismissed, setGuidedFlowDismissed] = useState(false);
  const [notificationsOpen, setNotificationsOpen] = useState(false);
  const [notificationsMode, setNotificationsMode] = useState('bell');
  const [notificationFeed, setNotificationFeed] = useState(() => buildDefaultNotifications());
  const [bellNotificationIds, setBellNotificationIds] = useState(() =>
    buildDefaultNotifications().map((item) => item.id)
  );
  const [threadUsage, setThreadUsage] = useState(null);
  const [threadUsageLoading, setThreadUsageLoading] = useState(false);
  const [threadUsageError, setThreadUsageError] = useState('');
  const [scoreShellMenu, setScoreShellMenu] = useState(null);
  const scoreShellMenuRef = useRef(null);
  const savedEmail = (() => {
    try { return localStorage.getItem('jaspen_last_email'); } catch { return null; }
  })();
  const userName = displayName || user?.name || user?.email?.split('@')[0] || savedEmail?.split?.('@')[0] || 'User';
  const inviteCode = String(user?.referral_code || '').trim();
  const inviteLink = buildInviteLink(inviteCode);
  const inviteDisplay = buildInviteDisplay(inviteCode);
  const adminWorkspacePreviewPlan = useMemo(() => {
    if (!Boolean(user?.is_admin)) return '';
    const params = new URLSearchParams(location.search);
    if (String(params.get('admin_preview') || '').trim().toLowerCase() !== 'workspace') return '';
    const planKey = String(params.get('plan_key') || '').trim().toLowerCase();
    return ADMIN_PREVIEW_PLAN_KEYS.has(planKey) ? planKey : '';
  }, [location.search, user?.is_admin]);
  const adminPreviewRole = useMemo(() => {
    if (!isPlatformAdmin || !['team', 'enterprise'].includes(adminWorkspacePreviewPlan)) return null;
    const params = new URLSearchParams(location.search);
    const role = String(params.get('role') || '').trim().toLowerCase();
    return ['viewer', 'collaborator', 'creator', 'admin'].includes(role) ? role : null;
  }, [adminWorkspacePreviewPlan, isPlatformAdmin, location.search]);
  const notificationsStorageKey = useMemo(() => {
    if (user?.id) return `jaspen_notifications_id_${user.id}`;
    if (user?.email) return `jaspen_notifications_email_${String(user.email).toLowerCase()}`;
    return 'jaspen_notifications_last';
  }, [user?.id, user?.email]);
  const [welcomeNow, setWelcomeNow] = useState(() => new Date());
  const plans = billingCatalog?.plans || {};
  const modelTypes = useMemo(() => billingCatalog?.model_types || {}, [billingCatalog]);
  const currentPlanKey = String(billingStatus?.plan_key || 'free').toLowerCase();
  const effectivePlanKey = adminWorkspacePreviewPlan || highestPlanKey(
    currentPlanKey,
    user?.active_organization_plan_key,
    user?.subscription_plan,
  );
  const mfaRolloutPlanKey = highestPlanKey(
    user?.active_organization_plan_key,
    user?.subscription_plan,
  );
  const mfaRolloutEnforced = Date.now() >= Date.parse(MFA_ROLLOUT_ENFORCE_AT);
  const mfaRolloutEligible = (
    MFA_ROLLOUT_TARGET_PLANS.has(mfaRolloutPlanKey)
    && !Boolean(user?.mfa_enabled)
    && !mfaRolloutEnforced
  );
  const mfaRolloutDismissStorageKey = useMemo(() => {
    const owner = String(user?.id || user?.email || '').trim().toLowerCase();
    if (!owner) return '';
    return `${MFA_ROLLOUT_DISMISS_KEY_PREFIX}:${owner}:2026-12-15`;
  }, [user?.email, user?.id]);
  const previewPlanCategory = effectivePlanKey === 'enterprise'
    ? 'enterprise'
    : effectivePlanKey === 'team'
    ? 'team'
    : 'individual';
  const currentPlanLabel = plans[currentPlanKey]?.label || (currentPlanKey[0]?.toUpperCase() + currentPlanKey.slice(1));
  const supportRoleSwitchValue = useMemo(
    () => resolveSupportRoleSwitchValue(location),
    [location]
  );
  const customerPreviewActive = Boolean(isPlatformAdmin && supportRoleSwitchValue !== 'actual');
  const footerPlanKey = customerPreviewActive ? effectivePlanKey : (
    planCategory === 'enterprise'
      ? 'enterprise'
      : planCategory === 'team'
      ? 'team'
      : currentPlanKey
  );
  const footerPlanLabel = plans[footerPlanKey]?.label || (footerPlanKey[0]?.toUpperCase() + footerPlanKey.slice(1));
  const adminWorkspacePreviewActive = Boolean(adminWorkspacePreviewPlan);

  useEffect(() => {
    if (!mfaRolloutDismissStorageKey || !mfaRolloutEligible) {
      setMfaRolloutBannerDismissed(false);
      return;
    }
    try {
      setMfaRolloutBannerDismissed(localStorage.getItem(mfaRolloutDismissStorageKey) === '1');
    } catch {
      setMfaRolloutBannerDismissed(false);
    }
  }, [mfaRolloutDismissStorageKey, mfaRolloutEligible]);

  const dismissMfaRolloutBanner = useCallback(() => {
    if (!mfaRolloutDismissStorageKey) {
      setMfaRolloutBannerDismissed(true);
      return;
    }
    try {
      localStorage.setItem(mfaRolloutDismissStorageKey, '1');
    } catch {
      // no-op
    }
    setMfaRolloutBannerDismissed(true);
  }, [mfaRolloutDismissStorageKey]);
  const toolEntitlements = useMemo(
    () => (Array.isArray(billingStatus?.tool_entitlements) ? billingStatus.tool_entitlements : []),
    [billingStatus]
  );
  const toolEntitlementById = useMemo(() => {
    const map = {};
    toolEntitlements.forEach((tool) => {
      const id = String(tool?.id || '').trim();
      if (id) map[id] = tool;
    });
    return map;
  }, [toolEntitlements]);
  const fallbackMinPlanByTool = useMemo(() => ({
    scenario_create: 'essential',
    scenario_apply: 'essential',
    scenario_adopt: 'essential',
    wbs_read: 'essential',
    wbs_write: 'essential',
    jira_sync: 'team',
    workfront_sync: 'team',
    smartsheet_sync: 'team',
    salesforce_insights: 'enterprise',
    snowflake_insights: 'enterprise',
    oracle_fusion_insights: 'enterprise',
    servicenow_insights: 'enterprise',
    netsuite_insights: 'enterprise',
  }), []);
  const canUseTool = useCallback((toolId, mode = 'read') => {
    const entry = toolEntitlementById[String(toolId || '').trim()];
    if (entry) {
      if (String(mode || 'read').toLowerCase() === 'write') return Boolean(entry.allowed_write);
      return Boolean(entry.allowed_read);
    }

    // Fallback while status payload is loading or if backend omits entitlement data.
    const minPlan = fallbackMinPlanByTool[String(toolId || '').trim()];
    const minRank = PLAN_RANK[minPlan] ?? Number.MAX_SAFE_INTEGER;
    const curRank = PLAN_RANK[currentPlanKey] ?? 0;
    return curRank >= minRank;
  }, [toolEntitlementById, fallbackMinPlanByTool, currentPlanKey]);
  const canUseScenarios = canUseTool('scenario_create', 'write');
  const canUseWbsWrite = canUseTool('wbs_write', 'write');
  const effectiveCanManageOrg = adminPreviewRole ? adminPreviewRole === 'admin' : canManageOrg;
  const effectiveIsViewer = adminPreviewRole ? adminPreviewRole === 'viewer' : isOrgViewer;
  const effectiveIsCollaborator = adminPreviewRole ? adminPreviewRole === 'collaborator' : isOrgCollaborator;
  const effectiveIsCreator = adminPreviewRole
    ? ['admin', 'creator'].includes(adminPreviewRole)
    : isOrgCreator;
  const canStartOrgProjects = previewPlanCategory === 'individual' || effectiveIsCreator || (isPlatformAdmin && !customerPreviewActive);
  const canAccessExecutionTab = (isPlatformAdmin && !customerPreviewActive) || PLAN_RANK[effectivePlanKey] >= PLAN_RANK.essential;
  const canEditExecutionFields = canAccessExecutionTab && canUseWbsWrite && (
    previewPlanCategory === 'individual' ||
    effectiveIsCreator ||
    effectiveIsCollaborator ||
    (isPlatformAdmin && !customerPreviewActive)
  );
  const canEditExecutionStructure = canAccessExecutionTab && canUseWbsWrite && (
    previewPlanCategory === 'individual' ||
    effectiveIsCreator ||
    (isPlatformAdmin && !customerPreviewActive)
  );
  const canEditExecutionDependencies = canEditExecutionStructure;
  const showRealTeam = !isPlatformAdmin && effectiveCanManageOrg;
  const showLockedTeam = previewPlanCategory === 'individual' && (!isPlatformAdmin || customerPreviewActive);
  const showRealDashboard = previewPlanCategory !== 'individual' || (isPlatformAdmin && !customerPreviewActive);
  const showLockedDashboard = previewPlanCategory === 'individual' && (!isPlatformAdmin || customerPreviewActive);
  const showRealInsights = (isPlatformAdmin && !customerPreviewActive) || PLAN_RANK[effectivePlanKey] >= PLAN_RANK.team;
  const showLockedInsights = !showRealInsights;
  const showRealReports = (isPlatformAdmin && !customerPreviewActive) || PLAN_RANK[effectivePlanKey] >= PLAN_RANK.team;
  const showLockedReports = !showRealReports;
  const showRealActivity = (isPlatformAdmin && !customerPreviewActive) || PLAN_RANK[effectivePlanKey] >= PLAN_RANK.essential;
  const showLockedActivity = !showRealActivity;
  const showRealConnectors = (isPlatformAdmin && !customerPreviewActive) || PLAN_RANK[effectivePlanKey] >= PLAN_RANK.essential;
  const showLockedConnectors = !showRealConnectors;
  const canExportScorecardPdf = (isPlatformAdmin && !customerPreviewActive) || PLAN_RANK[effectivePlanKey] >= PLAN_RANK.essential;
  const canExportScorecardPptx = (isPlatformAdmin && !customerPreviewActive) || PLAN_RANK[effectivePlanKey] >= PLAN_RANK.team;
  const canExportWbsCsv = (isPlatformAdmin && !customerPreviewActive) || PLAN_RANK[effectivePlanKey] >= PLAN_RANK.team;
  const canExportConversationPdf = (isPlatformAdmin && !customerPreviewActive) || PLAN_RANK[effectivePlanKey] >= PLAN_RANK.essential;
  const canExportConversationMarkdown = true;
  const batchIdeasPlanUnlocked = (isPlatformAdmin && !customerPreviewActive) || PLAN_RANK[effectivePlanKey] >= PLAN_RANK.team;
  const batchIdeasRoleUnlocked = previewPlanCategory !== 'individual' && (
    effectiveIsCreator || (isPlatformAdmin && !customerPreviewActive)
  );
  const canUseBatchIdeas = batchIdeasPlanUnlocked && batchIdeasRoleUnlocked;
  const batchIdeasLocked = !canUseBatchIdeas;
  const batchIdeasLockReason = !batchIdeasPlanUnlocked
    ? 'plan'
    : !batchIdeasRoleUnlocked
    ? 'role'
    : null;
  const connectorsManagePath = adminWorkspacePreviewPlan
    ? `/connectors-manage?admin_preview=workspace&plan_key=${encodeURIComponent(adminWorkspacePreviewPlan)}${adminPreviewRole ? `&role=${encodeURIComponent(adminPreviewRole)}` : ''}`
    : '/connectors-manage';
  const monthlyCreditLimit = billingStatus?.monthly_credit_limit;
  const creditsRemaining = billingStatus?.credits_remaining;
  const monthlyCreditsUsed = billingStatus?.credits_used;
  const resolvedMonthlyCreditsUsed = useMemo(() => {
    const direct = Number(monthlyCreditsUsed);
    if (Number.isFinite(direct)) return Math.max(0, direct);

    const limitNum = Number(monthlyCreditLimit);
    const remainingNum = Number(creditsRemaining);
    if (Number.isFinite(limitNum) && Number.isFinite(remainingNum)) {
      return Math.max(0, limitNum - remainingNum);
    }
    return null;
  }, [monthlyCreditsUsed, monthlyCreditLimit, creditsRemaining]);
  const monthlyUsagePercent = useMemo(() => {
    const limitNum = Number(monthlyCreditLimit);
    if (!Number.isFinite(limitNum) || limitNum <= 0 || resolvedMonthlyCreditsUsed == null) return null;
    return Math.max(0, Math.min(100, Math.round((resolvedMonthlyCreditsUsed / limitNum) * 100)));
  }, [monthlyCreditLimit, resolvedMonthlyCreditsUsed]);
  const creditDisplayTier = useMemo(() => {
    if (effectivePlanKey === 'enterprise') return 'enterprise';
    if (effectivePlanKey === 'team') return 'team';
    if (effectivePlanKey === 'essential') return 'essential';
    return 'free';
  }, [effectivePlanKey]);
  const intakeCreditsValue = useMemo(() => {
    const remaining = Number(creditsRemaining);
    if (Number.isFinite(remaining)) return Math.max(0, Math.round(remaining));
    const monthly = Number(monthlyCreditLimit);
    if (Number.isFinite(monthly)) return Math.max(0, Math.round(monthly));
    return null;
  }, [creditsRemaining, monthlyCreditLimit]);
  const intakeCreditsCompactLabel = useMemo(() => {
    if (billingLoading) return '...';
    if (creditDisplayTier === 'enterprise') return 'Contracted';
    if (creditsRemaining == null && monthlyCreditLimit == null) return '∞';

    const remainingNum = Number(intakeCreditsValue);
    const limitNum = Number(monthlyCreditLimit);
    const remainingLabel = Number.isFinite(remainingNum) ? Number(remainingNum).toLocaleString() : '--';
    if (!Number.isFinite(limitNum) || limitNum <= 0) return remainingLabel;
    const limitLabel = Math.round(limitNum).toLocaleString();

    if (creditDisplayTier === 'team') {
      return `Pool ${remainingLabel}/${limitLabel}`;
    }
    return `${remainingLabel}/${limitLabel}`;
  }, [billingLoading, creditDisplayTier, creditsRemaining, monthlyCreditLimit, intakeCreditsValue]);
  const creditsTone = useMemo(() => {
    if (creditDisplayTier === 'enterprise') return 'normal';
    const remainingNum = Number(creditsRemaining);
    const limitNum = Number(monthlyCreditLimit);
    if (!Number.isFinite(remainingNum) || !Number.isFinite(limitNum) || limitNum <= 0) {
      return 'normal';
    }
    const ratio = Math.max(0, remainingNum / limitNum);
    if (ratio <= 0.05) return 'critical';
    if (ratio <= 0.2) return 'warning';
    return 'normal';
  }, [creditDisplayTier, creditsRemaining, monthlyCreditLimit]);
  const creditsTitle = creditDisplayTier === 'enterprise'
    ? 'View contracted usage'
    : creditsTone === 'critical'
      ? 'Critical: credits are below 5%. Open billing.'
      : creditsTone === 'warning'
        ? 'Low credits: below 20%. Open billing.'
        : 'View account credits';
  const creditsBadge = creditsRemaining == null ? 'Contracted' : Number(creditsRemaining || 0).toLocaleString();
  const lowCreditsCycleKey = useMemo(() => {
    const now = new Date();
    const y = now.getUTCFullYear();
    const m = String(now.getUTCMonth() + 1).padStart(2, '0');
    return `${y}-${m}`;
  }, []);
  const lowCreditsDismissStorageKey = useMemo(() => {
    const owner = String(user?.id || user?.email || '').trim().toLowerCase();
    if (!owner) return '';
    return `${LOW_CREDITS_DISMISS_KEY_PREFIX}:${owner}:${lowCreditsCycleKey}`;
  }, [lowCreditsCycleKey, user?.email, user?.id]);
  const lowCreditsBannerEligible = useMemo(() => (
    Boolean(user)
    && !billingLoading
    && creditDisplayTier !== 'enterprise'
    && (creditsTone === 'warning' || creditsTone === 'critical')
  ), [billingLoading, creditDisplayTier, creditsTone, user]);
  const lowCreditsBannerToneClass = creditsTone === 'critical' ? 'is-critical' : 'is-warning';
  const lowCreditsHeadline = creditsTone === 'critical'
    ? 'Credits are critically low'
    : 'Credits are running low';
  const lowCreditsBody = creditsTone === 'critical'
    ? 'You have less than 5% of your monthly credits remaining. Open Billing to review usage and top up if needed.'
    : 'You have less than 20% of your monthly credits remaining. Open Billing to review usage and avoid interruptions.';
  useEffect(() => {
    if (!lowCreditsDismissStorageKey || !lowCreditsBannerEligible) {
      setLowCreditsBannerDismissed(false);
      return;
    }
    try {
      setLowCreditsBannerDismissed(localStorage.getItem(lowCreditsDismissStorageKey) === '1');
    } catch {
      setLowCreditsBannerDismissed(false);
    }
  }, [lowCreditsDismissStorageKey, lowCreditsBannerEligible]);
  const dismissLowCreditsBanner = useCallback(() => {
    if (!lowCreditsDismissStorageKey) {
      setLowCreditsBannerDismissed(true);
      return;
    }
    try {
      localStorage.setItem(lowCreditsDismissStorageKey, '1');
    } catch {
      // no-op
    }
    setLowCreditsBannerDismissed(true);
  }, [lowCreditsDismissStorageKey]);
  useEffect(() => {
    if (planCategory === 'individual' || !user) {
      setSharedProjects([]);
      setSharedProjectsLoading(false);
      return;
    }
    if (!effectiveIsCollaborator && !effectiveIsViewer) {
      setSharedProjects([]);
      setSharedProjectsLoading(false);
      return;
    }

    let cancelled = false;
    setSharedProjectsLoading(true);
    authFetch('/api/v1/team/projects')
      .then((response) => response.json().catch(() => ({})))
      .then((payload) => {
        if (!cancelled) {
          setSharedProjects(Array.isArray(payload?.projects) ? payload.projects : []);
        }
      })
      .catch(() => {
        if (!cancelled) {
          setSharedProjects([]);
        }
      })
      .finally(() => {
        if (!cancelled) {
          setSharedProjectsLoading(false);
        }
      });

    return () => {
      cancelled = true;
    };
  }, [authFetch, effectiveIsCollaborator, effectiveIsViewer, planCategory, user]);
  const visibleSharedProjects = useMemo(() => {
    const currentUserId = String(user?.id || '').trim();
    return (Array.isArray(sharedProjects) ? sharedProjects : []).filter((project) => {
      const ownerId = String(project?.created_by_user_id || '').trim();
      const visibility = String(project?.visibility || 'private').trim().toLowerCase();
      const sharedWith = Array.isArray(project?.shared_with_user_ids) ? project.shared_with_user_ids.map((id) => String(id)) : [];
      if (ownerId && currentUserId && ownerId === currentUserId) return true;
      if (visibility === 'team') return true;
      if (visibility === 'specific') return sharedWith.includes(currentUserId);
      return false;
    });
  }, [sharedProjects, user?.id]);
  const notificationFeedWithFallback = useMemo(() => {
    const normalized = normalizeNotificationFeed(notificationFeed);
    return normalized.length > 0 ? normalized : buildDefaultNotifications();
  }, [notificationFeed]);
  const bellNotifications = useMemo(() => {
    const allowed = new Set(bellNotificationIds);
    return notificationFeedWithFallback.filter((item) => allowed.has(item.id));
  }, [notificationFeedWithFallback, bellNotificationIds]);
  const unreadNotificationCount = bellNotificationIds.length;
  const notificationsForDisplay = notificationsMode === 'settings'
    ? notificationFeedWithFallback
    : bellNotifications;
  const allowedModelTypes = useMemo(() => {
    const fromStatus = Array.isArray(billingStatus?.allowed_model_types)
      ? billingStatus.allowed_model_types.map((item) => String(item || '').toLowerCase()).filter(Boolean)
      : [];
    if (fromStatus.length > 0) return fromStatus;
    return ['pluto'];
  }, [billingStatus]);
  const allModelTypeKeys = useMemo(() => {
    const catalogKeys = Object.keys(modelTypes || {}).map((key) => String(key || '').toLowerCase()).filter(Boolean);
    const merged = Array.from(new Set([...MODEL_DISPLAY_ORDER, ...catalogKeys]));
    return merged.sort((a, b) => {
      const ai = MODEL_DISPLAY_ORDER.indexOf(a);
      const bi = MODEL_DISPLAY_ORDER.indexOf(b);
      const rankA = ai === -1 ? Number.MAX_SAFE_INTEGER : ai;
      const rankB = bi === -1 ? Number.MAX_SAFE_INTEGER : bi;
      if (rankA !== rankB) return rankA - rankB;
      return a.localeCompare(b);
    });
  }, [modelTypes]);
  const modelOptions = useMemo(() => {
    return allModelTypeKeys.map((modelTypeKey) => {
      const normalizedKey = String(modelTypeKey || '').toLowerCase();
      const item = modelTypes?.[normalizedKey] || {};
      const fallbackLabel = normalizedKey
        ? normalizedKey.charAt(0).toUpperCase() + normalizedKey.slice(1)
        : 'Model';
      const label = item?.label || fallbackLabel;
      const version = String(item?.version || MODEL_VERSION_BY_TYPE[normalizedKey] || '1.0').trim();
      const withVersion = `${label}-${version}`;
      const isAllowed = allowedModelTypes.includes(normalizedKey);
      return {
        key: normalizedKey,
        label,
        withVersion,
        isAllowed,
      };
    });
  }, [allModelTypeKeys, modelTypes, allowedModelTypes]);
  const selectedModelOption = useMemo(
    () => modelOptions.find((option) => option.key === selectedModelType) || modelOptions[0] || null,
    [modelOptions, selectedModelType]
  );
  const defaultModelType = useMemo(() => {
    const candidate = String(billingStatus?.default_model_type || '').toLowerCase();
    if (candidate && allowedModelTypes.includes(candidate)) return candidate;
    return allowedModelTypes[0] || 'pluto';
  }, [billingStatus, allowedModelTypes]);
  const modelTypeStorageKey = useMemo(() => {
    if (user?.id) return `jaspen_model_type_id_${user.id}`;
    if (user?.email) return `jaspen_model_type_email_${String(user.email).toLowerCase()}`;
    return 'jaspen_model_type_last';
  }, [user?.id, user?.email]);
  const activeThreadId = currentSessionId || sessionId || null;

  const preferredFirstName = useMemo(() => {
    const source = (displayName || userName || '').trim();
    if (!source) return 'there';
    return source.split(/\s+/)[0];
  }, [displayName, userName]);
  const greetingPrefix = useMemo(() => {
    const hour = welcomeNow.getHours();
    if (hour < 12) return 'Good morning';
    if (hour < 17) return 'Good afternoon';
    return 'Good evening';
  }, [welcomeNow]);
  const dynamicPrompt = useMemo(() => {
    const prompts = [
      'Ready to build momentum?',
      "Let's make progress.",
      "Let's move this forward.",
      'Ready to get something done?',
      "Let's turn ideas into action."
    ];
    const seed = `${preferredFirstName}-${welcomeNow.getFullYear()}-${welcomeNow.getMonth()}-${welcomeNow.getDate()}`;
    const hash = [...seed].reduce((acc, ch) => acc + ch.charCodeAt(0), 0);
    return prompts[hash % prompts.length];
  }, [preferredFirstName, welcomeNow]);
  const welcomeHeading = `${greetingPrefix}, ${preferredFirstName}. ${dynamicPrompt}`;

  useEffect(() => {
    if (!user) return;
    const keys = getUserStorageKeys(user);
    const saved = (() => {
      try {
        return keys.map((k) => localStorage.getItem(k)).find(Boolean) || null;
      } catch {
        return null;
      }
    })();
    const fallback = user?.name || user?.email?.split('@')[0] || '';
    const initial = saved || fallback;
    setDisplayName(saved || '');
    setNameInput(initial);
    setNameError('');
    setOnboardingMode('entry');
    setOnboardingInitialSelection(readOnboardingState(user)?.selection || null);
    setGuidedFlowDismissed(readGuidedFlowDismissed(user));
    try {
      if (user?.email) localStorage.setItem('jaspen_last_email', user.email);
    } catch {}
  }, [user]);

  useEffect(() => {
    if (!user || sessionsLoading) return;
    const hasActiveThread = Boolean(sessionId || currentSessionId);
    const hasMessages = Array.isArray(messages) && messages.length > 0;
    if (hasActiveThread || hasMessages) {
      setOnboardingOpen(false);
    }
  }, [user, sessionsLoading, sessionId, currentSessionId, messages]);

  useEffect(() => {
    const timer = window.setInterval(() => setWelcomeNow(new Date()), 60000);
    return () => window.clearInterval(timer);
  }, []);

  useEffect(() => {
    try {
      ['jaspen_last_session_id', 'jaspen_sid', 'jaspen_history', 'jaspen_projects'].forEach((key) => localStorage.removeItem(key));
    } catch {}
  }, []);

  useEffect(() => {
    try {
      const raw = localStorage.getItem(notificationsStorageKey);
      if (!raw) {
        const defaults = buildDefaultNotifications();
        setNotificationFeed(defaults);
        setBellNotificationIds(defaults.map((item) => item.id));
        return;
      }
      const parsed = JSON.parse(raw);
      // Legacy format: single array with unread flags.
      if (Array.isArray(parsed)) {
        const normalizedFeed = normalizeNotificationFeed(parsed);
        const fallbackFeed = normalizedFeed.length > 0 ? normalizedFeed : buildDefaultNotifications();
        setNotificationFeed(fallbackFeed);
        const unreadIds = normalizedFeed
          .filter((item) => {
            const match = parsed.find((rawItem) => String(rawItem?.id || '') === item.id);
            return Boolean(match?.unread);
          })
          .map((item) => item.id);
        setBellNotificationIds(unreadIds);
        return;
      }
      // New split format: { feed: [...], bellIds: [...] }
      if (parsed && typeof parsed === 'object') {
        const normalizedFeed = normalizeNotificationFeed(parsed.feed);
        const fallbackFeed = normalizedFeed.length > 0 ? normalizedFeed : buildDefaultNotifications();
        const allowedIds = new Set(fallbackFeed.map((item) => item.id));
        const persistedBellIds = Array.isArray(parsed.bellIds)
          ? parsed.bellIds.map((id) => String(id || '').trim()).filter((id) => allowedIds.has(id))
          : [];
        setNotificationFeed(fallbackFeed);
        setBellNotificationIds(persistedBellIds);
        return;
      }
    } catch {}
    const defaults = buildDefaultNotifications();
    setNotificationFeed(defaults);
    setBellNotificationIds(defaults.map((item) => item.id));
  }, [notificationsStorageKey]);

  useEffect(() => {
    try {
      localStorage.setItem(
        notificationsStorageKey,
        JSON.stringify({
          feed: notificationFeed,
          bellIds: bellNotificationIds,
        })
      );
    } catch {}
  }, [notificationsStorageKey, notificationFeed, bellNotificationIds]);

  const clearNotificationBadge = useCallback(() => {
    setBellNotificationIds([]);
  }, []);

  const upsertNotification = useCallback((item, { markUnread = true } = {}) => {
    if (!item?.id) return;
    setNotificationFeed((prev) => {
      const base = Array.isArray(prev) ? prev : [];
      const next = base.filter((entry) => entry?.id !== item.id);
      return [item, ...next];
    });
    if (markUnread) {
      setBellNotificationIds((prev) => {
        const next = Array.isArray(prev) ? prev.filter((id) => id !== item.id) : [];
        return [item.id, ...next];
      });
    }
  }, []);

  const dismissNotification = useCallback((id) => {
    if (!id) return;
    setNotificationFeed((prev) => (Array.isArray(prev) ? prev.filter((item) => item?.id !== id) : prev));
    setBellNotificationIds((prev) => (Array.isArray(prev) ? prev.filter((itemId) => itemId !== id) : prev));
  }, []);

  const handleBatchIdeasActivity = useCallback((activity = {}) => {
    const type = String(activity?.type || '').trim();
    if (!type) return;
    const stamp = new Date().toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' });
    if (type === 'batch_upload_complete') {
      const total = Number(activity?.totalCount || 0);
      upsertNotification({
        id: `notif-batch-upload-${Date.now()}`,
        title: 'Batch upload complete',
        body: `Uploaded ${total} idea${total === 1 ? '' : 's'}${activity?.filename ? ` from ${activity.filename}` : ''}.`,
        stamp,
      });
      return;
    }
    if (type === 'batch_rank_complete') {
      const ranked = Number(activity?.rankedCount || 0);
      upsertNotification({
        id: `notif-batch-rank-${Date.now()}`,
        title: 'Batch ranking complete',
        body: `Jaspen ranked ${ranked} idea${ranked === 1 ? '' : 's'}. Ready ideas can be promoted into project threads.`,
        stamp,
      });
      return;
    }
    if (type === 'batch_promote_complete') {
      const promoted = Number(activity?.promotedCount || 0);
      upsertNotification({
        id: `notif-batch-promote-${Date.now()}`,
        title: 'Batch promotion complete',
        body: activity?.hasMore
          ? `Promoted ${promoted} ready idea${promoted === 1 ? '' : 's'}. More ready ideas remain.`
          : `Promoted ${promoted} ready idea${promoted === 1 ? '' : 's'} into project threads.`,
        stamp,
      });
    }
  }, [upsertNotification]);

  const persistDisplayName = async (value) => {
    const trimmed = String(value || '').trim();
    if (!trimmed) return false;
    setNameError('');
    setNameSaving(true);
    const result = await updateDisplayName(trimmed);
    if (!result?.success) {
      setNameError(result?.error || 'Unable to save name.');
      setNameSaving(false);
      return false;
    }
    try {
      const keys = getUserStorageKeys(user);
      keys.forEach((k) => localStorage.setItem(k, trimmed));
    } catch {}
    writeNamePromptDeferred(user, false);
    setDisplayName(trimmed);
    setNameSaving(false);
    return true;
  };

  const loadBilling = useCallback(async () => {
    setBillingLoading(true);
    try {
      const statusPath = adminWorkspacePreviewPlan
        ? `/api/v1/admin/preview/workspace?plan_key=${encodeURIComponent(adminWorkspacePreviewPlan)}`
        : '/api/v1/billing/status';
      const [statusRes, catalogRes] = await Promise.all([
        authFetch(`${API_BASE}${statusPath}`, {
          headers: buildAuthHeaders({}, 'GET'),
          credentials: 'include'
        }),
        fetch(`${API_BASE}/api/v1/billing/catalog`, { credentials: 'include' })
      ]);
      const statusData = await statusRes.json().catch(() => ({}));
      const catalogData = await catalogRes.json().catch(() => ({}));
      if (!statusRes.ok) {
        if (statusRes.status === 401) {
          await handleUnauthorized();
        }
        throw new Error(statusData?.msg || 'Unable to load plan details.');
      }
      setBillingStatus(statusData || null);
      setBillingCatalog(catalogData || { plans: {}, overage_packs: {}, model_types: {} });
      setBillingMessage('');
    } catch (error) {
      setBillingMessage(error.message || 'Unable to load plan details.');
    } finally {
      setBillingLoading(false);
    }
  }, [adminWorkspacePreviewPlan, authFetch, handleUnauthorized]);

  useEffect(() => {
    loadBilling();
  }, [loadBilling, user?.id, user?.email]);

  const syncCreditsFromPayload = useCallback((payload, { refresh = false } = {}) => {
    if (adminWorkspacePreviewPlan) return;
    const remainingCandidates = [
      payload?.credits?.remaining,
      payload?.credits_remaining,
      payload?.remaining_credits,
      payload?.analysis?.meta?.credits_remaining,
    ];
    const limitCandidates = [
      payload?.monthly_credit_limit,
      payload?.credits?.monthly_limit,
    ];

    const remaining = remainingCandidates.find((value) => Number.isFinite(Number(value)));
    const monthlyLimit = limitCandidates.find((value) => Number.isFinite(Number(value)));
    if (remaining == null && monthlyLimit == null) {
      if (refresh) void loadBilling();
      return;
    }

    setBillingStatus((prev) => {
      const next = (prev && typeof prev === 'object') ? { ...prev } : {};
      if (remaining != null) {
        next.credits_remaining = Number(remaining);
      }
      if (monthlyLimit != null) {
        next.monthly_credit_limit = Number(monthlyLimit);
      }
      if (
        Number.isFinite(Number(next.monthly_credit_limit))
        && Number.isFinite(Number(next.credits_remaining))
      ) {
        next.credits_used = Math.max(0, Number(next.monthly_credit_limit) - Number(next.credits_remaining));
      }
      return next;
    });

    if (refresh) {
      void loadBilling();
    }
  }, [adminWorkspacePreviewPlan, loadBilling]);

  useEffect(() => {
    if (!canUseScenarios && activeTab === 'scenario') {
      setActiveTab('summary');
      setView('summary');
    }
  }, [canUseScenarios, activeTab]);

  const loadThreadUsage = useCallback(async (targetThreadId = activeThreadId) => {
    if (!targetThreadId) {
      setThreadUsage(null);
      setThreadUsageError('');
      return;
    }

    setThreadUsageLoading(true);
    setThreadUsageError('');
    try {
      const response = await authFetch(`/api/v1/ai-agent/threads/${encodeURIComponent(targetThreadId)}/usage`, {
        method: 'GET',
      });
      const payload = await response.json().catch(() => ({}));
      if (!response.ok) {
        if (response.status === 404) {
          setThreadUsage(null);
          setThreadUsageError('');
          return;
        }
        if (response.status === 401) {
          await handleUnauthorized();
        }
        throw new Error(payload?.error || payload?.msg || payload?.message || 'Unable to load usage details.');
      }
      setThreadUsage(payload || null);
    } catch (err) {
      setThreadUsageError(err?.message || 'Unable to load usage details.');
      setThreadUsage(null);
    } finally {
      setThreadUsageLoading(false);
    }
  }, [activeThreadId, authFetch, handleUnauthorized]);

  useEffect(() => {
    if (!sidebarState.settings) return;
    if (!activeThreadId) {
      setThreadUsage(null);
      setThreadUsageError('');
      return;
    }
    loadThreadUsage(activeThreadId);
  }, [sidebarState.settings, activeThreadId, messages.length, loadThreadUsage]);

  useEffect(() => {
    let saved = '';
    try {
      saved = String(localStorage.getItem(modelTypeStorageKey) || '').toLowerCase();
    } catch {
      saved = '';
    }
    if (saved && allowedModelTypes.includes(saved)) {
      setSelectedModelType(saved);
      return;
    }
    setSelectedModelType(defaultModelType);
  }, [modelTypeStorageKey, allowedModelTypes, defaultModelType]);

  useEffect(() => {
    const normalized = String(selectedModelType || '').toLowerCase();
    if (!normalized || !allowedModelTypes.includes(normalized)) return;
    try {
      localStorage.setItem(modelTypeStorageKey, normalized);
    } catch {}
  }, [modelTypeStorageKey, selectedModelType, allowedModelTypes]);

  useEffect(() => {
    if (!modelMenuOpen) return;
    const onPointerDown = (event) => {
      if (!(event.target instanceof Node)) return;
      if (!modelMenuRef.current?.contains(event.target)) {
        setModelMenuOpen(false);
      }
    };
    const onKeyDown = (event) => {
      if (event.key === 'Escape') setModelMenuOpen(false);
    };
    document.addEventListener('pointerdown', onPointerDown);
    document.addEventListener('keydown', onKeyDown);
    return () => {
      document.removeEventListener('pointerdown', onPointerDown);
      document.removeEventListener('keydown', onKeyDown);
    };
  }, [modelMenuOpen]);

  useEffect(() => {
    if (busy) setModelMenuOpen(false);
  }, [busy]);

  const dismissSidebars = useCallback(() => {
    dispatchSidebar({ type: 'CLOSE_ALL' });
  }, []);

  const anySidebarOpen = sidebarState.history || sidebarState.readiness || sidebarState.settings;

  const focusVisibleComposer = useCallback(() => {
    const candidates = [chatTabInputRef.current, intakeInputRef.current];
    const target = candidates.find((node) => node && !node.disabled && node.offsetParent !== null);
    if (!target) return false;
    target.focus();
    const nextLength = target.value?.length || 0;
    target.setSelectionRange?.(nextLength, nextLength);
    return true;
  }, []);

  const openHistorySearch = useCallback(() => {
    if (!hasHistory) return false;
    if (view !== 'intake') {
      setView('intake');
    }
    dispatchSidebar({ type: 'OPEN_HISTORY' });
    window.setTimeout(() => {
      historySearchInputRef.current?.focus();
      historySearchInputRef.current?.select?.();
    }, 0);
    return true;
  }, [hasHistory, view]);

  useEffect(() => {
    if (!anySidebarOpen) return;

    const onPointerDown = (event) => {
      if (!(event.target instanceof Element)) return;
      if (event.target.closest('.jas-ud-submenu-portal')) return;
      if (event.target.closest('.jas-left-sidebar')) return;
      if (event.target.closest('.jas-sidebar-tab')) return;
      if (event.target.closest('.jas-drawer-tab')) return;
      dismissSidebars();
    };

    document.addEventListener('pointerdown', onPointerDown);
    return () => document.removeEventListener('pointerdown', onPointerDown);
  }, [anySidebarOpen, dismissSidebars]);

  const startPlanChange = async (planKey) => {
    setBillingActionLoading(planKey);
    setBillingMessage('');
    try {
      const response = await authFetch(`${API_BASE}/api/v1/billing/create-checkout-session`, {
        method: 'POST',
        headers: buildAuthHeaders({ 'Content-Type': 'application/json' }, 'POST'),
        credentials: 'include',
        body: JSON.stringify({ plan_key: planKey }),
      });
      const data = await response.json().catch(() => ({}));
      if (!response.ok) {
        if (response.status === 401) {
          await handleUnauthorized();
        }
        throw new Error(data?.msg || 'Unable to start plan change.');
      }
      if (data?.url) {
        window.location.href = data.url;
        return;
      }
      await loadBilling();
    } catch (error) {
      setBillingMessage(error.message || 'Unable to start plan change.');
    } finally {
      setBillingActionLoading('');
    }
  };

  const openBillingPortal = async () => {
    setBillingActionLoading('portal');
    setBillingMessage('');
    try {
      const response = await authFetch(`${API_BASE}/api/v1/billing/create-portal-session`, {
        method: 'POST',
        headers: buildAuthHeaders({ 'Content-Type': 'application/json' }, 'POST'),
        credentials: 'include',
        body: JSON.stringify({ return_url: `${window.location.origin}/account` }),
      });
      const data = await response.json().catch(() => ({}));
      if (!response.ok || !data?.url) {
        if (response.status === 401) {
          await handleUnauthorized();
        }
        throw new Error(data?.msg || 'Unable to open billing settings.');
      }
      window.location.href = data.url;
    } catch (error) {
      setBillingMessage(error.message || 'Unable to open billing settings.');
    } finally {
      setBillingActionLoading('');
    }
  };

  const renderNameModal = () => {
    if (!nameModalOpen) return null;
    const titleId = 'jas-name-modal-title';
    const descriptionId = 'jas-name-modal-description';
    return (
      <div className="jas-name-modal-backdrop" role="presentation">
        <div
          className="jas-name-modal"
          role="dialog"
          aria-modal="true"
          aria-labelledby={titleId}
          aria-describedby={descriptionId}
        >
          <h3 id={titleId}>What should I call you?</h3>
          <p id={descriptionId}>We&apos;ll use this across Jaspen. If you&apos;d rather do it later, you can update it anytime from Account settings.</p>
          <input
            className="jas-name-input"
            value={nameInput}
            onChange={(e) => setNameInput(e.target.value)}
            placeholder="Your name"
            autoFocus
          />
          {nameError && <p className="jas-name-error">{nameError}</p>}
          <div className="jas-name-actions">
          <button
            type="button"
            className="jas-name-cancel"
              onClick={() => {
                setNameError('');
                setNameModalOpen(false);
                if (nameModalMode === 'required') {
                  const onboardingState = readOnboardingState(user);
                  if (!onboardingState?.completed && !onboardingState?.deferred) {
                    setOnboardingMode('entry');
                    setOnboardingInitialSelection(onboardingState?.selection || onboardingInitialSelection || null);
                    setOnboardingOpen(true);
                    return;
                  }
                  deferSetupPrompt();
                }
            }}
          >
            {nameModalMode === 'required' ? 'Set up later' : 'Cancel'}
          </button>
            <button
              type="button"
              className="jas-name-save"
              onClick={async () => {
                const trimmed = nameInput.trim();
                if (!trimmed) return;
                const ok = await persistDisplayName(trimmed);
                if (ok) {
                  setNameModalOpen(false);
                  if (nameModalMode === 'required') {
                    const onboardingState = readOnboardingState(user);
                    if (!onboardingState?.completed && !onboardingState?.deferred) {
                      setOnboardingMode('entry');
                      setOnboardingInitialSelection(onboardingState?.selection || onboardingInitialSelection || null);
                      setOnboardingLaunchLabel('');
                      setOnboardingOpen(true);
                    }
                  }
                }
              }}
              disabled={!nameInput.trim() || nameSaving} aria-disabled={!nameInput.trim() || nameSaving}
            >
              {nameSaving ? 'Saving...' : 'Save'}
            </button>
          </div>
        </div>
      </div>
    );
  };

  const renderBillingModal = () => {
    if (!billingModalOpen) return null;
    return (
      <div className="jas-modal-backdrop" role="presentation" onClick={() => setBillingModalOpen(false)}>
        <div className="jas-account-modal" role="dialog" aria-modal="true" aria-label="Account and billing" onClick={(e) => e.stopPropagation()}>
          <div className="jas-account-modal-header">
            <h3>Account and billing</h3>
            <button type="button" className="jas-account-modal-close" onClick={() => setBillingModalOpen(false)} aria-label="Close">
              <FontAwesomeIcon icon={faTimes} />
            </button>
          </div>

          <div className="jas-account-summary-grid">
            <article className="jas-account-summary-card">
              <p className="label">Current plan</p>
              <p className="value">{currentPlanLabel}</p>
            </article>
            <article className="jas-account-summary-card">
              <p className="label">Credits remaining</p>
              <p className="value">{creditsBadge}</p>
            </article>
            <article className="jas-account-summary-card">
              <p className="label">Monthly limit</p>
              <p className="value">
                {monthlyCreditLimit == null ? 'Contracted' : Number(monthlyCreditLimit).toLocaleString()}
              </p>
            </article>
          </div>

          <div className="jas-account-plan-grid">
            {PLAN_ORDER.map((key) => {
              const plan = plans[key];
              if (!plan) return null;
              const isCurrent = key === currentPlanKey;
              const isSalesOnly = !!plan.sales_only;
              return (
                <article className={`jas-account-plan-card ${isCurrent ? 'is-current' : ''}`} key={key}>
                  <h4>{plan.label}</h4>
                  <p className="price">
                    {Number.isFinite(plan.monthly_price_usd)
                      ? (plan.monthly_price_usd === 0 ? '$0/mo' : `$${plan.monthly_price_usd}/mo`)
                      : 'Contact sales'}
                  </p>
                  <p className="detail">
                    {plan.monthly_credits == null
                      ? 'Contracted pooled credits'
                      : `${Number(plan.monthly_credits).toLocaleString()} credits/month`}
                  </p>
                  <p className="detail jas-account-plan-connectors">
                    Connectors: {getPlanConnectorSentence(key)}
                  </p>
                  {isCurrent ? (
                    <span className="jas-account-pill">Current</span>
                  ) : isSalesOnly ? (
                    <a href="/pages/get-in-touch" className="jas-account-action-link" target="_blank" rel="noreferrer">Talk to sales</a>
                  ) : (
                    <button
                      type="button"
                      className="jas-account-action-btn"
                      onClick={() => startPlanChange(key)}
                      disabled={billingActionLoading === key} aria-disabled={billingActionLoading === key}
                    >
                      {billingActionLoading === key ? 'Redirecting...' : 'Select plan'}
                    </button>
                  )}
                </article>
              );
            })}
          </div>

          {billingMessage && <p className="jas-account-message">{billingMessage}</p>}

          <div className="jas-account-modal-actions">
            <button
              type="button"
              className="jas-account-portal-btn"
              onClick={openBillingPortal}
              disabled={billingActionLoading === 'portal'} aria-disabled={billingActionLoading === 'portal'}
            >
              {billingActionLoading === 'portal' ? 'Opening...' : 'Manage billing'}
            </button>
            <button
              type="button"
              className="jas-account-secondary-btn"
              onClick={() => navigate('/account')}
            >
              Full account page
            </button>
          </div>
        </div>
      </div>
    );
  };

  const renderNotificationsModal = () => {
    if (!notificationsOpen) return null;
    return (
      <div
        className="jas-notifications-backdrop"
        role="presentation"
        onClick={() => setNotificationsOpen(false)}
      >
        <div
          className="jas-notifications-modal"
          role="dialog"
          aria-modal="true"
          aria-label="Notifications"
          onClick={(e) => e.stopPropagation()}
        >
          <div className="jas-notifications-header">
            <h3>Notifications</h3>
            <div className="jas-notifications-header-actions">
              <button
                type="button"
                className="jas-notifications-clear"
                onClick={clearNotificationBadge}
                disabled={unreadNotificationCount === 0} aria-disabled={unreadNotificationCount === 0}
              >
                Clear
              </button>
              <button
                type="button"
                className="jas-notifications-close"
                onClick={() => setNotificationsOpen(false)}
                aria-label="Close notifications"
              >
                <FontAwesomeIcon icon={faTimes} />
              </button>
            </div>
          </div>
          <div className="jas-notifications-list">
            {notificationsForDisplay.length === 0 ? (
              <div className="jas-notification-empty">
                {notificationsMode === 'bell' ? 'No new notifications' : 'No notifications'}
              </div>
            ) : (
              notificationsForDisplay.map((item) => (
                <article key={item.id} className="jas-notification-item">
                  <div className="jas-notification-row">
                    <h4>{item.title}</h4>
                    <span>{item.stamp}</span>
                  </div>
                  <p>{item.body}</p>
                </article>
              ))
            )}
          </div>
        </div>
      </div>
    );
  };

  const openExternal = (path) => {
    window.open(path, '_blank', 'noopener,noreferrer');
  };

  const openDisplayNameEditor = () => {
    setNameError('');
    setNameInput(displayName || user?.name || user?.email?.split?.('@')[0] || '');
    setNameModalMode('edit');
    setNameModalOpen(true);
  };

  const persistOnboardingProfileState = useCallback(async (payload = {}) => {
    if (typeof updateUiPreferences !== 'function') return;
    const currentPrefs = user?.ui_preferences && typeof user.ui_preferences === 'object'
      ? user.ui_preferences
      : {};
    const currentOnboarding = currentPrefs?.onboarding && typeof currentPrefs.onboarding === 'object'
      ? currentPrefs.onboarding
      : {};
    const nextSelection = payload?.selection && typeof payload.selection === 'object'
      ? { ...payload.selection }
      : (payload?.selection === null ? null : (currentOnboarding.selection && typeof currentOnboarding.selection === 'object'
        ? { ...currentOnboarding.selection }
        : null));
    const nextOnboarding = {
      ...currentOnboarding,
      ...(Object.prototype.hasOwnProperty.call(payload || {}, 'completed') ? { completed: Boolean(payload?.completed) } : {}),
      ...(Object.prototype.hasOwnProperty.call(payload || {}, 'deferred') ? { deferred: Boolean(payload?.deferred) } : {}),
      ...(Object.prototype.hasOwnProperty.call(payload || {}, 'selection') ? { selection: nextSelection } : {}),
    };
    const result = await updateUiPreferences({
      onboarding: nextOnboarding,
      onboarding_complete: Boolean(nextOnboarding.completed),
    });
    if (!result?.success) {
      devWarn('[onboarding] Failed to persist profile onboarding state', result?.error || 'unknown error');
    }
  }, [updateUiPreferences, user?.ui_preferences]);

  // Dismissible tips carousel — fixed bottom-right, one card at a time
  const [tipIndex, setTipIndex] = useState(() => {
    try { return parseInt(localStorage.getItem('jaspen_tip_idx') || '0', 10); } catch { return 0; }
  });
  const [tipExiting, setTipExiting] = useState(false);
  const dismissTip = () => {
    if (tipExiting) return;
    setTipExiting(true);
    setTimeout(() => {
      const next = tipIndex + 1;
      try { localStorage.setItem('jaspen_tip_idx', String(next)); } catch { /* noop */ }
      setTipIndex(next);
      setTipExiting(false);
    }, 200);
  };

  const deferSetupPrompt = () => {
    const previousSelection = readOnboardingState(user)?.selection || onboardingInitialSelection || null;
    writeNamePromptDeferred(user, true);
    writeOnboardingState(user, {
      completed: false,
      deferred: true,
      selection: previousSelection,
    });
    void persistOnboardingProfileState({
      completed: false,
      deferred: true,
      selection: previousSelection,
    });
    setNameModalOpen(false);
    setOnboardingOpen(false);
    upsertNotification(SETUP_REMINDER_NOTIFICATION);
    showToast('Saved for later. You can find this reminder in Notifications and Account settings.', 'info');
  };

  const openSetupPromptFlow = () => {
    const previousSelection = readOnboardingState(user)?.selection || onboardingInitialSelection || null;
    dismissNotification(SETUP_REMINDER_NOTIFICATION.id);
    writeNamePromptDeferred(user, false);
    writeOnboardingState(user, {
      completed: false,
      deferred: false,
      selection: previousSelection,
    });
    void persistOnboardingProfileState({
      completed: false,
      deferred: false,
      selection: previousSelection,
    });
    if (!displayName) {
      setNameError('');
      setNameInput(displayName || user?.name || user?.email?.split?.('@')[0] || '');
      setNameModalMode('required');
      setNameModalOpen(true);
      return;
    }
    setOnboardingMode('entry');
    setOnboardingInitialSelection(previousSelection);
    setOnboardingLaunchLabel('');
    setOnboardingOpen(true);
  };

  const openOnboardingEditor = () => {
    setOnboardingMode('settings');
    setOnboardingInitialSelection(readOnboardingState(user)?.selection || null);
    setOnboardingLaunchLabel('');
    setOnboardingOpen(true);
    dispatchSidebar({ type: 'CLOSE_SETTINGS' });
  };

  const handleSupportRoleSwitch = (value) => {
    const option = SUPPORT_ROLE_SWITCH_OPTIONS.find((item) => item.value === value);
    if (!option) return;
    navigate(option.path);
  };

  const renderUserMenuContent = (onClose) => (
    <div className="jas-ud-layout">
      <div className="jas-ud-scroll">
        {isPlatformAdmin && (
          <div className="jas-ud-section">
            <div className="jas-ud-section-label">Role Switcher</div>
            <div className="jas-ud-role-switcher">
              <label className="jas-ud-role-switcher-label" htmlFor="jas-support-role-switcher">
                Preview customer-facing access
              </label>
              <select
                id="jas-support-role-switcher"
                value={supportRoleSwitchValue}
                onChange={(event) => {
                  onClose?.();
                  handleSupportRoleSwitch(event.target.value);
                }}
              >
                {SUPPORT_ROLE_SWITCH_OPTIONS.map((option) => (
                  <option key={option.value} value={option.value}>{option.label}</option>
                ))}
              </select>
              <p className="jas-ud-role-switcher-note">
                {supportRoleSwitchValue === 'actual'
                  ? 'Showing your actual admin account.'
                  : `Previewing ${SUPPORT_ROLE_SWITCH_OPTIONS.find((option) => option.value === supportRoleSwitchValue)?.label || 'support mode'} using your active org data.`}
              </p>
            </div>
          </div>
        )}
        <div className="jas-ud-section">
          <div className="jas-ud-section-label">Navigate</div>
          {showRealDashboard && (
            <button className="jas-ud-item" onClick={() => { onClose?.(); navigate('/dashboard'); }}>
              <FontAwesomeIcon icon={faListCheck} />
              <span className="jas-ud-item-label">Dashboard</span>
            </button>
          )}
          {showLockedDashboard && (
            <button
              className="jas-ud-item is-locked"
              onClick={() => setBillingModalOpen(true)}
              title="Upgrade to Team to unlock shared dashboards"
            >
              <FontAwesomeIcon icon={faListCheck} />
              <span className="jas-ud-item-label">Dashboard</span>
              <span className="jas-ud-item-ext"><FontAwesomeIcon icon={faLock} /></span>
            </button>
          )}
          {canStartOrgProjects && (
            <button className="jas-ud-item" onClick={() => { onClose?.(); navigate('/new'); }}>
              <FontAwesomeIcon icon={faPlus} />
              <span className="jas-ud-item-label">New Project</span>
            </button>
          )}
          <button className="jas-ud-item" onClick={() => { onClose?.(); navigate('/projects'); }}>
            <FontAwesomeIcon icon={faLayerGroup} />
            <span className="jas-ud-item-label">Projects</span>
          </button>
          <button className="jas-ud-item" onClick={() => { onClose?.(); navigate('/scores'); }}>
            <FontAwesomeIcon icon={faChartLine} />
            <span className="jas-ud-item-label">Scores</span>
          </button>
          {showRealInsights && (
            <button className="jas-ud-item" onClick={() => { onClose?.(); navigate('/insights'); }}>
              <FontAwesomeIcon icon={faChartLine} />
              <span className="jas-ud-item-label">Insights</span>
            </button>
          )}
          {showLockedInsights && (
            <button
              className="jas-ud-item is-locked"
              onClick={() => setBillingModalOpen(true)}
              title="Upgrade to Team to unlock connected insights"
            >
              <FontAwesomeIcon icon={faChartLine} />
              <span className="jas-ud-item-label">Insights</span>
              <span className="jas-ud-item-ext"><FontAwesomeIcon icon={faLock} /></span>
            </button>
          )}
          {showRealReports && (
            <button className="jas-ud-item" onClick={() => { onClose?.(); navigate('/reports'); }}>
              <FontAwesomeIcon icon={faDownload} />
              <span className="jas-ud-item-label">Reports</span>
            </button>
          )}
          {showLockedReports && (
            <button
              className="jas-ud-item is-locked"
              onClick={() => setBillingModalOpen(true)}
              title="Upgrade to Team to unlock reports"
            >
              <FontAwesomeIcon icon={faDownload} />
              <span className="jas-ud-item-label">Reports</span>
              <span className="jas-ud-item-ext"><FontAwesomeIcon icon={faLock} /></span>
            </button>
          )}
          {showRealActivity && (
            <button className="jas-ud-item" onClick={() => { onClose?.(); navigate('/activity'); }}>
              <FontAwesomeIcon icon={faClockRotateLeft} />
              <span className="jas-ud-item-label">Activity</span>
            </button>
          )}
          {showLockedActivity && (
            <button
              className="jas-ud-item is-locked"
              onClick={() => setBillingModalOpen(true)}
              title="Upgrade to Essential to unlock activity history"
            >
              <FontAwesomeIcon icon={faClockRotateLeft} />
              <span className="jas-ud-item-label">Activity</span>
              <span className="jas-ud-item-ext"><FontAwesomeIcon icon={faLock} /></span>
            </button>
          )}
          {showRealTeam && (
            <button className="jas-ud-item" onClick={() => { onClose?.(); navigate('/team'); }}>
              <FontAwesomeIcon icon={faUser} />
              <span className="jas-ud-item-label">Team</span>
            </button>
          )}
          {showLockedTeam && (
            <button
              className="jas-ud-item is-locked"
              onClick={() => setBillingModalOpen(true)}
              title="Upgrade to Team to unlock shared members and settings"
            >
              <FontAwesomeIcon icon={faUser} />
              <span className="jas-ud-item-label">Team</span>
              <span className="jas-ud-item-ext"><FontAwesomeIcon icon={faLock} /></span>
            </button>
          )}
          {!isPlatformAdmin && isEnterpriseAdmin && (
            <button className="jas-ud-item" onClick={() => { onClose?.(); navigate('/enterprise-admin'); }}>
              <FontAwesomeIcon icon={faGaugeHigh} />
              <span className="jas-ud-item-label">Enterprise Admin</span>
            </button>
          )}
          {showRealConnectors && (
            <button className="jas-ud-item" onClick={() => { onClose?.(); navigate(connectorsManagePath); }}>
              <FontAwesomeIcon icon={faLayerGroup} />
              <span className="jas-ud-item-label">Data Sources</span>
            </button>
          )}
          {showLockedConnectors && (
            <button
              className="jas-ud-item is-locked"
              onClick={() => setBillingModalOpen(true)}
              title="Upgrade to Essential to unlock starter data sources"
            >
              <FontAwesomeIcon icon={faLayerGroup} />
              <span className="jas-ud-item-label">Data Sources</span>
              <span className="jas-ud-item-ext"><FontAwesomeIcon icon={faLock} /></span>
            </button>
          )}
          <button className="jas-ud-item" onClick={() => { onClose?.(); navigate('/knowledge'); }}>
            <FontAwesomeIcon icon={faQuestionCircle} />
            <span className="jas-ud-item-label">Knowledge</span>
          </button>
          <button className="jas-ud-item" onClick={() => { onClose?.(); navigate('/account'); }}>
            <FontAwesomeIcon icon={faUser} />
            <span className="jas-ud-item-label">Account</span>
          </button>
          {isPlatformAdmin && (
            <button className="jas-ud-item" onClick={() => { onClose?.(); navigate('/jaspen-admin'); }}>
              <FontAwesomeIcon icon={faUser} />
              <span className="jas-ud-item-label">Jaspen Admin</span>
            </button>
          )}
        </div>

        <div className="jas-ud-section">
          <div className="jas-ud-section-label">User Tools</div>
          <div className="jas-ud-role-switcher jas-ud-invite-card">
            <span className="jas-ud-role-switcher-label">Invite others</span>
            <p className="jas-ud-role-switcher-note">
              Share your invite link from here.
            </p>
            <div className="jas-ud-invite-row">
              <code>{inviteDisplay || 'Generating…'}</code>
              <button
                type="button"
                className="jas-ud-invite-btn"
                onClick={handleCopyInviteLink}
                disabled={!inviteLink} aria-disabled={!inviteLink}
              >
                Copy link
              </button>
            </div>
          </div>
          <button
            className="jas-ud-item"
            onClick={() => {
              setNotificationsMode('settings');
              setNotificationsOpen(true);
            }}
          >
            <FontAwesomeIcon icon={faBell} />
            <span className="jas-ud-item-label">Notifications</span>
            <span className="jas-ud-item-badge">{unreadNotificationCount}</span>
          </button>
          <button className="jas-ud-item" onClick={() => { setBillingModalOpen(true); }}>
            <FontAwesomeIcon icon={faBolt} />
            <span className="jas-ud-item-label">Credits</span>
            <span className="jas-ud-item-badge">{billingLoading ? '...' : creditsBadge}</span>
          </button>
        </div>

        <div className="jas-ud-section">
          <div className="jas-ud-section-label">Account Usage (This Month)</div>
          {billingLoading && (
            <p className="jas-ud-usage-empty">Loading usage...</p>
          )}
          {!billingLoading && monthlyCreditLimit == null && (
            <p className="jas-ud-usage-note">Monthly limit: Contracted pooled credits on {currentPlanLabel} plan.</p>
          )}
          {!billingLoading && monthlyCreditLimit != null && (
            <>
              <div className="jas-ud-usage-grid jas-ud-usage-grid-compact">
                <div className="jas-ud-usage-stat">
                  <span>Used</span>
                  <strong>{Number(resolvedMonthlyCreditsUsed || 0).toLocaleString()}</strong>
                </div>
                <div className="jas-ud-usage-stat">
                  <span>Remaining</span>
                  <strong>{Number(creditsRemaining || 0).toLocaleString()}</strong>
                </div>
              </div>
              <p className="jas-ud-usage-note">
                Monthly limit: {Number(monthlyCreditLimit || 0).toLocaleString()} credits on {currentPlanLabel}.
              </p>
            </>
          )}
        </div>

        <div className="jas-ud-section">
          <div className="jas-ud-section-label">Current Thread Usage</div>
          {!activeThreadId && (
            <p className="jas-ud-usage-empty">Start or open a thread to see usage details.</p>
          )}
          {activeThreadId && threadUsageLoading && (
            <p className="jas-ud-usage-empty">Loading usage...</p>
          )}
          {activeThreadId && !threadUsageLoading && threadUsageError && (
            <p className="jas-ud-usage-error">{threadUsageError}</p>
          )}
          {activeThreadId && !threadUsageLoading && !threadUsageError && !threadUsage && (
            <p className="jas-ud-usage-empty">Usage details are not available for this thread yet.</p>
          )}
          {activeThreadId && !threadUsageLoading && !threadUsageError && (
            threadUsage ? (
            <>
              <div className="jas-ud-usage-top">
                <span className="jas-ud-usage-model">
                  Model: {String(threadUsage?.usage_summary?.model || selectedModelType || 'unknown')}
                </span>
                <button
                  type="button"
                  className="jas-ud-usage-refresh"
                  onClick={() => loadThreadUsage(activeThreadId)}
                >
                  Refresh
                </button>
              </div>
              <div className="jas-ud-usage-grid">
                <div className="jas-ud-usage-stat">
                  <span>Total tokens</span>
                  <strong>{Number(threadUsage?.usage_summary?.total_tokens || 0).toLocaleString()}</strong>
                </div>
                <div className="jas-ud-usage-stat">
                  <span>Credits charged</span>
                  <strong>{Number(threadUsage?.usage_summary?.credits_charged || 0).toLocaleString()}</strong>
                </div>
                <div className="jas-ud-usage-stat">
                  <span>Input tokens</span>
                  <strong>{Number(threadUsage?.usage_summary?.input_tokens || 0).toLocaleString()}</strong>
                </div>
                <div className="jas-ud-usage-stat">
                  <span>Output tokens</span>
                  <strong>{Number(threadUsage?.usage_summary?.output_tokens || 0).toLocaleString()}</strong>
                </div>
              </div>
              {Array.isArray(threadUsage?.usage_events) && threadUsage.usage_events.length > 0 && (
                <div className="jas-ud-usage-events">
                  {threadUsage.usage_events.slice(-4).reverse().map((event, idx) => (
                    <div key={`${event?.timestamp || 'usage'}-${idx}`} className="jas-ud-usage-event">
                      <span>{new Date(event?.timestamp || Date.now()).toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' })}</span>
                      <span>{Number(event?.total_tokens || 0).toLocaleString()} tok</span>
                      <span>{Number(event?.credits_charged || 0).toLocaleString()} cr</span>
                    </div>
                  ))}
                </div>
              )}
            </>
            ) : null
          )}
        </div>

        <div className="jas-ud-section">
          <button className="jas-ud-item" onClick={() => { openExternal('/pages/support'); }}>
            <FontAwesomeIcon icon={faQuestionCircle} />
            <span className="jas-ud-item-label">Get help</span>
            <span className="jas-ud-item-ext"><FontAwesomeIcon icon={faArrowUpRightFromSquare} /></span>
          </button>
        </div>
      </div>

      <SidebarIdentityFooter
        displayName={displayName}
        planLabel={footerPlanLabel}
        onOpenDisplayNameEditor={openDisplayNameEditor}
        onOpenOnboardingEditor={openOnboardingEditor}
        onOpenBilling={() => setBillingModalOpen(true)}
        onLogout={handleLogout}
        onClose={onClose}
      />
    </div>
  );

  // === Speech Recognition for Voice Input ===
  useEffect(() => {
    // Check for browser support
    const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
    if (!SpeechRecognition) {
      devWarn('Speech recognition not supported in this browser');
      return;
    }

    if (isRecording) {
      // Start recording
      const recognition = new SpeechRecognition();
      recognition.continuous = true;
      recognition.interimResults = true;
      recognition.lang = 'en-US';

      recognition.onresult = (event) => {
        let transcript = '';
        for (let i = event.resultIndex; i < event.results.length; i++) {
          transcript += event.results[i][0].transcript;
        }
        // Append to existing input
        setInput(prev => {
          const separator = prev && !prev.endsWith(' ') ? ' ' : '';
          return prev + separator + transcript;
        });
      };

      recognition.onerror = (event) => {
        console.error('Speech recognition error:', event.error);
        setIsRecording(false);
      };

      recognition.onend = () => {
        // Only restart if still recording (user hasn't stopped)
        if (recognitionRef.current === recognition) {
          setIsRecording(false);
        }
      };

      recognitionRef.current = recognition;
      recognition.start();
    } else {
      // Stop recording
      if (recognitionRef.current) {
        recognitionRef.current.stop();
        recognitionRef.current = null;
      }
    }

    return () => {
      if (recognitionRef.current) {
        recognitionRef.current.stop();
        recognitionRef.current = null;
      }
    };
  }, [isRecording]);

  // === Persist/Restore current session across refresh ===
  const LS_JAS_LAST_SESSION = 'jas_last_session_id';

  const setLastSessionId = (sid) => {
    try { localStorage.setItem(LS_JAS_LAST_SESSION, String(sid || '')); } catch {}
    // Optional: also store in URL so refresh/share works
    try {
      const u = new URL(window.location.href);
      u.searchParams.set('sid', String(sid || ''));
      window.history.replaceState({}, '', u.toString());
    } catch {}
  };

  const clearLastSessionId = () => {
    try { localStorage.removeItem(LS_JAS_LAST_SESSION); } catch {}
    try {
      const u = new URL(window.location.href);
      u.searchParams.delete('sid');
      window.history.replaceState({}, '', u.toString());
    } catch {}
  };

// AI Assistant drawer state
const [aiDrawerOpen, setAiDrawerOpen] = useState(true);
const [aiInput, setAiInput] = useState('');
const [aiScenarioProposal, setAiScenarioProposal] = useState(null);
const [aiScenarioBusy, setAiScenarioBusy] = useState(false);
const aiMessagesRef = useRef(null);
const aiMessagesEndRef = useRef(null);
const aiDrawerPanelRef = useRef(null);
const [initialRestorePending, setInitialRestorePending] = useState(() => Boolean(getRestorableSessionIdFromLocation()));
  const closeShortcutSurface = useCallback(() => {
    if (commandPaletteOpen) {
      setCommandPaletteOpen(false);
      return true;
    }
    if (confirmDialog) {
      setConfirmDialog(null);
      return true;
    }
    if (modelMenuOpen) {
      setModelMenuOpen(false);
      return true;
    }
    if (threadEditOpen) {
      setThreadEditOpen(false);
      return true;
    }
    if (saveStarterModalOpen) {
      setSaveStarterModalOpen(false);
      return true;
    }
    if (helpOpen) {
      setHelpOpen(false);
      return true;
    }
    if (notificationsOpen) {
      setNotificationsOpen(false);
      return true;
    }
    if (billingModalOpen) {
      setBillingModalOpen(false);
      return true;
    }
    if (batchIdeasOpen) {
      setBatchIdeasOpen(false);
      return true;
    }
    if (aiDrawerOpen) {
      setAiDrawerOpen(false);
      return true;
    }
    if (anySidebarOpen) {
      dismissSidebars();
      return true;
    }
    return false;
  }, [
    aiDrawerOpen,
    anySidebarOpen,
    batchIdeasOpen,
    billingModalOpen,
    commandPaletteOpen,
    confirmDialog,
    dismissSidebars,
    helpOpen,
    modelMenuOpen,
    notificationsOpen,
    saveStarterModalOpen,
    threadEditOpen,
  ]);
  const objectiveLabel = OBJECTIVE_LABEL_BY_KEY[strategyObjective] || OBJECTIVE_LABEL_BY_KEY.balanced;
  const objectiveLocked = Boolean(
    sessionId ||
    currentSessionId ||
    (Array.isArray(messages) && messages.some((m) => String(m?.text || '').trim().length > 0))
  );
  const selectedStarter = useMemo(
    () => savedStarterConfigs.find((starter) => starter?.id === selectedStarterId) || null,
    [savedStarterConfigs, selectedStarterId]
  );

  const applyStrategyObjective = useCallback(async (nextObjective, options = {}) => {
    const normalized = normalizeStrategyObjective(nextObjective);
    const shouldPersist = options.persist !== false;
    const persistThreadId = options.threadId || currentSessionId || sessionId || null;
    const explicitSetting = Object.prototype.hasOwnProperty.call(options, 'explicit')
      ? Boolean(options.explicit)
      : options.markExplicit !== false;
    const silent = options.silent === true;
    setStrategyObjective(normalized);
    setAiScenarioProposal((prev) => (prev ? { ...prev, objective: normalized } : prev));
    setObjectiveExplicitlySet(explicitSetting);
    if (!shouldPersist || !persistThreadId) return normalized;

    try {
      await Jaspen.setThreadObjective(persistThreadId, normalized, explicitSetting);
    } catch (err) {
      console.error('[applyStrategyObjective] persist failed', err);
      if (!silent) showToast('Saved locally, but could not sync objective to thread yet.', 'warning');
    }
    return normalized;
  }, [currentSessionId, sessionId, showToast]);


  // AI drawer messages - DO NOT fabricate assistant messages
  // Assistant messages must ONLY come from backend endpoint
// Load conversation history into Assistant when scorecard is shown
// Sidebar Assistant uses the main `messages` thread as the single source of truth.
// (No separate aiMessages state.)

  // Fetch readiness spec on mount (ONCE) - single source, no duplicates
  useEffect(() => {
    const apiBase = API_BASE;
    let abort = false;
    (async () => {
      try {
        const res = await fetch(`${apiBase}/api/v1/ai-agent/readiness/spec`, { credentials: 'include' });
        if (!res.ok) return;
        const json = await res.json();
        if (abort) return;

        setReadinessSpec(json || null);
        setReadinessVersion(json?.version || null);

        const map = {};
        for (const c of (json?.categories || [])) {
          map[c.key] = { label: c.label || c.key, weight: c.weight ?? null };
        }
        setSpecMap(map);
      } catch (e) {
        console.error('[fetchReadinessSpec] failed', e);
      }
    })();
    return () => { abort = true; };
  }, []);
  
  useEffect(() => {
    fetchSessions();
  }, []);

  const loadSavedStarters = useCallback(async () => {
    setStartersLoading(true);
    try {
      const resp = await Jaspen.listStarters();
      const rows = Array.isArray(resp?.starters) ? resp.starters : [];
      setSavedStarterConfigs(rows);
    } catch (err) {
      console.error('[loadSavedStarters] failed', err);
      setSavedStarterConfigs([]);
    } finally {
      setStartersLoading(false);
    }
  }, []);

  useEffect(() => {
    loadSavedStarters();
  }, [loadSavedStarters]);

  useEffect(() => {
    if (sessionId || messages.length > 0) return;
    if (!selectedStarter) return;
    const starterObjective = normalizeStrategyObjective(
      selectedStarter?.objective || selectedStarter?.intake_context?.objective || 'balanced'
    );
    applyStrategyObjective(starterObjective, { persist: false, markExplicit: true, silent: true });
  }, [selectedStarter, sessionId, messages.length, applyStrategyObjective]);

  // --- Chat helper that returns reply + readiness ---
  const chatWithReadiness = async (message, forcedSid) => {
    const sid = (() => {
      if (forcedSid && typeof forcedSid === 'string') {
        const m = document.cookie.match(/(?:^|;\s*)jaspen_sid=([^;]+)/);
        const cookieSid = m ? decodeURIComponent(m[1]) : null;
        if (cookieSid !== forcedSid) {
          document.cookie = `jaspen_sid=${encodeURIComponent(forcedSid)}; Max-Age=${30*24*3600}; Path=/; Secure; SameSite=None`;
        }
        return forcedSid;
      }
      const m = document.cookie.match(/(?:^|;\s*)jaspen_sid=([^;]+)/);
      if (m) return decodeURIComponent(m[1]);
      return null;
    })();

    if (!sid) {
      throw new Error('No active session was found for this conversation.');
    }

    const json = await streamConversationReply({
      threadId: sid,
      userText: message,
      modelType: selectedModelType,
      objective: strategyObjective,
    });
    return {
      ...json,
      text: json.reply || json.message || '',
      readiness: json.readiness || null,
      sessionId: json.session_id || sid,
      actions: json.actions || json.ui_actions || json.uiActions || [],
      mutations: Array.isArray(json.mutations)
        ? json.mutations
        : (Array.isArray(json.tool_results) ? json.tool_results : []),
      model_type: json.model_type || null,
      strategy_objective: json.strategy_objective || null,
    };

  };

  // Fetch sessions (cookie OR bearer)
  const fetchSessions = async () => {
    try {
      const [threadResponse, scoresResponse] = await Promise.all([
        authFetch(`${API_BASE}/api/v1/ai-agent/threads`, {
          method: 'GET',
          headers: buildAuthHeaders({}, 'GET'),
          credentials: 'include'
        }),
        authFetch(`${API_BASE}/api/v1/strategy/scores?limit=200`, {
          method: 'GET',
          headers: buildAuthHeaders({}, 'GET'),
          credentials: 'include'
        }),
      ]);

      if (threadResponse.status === 401 || scoresResponse.status === 401) {
        await handleUnauthorized();
        setAnalysisHistory([]);
        return;
      }

      const completedById = new Map();

      if (scoresResponse.ok) {
        const scoreData = await scoresResponse.json().catch(() => ({}));
        const scoreRows = Array.isArray(scoreData?.scores) ? scoreData.scores : [];
        for (const row of scoreRows) {
          const threadId = String(row?.thread_id || '').trim();
          if (!threadId) continue;
          const serverTimestamp = parseHistoryTimestamp(row?.updated_at || row?.created_at || Date.now());
          completedById.set(threadId, {
            id: threadId,
            createdAt: serverTimestamp,
            lastUsedAt: serverTimestamp,
            result: {
              analysis_id: threadId,
              project_name: row?.project_name || 'Untitled Idea',
              _owner_thread_id: threadId,
              jaspen_score: row?.jaspen_score,
              score_category: row?.score_category,
              component_scores: row?.component_scores || {},
              financial_impact: row?.financial_impact || {},
              status: 'completed',
              strategy_objective: normalizeStrategyObjective(row?.strategy_objective || 'balanced'),
            },
          });
        }
      }

      if (!threadResponse.ok) {
        setAnalysisHistory(Array.from(completedById.values()).sort((a, b) => Number(b.lastUsedAt || b.createdAt || 0) - Number(a.lastUsedAt || a.createdAt || 0)));
        return;
      }

      const data = await threadResponse.json().catch(() => ({}));
      if (!(data.success && data.sessions)) {
        setAnalysisHistory(Array.from(completedById.values()).sort((a, b) => Number(b.lastUsedAt || b.createdAt || 0) - Number(a.lastUsedAt || a.createdAt || 0)));
        return;
      }

      const shouldScopeSelfServe = isSelfServePlan(user?.subscription_plan) && Boolean(user?.id);
      const scopedSessions = shouldScopeSelfServe
        ? data.sessions.filter((session) => String(session?.user_id || '') === String(user.id))
        : data.sessions;

      for (const session of scopedSessions) {
        const threadId = String(session?.session_id || '').trim();
        if (!threadId) continue;

        const sessionResult = getDisplayScorecardResult(
          (session && typeof session.result === 'object') ? session.result : null,
          threadId,
        );
        const historyResult = getDisplayScorecardResult(extractMeaningfulHistoryResult(
          Array.isArray(session.analysis_history) ? session.analysis_history : session.analyses
        ), threadId);
        const full = hasMeaningfulScorecardData(sessionResult)
          ? sessionResult
          : (hasMeaningfulScorecardData(historyResult) ? historyResult : {});

        const hasCompletedScorecard = hasMeaningfulScorecardData(full) || completedById.has(threadId);
        if (hasCompletedScorecard) {
          const existing = completedById.get(threadId);
          const serverTimestamp = parseHistoryTimestamp(session.timestamp || session.created || existing?.createdAt || Date.now());
          const lastUserMessageAt = getLastUserMessageTimestamp(
            full.chat_history ?? session.chat_history,
            existing?.lastUsedAt || serverTimestamp
          );
          completedById.set(threadId, {
            id: threadId,
            createdAt: serverTimestamp,
            lastUsedAt: lastUserMessageAt,
            result: {
              ...(existing?.result || {}),
              ...full,
              analysis_id: full.analysis_id ?? existing?.result?.analysis_id ?? threadId,
              project_name: full.project_name ?? existing?.result?.project_name ?? session.name ?? 'Untitled Idea',
              _owner_thread_id: threadId,
              jaspen_score: full.jaspen_score ?? existing?.result?.jaspen_score ?? session.score,
              status: 'completed',
              chat_history: full.chat_history ?? session.chat_history,
              readiness: normalizeReadiness(full.readiness ?? session.readiness),
              collected_data: full.collected_data ?? session.collected_data,
              strategy_objective: normalizeStrategyObjective(
                full.strategy_objective ?? existing?.result?.strategy_objective ?? session.strategy_objective ?? 'balanced'
              ),
              objective_explicitly_set: Boolean(
                full.objective_explicitly_set ?? existing?.result?.objective_explicitly_set ?? session.objective_explicitly_set
              ),
            },
          });
          continue;
        }

        const createdAt = parseHistoryTimestamp(session.timestamp || session.created);
        const lastUserMessageAt = getLastUserMessageTimestamp(session.chat_history, createdAt);
        completedById.set(threadId, {
          id: threadId,
          createdAt,
          lastUsedAt: lastUserMessageAt,
          result: {
            analysis_id: threadId,
            project_name: session.name ?? 'Untitled Idea',
            _owner_thread_id: threadId,
            status: session.status,
            chat_history: session.chat_history,
            readiness: normalizeReadiness(session.readiness),
            collected_data: session.collected_data,
            strategy_objective: normalizeStrategyObjective(session.strategy_objective ?? 'balanced'),
            objective_explicitly_set: Boolean(session.objective_explicitly_set),
          },
        });
      }

      const apiSessions = Array.from(completedById.values());
      apiSessions.sort((a, b) => Number(b.lastUsedAt || b.createdAt || 0) - Number(a.lastUsedAt || a.createdAt || 0));
      setAnalysisHistory(apiSessions);
    } catch (error) {
      console.error('Error fetching sessions:', error);
      setAnalysisHistory([]);
    } finally {
      setSessionsLoading(false);
    }
  };

// Fetch a full session by id (chat_history + readiness.categories + collected_data)
async function loadSessionById(id) {
  if (!id) return null;

  const apiBase = API_BASE;
  const url = `${apiBase}/api/v1/ai-agent/threads/${encodeURIComponent(id )}`;

  try {
    // Attempt 1: NEW AI Agent thread fetch (JWT + cookie)
    let resp = await fetch(url, {
      method: 'GET',
      headers: buildAuthHeaders({}, 'GET'),
      credentials: 'include',
    });

    // If auth fails, session is no longer valid for this browser context.
    if (resp.status === 401) {
      await handleUnauthorized();
      return null;
    }

    if (!resp.ok) return null;

    const data = await resp.json();
    
    // Transform NEW API response (thread + analyses) to OLD format
    if (data.thread) {
      const thread = data.thread;
      const analyses = data.analyses || [];
      const latestAnalysis = analyses.length > 0 ? analyses[0] : null;
      const latestAnalysisResult = (latestAnalysis && typeof latestAnalysis.result === 'object')
        ? latestAnalysis.result
        : null;
      const sessionResult = getDisplayScorecardResult(
        (data?.session?.result && typeof data.session.result === 'object')
          ? data.session.result
          : null,
        thread.id,
      );
      const historyResult = getDisplayScorecardResult(extractMeaningfulHistoryResult(analyses), thread.id);
      const resolvedResult = hasMeaningfulScorecardData(latestAnalysisResult)
        ? latestAnalysisResult
        : hasMeaningfulScorecardData(sessionResult)
          ? sessionResult
          : hasMeaningfulScorecardData(historyResult)
            ? historyResult
            : null;
      const resolvedReadiness = normalizeReadiness(
        thread.readiness_snapshot || data?.session?.readiness || null
      );
      
      return {
        session_id: thread.id,
        name: thread.name,
        model_type: thread.model_type || null,
        strategy_objective: normalizeStrategyObjective(
          thread.strategy_objective || data?.session?.strategy_objective || 'balanced'
        ),
        objective_explicitly_set: Boolean(
          thread.objective_explicitly_set ?? data?.session?.objective_explicitly_set
        ),
        chat_history: thread.conversation_history || [],
        readiness: resolvedReadiness,
        collected_data: data?.session?.collected_data || {},
        status: resolvedResult || latestAnalysis ? 'completed' : 'in_progress',
        analysis_history: analyses,
        result: resolvedResult ? {
          ...resolvedResult,
          analysis_id:
            resolvedResult.analysis_id ||
            latestAnalysis?.analysis_id ||
            resolvedResult.id ||
            thread.id,
          project_name: resolvedResult.project_name || thread.name,
          chat_history:
            Array.isArray(resolvedResult.chat_history) && resolvedResult.chat_history.length > 0
              ? resolvedResult.chat_history
              : (thread.conversation_history || []),
          readiness: normalizeReadiness(resolvedResult.readiness || resolvedReadiness),
          strategy_objective: normalizeStrategyObjective(
            resolvedResult.strategy_objective ||
            thread.strategy_objective ||
            data?.session?.strategy_objective ||
            'balanced'
          ),
          objective_explicitly_set: Boolean(
            resolvedResult.objective_explicitly_set ??
            thread.objective_explicitly_set ??
            data?.session?.objective_explicitly_set
          ),
        } : null,
      };
    }
    
    // Fallback: if response doesn't have thread structure, try to use as-is
    const raw = (data && (data.session || data)) || null;
    if (!raw) return null;

    const resolvedResult =
      (raw.result && typeof raw.result === 'object' && Object.keys(raw.result).length > 0)
        ? raw.result
        : (data.result && typeof data.result === 'object' && Object.keys(data.result).length > 0)
          ? data.result
          : raw;

    return {
      ...raw,
      result: resolvedResult,
      model_type: raw.model_type || null,
      strategy_objective: normalizeStrategyObjective(raw.strategy_objective || 'balanced'),
      objective_explicitly_set: Boolean(raw.objective_explicitly_set),
      readiness: raw.readiness ? normalizeReadiness(raw.readiness) : normalizeReadiness(null),
    };
  } catch (e) {
    return null;
  }
}

  // GOAL B: Hydrate scorecard sections if missing
  useEffect(() => {
    if (view !== 'summary') return;
    if (!sessionId) return;
    if (!analysisResult) return;
    if (hydratedScorecardRef.current.has(sessionId)) return;

    const isPartial =
      !analysisResult.decision_framework &&
      !analysisResult.investment_analysis &&
      !analysisResult.npv_irr_analysis &&
      !analysisResult.valuation &&
      !analysisResult.before_after_financials;

    if (!isPartial) {
      hydratedScorecardRef.current.add(sessionId);
      return;
    }

    hydratedScorecardRef.current.add(sessionId);

    (async () => {
      try {
        const session = await loadSessionById(sessionId);
        const full = session?.result;
        if (full && typeof full === 'object' && Object.keys(full).length > 0) {
          const normalized = normalizeAnalysis(full);
          setAnalysisResult(normalized);
          baselineRef.current = normalized;
        }
      } catch (e) {
        // no-op: hydration is best-effort
      }
    })();
  }, [view, sessionId, analysisResult]);

  // --------- Auto-open logic (unchanged) ---------
  const firstOpenedFor = useRef(null);
  const prevSessionIdRef = useRef(null);
  const lastSendAtRef = useRef(0);

  useEffect(() => {
    if (sessionId && sessionId !== prevSessionIdRef.current) {
      firstOpenedFor.current = null;
      prevSessionIdRef.current = sessionId;
      dispatchSidebar({ type: 'NEW_SESSION' });
    }
  }, [sessionId]);
// Persist last active Jaspen session so refresh can restore it
useEffect(() => {
  if (!sessionId) return;
  setLastSessionId(sessionId);
}, [sessionId]);

// (removed duplicate /api/v1/readiness/spec effect)

  useEffect(() => {
    const isDesktop = window.matchMedia('(min-width: 769px)').matches;
    if (
      isDesktop &&
      sessionId &&
      messages.length > 0 &&
      !sidebarState.userDismissedReadiness &&
      !sidebarState.readiness &&
      !sidebarState.history &&
      !sidebarState.settings &&
      firstOpenedFor.current !== sessionId
    ) {
      dispatchSidebar({ type: 'OPEN_READINESS' });
      firstOpenedFor.current = sessionId;
    }
  }, [
    sessionId,
    messages.length,
    sidebarState.userDismissedReadiness,
    sidebarState.readiness,
    sidebarState.history,
    sidebarState.settings
  ]);

  useEffect(() => {
    const mq = window.matchMedia('(max-width: 768px)');
    const handler = () => {};
    mq.addEventListener?.('change', handler);
    mq.addListener?.(handler);
    return () => {
      mq.removeEventListener?.('change', handler);
      mq.removeListener?.(handler);
    };
  }, []);

  useEffect(() => {
    if (!hasHistory && sidebarState.history) {
      dispatchSidebar({ type: 'CLOSE_HISTORY' });
    }
  }, [hasHistory, sidebarState.history]);

  // Autoscroll
  const endRef = useRef(null);
  // Skip exactly one server readiness ping (used right after restoring a session)
  const skipPingRef = useRef(false);
  // Auto-restore previous session on refresh (URL sid > localStorage sid)
  const didAutoRestoreRef = useRef(false);
  // (moved above to avoid TDZ / ReferenceError)

  useEffect(() => {
    if (didAutoRestoreRef.current) return;
    didAutoRestoreRef.current = true;

    (async () => {
      // Prefer URL sid, fallback to localStorage
      const urlSid = (() => {
        try { return new URLSearchParams(window.location.search).get('sid'); }
        catch { return null; }
      })();
      const urlSessionId = (() => {
        try { return new URLSearchParams(window.location.search).get('session_id'); }
        catch { return null; }
      })();
      const resolvedUrlSessionId = urlSid || urlSessionId;

      // GOAL A: If there is no ?sid=, do NOT restore anything.
      // Force the workspace to the default intake state.
      if (!resolvedUrlSessionId) {
        setSessionId(null);
        setCurrentSessionId(null);
        setAnalysisResult(null);
        setMessages([]);
        setStrategyObjective('balanced');
        setObjectiveExplicitlySet(false);
// (removed) sidebar uses main `messages` as the thread source of truth
        setCollectedData({});
        setReadinessAudit(null);
        setView('intake');
        setActiveTab('summary');
        dispatchSidebar({ type: 'CLOSE_ALL' });
        setInitialRestorePending(false);
        return;
      }
      const sid = resolvedUrlSessionId;

      // prevent readiness “snap” edge cases during restore
      skipPingRef.current = true;

      let session = await loadSessionById(sid);
      let restoreBundle = null;

      // Fallback: if session detail is blocked by auth on refresh, restore via thread bundle
      if (!session) {
        try {
          restoreBundle = await Jaspen.getThreadBundle(sid, { msg_limit: 50, scn_limit: 50 });

          // Normalize bundle messages into the same chat_history shape your UI expects
          const bundleMsgs = Array.isArray(restoreBundle?.messages) ? restoreBundle.messages : [];
          const chat_history = bundleMsgs.map((m) => ({
            role: m.role || (m.sender === 'user' ? 'user' : 'assistant'),
            content: m.content || m.text || m.message || '',
          })).filter(x => (x.content || '').trim().length > 0);

          session = {
            session_id: sid,
            chat_history,
            collected_data: restoreBundle?.collected_data || {},
            status: restoreBundle?.status || 'in_progress',
            result: restoreBundle?.result || restoreBundle?.analysis_result || null,
            score: restoreBundle?.score ?? null,
            strategy_objective: normalizeStrategyObjective(
              restoreBundle?.strategy_objective || restoreBundle?.thread?.strategy_objective || 'balanced'
            ),
            objective_explicitly_set: false,
          };
        } catch (e) {
        }
      }

      if (!restoreBundle) {
        try {
          restoreBundle = await Jaspen.getThreadBundle(sid, { msg_limit: 50, scn_limit: 50 });
        } catch (e) {
        }
      }

      if (!session) {
        setInitialRestorePending(false);
        return;
      }

      setSessionId(sid);
      setCurrentSessionId(sid);
      setLastSessionId(sid);
      const restoredModelType = String(session?.model_type || '').toLowerCase();
      if (restoredModelType && allowedModelTypes.includes(restoredModelType)) {
        setSelectedModelType(restoredModelType);
      }
      setStrategyObjective(normalizeStrategyObjective(session?.strategy_objective || 'balanced'));
      setObjectiveExplicitlySet(Boolean(session?.objective_explicitly_set));

// Restore chat history (support both session.chat_history and session.result.chat_history)
const rawHistory =
  (Array.isArray(session?.chat_history) && session.chat_history.length > 0)
    ? session.chat_history
    : (Array.isArray(session?.result?.chat_history) && session.result.chat_history.length > 0)
      ? session.result.chat_history
      : [];

if (rawHistory.length > 0) {
  setMessages(toUiMessages(rawHistory));
}
      applyPersistedReadinessSnapshot(session?.readiness || null);
      // Restore collected_data
      if (session.collected_data && typeof session.collected_data === 'object') {
        setCollectedData(session.collected_data);
      }

      // Restore scorecard (completed sessions)
      const currentScorecard = restoreBundle?.current_scorecard || null;
      const baselineScorecard = restoreBundle?.baseline_scorecard || null;
      const persistedRestoreSnapshots = Array.isArray(restoreBundle?.scorecard_snapshots)
        ? restoreBundle.scorecard_snapshots
        : [];
      const scenarioScorecards = Array.isArray(restoreBundle?.scenarios)
        ? restoreBundle.scenarios
            .map((entry) => entry?.scorecard || entry?.analysis_result || entry?.result || null)
            .filter((entry) => entry && typeof entry === 'object')
        : [];
      const restoreSnapshots = persistedRestoreSnapshots.length > 0
        ? buildMergedScorecardSnapshots({
            analysisResult: null,
            bundleBaselineScorecard: baselineScorecard,
            baselineScorecardId:
              baselineScorecard?.analysis_id ||
              baselineScorecard?.id ||
              baselineScorecard?.analysisId ||
              sid,
            scorecardSnapshots: persistedRestoreSnapshots,
            sessionId: sid,
          })
        : buildScorecardSnapshots({
            threadId: sid,
            baselineScorecard,
            currentScorecard,
            scenarioScorecards,
          });
      const restoreBaselineId =
        baselineScorecard?.analysis_id ||
        baselineScorecard?.id ||
        baselineScorecard?.analysisId ||
        restoreSnapshots.find((snapshot) => snapshot?.isBaseline)?.id ||
        null;
      const restoreSelectedId = String(
        restoreBundle?.selected_scorecard_id ||
        currentScorecard?.analysis_id ||
        currentScorecard?.id ||
        currentScorecard?.analysisId ||
        restoreBaselineId ||
        ''
      ).trim();
      const restoreHistory = Array.isArray(session?.analysis_history) ? session.analysis_history : analysisHistory;
      const restoreBaseResult =
        hasMeaningfulScorecardData(session?.result) ? session.result : session?.result || null;
      const restoreInitialView =
        session?.status === 'completed' ||
        session?.score != null ||
        restoreSnapshots.length > 0 ||
        hasMeaningfulScorecardData(restoreBaseResult)
          ? 'summary'
          : 'intake';
      const restoreContext = resolveScoreWorkspaceContext({
        analysisHistory: restoreHistory,
        sessionId: sid,
        currentSessionId: sid,
        selectedScorecardId: restoreSelectedId,
        scorecardSnapshots: restoreSnapshots,
        selectedVariant: null,
        analysisResult: restoreBaseResult,
        bundleCurrentScorecard: currentScorecard,
        bundleBaselineScorecard: baselineScorecard,
        view: restoreInitialView,
        activeTab: 'summary',
      });
      const restoredOwnerThreadId = restoreContext.ownerThreadId || sid;

      setSessionId(restoredOwnerThreadId);
      setCurrentSessionId(restoredOwnerThreadId);
      setLastSessionId(restoredOwnerThreadId);
      setBundleCurrentScorecard(currentScorecard);
      setBundleBaselineScorecard(baselineScorecard);
      setScorecardSnapshots(restoreSnapshots);
      setBaselineScorecardId(restoreBaselineId);
      setActiveSnapshotId(restoreSelectedId || restoreBaselineId || null);
      setSelectedScorecardId(restoreSelectedId || restoreBaselineId || null);

      if (restoreContext.hasScorecard && hasMeaningfulScorecardData(restoreContext.scorecard)) {
        const rootedScoreResult = buildProjectScoreResult({
          baselineScorecard: baselineScorecard || restoreSnapshots.find((snapshot) => snapshot?.isBaseline) || restoreContext.scorecard,
          snapshots: restoreSnapshots,
          selectedScorecardId: restoreSelectedId || restoreBaselineId || null,
          ownerThreadId: restoredOwnerThreadId,
          existingResult: restoreBaseResult,
          fallbackScorecard: restoreContext.scorecard,
        });
        baselineRef.current = rootedScoreResult._baseline_scorecard;
        setAnalysisResult(rootedScoreResult);
        setView('summary');
        setActiveTab('summary');
      } else {
        setView('intake');
      }

      // Always refresh readiness + scenarios from backend truth
      fetchReadinessFor(restoredOwnerThreadId);
      refreshBundle(restoredOwnerThreadId);
      setInitialRestorePending(false);
    })();

    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [allowedModelTypes, applyPersistedReadinessSnapshot]);

  const scrollToEnd = () => endRef.current?.scrollIntoView({ behavior: 'smooth' });
  useEffect(scrollToEnd, [messages, busy]);

  const syncAiDrawerToBottom = useCallback(() => {
    const node = aiMessagesRef.current;
    const endNode = aiMessagesEndRef.current;
    if (!node || !endNode) return () => {};
    const run = () => {
      endNode.scrollIntoView({ block: 'end' });
      node.scrollTo({ top: node.scrollHeight, behavior: 'auto' });
    };
    const rafA = window.requestAnimationFrame(run);
    const rafB = window.requestAnimationFrame(() => window.requestAnimationFrame(run));
    const timeoutA = window.setTimeout(run, 60);
    const timeoutB = window.setTimeout(run, 180);
    let resizeObserver = null;
    let mutationObserver = null;
    if (typeof ResizeObserver !== 'undefined') {
      resizeObserver = new ResizeObserver(() => run());
      resizeObserver.observe(node);
    }
    if (typeof MutationObserver !== 'undefined') {
      mutationObserver = new MutationObserver(() => run());
      mutationObserver.observe(node, { childList: true, subtree: true, characterData: true });
    }
    return () => {
      window.cancelAnimationFrame(rafA);
      window.cancelAnimationFrame(rafB);
      window.clearTimeout(timeoutA);
      window.clearTimeout(timeoutB);
      resizeObserver?.disconnect();
      mutationObserver?.disconnect();
    };
  }, []);

  useLayoutEffect(() => {
    if (!aiDrawerOpen) return;
    if (activeTab === 'scenario' && scenarioDrawerView !== 'assistant') return;
    return syncAiDrawerToBottom();
  }, [aiDrawerOpen, activeTab, scenarioDrawerView, messages, busy, syncAiDrawerToBottom]);

  useEffect(() => {
    const panel = aiDrawerPanelRef.current;
    if (!panel || !aiDrawerOpen) return undefined;
    const handleTransitionEnd = (event) => {
      if (event.target !== panel) return;
      if (activeTab === 'scenario' && scenarioDrawerView !== 'assistant') return;
      syncAiDrawerToBottom();
    };
    panel.addEventListener('transitionend', handleTransitionEnd);
    return () => {
      panel.removeEventListener('transitionend', handleTransitionEnd);
    };
  }, [aiDrawerOpen, activeTab, scenarioDrawerView, syncAiDrawerToBottom]);

  // Hoisted function declaration to avoid TDZ issues
  function toConversationHistory(msgs) {
    return msgs.map(m => ({ role: m.role === 'user' ? 'user' : 'assistant', content: m.text }));
  }

  // Fetch readiness snapshot (percent + categories) for a given session id
  // RETURNS the audit payload for immediate use in persistence
async function fetchReadinessFor(sid) {
  if (!sid) {
    devWarn('[fetchReadinessFor] ABORT - no sid provided');
    return null;
  }

  try {
    const apiBase = API_BASE;
    const url = `${apiBase}/api/v1/ai-agent/readiness/audit?thread_id=${encodeURIComponent(sid)}`;

    const res = await fetch(url, {
      method: 'GET',
      credentials: 'include',
      headers: {
        ...buildAuthHeaders({ 'Content-Type': 'application/json' }, 'GET'),
        'X-Session-ID': sid,
      },
    });

    if (!res.ok) throw new Error(`HTTP ${res.status}`);

    const auditPayload = await res.json();

    const overall = {
      percent: Number(auditPayload?.overall?.percent ?? auditPayload?.percent ?? 0),
      source: auditPayload?.overall?.source ?? auditPayload?.source ?? null,
      heur_overall: Number(auditPayload?.overall?.heur_overall ?? auditPayload?.heur_overall ?? 0),
    };
    const pct = Math.max(0, Math.min(100, Math.round(overall.percent || 0)));

    const categories = Array.isArray(auditPayload?.categories) ? auditPayload.categories : [];
    const items = Array.isArray(auditPayload?.items) ? auditPayload.items : [];
    const checklist_summary = auditPayload?.checklist_summary && typeof auditPayload.checklist_summary === 'object'
      ? auditPayload.checklist_summary
      : null;
    const version = auditPayload?.version || null;

    const newAudit = { overall: { ...overall, percent: pct }, categories, items, checklist_summary, version };
    setReadinessAudit(newAudit);
    setReadinessSource(overall.source);
    setReadinessVersion(version);
    // NOTE: Do NOT map readiness categories into collectedData here. Only render from readinessAudit.categories.

    return auditPayload; // Return for immediate use in persistence
  } catch (e) {
    console.error('[fetchReadinessFor] failed', e);
    return null;
  }
}

  // =================== READINESS FETCH ===================
  // Always fetch readiness from backend when sessionId changes
  useEffect(() => {
    if (!sessionId) return;

    // Skip exactly one readiness ping (used for brand-new sessions or restores)
    if (skipPingRef.current) {
      skipPingRef.current = false;
      return;
    }

    // Always fetch from backend - no caching, no fallbacks
    fetchReadinessFor(sessionId);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sessionId]);


  // Restore original chat + show score summary when returning to Discuss (intake)
  useEffect(() => {
    if (view !== 'intake') return;
    if (!sessionId) return;

    const entry =
      analysisHistory.find(s => s.id === sessionId) ||
      analysisHistory.find(s => s.result?.analysis_id === sessionId);

    const hist = entry?.result?.chat_history;
    // Restore chat history as-is - NO FABRICATED MESSAGES
    if ((messages?.length || 0) === 0 && Array.isArray(hist) && hist.length > 0) {
      setMessages(toUiMessages(hist));
    }

    // Readiness is ONLY fetched from backend via fetchReadinessFor - no sync from saved data
  }, [view, sessionId, analysisHistory, messages?.length]);

  useEffect(() => {
    if (view !== 'intake') return;
    const tid = sessionId || currentSessionId;
    if (!tid) return;
    if (readinessAudit?.overall?.percent != null) return;
    void fetchReadinessFor(tid);
  }, [view, sessionId, currentSessionId, readinessAudit]);

  // --- Upload (UI only) ---
  const fileInputRef = useRef(null);
  const chatTabInputRef = useRef(null);
  const intakeInputRef = useRef(null);
  const modelMenuRef = useRef(null);

// ======= UI Readiness - SINGLE SOURCE FROM BACKEND ====================
// ONLY source: readinessAudit.overall.percent from GET /api/v1/readiness/audit
// NO fallbacks, NO cached values, NO guessing
const hasConversationMessages = Array.isArray(messages)
  && messages.some((m) => String(m?.text || '').trim().length > 0);
const uiReadiness = hasConversationMessages && readinessAudit?.overall?.percent != null
  ? clampPercent(readinessAudit.overall.percent)
  : 0;

// Readiness gate (use backend overall.percent via uiReadiness)
const canAnalyze = React.useMemo(() => {
  const hasUserTurns = messages?.some(m => m.role === 'user' && (m.text || '').trim());
return uiReadiness >= 85 && hasUserTurns;
}, [uiReadiness, messages]);

const readinessChecklistItems = useMemo(() => {
  const items = Array.isArray(readinessAudit?.items) ? readinessAudit.items : [];
  if (items.length > 0) {
    return items.map((item, index) => {
      const percent = clampPercent(item?.percent ?? 0);
      const status = String(item?.status || '').toLowerCase();
      const complete = status === 'complete' || item?.completed === true || percent >= 85;
      const inProgress = !complete && (status === 'in_progress' || status === 'partial' || percent >= 45);
      return {
        id: item?.id || item?.key || `item_${index}`,
        label: item?.label || item?.key || `Checklist item ${index + 1}`,
        percent,
        complete,
        inProgress,
        contextModule: item?.context_module || null,
        itemType: item?.type || 'core',
      };
    });
  }

  const categories = Array.isArray(readinessAudit?.categories) ? readinessAudit.categories : [];
  return categories.map((category, index) => {
    const percent = clampPercent(category?.percent ?? 0);
    const complete = category?.completed === true || percent >= 85;
    const inProgress = !complete && percent >= 45;
    return {
      id: category?.key || `cat_${index}`,
      label: category?.label || category?.key || `Checklist item ${index + 1}`,
      percent,
      complete,
      inProgress,
      contextModule: null,
      itemType: 'core',
    };
  });
}, [readinessAudit]);

const readinessChecklistSummary = useMemo(() => {
  const summary = readinessAudit?.checklist_summary;
  if (summary && typeof summary === 'object') {
    const done = Number(summary.complete || 0);
    const inProgress = Number(summary.in_progress || 0);
    const missing = Number(summary.missing || 0);
    const total = Number(summary.total || (done + inProgress + missing));
    return { done, inProgress, missing, total };
  }

  const done = readinessChecklistItems.filter((item) => item.complete).length;
  const inProgress = readinessChecklistItems.filter((item) => !item.complete && item.inProgress).length;
  const missing = readinessChecklistItems.filter((item) => !item.complete && !item.inProgress).length;
  return { done, inProgress, missing, total: readinessChecklistItems.length };
}, [readinessAudit, readinessChecklistItems]);

const renderReadinessChecklistGroup = (title, items, helper = '') => {
  if (!Array.isArray(items) || items.length === 0) return null;
  return (
    <div className="jas-collected-section">
      <h4>{title}</h4>
      {helper ? (
        <p style={{ color: 'var(--color-text-muted)', fontSize: '12px', margin: '0 0 10px' }}>{helper}</p>
      ) : null}
      <div className="jas-checklist">
        {items.map((item) => (
          <label className="jas-check-item" key={item.id}>
            <input type="checkbox" className="jas-check" checked={item.complete} readOnly />
            <div className="jas-check-main">
              <div className="jas-check-label">{item.label}</div>
              <div className="jas-check-meta">
                {item.complete ? 'Captured' : item.inProgress ? `In progress (${item.percent}%)` : 'Missing'}
                {item.contextModule ? ` • ${String(item.contextModule).replace(/_/g, ' ')}` : ''}
              </div>
            </div>
          </label>
        ))}
      </div>
    </div>
  );
};

const renderReadinessChecklist = () => {
  const coreItems = readinessChecklistItems.filter((item) => item.itemType === 'core');
  const objectiveItems = readinessChecklistItems.filter((item) => item.itemType === 'objective');
  const contextItems = readinessChecklistItems.filter((item) => item.itemType === 'context');
  const objectiveLabel = OBJECTIVE_LABEL_BY_KEY[
    readinessAudit?.objective_profile || strategyObjective || 'balanced'
  ] || 'Balanced';

  return (
    <>
      <div className="jas-collected-section">
        <h4>Progress Checklist</h4>
        <p style={{ color: 'var(--color-text-muted)', fontSize: '12px', margin: '0 0 10px' }}>
          {readinessChecklistSummary.done}/{readinessChecklistSummary.total} captured
          {readinessChecklistSummary.inProgress > 0 ? ` • ${readinessChecklistSummary.inProgress} in progress` : ''}
        </p>
      </div>
      {readinessChecklistItems.length > 0 ? (
        <>
          {renderReadinessChecklistGroup('Core Framework', coreItems)}
          {renderReadinessChecklistGroup(
            `${objectiveLabel} Focus Areas`,
            objectiveItems,
            `These buckets adapt to your selected objective so the conversation fills the right gaps first.`
          )}
          {renderReadinessChecklistGroup('Context Signals', contextItems)}
        </>
      ) : (
        <div className="jas-collected-section">
          <p style={{ color: 'var(--color-text-muted)', fontSize: '13px', lineHeight: 1.5, margin: '6px 0 0' }}>
            Ask one more question to start checklist tracking.
          </p>
        </div>
      )}
    </>
  );
};

const renderModelTypeInlinePicker = (className = '') => (
  <div className={`jas-model-picker-inline ${className}`.trim()} ref={modelMenuRef}>
    <button
      type="button"
      className={`jas-model-picker-trigger ${modelMenuOpen ? 'is-open' : ''}`}
      aria-haspopup="listbox"
      aria-expanded={modelMenuOpen}
      aria-label="Select model"
      title="Select model"
      onClick={() => setModelMenuOpen((prev) => !prev)}
      disabled={busy} aria-disabled={busy}
    >
      <span className="jas-model-picker-trigger-text">{selectedModelOption?.withVersion || 'Model'}</span>
      <FontAwesomeIcon icon={faChevronDown} className={`jas-model-picker-caret ${modelMenuOpen ? 'is-open' : ''}`} />
    </button>
    {modelMenuOpen && (
      <div className="jas-model-picker-menu" role="listbox" aria-label="Model options">
        {modelOptions.map((option) => (
          <button
            key={option.key}
            type="button"
            role="option"
            aria-selected={selectedModelType === option.key}
            className={`jas-model-picker-option ${selectedModelType === option.key ? 'is-selected' : ''}`}
            disabled={!option.isAllowed} aria-disabled={!option.isAllowed}
            onClick={() => {
              if (!option.isAllowed) return;
              setSelectedModelType(option.key);
              setModelMenuOpen(false);
            }}
          >
            <span className="jas-model-picker-option-main">{option.withVersion}</span>
            {!option.isAllowed && <span className="jas-model-picker-option-meta">(Upgrade to access)</span>}
            {option.isAllowed && selectedModelType === option.key && (
              <FontAwesomeIcon icon={faCheck} className="jas-model-picker-option-check" />
            )}
          </button>
        ))}
      </div>
    )}
  </div>
);

const renderObjectiveTags = (className = '') => {
  if (objectiveLocked) return null;
  return (
    <div className={`jas-objective-tags ${className}`.trim()}>
      <span className="jas-objective-tags-label">
        {objectiveExplicitlySet ? `Objective: ${objectiveLabel}` : 'Primary objective?'}
      </span>
      {OBJECTIVE_OPTIONS.map((option) => (
        <button
          key={option.key}
          type="button"
          className={`jas-objective-tag ${strategyObjective === option.key ? 'active' : ''}`}
          onClick={() => applyStrategyObjective(option.key, { persist: true, markExplicit: true, silent: true })}
        >
          {option.label}
        </button>
      ))}
    </div>
  );
};

const renderConnectorContextTags = () => {
  if (planCategory !== 'enterprise' && planCategory !== 'team') return null;
  if (!Array.isArray(connectedDataSources) || connectedDataSources.length === 0) return null;
  return (
    <div className="jas-connector-context-tags">
      <span className="jas-connector-context-label">
        {contextSourceLoading ? 'Loading…' : 'Data context'}
      </span>
      {connectedDataSources.map((source) => {
        const isActive = activeContextSourceIds.has(source.id);
        return (
          <button
            key={source.id}
            type="button"
            className={`jas-connector-context-chip ${isActive ? 'active' : ''}`}
            onClick={() => {
              void handleToggleContextSource(source.id, source.label);
            }}
            title={isActive ? `Remove ${source.label} context` : `Add live ${source.label} data as AI context`}
          >
            {isActive && <FontAwesomeIcon icon={faCheck} />}
            {source.label}
          </button>
        );
      })}
    </div>
  );
};

const renderSelectedObjectivePill = (className = '') => {
  if (!objectiveExplicitlySet && !objectiveLocked) return null;
  return (
    <span className={`jas-objective-selection-pill ${className}`.trim()}>
      <span className="jas-objective-selection-pill-text">{objectiveLabel}</span>
      {!objectiveLocked ? (
        <button
          type="button"
          className="jas-objective-selection-pill-clear"
          onClick={() => applyStrategyObjective('balanced', { persist: true, explicit: false, silent: true })}
          aria-label="Remove selected intention"
          title="Remove intention"
          disabled={busy} aria-disabled={busy}
        >
          <FontAwesomeIcon icon={faTimes} />
        </button>
      ) : null}
    </span>
  );
};

const renderSelectedDataContextPills = (className = '') => {
  if (!Array.isArray(connectedDataSources) || connectedDataSources.length === 0) return null;
  const activeSources = connectedDataSources.filter((source) => activeContextSourceIds.has(source.id));
  if (activeSources.length === 0) return null;
  return (
    <div className={`jas-selected-data-context-pills ${className}`.trim()}>
      {activeSources.map((source) => (
        <span key={source.id} className="jas-objective-selection-pill">
          <span className="jas-objective-selection-pill-text">{source.label}</span>
          <button
            type="button"
            className="jas-objective-selection-pill-clear"
            onClick={() => {
              void handleToggleContextSource(source.id, source.label);
            }}
            aria-label={`Remove ${source.label} data context`}
            title={`Remove ${source.label} data context`}
            disabled={busy} aria-disabled={busy}
          >
            <FontAwesomeIcon icon={faTimes} />
          </button>
        </span>
      ))}
    </div>
  );
};

const renderStarterSelector = (className = '') => {
  if (sessionId || messages.length > 0) return null;
  if (!startersLoading && savedStarterConfigs.length === 0) return null;
  return (
    <div className={`jas-starter-selector ${className}`.trim()}>
      <label htmlFor="jas-starter-select">Start from saved configuration</label>
      <div className="jas-starter-selector-row">
        <select
          id="jas-starter-select"
          value={selectedStarterId}
          onChange={(e) => setSelectedStarterId(e.target.value)}
          disabled={busy || startersLoading}
        >
          <option value="">
            {startersLoading ? 'Loading configurations…' : 'Choose saved configuration'}
          </option>
          {savedStarterConfigs.map((starter) => (
            <option key={starter.id} value={starter.id}>
              {starter.name}
            </option>
          ))}
        </select>
        {selectedStarterId && (
          <button
            type="button"
            className="jas-starter-clear-btn"
            onClick={() => setSelectedStarterId('')}
            disabled={busy} aria-disabled={busy}
          >
            Clear
          </button>
        )}
      </div>
      {selectedStarter?.description && (
        <p className="jas-starter-description">{selectedStarter.description}</p>
      )}
    </div>
  );
};

const renderStreamToolStatus = () => {
  if (!busy || !streamToolStatus) return null;
  return (
    <div className="jas-stream-status" aria-live="polite">
      <FontAwesomeIcon icon={faSpinner} spin />
      <span>{streamToolStatus}</span>
    </div>
  );
};

const resizeComposerTextarea = useCallback((el) => {
  if (!el) return;
  el.style.height = 'auto';
  const next = Math.max(44, Math.min(el.scrollHeight, 180));
  el.style.height = `${next}px`;
}, []);

const handleComposerInputChange = useCallback((event) => {
  setInput(event.target.value);
  resizeComposerTextarea(event.target);
}, [resizeComposerTextarea]);

useEffect(() => {
  resizeComposerTextarea(chatTabInputRef.current);
  resizeComposerTextarea(intakeInputRef.current);
}, [input, activeTab, view, resizeComposerTextarea]);

  // Utilities
  const normalize = (s) => (s || '').replace(/\s+/g, ' ').trim().toLowerCase();

  // Readiness helpers
  const clampPct = (v) => Math.max(0, Math.min(100, Math.round(Number(v) || 0)));

  const appendAssistant = (reply) => {
    const clean = (reply || '').trim();
    if (!clean) return;
    setMessages(prev => {
      const lastAi = [...prev].reverse().find(m => m.role === 'ai');
      if (lastAi && normalize(lastAi.text) === normalize(clean)) return prev;
      return [...prev, { role: 'ai', text: clean }];
    });
  };

  const createStreamingAssistantPlaceholder = useCallback(() => {
    const messageId = `stream-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
    setMessages((prev) => [...prev, { id: messageId, role: 'ai', text: '', streaming: true }]);
    return messageId;
  }, []);

  const appendStreamingAssistantDelta = useCallback((messageId, delta) => {
    if (!messageId || !delta) return;
    setMessages((prev) => prev.map((message) => (
      message.id === messageId
        ? { ...message, text: `${message.text || ''}${delta}`, streaming: true }
        : message
    )));
  }, []);

  const finalizeStreamingAssistant = useCallback((messageId, finalText = '', metadata = {}) => {
    setMessages((prev) => prev.map((message) => {
      if (message.id !== messageId) return message;
      const resolvedText = String(finalText || message.text || '').trim();
      return {
        ...message,
        text: resolvedText,
        streaming: false,
        historyIndex: Number.isInteger(metadata?.historyIndex) ? metadata.historyIndex : message.historyIndex,
        feedbackValue: metadata?.feedbackValue || message.feedbackValue || null,
        hasMutations: Boolean(metadata?.hasMutations) || Boolean(message.hasMutations),
        canUndo: typeof metadata?.canUndo === 'boolean' ? metadata.canUndo : Boolean(message.canUndo),
        undoApplied: typeof metadata?.undoApplied === 'boolean' ? metadata.undoApplied : Boolean(message.undoApplied),
        regenerated: Boolean(metadata?.regenerated) || Boolean(message.regenerated),
        alternativesCount: Number.isInteger(metadata?.alternativesCount) ? metadata.alternativesCount : (message.alternativesCount || 0),
      };
    }));
  }, []);

  const setStreamingAssistantError = useCallback((messageId, fallbackText) => {
    setMessages((prev) => prev.map((message) => (
      message.id === messageId
        ? { ...message, text: fallbackText || 'Sorry — I hit an error. Please try again.', streaming: false }
        : message
    )));
  }, []);

  const toolStatusLabel = useCallback((toolName) => {
    switch (String(toolName || '').trim()) {
      case 'add_wbs_task':
      case 'update_wbs_task':
      case 'add_wbs_dependency':
      case 'remove_wbs_task':
      case 'generate_execution_plan':
        return 'Updating execution plan…';
      case 'create_scenario':
        return 'Modeling scenario…';
      case 'rename_thread':
        return 'Renaming initiative…';
      case 'get_readiness_snapshot':
        return 'Checking readiness…';
      case 'get_data_contract':
        return 'Reviewing required inputs…';
      default:
        return 'Working…';
    }
  }, []);

  const streamConversationReply = useCallback(async ({
    threadId,
    userText,
    modelType,
    objective,
    viewContext,
    attachments,
  }) => {
    setIsStreamingReply(true);
    const placeholderId = createStreamingAssistantPlaceholder();
    let finalPayload = null;
    try {
      finalPayload = await Jaspen.streamConversation({
        session_id: threadId,
        user_message: userText,
        model_type: modelType,
        strategy_objective: objective,
        view_context: viewContext && typeof viewContext === 'object' ? viewContext : undefined,
        attachments,
        onDelta: (text) => appendStreamingAssistantDelta(placeholderId, text),
        onToolUse: (event) => setStreamToolStatus(toolStatusLabel(event?.tool)),
        onToolResult: () => setStreamToolStatus(''),
        onToolStatus: (event) => setStreamToolStatus(String(event?.status || '').trim()),
        onDone: (payload) => {
          finalPayload = payload;
          setStreamToolStatus('');
          finalizeStreamingAssistant(placeholderId, payload?.reply || payload?.message || '', {
            historyIndex: Number.isInteger(payload?.assistant_message_index) ? payload.assistant_message_index : null,
            hasMutations: Array.isArray(payload?.mutations) && payload.mutations.length > 0,
            canUndo: Boolean(payload?.undo_available),
          });
        },
      });
      finalizeStreamingAssistant(placeholderId, finalPayload?.reply || finalPayload?.message || '', {
        historyIndex: Number.isInteger(finalPayload?.assistant_message_index) ? finalPayload.assistant_message_index : null,
        hasMutations: Array.isArray(finalPayload?.mutations) && finalPayload.mutations.length > 0,
        canUndo: Boolean(finalPayload?.undo_available),
      });
      setStreamToolStatus('');
      return finalPayload;
    } catch (streamErr) {
      setStreamToolStatus('');
      setStreamingAssistantError(placeholderId, 'Sorry — I hit an error. Please try again.');
      throw streamErr;
    } finally {
      setIsStreamingReply(false);
    }
  }, [
    appendStreamingAssistantDelta,
    createStreamingAssistantPlaceholder,
    finalizeStreamingAssistant,
    setStreamingAssistantError,
    toolStatusLabel,
  ]);

  const streamConversationStartReply = useCallback(async ({
    description,
    modelType,
    objective,
    intakeContext,
    viewContext,
    leverDefaults,
    starterId,
    attachments,
  }) => {
    setIsStreamingReply(true);
    const placeholderId = createStreamingAssistantPlaceholder();
    let finalPayload = null;
    try {
      finalPayload = await Jaspen.streamConversationStart({
        description,
        model_type: modelType,
        strategy_objective: objective,
        intake_context: intakeContext,
        view_context: viewContext && typeof viewContext === 'object' ? viewContext : undefined,
        lever_defaults: leverDefaults,
        starter_id: starterId,
        attachments,
        onDelta: (text) => appendStreamingAssistantDelta(placeholderId, text),
        onToolUse: (event) => setStreamToolStatus(toolStatusLabel(event?.tool)),
        onToolResult: () => setStreamToolStatus(''),
        onToolStatus: (event) => setStreamToolStatus(String(event?.status || '').trim()),
        onDone: (payload) => {
          finalPayload = payload;
          setStreamToolStatus('');
          finalizeStreamingAssistant(placeholderId, payload?.reply || payload?.message || '', {
            historyIndex: Number.isInteger(payload?.assistant_message_index) ? payload.assistant_message_index : null,
            hasMutations: Array.isArray(payload?.mutations) && payload.mutations.length > 0,
            canUndo: Boolean(payload?.undo_available),
          });
        },
      });
      finalizeStreamingAssistant(placeholderId, finalPayload?.reply || finalPayload?.message || '', {
        historyIndex: Number.isInteger(finalPayload?.assistant_message_index) ? finalPayload.assistant_message_index : null,
        hasMutations: Array.isArray(finalPayload?.mutations) && finalPayload.mutations.length > 0,
        canUndo: Boolean(finalPayload?.undo_available),
      });
      setStreamToolStatus('');
      return finalPayload;
    } catch (streamErr) {
      setStreamToolStatus('');
      setStreamingAssistantError(placeholderId, 'Sorry — I hit an error. Please try again.');
      throw streamErr;
    } finally {
      setIsStreamingReply(false);
    }
  }, [
    appendStreamingAssistantDelta,
    createStreamingAssistantPlaceholder,
    finalizeStreamingAssistant,
    setStreamingAssistantError,
    toolStatusLabel,
  ]);

  const handleModelTypeBlocked = useCallback((errorLike) => {
    const payload = errorLike?.data || {};
    const backendAllowed = Array.isArray(payload?.allowed_model_types) ? payload.allowed_model_types : [];
    const nextModel = backendAllowed.length > 0 ? String(backendAllowed[0]).toLowerCase() : defaultModelType;
    if (nextModel) {
      setSelectedModelType(nextModel);
    }
    setBillingModalOpen(true);
    showToast(payload?.error || 'This model requires a higher plan. Please upgrade to continue.', 'info');
  }, [defaultModelType, showToast]);

  // === Auth ===
  const handleLogout = async (e) => {
    e?.preventDefault?.();
    await logout();
  };

  // === Conversation Start ===
  // Flow: Call Jaspen.convoStart → set session → await audit → append message → save
  async function startConversation(description, options = {}) {
    setBusy(true); setError(null);

    // Clear old readiness immediately to show 0% for new conversation
    setReadinessAudit(null);

    try {
      const starterIntakeContext = (selectedStarter && typeof selectedStarter.intake_context === 'object')
        ? selectedStarter.intake_context
        : {};
      const selectedObjectiveLabel = OBJECTIVE_LABEL_BY_KEY[strategyObjective] || OBJECTIVE_LABEL_BY_KEY.balanced;
      const intakeContext = {
        ...starterIntakeContext,
        ...(pendingOnboardingContext && typeof pendingOnboardingContext === 'object' ? pendingOnboardingContext : {}),
        ...(options.intake_context && typeof options.intake_context === 'object' ? options.intake_context : {}),
        objective: selectedObjectiveLabel,
      };
      const leverDefaults = (options.lever_defaults && typeof options.lever_defaults === 'object')
        ? options.lever_defaults
        : (selectedStarter && typeof selectedStarter.lever_defaults === 'object' ? selectedStarter.lever_defaults : undefined);

      // Step 1: Stream the initial assistant reply, not just follow-up turns.
      const dataPromise = streamConversationStartReply({
        description,
        modelType: selectedModelType,
        objective: strategyObjective,
        intakeContext,
        viewContext: chatViewContext,
        leverDefaults,
        starterId: selectedStarter?.id || undefined,
        attachments: Array.isArray(options.attachments) ? options.attachments : [],
      });

      // Let the placeholder stream render instead of showing a blocking overlay.
      setBusy(false);
      const data = await dataPromise;
      syncCreditsFromPayload(data, { refresh: true });

      // Step 2: Set sessionId (must use real thread_id/session_id from backend)
      const sid = data.thread_id || data.session_id;
      if (!sid) {
        throw new Error('Missing thread_id from convoStart response');
      }
      setSessionId(sid);
      setCurrentSessionId(sid);
      dispatchSidebar({ type: "OPEN_READINESS" });

      // Step 3: await GET /api/v1/readiness/audit (authoritative)
      await fetchReadinessFor(sid);
      
      if (data?.model_type) {
        setSelectedModelType(String(data.model_type).toLowerCase());
      }
      setStrategyObjective(normalizeStrategyObjective(data?.strategy_objective || strategyObjective));
      setObjectiveExplicitlySet(Boolean(data?.objective_explicitly_set) || objectiveExplicitlySet);
      await applyMutationRefreshes(data, sid);
      setSelectedStarterId('');
      setPendingOnboardingContext(null);


      // REMOVED - AI Agent backend handles persistence automatically
      // await saveSessionToBackend({...});
      await fetchSessions();
      return sid;
    } catch (e) {
      if (e?.status === 403 && e?.data?.code === 'model_type_not_allowed') {
        handleModelTypeBlocked(e);
        setError(e?.data?.error || 'This model requires a higher plan.');
      } else {
        setError("Could not start the conversation. Please try again.");
      }
      console.error(e);
      return null;
    } finally {
      setBusy(false);
    }
  }

  // === Conversation Continue ===
  // Flow: Call Jaspen.convoContinue → append message → await audit → persist using returned payload
async function continueConversation(userText, options = {}) {
  if (!sessionId) {
    devWarn('[continueConversation] ABORT - no sessionId');
    return null;
  }
  setBusy(true);
  setError(null);

  try {
    const data = await streamConversationReply({
      threadId: sessionId,
      userText,
      modelType: selectedModelType,
      objective: strategyObjective,
      viewContext: chatViewContext,
      attachments: Array.isArray(options.attachments) ? options.attachments : [],
    });
    syncCreditsFromPayload(data, { refresh: true });

    if (data?.model_type) {
      setSelectedModelType(String(data.model_type).toLowerCase());
    }
    setStrategyObjective(normalizeStrategyObjective(data?.strategy_objective || strategyObjective));
    setObjectiveExplicitlySet(Boolean(data?.objective_explicitly_set) || objectiveExplicitlySet);
    await applyMutationRefreshes(data, sessionId);

    // Step 3: await GET /api/v1/readiness/audit
    const auditPayload = await fetchReadinessFor(sessionId);

    const updatedCollected = data?.collected_data || collectedData;
    setCollectedData(updatedCollected);

    // Step 4: Update UI state with new readiness
    if (auditPayload) {
      const pct = clampPercent(auditPayload.overall?.percent ?? 0);
      const categories = Array.isArray(auditPayload?.categories) ? auditPayload.categories : [];
      const items = Array.isArray(auditPayload?.items) ? auditPayload.items : [];
      const checklist_summary = auditPayload?.checklist_summary && typeof auditPayload.checklist_summary === 'object'
        ? auditPayload.checklist_summary
        : null;
      const version = auditPayload?.version || null;

      setReadinessAudit({
        overall: { ...auditPayload.overall, percent: pct },
        categories,
        items,
        checklist_summary,
        version
      });
    } else {
      devWarn('[continueConversation] auditPayload is null/undefined - readiness NOT updated');
    }

    await fetchSessions();

    // Note: AI Agent backend handles persistence automatically
    // No need to call saveSessionToBackend - readiness is already saved by backend

    return sessionId;
  } catch (e) {
    if (e?.status === 403 && e?.data?.code === 'model_type_not_allowed') {
      handleModelTypeBlocked(e);
      setError(e?.data?.error || 'This model requires a higher plan.');
    } else {
      setError("Having trouble continuing the conversation. Please resend.");
    }
    console.error(e);
    return null;
  } finally {
    setBusy(false);
  }
}

async function regenerateLastResponse() {
  if (!activeThreadId || regenerating || busy || isStreamingReply) return;

  const lastIdx = messages.length - 1;
  const lastAi = messages[lastIdx];
  if (!lastAi || lastAi.role !== 'ai') return;

  setRegenerating(true);
  setError(null);

  const originalMessage = { ...lastAi };
  const messageId = `regen-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;

  setMessages((prev) => {
    const updated = [...prev];
    updated[updated.length - 1] = {
      id: messageId,
      role: 'ai',
      text: '',
      streaming: true,
    };
    return updated;
  });

  try {
    const data = await Jaspen.streamRegenerate({
      session_id: activeThreadId,
      model_type: selectedModelType,
      onDelta: (text) => appendStreamingAssistantDelta(messageId, text),
      onToolUse: (event) => setStreamToolStatus(toolStatusLabel(event?.tool)),
      onToolResult: () => setStreamToolStatus(''),
      onToolStatus: (event) => setStreamToolStatus(String(event?.status || '').trim()),
      onDone: (payload) => {
        setStreamToolStatus('');
        finalizeStreamingAssistant(messageId, payload?.reply || payload?.message || '', {
          historyIndex: Number.isInteger(payload?.assistant_message_index) ? payload.assistant_message_index : null,
          regenerated: Boolean(payload?.regenerated),
          alternativesCount: Number.isInteger(payload?.alternatives_count) ? payload.alternatives_count : 0,
        });
      },
    });
    syncCreditsFromPayload(data, { refresh: true });

    finalizeStreamingAssistant(messageId, data?.reply || data?.message || '', {
      historyIndex: Number.isInteger(data?.assistant_message_index) ? data.assistant_message_index : null,
      regenerated: Boolean(data?.regenerated),
      alternativesCount: Number.isInteger(data?.alternatives_count) ? data.alternatives_count : 0,
    });
    setStreamToolStatus('');

    if (data?.model_type) {
      setSelectedModelType(String(data.model_type).toLowerCase());
    }
    await applyMutationRefreshes(data, activeThreadId);

    const auditPayload = await fetchReadinessFor(activeThreadId);
    if (auditPayload) {
      const pct = clampPercent(auditPayload.overall?.percent ?? 0);
      setReadinessAudit({
        overall: { ...auditPayload.overall, percent: pct },
        categories: Array.isArray(auditPayload?.categories) ? auditPayload.categories : [],
        items: Array.isArray(auditPayload?.items) ? auditPayload.items : [],
        checklist_summary: auditPayload?.checklist_summary || null,
        version: auditPayload?.version || null,
      });
    }
  } catch (e) {
    setMessages((prev) => {
      const updated = [...prev];
      const target = updated[updated.length - 1];
      if (target?.id === messageId) {
        updated[updated.length - 1] = originalMessage;
      }
      return updated;
    });
    setStreamToolStatus('');
    showToast(e?.message || 'We could not regenerate that response just now.', 'error', {
      actionLabel: 'Retry',
      onAction: () => {
        void regenerateLastResponse();
      },
    });
  } finally {
    setRegenerating(false);
  }
}

async function undoLastMutationTurn() {
  if (!activeThreadId || undoingMutation || busy || isStreamingReply || regenerating) return;

  const lastIdx = messages.length - 1;
  const lastAi = messages[lastIdx];
  if (!lastAi || lastAi.role !== 'ai' || !lastAi.hasMutations || !lastAi.canUndo) return;

  setUndoingMutation(true);
  setError(null);

  try {
    const data = await Jaspen.undoMutations(activeThreadId);
    setMessages((prev) => prev.map((entry, idx) => (
      idx === prev.length - 1 && entry?.role === 'ai'
        ? {
            ...entry,
            canUndo: false,
            undoApplied: true,
          }
        : entry
    )));

    await refreshBundle(activeThreadId);
    await refreshThreadWbs(activeThreadId);
    await fetchSessions();

    const auditPayload = await fetchReadinessFor(activeThreadId);
    if (auditPayload) {
      const pct = clampPercent(auditPayload.overall?.percent ?? 0);
      setReadinessAudit({
        overall: { ...auditPayload.overall, percent: pct },
        categories: Array.isArray(auditPayload?.categories) ? auditPayload.categories : [],
        items: Array.isArray(auditPayload?.items) ? auditPayload.items : [],
        checklist_summary: auditPayload?.checklist_summary || null,
        version: auditPayload?.version || null,
      });
    }

    showToast(data?.message || 'Reverted the latest AI-applied changes.', 'success');
  } catch (undoError) {
    showToast(undoError?.message || 'We could not undo those changes right now.', 'error', {
      actionLabel: 'Retry',
      onAction: () => {
        void undoLastMutationTurn();
      },
    });
  } finally {
    setUndoingMutation(false);
  }
}
// === Begin Project (confirm + backend create + spinner + navigate) ===
const [beginBusy, setBeginBusy] = useState(false);
const [beginMsg, setBeginMsg] = useState("Generating your project plan…");
const [preflightOpen, setPreflightOpen] = useState(false);
const [preflightQuestions, setPreflightQuestions] = useState([]);
const [preflightAnswers, setPreflightAnswers] = useState({});
const [connectedDataSources, setConnectedDataSources] = useState([]);
const [activeContextSourceIds, setActiveContextSourceIds] = useState(new Set());
const [contextSourceData, setContextSourceData] = useState({});
const [contextSourceLoading, setContextSourceLoading] = useState(false);
const sfConnected = connectedDataSources.some((item) => item.id === 'salesforce_insights');
const sfPipelineLoading = contextSourceLoading && activeContextSourceIds.has('salesforce_insights');
const hasProjectPlan = useMemo(
  () => Array.isArray(threadWbs?.tasks) && threadWbs.tasks.length > 0,
  [threadWbs]
);
const activeScenarioForProject = useMemo(() => {
  const activeId = String(activeSnapshotId || '').trim();
  if (!activeId) return null;
  const snapshots = Array.isArray(scorecardSnapshots) ? scorecardSnapshots : [];
  return snapshots.find((snapshot) => {
    if (!snapshot || typeof snapshot !== 'object') return false;
    const snapshotId = String(snapshot.id || snapshot.analysis_id || '').trim();
    return snapshotId === activeId && !Boolean(snapshot.isBaseline);
  }) || null;
}, [activeSnapshotId, scorecardSnapshots]);
const activeScenarioProjectLabel = useMemo(
  () => String(activeScenarioForProject?.label || '').trim(),
  [activeScenarioForProject]
);

const openExecutionPage = useCallback((threadIdValue) => {
  const tid = String(threadIdValue || '').trim();
  if (!tid) return;
  const nextParams = new URLSearchParams();
  nextParams.set('sid', tid);
  const currentParams = new URLSearchParams(location.search);
  ['admin_preview', 'plan_key', 'role'].forEach((key) => {
    const value = String(currentParams.get(key) || '').trim();
    if (value) nextParams.set(key, value);
  });
  navigate(`/execution-plan?${nextParams.toString()}`);
}, [location.search, navigate]);

const liveStatusMessage = useMemo(() => {
  if (beginBusy) return 'Project setup is in progress.';
  if (!busy) return '';
  if (isStreamingReply) {
    return streamToolStatus || 'Jaspen is responding.';
  }
  return sessionId ? 'Jaspen is thinking.' : 'Jaspen is starting the conversation.';
}, [beginBusy, busy, isStreamingReply, streamToolStatus, sessionId]);

const getActiveScorecardSnapshotForHistory = useCallback(() => {
  const selectedId = String(effectiveSelectedScorecardId || activeScorecardId || '').trim();
  if (selectedId && Array.isArray(scorecardSnapshots)) {
    const selected = scorecardSnapshots.find((item) => String(item?.id || '') === selectedId);
    if (selected && typeof selected === 'object') return cloneScorecardSnapshot(selected);
  }
  if (activeScorecard && typeof activeScorecard === 'object') return cloneScorecardSnapshot(activeScorecard);
  if (analysisResult && typeof analysisResult === 'object') return cloneScorecardSnapshot(analysisResult);
  return null;
}, [activeScorecard, activeScorecardId, analysisResult, effectiveSelectedScorecardId, scorecardSnapshots]);

const getScorecardSnapshotRevision = useCallback((snapshotIdValue = null) => {
  const fallbackSelectedId = String(effectiveSelectedScorecardId || activeScorecardId || activeSnapshotId || '').trim();
  const targetId = String(snapshotIdValue || fallbackSelectedId || '').trim();
  const snapshots = Array.isArray(scorecardSnapshots) ? scorecardSnapshots : [];
  let target = null;
  if (targetId) {
    target = snapshots.find((snapshot) => String(snapshot?.id || snapshot?.analysis_id || '').trim() === targetId) || null;
  }
  if (!target && activeScorecard && typeof activeScorecard === 'object') target = activeScorecard;
  if (!target && analysisResult && typeof analysisResult === 'object') target = analysisResult;
  if (!target || typeof target !== 'object') return null;
  const token = target.createdAt ?? target.updated_at ?? target.timestamp ?? null;
  if (token == null) return null;
  const normalized = String(token).trim();
  return normalized || null;
}, [activeScorecard, activeScorecardId, activeSnapshotId, analysisResult, effectiveSelectedScorecardId, scorecardSnapshots]);

const buildScorecardConcurrencyGuard = useCallback((snapshotIdValue = null) => {
  const expectedSelectedId = String(effectiveSelectedScorecardId || activeScorecardId || activeSnapshotId || '').trim() || null;
  const expectedSnapshotId = String(snapshotIdValue || expectedSelectedId || '').trim() || null;
  const expectedSnapshotRevision = getScorecardSnapshotRevision(expectedSnapshotId);
  return {
    expected_selected_scorecard_id: expectedSelectedId,
    expected_snapshot_id: expectedSnapshotId,
    expected_snapshot_revision: expectedSnapshotRevision,
  };
}, [activeScorecardId, activeSnapshotId, effectiveSelectedScorecardId, getScorecardSnapshotRevision]);

const applySnapshotViaScorecardPatch = useCallback(async (snapshotToApply) => {
  const tid = String(currentSessionId || sessionId || '').trim();
  if (!tid || !snapshotToApply || typeof snapshotToApply !== 'object') return null;

  const selectedId = String(
    effectiveSelectedScorecardId
    || activeScorecardId
    || snapshotToApply.id
    || snapshotToApply.analysis_id
    || ''
  ).trim() || null;
  const patchPayload = buildScorecardRestorePatch(snapshotToApply);
  if (Object.keys(patchPayload).length === 0) return null;
  const concurrencyGuard = buildScorecardConcurrencyGuard(selectedId);

  const headers = buildAuthHeaders({ 'Content-Type': 'application/json' }, 'PATCH');
  const response = await fetch(
    `${API_BASE}/api/v1/strategy/threads/${encodeURIComponent(tid)}/scorecard-patch`,
    {
      method: 'PATCH',
      headers,
      credentials: 'include',
      body: JSON.stringify({
        ...patchPayload,
        selected_scorecard_id: selectedId,
        ...(concurrencyGuard.expected_selected_scorecard_id ? { expected_selected_scorecard_id: concurrencyGuard.expected_selected_scorecard_id } : {}),
        ...(concurrencyGuard.expected_snapshot_id ? { expected_snapshot_id: concurrencyGuard.expected_snapshot_id } : {}),
        ...(concurrencyGuard.expected_snapshot_revision ? { expected_snapshot_revision: concurrencyGuard.expected_snapshot_revision } : {}),
      }),
    }
  );
  if (!response.ok) {
    const errPayload = await response.json().catch(() => ({}));
    const message = errPayload?.error || `HTTP ${response.status}`;
    const err = new Error(message);
    err.status = response.status;
    throw err;
  }
  const payload = await response.json().catch(() => ({}));
  if (payload?.updated_scorecard && typeof payload.updated_scorecard === 'object') {
    setAnalysisResult((prev) => (prev ? { ...prev, ...payload.updated_scorecard } : prev));
    if (payload?.selected_scorecard_id) {
      setSelectedScorecardId(String(payload.selected_scorecard_id));
    }
  }
  await refreshBundle(tid);
  return payload;
}, [
  activeScorecardId,
  currentSessionId,
  effectiveSelectedScorecardId,
  buildScorecardConcurrencyGuard,
  refreshBundle,
  sessionId,
]);

const handleScoreCardFieldEdit = useCallback(async (fieldKey, newValue) => {
  const tid = String(currentSessionId || sessionId || '').trim();
  if (!tid) return;
  const beforeSnapshot = getActiveScorecardSnapshotForHistory();

  const FIELD_MAP = {
    executive: 'executive_summary',
    summary: 'key_insights',
    rationale: 'component_rationale',
    financial: 'financial_impact',
    risks: 'top_risks',
    recommendations: 'recommendations',
    decision: 'decision_framework',
    investment: 'investment_analysis',
    npv: 'npv_irr_analysis',
    valuation: 'valuation',
    assumptions: 'assumptions',
  };
  const fieldName = FIELD_MAP[fieldKey] || fieldKey;

  try {
    const concurrencyGuard = buildScorecardConcurrencyGuard(effectiveSelectedScorecardId || activeScorecardId || null);
    const headers = buildAuthHeaders({ 'Content-Type': 'application/json' }, 'PATCH');
    const response = await fetch(
      `${API_BASE}/api/v1/strategy/threads/${encodeURIComponent(tid)}/scorecard-patch`,
      {
        method: 'PATCH',
        headers,
        credentials: 'include',
        body: JSON.stringify({
          [fieldName]: newValue,
          selected_scorecard_id: effectiveSelectedScorecardId || activeScorecardId || null,
          ...(concurrencyGuard.expected_selected_scorecard_id ? { expected_selected_scorecard_id: concurrencyGuard.expected_selected_scorecard_id } : {}),
          ...(concurrencyGuard.expected_snapshot_id ? { expected_snapshot_id: concurrencyGuard.expected_snapshot_id } : {}),
          ...(concurrencyGuard.expected_snapshot_revision ? { expected_snapshot_revision: concurrencyGuard.expected_snapshot_revision } : {}),
        }),
      }
    );
    if (!response.ok) {
      const errPayload = await response.json().catch(() => ({}));
      const message = errPayload?.error || `HTTP ${response.status}`;
      const err = new Error(message);
      err.status = response.status;
      throw err;
    }
    const payload = await response.json().catch(() => ({}));
    if (payload?.updated_scorecard && typeof payload.updated_scorecard === 'object') {
      setAnalysisResult((prev) => (prev ? { ...prev, ...payload.updated_scorecard } : prev));
      if (payload?.selected_scorecard_id) {
        setSelectedScorecardId(String(payload.selected_scorecard_id));
      }
      if (beforeSnapshot) {
        setScorecardUndoStack((prev) => [
          ...prev,
          {
            before: beforeSnapshot,
            after: cloneScorecardSnapshot(payload.updated_scorecard),
            timestamp: Date.now(),
          },
        ].slice(-30));
        setScorecardRedoStack([]);
      }
    }
    await refreshBundle(tid);
  } catch (err) {
    if (Number(err?.status) === 409) {
      await refreshBundle(tid);
      showToast(err?.message || 'Scorecard changed elsewhere. Refreshed to latest.', 'warning');
      return;
    }
    showToast('Failed to save edit. Changes are local only.', 'warning');
  }
}, [
  activeScorecardId,
  buildScorecardConcurrencyGuard,
  currentSessionId,
  effectiveSelectedScorecardId,
  getActiveScorecardSnapshotForHistory,
  refreshBundle,
  sessionId,
  showToast,
]);

const undoScorecardManualEdit = useCallback(async () => {
  if (scorecardEditHistoryBusy || scorecardUndoStack.length === 0) return;
  const entry = scorecardUndoStack[scorecardUndoStack.length - 1];
  if (!entry?.before) return;
  setScorecardEditHistoryBusy(true);
  try {
    await applySnapshotViaScorecardPatch(entry.before);
    setScorecardUndoStack((prev) => prev.slice(0, -1));
    setScorecardRedoStack((prev) => [
      ...prev,
      {
        before: cloneScorecardSnapshot(entry.before),
        after: cloneScorecardSnapshot(entry.after),
        timestamp: Date.now(),
      },
    ].slice(-30));
    showToast('Reverted scorecard edit.', 'success');
  } catch {
    showToast('Could not undo scorecard edit right now.', 'error');
  } finally {
    setScorecardEditHistoryBusy(false);
  }
}, [applySnapshotViaScorecardPatch, scorecardEditHistoryBusy, scorecardUndoStack, showToast]);

const redoScorecardManualEdit = useCallback(async () => {
  if (scorecardEditHistoryBusy || scorecardRedoStack.length === 0) return;
  const entry = scorecardRedoStack[scorecardRedoStack.length - 1];
  if (!entry?.after) return;
  setScorecardEditHistoryBusy(true);
  try {
    await applySnapshotViaScorecardPatch(entry.after);
    setScorecardRedoStack((prev) => prev.slice(0, -1));
    setScorecardUndoStack((prev) => [
      ...prev,
      {
        before: cloneScorecardSnapshot(entry.before),
        after: cloneScorecardSnapshot(entry.after),
        timestamp: Date.now(),
      },
    ].slice(-30));
    showToast('Reapplied scorecard edit.', 'success');
  } catch {
    showToast('Could not redo scorecard edit right now.', 'error');
  } finally {
    setScorecardEditHistoryBusy(false);
  }
}, [applySnapshotViaScorecardPatch, scorecardEditHistoryBusy, scorecardRedoStack, showToast]);

const canUndoScorecardManualEdit = scorecardUndoStack.length > 0 && !scorecardEditHistoryBusy;
const canRedoScorecardManualEdit = scorecardRedoStack.length > 0 && !scorecardEditHistoryBusy;

useEffect(() => {
  if (planCategory !== 'enterprise' && planCategory !== 'team') {
    setConnectedDataSources([]);
    setActiveContextSourceIds(new Set());
    setContextSourceData({});
    return;
  }
  const loadConnectedSources = async () => {
    try {
      const headers = buildAuthHeaders({}, 'GET');
      const response = await fetch(`${API_BASE}/api/v1/connectors/status`, {
        method: 'GET',
        headers,
        credentials: 'include',
      });
      if (!response.ok) return;
      const data = await response.json().catch(() => ({}));
      const allowed = ['salesforce_insights', 'snowflake_insights', 'servicenow_insights', 'netsuite_insights', 'oracle_fusion_insights'];
      const connected = (Array.isArray(data?.connectors) ? data.connectors : [])
        .filter((item) => item?.connected && allowed.includes(item?.id))
        .map((item) => ({
          id: item.id,
          label: item.label || item.id,
          defaultTable: Array.isArray(item?.snowflake?.table_allowlist) ? (item.snowflake.table_allowlist[0] || '') : '',
        }));
      setConnectedDataSources(connected);
    } catch {}
  };
  loadConnectedSources();
}, [planCategory]);

function formatConnectorContextForAgent(data, connectorType) {
  if (connectorType === 'snowflake' && Array.isArray(data?.rows)) {
    const meta = typeof data?.summary === 'object' && data.summary ? data.summary : {};
    const table = meta.table || 'unknown_table';
    const cols = Array.isArray(meta.used_columns) ? meta.used_columns.join(', ') : 'all columns';
    const rowCount = meta.returned_rows ?? data.rows.length;
    const rowsText = data.rows
      .slice(0, 50)
      .map((row, i) => `Row ${i + 1}: ${JSON.stringify(row)}`)
      .join('\n');
    return (
      `Source: Snowflake | Table: ${table}\n` +
      `Columns available: ${cols}\n` +
      `Rows returned: ${rowCount}\n\n` +
      `DATA:\n${rowsText}`
    );
  }
  if (typeof data?.pipeline_summary === 'string') return data.pipeline_summary;
  if (typeof data?.summary === 'string') return data.summary;
  if (typeof data?.message === 'string') return data.message;
  return JSON.stringify(data).slice(0, 5000);
}

const handleToggleContextSource = useCallback(async (connectorId, label) => {
  const wasActive = activeContextSourceIds.has(connectorId);
  setActiveContextSourceIds((prev) => {
    const next = new Set(prev);
    if (next.has(connectorId)) next.delete(connectorId);
    else next.add(connectorId);
    return next;
  });

  if (wasActive || contextSourceData[connectorId]) return;
  setContextSourceLoading(true);
  try {
    let url = '';
    let method = 'GET';
    let body = null;
    const sourceMeta = connectedDataSources.find((item) => item.id === connectorId);
    if (connectorId === 'salesforce_insights') {
      url = `${API_BASE}/api/v1/connectors/salesforce/pipeline/summary?days=30&limit=50`;
    } else if (connectorId === 'snowflake_insights') {
      url = `${API_BASE}/api/v1/connectors/snowflake/query`;
      method = 'POST';
      const defaultTable = String(sourceMeta?.defaultTable || '').trim();
      if (!defaultTable) {
        throw new Error('Snowflake allowlist is empty. Add at least one table in Connectors first.');
      }
      body = JSON.stringify({
        table: defaultTable,
        limit: 100,
      });
    }

    if (!url) {
      setContextSourceData((prev) => ({
        ...prev,
        [connectorId]: `${label} is connected. Detailed context fetcher will be added as this connector API is finalized.`,
      }));
      showToast(`${label} connected. Context placeholder loaded.`, 'success');
      return;
    }

    const response = await fetch(url, {
      method,
      headers: buildAuthHeaders(method === 'POST' ? { 'Content-Type': 'application/json' } : {}, method),
      credentials: 'include',
      ...(body ? { body } : {}),
    });
    const data = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(data?.error || `Could not load ${label} data.`);
    const MAX_CONNECTOR_CONTEXT_CHARS = 8000;
    const sourceType = connectorId === 'snowflake_insights'
      ? 'snowflake'
      : connectorId === 'salesforce_insights'
        ? 'salesforce'
        : 'generic';
    const summary = formatConnectorContextForAgent(data, sourceType).slice(0, MAX_CONNECTOR_CONTEXT_CHARS).trim();
    if (!summary) throw new Error(`No ${label} context available.`);
    setContextSourceData((prev) => ({ ...prev, [connectorId]: summary }));
    showToast(`${label} data loaded as context.`, 'success');
  } catch {
    showToast(`Could not load ${label} data.`, 'error');
    setActiveContextSourceIds((prev) => {
      const next = new Set(prev);
      next.delete(connectorId);
      return next;
    });
  } finally {
    setContextSourceLoading(false);
  }
}, [activeContextSourceIds, connectedDataSources, contextSourceData, showToast]);

const handleLoadSalesforcePipeline = useCallback(async () => {
  await handleToggleContextSource('salesforce_insights', 'Salesforce');
}, [handleToggleContextSource]);

async function onBeginProject(extraAnswers = null) {
  if (!canAccessExecutionTab) {
    showToast('Upgrade to Essential to begin a project from this scorecard.', 'info');
    setBillingModalOpen(true);
    return;
  }
  if (!canStartOrgProjects) {
    showToast('Only creators and admins can start new projects in a shared workspace.', 'info');
    return;
  }

  const tid = currentSessionId || sessionId;
  if (!tid) {
    showToast('No active session. Start a conversation first.', 'error');
    return;
  }

  const activeScenarioName = activeScenarioProjectLabel;
  const sourceLabel = activeScenarioName
    ? `${activeScenarioName} (Active)`
    : 'Baseline';
  const ok = window.confirm(
    `Build an execution plan based on: ${sourceLabel}?\n\n` +
    `Jaspen will generate a full project WBS from this scorecard context and open it on the Execution page.`
  );
  if (!ok) return;

  setBeginBusy(true);
  setBeginMsg('Building your project plan…');

  try {
    const body = { commit: true };
    if (extraAnswers && Object.keys(extraAnswers).length > 0) {
      body.preflight_answers = extraAnswers;
    }
    const resp = await fetch(
      `${API_BASE}/api/v1/strategy/threads/${encodeURIComponent(tid)}/ai-wbs`,
      {
        method: 'POST',
        headers: buildAuthHeaders({ 'Content-Type': 'application/json' }, 'POST'),
        credentials: 'include',
        body: JSON.stringify(body),
      }
    );

    const json = await resp.json().catch(() => ({}));

    if (json?.needs_preflight === true) {
      setBeginBusy(false);
      setPreflightQuestions(Array.isArray(json.questions) ? json.questions : []);
      setPreflightAnswers({});
      setPreflightOpen(true);
      return;
    }

    if (!resp.ok) {
      const detail = json?.error || json?.detail || `HTTP ${resp.status}`;
      setBeginMsg(`Could not generate plan: ${detail}`);
      setTimeout(() => setBeginBusy(false), 2000);
      return;
    }

    setBeginMsg('Plan ready — opening Execution page…');
    setTimeout(() => {
      setBeginBusy(false);
      openExecutionPage(tid);
    }, 700);
  } catch (e) {
    console.error('[Begin Project] failed', e);
    setBeginMsg('Something went wrong. Please try again.');
    setTimeout(() => setBeginBusy(false), 2000);
  }
}

const handleExecutionRefresh = useCallback(async () => {
  const tid = String(currentSessionId || sessionId || '').trim();
  if (!tid) return;
  await Promise.all([refreshThreadWbs(tid), refreshBundle(tid)]);
}, [currentSessionId, refreshBundle, refreshThreadWbs, sessionId]);

const resolveThreadWbsState = useCallback(async (tid) => {
  const response = await Jaspen.getThreadWbs(tid);
  const currentWbs = (response?.project_wbs && typeof response.project_wbs === 'object')
    ? response.project_wbs
    : { name: 'Execution Plan', tasks: [] };
  const tasks = Array.isArray(currentWbs.tasks) ? [...currentWbs.tasks] : [];
  return { currentWbs, tasks };
}, []);

const handleExecutionTaskUpdate = useCallback(async (taskId, patch = {}) => {
  const tid = String(currentSessionId || sessionId || '').trim();
  if (!tid) throw new Error('No active thread.');
  const nextPatch = patch && typeof patch === 'object' ? patch : {};
  const { currentWbs, tasks } = await resolveThreadWbsState(tid);
  const idx = tasks.findIndex((task) => String(task?.id || '') === String(taskId || ''));
  if (idx < 0) throw new Error('Task not found.');
  tasks[idx] = { ...tasks[idx], ...nextPatch };
  await Jaspen.upsertThreadWbs(tid, { ...currentWbs, tasks });
  await refreshThreadWbs(tid);
}, [currentSessionId, refreshThreadWbs, resolveThreadWbsState, sessionId]);

const handleExecutionTaskAdd = useCallback(async (payload = {}) => {
  const tid = String(currentSessionId || sessionId || '').trim();
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
}, [currentSessionId, refreshThreadWbs, resolveThreadWbsState, sessionId]);

const handleExecutionTaskRemove = useCallback(async (taskId) => {
  const tid = String(currentSessionId || sessionId || '').trim();
  if (!tid) throw new Error('No active thread.');
  const { currentWbs, tasks } = await resolveThreadWbsState(tid);
  const removeId = String(taskId || '').trim();
  if (!removeId) throw new Error('Task id is required.');
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
}, [currentSessionId, refreshThreadWbs, resolveThreadWbsState, sessionId]);

const handleExecutionDependencyAdd = useCallback(async (taskId, dependsOnId) => {
  const tid = String(currentSessionId || sessionId || '').trim();
  if (!tid) throw new Error('No active thread.');
  const sourceTaskId = String(taskId || '').trim();
  const depId = String(dependsOnId || '').trim();
  if (!sourceTaskId || !depId) throw new Error('Task dependency is invalid.');
  if (sourceTaskId === depId) return;
  const { currentWbs, tasks } = await resolveThreadWbsState(tid);
  const idx = tasks.findIndex((task) => String(task?.id || '') === sourceTaskId);
  if (idx < 0) throw new Error('Task not found.');
  const deps = Array.isArray(tasks[idx]?.depends_on) ? [...tasks[idx].depends_on] : [];
  if (!deps.includes(depId)) deps.push(depId);
  tasks[idx] = { ...tasks[idx], depends_on: deps };
  await Jaspen.upsertThreadWbs(tid, { ...currentWbs, tasks });
  await refreshThreadWbs(tid);
}, [currentSessionId, refreshThreadWbs, resolveThreadWbsState, sessionId]);

const openExecutionAssistant = useCallback(() => {
  setAiDrawerOpen(true);
  setScenarioDrawerView('assistant');
  setAiInput('Edit this execution plan: update phases, owners, due dates, dependencies, and priorities.');
}, []);

useEffect(() => {
  const tid = String(currentSessionId || sessionId || '').trim();
  if (!tid) {
    setThreadWbs(null);
    return;
  }
  void refreshThreadWbs(tid);
}, [currentSessionId, refreshThreadWbs, sessionId]);

useEffect(() => {
  if (activeTab !== 'execution') return;
  const tid = String(currentSessionId || sessionId || '').trim();
  if (!tid) {
    setThreadWbs(null);
    return;
  }
  refreshThreadWbs(tid);
}, [activeTab, currentSessionId, refreshThreadWbs, sessionId]);

function handleOpenBatchIdeaThread(threadId) {
  if (!threadId) return;
  setBatchIdeasOpen(false);
  navigate(`/new?sid=${encodeURIComponent(threadId)}`);
}

const openSaveStarterModal = () => {
  const defaultName = deriveIdeaTitle({
    result: activeScorecard || analysisResult,
    messages,
    fallback: 'Starter Configuration',
  });
  setNewStarterName(defaultName.slice(0, 255));
  setNewStarterDescription('');
  setSaveStarterModalOpen(true);
};

const handleSaveStarter = async () => {
  const threadId = currentSessionId || sessionId;
  const name = String(newStarterName || '').trim();
  if (!threadId) {
    showToast('No active thread to save.', 'error');
    return;
  }
  if (!name) {
    showToast('Starter name is required.', 'error');
    return;
  }

  setSavingStarter(true);
  try {
    await Jaspen.createStarter({
      thread_id: threadId,
      name,
      description: String(newStarterDescription || '').trim(),
    });
    await loadSavedStarters();
    setSaveStarterModalOpen(false);
    showToast('Saved as starter configuration.', 'success');
  } catch (err) {
    console.error('[handleSaveStarter] failed', err);
    showToast(err?.message || 'Failed to save starter.', 'error');
  } finally {
    setSavingStarter(false);
  }
};

  const applySnapshotMeta = useCallback((snapshotMeta = {}, { refresh = false, select = false } = {}) => {
    const rawSnapshots = Array.isArray(snapshotMeta?.scorecard_snapshots)
      ? snapshotMeta.scorecard_snapshots
      : null;
    const nextSelectedId = snapshotMeta?.selected_scorecard_id || null;
    const nextSnapshot = snapshotMeta?.snapshot && typeof snapshotMeta.snapshot === 'object'
      ? snapshotMeta.snapshot
      : null;

    // Always merge baseline into the snapshot list so the dropdown never loses
    // the Baseline option after adopt/set-active/rename/delete operations.
    const nextSnapshots = rawSnapshots
      ? buildMergedScorecardSnapshots({
          analysisResult,
          bundleBaselineScorecard,
          baselineScorecardId,
          scorecardSnapshots: rawSnapshots,
          sessionId,
        })
      : null;

    if (nextSnapshots && nextSnapshots.length > 0) {
      setScorecardSnapshots(nextSnapshots);
    } else if (nextSnapshot?.id) {
      setScorecardSnapshots((prev) => {
        const items = Array.isArray(prev) ? prev : [];
        const otherSnapshots = items.filter((item) => {
          const itemId = String(item?.id || item?.analysis_id || '').trim();
          return itemId && itemId !== String(nextSnapshot.id);
        });
        return [...otherSnapshots, nextSnapshot];
      });
    }

    if (nextSelectedId) {
      setActiveSnapshotId(nextSelectedId);
      setSelectedScorecardId((current) => {
        const currentId = String(current || '').trim();
        const nextId = String(nextSelectedId || '').trim();
        const hasCurrentInNext = nextSnapshots
          ? nextSnapshots.some((item) => String(item?.id || item?.analysis_id || '').trim() === currentId)
          : Boolean(currentId);
        if (select || !currentId || !hasCurrentInNext) {
          return nextId;
        }
        return current;
      });
    }

    if (refresh) {
      const tid = currentSessionId || sessionId;
      if (tid) {
        refreshBundle(tid).catch(() => {});
      }
    }
  }, [analysisResult, baselineScorecardId, bundleBaselineScorecard, currentSessionId, refreshBundle, sessionId]);

  const openPlanningReadyAssistant = useCallback((scorecardLabel = 'This scorecard') => {
    const cleanedLabel = String(scorecardLabel || '').trim() || 'This scorecard';
    setAiDrawerOpen(true);
    setScenarioDrawerView('assistant');
    setAiInput(`${cleanedLabel} is now active. Want me to draft the first execution phase?`);
  }, []);

  const handleScenarioAdopt = async (adoptedScenario, label) => {
    if (!adoptedScenario || (!adoptedScenario.id && !adoptedScenario.analysis_id)) {
      devWarn('[handleScenarioAdopt] Invalid scenario:', adoptedScenario);
      showToast('Invalid scenario - cannot set active', 'error');
      return;
    }

    const tid = currentSessionId || sessionId;
    if (!tid) {
      showToast('No active session', 'error');
      return;
    }

    try {
      const scenarioId = adoptedScenario.id || adoptedScenario.analysis_id;
      const response = await Jaspen.adoptScenario(scenarioId, tid);
      // select: true forces the Score tab to switch to the adopted variant
      applySnapshotMeta(response, { refresh: true, select: true });
      setActiveTab('summary');
      setView('summary');
      openPlanningReadyAssistant(label || 'Scenario');
      const confirmPrompt = `${label || 'Scenario'} is active. Do you want me to generate a project WBS now?`;
      setMessages((prev) => [...prev, { role: 'ai', text: confirmPrompt }]);
      persistSidebarExchange(tid, null, confirmPrompt);
      setPostAdoptWbsPrompt({
        threadBundleId: tid,
        scorecardId: scenarioId,
        label: label || 'Scenario',
      });
      showToast(`${label || 'Scenario'} set as active scorecard.`, 'success');
    } catch (err) {
      console.error('[handleScenarioAdopt] failed:', err);
      showToast('Failed to set active scorecard', 'error');
    }
  };

  // === Finish & Analyze ===
  async function onFinishAnalyze() {
    if (!sessionId || busy) {
      devWarn('[Finish&Analyze] blocked', { sessionId, currentSessionId, busy, uiReadiness, canAnalyze, msgCount: messages?.length });
      return;
    }
    setBusy(true);
    setError(null);
    const stopProgress = startManualProgressStatus([
      'Reviewing conversation context…',
      'Scoring strategic dimensions…',
      'Building financial and risk analysis…',
      'Drafting executive score narrative…',
      'Preparing scorecard dashboard…',
    ], 2100);

    const normalize = (r = {}) => {
      const compat = r.compat || {};
      const comps  = r.component_scores || compat.components || {};
      const fin    = r.financial_impact || compat.financials || {};

      let score = Number.parseInt(Number(r.jaspen_score ?? compat.score ?? 0), 10);
      if (!Number.isFinite(score)) score = 0;
      const score_category =
        r.score_category ||
        (score >= 80 ? 'Excellent' : score >= 60 ? 'Good' : score >= 40 ? 'Fair' : 'At Risk');

      const toInt = (v) => {
        const n = Number.parseInt(Number(v), 10);
        return Number.isFinite(n) ? n : 0;
      };
      const component_scores = {
        financial_health:       toInt(comps.financial_health ?? comps.financialHealth ?? comps.financial ?? comps.economics),
        operational_efficiency: toInt(comps.operational_efficiency ?? comps.operationalEfficiency ?? comps.execution ?? comps.operations),
        market_position:        toInt(comps.market_position ?? comps.marketPosition ?? comps.market ?? comps.strategy),
        execution_readiness:    toInt(comps.execution_readiness ?? comps.executionReadiness ?? comps.team ?? comps.readiness),
      };

      const project_name =
        r.project_name || compat.title || r.title || 'Untitled Idea';

      const risks = r.risks || r.top_risks || [];

      return {
        ...r,
        jaspen_score: score,
        score_category,
        component_scores,
        financial_impact: {
          ebitda_at_risk:   fin.ebitda_at_risk   ?? fin.ebitdaAtRisk   ?? fin.ebitda ?? fin.risk,
          potential_loss:   fin.potential_loss   ?? fin.potentialLoss,
          roi_opportunity:  fin.roi_opportunity  ?? fin.roiOpportunity,
          projected_ebitda: fin.projected_ebitda ?? fin.projectedEbitda,
        },
        project_name,
        risks,
      };
    };

    try {
      const transcript = messages
        .map(m => `${m.role === 'user' ? 'User' : 'AI'}: ${m.text}`)
        .join('\n');

      // derive a stable numeric seed from the session id (same inputs => same score)
      const sid  = currentSessionId || sessionId;
      const seed = Number(String(sid).replace(/\D/g, '')) % 2147483647 || 123456;

      const data = await Jaspen.analyzeFromConversation({
        session_id: sid,
        transcript,
        deterministic: true,
        seed,
        model_type: selectedModelType,
      });
      if (data?.model_type) {
        setSelectedModelType(String(data.model_type).toLowerCase());
      }
      setStreamToolStatus('Scoring strategic dimensions…');

      const raw = (data && data.analysis) ? data.analysis : (data && data.analysis_result) ? data.analysis_result : (data || {});

      // Map backend fields to frontend expectations
      const mapped = {
        ...raw,
        jaspen_score: raw.overall_score || raw.jaspen_score || 0,
        component_scores: raw.scores || raw.component_scores || {},
        project_name: raw.name || raw.project_name || deriveIdeaTitle({ messages, fallback: 'Untitled Idea' }),
        inputs: raw.inputs || raw.analysis_result?.inputs || null,
        compat: raw.compat || raw.analysis_result?.compat || null,
      };

      const result = { ...normalize(mapped), analysis_id: sid };

      if (!result || Object.keys(result).length === 0) {
        throw new Error("No analysis_result returned");
      }
      setStreamToolStatus('Building scorecard narrative and recommendations…');

      // Ensure _baseline_scorecard is always set on the analysis result so
      // every downstream consumer (buildMergedScorecardSnapshots, Score tab
      // dropdown, refreshBundle) can find the baseline without fallbacks.
      if (!result._baseline_scorecard || typeof result._baseline_scorecard !== 'object') {
        result._baseline_scorecard = { ...result };
      }
      result.selected_scorecard_id = result.analysis_id || sid;

      setAnalysisResult(result);

      // Mark baseline scorecard
      const baselineSnapshot = {
        ...result._baseline_scorecard,
        id: result.analysis_id || result.id || sessionId,
        label: 'Baseline',
        isBaseline: true,
        createdAt: Date.now(),
      };

      // Initialize scorecardSnapshots with baseline
      setScorecardSnapshots([baselineSnapshot]);
      setSelectedScorecardId(baselineSnapshot.id);
      setBaselineScorecardId(baselineSnapshot.id);
      baselineRef.current = result._baseline_scorecard; // Store baseline reference

      setView('summary');
      setActiveTab('summary');
      setStreamToolStatus('Preparing summary dashboard…');

      const suggestedFollowUps = buildScorecardFollowUpPrompts(
        result,
        deriveIdeaTitle({ result, messages, fallback: 'this initiative' }),
      );
      if (suggestedFollowUps.length > 0) {
        const followUpText = [
          'Ask Jaspen next:',
          ...suggestedFollowUps.slice(0, 3).map((prompt, idx) => `${idx + 1}. ${prompt}`),
        ].join('\n');
        setMessages((prev) => [...prev, { role: 'ai', text: followUpText }]);
      }

      // Let the score dashboard render immediately after a successful analysis.
      // Bundle/history refreshes should enrich the summary, not block navigation to it.
      window.setTimeout(() => {
        void refreshBundle(currentSessionId || sessionId);
        void fetchSessions();
      }, 0);
    } catch (e) {
      if (e?.status === 403 && e?.data?.code === 'model_type_not_allowed') {
        handleModelTypeBlocked(e);
        setError(e?.data?.error || 'This model requires a higher plan.');
      } else {
        setError("Could not build the scorecard yet. Try adding one more detail, then Finish again.");
      }
      console.error(e);
    } finally {
      stopProgress();
      setStreamToolStatus('');
      setBusy(false);
    }
  }

  // === Input handling ===
  async function onSubmit(options = {}) {
    const now = Date.now();
    if (now - (lastSendAtRef.current || 0) < 500) return;
    lastSendAtRef.current = now;

    const text = (input || '').trim();
    if (busy) return;
    if (effectiveIsViewer) {
      showToast('Viewers can review shared projects but cannot edit them.', 'info');
      return;
    }
    const optionFiles = Array.isArray(options?.files) ? options.files : null;
    const selectedFiles = optionFiles ? [...optionFiles] : [...(pendingFiles || [])];
    if (!text && selectedFiles.length === 0) return;
    if (!sessionId && !canStartOrgProjects) {
      showToast('This role can work inside shared projects but cannot start new ones.', 'info');
      return;
    }

    const chatFiles = selectedFiles.filter((item) => isChatAttachmentFile(item));
    const analysisFiles = selectedFiles.filter((item) => !isChatAttachmentFile(item));
    const attachments = selectedFiles.map((item) => ({
      ...buildMessageAttachmentMeta(item),
      uploading: true,
    }));
    const selectedContextIds = [...activeContextSourceIds];
    const selectedContextLabels = selectedContextIds
      .map((id) => connectedDataSources.find((item) => item.id === id)?.label || id)
      .filter(Boolean);
    const activeContextParts = selectedContextIds
      .filter((id) => contextSourceData[id])
      .map((id) => {
        const source = connectedDataSources.find((item) => item.id === id);
        return `[${source?.label || id} Context]\n${contextSourceData[id]}`;
      });
    if (selectedContextIds.length > 0 && activeContextParts.length === 0) {
      showToast('Selected data context is still loading. Please wait a moment, then send again.', 'info');
      return;
    }
    const contextPrefix = activeContextParts.length > 0
      ? `${activeContextParts.join('\n\n')}\n\n---\n\n`
      : '';

    const displayMessageText = (text || '').trim() || (
      chatFiles.length > 0
        ? 'Please review the attached files and help me interpret them.'
        : `Uploaded ${attachments.length} file${attachments.length === 1 ? '' : 's'}`
    );
    const contextLabelSuffix = selectedContextLabels.length > 0
      ? `\n\n[Data context attached: ${selectedContextLabels.join(', ')}]`
      : '';
    const displayMessageTextWithContext = `${displayMessageText}${contextLabelSuffix}`;
    const messageText = `${contextPrefix}${displayMessageText}`.trim();

    setMessages(prev => [
      ...prev,
      {
        role: 'user',
        text: displayMessageTextWithContext,
        attachments,
      },
    ]);

    setInput('');
    setPendingFiles([]);

    const placeholder = messageText;
    let resolvedThreadId = sessionId || currentSessionId || null;
    if (!sessionId) {
      resolvedThreadId = await startConversation(placeholder, {
        attachments: chatFiles.map((item) => item.file).filter(Boolean),
      });
    } else {
      resolvedThreadId = await continueConversation(placeholder, {
        attachments: chatFiles.map((item) => item.file).filter(Boolean),
      });
    }

    if (analysisFiles.length > 0) {
      await analyzeUploadedFiles(analysisFiles, resolvedThreadId, text);
    }
  }

  function onKey(e) {
    const commandSend = e.key === 'Enter' && (e.metaKey || e.ctrlKey);
    const standardSend = e.key === 'Enter' && !e.shiftKey;
    if (commandSend || standardSend) {
      e.preventDefault();
      onSubmit();
    }
  }

  function onFilesSelected(e) {
    const picked = Array.from(e.target.files || []);
    if (!picked.length) return;
    const MAX_FILES_AT_ONCE = 10;
    const toAdd = picked.slice(0, MAX_FILES_AT_ONCE).map((f) => ({
      name: f.name,
      size: f.size,
      type: f.type || 'application/octet-stream',
      file: f,
      preview: f.type?.startsWith('image/') ? URL.createObjectURL(f) : null,
    }));
    const hasDraftText = Boolean(String(input || '').trim());
    const hasPending = Array.isArray(pendingFiles) && pendingFiles.length > 0;
    const canAutoAnalyze =
      !busy &&
      !effectiveIsViewer &&
      !hasDraftText &&
      !hasPending &&
      toAdd.length > 0;

    if (canAutoAnalyze) {
      setPendingFiles(toAdd);
      window.setTimeout(() => {
        void onSubmit({ files: toAdd, auto_upload: true });
      }, 0);
    } else {
      setPendingFiles((prev) => [...prev, ...toAdd]);
    }
    e.target.value = '';
  }

  async function analyzeUploadedFiles(filesToAnalyze, threadForInsights, promptText = '') {
    const validFiles = (Array.isArray(filesToAnalyze) ? filesToAnalyze : []).filter((f) => f?.file);
    if (validFiles.length === 0) return;

    const resolvedThreadId = threadForInsights || currentSessionId || sessionId || null;
    const insightEvents = [];

    for (const item of validFiles) {
      try {
        const resp = await Jaspen.analyzeDataFile({
          file: item.file,
          thread_id: resolvedThreadId || undefined,
          prompt: promptText || undefined,
        });
        const summary = String(resp?.insight?.insight_text || '').trim();
        if (summary) {
          insightEvents.push({
            fileName: item.name,
            summary,
            insight: resp?.insight || null,
          });
        }
      } catch (err) {
        console.error('[analyzeUploadedFiles] failed', err);
        showToast(`Failed to analyze ${item.name}`, 'error');
      }
    }

    if (insightEvents.length > 0) {
      const joined = insightEvents
        .map((evt) => `From ${evt.fileName}: ${evt.summary}`)
        .join('\n\n');
      setMessages((prev) => [...prev, { role: 'ai', text: `AI Insights\n\n${joined}` }]);
      showToast('AI insights added from uploaded data', 'success');

      if (analysisResult) {
        setAnalysisResult((prev) => ({
          ...(prev || {}),
          ai_insights: [
            ...(Array.isArray(prev?.ai_insights) ? prev.ai_insights : []),
            ...insightEvents.map((evt) => ({
              file_name: evt.fileName,
              summary: evt.summary,
              insight: evt.insight,
              timestamp: new Date().toISOString(),
            })),
          ].slice(-10),
        }));
      }
    }
  }

  // === AI Assistant Handlers ===
  const toggleAIDrawer = () => setAiDrawerOpen(!aiDrawerOpen);

  // === Sidebar mini scorecard ===
  const renderMiniScorecard = (result) => {
    if (!result) return null;
    const comps = result.component_scores || result.scores || result.compat?.components || {};
    const score = result.jaspen_score ?? result.overall_score ?? result.score ?? result.compat?.score ?? 0;
    const category = result.score_category ||
      (Number(score) >= 80 ? 'Excellent' : Number(score) >= 60 ? 'Good' : Number(score) >= 40 ? 'Fair' : 'At Risk');
    const items = [
      { key: 'financial_health',       label: 'Financial Health',       val: comps.financial_health ?? comps.financialHealth ?? comps.financial ?? comps.economics ?? 0 },
      { key: 'operational_efficiency', label: 'Operational Efficiency', val: comps.operational_efficiency ?? comps.operationalEfficiency ?? comps.operations ?? comps.execution ?? 0 },
      { key: 'market_position',        label: 'Market Position',        val: comps.market_position ?? comps.marketPosition ?? comps.market ?? comps.strategy ?? 0 },
      { key: 'execution_readiness',    label: 'Execution Readiness',    val: comps.execution_readiness ?? comps.executionReadiness ?? comps.readiness ?? comps.team ?? 0 },
    ];
    const clamp = (n) => Math.max(0, Math.min(100, Math.round(Number(n) || 0)));
    const risks = Array.isArray(result.risks) ? result.risks : [];

    return (
      <div className="jas-mini-scorecard">
        <div className="jas-mini-scorecard-head">
          <div className="jas-mini-project">{deriveIdeaTitle({ result, messages, fallback: 'Untitled Idea' })}</div>
          <div className="jas-mini-scoreline">
            <span className="jas-mini-score">{clamp(score)}</span>
            <span className="jas-mini-outof">/100</span>
            <span className="jas-mini-cat">{category ? `• ${category}` : ''}</span>
          </div>
        </div>

        <div className="jas-mini-components">
          {items.map((it) => (
            <div key={it.key} className="jas-mini-row">
              <div className="jas-mini-row-top">
                <span className="jas-mini-label">{it.label}</span>
                <span className="jas-mini-val">{clamp(it.val)}</span>
              </div>
              <div className="jas-mini-bar">
                <div className="jas-mini-bar-fill" style={{ width: `${clamp(it.val)}%` }} />
              </div>
            </div>
          ))}
        </div>

        {risks.length > 0 && (
          <div className="jas-mini-risks">
            <div className="jas-mini-section-title">Top Risks</div>
            <ul className="jas-mini-risklist">
              {risks.slice(0, 3).map((r, i) => (
                <li key={i}>{String(r)}</li>
              ))}
            </ul>
          </div>
        )}
      </div>
    );
  };

  // === Chat Command Handlers ===
  const chatCommandHandlers = {
    [ChatActionTypes.SCORECARD_SELECT]: (payload) => {
      const { scorecardId } = payload;
      if (scorecardId && scorecardSnapshots.find(s => s.id === scorecardId)) {
        setSelectedScorecardId(scorecardId);
        showToast(`Switched to ${scorecardSnapshots.find(s => s.id === scorecardId)?.label || 'scorecard'}`, 'success');
      } else {
        showToast('Scorecard not found', 'error');
      }
    },
    
[ChatActionTypes.SCORECARD_UPDATE_FIELD]: async (payload) => {
  const {
    scorecardId,
    section,          // e.g. "decision_framework"
    rowLabel,         // e.g. "Overall Recommendation"
    updates           // e.g. { decision: "Maybe", notes: "Funding Needed" }
  } = payload || {};

  const baseId = scorecardId || effectiveSelectedScorecardId || baselineScorecardId;
  if (!baseId) {
    showToast('No scorecard available to update', 'error');
    return;
  }

  // Source scorecard = snapshot if available, else fall back to current analysisResult
  const source =
    (Array.isArray(scorecardSnapshots) ? scorecardSnapshots.find(s => s.id === baseId) : null) ||
    (analysisResult ? { ...analysisResult, id: baseId } : null);

  if (!source) {
    showToast('Scorecard not found', 'error');
    return;
  }

  // Create an edited copy id (baseline stays immutable)
  const editedId = `${baseId}__edited`;

  const applyDecisionFrameworkUpdate = (scorecard) => {
    const df = scorecard?.decision_framework;

    // If decision_framework is not an array, nothing to edit
    if (!Array.isArray(df)) return scorecard;

    const target = String(rowLabel || '').trim();
    const nextDf = df.map((row) => {
      const label = String(row?.label || row?.name || '').trim();
      if (label !== target) return row;

      return {
        ...row,
        ...(updates && typeof updates === 'object' ? updates : {}),
      };
    });

    return { ...scorecard, decision_framework: nextDf };
  };

  let next = { ...source };

  if ((section || '') === 'decision_framework') {
    next = applyDecisionFrameworkUpdate(next);
  } else {
    // Generic fallback: shallow merge
    if (updates && typeof updates === 'object') next = { ...next, ...updates };
  }

  // Mark as edited snapshot
  next = {
    ...next,
    id: editedId,
    label: (source.label ? `${source.label} (Edited)` : 'Edited Scorecard'),
    isBaseline: false,
    createdAt: Date.now(),
  };

  // 1) Upsert edited snapshot + select it
  setScorecardSnapshots((prev) => {
    const arr = Array.isArray(prev) ? prev : [];
    const exists = arr.some(s => s.id === editedId);
    return exists ? arr.map(s => (s.id === editedId ? next : s)) : [...arr, next];
  });

  setSelectedScorecardId(editedId);

  // 2) Tell the AI it happened (this becomes part of the thread context)
  try {
    const changedKeys =
      updates && typeof updates === 'object'
        ? Object.entries(updates).map(([k, v]) => `${k}=${JSON.stringify(v)}`).join(', ')
        : '';
    appendAssistant(
      `✅ Updated ${section || 'scorecard'} → "${rowLabel || ''}"${changedKeys ? ` (${changedKeys})` : ''}.`
    );
  } catch {}

  showToast('Updated scorecard table', 'success');

  // 3) Persist so refresh restores:
  // - Keep original baseline in result._baseline_scorecard (first time only)
  // - Persist snapshots + selected scorecard id inside the result blob
  try {
    const aiThreadId = currentSessionId || sessionId;
    const baselineId = baselineScorecardId || (analysisResult?.analysis_id ?? aiThreadId);

    // Determine baseline snapshot to preserve (if not already preserved)
    const baselineSnap =
      (Array.isArray(scorecardSnapshots) ? scorecardSnapshots.find(s => s.id === baselineId) : null) ||
      (analysisResult ? { ...analysisResult, id: baselineId, label: 'Baseline', isBaseline: true } : null);

    const safeBaseline = baselineSnap ? { ...baselineSnap } : null;
    if (safeBaseline) {
      delete safeBaseline.scorecard_snapshots;
      delete safeBaseline._baseline_scorecard;
      delete safeBaseline.selected_scorecard_id;
    }

    // Build snapshots we want persisted (baseline + edited + others)
    const currentSnaps = Array.isArray(scorecardSnapshots) && scorecardSnapshots.length > 0
      ? scorecardSnapshots
      : (baselineSnap ? [baselineSnap] : []);

    const withEdited = (() => {
      const exists = currentSnaps.some(s => s.id === editedId);
      return exists ? currentSnaps.map(s => (s.id === editedId ? next : s)) : [...currentSnaps, next];
    })();

    // Also ensure baseline has isBaseline true
    const persistedSnaps = withEdited.map(s => {
      if (!s) return s;
      if (s.id === baselineId) return { ...s, isBaseline: true, label: s.label || 'Baseline' };
      return s;
    });

    // Persist: store snapshots + selection inside the result blob
    // IMPORTANT: We do NOT set analysisResult = next (baseline stays baseline in state)
    const resultToPersist = {
      ...(analysisResult || {}),
      _baseline_scorecard: (analysisResult?._baseline_scorecard || safeBaseline || null),
      scorecard_snapshots: persistedSnaps,
      selected_scorecard_id: editedId,
    };

    // REMOVED - AI Agent backend handles persistence automatically
    // await saveSessionToBackend({...});
  } catch (e) {
    console.error('[SCORECARD_UPDATE_FIELD] persist failed', e);
    showToast('Your updates appeared on screen, but we could not save them yet.', 'error');
  }
},
    
        [ChatActionTypes.SCENARIO_SET_INPUT]: (payload) => {
      if (effectiveIsViewer) {
        showToast('Viewers cannot modify scenarios.', 'info');
        return;
      }
      if (!canUseScenarios) {
        showToast('Scenario tools require Essential or higher.', 'info');
        setBillingModalOpen(true);
        return;
      }
      // payload examples:
      // { scenario: 'A', key: 'budget', value: 250000 }
      // { scenarioId: 'scenarioA', lever: 'budget', value: 250000 }
      setActiveTab('scenario');
      setView('scenario');

      const api = scenarioModelerRef.current;
      if (!api || typeof api.setScenarioInput !== 'function') {
        showToast('Scenario inputs are not ready yet', 'error');
        return;
      }

      const ok = api.setScenarioInput(payload);
      if (ok) showToast('Scenario input updated', 'success');
      else showToast('Could not apply scenario input', 'error');
    },

    
        [ChatActionTypes.SCENARIO_RUN]: async (payload) => {
      if (effectiveIsViewer) {
        showToast('Viewers cannot run scenarios.', 'info');
        return;
      }
      if (!canUseScenarios) {
        showToast('Scenario tools require Essential or higher.', 'info');
        setBillingModalOpen(true);
        return;
      }
      setActiveTab('scenario');
      setView('scenario');

      const api = scenarioModelerRef.current;
      if (!api || typeof api.runScenario !== 'function') {
        showToast('Scenario runner is not ready yet', 'error');
        return;
      }

      showToast('Running scenario…', 'info');
      try {
        await api.runScenario(payload);
        showToast('Scenario complete', 'success');
      } catch (e) {
        console.error('[SCENARIO_RUN] failed', e);
        showToast('We could not run that scenario right now.', 'error', {
          actionLabel: 'Retry',
          onAction: () => {
            void api.runScenario(payload).catch(() => {
              showToast('Scenario retry failed. Please try again.', 'error');
            });
          },
        });
      }
    },

    
        [ChatActionTypes.SCENARIO_ADOPT]: async (payload) => {
      if (effectiveIsViewer) {
        showToast('Viewers cannot adopt scenarios.', 'info');
        return;
      }
      if (!canUseScenarios) {
        showToast('Scenario tools require Essential or higher.', 'info');
        setBillingModalOpen(true);
        return;
      }
      setActiveTab('scenario');
      setView('scenario');

      const api = scenarioModelerRef.current;
      if (!api || typeof api.adoptScenario !== 'function') {
        showToast('Scenario adoption is not ready yet', 'error');
        return;
      }

      try {
        const adopted = await api.adoptScenario(payload);
        if (adopted) showToast('Scenario adopted', 'success');
        else showToast('Nothing to adopt yet', 'info');
      } catch (e) {
        console.error('[SCENARIO_ADOPT] failed', e);
        showToast('Scenario adoption failed', 'error');
      }
    },

    [ChatActionTypes.WBS_ADD_TASK]: async (payload) => {
      if (!canUseWbsWrite) {
        showToast('WBS write tools require Essential or higher.', 'info');
        setBillingModalOpen(true);
        return;
      }
      const tid = currentSessionId || sessionId;
      if (!tid) {
        showToast('Start a thread before updating WBS.', 'error');
        return;
      }

      const title = String(payload?.title || payload?.task || payload?.text || '').trim();
      if (!title) {
        showToast('Task title is required.', 'error');
        return;
      }

      try {
        const wbsResp = await Jaspen.getThreadWbs(tid);
        const currentWbs = (wbsResp?.project_wbs && typeof wbsResp.project_wbs === 'object')
          ? wbsResp.project_wbs
          : { name: 'Execution WBS', tasks: [] };
        const tasks = Array.isArray(currentWbs.tasks) ? [...currentWbs.tasks] : [];

        tasks.push({
          id: String(payload?.id || `task_${Date.now()}`),
          title,
          status: String(payload?.status || 'todo').toLowerCase(),
          owner: payload?.owner || '',
          due_date: payload?.due_date || payload?.dueDate || null,
          phase: String(payload?.phase || payload?.phase_name || 'Execution'),
          description: String(payload?.description || ''),
          priority: String(payload?.priority || 'medium').toLowerCase(),
          estimated_days: Number(payload?.estimated_days || payload?.timeline_days || 1),
          timeline_days: Number(payload?.timeline_days || payload?.estimated_days || 1),
          depends_on: Array.isArray(payload?.depends_on) ? payload.depends_on : [],
        });

        await Jaspen.upsertThreadWbs(tid, { ...currentWbs, tasks });
        showToast('Task added to WBS', 'success');
      } catch (e) {
        console.error('[WBS_ADD_TASK] failed', e);
        if (e?.status === 403) setBillingModalOpen(true);
        showToast(e?.message || 'Failed to add task to WBS', 'error');
      }
    },

    [ChatActionTypes.WBS_UPDATE_TASK]: async (payload) => {
      if (!canUseWbsWrite) {
        showToast('WBS write tools require Essential or higher.', 'info');
        setBillingModalOpen(true);
        return;
      }
      const tid = currentSessionId || sessionId;
      if (!tid) {
        showToast('Start a thread before updating WBS.', 'error');
        return;
      }

      const taskId = String(payload?.id || payload?.task_id || '').trim();
      if (!taskId) {
        showToast('Task id is required.', 'error');
        return;
      }

      try {
        const wbsResp = await Jaspen.getThreadWbs(tid);
        const currentWbs = (wbsResp?.project_wbs && typeof wbsResp.project_wbs === 'object')
          ? wbsResp.project_wbs
          : { name: 'Execution WBS', tasks: [] };
        const tasks = Array.isArray(currentWbs.tasks) ? [...currentWbs.tasks] : [];
        const idx = tasks.findIndex((t) => String(t?.id || '') === taskId);
        if (idx < 0) {
          showToast('Task not found in WBS', 'error');
          return;
        }

        tasks[idx] = {
          ...tasks[idx],
          ...(payload?.title ? { title: String(payload.title) } : {}),
          ...(payload?.status ? { status: String(payload.status).toLowerCase() } : {}),
          ...(payload?.owner != null ? { owner: String(payload.owner) } : {}),
          ...(payload?.due_date != null ? { due_date: payload.due_date } : {}),
          ...(payload?.phase ? { phase: String(payload.phase) } : {}),
          ...(payload?.description != null ? { description: String(payload.description) } : {}),
          ...(payload?.priority ? { priority: String(payload.priority).toLowerCase() } : {}),
          ...(payload?.estimated_days != null ? {
            estimated_days: Number(payload.estimated_days),
            timeline_days: Number(payload.estimated_days),
          } : {}),
          ...(payload?.suggested_role != null ? { suggested_role: String(payload.suggested_role) } : {}),
        };

        await Jaspen.upsertThreadWbs(tid, { ...currentWbs, tasks });
        showToast('WBS task updated', 'success');
      } catch (e) {
        console.error('[WBS_UPDATE_TASK] failed', e);
        if (e?.status === 403) setBillingModalOpen(true);
        showToast(e?.message || 'Failed to update WBS task', 'error');
      }
    },

    [ChatActionTypes.WBS_ADD_DEPENDENCY]: async (payload) => {
      if (!canUseWbsWrite) {
        showToast('WBS write tools require Essential or higher.', 'info');
        setBillingModalOpen(true);
        return;
      }
      const tid = currentSessionId || sessionId;
      if (!tid) {
        showToast('Start a thread before updating WBS.', 'error');
        return;
      }

      const taskId = String(payload?.task_id || payload?.taskId || payload?.id || '').trim();
      const dependsOn = String(payload?.depends_on || payload?.dependsOn || '').trim();
      if (!taskId || !dependsOn) {
        showToast('task_id and depends_on are required for dependency updates.', 'error');
        return;
      }

      try {
        const wbsResp = await Jaspen.getThreadWbs(tid);
        const currentWbs = (wbsResp?.project_wbs && typeof wbsResp.project_wbs === 'object')
          ? wbsResp.project_wbs
          : { name: 'Execution WBS', tasks: [] };
        const tasks = Array.isArray(currentWbs.tasks) ? [...currentWbs.tasks] : [];
        const idx = tasks.findIndex((t) => String(t?.id || '') === taskId);
        if (idx < 0) {
          showToast('Task not found in WBS', 'error');
          return;
        }

        const deps = Array.isArray(tasks[idx]?.depends_on) ? [...tasks[idx].depends_on] : [];
        if (!deps.includes(dependsOn) && dependsOn !== taskId) deps.push(dependsOn);
        tasks[idx] = { ...tasks[idx], depends_on: deps };

        await Jaspen.upsertThreadWbs(tid, { ...currentWbs, tasks });
        showToast('WBS dependency added', 'success');
      } catch (e) {
        console.error('[WBS_ADD_DEPENDENCY] failed', e);
        if (e?.status === 403) setBillingModalOpen(true);
        showToast(e?.message || 'Failed to add dependency', 'error');
      }
    },

    [ChatActionTypes.WBS_REMOVE_TASK]: async (payload) => {
      if (!canUseWbsWrite) {
        showToast('WBS write tools require Essential or higher.', 'info');
        setBillingModalOpen(true);
        return;
      }
      const tid = currentSessionId || sessionId;
      if (!tid) {
        showToast('Start a thread before updating WBS.', 'error');
        return;
      }

      const taskId = String(payload?.id || payload?.task_id || '').trim();
      if (!taskId) {
        showToast('Task id is required.', 'error');
        return;
      }

      try {
        const wbsResp = await Jaspen.getThreadWbs(tid);
        const currentWbs = (wbsResp?.project_wbs && typeof wbsResp.project_wbs === 'object')
          ? wbsResp.project_wbs
          : { name: 'Execution WBS', tasks: [] };
        let tasks = Array.isArray(currentWbs.tasks) ? [...currentWbs.tasks] : [];

        const beforeCount = tasks.length;
        tasks = tasks.filter((task) => String(task?.id || '') !== taskId);
        if (tasks.length === beforeCount) {
          showToast('Task not found in WBS', 'error');
          return;
        }

        tasks = tasks.map((task) => ({
          ...task,
          depends_on: Array.isArray(task?.depends_on)
            ? task.depends_on.filter((dep) => dep !== taskId)
            : [],
        }));

        await Jaspen.upsertThreadWbs(tid, { ...currentWbs, tasks });
        showToast('Task removed from WBS', 'success');
      } catch (e) {
        console.error('[WBS_REMOVE_TASK] failed', e);
        if (e?.status === 403) setBillingModalOpen(true);
        showToast(e?.message || 'Failed to remove task', 'error');
      }
    },

    
    [ChatActionTypes.PROJECT_BEGIN]: async (payload) => {
      const scorecardId = payload.scorecardId || effectiveSelectedScorecardId;
      if (!scorecardId) {
        showToast('No scorecard selected', 'error');
        return;
      }
      
      try {
        // Call the beginProject flow
        const projectData = await Jaspen.beginProject({
          threadBundleId: sessionId,
          scorecardId: scorecardId,
          projectName: deriveIdeaTitle({ result: activeScorecard || analysisResult, messages, fallback: 'Untitled Idea' })
        });
        
        showToast('Project created successfully!', 'success');
        
        // Navigate to project planning
        navigate(`/workspace/${sessionId}/project/${projectData.projectId}`, {
          state: { scorecardId, ...projectData }
        });
      } catch (error) {
        console.error('Begin project failed:', error);
        showToast('Failed to create project', 'error');
      }
    },
  };
  
  const { dispatchChatActions } = useChatCommands(chatCommandHandlers);

  const buildAiScenarioProposal = useCallback((resp, instruction, threadId, fallbackObjective = 'balanced') => {
    const suggestion = (resp && typeof resp === 'object' && resp.suggestion && typeof resp.suggestion === 'object')
      ? resp.suggestion
      : {};
    const suggestedDeltas = (suggestion && typeof suggestion.deltas === 'object') ? suggestion.deltas : {};
    const leverReasons = (suggestion && typeof suggestion.reasons === 'object')
      ? suggestion.reasons
      : ((suggestion && typeof suggestion.rationale === 'object') ? suggestion.rationale : {});
    const leverContext = Array.isArray(resp?.lever_context) ? resp.lever_context : [];
    const contextByKey = {};
    leverContext.forEach((lever) => {
      if (!lever || !lever.key) return;
      contextByKey[String(lever.key)] = lever;
    });

    const defaultBounds = (currentValue, leverType) => {
      const current = Number(currentValue || 0);
      if (leverType === 'months') return { min: 1, max: Math.max(24, current * 3 || 24), step: 1 };
      if (leverType === 'percentage') {
        if (current >= 0 && current <= 1) return { min: 0, max: 1, step: 0.01 };
        return { min: 0, max: Math.max(100, current * 2 || 100), step: 0.5 };
      }
      if (leverType === 'currency') {
        const base = Math.max(Math.abs(current), 1000);
        return { min: 0, max: Math.max(current + base * 2, base * 3), step: Math.max(1, Math.round(base * 0.01)) };
      }
      const base = Math.max(Math.abs(current), 10);
      return { min: 0, max: Math.max(current + base * 2, base * 3), step: 1 };
    };

    const rows = Object.entries(suggestedDeltas).map(([key, rawValue]) => {
      const meta = contextByKey[key] || {};
      const current = Number(meta.current ?? 0);
      const type = String(meta.type || 'number');
      const bounds = {
        min: Number(meta.min),
        max: Number(meta.max),
        step: Number(meta.step),
      };
      const fallback = defaultBounds(current, type);
      const rationaleFromSuggestion = String((suggestion.rationale && suggestion.rationale[key]) || '').trim();
      const rationaleFromReasons = String((leverReasons && leverReasons[key]) || '').trim();
      return {
        key,
        label: String(meta.label || key).trim() || key,
        type,
        current: Number.isFinite(current) ? current : 0,
        value: Number(rawValue),
        min: Number.isFinite(bounds.min) ? bounds.min : fallback.min,
        max: Number.isFinite(bounds.max) ? bounds.max : fallback.max,
        step: Number.isFinite(bounds.step) && bounds.step > 0 ? bounds.step : fallback.step,
        rationale: rationaleFromReasons || rationaleFromSuggestion,
      };
    }).filter((row) => Number.isFinite(row.value));

    const availableLevers = leverContext.map((lever) => ({
      key: String(lever.key || ''),
      label: String(lever.label || lever.key || '').trim() || String(lever.key || ''),
      type: String(lever.type || 'number'),
      current: Number(lever.current || 0),
      min: Number(lever.min),
      max: Number(lever.max),
      step: Number(lever.step),
    })).filter((lever) => lever.key);

    const selectedKeys = new Set(rows.map((row) => row.key));
    const firstAvailable = (availableLevers.find((lever) => !selectedKeys.has(lever.key)) || {}).key || '';

    return {
      threadId,
      objective: normalizeStrategyObjective(resp?.strategy_objective || fallbackObjective),
      instruction: String(instruction || '').trim(),
      label: String(suggestion.label || resp?.scenario?.label || 'AI Suggested Scenario').trim() || 'AI Suggested Scenario',
      summary: String(suggestion.summary || '').trim(),
      rows,
      preview: resp?.preview_scorecard || null,
      availableLevers,
      addLeverKey: firstAvailable,
    };
  }, []);

  const proposalDeltas = (proposal) => {
    const out = {};
    (proposal?.rows || []).forEach((row) => {
      const val = Number(row?.value);
      if (!row?.key || !Number.isFinite(val)) return;
      out[row.key] = val;
    });
    return out;
  };

  const setProposalRowValue = (key, value) => {
    setAiScenarioProposal((prev) => {
      if (!prev) return prev;
      return {
        ...prev,
        rows: prev.rows.map((row) => {
          if (row.key !== key) return row;
          return { ...row, value };
        }),
      };
    });
  };

  const setProposalAddLeverKey = (key) => {
    setAiScenarioProposal((prev) => (prev ? { ...prev, addLeverKey: key } : prev));
  };

  const addProposalLever = () => {
    setAiScenarioProposal((prev) => {
      if (!prev) return prev;
      const key = String(prev.addLeverKey || '').trim();
      if (!key) return prev;
      if (prev.rows.some((row) => row.key === key)) return prev;
      const meta = prev.availableLevers.find((lever) => lever.key === key);
      if (!meta) return prev;
      const row = {
        key: meta.key,
        label: meta.label,
        type: meta.type || 'number',
        current: Number(meta.current || 0),
        value: Number(meta.current || 0),
        min: Number.isFinite(meta.min) ? meta.min : 0,
        max: Number.isFinite(meta.max) ? meta.max : Math.max(100, Number(meta.current || 0) * 2 || 100),
        step: Number.isFinite(meta.step) && meta.step > 0 ? meta.step : 1,
        rationale: '',
      };
      const nextRows = [...prev.rows, row];
      const selected = new Set(nextRows.map((item) => item.key));
      const nextAdd = (prev.availableLevers.find((lever) => !selected.has(lever.key)) || {}).key || '';
      return { ...prev, rows: nextRows, addLeverKey: nextAdd };
    });
  };

  const removeProposalLever = (key) => {
    setAiScenarioProposal((prev) => {
      if (!prev) return prev;
      const nextRows = prev.rows.filter((row) => row.key !== key);
      const selected = new Set(nextRows.map((item) => item.key));
      const nextAdd = prev.addLeverKey || (prev.availableLevers.find((lever) => !selected.has(lever.key)) || {}).key || '';
      return { ...prev, rows: nextRows, addLeverKey: nextAdd };
    });
  };

  const previewAiScenarioProposal = async () => {
    if (!aiScenarioProposal?.threadId) return;
    setAiScenarioBusy(true);
    try {
      const resp = await Jaspen.generateAiScenario(aiScenarioProposal.threadId, {
        instruction: aiScenarioProposal.instruction,
        deltas: proposalDeltas(aiScenarioProposal),
        label: aiScenarioProposal.label,
        commit: false,
        model_type: selectedModelType,
        strategy_objective: strategyObjective,
      });
      setStrategyObjective(normalizeStrategyObjective(resp?.strategy_objective || strategyObjective));
      const next = buildAiScenarioProposal(resp, aiScenarioProposal.instruction, aiScenarioProposal.threadId, strategyObjective);
      setAiScenarioProposal((prev) => ({
        ...next,
        label: prev?.label || next.label,
        instruction: prev?.instruction || next.instruction,
      }));
      showToast('Scenario preview updated', 'success');
    } catch (err) {
      console.error('[previewAiScenarioProposal] failed', err);
      showToast(err?.message || 'Failed to refresh scenario preview', 'error');
    } finally {
      setAiScenarioBusy(false);
    }
  };

  const regenerateAiScenarioProposal = async () => {
    if (!aiScenarioProposal?.threadId) return;
    setAiScenarioBusy(true);
    try {
      const resp = await Jaspen.generateAiScenario(aiScenarioProposal.threadId, {
        instruction: aiScenarioProposal.instruction,
        commit: false,
        model_type: selectedModelType,
        strategy_objective: strategyObjective,
      });
      setStrategyObjective(normalizeStrategyObjective(resp?.strategy_objective || strategyObjective));
      const next = buildAiScenarioProposal(resp, aiScenarioProposal.instruction, aiScenarioProposal.threadId, strategyObjective);
      setAiScenarioProposal(next);
      showToast('AI scenario regenerated', 'success');
    } catch (err) {
      console.error('[regenerateAiScenarioProposal] failed', err);
      showToast(err?.message || 'Failed to regenerate AI scenario', 'error');
    } finally {
      setAiScenarioBusy(false);
    }
  };

  const rejectAiScenarioProposal = () => {
    setAiScenarioProposal(null);
    showToast('Scenario suggestion discarded', 'info');
  };

  const acceptAiScenarioProposal = async () => {
    if (!aiScenarioProposal?.threadId) return;
    setAiScenarioBusy(true);
    try {
      const resp = await Jaspen.generateAiScenario(aiScenarioProposal.threadId, {
        instruction: aiScenarioProposal.instruction,
        deltas: proposalDeltas(aiScenarioProposal),
        label: aiScenarioProposal.label,
        commit: true,
        accept: true,
        model_type: selectedModelType,
        strategy_objective: strategyObjective,
      });
      setStrategyObjective(normalizeStrategyObjective(resp?.strategy_objective || strategyObjective));
      await refreshBundle(aiScenarioProposal.threadId);
      setActiveTab('scenario');
      setView('scenario');
      setAiScenarioProposal(null);
      const score = resp?.scenario?.result?.jaspen_score ?? resp?.preview_scorecard?.jaspen_score;
      setMessages((prev) => [
        ...prev,
        { role: 'ai', text: `Scenario accepted: "${aiScenarioProposal.label}"${score != null ? ` (score ${score})` : ''}.` },
      ]);
      showToast('AI scenario applied', 'success');
    } catch (err) {
      console.error('[acceptAiScenarioProposal] failed', err);
      showToast(err?.message || 'Failed to apply AI scenario', 'error');
    } finally {
      setAiScenarioBusy(false);
    }
  };

// Persist a user+assistant exchange (or single-note entry) so it survives logout/login.
const persistSidebarExchange = async (threadId, userText, assistantText) => {
  if (!threadId || (!userText && !assistantText)) return;
  try {
    const msgs = [];
    if (userText) msgs.push({ role: 'user', content: userText });
    if (assistantText) msgs.push({ role: 'assistant', content: assistantText });
    await Jaspen.appendMessages(threadId, msgs);
  } catch (e) {
    devWarn('[persistSidebarExchange] failed', e);
  }
};

const sendAIMessage = async () => {
  const text = (aiInput || '').trim();
  if (!text || !sessionId || busy) return;
  if (effectiveIsViewer) {
    showToast('Viewers can review shared projects but cannot modify them.', 'info');
    return;
  }

  setAiInput('');
  setBusy(true);
  setError(null);

  try {
    // 1) Add the user's message into the ONE shared thread UI
    setMessages(prev => [...prev, { role: 'user', text }]);

    const aiThreadId = editableThreadId || currentSessionId || sessionId;
    const isAffirmativeConfirmation = /^(yes|yep|yeah|confirm|do it|go ahead|generate(?: now)?|create(?: it)?|build(?: it)?|please do|proceed)\b/i.test(text);
    const isNegativeConfirmation = /^(no|not now|cancel|stop|skip|later|don't|do not)\b/i.test(text);

    if (pendingWbsConfirmation && aiThreadId && pendingWbsConfirmation.threadId === aiThreadId) {
      if (isNegativeConfirmation) {
        const notNowReply = 'No problem — I will not generate the project WBS yet. Say "generate execution plan" anytime when you are ready.';
        setMessages((prev) => [...prev, { role: 'ai', text: notNowReply }]);
        await persistSidebarExchange(aiThreadId, text, notNowReply);
        setPendingWbsConfirmation(null);
        return;
      }
      if (isAffirmativeConfirmation) {
        try {
          const aiWbs = await Jaspen.generateAiWbs(aiThreadId, {
            instruction: pendingWbsConfirmation.instruction || 'Generate a recommended project WBS from this scorecard.',
            commit: true,
            model_type: selectedModelType,
            scenario_id: pendingWbsConfirmation.scorecardId || null,
          });
          const taskCount = Array.isArray(aiWbs?.project_wbs?.tasks) ? aiWbs.project_wbs.tasks.length : 0;
          const wbsReply = `Generated an AI project WBS with ${taskCount} tasks. You can now refine it in the project planning views.`;
          setMessages((prev) => [...prev, { role: 'ai', text: wbsReply }]);
          await persistSidebarExchange(aiThreadId, text, wbsReply);
          showToast('AI WBS generated', 'success');
        } catch (wbsErr) {
          console.error('[sendAIMessage] confirmed AI WBS generation failed', wbsErr);
          const failReply = 'I could not generate the project WBS right now. Please try again in a moment.';
          setMessages((prev) => [...prev, { role: 'ai', text: failReply }]);
          await persistSidebarExchange(aiThreadId, text, failReply);
          showToast('Could not generate project WBS', 'error');
        } finally {
          setPendingWbsConfirmation(null);
        }
        return;
      }

      const clarificationReply = 'Please confirm with "yes" to generate the project WBS now, or "not now" to skip.';
      setMessages((prev) => [...prev, { role: 'ai', text: clarificationReply }]);
      await persistSidebarExchange(aiThreadId, text, clarificationReply);
      return;
    }

    // 2) Call the endpoint that can return Interactive actions
    const resp = await chatWithReadiness(text, currentSessionId || sessionId);

    await applyMutationRefreshes(resp, resp?.sessionId || currentSessionId || sessionId);

    // 4) Refresh readiness (authoritative) and persist the full updated thread
    const sidForAudit = resp?.sessionId || currentSessionId || sessionId;
    const auditPayload = await fetchReadinessFor(sidForAudit);

    const readinessObj = auditPayload ? {
      percent: clampPercent(auditPayload.overall?.percent ?? 0),
      categories: auditPayload.categories || [],
      updated_at: new Date().toISOString()
    } : {
      percent: 0,
      categories: [],
      updated_at: new Date().toISOString()
    };

    await fetchSessions();

    // Build the chat_history from the latest visible thread
    const nextChatHistory = [
      ...toConversationHistory(messages),
      { role: 'user', content: text },
      ...(resp?.text ? [{ role: 'assistant', content: resp.text }] : []),
    ];

    // REMOVED - AI Agent backend handles persistence automatically
    // await saveSessionToBackend({...});

    // 5) Interactive actions
    // parseUIActions expects "response-ish" data; provide the fields it might look for.
const actionEnvelope = {
  ...resp,
  reply: resp?.text,
  text: resp?.text,
  actions: resp?.actions || []
};

const uiActions = parseUIActions(actionEnvelope);
    if (uiActions?.length) {
      const results = dispatchChatActions(uiActions);
      results.forEach(({ success, error }) => {
        if (!success) showToast(`Action failed: ${error}`, 'error');
      });
    }
  } catch (err) {
    console.error('[sendAIMessage] failed', err);
  } finally {
    setBusy(false);
  }
};

const handleGenerateAiWbsFromScorecard = useCallback(async ({ threadBundleId, scorecardId } = {}) => {
  const tid = threadBundleId || currentSessionId || sessionId;
  if (!tid || aiWbsBusy) return;

  const scenarioId = (scorecardId && baselineScorecardId && scorecardId !== baselineScorecardId)
    ? scorecardId
    : null;

  setAiWbsBusy(true);
  try {
    const resp = await Jaspen.generateAiWbs(tid, {
      scenario_id: scenarioId,
      commit: true,
      prompt: 'Generate a recommended project WBS from this scorecard.',
      model_type: selectedModelType,
    });
    const taskCount = Array.isArray(resp?.project_wbs?.tasks) ? resp.project_wbs.tasks.length : 0;
    setMessages((prev) => [
      ...prev,
      {
        role: 'ai',
        text: `Generated a project WBS with ${taskCount} tasks${scenarioId ? ` using scenario ${scenarioId}` : ''}.`,
      },
    ]);
    showToast('Generated project plan from scorecard', 'success');
  } catch (err) {
    console.error('[handleGenerateAiWbsFromScorecard] failed', err);
    if (err?.status === 403) setBillingModalOpen(true);
    showToast(err?.message || 'Failed to generate project plan', 'error');
  } finally {
    setAiWbsBusy(false);
  }
}, [aiWbsBusy, baselineScorecardId, currentSessionId, selectedModelType, sessionId, showToast]);

const renderPostAdoptWbsPrompt = () => {
  if (!postAdoptWbsPrompt) return null;
  const scenarioLabel = postAdoptWbsPrompt?.label || 'Scenario';
  return (
    <div
      className="jas-modal-backdrop"
      role="presentation"
      onClick={() => setPostAdoptWbsPrompt(null)}
    >
      <div
        className="jas-account-modal"
        role="dialog"
        aria-modal="true"
        aria-label="Generate execution plan"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="jas-account-modal-header">
          <h3>Generate execution plan now?</h3>
          <button
            type="button"
            className="jas-account-modal-close"
            onClick={() => setPostAdoptWbsPrompt(null)}
            aria-label="Close"
          >
            <FontAwesomeIcon icon={faTimes} />
          </button>
        </div>
        <p style={{ margin: '0 0 16px', color: 'var(--color-text-secondary)' }}>
          {scenarioLabel} is active. Generate a project WBS from this scorecard now, or do it later from the Score tab.
        </p>
        <div className="jas-account-modal-actions">
          <button
            type="button"
            className="jas-account-secondary-btn"
            onClick={() => {
              const payload = postAdoptWbsPrompt;
              const userReply = 'Not now - I will generate the project WBS later.';
              setMessages((prev) => [...prev, { role: 'user', text: userReply }]);
              persistSidebarExchange(payload?.threadBundleId, userReply, null);
              setPostAdoptWbsPrompt(null);
            }}
          >
            Not now
          </button>
          <button
            type="button"
            className="jas-account-portal-btn"
            onClick={async () => {
              const payload = postAdoptWbsPrompt;
              const userReply = 'Yes - generate the project WBS now.';
              setMessages((prev) => [...prev, { role: 'user', text: userReply }]);
              persistSidebarExchange(payload?.threadBundleId, userReply, null);
              setPostAdoptWbsPrompt(null);
              await handleGenerateAiWbsFromScorecard({
                threadBundleId: payload?.threadBundleId,
                scorecardId: payload?.scorecardId,
              });
            }}
          >
            Generate now
          </button>
        </div>
      </div>
    </div>
  );
};

const triggerDownload = useCallback((blob, filename) => {
  if (!(blob instanceof Blob)) return;
  const objectUrl = URL.createObjectURL(blob);
  const link = document.createElement('a');
  link.href = objectUrl;
  link.download = filename || 'jaspen-export';
  document.body.appendChild(link);
  link.click();
  link.remove();
  window.setTimeout(() => URL.revokeObjectURL(objectUrl), 1500);
}, []);

const handleExportScorecardPdf = useCallback(async ({ threadBundleId, scorecardId, projectName } = {}) => {
  const tid = threadBundleId || currentSessionId || sessionId;
  if (!tid) {
    showToast('No active thread to export.', 'error');
    return;
  }
  setExportBusyType('pdf');
  try {
    const { blob, filename } = await Jaspen.downloadScorecardPdf(tid, { scorecardId });
    triggerDownload(blob, filename || `${String(projectName || 'jaspen-scorecard').toLowerCase().replace(/[^a-z0-9._-]+/g, '-')}-scorecard.pdf`);
    showToast('Exported scorecard PDF', 'success');
  } catch (err) {
    console.error('[handleExportScorecardPdf] failed', err);
    if (err?.status === 403) setBillingModalOpen(true);
    showToast(err?.message || 'Failed to export scorecard PDF', 'error');
  } finally {
    setExportBusyType(null);
  }
}, [currentSessionId, sessionId, showToast, triggerDownload]);

const handleExportScorecardPptx = useCallback(async ({ threadBundleId, scorecardId, projectName } = {}) => {
  const tid = threadBundleId || currentSessionId || sessionId;
  if (!tid) {
    showToast('No active thread to export.', 'error');
    return;
  }
  setExportBusyType('pptx');
  try {
    const { blob, filename } = await Jaspen.downloadScorecardPptx(tid, { scorecardId });
    triggerDownload(blob, filename || `${String(projectName || 'jaspen-scorecard').toLowerCase().replace(/[^a-z0-9._-]+/g, '-')}-scorecard.pptx`);
    showToast('Exported scorecard PowerPoint', 'success');
  } catch (err) {
    console.error('[handleExportScorecardPptx] failed', err);
    if (err?.status === 403) setBillingModalOpen(true);
    showToast(err?.message || 'Failed to export scorecard PowerPoint', 'error');
  } finally {
    setExportBusyType(null);
  }
}, [currentSessionId, sessionId, showToast, triggerDownload]);

const handleExportWbsCsv = useCallback(async ({ threadBundleId, projectName } = {}) => {
  const tid = threadBundleId || currentSessionId || sessionId;
  if (!tid) {
    showToast('No active thread to export.', 'error');
    return;
  }
  setExportBusyType('csv');
  try {
    const { blob, filename } = await Jaspen.downloadWbsCsv(tid);
    triggerDownload(blob, filename || `${String(projectName || 'jaspen-execution').toLowerCase().replace(/[^a-z0-9._-]+/g, '-')}-wbs.csv`);
    showToast('Exported execution plan CSV', 'success');
  } catch (err) {
    console.error('[handleExportWbsCsv] failed', err);
    if (err?.status === 403) setBillingModalOpen(true);
    showToast(err?.message || 'Failed to export execution plan CSV', 'error');
  } finally {
    setExportBusyType(null);
  }
}, [currentSessionId, sessionId, showToast, triggerDownload]);

const handleExportConversationMarkdown = useCallback(async ({ threadBundleId, projectName } = {}) => {
  const tid = threadBundleId || currentSessionId || sessionId;
  if (!tid) {
    showToast('No active thread to export.', 'error');
    return;
  }
  setExportBusyType('conversation-md');
  try {
    const { blob, filename } = await Jaspen.downloadConversationMarkdown(tid);
    triggerDownload(blob, filename || `${String(projectName || 'jaspen-conversation').toLowerCase().replace(/[^a-z0-9._-]+/g, '-')}-conversation.md`);
    showToast('Exported conversation transcript', 'success');
  } catch (err) {
    console.error('[handleExportConversationMarkdown] failed', err);
    showToast(err?.message || 'Failed to export conversation transcript', 'error');
  } finally {
    setExportBusyType(null);
  }
}, [currentSessionId, sessionId, showToast, triggerDownload]);

const handleExportConversationPdf = useCallback(async ({ threadBundleId, projectName } = {}) => {
  const tid = threadBundleId || currentSessionId || sessionId;
  if (!tid) {
    showToast('No active thread to export.', 'error');
    return;
  }
  setExportBusyType('conversation-pdf');
  try {
    const { blob, filename } = await Jaspen.downloadConversationPdf(tid);
    triggerDownload(blob, filename || `${String(projectName || 'jaspen-conversation').toLowerCase().replace(/[^a-z0-9._-]+/g, '-')}-conversation.pdf`);
    showToast('Exported conversation transcript PDF', 'success');
  } catch (err) {
    console.error('[handleExportConversationPdf] failed', err);
    if (err?.status === 403) setBillingModalOpen(true);
    showToast(err?.message || 'Failed to export conversation transcript PDF', 'error');
  } finally {
    setExportBusyType(null);
  }
}, [currentSessionId, sessionId, showToast, triggerDownload]);

  // === Helpers ===
  const dismissGuidedFlow = useCallback(() => {
    writeGuidedFlowDismissed(user, true);
    setGuidedFlowDismissed(true);
  }, [user]);

  const launchGuidedFlow = useCallback(() => {
    const prompt = GUIDED_FLOW_TEMPLATE_PROMPT;
    writeGuidedFlowDismissed(user, true);
    setGuidedFlowDismissed(true);
    setInput(prompt);
    window.setTimeout(() => {
      intakeInputRef.current?.focus();
    }, 0);
  }, [user]);

  const handleOnboardingComplete = useCallback((selection = {}) => {
    const roleKey = String(selection?.role || '').trim().toLowerCase();
    const evaluationKey = String(selection?.evaluation || '').trim().toLowerCase();
    const startMode = String(selection?.startMode || 'conversation').trim().toLowerCase();
    const mappedObjective = normalizeStrategyObjective(
      ONBOARDING_OBJECTIVE_BY_EVALUATION[evaluationKey] || 'balanced'
    );
    const nextExplicit = mappedObjective !== 'balanced';

    setStrategyObjective(mappedObjective);
    setObjectiveExplicitlySet(nextExplicit);
    const nextSelection = {
      role: roleKey || 'other',
      evaluation: evaluationKey || 'new_initiative',
      startMode: startMode || 'conversation',
    };
    const nextContext = {
      role: roleKey || 'other',
      role_label: ONBOARDING_ROLE_LABELS[roleKey] || ONBOARDING_ROLE_LABELS.other,
      evaluation_focus: evaluationKey || 'new_initiative',
      evaluation_focus_label: ONBOARDING_EVALUATION_LABELS[evaluationKey] || ONBOARDING_EVALUATION_LABELS.new_initiative,
      start_preference: startMode || 'conversation',
      start_preference_label: ONBOARDING_START_LABELS[startMode] || ONBOARDING_START_LABELS.conversation,
      onboarding_complete: true,
    };
    setPendingOnboardingContext(nextContext);
    setOnboardingInitialSelection(nextSelection);
    setGuidedFlowDismissed(false);
    writeGuidedFlowDismissed(user, false);
    writeOnboardingState(user, { completed: true, deferred: false, selection: nextSelection });
    void persistOnboardingProfileState({ completed: true, deferred: false, selection: nextSelection });
    dismissNotification(SETUP_REMINDER_NOTIFICATION.id);
    if (onboardingMode === 'settings') {
      if (!sessionId && !currentSessionId && (!Array.isArray(messages) || messages.length === 0)) {
        setStrategyObjective(mappedObjective);
        setObjectiveExplicitlySet(nextExplicit);
      }
      setOnboardingOpen(false);
      setOnboardingMode('entry');
      showToast('Onboarding preferences updated', 'success');
      return;
    }
    const launchLabel = startMode === 'batch_ideas'
      ? 'Opening Batch Ideas…'
      : startMode === 'data_upload'
        ? 'Preparing data upload…'
        : 'Preparing conversation…';
    setOnboardingLaunchLabel(launchLabel);
    if (startMode === 'batch_ideas') {
      window.setTimeout(() => {
        setOnboardingOpen(false);
        setBatchIdeasOpen(true);
        setOnboardingLaunchLabel('');
      }, 260);
      return;
    }
    window.setTimeout(() => {
      setOnboardingOpen(false);
      window.setTimeout(() => intakeInputRef.current?.focus(), 0);
      if (startMode === 'data_upload') {
        fileInputRef.current?.click();
      }
      setOnboardingLaunchLabel('');
    }, 260);
  }, [user, onboardingMode, sessionId, currentSessionId, messages, showToast, dismissNotification, persistOnboardingProfileState]);

  const handleNewAnalysis = useCallback((forceNew = false) => {
    clearLastSessionId();
    setView('intake');
    setSessionId(null);
    setCurrentSessionId(null);
    setMessages([]);
    setInput('');
    setBusy(false);
    setReadinessAudit(null);
    setAnalysisResult(null);
    setError(null);
    setSavedScenarios([]);
    setCollectedData({});
    setStrategyObjective('balanced');
    setObjectiveExplicitlySet(false);
    setOnboardingMode('entry');
    setOnboardingInitialSelection(readOnboardingState(user)?.selection || null);
    setPendingOnboardingContext(null);
    setOnboardingLaunchLabel('');
    dispatchSidebar({ type: 'CLOSE_READINESS' });
  }, [user]);

  useEffect(() => {
    if (!analysisResult) return;
    if (activeTab !== 'chat') return;
    setActiveTab('summary');
    setView('summary');
  }, [analysisResult, activeTab]);

useEffect(() => {
  const hint = String(analysisResult?.proactive_next_step || '').trim();
  if (!hint) return;
  setMessages((prev) => {
    if (prev.some((message) => message?._isProactiveHint)) return prev;
    return [
      ...prev,
      { role: 'ai', text: hint, _isProactiveHint: true },
    ];
  });
}, [analysisResult?.proactive_next_step]);

  useEffect(() => {
    if (!commandPaletteOpen) return;
    window.setTimeout(() => commandPaletteInputRef.current?.focus(), 0);
  }, [commandPaletteOpen]);

  useEffect(() => {
    if (!scoreShellMenu) return undefined;
    const handlePointerDown = (event) => {
      if (scoreShellMenuRef.current?.contains(event.target)) return;
      setScoreShellMenu(null);
    };
    document.addEventListener('mousedown', handlePointerDown);
    return () => document.removeEventListener('mousedown', handlePointerDown);
  }, [scoreShellMenu]);

  useEffect(() => {
    const isEditableTarget = (target) => {
      if (!(target instanceof HTMLElement)) return false;
      const tagName = target.tagName.toLowerCase();
      return (
        target.isContentEditable ||
        tagName === 'input' ||
        tagName === 'textarea' ||
        tagName === 'select'
      );
    };

    const onKeyDown = (event) => {
      const editableTarget = isEditableTarget(event.target);

      if (event.key === 'Escape') {
        if (closeShortcutSurface()) {
          event.preventDefault();
        }
        return;
      }

      if (
        (event.metaKey || event.ctrlKey) &&
        event.key === 'Enter' &&
        editableTarget &&
        document.activeElement === intakeInputRef.current &&
        String(input || '').trim()
      ) {
        event.preventDefault();
        void onSubmit();
        return;
      }

      if (editableTarget) return;

      if (
        event.key === '?' &&
        !event.metaKey &&
        !event.ctrlKey &&
        !event.altKey
      ) {
        setHelpOpen(true);
        event.preventDefault();
        return;
      }

      if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === 'k') {
        setCommandPaletteOpen((prev) => !prev);
        event.preventDefault();
        return;
      }

      if (event.altKey && event.shiftKey && event.key.toLowerCase() === 'n') {
        event.preventDefault();
        handleNewAnalysis(true);
        return;
      }

      if (
        event.key === '/' &&
        !event.metaKey &&
        !event.ctrlKey &&
        !event.altKey
      ) {
        if (focusVisibleComposer()) {
          event.preventDefault();
        }
      }
    };

    document.addEventListener('keydown', onKeyDown);
    return () => document.removeEventListener('keydown', onKeyDown);
  }, [closeShortcutSurface, focusVisibleComposer, handleNewAnalysis, input, openHistorySearch]);

  // ======== FIXED: Select analysis (history restore) ========================
  const handleSelectAnalysis = async (selection) => {
  // Block the very first readiness ping after selecting history
  skipPingRef.current = true;

  const result =
    selection && typeof selection === 'object' && selection.result && typeof selection.result === 'object'
      ? selection.result
      : selection;
  const ownerThreadId = resolveHistoryOwnerId(
    analysisHistory,
    selection && typeof selection === 'object' ? selection.id : '',
    result?._owner_thread_id,
    result?.thread_id,
    result?.session_id,
    result?.analysis_id,
    result?.id,
  );

  // Prefer a full record from the backend if the list item looks incomplete
  const baseId =
    ownerThreadId ||
    result?.analysis_id ||
    result?.session_id ||
    result?.id;

  const looksIncomplete =
    !Array.isArray(result?.chat_history) ||
    (result?.chat_history?.length ?? 0) < 1 ||
    !result?.readiness ||
    !Array.isArray(result?.readiness?.categories) ||
    (result?.readiness?.percent == null &&
     result?.readiness?.readiness_percent == null &&
     result?.readiness?.value == null);

  const full = looksIncomplete && baseId ? await loadSessionById(baseId) : null;
  const bundle = baseId
    ? await Jaspen.getThreadBundle(baseId, { msg_limit: 50, scn_limit: 50 }).catch(() => null)
    : null;
  const bundleScorecard = getMeaningfulBundleScorecard(bundle);

  // Merge shallowly: prefer fields from the full fetch when present
	  const merged = full
    ? {
        ...result,
        ...full,
        readiness: full.readiness ?? result.readiness,
        chat_history: Array.isArray(full.chat_history) ? full.chat_history : result.chat_history,
        collected_data: full.collected_data ?? result.collected_data,
        status: full.status ?? result.status,
        result:
          hasMeaningfulScorecardData(full?.result)
            ? full.result
            : (hasMeaningfulScorecardData(result?.result) ? result.result : full?.result ?? result?.result),
        analysis_id:
          (hasMeaningfulScorecardData(full?.result) ? full.result.analysis_id : null) ??
          (hasMeaningfulScorecardData(result?.result) ? result.result.analysis_id : null) ??
          result?.analysis_id ??
          ownerThreadId ??
          full.session_id ??
          result.session_id,
        project_name:
          (hasMeaningfulScorecardData(full?.result) ? full.result.project_name : null) ??
          (hasMeaningfulScorecardData(result?.result) ? result.result.project_name : null) ??
          full.name ??
          result.project_name,
        jaspen_score:
          (hasMeaningfulScorecardData(full?.result) ? full.result.jaspen_score : null) ??
          (hasMeaningfulScorecardData(result?.result) ? result.result.jaspen_score : null) ??
          full.score ??
          result.jaspen_score,
      }
	    : result;
  const mergedScorecard =
    hasMeaningfulScorecardData(bundleScorecard)
      ? bundleScorecard
      : hasMeaningfulScorecardData(merged?.result)
        ? merged.result
        : hasMeaningfulScorecardData(merged)
          ? merged
          : null;

  const mergedObjective = normalizeStrategyObjective(
    merged?.strategy_objective || merged?.result?.strategy_objective || 'balanced'
  );
  setStrategyObjective(mergedObjective);
  setObjectiveExplicitlySet(Boolean(merged?.objective_explicitly_set || merged?.result?.objective_explicitly_set));
  const resolvedOwnerThreadId = resolveHistoryOwnerId(
    analysisHistory,
    ownerThreadId,
    bundle?.thread?.id,
    bundle?.thread?.session_id,
    merged?.session_id,
    merged?.result?.session_id,
    merged?.result?._owner_thread_id,
    baseId,
  ) || `restored_${Date.now()}`;

  const currentScorecard = bundle?.current_scorecard || null;
  const baselineScorecard = bundle?.baseline_scorecard || null;

  // Use persisted snapshots from the bundle (only Set-Active scenarios) so
  // the Score dropdown is consistent with what refreshBundle produces.
  // Fall back to building from raw scenario scorecards only when no
  // persisted snapshots exist (legacy sessions before snapshot persistence).
  const persistedSnapshots = Array.isArray(bundle?.scorecard_snapshots)
    ? bundle.scorecard_snapshots
    : [];
  const scenarioScorecards = persistedSnapshots.length > 0
    ? []
    : (Array.isArray(bundle?.scenarios)
        ? bundle.scenarios
            .map((entry) => entry?.scorecard || entry?.analysis_result || entry?.result || null)
            .filter((entry) => entry && typeof entry === 'object')
        : []);
  const nextSnapshots = persistedSnapshots.length > 0
    ? persistedSnapshots
    : buildScorecardSnapshots({
        threadId: resolvedOwnerThreadId,
        baselineScorecard,
        currentScorecard,
        scenarioScorecards,
      });
  const nextBaselineId =
    baselineScorecard?.analysis_id ||
    baselineScorecard?.id ||
    baselineScorecard?.analysisId ||
    nextSnapshots.find((snapshot) => snapshot?.isBaseline)?.id ||
    null;
  const nextSelectedScorecardId =
    bundle?.selected_scorecard_id ||
    currentScorecard?.analysis_id ||
    currentScorecard?.id ||
    currentScorecard?.analysisId ||
    nextBaselineId ||
    selectedScorecardId ||
    '';
  const mergedSnapshots = buildMergedScorecardSnapshots({
    analysisResult: hasMeaningfulScorecardData(merged?.result) ? merged.result : merged,
    bundleBaselineScorecard: baselineScorecard,
    baselineScorecardId: nextBaselineId,
    scorecardSnapshots: nextSnapshots,
    sessionId: resolvedOwnerThreadId,
  });
  const selectionContext = resolveScoreWorkspaceContext({
    analysisHistory,
    sessionId: resolvedOwnerThreadId,
    currentSessionId: resolvedOwnerThreadId,
    selectedScorecardId: nextSelectedScorecardId,
    scorecardSnapshots: mergedSnapshots,
    selectedVariant: null,
    analysisResult: hasMeaningfulScorecardData(merged?.result) ? merged.result : merged,
    bundleCurrentScorecard: currentScorecard,
    bundleBaselineScorecard: baselineScorecard,
    view: merged?.status === 'in_progress' && !hasMeaningfulScorecardData(mergedScorecard)
      ? 'intake'
      : 'summary',
    activeTab: 'summary',
  });
  const resolvedScorecard = selectionContext.scorecard || mergedScorecard || merged || {};
  const resolvedActiveThreadId = selectionContext.ownerThreadId || resolvedOwnerThreadId;

  // Readiness normalization handled by normalizeReadiness() helper
  // Readiness is ONLY fetched from backend via fetchReadinessFor - no session cache

  // Branch: in-progress sessions return to intake with chat restored only when
  // they do not already carry a meaningful saved scorecard.
  if (!selectionContext.hasScorecard && merged?.status === 'in_progress' && Array.isArray(merged.chat_history)) {
    const sid = resolvedActiveThreadId;
    setSessionId(sid);
    setCurrentSessionId(sid);
    setLastSessionId(sid);

    const restoredMessages = toUiMessages(merged.chat_history);
    setMessages(restoredMessages);

    setCollectedData(merged.collected_data || {});
    setView('intake');
    dispatchSidebar({ type: 'CLOSE_HISTORY' });
    dispatchSidebar({ type: 'OPEN_READINESS' });
    fetchReadinessFor(sid);

    return;
  }

// Completed session -> workspace summary (prefer the persisted result blob)
try {
  const id = resolvedActiveThreadId;

  setSessionId(id);
  setLastSessionId(id);
  const bundleHistory = Array.isArray(bundle?.messages)
    ? bundle.messages.map((m) => ({
        role: m?.role || (m?.sender === 'user' ? 'user' : 'assistant'),
        content: m?.content || m?.text || m?.message || '',
      }))
    : [];
  const restoredMessages = toUiMessages(
    bundleHistory.length > 0
      ? bundleHistory
      : (merged?.chat_history || merged?.result?.chat_history || [])
  );
  if (restoredMessages.length > 0) {
    setMessages(restoredMessages);
  }

  setCurrentSessionId(id);

  if (bundle) {
    setBundleCurrentScorecard(currentScorecard);
    setBundleBaselineScorecard(baselineScorecard);
    if (mergedSnapshots.length > 0) {
      setScorecardSnapshots(mergedSnapshots);
      setBaselineScorecardId(nextBaselineId);
      setActiveSnapshotId(nextSelectedScorecardId || null);
      setSelectedScorecardId(nextSelectedScorecardId || nextBaselineId || null);
    }
  }

const fullScorecard = resolvedScorecard;
  const resolvedBaselineScorecard =
    (baselineScorecard && typeof baselineScorecard === 'object' && Object.keys(baselineScorecard).length > 0)
      ? baselineScorecard
      : mergedSnapshots.find((snapshot) => snapshot?.isBaseline) || null;
  const withScoreContext = (scorecard) => buildProjectScoreResult({
    baselineScorecard: resolvedBaselineScorecard || scorecard || fullScorecard || merged || {},
    snapshots: mergedSnapshots,
    selectedScorecardId: nextSelectedScorecardId || nextBaselineId || null,
    ownerThreadId: id,
    existingResult: merged?.result || analysisResult || merged,
    fallbackScorecard: scorecard || fullScorecard || merged || {},
  });

// GOAL B part 2: Check for missing detailed sections and hydrate if needed
const missingSections =
  !fullScorecard?.decision_framework &&
  !fullScorecard?.investment_analysis &&
  !fullScorecard?.npv_irr_analysis &&
  !fullScorecard?.valuation &&
  !fullScorecard?.before_after_financials;

if (missingSections) {
  const fresh = await loadSessionById(id);
  const freshBundle = await Jaspen.getThreadBundle(id, { msg_limit: 50, scn_limit: 50 }).catch(() => null);
  const freshScorecard = getMeaningfulBundleScorecard(freshBundle) || fresh?.result || fresh;
  if (freshScorecard) {
    const normalized = withScoreContext(freshScorecard);
    setAnalysisResult(normalized);
    baselineRef.current = normalized._baseline_scorecard || normalized;
  } else {
    const normalized = withScoreContext(fullScorecard || merged || {});
    setAnalysisResult(normalized);
    baselineRef.current = normalized._baseline_scorecard || normalized;
  }
} else {
  const normalized = withScoreContext(fullScorecard);
  setAnalysisResult(normalized);
  baselineRef.current = normalized._baseline_scorecard || normalized;
}

  dispatchSidebar({ type: 'CLOSE_HISTORY' });
  // Readiness sidebar only applies to in-progress (incomplete) sessions
  // Completed sessions go directly to summary view
  setView('summary');
  setActiveTab('summary');

  } catch (e) {
  console.error('[handleSelectAnalysis] hydrate failed', e, { merged });
  // Safe fallback so the UI still renders something
const normalizedFallback = {
  ...buildProjectScoreResult({
    baselineScorecard: baselineScorecard || mergedSnapshots.find((snapshot) => snapshot?.isBaseline) || merged || {},
    snapshots: mergedSnapshots,
    selectedScorecardId: nextSelectedScorecardId || nextBaselineId || null,
    ownerThreadId: resolvedActiveThreadId,
    existingResult: merged?.result || merged,
    fallbackScorecard: merged || {},
  }),
};
setAnalysisResult(normalizedFallback);
if (!baselineRef.current) baselineRef.current = normalizedFallback._baseline_scorecard || normalizedFallback; // only set if not set yet
}
  }

  const didPromoteCompletedRefreshRef = useRef(null);
  useEffect(() => {
    const activeId = sessionId || currentSessionId;
    if (!activeId) {
      didPromoteCompletedRefreshRef.current = null;
      return;
    }
    if (view !== 'intake') return;
    if (analysisResult) return;
    const entry =
      analysisHistory.find((s) => s.id === activeId) ||
      analysisHistory.find((s) => s.result?.analysis_id === activeId);
    if (!hasMeaningfulScorecardData(entry?.result)) return;
    if (didPromoteCompletedRefreshRef.current === activeId) return;
    didPromoteCompletedRefreshRef.current = activeId;
    void handleSelectAnalysis(entry);
  }, [sessionId, currentSessionId, view, analysisResult, analysisHistory]);

  // Delete a session
  const deleteAnalysisById = async (itemId) => {
    try {
await authFetch(`${API_BASE}/api/v1/ai-agent/threads/${itemId}`, {
  method: 'DELETE',
  headers: buildAuthHeaders({}, 'DELETE'),
  credentials: 'include'
} );
    } catch (error) {
      console.error('Error deleting session from backend:', error);
    }
  };

  const handleDeleteAnalysis = async (itemId) => {
    if (!itemId) return;
    const entry = analysisHistory.find((item) => String(item?.id || '').trim() === String(itemId).trim());
    const label = (entry?.name || entry?.title || entry?.result?.project_name || 'this analysis').trim();

    setConfirmDialog({
      title: 'Delete analysis',
      message: `Delete "${label}"? This cannot be undone.`,
      confirmLabel: 'Delete analysis',
      confirmVariant: 'danger',
      onConfirm: async () => {
        await deleteAnalysisById(itemId);
        await fetchSessions();
      },
    });
  };

  const handleClearHistory = async () => {
    if (!analysisHistory.length || clearingHistory) return;
    setConfirmDialog({
      title: 'Clear history',
      message: `Delete all ${analysisHistory.length} history sessions? This cannot be undone.`,
      confirmLabel: 'Clear history',
      confirmVariant: 'danger',
      onConfirm: async () => {
        setClearingHistory(true);
        try {
          const ids = analysisHistory.map((h) => h.id).filter(Boolean);
          await Promise.allSettled(ids.map((id) => deleteAnalysisById(id)));

          const currentGone = ids.includes(currentSessionId) || ids.includes(sessionId);
          if (currentGone) {
            clearLastSessionId();
            setSessionId(null);
            setCurrentSessionId(null);
            setAnalysisResult(null);
            setMessages([]);
            setView('intake');
          }

          await fetchSessions();
          showToast('History cleared', 'success');
        } catch (error) {
          console.error('[handleClearHistory] failed', error);
          showToast('Failed to clear history', 'error');
        } finally {
          setClearingHistory(false);
        }
      },
    });
  };

  // Persist a scenario row to the backend, then refresh bundle
async function persistScenario(label, values) {
  try {
    const apiBase = API_BASE;
    const threadId = currentSessionId || sessionId;
    if (!threadId || !analysisResult?.analysis_id) {
      throw new Error('Missing thread/analysis id');
    }

    const res = await authFetch(
      `${apiBase}/api/v1/strategy/threads/${encodeURIComponent(threadId)}/scenarios`,
      {
        method: 'POST',
        credentials: 'include',
        headers: buildAuthHeaders({ 'Content-Type': 'application/json' }, 'POST'),
        body: JSON.stringify({
based_on: analysisResult?.analysis_id || sessionId,
          deltas: values || {},
          label: label || 'Scenario',
        }),
      }
    );

    const json = await res.json().catch(() => ({}));
    if (!res.ok) {
      const err = json?.error || `HTTP ${res.status}`;
      throw new Error(err);
    }

    // refresh bundle so the new scenario appears immediately
    await refreshBundle(threadId);
    return json?.scenario_id || null;
  } catch (e) {
    console.error('[persistScenario] failed', e);
    return null;
  }
}

// Capture scenario results so the Score dropdown can switch among them
const ensureVariantOption = (id, label, result) => {
  setScoreVariants(prev => {
    const exists = prev.some(v => v.id === id);
    if (exists) return prev.map(v => (v.id === id ? { ...v, result } : v));
    return [...prev, { id, label, result }];
  });
};

const handleScenarioResultA = (result) => {
  if (!result) return;
  setResultA(result);
  ensureVariantOption('scenarioA', 'Scenario A', result);
};

const handleScenarioResultB = (result) => {
  if (!result) return;
  setResultB(result);
  ensureVariantOption('scenarioB', 'Scenario B', result);
};

const handleScenarioResultC = (result) => {
  if (!result) return;
  setResultC(result);
  ensureVariantOption('scenarioC', 'Scenario C', result);
};

const handleScenarioSaved = useCallback((payload = {}) => {
  if (!payload || typeof payload !== 'object') return;
  const scenarioId = String(
    payload?.response?.scenario_id ||
    payload?.response?.scenario?.scenario_id ||
    payload?.snapshot?.scenario_id ||
    payload?.snapshot?.id ||
    ''
  ).trim();
  if (!scenarioId) return;

  const nextEntry = {
    id: scenarioId,
    label: String(payload?.label || payload?.snapshot?.label || 'Scenario').trim() || 'Scenario',
    values: payload?.response?.scenario?.deltas || payload?.values || {},
    result: payload?.snapshot && typeof payload.snapshot === 'object' ? payload.snapshot : null,
    timestamp: Date.now(),
  };

  // Optimistic local update so the UI reflects the saved scenario immediately
  setSavedScenarios((prev) => {
    const items = Array.isArray(prev) ? prev : [];
    const others = items.filter((item) => String(item?.id || '').trim() !== scenarioId);
    return [...others, nextEntry].sort((a, b) => Number(b?.timestamp || 0) - Number(a?.timestamp || 0));
  });

  // Re-fetch from backend so savedScenarios are authoritative and persist
  // across refresh/logout. The optimistic update above keeps the UI snappy.
  const tid = currentSessionId || sessionId;
  if (tid) {
    refreshBundle(tid).catch(() => {});
  }
}, [currentSessionId, refreshBundle, sessionId]);

const handleSnapshotSelect = useCallback(async (snapshotId) => {
  const nextId = String(snapshotId || '').trim();
  if (!nextId) return;
  setSelectedScorecardId(nextId);
  setActiveTab('summary');
  setView('summary');
}, []);

const handleSnapshotSetActive = useCallback(async (snapshotId, snapshotLabel) => {
  const nextId = String(snapshotId || '').trim();
  const tid = currentSessionId || sessionId;
  if (!nextId || !tid) return;

  try {
    const concurrencyGuard = buildScorecardConcurrencyGuard(nextId);
    const response = await Jaspen.setActiveSnapshot(tid, nextId, concurrencyGuard);
    applySnapshotMeta(response, { refresh: true, select: true });
    setActiveTab('summary');
    setView('summary');
    openPlanningReadyAssistant(snapshotLabel || 'Active scorecard');
    showToast('Active scorecard updated.', 'success');
  } catch (err) {
    console.error('[handleSnapshotSetActive] failed', err);
    if (Number(err?.status) === 409) {
      await refreshBundle(tid);
      showToast(err?.message || 'Scorecard changed elsewhere. Refreshed to latest.', 'warning');
      return;
    }
    showToast(err?.message || 'Failed to set active scorecard.', 'error');
  }
}, [applySnapshotMeta, buildScorecardConcurrencyGuard, currentSessionId, openPlanningReadyAssistant, refreshBundle, sessionId, showToast]);

const handleSnapshotRename = useCallback(async (snapshotId, currentLabel) => {
  const nextId = String(snapshotId || '').trim();
  const tid = currentSessionId || sessionId;
  if (!nextId || !tid) return;

  const proposed = window.prompt('Rename this scorecard variant', currentLabel || '');
  if (proposed == null) return;
  const nextLabel = proposed.trim();
  if (!nextLabel || nextLabel === String(currentLabel || '').trim()) return;

  try {
    const concurrencyGuard = buildScorecardConcurrencyGuard(nextId);
    const response = await Jaspen.renameSnapshot(tid, nextId, nextLabel, concurrencyGuard);
    applySnapshotMeta(response, { refresh: false });
    showToast('Scorecard variant renamed', 'success');
  } catch (err) {
    console.error('[handleSnapshotRename] failed', err);
    if (Number(err?.status) === 409) {
      await refreshBundle(tid);
      showToast(err?.message || 'Scorecard changed elsewhere. Refreshed to latest.', 'warning');
      return;
    }
    showToast(err?.message || 'Failed to rename scorecard variant.', 'error');
  }
}, [applySnapshotMeta, buildScorecardConcurrencyGuard, currentSessionId, refreshBundle, sessionId]);

const handleSnapshotDelete = useCallback(async (snapshotId, label) => {
  const nextId = String(snapshotId || '').trim();
  const tid = currentSessionId || sessionId;
  if (!nextId || !tid) return;

  setConfirmDialog({
    title: 'Delete scorecard variant',
    message: `Delete "${label || 'this scorecard variant'}"? This cannot be undone.`,
    confirmLabel: 'Delete scorecard',
    confirmVariant: 'danger',
    onConfirm: async () => {
      try {
        const concurrencyGuard = buildScorecardConcurrencyGuard(nextId);
        const response = await Jaspen.deleteSnapshot(tid, nextId, concurrencyGuard);
        applySnapshotMeta(response, { refresh: true });
        showToast('Scorecard variant deleted', 'success');
      } catch (err) {
        console.error('[handleSnapshotDelete] failed', err);
        if (Number(err?.status) === 409) {
          await refreshBundle(tid);
          showToast(err?.message || 'Scorecard changed elsewhere. Refreshed to latest.', 'warning');
          return;
        }
        showToast(err?.message || 'Failed to delete scorecard variant.', 'error');
      }
    },
  });
}, [applySnapshotMeta, buildScorecardConcurrencyGuard, currentSessionId, refreshBundle, sessionId]);

  const handleCompareScenarios = async () => {
    await refreshBundle(currentSessionId || sessionId);
    setView('comparison');
    setActiveTab('scenario');
  };

  // === Help Chat ===
  const sendHelpMessage = async () => {
    if (!helpInput.trim() || helpLoading) return;

    const userMessage = { role: 'user', content: helpInput };
    setHelpMessages([...helpMessages, userMessage]);
    setHelpInput('');
    setHelpLoading(true);

    try {
      const response = await authFetch(`${API_BASE}/api/v1/help/chat`, {
        method: 'POST',
        headers: buildAuthHeaders({ 'Content-Type': 'application/json' }, 'POST'),
        body: JSON.stringify({
          message: helpInput,
          context: 'Jaspen'
        })
      });
      const data = await response.json();

      if (data.success) {
        const assistantMessage = {
          role: 'assistant',
          content: data.response
        };
        setHelpMessages(prev => [...prev, assistantMessage]);
      }
    } catch (error) {
      console.error('Error sending help message:', error);
      const errorMessage = { role: 'assistant', content: 'Sorry, I encountered an error. Please try again.' };
      setHelpMessages(prev => [...prev, errorMessage]);
    } finally {
      setHelpLoading(false);
    }
  };

  // =========================
  // ====== WORKSPACE TABS ===
  // =========================

  const buildScoreCommentary = (msgs = []) => {
    const aiMessages = [...msgs]
      .filter((m) => m?.role === 'ai' && (m?.text || '').trim())
      .slice(-3);
    if (aiMessages.length === 0) return null;

    const text = aiMessages.map((m) => m.text || '').join(' ').trim();
    if (!text) return null;

    const sentences = text
      .split(/(?<=[.!?])\s+/)
      .map((s) => s.trim())
      .filter(Boolean);

    const pick = (keywords) =>
      sentences.find((s) => keywords.some((k) => s.toLowerCase().includes(k))) || '';

    return {
      overall: sentences.slice(0, 2).join(' '),
      byCategory: {
        financial_health: pick(['financial', 'cash', 'revenue', 'margin', 'unit economics', 'profit', 'ebitda', 'ltv', 'cac']),
        market_position: pick(['market', 'position', 'competition', 'demand', 'segments', 'differentiation', 'gtm', 'go-to-market']),
        operational_efficiency: pick(['operations', 'efficiency', 'process', 'cost', 'execution', 'scale', 'throughput']),
        execution_readiness: pick(['execution', 'readiness', 'team', 'timeline', 'plan', 'resources', 'milestone']),
      },
      source: 'chat_transcript_latest_ai',
    };
  };

  const scoreCommentary = useMemo(() => buildScoreCommentary(messages), [messages]);

  const renderWorkspaceShell = () => {
    const isReadinessOpen = false;
    const isSettingsOpen = sidebarState.settings;
    const isScenarioTab = activeTab === 'scenario';
    const shellOpen = sidebarState.history || sidebarState.readiness || sidebarState.settings;
    const sideTabBase = 128;
    const sideTabGap = 130;
    const sideTabSecond = sideTabBase + sideTabGap;
    const baselineTitleSource =
      (analysisResult?._baseline_scorecard && typeof analysisResult._baseline_scorecard === 'object'
        ? analysisResult._baseline_scorecard
        : null) ||
      bundleBaselineScorecard ||
      analysisResult ||
      activeScorecard;
    const workspaceProjectTitle = deriveIdeaTitle({
      result: baselineTitleSource,
      messages,
      fallback: 'Untitled Idea',
    });
    const baselineSnapshotId =
      baselineScorecardId ||
      analysisResult?._baseline_scorecard?.analysis_id ||
      analysisResult?._baseline_scorecard?.id ||
      analysisResult?.analysis_id ||
      analysisResult?.id ||
      sessionId;
    const mergedSnapshots = mergedScoreWorkspaceSnapshots.length > 0
      ? mergedScoreWorkspaceSnapshots
      : buildMergedScorecardSnapshots({
          analysisResult,
          bundleBaselineScorecard,
          baselineScorecardId: baselineSnapshotId,
          scorecardSnapshots,
          sessionId,
        });
    const snapshotOptions = mergedSnapshots.length > 0
      ? [...mergedSnapshots]
          .sort((a, b) => {
            if (Boolean(a?.isBaseline) !== Boolean(b?.isBaseline)) {
              return a?.isBaseline ? -1 : 1;
            }
            const aSelected = String(a?.id || '') === String(effectiveSelectedScorecardId || '');
            const bSelected = String(b?.id || '') === String(effectiveSelectedScorecardId || '');
            if (aSelected !== bSelected) return aSelected ? -1 : 1;
            const aCreated = Date.parse(String(a?.createdAt || a?.timestamp || '')) || Number(a?.createdAt || 0) || 0;
            const bCreated = Date.parse(String(b?.createdAt || b?.timestamp || '')) || Number(b?.createdAt || 0) || 0;
            return bCreated - aCreated;
          })
          .map((snap, idx) => ({
            id: snap.id,
            label: snap.isBaseline ? 'Baseline' : (snap.label || `Scenario ${idx}`),
            isBaseline: Boolean(snap?.isBaseline),
            isSelected: String(snap?.id || '') === String(effectiveSelectedScorecardId || ''),
            isActive: String(snap?.id || '') === String(activeSnapshotId || ''),
            canDelete: !Boolean(snap?.isBaseline),
          }))
      : [];
    const useSnapshotSelect = snapshotOptions.length > 0;
    const resolvedScoreSelectValue = String(
      activeScorecardId ||
      effectiveSelectedScorecardId ||
      snapshotOptions[0]?.id ||
      ''
    ).trim();
    const scoreSelectValue = useSnapshotSelect
      ? resolvedScoreSelectValue
      : selectedVariantId;
    const selectedScoreLabel = useSnapshotSelect
      ? (snapshotOptions.find((option) => option.id === resolvedScoreSelectValue)?.label || snapshotOptions[0]?.label || 'Baseline')
      : (scoreVariants.find((variant) => variant.id === scoreSelectValue)?.label || 'Baseline');
    const completedScoreOptions = analysisHistory
      .filter((item) => (item.result?.status || 'completed') === 'completed')
      .map((item) => ({
        id: item.id,
        label: `${(item.result?.project_name || 'Analysis').slice(0, 32)}${item.result?.jaspen_score != null ? ` — ${item.result.jaspen_score}` : ''}`,
        result: item.result,
      }));
    const selectedCompletedScoreLabel = 'Completed Scores';
    const scenarioTabLocked = !canUseScenarios || effectiveIsViewer;
    const canBeginProject = canAccessExecutionTab && canStartOrgProjects;
    const canOpenProject = canAccessExecutionTab;
    const projectActionTitle = hasProjectPlan
      ? (!canOpenProject
          ? 'Upgrade to open project plan'
          : 'Go to project plan')
      : !canAccessExecutionTab
      ? 'Upgrade to begin project'
      : !canStartOrgProjects
      ? 'Only creators and admins can begin a project in a shared workspace.'
      : 'Begin project';
    const contextualScorePrompts = buildScorecardFollowUpPrompts(activeScorecard, workspaceProjectTitle);
    const fallbackScorePrompts = [
      'Explain what drove this score',
      'Rewrite the top recommendation to sound more executive',
      'Tighten the wording of the biggest risk',
      'What would raise this score fastest?',
    ];
    const scoreDrawerPrompts = scoreWorkspaceMode === 'summary'
      ? [
          ...(sfConnected ? [{
            id: 'sf-pipeline',
            label: 'Load my Salesforce pipeline',
            icon: faArrowRightArrowLeft,
            onClick: handleLoadSalesforcePipeline,
            loading: sfPipelineLoading,
          }] : []),
          ...(contextualScorePrompts.length > 0 ? contextualScorePrompts : fallbackScorePrompts),
        ]
      : [];
    const aiDrawerPlaceholder = scoreWorkspaceMode === 'summary'
      ? 'Ask about this scorecard, its risks, or how to sharpen the wording... (Cmd/Ctrl+K for commands)'
      : 'Ask about tasks, timeline, resources...';
    const openWorkspaceTab = async (id) => {
      const isLocked = id === 'scenario' && scenarioTabLocked;
      if (isLocked) {
        if (id === 'scenario' && effectiveIsViewer) {
          showToast('Viewers can review shared project results but cannot use scenario tools.', 'info');
        } else if (id === 'scenario') {
          showToast('Scenarios are available on Essential, Team, and Enterprise plans.', 'info');
          setBillingModalOpen(true);
        }
        return;
      }
      setActiveTab(id);
      setView(id);
      if (id === 'scenario' && (sessionId || analysisResult?.analysis_id)) {
        try {
          const tid = sessionId || analysisResult?.analysis_id;
          await refreshBundle(tid);
        } catch {}
      }
    };
    const topTabIds = ['summary', 'scenario'];
    const TabButton = ({ id, label }) => {
      const isLocked = id === 'scenario' && scenarioTabLocked;
      const badgeLabel = id === 'scenario' && isLocked ? 'Essential+' : '';
      return (
      <button
        type="button"
        ref={(node) => {
          if (node) workspaceTabRefs.current[id] = node;
        }}
        className={`jas-top-tab ${activeTab === id ? 'active' : ''} ${isLocked ? 'disabled' : ''}`}
        role="tab"
        aria-selected={activeTab === id}
        aria-disabled={isLocked}
        tabIndex={activeTab === id ? 0 : -1}
        onClick={() => {
          void openWorkspaceTab(id);
        }}
        onKeyDown={(event) => {
          if (!['ArrowRight', 'ArrowLeft', 'Home', 'End'].includes(event.key)) return;
          event.preventDefault();
          const enabledTabs = topTabIds.filter((tabId) => {
            if (tabId === 'scenario' && scenarioTabLocked) return false;
            return true;
          });
          if (!enabledTabs.length) return;
          const currentIndex = Math.max(enabledTabs.indexOf(id), 0);
          let nextIndex = currentIndex;
          if (event.key === 'ArrowRight') nextIndex = (currentIndex + 1) % enabledTabs.length;
          if (event.key === 'ArrowLeft') nextIndex = (currentIndex - 1 + enabledTabs.length) % enabledTabs.length;
          if (event.key === 'Home') nextIndex = 0;
          if (event.key === 'End') nextIndex = enabledTabs.length - 1;
          const nextId = enabledTabs[nextIndex];
          workspaceTabRefs.current[nextId]?.focus();
          void openWorkspaceTab(nextId);
        }}
      >
        {label}
        {badgeLabel && <span className="jas-ud-item-badge" style={{ marginLeft: 8 }}>{badgeLabel}</span>}
      </button>
      );
    };

    const commandOptions = [
      {
        id: 'new-analysis',
        label: 'New analysis',
        hint: 'Start a fresh workspace thread',
        keywords: 'new analysis thread start',
        run: () => handleNewAnalysis(true),
      },
      {
        id: 'go-score',
        label: 'Go to Score view',
        hint: 'Open score summary tab',
        keywords: 'score summary tab',
        run: () => { void openWorkspaceTab('summary'); },
      },
      {
        id: 'go-scenarios',
        label: 'Go to Scenarios view',
        hint: 'Open scenario modeling tab',
        keywords: 'scenario scenarios modeling',
        run: () => { void openWorkspaceTab('scenario'); },
      },
      {
        id: 'focus-composer',
        label: 'Focus composer',
        hint: 'Jump to chat input',
        keywords: 'composer input prompt chat',
        run: () => { focusVisibleComposer(); },
      },
      {
        id: 'focus-history',
        label: 'Focus history search',
        hint: 'Open history rail and focus search',
        keywords: 'history search sessions',
        run: () => { openHistorySearch(); },
      },
      {
        id: 'open-help',
        label: 'Open help',
        hint: 'Show keyboard help and support',
        keywords: 'help support shortcuts',
        run: () => { setHelpOpen(true); },
      },
      {
        id: 'open-account',
        label: 'Open account settings',
        hint: 'Go to account page',
        keywords: 'account settings profile',
        run: () => { navigate('/account'); },
      },
      {
        id: 'open-projects',
        label: 'Open projects',
        hint: 'Go to project portfolio',
        keywords: 'projects portfolio',
        run: () => { navigate('/projects'); },
      },
    ];
    const filteredCommandOptions = commandOptions.filter((option) => {
      const query = String(commandQuery || '').trim().toLowerCase();
      if (!query) return true;
      return `${option.label} ${option.hint} ${option.keywords}`.toLowerCase().includes(query);
    });
    const runCommandOption = (option) => {
      if (!option || typeof option.run !== 'function') return;
      setCommandPaletteOpen(false);
      setCommandQuery('');
      option.run();
    };

    return (
      <div className={`jas jas-shell ${shellOpen ? 'drawer-open' : ''}`}>
        <a href="#jas-main-content" className="jas-skip-link">Skip to main content</a>
        <main className="jas-main" aria-label="Jaspen workspace">
          <div className="jas-sr-only" aria-live="polite" aria-atomic="true">{liveStatusMessage}</div>
          <ToastContainer toasts={toasts} onDismiss={dismissToast} />

      {/* LEFT SIDEBAR - User Settings */}
      <aside
        id="jas-workspace-settings-panel"
        className={`jas-left-sidebar jas-settings-sidebar ${sidebarState.settings ? 'sidebar-open' : ''}`}
        aria-labelledby="jas-workspace-settings-title"
      >
        <div className="jas-sidebar-header">
          <h3 id="jas-workspace-settings-title">User Settings</h3>
          <button
            className="jas-sidebar-close"
            onClick={() => dispatchSidebar({ type: 'CLOSE_SETTINGS' })}
            aria-label="Close user settings"
          >
            <FontAwesomeIcon icon={faTimes} />
          </button>
        </div>
        <div className="jas-sidebar-content">
          {renderUserMenuContent(() => dispatchSidebar({ type: 'CLOSE_SETTINGS' }))}
        </div>
      </aside>

      {!sidebarState.settings && (
        <button
          type="button"
          className="jas-sidebar-tab jas-tab-settings"
          onClick={() => dispatchSidebar({ type: 'TOGGLE_SETTINGS' })}
          aria-label="User settings"
          title="User settings"
          aria-expanded={sidebarState.settings}
          aria-controls="jas-workspace-settings-panel"
          style={{ top: `${sideTabBase}px` }}
        >
          <FontAwesomeIcon icon={faBars} />
          <span className="jas-tab-label">Menu</span>
        </button>
      )}

      {busy && !isStreamingReply && (
        <div className="thinking-overlay">
          <div className="thinking-content">
            <FontAwesomeIcon icon={faSpinner} spin />
            <span>Thinking...</span>
          </div>
        </div>
      )}

      {renderNameModal()}
      {renderBillingModal()}
      {renderPostAdoptWbsPrompt()}
      <ConfirmDialog
        isOpen={Boolean(confirmDialog)}
        title={confirmDialog?.title || 'Confirm action'}
        message={confirmDialog?.message || 'Are you sure you want to continue?'}
        confirmLabel={confirmDialog?.confirmLabel || 'Confirm'}
        confirmVariant={confirmDialog?.confirmVariant || 'danger'}
        onConfirm={async () => {
          const action = confirmDialog?.onConfirm;
          setConfirmDialog(null);
          if (typeof action === 'function') await action();
        }}
        onCancel={() => setConfirmDialog(null)}
      />
      {commandPaletteOpen && (
        <div className="jas-command-overlay" role="dialog" aria-modal="true" aria-label="Command palette">
          <div className="jas-command-card">
            <div className="jas-command-head">
              <h3>Command Palette</h3>
              <button
                type="button"
                className="jas-command-close"
                onClick={() => {
                  setCommandPaletteOpen(false);
                  setCommandQuery('');
                }}
                aria-label="Close command palette"
              >
                <FontAwesomeIcon icon={faTimes} />
              </button>
            </div>
            <input
              ref={commandPaletteInputRef}
              className="jas-command-input"
              type="text"
              value={commandQuery}
              onChange={(event) => setCommandQuery(event.target.value)}
              onKeyDown={(event) => {
                if (event.key === 'Escape') {
                  event.preventDefault();
                  setCommandPaletteOpen(false);
                  setCommandQuery('');
                  return;
                }
                if (event.key === 'Enter' && filteredCommandOptions.length > 0) {
                  event.preventDefault();
                  runCommandOption(filteredCommandOptions[0]);
                }
              }}
              placeholder="Type a command..."
              aria-label="Filter commands"
            />
            <div className="jas-command-list" role="listbox" aria-label="Available commands">
              {filteredCommandOptions.length === 0 ? (
                <p className="jas-command-empty">No matching commands.</p>
              ) : (
                filteredCommandOptions.map((option) => (
                  <button
                    key={option.id}
                    type="button"
                    className="jas-command-item"
                    onClick={() => runCommandOption(option)}
                  >
                    <strong>{option.label}</strong>
                    <span>{option.hint}</span>
                  </button>
                ))
              )}
            </div>
          </div>
        </div>
      )}

{/* Assistant Vertical Tab (Score + Scenarios only) */}
{activeTab !== 'chat' && (
  <JaspenAiDrawer
    id="jas-ai-drawer-panel"
    panelRef={aiDrawerPanelRef}
    messagesContainerRef={aiMessagesRef}
    messagesEndRef={aiMessagesEndRef}
    isOpen={aiDrawerOpen}
    onOpen={toggleAIDrawer}
    onClose={toggleAIDrawer}
    showSideTab={true}
    sideTabTop={sideTabSecond}
    tabs={isScenarioTab ? [{ key: 'assistant', label: 'Jaspen' }, { key: 'scorecard', label: 'Scorecard' }] : null}
    activeDrawerTab={scenarioDrawerView}
    onDrawerTabChange={setScenarioDrawerView}
    messages={messages}
    renderMessage={(m) => renderConversationMessage(m)}
    renderAttachments={(m) => renderMessageAttachments(m)}
    renderActions={(m, key, idx, total) => renderMessageActions(m, key, idx, total)}
    streamStatus={renderStreamToolStatus()}
    extraPanel={
      aiScenarioProposal ? (
        <div className="jas-ai-scenario-panel">
          <div className="jas-ai-scenario-head">
            <div className="jas-ai-scenario-title">AI Scenario Draft</div>
            <div className="jas-ai-scenario-sub">
              {aiScenarioProposal.preview?.jaspen_score != null
                ? `Projected score: ${aiScenarioProposal.preview.jaspen_score}`
                : 'Projected score unavailable'}
            </div>
          </div>

          <div className="jas-ai-scenario-field">
            <label>Scenario label</label>
            <input
              type="text"
              value={aiScenarioProposal.label}
              onChange={(e) => setAiScenarioProposal((prev) => (prev ? { ...prev, label: e.target.value } : prev))}
              disabled={aiScenarioBusy}
            />
          </div>

          <div className="jas-ai-scenario-field">
            <label>Desired outcome</label>
            <textarea
              rows={2}
              value={aiScenarioProposal.instruction}
              onChange={(e) => setAiScenarioProposal((prev) => (prev ? { ...prev, instruction: e.target.value } : prev))}
              disabled={aiScenarioBusy}
            />
          </div>

          <div className="jas-ai-scenario-field">
            <label>Objective profile</label>
            <select
              value={strategyObjective}
              onChange={(e) => applyStrategyObjective(e.target.value, { persist: true, markExplicit: true, silent: true })}
              disabled={aiScenarioBusy}
            >
              {OBJECTIVE_OPTIONS.map((option) => (
                <option key={option.key} value={option.key}>{option.label}</option>
              ))}
            </select>
          </div>

          {aiScenarioProposal.summary && (
            <p className="jas-ai-scenario-summary">{aiScenarioProposal.summary}</p>
          )}

          <div className="jas-ai-scenario-rows">
            {aiScenarioProposal.rows.map((row) => (
              <div className="jas-ai-scenario-row" key={row.key}>
                <div className="jas-ai-scenario-row-label">
                  <strong>{row.label}</strong>
                  <span>Current: {row.current}</span>
                </div>
                <div className="jas-ai-scenario-row-input">
                  <input
                    type="number"
                    value={row.value}
                    min={row.min}
                    max={row.max}
                    step={row.step}
                    disabled={aiScenarioBusy}
                    onChange={(e) => {
                      const nextVal = Number(e.target.value);
                      if (!Number.isFinite(nextVal)) return;
                      setProposalRowValue(row.key, nextVal);
                    }}
                  />
                  <button
                    type="button"
                    className="jas-ai-mini-btn"
                    onClick={() => removeProposalLever(row.key)}
                    disabled={aiScenarioBusy} aria-disabled={aiScenarioBusy}
                    title="Remove lever"
                  >
                    Remove
                  </button>
                </div>
                {row.rationale && <div className="jas-ai-scenario-rationale">{row.rationale}</div>}
              </div>
            ))}
          </div>

          {Array.isArray(aiScenarioProposal.availableLevers) && aiScenarioProposal.availableLevers.length > aiScenarioProposal.rows.length && (
            <div className="jas-ai-scenario-add">
              <select
                value={aiScenarioProposal.addLeverKey || ''}
                onChange={(e) => setProposalAddLeverKey(e.target.value)}
                disabled={aiScenarioBusy}
              >
                <option value="">Add lever...</option>
                {aiScenarioProposal.availableLevers
                  .filter((lever) => !aiScenarioProposal.rows.some((row) => row.key === lever.key))
                  .map((lever) => (
                    <option key={lever.key} value={lever.key}>{lever.label}</option>
                  ))}
              </select>
              <button type="button" className="jas-ai-mini-btn" onClick={addProposalLever} disabled={aiScenarioBusy || !aiScenarioProposal.addLeverKey} aria-disabled={aiScenarioBusy || !aiScenarioProposal.addLeverKey}>
                Add
              </button>
            </div>
          )}

          <div className="jas-ai-scenario-actions">
            <button type="button" className="jas-ai-mini-btn secondary" onClick={regenerateAiScenarioProposal} disabled={aiScenarioBusy} aria-disabled={aiScenarioBusy}>
              Modify (Regenerate)
            </button>
            <button type="button" className="jas-ai-mini-btn secondary" onClick={previewAiScenarioProposal} disabled={aiScenarioBusy} aria-disabled={aiScenarioBusy}>
              Update Preview
            </button>
            <button type="button" className="jas-ai-mini-btn danger" onClick={rejectAiScenarioProposal} disabled={aiScenarioBusy} aria-disabled={aiScenarioBusy}>
              Reject
            </button>
            <button type="button" className="jas-ai-mini-btn primary" onClick={acceptAiScenarioProposal} disabled={aiScenarioBusy || aiScenarioProposal.rows.length === 0} aria-disabled={aiScenarioBusy || aiScenarioProposal.rows.length === 0}>
              {aiScenarioBusy ? 'Applying…' : 'Accept'}
            </button>
          </div>
        </div>
      ) : null
    }
    input={aiInput}
    onInputChange={setAiInput}
    onInputKeyDown={(e) => {
      if (e.key === 'Enter' && !e.shiftKey) {
        e.preventDefault();
        sendAIMessage();
      }
    }}
    onSend={sendAIMessage}
    placeholder={aiDrawerPlaceholder}
    busy={busy}
    starterPrompts={scoreDrawerPrompts}
    inputExtras={renderObjectiveTags('jas-ai-objective-tags')}
    alternateContent={renderMiniScorecard(activeScorecard)}
    footer={
      <SidebarIdentityFooter
        displayName={displayName}
        planLabel={footerPlanLabel}
        onOpenDisplayNameEditor={openDisplayNameEditor}
        onOpenOnboardingEditor={openOnboardingEditor}
        onOpenBilling={() => setBillingModalOpen(true)}
        onLogout={handleLogout}
        onClose={() => setAiDrawerOpen(false)}
      />
    }
  />
)}

      <ThreadEditModal
        open={threadEditOpen}
        onClose={() => setThreadEditOpen(false)}
        sessionId={editableThreadId || sessionId}
        threadId={editableThreadId || sessionId}
        threadMode="auto"
        initialName={activeScorecard?.project_name || analysisResult?.project_name || ''}
        initialAdoptedAnalysisId={analysisResult?.analysis_id || ''}
        authFetch={authFetch}
        onSaved={(payload) => {
          if (payload?.name) {
            setAnalysisResult((prev) => prev ? { ...prev, project_name: payload.name } : prev);
            setBundleCurrentScorecard((prev) => prev ? { ...prev, project_name: payload.name } : prev);
            setBundleBaselineScorecard((prev) => prev ? { ...prev, project_name: payload.name } : prev);
            setScorecardSnapshots((prev) => (
              Array.isArray(prev)
                ? prev.map((snapshot) => ({ ...snapshot, project_name: payload.name }))
                : prev
            ));
            setAnalysisHistory((prev) => (
              Array.isArray(prev)
                ? prev.map((entry) => {
                    if (!entry || typeof entry !== 'object') return entry;
                    const entryId = String(entry.id || '').trim();
                    const resultId = String(entry?.result?.analysis_id || '').trim();
                    const currentActiveId = String(activeScorecard?.analysis_id || activeScorecard?.id || '').trim();
                    if (entryId !== String(editableThreadId || sessionId || '').trim() && resultId !== currentActiveId) {
                      return entry;
                    }
                    return {
                      ...entry,
                      result: entry.result && typeof entry.result === 'object'
                        ? { ...entry.result, project_name: payload.name }
                        : entry.result,
                    };
                  })
                : prev
            ));
          }
          refreshBundle(editableThreadId || sessionId);
        }}
      />

      <div
        id="jas-main-content"
        className={`jas-workspace ${aiDrawerOpen ? 'jas-ai-open' : ''} ${isReadinessOpen ? 'jas-readiness-open' : ''} ${isSettingsOpen ? 'jas-settings-open' : ''}`}
      >
          {(beginBusy || (busy && !isStreamingReply) || (busy && isStreamingReply)) && (
            <div className="jas-global-progress" role="status" aria-live="polite">
              <div className="jas-global-progress-track">
                <div className="jas-global-progress-bar" />
              </div>
              <span>{beginBusy ? beginMsg : (streamToolStatus || 'Jaspen is working...')}</span>
            </div>
          )}
          <div className="jas-workspace-header">
            {adminWorkspacePreviewActive && (
              <div className="jas-admin-preview-banner">
                Previewing Workspace as <strong>{supportRoleSwitchValue === 'actual' ? currentPlanLabel : (SUPPORT_ROLE_SWITCH_OPTIONS.find((option) => option.value === supportRoleSwitchValue)?.label || currentPlanLabel)}</strong> using your active organization data.
              </div>
            )}
            {mfaRolloutEligible && !mfaRolloutBannerDismissed && (
              <div className="jas-mfa-rollout-banner" role="status" aria-live="polite">
                <p>
                  Starting {MFA_ROLLOUT_NOTICE_DATE_LABEL}, MFA will be required for your account.
                  <button
                    type="button"
                    className="jas-mfa-rollout-link"
                    onClick={() => navigate('/account?tab=security')}
                  >
                    Set it up now
                  </button>
                </p>
                <button
                  type="button"
                  className="jas-mfa-rollout-dismiss"
                  onClick={dismissMfaRolloutBanner}
                  aria-label="Dismiss MFA reminder"
                >
                  <FontAwesomeIcon icon={faTimes} />
                </button>
              </div>
            )}
            {lowCreditsBannerEligible && !lowCreditsBannerDismissed && (
              <div className={`jas-low-credits-banner ${lowCreditsBannerToneClass}`} role="status" aria-live="polite">
                <div className="jas-low-credits-banner-copy">
                  <p className="jas-low-credits-banner-title">
                    <FontAwesomeIcon icon={faExclamationTriangle} />
                    <span>{lowCreditsHeadline}</span>
                  </p>
                  <p>{lowCreditsBody}</p>
                </div>
                <div className="jas-low-credits-banner-actions">
                  <button
                    type="button"
                    className="jas-low-credits-banner-link"
                    onClick={() => setBillingModalOpen(true)}
                  >
                    Open Billing
                  </button>
                  <button
                    type="button"
                    className="jas-low-credits-banner-dismiss"
                    onClick={dismissLowCreditsBanner}
                    aria-label="Dismiss low credits reminder"
                  >
                    <FontAwesomeIcon icon={faTimes} />
                  </button>
                </div>
              </div>
            )}
            {effectiveIsViewer && sessionId && (
              <div className="jas-viewer-badge">
                <FontAwesomeIcon icon={faLock} />
                Viewing as read-only
              </div>
            )}
            <div className="jas-workspace-header-top">
              <div className="jas-workspace-title">
                <div className="jas-project-title-row">
                  <h2 className="jas-project-title">
                    {workspaceProjectTitle}
                  </h2>
                  {sessionId && (
                    <button
                      type="button"
                      className="jas-project-title-edit"
                      onClick={() => setThreadEditOpen(true)}
                      title="Edit initiative title"
                      aria-label="Edit initiative title"
                    >
                      <FontAwesomeIcon icon={faPen} />
                      <span>Edit</span>
                    </button>
                  )}
                </div>
              </div>

              <button
                type="button"
                className="jas-return-main-btn"
                onClick={() => window.location.assign('/new')}
                title="Start a new Jaspen session"
                aria-label="Start a new Jaspen session"
              >
                <span className="jas-return-main-brand">
                  <img
                    src="/android-chrome-192x192.png"
                    alt=""
                    aria-hidden="true"
                    className="jas-return-main-logo"
                  />
                  <span className="jas-return-main-label">Jaspen</span>
                </span>
                <span className="jas-return-main-plus" aria-hidden="true">
                  <FontAwesomeIcon icon={faPlus} />
                </span>
              </button>
            </div>

            <nav className="jas-top-tabs" role="tablist" aria-label="Jaspen views">
              <TabButton id="summary"  label="Score" />
              <TabButton id="scenario" label="Scenarios" />

              {/* Only show dropdowns and Begin Project on Score tab */}
              {activeTab === 'summary' && (
                <div className="jas-right-rail" ref={scoreShellMenuRef}>
                  <div className={`jas-select-menu ${scoreShellMenu === 'scorecard' ? 'open' : ''}`}>
                    <button
                      type="button"
                      className="jas-select-trigger"
                      aria-haspopup="listbox"
                      aria-expanded={scoreShellMenu === 'scorecard'}
                      onClick={() => setScoreShellMenu((prev) => (prev === 'scorecard' ? null : 'scorecard'))}
                    >
                      <span>{selectedScoreLabel}</span>
                      <FontAwesomeIcon icon={faChevronDown} />
                    </button>
                    {scoreShellMenu === 'scorecard' && (
                      <div className="jas-select-dropdown" role="listbox" aria-label="Scorecard views">
                        {(useSnapshotSelect ? snapshotOptions : scoreVariants).map((option) => (
                          <div
                            key={option.id}
                            className={`jas-select-option-row ${scoreSelectValue === option.id ? 'selected' : ''}`}
                          >
                            <button
                              type="button"
                              className={`jas-select-option ${scoreSelectValue === option.id ? 'selected' : ''}`}
                              role="option"
                              aria-selected={scoreSelectValue === option.id}
                              onClick={async () => {
                                if (useSnapshotSelect) {
                                  handleSnapshotSelect(option.id);
                                } else {
                                  setSelectedVariantId(option.id);
                                }
                                setScoreShellMenu(null);
                              }}
                            >
                              {scoreSelectValue === option.id && <FontAwesomeIcon icon={faCheck} />}
                              <span>
                                {option.label}
                                {option.isBaseline ? ' (Baseline)' : option.isActive ? ' (Active)' : ''}
                              </span>
                            </button>
                            {useSnapshotSelect && (
                              <div className="jas-select-option-actions">
                                {!option.isActive && (
                                  <button
                                    type="button"
                                    className="jas-select-option-action"
                                    onClick={async (event) => {
                                      event.stopPropagation();
                                      await handleSnapshotSetActive(option.id, option.label);
                                      setScoreShellMenu(null);
                                    }}
                                    title="Set active"
                                    aria-label={`Set ${option.label} active`}
                                  >
                                    <FontAwesomeIcon icon={faCheck} />
                                  </button>
                                )}
                                {!option.isBaseline && (
                                  <button
                                    type="button"
                                    className="jas-select-option-action"
                                    onClick={async (event) => {
                                      event.stopPropagation();
                                      await handleSnapshotRename(option.id, option.label);
                                    }}
                                    title="Rename"
                                    aria-label={`Rename ${option.label}`}
                                  >
                                    <FontAwesomeIcon icon={faPen} />
                                  </button>
                                )}
                                {option.canDelete && (
                                  <button
                                    type="button"
                                    className="jas-select-option-action danger"
                                    onClick={async (event) => {
                                      event.stopPropagation();
                                      await handleSnapshotDelete(option.id, option.label);
                                    }}
                                    title="Delete"
                                    aria-label={`Delete ${option.label}`}
                                  >
                                    <FontAwesomeIcon icon={faTrash} />
                                  </button>
                                )}
                              </div>
                            )}
                          </div>
                        ))}
                      </div>
                    )}
                  </div>

                  <div className={`jas-select-menu ${scoreShellMenu === 'history' ? 'open' : ''}`}>
                    <button
                      type="button"
                      className="jas-select-trigger"
                      aria-haspopup="listbox"
                      aria-expanded={scoreShellMenu === 'history'}
                      onClick={() => setScoreShellMenu((prev) => (prev === 'history' ? null : 'history'))}
                    >
                      <span>{selectedCompletedScoreLabel}</span>
                      <FontAwesomeIcon icon={faChevronDown} />
                    </button>
                    {scoreShellMenu === 'history' && (
                      <div className="jas-select-dropdown" role="listbox" aria-label="Completed scores">
                        {completedScoreOptions.length === 0 ? (
                          <div className="jas-select-empty">No completed scores yet.</div>
                        ) : (
                          completedScoreOptions.map((option) => (
                            <button
                              key={option.id}
                              type="button"
                              className="jas-select-option"
                              role="option"
                              aria-selected="false"
                              onClick={() => {
                                if (option.result) {
                                  handleSelectAnalysis(option);
                                }
                                setScoreShellMenu(null);
                              }}
                            >
                              <span>{option.label}</span>
                            </button>
                          ))
                        )}
                      </div>
                    )}
                  </div>

                    <button
                      type="button"
                      className={`begin-project-btn ${hasProjectPlan ? 'is-project-ready' : ''}`}
                      onClick={() => {
                        if (hasProjectPlan) {
                          const tid = String(currentSessionId || sessionId || '').trim();
                          if (!tid) {
                            showToast('No active session. Open a scored thread first.', 'error');
                            return;
                          }
                          openExecutionPage(tid);
                          return;
                        }
                        void onBeginProject();
                      }}
                      disabled={beginBusy || (hasProjectPlan ? !canOpenProject : !canBeginProject)} aria-disabled={beginBusy || (hasProjectPlan ? !canOpenProject : !canBeginProject)}
                      title={projectActionTitle}
                    >
                      <FontAwesomeIcon
                        icon={beginBusy ? faSpinner : (hasProjectPlan ? faArrowUpRightFromSquare : faPlay)}
                        spin={beginBusy}
                      />
                      <span>{beginBusy ? 'Working…' : (hasProjectPlan ? 'Go to Project' : 'Project')}</span>
                    </button>
                  {hasProjectPlan && (
                    <div className="jas-project-ready-badge" aria-live="polite">
                      <span>Project plan created</span>
                      {activeScenarioProjectLabel && (
                        <strong>from {activeScenarioProjectLabel}</strong>
                      )}
                      <button
                        type="button"
                        className="jas-project-ready-link"
                        onClick={() => {
                          const tid = String(currentSessionId || sessionId || '').trim();
                          if (!tid) return;
                          openExecutionPage(tid);
                        }}
                      >
                        View →
                      </button>
                    </div>
                  )}
                  <button
                    type="button"
                    className="save-starter-btn"
                    onClick={openSaveStarterModal}
                    disabled={savingStarter || beginBusy || !(currentSessionId || sessionId)} aria-disabled={savingStarter || beginBusy || !(currentSessionId || sessionId)}
                  >
                    <span>{savingStarter ? 'Saving…' : 'Save as Starter'}</span>
                  </button>
                </div>
              )}

{/* ===== BEGIN: Begin Project overlay (fixed) ===== */}
{beginBusy && (
  <div
    style={{
      position: "fixed",
      inset: 0,
      background: "rgba(15, 23, 42, 0.55)",
      display: "flex",
      alignItems: "center",
      justifyContent: "center",
      zIndex: 9999,
      backdropFilter: "blur(2px)",
    }}
    aria-live="polite"
  >
    <div
      style={{
        background: "white",
        borderRadius: 12,
        padding: "20px 24px",
        minWidth: 280,
        boxShadow: "0 10px 30px rgba(0,0,0,.15)",
        textAlign: "center",
      }}
    >
      <div style={{ fontSize: 22, marginBottom: 10, fontWeight: 600, color: 'var(--color-text-primary)' }}>
        Getting Things Ready
      </div>
      <div style={{ marginBottom: 14, color: 'var(--color-text-secondary)' }}>{beginMsg}</div>
      <div style={{ display: "flex", gap: 6, justifyContent: "center" }}>
        {[0,1,2].map((i) => (
          <span
            key={i}
            style={{
              width: 8,
              height: 8,
              borderRadius: "50%",
              background: 'var(--color-brand-magenta)',
              display: "inline-block",
              animation: `jas-dot 1s ease-in-out ${i * 0.12}s infinite`,
            }}
          />
        ))}
      </div>
      <style>{`
        @keyframes jas-dot {
          0%, 80%, 100% { transform: translateY(0); opacity: .6; }
          40% { transform: translateY(-6px); opacity: 1; }
        }
      `}</style>
    </div>
  </div>
)}
{/* ===== END: Begin Project overlay ===== */}
            </nav>
          </div>

          <div className="jas-workspace-body">
{activeTab === 'summary' && (
  <div className={!sidebarState.settings || !aiDrawerOpen ? 'score-with-rail' : ''}>
    {!hasProjectPlan && canUseScenarios && !effectiveIsViewer && (
      <aside className="jas-summary-guidance-callout" aria-live="polite">
        <div className="jas-summary-guidance-copy">
          <strong>Before creating your plan:</strong>
          <span>Model scenarios to optimize your approach, then set one active for project generation.</span>
        </div>
        <button
          type="button"
          className="save-starter-btn"
          onClick={() => {
            setActiveTab('scenario');
            setView('scenario');
            if (sessionId || analysisResult?.analysis_id) {
              const tid = sessionId || analysisResult?.analysis_id;
              void refreshBundle(tid);
            }
          }}
        >
          Open Scenarios
        </button>
      </aside>
    )}
    <ErrorBoundary title="Scorecard unavailable" onRetry={() => sessionId && refreshBundle(sessionId)}>
      <ScoreDashboard
        analysisResult={activeScorecard}
        loading={bundleLoading && !activeScorecard}
        drawerOpen={aiDrawerOpen}
        onEditField={handleScoreCardFieldEdit}
        editEnabled

        scoreVariants={scoreVariants}
        selectedVariantId={selectedVariantId}
        onSelectVariant={setSelectedVariantId}

        scorecardSnapshots={scorecardSnapshots}
        selectedScorecardId={effectiveSelectedScorecardId}
        onSelectScorecard={handleSnapshotSelect}
        baselineScorecardId={baselineScorecardId}
        threadBundleId={sessionId}
        scoreCommentary={scoreCommentary}
        onOpenThreadEdit={() => setThreadEditOpen(true)}
        canExportScorecardPdf={canExportScorecardPdf}
        canExportScorecardPptx={canExportScorecardPptx}
        canExportWbsCsv={canExportWbsCsv}
        canExportConversationPdf={canExportConversationPdf}
        canExportConversationMarkdown={canExportConversationMarkdown}
        exportBusyType={exportBusyType}
        onExportScorecardPdf={handleExportScorecardPdf}
        onExportScorecardPptx={handleExportScorecardPptx}
        onExportWbsCsv={handleExportWbsCsv}
        onExportConversationPdf={handleExportConversationPdf}
        onExportConversationMarkdown={handleExportConversationMarkdown}
        canUndoManualEdits={canUndoScorecardManualEdit}
        canRedoManualEdits={canRedoScorecardManualEdit}
        onUndoManualEdit={undoScorecardManualEdit}
        onRedoManualEdit={redoScorecardManualEdit}
        manualEditHistoryBusy={scorecardEditHistoryBusy}

        onBackToMain={handleNewAnalysis}
        onOpenScenario={() => { setActiveTab('scenario'); setView('scenario'); }}
      />
    </ErrorBoundary>
  </div>
)}

            {activeTab === 'scenario' && (
              <>
	                {view === 'comparison' && savedScenarios.length > 0 ? (
	                  <ComparisonView
	                    baseAnalysis={analysisResult}
	                    scenarios={savedScenarios}
	                    onBackToScenario={() => { setView('scenario'); }}
	                    onBackToSummary={() => { setActiveTab('summary'); setView('summary'); }}
	                    onAdopt={handleScenarioAdopt}
	                  />
	                ) : (
	                  <ErrorBoundary title="Scenario modeler unavailable" onRetry={() => sessionId && refreshBundle(sessionId)}>
                    <ScenarioModeler
                      ref={scenarioModelerRef}
                      analysisId={sessionId}
                      loading={bundleLoading && !(bundleBaselineScorecard || baselineRef.current || analysisResult)}
                      baseAnalysis={bundleBaselineScorecard || baselineRef.current || analysisResult}
                      leverCatalog={leverCatalog}
                      outputMetrics={scenarioOutputMetrics}
                      scenarioLevers={scenarioLevers}
                      refreshVersion={scenarioMutationVersion}
                      savedScenarios={savedScenarios}
                      onRequestDeeperAnalysis={() => {
                        setAiDrawerOpen(true);
                        setScenarioDrawerView('assistant');
                        setHelpInput('Run a deeper financial analysis for this project');
                      }}
                      onScenarioSaved={handleScenarioSaved}
                      onAdoptScenario={handleScenarioAdopt}
                      onBackToSummary={() => { setActiveTab('summary'); setView('summary'); }}
                      onCompare={handleCompareScenarios}
                      onResultA={(res) => { setResultA(res); }}
                      onResultB={(res) => { setResultB(res); }}
                      onResultC={(res) => { setResultC(res); }}
                      onConvertToProject={() => {
                        storage.saveProject({
                          id: `proj_${Date.now()}`,
                          source_analysis_id: sessionId,
                          createdAt: Date.now(),
                          title: deriveIdeaTitle({ result: analysisResult, messages, fallback: 'Untitled Idea' }),
                          payload: analysisResult,
                        });
                        const nextParams = new URLSearchParams();
                        if (sessionId) nextParams.set('sid', String(sessionId));
                        const currentParams = new URLSearchParams(location.search);
                        ['admin_preview', 'plan_key', 'role'].forEach((key) => {
                          const value = String(currentParams.get(key) || '').trim();
                          if (value) nextParams.set(key, value);
                        });
                        navigate(`/execution-plan${nextParams.toString() ? `?${nextParams.toString()}` : ''}`);
                      }}
                    />
                  </ErrorBoundary>
                )}
              </>
            )}
          </div>
        </div>
        </main>
      </div>
    );
  };

  // =========================
  // ======== RENDERS ========
  // =========================

  // If we have an analysis, render the workspace with tabs (post-Analyze)
  if (analysisResult && view !== 'intake') {
    return renderWorkspaceShell();
  }

  if (initialRestorePending) {
    return (
      <div className="jas jas-shell">
        <main className="jas-main" aria-label="Jaspen workspace">
          <div className="jas-restore-shell" />
        </main>
      </div>
    );
  }

  // Default: conversational intake (no tabs)
  const intakeShellOpen = sidebarState.history || sidebarState.readiness || sidebarState.settings;
  const intakeHasReadinessTab = sessionId && messages.length > 0 && !sidebarState.readiness;
  const showIntakeTopbarUtilities = !sessionId && messages.length === 0;
  const showTopbarCredits = Boolean(user);
  const showSharedProjectsLanding = !sessionId && messages.length === 0 && planCategory !== 'individual' && (effectiveIsCollaborator || effectiveIsViewer);
  const onboardingState = readOnboardingState(user);
  const shouldShowSetupPrompt = Boolean(
    user &&
    !showSharedProjectsLanding &&
    !nameModalOpen &&
    !onboardingOpen &&
    messages.length === 0 &&
    !sessionId &&
    !currentSessionId &&
    (
      (!displayName && !readNamePromptDeferred(user)) ||
      (!onboardingState?.completed && !onboardingState?.deferred)
    )
  );
  const shouldShowGuidedFlow = Boolean(
    user &&
    onboardingState?.completed &&
    !guidedFlowDismissed &&
    !showSharedProjectsLanding &&
    !nameModalOpen &&
    !onboardingOpen &&
    messages.length === 0 &&
    !sessionId &&
    !currentSessionId
  );
  const showOnboarding = onboardingOpen && !nameModalOpen && !showSharedProjectsLanding;
  const intakeTabs = [];
  if (!sidebarState.settings) intakeTabs.push('settings');
  if (hasHistory && !sidebarState.history) intakeTabs.push('history');
  if (intakeHasReadinessTab) intakeTabs.push('readiness');
  const intakeTabTop = (key) => {
    const idx = intakeTabs.indexOf(key);
    return `${128 + idx * 130}px`;
  };
  return (
    <div className={`jas jas-shell ${intakeShellOpen ? 'drawer-open' : ''}`}>
      <a href="#jas-main-content" className="jas-skip-link">Skip to main content</a>
      <main className="jas-main" aria-label="Jaspen intake workspace">
        <div className="jas-sr-only" aria-live="polite" aria-atomic="true">{liveStatusMessage}</div>
        <div className="agent-chat-interface">
      {busy && !isStreamingReply && (
        <div className="thinking-overlay">
          <div className="thinking-content">
            <FontAwesomeIcon icon={faSpinner} spin />
            <span>{sessionId ? "Thinking..." : "Starting conversation..."}</span>
          </div>
        </div>
      )}

      {/* Drawer Tabs on Left Edge */}
      {!sidebarState.settings && (
        <button
          type="button"
          className="jas-drawer-tab jas-drawer-tab-settings"
          style={{ top: intakeTabTop('settings') }}
          onClick={() => dispatchSidebar({ type: 'TOGGLE_SETTINGS' })}
          aria-label="Open user settings"
          aria-expanded={sidebarState.settings}
          aria-controls="jas-intake-settings-panel"
        >
          <FontAwesomeIcon icon={faBars} />
          MENU
        </button>
      )}
      {hasHistory && !sidebarState.history && (
        <button
          type="button"
          className="jas-drawer-tab jas-drawer-tab-history"
          style={{ top: intakeTabTop('history') }}
          onClick={() => dispatchSidebar({ type: 'TOGGLE_HISTORY' })}
          aria-label="Open analysis history"
          aria-expanded={sidebarState.history}
          aria-controls="jas-intake-history-panel"
        >
          <FontAwesomeIcon icon={faClockRotateLeft} />
          HISTORY
        </button>
      )}
      {intakeHasReadinessTab && (
        <button
          type="button"
          className={`jas-drawer-tab jas-drawer-tab-readiness ${sessionId && messages.length > 0 ? 'active' : ''}`}
          style={{ top: intakeTabTop('readiness') }}
          onClick={() => dispatchSidebar({ type: 'OPEN_READINESS' })}
          aria-label="Open analysis readiness"
          aria-expanded={sidebarState.readiness}
          aria-controls="jas-intake-readiness-panel"
        >
          <FontAwesomeIcon icon={faGaugeHigh} />
          READINESS
        </button>
      )}

      {/* Drawer Overlay - non-blocking, just visual dimming */}

      {/* LEFT SIDEBAR - Readiness */}
      <aside
        id="jas-intake-readiness-panel"
        className={`jas-left-sidebar jas-readiness-sidebar ${sidebarState.readiness ? 'sidebar-open' : ''}`}
        aria-labelledby="jas-intake-readiness-title"
      >
        <div className="jas-sidebar-header">
          <h3 id="jas-intake-readiness-title">Analysis Readiness</h3>
          <button
            className="jas-sidebar-close"
            onClick={() => dispatchSidebar({ type: 'CLOSE_READINESS' })}
            aria-label="Close analysis readiness"
          >
            <FontAwesomeIcon icon={faTimes} />
          </button>
        </div>
        <div className="jas-sidebar-content">
          <div className="jas-readiness-display">
            <div className="jas-readiness-circle">
              <svg className="jas-progress-ring" width="120" height="120">
                <circle className="jas-progress-ring-bg" stroke="var(--color-border-default)" strokeWidth="8" fill="transparent" r="52" cx="60" cy="60" />
                <circle
                  className="jas-progress-ring-fill"
                  stroke="var(--color-status-success)"
                  strokeWidth="8"
                  fill="transparent"
                  r="52"
                  cx="60" cy="60"
                  strokeDasharray={`${(uiReadiness / 100) * READINESS_CIRC} ${READINESS_CIRC}`}
                  strokeDashoffset="0"
                  transform="rotate(-90 60 60)"
                />
              </svg>
              <div className="jas-readiness-percent">{Math.round(uiReadiness)}%</div>
            </div>
<div className="jas-readiness-status">
  {uiReadiness < 60 ? 'Gathering information...' : uiReadiness < 90 ? 'Almost ready!' : 'Ready to analyze!'}
</div>

{(readinessSource || readinessVersion) && (
  <div className="jas-readiness-meta" style={{ marginTop: '6px', fontSize: '12px', color: 'var(--color-text-muted)' }}>
    {readinessSource && (
      <span className="jas-chip" style={{
        display: 'inline-block', padding: '2px 6px', borderRadius: '8px',
        border: '1px solid var(--color-border-default)', marginRight: '6px'
      }}>
        Source: {readinessSource.toUpperCase()}
      </span>
    )}
    {readinessVersion && (
      <span className="jas-chip" style={{
        display: 'inline-block', padding: '2px 6px', borderRadius: '8px',
        border: '1px solid var(--color-border-default)'
      }}>
        {readinessVersion}
      </span>
    )}
  </div>
)}
          </div>

{renderReadinessChecklist()}
        </div>
        <SidebarIdentityFooter
          displayName={displayName}
          planLabel={footerPlanLabel}
          onOpenDisplayNameEditor={openDisplayNameEditor}
          onOpenOnboardingEditor={openOnboardingEditor}
          onOpenBilling={() => setBillingModalOpen(true)}
          onLogout={handleLogout}
          onClose={() => dispatchSidebar({ type: 'CLOSE_READINESS' })}
        />
      </aside>

      {/* LEFT SIDEBAR - History */}
      {hasHistory && (
        <aside
          id="jas-intake-history-panel"
          className={`jas-left-sidebar jas-history-sidebar ${sidebarState.history ? 'sidebar-open' : ''}`}
          aria-labelledby="jas-intake-history-title"
        >
          <div className="jas-sidebar-header jas-sidebar-header-history">
            <button
              className="jas-sidebar-clear jas-sidebar-clear-left"
              onClick={handleClearHistory}
              disabled={clearingHistory || analysisHistory.length === 0} aria-disabled={clearingHistory || analysisHistory.length === 0}
              title="Clear all history"
            >
              {clearingHistory ? 'Clearing…' : 'Clear'}
            </button>
            <h3 id="jas-intake-history-title">Analysis History</h3>
            <button
              className="jas-sidebar-close"
              onClick={() => dispatchSidebar({ type: 'CLOSE_HISTORY' })}
              aria-label="Close analysis history"
            >
              <FontAwesomeIcon icon={faTimes} />
            </button>
          </div>
          <div className="jas-sidebar-content">
            <div className="jas-history-search">
              <input
                ref={historySearchInputRef}
                type="search"
                className="jas-history-search-input"
                placeholder="Search history"
                value={historySearch}
                onChange={(e) => setHistorySearch(e.target.value)}
                aria-label="Search analysis history"
              />
            </div>
            {filteredAnalysisHistory.length === 0 && historySearch.trim() ? (
              <div className="jas-no-history">
                No matching sessions for "{historySearch.trim()}".
              </div>
            ) : (
              filteredAnalysisHistory.map(({ item, title, matchSnippet }, index) => (
                <div key={item.id || index} className="jas-history-item">
                  <button
                    type="button"
                    className="jas-history-item-select"
                    onClick={() => handleSelectAnalysis(item)}
                    aria-label={`Open ${title || `Analysis ${item.id?.slice(-8) || index + 1}`}`}
                  >
                    <div className="hi-text">
                      <div className="hi-title">
                        {title || `Analysis ${item.id?.slice(-8) || index + 1}`}
                      </div>
                      <div className="hi-meta">
                        <span>{formatHistoryLastUsed(item.lastUsedAt || item.createdAt)}</span>
                        {item.result?.jaspen_score && (<span className="hi-score">Score: {item.result.jaspen_score}</span>)}
                      </div>
                      {matchSnippet ? (
                        <div className="hi-snippet">{matchSnippet}</div>
                      ) : null}
                    </div>
                  </button>
                  <button
                    className="hi-delete"
                    type="button"
                    onClick={() => {
                      handleDeleteAnalysis(item.id);
                    }}
                    title="Delete"
                    aria-label={`Delete ${title || `analysis ${item.id?.slice(-8) || index + 1}`}`}
                  >
                    <FontAwesomeIcon icon={faTrash} />
                  </button>
                </div>
              ))
            )}
          </div>
        </aside>
      )}

      {/* LEFT SIDEBAR - User Settings */}
      <aside
        id="jas-intake-settings-panel"
        className={`jas-left-sidebar jas-settings-sidebar ${sidebarState.settings ? 'sidebar-open' : ''}`}
        aria-labelledby="jas-intake-settings-title"
      >
        <div className="jas-sidebar-header">
          <h3 id="jas-intake-settings-title">User Settings</h3>
          <button
            className="jas-sidebar-close"
            onClick={() => dispatchSidebar({ type: 'CLOSE_SETTINGS' })}
            aria-label="Close user settings"
          >
            <FontAwesomeIcon icon={faTimes} />
          </button>
        </div>
        <div className="jas-sidebar-content">
          {renderUserMenuContent(() => dispatchSidebar({ type: 'CLOSE_SETTINGS' }))}
        </div>
      </aside>

      {/* Header - Manus Style Top Bar */}
      <div className="jas-chat-topbar">
        <div className="jas-topbar-left">
          <button
            type="button"
            className="jas-topbar-title jas-topbar-link"
            onClick={() => window.location.reload()}
            title="Refresh"
          >
            Jaspen
          </button>
          {canStartOrgProjects && (
            <button
              className="jas-topbar-new"
              onClick={() => handleNewAnalysis(true)}
              title="New Session"
              aria-label="New Session"
            >
              <FontAwesomeIcon icon={faPlus} />
            </button>
          )}
        </div>

        <div className="jas-topbar-right">
          {showIntakeTopbarUtilities && (
            <>
              <button
                type="button"
                className="jas-topbar-bell"
                onClick={() => {
                  setNotificationsMode('bell');
                  setNotificationsOpen(true);
                }}
                title="Notifications"
                aria-label="Open notifications"
              >
                <FontAwesomeIcon icon={faBell} />
                {unreadNotificationCount > 0 && (
                  <span className="jas-topbar-bell-count">{unreadNotificationCount}</span>
                )}
              </button>
            </>
          )}
          {showTopbarCredits && (
            <button
              type="button"
              className={`jas-topbar-credits ${creditsTone === 'warning' ? 'is-warning' : ''} ${creditsTone === 'critical' ? 'is-critical' : ''}`.trim()}
              onClick={() => setBillingModalOpen(true)}
              title={creditsTitle}
              aria-label="View credits"
            >
              <FontAwesomeIcon icon={faBolt} />
              <span>{intakeCreditsCompactLabel}</span>
            </button>
          )}
        </div>
      </div>

      {renderNotificationsModal()}
      {renderNameModal()}
      {renderBillingModal()}
      {renderPostAdoptWbsPrompt()}
      <Onboarding
        open={showOnboarding}
        canGoBack={!displayName}
        canSkip
        onBack={() => {
          setOnboardingOpen(false);
          setNameModalMode('required');
          setNameModalOpen(true);
        }}
        onSkip={() => {
          const previousSelection = readOnboardingState(user)?.selection || onboardingInitialSelection || null;
          writeOnboardingState(user, {
            completed: false,
            deferred: true,
            selection: previousSelection,
          });
          void persistOnboardingProfileState({
            completed: false,
            deferred: true,
            selection: previousSelection,
          });
          setOnboardingOpen(false);
          upsertNotification(SETUP_REMINDER_NOTIFICATION);
          showToast('Saved for later. You can find this reminder in Notifications and Account settings.', 'info');
        }}
        onComplete={handleOnboardingComplete}
        initialSelection={onboardingInitialSelection}
        submitLabel={onboardingMode === 'settings' ? 'Save preferences' : 'Start'}
        busy={Boolean(onboardingLaunchLabel)}
        busyLabel={onboardingLaunchLabel}
      />
      {preflightOpen && (
        <div className="jas-modal-overlay" role="dialog" aria-modal="true" aria-labelledby="preflight-title">
          <div className="jas-modal-card preflight-panel">
            <h2 id="preflight-title" className="preflight-title">Before we build the plan</h2>
            <p className="preflight-subtitle">
              Jaspen needs a few details to create the most useful execution plan for your team.
              All fields are optional and you can skip anything that does not apply.
            </p>
            <div className="preflight-questions">
              {preflightQuestions.map((question) => (
                <div key={question.id} className="preflight-q">
                  <label htmlFor={`pf-${question.id}`} className="preflight-label">{question.label}</label>
                  <textarea
                    id={`pf-${question.id}`}
                    className="preflight-textarea"
                    value={preflightAnswers[question.id] || ''}
                    onChange={(event) => setPreflightAnswers((prev) => ({
                      ...prev,
                      [question.id]: event.target.value,
                    }))}
                    rows={2}
                    placeholder="Optional"
                  />
                </div>
              ))}
            </div>
            <div className="preflight-actions">
              <button
                type="button"
                className="sc-btn sc-btn-primary"
                onClick={() => {
                  setPreflightOpen(false);
                  void onBeginProject(preflightAnswers);
                }}
              >
                Generate execution plan
              </button>
              <button
                type="button"
                className="sc-btn sc-btn-secondary"
                onClick={() => setPreflightOpen(false)}
              >
                Cancel
              </button>
            </div>
          </div>
        </div>
      )}
      <BatchIdeaManager
        open={batchIdeasOpen}
        onClose={() => setBatchIdeasOpen(false)}
        onOpenBilling={() => setBillingModalOpen(true)}
        onOpenThread={handleOpenBatchIdeaThread}
        onRefreshSessions={fetchSessions}
        canUseBatchIdeas={canUseBatchIdeas}
        isLocked={batchIdeasLocked}
        canPromoteBatchIdeas={canStartOrgProjects && canUseBatchIdeas}
        showToast={showToast}
        lockReason={batchIdeasLockReason}
        onBatchActivity={handleBatchIdeasActivity}
      />
      {saveStarterModalOpen && (
        <div className="jas-modal-overlay" role="dialog" aria-modal="true" aria-label="Save starter configuration">
          <div className="jas-modal-card jas-save-starter-modal">
            <div className="jas-modal-head">
              <h3>Save as Starter</h3>
              <button
                type="button"
                className="jas-ai-mini-btn"
                onClick={() => setSaveStarterModalOpen(false)}
                disabled={savingStarter} aria-disabled={savingStarter}
              >
                Close
              </button>
            </div>
            <div className="jas-modal-body">
              <div className="jas-save-starter-form">
                <label htmlFor="jas-starter-name">Name</label>
                <input
                  id="jas-starter-name"
                  type="text"
                  value={newStarterName}
                  maxLength={255}
                  onChange={(e) => setNewStarterName(e.target.value)}
                  disabled={savingStarter}
                  placeholder="Growth Playbook Starter"
                />

                <label htmlFor="jas-starter-description">Description (optional)</label>
                <textarea
                  id="jas-starter-description"
                  rows={3}
                  value={newStarterDescription}
                  onChange={(e) => setNewStarterDescription(e.target.value)}
                  disabled={savingStarter}
                  placeholder="Context and assumptions this starter captures."
                />

                <div className="jas-save-starter-actions">
                  <button
                    type="button"
                    className="jas-ai-mini-btn secondary"
                    onClick={() => setSaveStarterModalOpen(false)}
                    disabled={savingStarter} aria-disabled={savingStarter}
                  >
                    Cancel
                  </button>
                  <button
                    type="button"
                    className="jas-ai-mini-btn primary"
                    onClick={handleSaveStarter}
                    disabled={savingStarter || !String(newStarterName || '').trim()} aria-disabled={savingStarter || !String(newStarterName || '').trim()}
                  >
                    {savingStarter ? 'Saving…' : 'Save Starter'}
                  </button>
                </div>
              </div>
            </div>
          </div>
        </div>
      )}

      {/* Content */}
      <div id="jas-main-content" className="jas-chat-content">
        {showSharedProjectsLanding ? (
          <div className="jas-shared-projects-landing">
            <h2>Shared Projects</h2>
            <p className="jas-shared-projects-sub">
              {effectiveIsViewer
                ? 'Projects shared with you for viewing.'
                : 'Projects shared with you for collaboration.'}
            </p>

            {sharedProjectsLoading && (
              <p className="jas-shared-projects-empty">Loading shared projects...</p>
            )}

            {!sharedProjectsLoading && visibleSharedProjects.length === 0 && (
              <div className="jas-shared-projects-empty-state">
                <p>
                  {effectiveIsViewer
                    ? "You haven't been invited to view any projects yet."
                    : "You haven't been invited to collaborate on any projects yet."}
                </p>
                <p>When a project owner shares a project with you, it will appear here.</p>
              </div>
            )}

            {!sharedProjectsLoading && visibleSharedProjects.length > 0 && (
              <div className="jas-shared-projects-list">
                {visibleSharedProjects.map((project) => (
                  <button
                    key={project.session_id}
                    type="button"
                    className="jas-shared-project-card"
                    onClick={() => navigate(`/new?session_id=${encodeURIComponent(project.session_id)}`)}
                  >
                    <strong>{project.name || 'Untitled Project'}</strong>
                    <span>Owner: {project.owner_name || 'Unknown'}</span>
                    <span>Status: {project.status || 'active'}</span>
                    <span>Updated: {project.updated_at ? new Date(project.updated_at).toLocaleString() : '—'}</span>
                    <span className="jas-shared-project-access">
                      {effectiveIsViewer ? 'View only' : 'Can edit'}
                    </span>
                  </button>
                ))}
              </div>
            )}
          </div>
        ) : messages.length === 0 ? (
          <div className="jas-chat-welcome">
            <h2 className="jas-chat-welcome-title">
              <img
                className="jas-chat-welcome-unicorn"
                src="/android-chrome-192x192.png"
                alt="Jaspen mascot logo"
              />
              <span>{welcomeHeading}</span>
            </h2>
            {shouldShowSetupPrompt ? (
              <div className="jas-setup-prompt" role="note" aria-label="Optional setup prompt">
                <div className="jas-setup-prompt-copy">
                  <span className="jas-setup-prompt-eyebrow">Optional setup</span>
                  <div className="jas-setup-prompt-copy-main">
                    <div>
                      <h3>Tailor Jaspen to how you work</h3>
                      <p>Choose a display name, role, and starting preference now, or come back anytime from Account settings.</p>
                    </div>
                    <div className="jas-setup-prompt-actions">
                      <button
                        type="button"
                        className="jas-setup-prompt-secondary"
                        onClick={deferSetupPrompt}
                      >
                        Maybe later
                      </button>
                      <button
                        type="button"
                        className="jas-setup-prompt-primary"
                        onClick={openSetupPromptFlow}
                      >
                        Set up now
                      </button>
                    </div>
                  </div>
                </div>
              </div>
            ) : null}
            {shouldShowGuidedFlow ? (
              <div className="jas-guided-flow" role="note" aria-label="Guided walkthrough">
                <div className="jas-guided-flow-head">
                  <span className="jas-guided-flow-kicker">First run guide</span>
                  <h3>Follow this flow once to see how Jaspen works end-to-end.</h3>
                </div>
                <ol className="jas-guided-flow-steps">
                  <li>Describe the initiative in chat and answer intake questions.</li>
                  <li>Generate a scorecard and review the executive summary.</li>
                  <li>Open Scenarios to compare leverage options and set one active.</li>
                  <li>Generate the execution plan and refine tasks, owners, and due dates.</li>
                </ol>
                <div className="jas-guided-flow-actions">
                  <button
                    type="button"
                    className="jas-guided-flow-primary"
                    onClick={launchGuidedFlow}
                  >
                    Start guided run
                  </button>
                  <button
                    type="button"
                    className="jas-guided-flow-secondary"
                    onClick={dismissGuidedFlow}
                  >
                    Hide guide
                  </button>
                </div>
              </div>
            ) : null}
            <p>Describe your project or goal, and I&apos;ll help you build a complete strategy scorecard with clear priorities and execution steps.</p>
          </div>
        ) : (
          <>
            <div className="jas-messages">
              {error && (
                <div className="agent-chat-error">
                  <FontAwesomeIcon icon={faExclamationTriangle} />
                  <span>{error}</span>
                </div>
              )}

	              {messages.map((m, idx) => (
	                <div key={idx} className={`jas-message ${m.role === 'ai' ? 'ai' : 'user'}`}>
	                  <div className="jas-message-bubble">{renderConversationMessage(m)}</div>
	                  {renderMessageAttachments(m)}
	                  {renderMessageActions(m, `main:${idx}`, idx, messages.length)}
	                </div>
	              ))}

              <div ref={endRef} />
            </div>
            {renderStreamToolStatus()}
          </>
        )}

        {/* Input Area - Manus Style */}
        {!showSharedProjectsLanding && (
        <div className="jas-chat-input-area">
          {renderStarterSelector()}
          <input
            ref={fileInputRef}
            id="jas-file-input"
            type="file"
            multiple
            accept="image/*,.pdf,.doc,.docx,.ppt,.pptx,.xls,.xlsx,.csv,.txt,.md"
            onChange={onFilesSelected}
            style={{ display: 'none' }}
          />

          {pendingFiles?.length > 0 && (
            <div className="jas-file-chips" style={{ maxWidth: '800px', margin: '0 auto 8px', display: 'flex', flexWrap: 'wrap', gap: '4px' }}>
              {pendingFiles.map((f, i) => (
                <span key={i} style={{ display: 'inline-flex', alignItems: 'center', gap: '4px', padding: '4px 8px', background: 'var(--color-bg-subtle)', borderRadius: '4px', fontSize: '0.75rem' }}>
                  {f.name}
                  <button
                    type="button"
                    style={{ background: 'none', border: 'none', cursor: 'pointer', padding: '0', fontSize: '0.875rem', color: 'var(--color-text-muted)' }}
                    title="Remove"
                    onClick={() => setPendingFiles(prev => prev.filter((_, idx) => idx !== i))}
                  >
                    ×
                  </button>
                </span>
              ))}
            </div>
          )}

          <div className="jas-chat-input-box">
            <textarea
              ref={intakeInputRef}
              value={input}
              onChange={handleComposerInputChange}
              onKeyDown={onKey}
              placeholder={sessionId ? "Continue the conversation..." : "Describe your project or goal..."}
              rows={2}
              disabled={busy || effectiveIsViewer}
            />
            <div className="jas-chat-input-toolbar">
              <div className="jas-chat-input-left-controls">
                <button
                  type="button"
                  className="jas-ci-btn"
                  aria-label="Attach files"
                  title="Attach"
                  disabled={busy || effectiveIsViewer} aria-disabled={busy || effectiveIsViewer}
                  onClick={() => fileInputRef.current?.click()}
                >
                  <FontAwesomeIcon icon={faPaperclip} />
                </button>
                {renderModelTypeInlinePicker()}
                {renderSelectedObjectivePill()}
                {renderSelectedDataContextPills()}
              </div>
              <div className="jas-chat-input-right-controls">
                <button
                  type="button"
                  className={`jas-ci-btn ${isRecording ? 'recording' : ''}`}
                  aria-label={isRecording ? 'Stop recording' : 'Start recording'}
                  title="Voice"
                  disabled={busy || effectiveIsViewer} aria-disabled={busy || effectiveIsViewer}
                  onClick={() => setIsRecording(prev => !prev)}
                >
                  <FontAwesomeIcon icon={faMicrophone} />
                </button>
                <button
                  className="jas-ci-btn send"
                  onClick={onSubmit}
                  disabled={busy || effectiveIsViewer || (!input.trim() && pendingFiles.length === 0)} aria-disabled={busy || effectiveIsViewer || (!input.trim() && pendingFiles.length === 0)}
                  title="Send"
                >
                  {busy ? <FontAwesomeIcon icon={faSpinner} spin /> : <FontAwesomeIcon icon={faArrowUp} />}
                </button>
              </div>
            </div>
          </div>

          {renderObjectiveTags('jas-chat-objective-tags')}
          {renderConnectorContextTags()}

          {sessionId && hasConversationMessages && (
            <div className="agent-chat-footer">
              <div className="progress-indicator">
                <div className="progress-bar-container">
                  <div className="progress-bar-fill" style={{ width: `${uiReadiness}%` }}></div>
                </div>
                <span className="progress-text">{Math.round(uiReadiness)}% ready</span>
              </div>
              <button
                className="finish-analyze-btn"
                onClick={onFinishAnalyze}
                disabled={!canAnalyze || busy || effectiveIsViewer} aria-disabled={!canAnalyze || busy || effectiveIsViewer}
                title={effectiveIsViewer ? 'Viewers cannot generate new scorecards' : (canAnalyze ? "Generate your Jaspen score" : "Keep chatting to gather more information")}
              >
                <FontAwesomeIcon icon={faCheck} />
                <span>Finish & Analyze</span>
              </button>
            </div>
          )}
        </div>
        )}
      </div>

      {/* Help Modal */}
      {helpOpen && (
        <div className="jas-help-modal">
          <div className="jas-help-content">
            <div className="jas-help-header">
              <h3>Help & Support</h3>
              <button className="jas-help-close" onClick={() => setHelpOpen(false)} aria-label="Close help">
                <FontAwesomeIcon icon={faTimes} />
              </button>
            </div>

            <div className="jas-help-messages">
              {helpMessages.length === 0 ? (
                <div className="jas-help-welcome">
                  <p>Hi! I'm here to help you with:</p>
                  <ul>
                    <li>Understanding Jaspen features</li>
                    <li>Navigating the platform</li>
                    <li>Project management tools</li>
                    <li>Lean Six Sigma resources</li>
                  </ul>
                  <p>Keyboard shortcuts:</p>
                  <ul>
                    <li><strong>?</strong> Open help</li>
                    <li><strong>Ctrl/Cmd + K</strong> Open command palette</li>
                    <li><strong>/</strong> Focus composer</li>
                    <li><strong>Esc</strong> Close drawers, modals, and dialogs</li>
                    <li><strong>Alt + Shift + N</strong> Start a new session</li>
                  </ul>
                  <p>What can I help you with?</p>
                </div>
              ) : (
                helpMessages.map((msg, idx) => (
                  <div key={idx} className={`jas-help-message ${msg.role}`}>
                    <div className="jas-help-bubble">
                      {msg.role === 'user' ? (
                        msg.content
                      ) : (
                        <ReactMarkdown remarkPlugins={[remarkGfm]}>
                          {String(msg.content || '')}
                        </ReactMarkdown>
                      )}
                    </div>
                  </div>
                ))
              )}
              {helpLoading && (
                <div className="jas-help-loading">
                  <span>Thinking...</span>
                </div>
              )}
            </div>

            <div className="jas-help-input">
              <textarea
                value={helpInput}
                onChange={(e) => setHelpInput(e.target.value)}
                onKeyPress={(e) => {
                  if (e.key === 'Enter' && !e.shiftKey) {
                    e.preventDefault();
                    sendHelpMessage();
                  }
                }}
                placeholder="Ask a question..."
                disabled={helpLoading}
              />
              <button onClick={sendHelpMessage} disabled={helpLoading || !helpInput.trim()} aria-disabled={helpLoading || !helpInput.trim()} aria-label="Send help message">
                <FontAwesomeIcon icon={faPaperPlane} />
              </button>
            </div>
          </div>
        </div>
      )}
        </div>
      </main>

      {/* Fixed bottom-right tips carousel */}
      {tipIndex < WORKSPACE_TIPS.length && (
        <div
          key={WORKSPACE_TIPS[tipIndex].id}
          className={`jas-floattip${tipExiting ? ' is-exiting' : ''}`}
          role="note"
          aria-label="Tip"
        >
          <button className="jas-floattip-close" onClick={dismissTip} aria-label="Dismiss tip">×</button>
          <p className="jas-floattip-title">{WORKSPACE_TIPS[tipIndex].title}</p>
          <p className="jas-floattip-body">{WORKSPACE_TIPS[tipIndex].body}</p>
          <div className="jas-floattip-dots">
            {WORKSPACE_TIPS.map((t, i) => (
              <span
                key={t.id}
                className={`jas-floattip-dot${i === tipIndex ? ' active' : i < tipIndex ? ' past' : ''}`}
              />
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
