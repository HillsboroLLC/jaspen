// ============================================================================
// File: frontend/src/jaspenInterface/Workspace/JaspenChat.jsx
// Purpose: The main chat-first interface — conversation, inline scorecards,
//          Trade-off and Execution tabs. Renamed from JaspenWorkspace.jsx
//          to free that name for the new canvas-style Workspace editor.
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
import { AUTH_EVENTS, authFetch as cookieAuthFetch, buildAuthHeaders } from '../../shared/auth/http';
import { getPlanConnectorSentence } from '../../shared/billing/planConnectors';

import { FontAwesomeIcon } from '@fortawesome/react-fontawesome';
import {
  faQuestionCircle,
  faPaperPlane, faSpinner, faTimes, faBars, faCheck, faExclamationTriangle,
  faChartLine, faTrash, faPlus, faMinus, faMicrophone,
  faBolt, faLayerGroup, faPlay, faListCheck, faArrowUpRightFromSquare, faGaugeHigh, faClockRotateLeft, faPaperclip, faFolder, faArrowUp,
  faDownload, faChevronDown, faChevronLeft, faChevronRight, faUser, faBell, faLock, faCopy, faThumbsUp, faThumbsDown, faRotate, faPen, faArrowRightArrowLeft,
} from '@fortawesome/free-solid-svg-icons';
import {
  MonitorCheck, MessageCircleQuestion,
  Sigma, Plus as LucidePlus, BarChart3
} from 'lucide-react';

// Data / storage
import { Jaspen, storage } from './JaspenClient';

// Tab components
import ScoreDashboard   from './ScoreDashboard';
import TradeoffView     from './TradeoffView';
import {
  COLOR as EXEC_COLOR,
  Eyebrow,
  Pill as ExecPill,
  Avatar as ExecAvatar,
  StatusPill,
  PriorityDot,
  EditableText as ExecEditableText,
  ViewSwitcher as ExecViewSwitcher,
  OwnerChip,
  PhaseCard as ExecPhaseCard,
  BoardView as ExecBoardView,
  TimelineView as ExecTimelineView,
} from './JaspenExecutionCanvas';
import BatchIdeaManager from './components/BatchIdeaManager';
import Onboarding from './components/Onboarding';
import SidebarIdentityFooter from './components/SidebarIdentityFooter';
import JaspenAiDrawer from './JaspenAiDrawer';
import ThreadEditModal from '../components/ThreadEditModal';
import { buildInviteDisplay, buildInviteLink } from '../../shared/inviteLink';
import { PLAN_ORDER, PLAN_RANK } from '../../shared/constants/appConstants';
import { formatSmartDate as fmtSmartDate, formatNextResetDate as fmtNextResetDate, formatTime as fmtTime } from '../../shared/utils/dateUtils';

// Styles - Single source of truth
import "./JaspenChat.css";

const IS_DEV = process.env.NODE_ENV !== 'production';
const devWarn = (...args) => {
  if (IS_DEV) console.warn(...args);
};
const BASELINE_INTERNAL_LABEL = 'Baseline';
const BASELINE_DISPLAY_LABEL = 'Original';

const isBaselineLikeLabel = (value) => {
  const normalized = String(value || '').trim().toLowerCase();
  return normalized === 'baseline' || normalized === 'original';
};

const formatScorecardLabel = (label, { isBaseline = false, fallback = 'Scorecard' } = {}) => {
  if (isBaseline || isBaselineLikeLabel(label)) return BASELINE_DISPLAY_LABEL;
  const cleaned = String(label || '').trim();
  return cleaned || fallback;
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

  // thread_ prefixed IDs are session storage keys — always prefer them directly
  // over analysis UUIDs which analysisHistory matching may otherwise surface first.
  const threadKey = candidates.find((id) => id.startsWith('thread_'));
  if (threadKey) return threadKey;

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
          label: BASELINE_INTERNAL_LABEL,
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
        label: BASELINE_INTERNAL_LABEL,
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
      label: baselineScorecard.label || BASELINE_INTERNAL_LABEL,
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
const ONBOARDING_INDUSTRY_LABELS = {
  technology: 'Technology',
  financial_services: 'Financial services',
  healthcare: 'Healthcare',
  retail_consumer: 'Retail / Consumer',
  manufacturing: 'Manufacturing',
  professional_services: 'Professional services',
  other: 'Other',
};
const ONBOARDING_COMPANY_SIZE_LABELS = {
  '1_10': '1-10 employees',
  '11_50': '11-50 employees',
  '51_500': '51-500 employees',
  '500_plus': '500+ employees',
};
const ONBOARDING_COMPANY_SIZE_TO_CONTEXT = {
  '1_10': 'startup',
  '11_50': 'smb',
  '51_500': 'mid-market',
  '500_plus': 'enterprise',
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

const formatSmartDate = fmtSmartDate;
const formatNextResetDate = fmtNextResetDate;

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
  { key: 'execution_readiness', label: 'Execution Confidence', aliases: ['execution_readiness', 'executionReadiness', 'readiness', 'team'] },
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

function toHistoryMessageShape(message = {}) {
  if (!message || typeof message !== 'object') return { role: 'assistant', content: '' };
  return {
    ...message,
    role: message?.role || (message?.sender === 'user' ? 'user' : 'assistant'),
    content: message?.content ?? message?.text ?? message?.message ?? '',
    artifact: message?.artifact && typeof message.artifact === 'object' ? message.artifact : undefined,
    timestamp: message?.timestamp || message?.created_at || undefined,
    mutations: Array.isArray(message?.mutations) ? message.mutations : undefined,
    undo: message?.undo && typeof message.undo === 'object' ? message.undo : undefined,
    feedback: message?.feedback && typeof message.feedback === 'object' ? message.feedback : undefined,
    regenerated: Boolean(message?.regenerated),
    alternatives: Array.isArray(message?.alternatives) ? message.alternatives : undefined,
    attachments: Array.isArray(message?.attachments) ? message.attachments : undefined,
  };
}

// When a thread is reloaded from the backend, persisted user messages still
// carry the FULL data-context prefix that was sent to the AI, e.g.:
//   "[Salesforce Context]\n<raw rows...>\n\n---\n\n<the user's actual message>"
// The live UI never shows that raw dump — it shows the user's text plus a small
// "[Data context attached: Salesforce]" marker. This normalizes a reloaded
// message back to that clean form so (1) the chat bubble doesn't show a wall of
// raw JSON, and (2) the top-bar "used sources" pill (which scans messages for
// the "[Data context attached: ...]" marker) keeps working after a refresh.
function normalizeUserContextText(rawText) {
  const raw = String(rawText || '');
  // Only touch messages that BEGIN with a raw "[<Label> Context]" block — these
  // are the reloaded/persisted ones. Live messages already use the clean marker.
  if (!/^\s*\[[^\]]+\sContext\]/.test(raw)) {
    return raw;
  }
  const SEP = '\n\n---\n\n';
  const sepIdx = raw.indexOf(SEP);
  if (sepIdx === -1) {
    // Unexpected shape — don't risk mangling the message.
    return raw;
  }
  const block = raw.slice(0, sepIdx);
  const userText = raw.slice(sepIdx + SEP.length).trim();
  const labels = [];
  const re = /\[([^\]]+?)\s+Context\]/g;
  let m;
  while ((m = re.exec(block)) !== null) {
    const label = String(m[1] || '').trim();
    if (label && !labels.includes(label)) labels.push(label);
  }
  const marker = labels.length ? `\n\n[Data context attached: ${labels.join(', ')}]` : '';
  return `${userText}${marker}`.trim();
}

function toUiMessages(history = []) {
  return (Array.isArray(history) ? history : [])
    .map((rawMsg, historyIndex) => {
      const msg = toHistoryMessageShape(rawMsg);
      const artifact = msg?.artifact && typeof msg.artifact === 'object' ? msg.artifact : null;
      const role = msg?.role === 'user' ? 'user' : 'ai';
      const rawText = String(msg?.content || msg?.text || '').trim();
      // Reloaded user messages carry the raw data-context dump — strip it back
      // to the clean "text + [Data context attached: X]" form. AI messages are
      // left untouched.
      const text = role === 'user' ? normalizeUserContextText(rawText) : rawText;
      return {
        id: msg?.id || null,
        role,
        text,
        artifact: artifact && typeof artifact.type === 'string' ? artifact : null,
        historyIndex,
        timestamp: msg?.timestamp || msg?.created_at || null,
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
      };
    })
    .filter((m) => (m.artifact || m.text.length > 0) && !isContextSyncMessage(m.text));
}

// Generic placeholders that are never acceptable as an idea title. We strip
// these so the derivation falls through to a real name from the conversation.
const _GENERIC_TITLE_NAMES = new Set([
  'baseline analysis', 'baseline', 'jaspen project', 'jaspen analysis',
  'strategy analysis', 'initiative', 'untitled', 'untitled idea',
  'untitled scorecard', 'project',
]);

function _isMeaningfulTitle(s) {
  const v = String(s || '').trim();
  if (!v) return false;
  if (_GENERIC_TITLE_NAMES.has(v.toLowerCase())) return false;
  return true;
}

function _capTitleSmart(value = '') {
  let cleaned = String(value || '').trim().replace(/\s+/g, ' ');
  cleaned = cleaned.replace(/^(we('re| are| run)\s+(an?\s+)?)|^(i('?m| am)\s+(building|launching|creating)\s+(an?\s+)?)|^(launch\s+(an?\s+)?)/i, '');
  if (!cleaned) return '';
  const words = cleaned.split(' ');
  if (words.length <= 7) return cleaned;
  const BREAK_WORDS = new Set(['for','to','that','which','and','or','with','in','on','at','by','from','via','using','through','across','into','of','about','between']);
  for (let i = Math.min(6, words.length - 1); i >= 3; i--) {
    const token = words[i].toLowerCase().replace(/[^a-z]/g, '');
    if (BREAK_WORDS.has(token)) return words.slice(0, i).join(' ');
  }
  return words.slice(0, 7).join(' ');
}

function deriveIdeaTitle({ result = null, messages = [], fallback = 'Untitled Idea' } = {}) {
  // Use the FIRST meaningful candidate — skip generic placeholders like
  // 'Baseline Analysis' that legacy scorecards still carry.
  const candidates = [
    result?.display_overrides?.title,
    result?.project_name,
    result?.name,
    result?.title,
    result?.compat?.title,
  ];
  for (const c of candidates) {
    if (_isMeaningfulTitle(c)) return _capTitleSmart(String(c).trim());
  }

  const firstUserIdea = (Array.isArray(messages) ? messages : [])
    .find((m) => m?.role === 'user' && String(m?.text || '').trim().length > 0);

  if (firstUserIdea?.text) {
    let raw = String(firstUserIdea.text).trim();
    // Strip common goal/intent prefixes so the title is the idea itself
    raw = raw.replace(/^(goal\s*[:–-]\s*|my goal\s+(is\s+)?[:–-]?\s*|i want to\s+|we want to\s+|we('re| are) (building|launching|creating)\s+|we('re| are| run)\s+(an?\s+)?|idea\s*[:–-]\s*)/i, '');
    // Take first sentence only
    const firstSentence = raw.split(/[.!?\n]/)[0].trim();
    const cleaned = firstSentence.length > 0 ? firstSentence : raw;
    // Cap at 7 words — find a natural break (before prepositions/conjunctions) rather than hard-cutting
    return _capTitleSmart(cleaned);
  }

  return _capTitleSmart(fallback);
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
  if (key === 'execution_readiness') return 'Execution Confidence';
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
    body: 'Run the Jaspen Score to validate viability across financial health, market position, and execution confidence.',
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

export default function JaspenChat() {
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

  // Don't auto-open settings when restoring a session (URL has ?sid=)
  const _isRestoringSession = Boolean(getRestorableSessionIdFromLocation());
  const [sidebarState, dispatchSidebar] = useReducer(sidebarReducer, {
    history: false,
    readiness: false,
    settings: !_isRestoringSession,
    userDismissedReadiness: false
  });
  const didAutoOpenSettingsRef = useRef(false);
  const copyResetTimeoutRef = useRef(null);

  useEffect(() => {
    if (didAutoOpenSettingsRef.current) return;
    didAutoOpenSettingsRef.current = true;
    // Only auto-open settings on fresh workspace (no session being restored)
    if (!getRestorableSessionIdFromLocation()) {
      dispatchSidebar({ type: 'OPEN_SETTINGS' });
    }
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

  const [collectedData, setCollectedData] = useState({});
  // AI-driven knowledge signals: { signals: [...], confidence: 0-100 }
  const [knowledgeSignals, setKnowledgeSignals] = useState(null);

  const [input, setInput] = useState('');
  const [pendingFiles, setPendingFiles] = useState([]);
  // Files the USER has shared this session (distinct from artifacts the agent
  // creates). Drives the "Session Uploads" list in the artifacts dropdown so
  // users can track what they shared vs. what Jaspen produced.
  const [sessionUploads, setSessionUploads] = useState([]);
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
  // AbortController for in-flight streams — Stop button calls .abort() on this.
  const streamAbortRef = useRef(null);
  const stopActiveStream = useCallback(() => {
    try {
      streamAbortRef.current?.abort();
    } catch (_) { /* no-op */ }
    streamAbortRef.current = null;
    setBusy(false);
    setIsStreamingReply(false);
    setStreamToolStatus('');
  }, []);
  const [copiedMessageKey, setCopiedMessageKey] = useState(null);
  const [feedbackBusyKey, setFeedbackBusyKey] = useState(null);
  const [isRecording, setIsRecording] = useState(false);
  const [error, setError] = useState(null);
  const recognitionRef = useRef(null);
  const historySearchInputRef = useRef(null);

  const [analysisResult, setAnalysisResult] = useState(null);
  const [scorecardGenerating, setScorecardGenerating] = useState(false);
  const [autoVersionGenerating, setAutoVersionGenerating] = useState(false);
  // The Trade-off tab is gated behind explicit user intent. It unlocks only
  // when the user asks to compare/rank ideas (or kicks off the session with a
  // batch ranking request). Just having multiple scorecards is not enough.
  const [tradeoffRequested, setTradeoffRequested] = useState(false);
  // Artifact lightbox: when the user clicks a scorecard in the Session
  // Artifacts dropdown, we show it in a dark-backdrop modal.
  const [lightboxScorecard, setLightboxScorecard] = useState(null);
  // View mode for the inline Execution view in the chat tab (list/board/timeline)
  const [inlineExecView, setInlineExecView] = useState('list');
  // Jaspen Insights panel collapsed state — persists to localStorage so the
  // user's preference survives reloads. Auto-suggested-but-not-forced collapse
  // when the user opens execution / trade-off (those views need width).
  const [insightsCollapsed, setInsightsCollapsed] = useState(() => {
    try { return localStorage.getItem('jaspen.insightsCollapsed') === '1'; } catch (_) { return false; }
  });
  const toggleInsightsCollapsed = () => {
    setInsightsCollapsed((v) => {
      const next = !v;
      try { localStorage.setItem('jaspen.insightsCollapsed', next ? '1' : '0'); } catch (_) {}
      return next;
    });
  };
  // Close lightbox on Esc
  useEffect(() => {
    if (!lightboxScorecard) return;
    const onKey = (e) => { if (e.key === 'Escape') setLightboxScorecard(null); };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [lightboxScorecard]);
  // Tracks which stage pill's content the sidebar is showing
  const [activePill, setActivePill] = useState('discovery');
  const [artifactsOpen, setArtifactsOpen] = useState(false);
  const [uploadsOpen, setUploadsOpen] = useState(false);
  // Scenario results kept at the Workspace level (so Score tab can switch)
const [resultA, setResultA] = useState(null);
const [resultB, setResultB] = useState(null);
const [resultC, setResultC] = useState(null);
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

// Variant selector (Baseline, Scenario A/B/C)
const [scoreVariants, setScoreVariants] = useState([]);
const [selectedVariantId, setSelectedVariantId] = useState('baseline');
// Keep the list of selectable score variants in sync
useEffect(() => {
  const opts = [
    analysisResult ? { id: 'baseline',  label: BASELINE_INTERNAL_LABEL,   result: analysisResult } : null,
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
// Tracks which scorecard's "Build Execution Plan" CTA is in flight (so the
// matching button on that specific card can show "Building plan…").
const [buildingExecutionPlanFor, setBuildingExecutionPlanFor] = useState(null);
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
          label: BASELINE_INTERNAL_LABEL,
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
  // Prevent duplicate auto-scoring triggers per session
  const autoScoringTriggeredRef = useRef(false);

  // Pull messages, latest analysis id, and saved scenarios from backend
const refreshBundle = async (tid, { fallbackTid } = {}) => {
  if (!tid) return;
  setBundleLoading(true);
  try {
    let bundle = await Jaspen.getThreadBundle(tid, { msg_limit: 50, scn_limit: 50 });
    // If this session has no baseline (e.g. orphan session from a hard-reload), try
    // the fallback thread — the actual analysis data lives on the original thread.
    if (!bundle?.baseline_scorecard && fallbackTid && fallbackTid !== tid) {
      try {
        const fallback = await Jaspen.getThreadBundle(fallbackTid, { msg_limit: 50, scn_limit: 50 });
        if (fallback?.baseline_scorecard) {
          bundle = fallback;
        }
      } catch { /* fallback failed silently */ }
    }

    // scenarios -> normalize to local shape used by list display
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
      // Merge: keep any local-only snapshots the backend hasn't persisted yet
      // (e.g. a version just scored via triggerAutoVersion before the round-trip completes)
      setScorecardSnapshots((prev) => {
        const bundleIds = new Set(bundleSnapshots.map((s) => String(s?.id || s?.analysis_id || '')).filter(Boolean));
        const localOnly = (Array.isArray(prev) ? prev : []).filter(
          (s) => s?.id && !bundleIds.has(String(s.id))
        );
        return localOnly.length > 0 ? [...bundleSnapshots, ...localOnly] : bundleSnapshots;
      });
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
      // Prevent auto-score re-trigger — result exists from bundle
      autoScoringTriggeredRef.current = true;
      if (view === 'intake') {
        setView('intake');
        setActiveTab('summary');
      }
    }

    const bundleMessages = toUiMessages(
      (Array.isArray(bundle?.messages) ? bundle.messages : []).map((m) => toHistoryMessageShape(m))
    );
    // Use functional form so we read actual current state, not stale closure value.
    // Prefer bundle when it carries explicit artifacts and current state does not.
    if (bundleMessages.length > 0) {
      setMessages(prev => {
        const prevHasArtifacts = prev.some((entry) => Boolean(entry?.artifact));
        const bundleHasArtifacts = bundleMessages.some((entry) => Boolean(entry?.artifact));
        if (prev.length === 0) return bundleMessages;
        if (!prevHasArtifacts && bundleHasArtifacts) return bundleMessages;
        if (prevHasArtifacts && bundleHasArtifacts) {
          const prevArtifactCount = prev.filter((entry) => Boolean(entry?.artifact)).length;
          const bundleArtifactCount = bundleMessages.filter((entry) => Boolean(entry?.artifact)).length;
          if (bundleArtifactCount > prevArtifactCount) return bundleMessages;
        }
        // Keep existing state otherwise (for in-flight local optimistic cards).
        if (prev.length > 0) return prev;
        return bundleMessages;
      });
    }
    // Re-derive trade-off unlock from history: if the user ever asked to
    // compare/rank in this thread, the Trade-off tab stays unlocked on reload.
    // Regex inlined to avoid TDZ on the hoisted helper above.
    const _tradeoffRe = /\b(trade[-\s]?off|compare\s+(these|them|the\s+(ideas?|scorecards?|options?|scenarios?|versions?))|rank\s+(these|them|the\s+(ideas?|scorecards?|options?|scenarios?|versions?))|stack[-\s]?rank|side[-\s]?by[-\s]?side|head[-\s]?to[-\s]?head|which\s+(one\s+)?(is\s+)?(best|better|should\s+(i|we))|impact\s+(vs|versus|and)\s+effort|effort\s+(vs|versus|and)\s+impact)\b/i;
    if (bundleMessages.some((m) => m.role === 'user' && _tradeoffRe.test(m.text || ''))) {
      setTradeoffRequested(true);
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


// ── Inline Execution View ─────────────────────────────────────────────────────
const renderInlineExecutionView = () => {
  const tasks = Array.isArray(threadWbs?.tasks) ? threadWbs.tasks : [];
  if (tasks.length === 0) {
    // Empty state — surface all scored ideas with a "Build plan from this
    // scorecard" CTA so the user has an obvious next step from this tab
    // (rather than a dead end).
    const ideaCards = Array.isArray(scorecardSnapshots) && scorecardSnapshots.length > 0
      ? scorecardSnapshots
      : (analysisResult ? [analysisResult] : []);
    return (
      <div className="jas-execution-inline-empty" style={{ padding: '32px 28px', maxWidth: 720 }}>
        <p className="jas-execution-inline-empty-title">Pick an idea to turn into a project</p>
        <p className="jas-execution-inline-empty-sub" style={{ marginBottom: 18 }}>
          Build an AI-authored execution plan from any of your scored ideas. The plan unlocks the Execution tab and can be edited directly in Workspace.
        </p>
        {ideaCards.length === 0 ? (
          <p style={{ fontSize: 13, color: '#94a3b8', fontStyle: 'italic' }}>
            Score an idea first — then come back here.
          </p>
        ) : (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
            {ideaCards.map((card, idx) => {
              const cid = card?.id || card?.analysis_id || `card-${idx}`;
              const name = (
                (card?.display_overrides?.title && _isMeaningfulTitle(card.display_overrides.title)) ? card.display_overrides.title :
                _isMeaningfulTitle(card?.name) ? card.name :
                _isMeaningfulTitle(card?.project_name) ? card.project_name :
                deriveIdeaTitle({ result: card, messages, fallback: `Idea ${idx + 1}` })
              );
              const score = Number(card?.jaspen_score || 0);
              const isBuilding = buildingExecutionPlanFor && String(buildingExecutionPlanFor) === String(cid);
              return (
                <div
                  key={cid}
                  style={{
                    display: 'flex', alignItems: 'center', gap: 14,
                    padding: '12px 16px',
                    background: '#fff',
                    border: '1px solid #e6eaf2',
                    borderRadius: 10,
                  }}
                >
                  <div style={{ flex: 1, minWidth: 0 }}>
                    <div style={{ fontSize: 14, fontWeight: 600, color: '#0f172a', whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>
                      {name}
                    </div>
                    <div style={{ fontSize: 11.5, color: '#64748b', marginTop: 2, fontFamily: 'JetBrains Mono, monospace' }}>
                      Score {score} · {score >= 80 ? 'Excellent' : score >= 60 ? 'Good' : score >= 40 ? 'Fair' : 'At Risk'}
                    </div>
                  </div>
                  <button
                    type="button"
                    onClick={() => void handleGenerateAiWbsFromScorecard({ threadBundleId: sessionId || currentSessionId, scorecardId: cid })}
                    disabled={Boolean(buildingExecutionPlanFor)}
                    style={{
                      padding: '7px 13px',
                      background: '#a0036c',
                      color: '#fff',
                      border: 'none',
                      borderRadius: 7,
                      fontSize: 12.5,
                      fontWeight: 500,
                      cursor: buildingExecutionPlanFor ? 'wait' : 'pointer',
                      opacity: buildingExecutionPlanFor && !isBuilding ? 0.55 : 1,
                      whiteSpace: 'nowrap',
                    }}
                  >
                    {isBuilding ? '⏳ Building…' : 'Build Plan →'}
                  </button>
                </div>
              );
            })}
          </div>
        )}
      </div>
    );
  }
  // ── Populated execution plan view ──────────────────────────────────────
  // Group tasks by phase (preserving order of first appearance), then render
  // PhaseCards from JaspenExecutionCanvas so the chat tab and Workspace
  // surfaces share the same visual atoms.
  const phaseOrder = [];
  const tasksByPhase = new Map();
  tasks.forEach((t) => {
    const name = String(t?.phase || 'Execution').trim() || 'Execution';
    if (!tasksByPhase.has(name)) { phaseOrder.push(name); tasksByPhase.set(name, []); }
    tasksByPhase.get(name).push(t);
  });
  const phases = phaseOrder.map((name, idx) => ({
    num: idx + 1,
    title: name,
    weeks: null,
    tasks: tasksByPhase.get(name),
  }));

  // Owners summary
  const ownersMap = new Map();
  tasks.forEach((t) => {
    const n = String(t?.owner || t?.suggested_role || '').trim();
    if (!n) return;
    ownersMap.set(n, (ownersMap.get(n) || 0) + 1);
  });
  const owners = Array.from(ownersMap.entries()).map(([name, count]) => ({ name, count }));

  // Inline edit handler: write to threadWbs then PATCH the whole WBS in a
  // background save. Mirrors the auto-save pattern in JaspenExecutionCanvas.
  const handleTaskUpdate = (taskId, patch) => {
    setThreadWbs((prev) => {
      const next = { ...(prev || {}) };
      const arr = Array.isArray(prev?.tasks) ? [...prev.tasks] : [];
      const idx = arr.findIndex((t) => String(t?.id || '') === String(taskId));
      if (idx < 0) return prev;
      arr[idx] = { ...arr[idx], ...patch };
      next.tasks = arr;
      const sid = sessionId || currentSessionId;
      const attemptSave = () => Jaspen.upsertThreadWbs(sid, next).catch((e) => {
        console.error('[exec-inline] save failed:', e);
        showToast('Couldn\'t save that change — try again.', 'error', {
          actionLabel: 'Retry',
          onAction: attemptSave,
        });
      });
      attemptSave();
      return next;
    });
  };
  const handleReorderTask = ({ sourceId, targetId, position, targetPhase }) => {
    setThreadWbs((prev) => {
      const tasks = Array.isArray(prev?.tasks) ? [...prev.tasks] : [];
      const srcIdx = tasks.findIndex((t) => String(t?.id || '') === String(sourceId));
      if (srcIdx < 0) return prev;
      const [moved] = tasks.splice(srcIdx, 1);
      const newPhase = targetPhase || moved.phase || 'Execution';
      moved.phase = newPhase;

      let insertAt = tasks.length;
      if (targetId) {
        const tgtIdx = tasks.findIndex((t) => String(t?.id || '') === String(targetId));
        if (tgtIdx >= 0) insertAt = position === 'before' ? tgtIdx : tgtIdx + 1;
      } else if (position === 'end-of-phase') {
        let lastIdxOfPhase = -1;
        tasks.forEach((t, i) => {
          if (String(t?.phase || '').trim() === newPhase) lastIdxOfPhase = i;
        });
        insertAt = lastIdxOfPhase >= 0 ? lastIdxOfPhase + 1 : tasks.length;
      }
      tasks.splice(insertAt, 0, moved);
      const next = { ...(prev || {}), tasks };
      const sid = sessionId || currentSessionId;
      const attemptReorderSave = () => Jaspen.upsertThreadWbs(sid, next).catch((e) => {
        console.error('[exec-inline] reorder save failed:', e);
        showToast('Couldn\'t save the new order — try again.', 'error', {
          actionLabel: 'Retry',
          onAction: attemptReorderSave,
        });
      });
      attemptReorderSave();
      return next;
    });
  };

  const handleAddTask = (phaseName) => {
    setThreadWbs((prev) => {
      const next = { ...(prev || {}) };
      const arr = Array.isArray(prev?.tasks) ? [...prev.tasks] : [];
      arr.push({
        id: `task_local_${Math.random().toString(36).slice(2, 12)}`,
        title: '',
        description: '',
        priority: 'medium',
        estimated_days: 3,
        timeline_days: 3,
        owner: '',
        suggested_role: '',
        phase: phaseName || 'Execution',
        status: 'todo',
        depends_on: [],
      });
      next.tasks = arr;
      const sid = sessionId || currentSessionId;
      const attemptAddSave = () => Jaspen.upsertThreadWbs(sid, next).catch((e) => {
        console.error('[exec-inline] add save failed:', e);
        showToast('Couldn\'t add the task — try again.', 'error', {
          actionLabel: 'Retry',
          onAction: attemptAddSave,
        });
      });
      attemptAddSave();
      return next;
    });
  };

  const wsHref = (sessionId || currentSessionId)
    ? `/workspace/${encodeURIComponent(sessionId || currentSessionId)}/__execution__`
    : null;

  // Idea name + score from the baseline / adopted scorecard so the header
  // reads like the design (project name + SCORE pill, not generic).
  const _BANNED_NAMES = new Set([
    'baseline analysis', 'baseline', 'jaspen project', 'jaspen analysis',
    'strategy analysis', 'initiative', 'untitled', 'untitled idea', 'project',
  ]);
  const _pickIdeaName = (s) => {
    const v = String(s || '').trim();
    if (!v) return null;
    if (_BANNED_NAMES.has(v.toLowerCase())) return null;
    return v;
  };
  const _scorecardForHeader = activeScorecard || analysisResult;
  const ideaName = (
    _pickIdeaName(_scorecardForHeader?.display_overrides?.title)
      || _pickIdeaName(_scorecardForHeader?.name)
      || _pickIdeaName(_scorecardForHeader?.project_name)
      || _pickIdeaName(_scorecardForHeader?.initiative_name)
      || deriveIdeaTitle({ result: _scorecardForHeader, messages, fallback: '' })
      || 'Execution plan'
  );
  const ideaScore = Number(_scorecardForHeader?.jaspen_score || 0) || null;
  const scoreCategory = ideaScore
    ? (ideaScore >= 80 ? 'Excellent' : ideaScore >= 60 ? 'Good' : ideaScore >= 40 ? 'Fair' : 'At Risk')
    : null;

  // Priority counts (replaces owners strip per design feedback)
  const priorityCounts = { critical: 0, high: 0, medium: 0, low: 0 };
  tasks.forEach((t) => {
    const p = String(t?.priority || 'medium').toLowerCase();
    if (priorityCounts[p] !== undefined) priorityCounts[p] += 1;
  });
  const PRIO_META = {
    critical: { dot: '#dc2626', label: 'Critical' },
    high:     { dot: '#f59e0b', label: 'High'     },
    medium:   { dot: '#8a93ad', label: 'Medium'   },
    low:      { dot: '#cbd5e1', label: 'Low'      },
  };

  // "Updated X min ago" — uses the WBS updated_at OR the most recent task
  // updated_at. Fallback: the plan's created_at.
  const _ts = (() => {
    let t = Date.parse(String(threadWbs?.updated_at || ''));
    tasks.forEach((task) => {
      const tt = Date.parse(String(task?.updated_at || ''));
      if (Number.isFinite(tt) && (!Number.isFinite(t) || tt > t)) t = tt;
    });
    if (!Number.isFinite(t)) t = Date.parse(String(threadWbs?.created_at || ''));
    return Number.isFinite(t) ? t : null;
  })();
  let lastUpdatedLabel = null;
  if (_ts) {
    const diffMin = Math.max(0, Math.round((Date.now() - _ts) / 60000));
    if (diffMin < 1) lastUpdatedLabel = 'Updated just now';
    else if (diffMin === 1) lastUpdatedLabel = 'Updated 1 min ago';
    else if (diffMin < 60) lastUpdatedLabel = `Updated ${diffMin} min ago`;
    else {
      const hrs = Math.round(diffMin / 60);
      if (hrs === 1) lastUpdatedLabel = 'Updated 1 hr ago';
      else if (hrs < 24) lastUpdatedLabel = `Updated ${hrs} hrs ago`;
      else {
        const days = Math.round(hrs / 24);
        lastUpdatedLabel = `Updated ${days} day${days === 1 ? '' : 's'} ago`;
      }
    }
  }

  return (
    <div style={{
      flex: 1, display: 'flex', flexDirection: 'column',
      background: EXEC_COLOR.bg, minWidth: 0, overflow: 'hidden',
      fontFamily: "'Inter Tight', system-ui, sans-serif",
    }}>
      {/* Canvas header */}
      <div style={{ padding: '22px 22px 14px', flex: '0 0 auto' }}>
        <div style={{ display: 'flex', alignItems: 'flex-start', gap: 14 }}>
          <div style={{ minWidth: 0, flex: 1 }}>
            <Eyebrow color={EXEC_COLOR.rose}>✦ &nbsp;Idea · Trade-off winner</Eyebrow>
            <div style={{ fontSize: 22, fontWeight: 600, color: EXEC_COLOR.navy, letterSpacing: '-0.015em', marginTop: 6, lineHeight: 1.2 }}>
              {ideaName}
            </div>
            <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginTop: 8, flexWrap: 'wrap' }}>
              {ideaScore && (
                <>
                  <span style={{
                    fontFamily: 'JetBrains Mono, monospace',
                    fontSize: 11.5, color: EXEC_COLOR.navy, padding: '3px 9px',
                    background: EXEC_COLOR.roseTint, border: `1px solid ${EXEC_COLOR.roseLine}`,
                    borderRadius: 999, fontWeight: 600,
                  }}>SCORE {ideaScore}</span>
                  {scoreCategory && (
                    <span style={{
                      fontFamily: 'JetBrains Mono, monospace',
                      fontSize: 10.5, color: EXEC_COLOR.greenInk, padding: '3px 8px',
                      background: EXEC_COLOR.greenTint, borderRadius: 4,
                      letterSpacing: '0.08em', fontWeight: 600, textTransform: 'uppercase',
                    }}>{scoreCategory}</span>
                  )}
                </>
              )}
              <span style={{ fontSize: 13, color: EXEC_COLOR.ink }}>
                {phases.length} phase{phases.length === 1 ? '' : 's'} · {tasks.length} task{tasks.length === 1 ? '' : 's'}
              </span>
            </div>
          </div>
          <ExecViewSwitcher value={inlineExecView} onChange={setInlineExecView} />
          <div style={{ display: 'flex', gap: 6, alignItems: 'center' }}>
            {wsHref && (
              <a
                href={wsHref}
                target="_blank"
                rel="noopener noreferrer"
                style={{
                  padding: '6px 12px', borderRadius: 8,
                  background: EXEC_COLOR.navy, color: '#fff',
                  textDecoration: 'none', fontSize: 12.5, fontWeight: 500,
                  whiteSpace: 'nowrap',
                }}
              >Open in Workspace ↗</a>
            )}
          </div>
        </div>

        {/* Priority chips strip (replaces owners) */}
        {tasks.length > 0 && (
          <div style={{
            marginTop: 14, display: 'flex', alignItems: 'center', gap: 10,
            padding: '8px 12px', flexWrap: 'wrap',
            background: '#fff', border: `1px solid ${EXEC_COLOR.line}`, borderRadius: 10,
          }}>
            <Eyebrow>Priority</Eyebrow>
            {['critical', 'high', 'medium', 'low'].map((p) => {
              const c = priorityCounts[p];
              if (c === 0) return null;
              const meta = PRIO_META[p];
              return (
                <div
                  key={p}
                  style={{
                    display: 'inline-flex', alignItems: 'center', gap: 7,
                    padding: '4px 11px', borderRadius: 999,
                    background: EXEC_COLOR.line2, border: `1px solid ${EXEC_COLOR.line}`,
                  }}
                >
                  <span style={{ width: 7, height: 7, borderRadius: 4, background: meta.dot }} />
                  <span style={{ fontSize: 12, color: EXEC_COLOR.navy2, fontWeight: 500 }}>{meta.label}</span>
                  <span style={{ fontFamily: 'JetBrains Mono, monospace', fontSize: 10.5, color: EXEC_COLOR.mute }}>· {c}</span>
                </div>
              );
            })}
            <div style={{ flex: 1 }} />
            {lastUpdatedLabel && (
              <span style={{ fontFamily: 'JetBrains Mono, monospace', fontSize: 10.5, color: EXEC_COLOR.mute }}>
                {lastUpdatedLabel}
              </span>
            )}
          </div>
        )}
      </div>

      {/* View body — list / board / timeline */}
      {inlineExecView === 'list' && (
        <div style={{ flex: 1, overflow: 'auto', padding: '0 22px 22px' }}>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
            {phases.map((p) => (
              <ExecPhaseCard
                key={p.title}
                phase={p}
                tasks={p.tasks}
                onUpdateTask={handleTaskUpdate}
                onAddTask={handleAddTask}
                onReorder={handleReorderTask}
              />
            ))}
          </div>
        </div>
      )}
      {inlineExecView === 'board' && (
        <div style={{ flex: 1, overflow: 'auto' }}>
          <ExecBoardView
            wbs={threadWbs}
            onColumnDrop={(sourceId, newStatus) => handleTaskUpdate(sourceId, { status: newStatus })}
          />
        </div>
      )}
      {inlineExecView === 'timeline' && (
        <div style={{ flex: 1, overflow: 'auto' }}>
          <ExecTimelineView wbs={threadWbs} phases={phases} />
        </div>
      )}
    </div>
  );
};

const renderScorecardCard = (result, opts = {}) => {
  const score = Number(result?.jaspen_score || 0);
  const category = score >= 80 ? 'Excellent' : score >= 60 ? 'Good' : score >= 40 ? 'Fair' : 'At Risk';
  const ringColor = '#a0036c';
  const circumference = 2 * Math.PI * 36;
  const offset = circumference - (score / 100) * circumference;
  const dims = result?.dimensions || {};

  const primaryDims = [
    { key: 'strategic_alignment', label: 'Strategic fit',   isRisk: false },
    { key: 'financial_viability', label: 'Cost efficiency', isRisk: false },
    { key: 'execution_readiness', label: 'Time-to-value',   isRisk: false },
    { key: 'risk_profile',        label: 'Execution risk',  isRisk: true  },
  ];
  const secondaryDims = [
    { key: 'market_opportunity', label: 'Market Opportunity' },
    { key: 'evidence_quality',   label: 'Evidence Quality'   },
  ];

  const risks = result?.top_risks || [];
  const recs = result?.recommendations || [];
  const nextSteps = result?.next_steps || [];
  const recommendedScenario = (recs[0] && typeof recs[0] === 'string') ? recs[0]
    : (recs[0]?.text || recs[0]?.action || null)
    || (nextSteps[0] && typeof nextSteps[0] === 'string' ? nextSteps[0] : null);
  // Title: prefer Workspace override → meaningful scorecard fields → derived
  // from conversation. Generic placeholders like "Baseline Analysis" are
  // filtered out so legacy cards still get a sensible display name.
  const title = (
    _isMeaningfulTitle(result?.display_overrides?.title) ? result.display_overrides.title :
    _isMeaningfulTitle(result?.name) ? result.name :
    _isMeaningfulTitle(result?.project_name) ? result.project_name :
    _isMeaningfulTitle(result?.title) ? result.title :
    deriveIdeaTitle({ result, messages: opts.messages || [], fallback: 'Untitled idea' })
  );

  // Relative timestamp
  const createdAt = result?._createdAt;
  const timeAgo = createdAt
    ? (() => { const m = Math.round((Date.now() - createdAt) / 60000); return m < 2 ? 'just now' : `${m} min ago`; })()
    : null;

  const renderDimBar = ({ key, label, isRisk }) => {
    const dim = dims[key] || {};
    const raw = Number(dim.score || result?.component_scores?.[key] || 0);
    const pct = Math.min(raw, 100);
    const tenths = (pct / 10).toFixed(1);
    const flagged = pct < 55;
    const barColor = (isRisk && pct < 65) ? '#f59e0b' : flagged ? '#f59e0b' : 'var(--navy)';
    const conf = String(dim.confidence || 'medium').toLowerCase();
    const isAssumed = conf === 'assumed' || conf === 'low';
    return (
      <div key={key} className="jas-dim-col" title={dim.rationale || ''}>
        <div className="jas-dim-col-header">
          <span className="jas-dim-label">{label}</span>
          <span className={`jas-dim-score-tenths${flagged ? ' flagged' : ''}`}>{tenths}<span className="jas-dim-denom">/10</span></span>
        </div>
        <div className="jas-dim-bar-track">
          <div className="jas-dim-bar-fill" style={{ width: `${pct}%`, background: barColor }}/>
        </div>
        {isAssumed && <span className="jas-dim-conf-badge" title={dim.what_would_improve || ''}>{conf}</span>}
      </div>
    );
  };

  return (
    <div className="jas-scorecard-card">
      {/* Eyebrow + timestamp */}
      <div style={{ display: 'flex', alignItems: 'center', marginBottom: 14 }}>
        <span className="jas-scorecard-eyebrow">Scorecard</span>
        {timeAgo && <span className="jas-scorecard-timestamp">v1 · {timeAgo}</span>}
      </div>

      {/* Header: ring + title */}
      <div className="jas-scorecard-header">
        <svg className="jas-score-ring" viewBox="0 0 88 88" width="80" height="80">
          <circle cx="44" cy="44" r="36" fill="none" stroke="#e5e7eb" strokeWidth="7"/>
          <circle cx="44" cy="44" r="36" fill="none" stroke={ringColor} strokeWidth="7"
            strokeDasharray={`${circumference}`}
            strokeDashoffset={offset}
            strokeLinecap="round"
            transform="rotate(-90 44 44)"/>
          <text x="44" y="49" textAnchor="middle" fontSize="22" fontWeight="700" fill="var(--navy)">{score}</text>
        </svg>
        <div className="jas-scorecard-meta">
          <span className="jas-scorecard-category" style={{ color: ringColor }}>{category}</span>
          <span className="jas-scorecard-title">{title}</span>
        </div>
      </div>

      {/* Primary 2×2 dimension grid */}
      <div className="jas-scorecard-dims-grid">
        {primaryDims.map(d => renderDimBar(d))}
      </div>

      {/* Secondary dims if populated */}
      {secondaryDims.some(({ key }) => (dims[key]?.score || result?.component_scores?.[key] || 0) > 0) && (
        <div className="jas-scorecard-dims-secondary">
          {secondaryDims.map(d => renderDimBar({ ...d, isRisk: false }))}
        </div>
      )}

      {/* Two-col bottom: Top Risks | Recommended */}
      {(risks.length > 0 || recommendedScenario) && (
        <div className="jas-scorecard-bottom-cols">
          {risks.length > 0 && (
            <div>
              <p className="jas-scorecard-bottom-col-label">Top Risks</p>
              {risks.slice(0, 3).map((r, i) => (
                <p key={i} className="jas-scorecard-risk-item">
                  · {typeof r === 'string' ? r : (r.risk || r.text || String(r))}
                </p>
              ))}
            </div>
          )}
          {recommendedScenario && (
            <div>
              <p className="jas-scorecard-bottom-col-label">Recommended Scenario</p>
              <p className="jas-scorecard-rec-text">+ {recommendedScenario}</p>
            </div>
          )}
        </div>
      )}

      {/* Footer: action buttons */}
      <div className="jas-scorecard-footer">
        <div className="jas-scorecard-footer-actions">
          <button className="jas-scorecard-action-ghost" title="Download scorecard">
            ↓ Download
          </button>
          <button className="jas-scorecard-action-ghost" title="Share scorecard">
            Share
          </button>
          {opts.onOpenWorkspaceScorecard && (
            <button
              className="jas-scorecard-action-ghost"
              type="button"
              onClick={() => { void opts.onOpenWorkspaceScorecard(result); }}
              title="Edit in Workspace (opens in new tab) — Beta"
            >
              Edit in Workspace ↗
            </button>
          )}
          {/* Build Execution Plan — primary CTA on the scorecard. Generates
              an AI-authored WBS for this specific idea and unlocks the
              Execution tab. */}
          {opts.onBuildExecutionPlan && (() => {
            const cid = result?.id || result?.analysis_id;
            const isBuilding = opts.buildingExecutionPlanFor && String(opts.buildingExecutionPlanFor) === String(cid);
            return (
              <button
                className="jas-scorecard-action-primary"
                onClick={() => opts.onBuildExecutionPlan(cid)}
                disabled={isBuilding || opts.buildingExecutionPlanFor}
                title="Generate an AI-authored execution plan from this scorecard"
                style={{
                  padding: '6px 12px',
                  background: '#a0036c',
                  color: '#fff',
                  border: 'none',
                  borderRadius: 6,
                  fontSize: 12,
                  fontWeight: 500,
                  cursor: isBuilding ? 'wait' : 'pointer',
                  opacity: opts.buildingExecutionPlanFor && !isBuilding ? 0.55 : 1,
                  whiteSpace: 'nowrap',
                }}
              >
                {isBuilding ? '⏳ Building plan…' : 'Build Execution Plan →'}
              </button>
            );
          })()}
          {opts.onNewVersion && (
            <button
              className="jas-scorecard-action-ghost jas-scorecard-action-new-version"
              title="Score a new version based on your updated context"
              onClick={opts.onNewVersion}
              disabled={opts.autoVersionGenerating}
              style={{ marginLeft: 'auto', opacity: opts.autoVersionGenerating ? 0.6 : 1 }}
            >
              {opts.autoVersionGenerating ? '⏳ Creating…' : '+ New Version'}
            </button>
          )}
        </div>
        <span className="jas-scorecard-view-hint">Ask Jaspen about any dimension →</span>

        {/* Parked-from-trade-off pill. Visible only when the user has
            explicitly excluded this scorecard from the Trade-off view
            (tradeoff_included = false). Clicking it re-includes via the
            same /overrides PATCH endpoint the Trade-off row toggle uses. */}
        {result?.display_overrides?.tradeoff_included === false && opts.threadId && (
          <div style={{
            marginTop: 10,
            display: 'inline-flex', alignItems: 'center', gap: 8,
            padding: '6px 10px',
            background: 'rgba(160,3,108,0.06)',
            border: '1px solid rgba(160,3,108,0.18)',
            borderRadius: 999,
            fontSize: 11.5, color: '#a0036c', fontWeight: 500,
          }}>
            <span>Parked from trade-off</span>
            <button
              type="button"
              onClick={async () => {
                const cid = String(result?.id || result?.analysis_id || '');
                if (!cid) return;
                try {
                  await Jaspen.patchScorecardOverrides(opts.threadId, cid, { tradeoff_included: true });
                  if (typeof opts.onTradeoffIncludeChanged === 'function') {
                    opts.onTradeoffIncludeChanged(cid, true);
                  }
                } catch (e) {
                  console.error('[scorecard] re-include failed', e);
                }
              }}
              style={{
                appearance: 'none', border: 'none', background: 'transparent',
                color: '#a0036c', fontWeight: 600, cursor: 'pointer',
                padding: 0, textDecoration: 'underline', fontSize: 11.5,
              }}
            >Include</button>
          </div>
        )}
      </div>
    </div>
  );
};

// ── Inline Trade-off artifact ─────────────────────────────────────────────────
// Compact summary card for the chat thread. Shows top 3 ranked ideas + a
// session-avg figure. Full table + quadrant lives in Workspace.
const renderInlineTradeoffArtifact = (data, opts = {}) => {
  const snaps = Array.isArray(data?.snapshots) ? data.snapshots : [];
  if (snaps.length === 0) return null;
  // Only count snapshots where tradeoff_included !== false
  const included = snaps.filter((s) => s?.display_overrides?.tradeoff_included !== false);
  const ranked = [...included].sort(
    (a, b) => Number(b?.jaspen_score ?? b?.score ?? 0) - Number(a?.jaspen_score ?? a?.score ?? 0)
  );
  const top3 = ranked.slice(0, 3);
  const total = included.length;
  const avg = total ? (ranked.reduce((s, x) => s + Number(x?.jaspen_score ?? x?.score ?? 0), 0) / total).toFixed(1) : '0';
  const wsHref = opts.threadId ? `/workspace/${encodeURIComponent(opts.threadId)}/__tradeoff__` : null;
  return (
    <div style={{
      background: '#fff', border: '1px solid #e9ecef', borderRadius: 14,
      padding: '18px 20px 16px', maxWidth: 720,
      fontFamily: "'Inter Tight', system-ui, sans-serif",
    }}>
      <div style={{ display: 'flex', alignItems: 'baseline', justifyContent: 'space-between', marginBottom: 12 }}>
        <div>
          <div style={{ fontFamily: 'JetBrains Mono, monospace', fontSize: 10.5, color: '#a0036c', letterSpacing: '0.08em', textTransform: 'uppercase', fontWeight: 600 }}>
            Trade-off · {total} idea{total === 1 ? '' : 's'} compared
          </div>
          <div style={{ fontSize: 13, color: '#5a6585', marginTop: 4 }}>
            Session avg: <strong style={{ color: '#161f3b' }}>{avg}</strong>
          </div>
        </div>
        {wsHref && (
          <button
            type="button"
            onClick={() => {
              if (opts.onOpenWorkspaceRoute) {
                void opts.onOpenWorkspaceRoute(opts.threadId, '__tradeoff__');
              } else {
                window.open(wsHref, '_blank', 'noopener,noreferrer');
              }
            }}
            style={{
              padding: '6px 12px', borderRadius: 8,
              background: '#0f172a', color: '#fff',
              border: 'none', fontSize: 12.5, fontWeight: 500, whiteSpace: 'nowrap', cursor: 'pointer',
            }}
          >Open in Workspace ↗</button>
        )}
      </div>
      <div style={{ display: 'flex', flexDirection: 'column' }}>
        {top3.map((s, i) => {
          const score = Math.round(Number(s?.jaspen_score ?? s?.score ?? 0));
          const name = s?.project_name || s?.name || s?.label || `Idea ${i + 1}`;
          const isLast = i === top3.length - 1;
          return (
            <div key={s?.id || i} style={{
              display: 'grid', gridTemplateColumns: '24px 1fr 48px',
              alignItems: 'center', gap: 12,
              padding: '10px 0',
              borderBottom: isLast ? 'none' : '1px solid #f1f3f5',
            }}>
              <span style={{ fontFamily: 'JetBrains Mono, monospace', fontSize: 12, fontWeight: 600, color: i === 0 ? '#a0036c' : '#5a6585' }}>{i + 1}</span>
              <span style={{ fontSize: 13, fontWeight: i === 0 ? 600 : 500, color: '#161f3b', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{name}</span>
              <span style={{ fontFamily: 'JetBrains Mono, monospace', fontSize: 14, fontWeight: 600, color: '#161f3b', textAlign: 'right' }}>{score}</span>
            </div>
          );
        })}
      </div>
      {total > 3 && (
        <div style={{ fontSize: 11.5, color: '#8a93ad', marginTop: 8, fontFamily: 'JetBrains Mono, monospace' }}>
          + {total - 3} more in Workspace
        </div>
      )}
    </div>
  );
};

// ── Inline Execution plan artifact ────────────────────────────────────────────
// Compact summary: phase / task counts + progress bar + first 3 task names.
// Full canvas (List / Board / Timeline) lives in Workspace.
const renderInlineExecutionArtifact = (wbs, opts = {}) => {
  const tasks = Array.isArray(wbs?.tasks) ? wbs.tasks : [];
  if (tasks.length === 0) return null;
  const phases = new Set(tasks.map((t) => String(t?.phase || 'Execution').trim() || 'Execution'));
  const statusCount = { todo: 0, in_progress: 0, blocked: 0, done: 0 };
  tasks.forEach((t) => {
    const s = String(t?.status || 'todo').toLowerCase();
    if (s.includes('done') || s.includes('complete')) statusCount.done += 1;
    else if (s.includes('progress') || s.includes('doing')) statusCount.in_progress += 1;
    else if (s.includes('block')) statusCount.blocked += 1;
    else statusCount.todo += 1;
  });
  const donePct = tasks.length ? Math.round((statusCount.done / tasks.length) * 100) : 0;
  const inProgressPct = tasks.length ? Math.round((statusCount.in_progress / tasks.length) * 100) : 0;
  const wsHref = opts.threadId ? `/workspace/${encodeURIComponent(opts.threadId)}/__execution__` : null;
  return (
    <div style={{
      background: '#fff', border: '1px solid #e9ecef', borderRadius: 14,
      padding: '18px 20px 16px', maxWidth: 720,
      fontFamily: "'Inter Tight', system-ui, sans-serif",
    }}>
      <div style={{ display: 'flex', alignItems: 'baseline', justifyContent: 'space-between', marginBottom: 12 }}>
        <div>
          <div style={{ fontFamily: 'JetBrains Mono, monospace', fontSize: 10.5, color: '#a0036c', letterSpacing: '0.08em', textTransform: 'uppercase', fontWeight: 600 }}>
            Execution plan
          </div>
          <div style={{ fontSize: 13, color: '#5a6585', marginTop: 4 }}>
            {phases.size} phase{phases.size === 1 ? '' : 's'} · {tasks.length} task{tasks.length === 1 ? '' : 's'} · <strong style={{ color: '#161f3b' }}>{donePct}% done</strong>
          </div>
        </div>
        {wsHref && (
          <button
            type="button"
            onClick={() => {
              if (opts.onOpenWorkspaceRoute) {
                void opts.onOpenWorkspaceRoute(opts.threadId, '__execution__');
              } else {
                window.open(wsHref, '_blank', 'noopener,noreferrer');
              }
            }}
            style={{
              padding: '6px 12px', borderRadius: 8,
              background: '#0f172a', color: '#fff',
              border: 'none', fontSize: 12.5, fontWeight: 500, whiteSpace: 'nowrap', cursor: 'pointer',
            }}
          >Open in Workspace ↗</button>
        )}
      </div>
      {/* Progress bar: green=done, navy=in-progress, light gray=todo */}
      <div style={{ display: 'flex', height: 6, borderRadius: 3, overflow: 'hidden', background: '#f1f3f5', marginBottom: 12 }}>
        <div style={{ width: `${donePct}%`, background: '#16a34a' }} />
        <div style={{ width: `${inProgressPct}%`, background: '#161f3b' }} />
      </div>
      <div style={{ display: 'flex', gap: 14, fontFamily: 'JetBrains Mono, monospace', fontSize: 10.5, color: '#5a6585', marginBottom: 10 }}>
        <span><strong style={{ color: '#16a34a' }}>{statusCount.done}</strong> done</span>
        <span><strong style={{ color: '#161f3b' }}>{statusCount.in_progress}</strong> in progress</span>
        {statusCount.blocked > 0 && <span><strong style={{ color: '#dc2626' }}>{statusCount.blocked}</strong> blocked</span>}
        <span><strong style={{ color: '#8a93ad' }}>{statusCount.todo}</strong> to-do</span>
      </div>
      {/* First 3 task names so the user sees what's in the plan at a glance */}
      <div style={{ display: 'flex', flexDirection: 'column' }}>
        {tasks.slice(0, 3).map((t, i) => {
          const isLast = i === Math.min(3, tasks.length) - 1;
          return (
            <div key={t?.id || i} style={{
              display: 'grid', gridTemplateColumns: '1fr auto',
              gap: 12, padding: '7px 0',
              borderBottom: isLast ? 'none' : '1px solid #f1f3f5',
            }}>
              <span style={{ fontSize: 12.5, color: '#161f3b', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{t?.title || 'Untitled task'}</span>
              <span style={{ fontFamily: 'JetBrains Mono, monospace', fontSize: 10.5, color: '#8a93ad' }}>{String(t?.phase || '').slice(0, 24)}</span>
            </div>
          );
        })}
      </div>
      {tasks.length > 3 && (
        <div style={{ fontSize: 11.5, color: '#8a93ad', marginTop: 8, fontFamily: 'JetBrains Mono, monospace' }}>
          + {tasks.length - 3} more in Workspace
        </div>
      )}
    </div>
  );
};

const renderConversationMessage = (message, opts = {}) => {
  // Render scorecard artifact inline
  if (message?.artifact?.type === 'scorecard') {
    return renderScorecardCard(message.artifact.data, opts);
  }
  // Render scorecard loading placeholder inline (holds position in thread)
  if (message?.artifact?.type === 'scorecard-loading') {
    return (
      <div className="jas-message-bubble">
        <div className="jas-scorecard-generating-bubble">
          <span className="jas-scorecard-generating-dots"><span/><span/><span/></span>
          <span className="jas-scorecard-generating-text">{message?.artifact?.label || 'Building your scorecard…'}</span>
        </div>
      </div>
    );
  }
  // Trade-off comparison artifact — compact inline summary of the top
  // ranked ideas across the user's scorecards. Open in Workspace for the
  // full canvas (table, quadrant, all ideas).
  if (message?.artifact?.type === 'tradeoff') {
    return renderInlineTradeoffArtifact(message.artifact.data, opts);
  }
  // Execution plan artifact — compact inline summary of phases / task
  // counts / progress, with Open in Workspace for the full Kanban / List /
  // Timeline canvas.
  if (message?.artifact?.type === 'execution_plan') {
    return renderInlineExecutionArtifact(message.artifact.data, opts);
  }
  const text = String(message?.text || '');
  if (message?.role === 'user') return text;

  return (
    <>
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        components={{
          h1: ({ children }) => <h1 className="jas-md-h1">{children}</h1>,
          h2: ({ children }) => <h2 className="jas-md-h2">{children}</h2>,
          h3: ({ children }) => <h3 className="jas-md-h3">{children}</h3>,
          h4: ({ children }) => <h4 className="jas-md-h4">{children}</h4>,
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
    </>
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
  let scorecardPatched = false;
  mutations.forEach((mutation) => {
    const tool = String(mutation?.tool || '').trim();
    const success = mutation?.success !== false;
    if (!success) return;
    if (tool === 'generate_scorecard' || tool === 'generate_tradeoff_comparison') {
      scenarioChanged = true;
    }
    if (['update_wbs_task', 'add_wbs_task', 'add_wbs_dependency', 'remove_wbs_task', 'generate_execution_plan'].includes(tool)) {
      wbsChanged = true;
    }
    if (tool === 'rename_thread') {
      threadRenamed = true;
    }
    if (tool === 'patch_scorecard') {
      scorecardPatched = true;
    }
  });

  if (!scenarioChanged && !wbsChanged && !threadRenamed && !scorecardPatched) return;

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
  if (scorecardPatched) setScenarioMutationVersion((prev) => prev + 1);
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
      setView('intake');
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
  const [billingCatalog, setBillingCatalog] = useState({ plans: {}, credit_packs: {}, overage_packs: {}, model_types: {} });
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
  useEffect(() => {
    const onCreditsExhausted = (event) => {
      const message = String(event?.detail?.message || "You've reached your monthly thinking power.").trim();
      setBillingMessage(message);
      setBillingModalOpen(true);
      showToast(message, 'warning');
    };
    window.addEventListener(AUTH_EVENTS.CREDITS_EXHAUSTED_EVENT, onCreditsExhausted);
    return () => window.removeEventListener(AUTH_EVENTS.CREDITS_EXHAUSTED_EVENT, onCreditsExhausted);
  }, [showToast]);
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
    // All connectors are available on all plans (free and above) per tool_registry.
    jira_sync: 'free',
    smartsheet_sync: 'free',
    salesforce_insights: 'free',
    snowflake_insights: 'free',
    oracle_fusion_insights: 'free',
    servicenow_insights: 'free',
    netsuite_insights: 'free',
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
  const showRealTeam = !isPlatformAdmin && effectiveCanManageOrg && PLAN_RANK[effectivePlanKey] >= PLAN_RANK.team;
  const showLockedTeam = !showRealTeam && previewPlanCategory === 'individual' && (!isPlatformAdmin || customerPreviewActive);
  const showRealDashboard = previewPlanCategory !== 'individual' || (isPlatformAdmin && !customerPreviewActive);
  const showLockedDashboard = previewPlanCategory === 'individual' && (!isPlatformAdmin || customerPreviewActive);
  const showRealInsights = (isPlatformAdmin && !customerPreviewActive) || PLAN_RANK[effectivePlanKey] >= PLAN_RANK.team;
  const showLockedInsights = !showRealInsights;
  const showRealReports = (isPlatformAdmin && !customerPreviewActive) || PLAN_RANK[effectivePlanKey] >= PLAN_RANK.team;
  const showLockedReports = !showRealReports;
  const showRealActivity = (isPlatformAdmin && !customerPreviewActive) || PLAN_RANK[effectivePlanKey] >= PLAN_RANK.essential;
  const showLockedActivity = !showRealActivity;
  const showRealConnectors = true;
  const showLockedConnectors = false;
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
  const usageWarningLevel = String(billingStatus?.usage_warning_level || 'normal').toLowerCase();
  const [meterHiddenWS, setMeterHiddenWS] = useState(Boolean(user?.ui_preferences?.hide_thinking_power_meter));
  useEffect(() => {
    setMeterHiddenWS(Boolean(user?.ui_preferences?.hide_thinking_power_meter));
  }, [user?.ui_preferences?.hide_thinking_power_meter]);
  const hideThinkingPowerMeter = meterHiddenWS;
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
  const intakeCreditsValue = useMemo(() => {
    const remaining = Number(creditsRemaining);
    if (Number.isFinite(remaining)) return Math.max(0, Math.round(remaining));
    const monthly = Number(monthlyCreditLimit);
    if (Number.isFinite(monthly)) return Math.max(0, Math.round(monthly));
    return null;
  }, [creditsRemaining, monthlyCreditLimit]);
  // Percentage of thinking power REMAINING (0–100)
  const creditsPctRemaining = useMemo(() => {
    const remainingNum = Number(creditsRemaining);
    const limitNum = Number(monthlyCreditLimit);
    if (!Number.isFinite(remainingNum) || !Number.isFinite(limitNum) || limitNum <= 0) return null;
    return Math.max(0, Math.min(100, (Math.max(0, remainingNum) / limitNum) * 100));
  }, [creditsRemaining, monthlyCreditLimit]);

  // Level drives color + visibility — based on % remaining
  const creditsLevel = useMemo(() => {
    if (creditsPctRemaining === null) return 'full';
    if (creditsPctRemaining <= 0)  return 'empty';
    if (creditsPctRemaining <= 10) return 'critical';
    if (creditsPctRemaining <= 20) return 'warning';
    if (creditsPctRemaining <= 50) return 'moderate';
    return 'full';
  }, [creditsPctRemaining]);

  // Only show a text label when the user should start paying attention
  // (≤50% remaining). Floor so we never show a stale 100% post-usage.
  const intakeCreditsCompactLabel = useMemo(() => {
    if (billingLoading || creditsPctRemaining === null) return null;
    if (creditsLevel === 'full') return null; // quiet when plenty remains
    return `${Math.floor(creditsPctRemaining)}%`;
  }, [billingLoading, creditsPctRemaining, creditsLevel]);

  // Tooltip: actual numbers + reset date
  const creditsTitle = useMemo(() => {
    const remainingNum = Number(creditsRemaining);
    const limitNum = Number(monthlyCreditLimit);
    const resetRaw = billingStatus?.cycle_reset_at;
    const resetStr = resetRaw
      ? new Date(resetRaw).toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' })
      : null;
    if (!Number.isFinite(remainingNum) || !Number.isFinite(limitNum) || limitNum <= 0) {
      return 'Thinking power is your monthly usage capacity.';
    }
    const rem = Math.max(0, Math.round(remainingNum)).toLocaleString();
    const lim = Math.round(limitNum).toLocaleString();
    return resetStr
      ? `${rem} of ${lim} thinking power remaining · Resets ${resetStr}`
      : `${rem} of ${lim} thinking power remaining`;
  }, [creditsRemaining, monthlyCreditLimit, billingStatus?.cycle_reset_at]);

  // Keep creditsTone for legacy banner logic
  const creditsTone = useMemo(() => {
    if (creditsLevel === 'empty' || creditsLevel === 'critical') return 'critical';
    if (creditsLevel === 'warning') return 'warning';
    return 'normal';
  }, [creditsLevel]);
  // Use floor (not round) so any consumption drops the badge below 100%.
  // Cap at 99% any time even a token has been used — only literally zero
  // usage shows 100%.
  const creditsBadge = (() => {
    if (creditsRemaining == null) return 'Contracted';
    const remaining = Math.max(0, Number(creditsRemaining || 0));
    const limit = Number(monthlyCreditLimit || 0);
    if (limit <= 0) return 'Usage';
    const rawPct = (remaining / limit) * 100;
    if (remaining >= limit) return '100%';
    // Anything consumed → cap at 99% so user never sees a stale 100%.
    const pct = Math.min(99, Math.floor(rawPct));
    return `${pct}%`;
  })();
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
    && ['warning', 'urgent', 'critical', 'exhausted', 'blocked'].includes(usageWarningLevel)
  ), [billingLoading, usageWarningLevel, user]);
  const lowCreditsBannerToneClass = creditsTone === 'critical' ? 'is-critical' : 'is-warning';
  const lowCreditsHeadline = usageWarningLevel === 'warning'
    ? 'Thinking power is running low'
    : usageWarningLevel === 'urgent'
      ? 'Thinking power is almost depleted'
      : usageWarningLevel === 'exhausted'
        ? 'Monthly thinking power reached'
        : usageWarningLevel === 'blocked'
          ? 'Thinking power usage is blocked'
          : 'Thinking power is running low';
  const lowCreditsBody = usageWarningLevel === 'warning'
    ? 'You’re using your thinking power quickly. Add credits, upgrade, or continue until your reset.'
    : usageWarningLevel === 'urgent'
      ? 'You’re almost out of thinking power. Add credits now to keep working without interruption.'
      : usageWarningLevel === 'exhausted'
        ? `You’ve reached your monthly thinking power. Add credits, upgrade, or wait until your reset on ${formatNextResetDate(billingStatus?.cycle_reset_at)}.`
        : usageWarningLevel === 'blocked'
          ? 'You have exceeded 105% of monthly thinking power. Add credits or upgrade to continue.'
          : 'Review thinking power usage in billing.';
  const toggleThinkingPowerMeter = useCallback(async () => {
    const next = !meterHiddenWS;
    setMeterHiddenWS(next);
    if (typeof updateUiPreferences !== 'function') return;
    await updateUiPreferences({ hide_thinking_power_meter: next });
  }, [meterHiddenWS, updateUiPreferences]);

  // Opt-out for the low-power warning toast (≤10% remaining). Local state
  // so the checkbox responds immediately to clicks; persists to
  // user.ui_preferences via updateUiPreferences in the background.
  const [warningHiddenWS, setWarningHiddenWS] = useState(
    Boolean(user?.ui_preferences?.hide_thinking_power_warning)
  );
  useEffect(() => {
    setWarningHiddenWS(Boolean(user?.ui_preferences?.hide_thinking_power_warning));
  }, [user?.ui_preferences?.hide_thinking_power_warning]);
  const toggleThinkingPowerWarning = useCallback(async () => {
    const next = !warningHiddenWS;
    setWarningHiddenWS(next);  // Optimistic — flips the UI immediately
    if (typeof updateUiPreferences !== 'function') return;
    await updateUiPreferences({ hide_thinking_power_warning: next });
  }, [warningHiddenWS, updateUiPreferences]);

  // Opt-out for the delete-session confirm dialog. Same local-state +
  // optimistic-flip pattern as above. Persists to ui_preferences AND
  // localStorage so it sticks even before billing/user refresh.
  const [skipDeleteConfirmWS, setSkipDeleteConfirmWS] = useState(() => {
    if (Boolean(user?.ui_preferences?.skip_delete_confirm)) return true;
    try { return localStorage.getItem('jaspen.skipDeleteConfirm') === '1'; } catch (_) { return false; }
  });
  useEffect(() => {
    setSkipDeleteConfirmWS(Boolean(user?.ui_preferences?.skip_delete_confirm)
      || (typeof localStorage !== 'undefined' && localStorage.getItem('jaspen.skipDeleteConfirm') === '1'));
  }, [user?.ui_preferences?.skip_delete_confirm]);
  const toggleSkipDeleteConfirm = useCallback(async () => {
    const next = !skipDeleteConfirmWS;
    setSkipDeleteConfirmWS(next);
    try { localStorage.setItem('jaspen.skipDeleteConfirm', next ? '1' : '0'); } catch (_) {}
    if (typeof updateUiPreferences !== 'function') return;
    await updateUiPreferences({ skip_delete_confirm: next });
  }, [skipDeleteConfirmWS, updateUiPreferences]);
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

  // Rehydrate the per-thread Session Uploads list from localStorage whenever the
  // active thread changes (e.g. on a hard refresh). Files that ARE stored as
  // message attachments still show via the render union; this covers the rest
  // (.md, .csv, etc.) that the backend doesn't persist on the message.
  const prevUploadThreadIdRef = useRef(null);
  useEffect(() => {
    const prevId = prevUploadThreadIdRef.current;
    prevUploadThreadIdRef.current = activeThreadId;
    if (!activeThreadId) return;
    let stored = [];
    try {
      const raw = localStorage.getItem(`jas_session_uploads_${activeThreadId}`);
      const parsed = raw ? JSON.parse(raw) : [];
      stored = Array.isArray(parsed) ? parsed : [];
    } catch {
      stored = [];
    }
    if (!prevId) {
      // null -> id: either a hard refresh of an existing thread, or a brand-new
      // session that just received its id. Merge any in-memory uploads (files
      // attached before the id existed) with the stored list, dedupe, persist.
      setSessionUploads((prev) => {
        const seen = new Set();
        const out = [];
        [...(Array.isArray(prev) ? prev : []), ...stored].forEach((f) => {
          const key = `${f?.name}::${f?.size ?? ''}`;
          if (f?.name && !seen.has(key)) { seen.add(key); out.push(f); }
        });
        persistSessionUploads(out, activeThreadId);
        return out;
      });
    } else if (prevId !== activeThreadId) {
      // Switched to a different thread: show only that thread's uploads.
      setSessionUploads(stored);
    }
  }, [activeThreadId]);

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
      setBillingCatalog(catalogData || { plans: {}, credit_packs: {}, overage_packs: {}, model_types: {} });
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
      payload?.tokens?.remaining,
      payload?.tokens_remaining_this_month,
    ];
    const limitCandidates = [
      payload?.monthly_credit_limit,
      payload?.credits?.monthly_limit,
      payload?.monthly_token_limit,
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
        next.tokens_remaining_this_month = Number(remaining);
      }
      if (monthlyLimit != null) {
        next.monthly_credit_limit = Number(monthlyLimit);
        next.monthly_token_limit = Number(monthlyLimit);
      }
      if (
        Number.isFinite(Number(next.monthly_credit_limit))
        && Number.isFinite(Number(next.credits_remaining))
      ) {
        next.credits_used = Math.max(0, Number(next.monthly_credit_limit) - Number(next.credits_remaining));
      }
      return next;
    });

    // ── Thinking Power low-warning toast ───────────────────────────────────
    // The per-turn "Used X.X%" toast was removed — the sidebar gauge + topbar
    // bolt are the source of truth and noise-free. We still fire ONE warning
    // toast per session when remaining drops under THINKING_POWER_LOW_WARNING_PCT
    // (10%) so the user has clear runway to top up. Suppressible per-user
    // via the "Hide low-power warnings" preference in the User Settings drawer.
    try {
      const usagePayload = payload?.usage && typeof payload.usage === 'object' ? payload.usage : null;
      const remainingPct = Number(usagePayload?.thinking_power_remaining_pct);
      const lowWarning = Boolean(usagePayload?.thinking_power_low_warning);
      // Source of truth: local state (warningHiddenWS). Falls back to user
      // prefs in case syncCreditsFromPayload runs before useState initializes.
      const optOut = Boolean(warningHiddenWS ?? user?.ui_preferences?.hide_thinking_power_warning);
      if (lowWarning && !optOut && Number.isFinite(remainingPct) && typeof showToast === 'function') {
        showToast(
          `Thinking Power is low (${remainingPct.toFixed(1)}% left). Top up or wait until reset.`,
          'warning',
          { durationMs: 6000 },
        );
      }
    } catch (_) { /* meter is display-only — never throw */ }

    if (refresh) {
      void loadBilling();
    }
  }, [adminWorkspacePreviewPlan, loadBilling, showToast, warningHiddenWS, user?.ui_preferences?.hide_thinking_power_warning]);

  useEffect(() => {
    if (!canUseScenarios && activeTab === 'scenario') {
      setActiveTab('summary');
      setView('intake');
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

  // Sidebars close only via their explicit X buttons — no click-outside dismissal.

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
              <p className="label">Thinking power</p>
              <p className="value">{creditsPctRemaining == null ? 'Unlimited' : `${Math.round(creditsPctRemaining)}% remaining`}</p>
            </article>
            <article className="jas-account-summary-card">
              <p className="label">Resets</p>
              <p className="value">{formatNextResetDate(billingStatus?.cycle_reset_at) || 'Next cycle'}</p>
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
                      ? 'Contracted pooled thinking power'
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
            <span className="jas-ud-item-label">Thinking power</span>
            <span className="jas-ud-item-badge">{billingLoading ? '...' : creditsBadge}</span>
          </button>
          <button className="jas-ud-meter-toggle" onClick={toggleThinkingPowerMeter}>
            <FontAwesomeIcon icon={faGaugeHigh} />
            {hideThinkingPowerMeter ? 'Show usage meter' : 'Hide usage meter'}
          </button>
          <label className="jas-ud-meter-toggle" style={{ cursor: 'pointer' }}>
            <input
              type="checkbox"
              checked={!warningHiddenWS}
              onChange={toggleThinkingPowerWarning}
              style={{ marginRight: 8 }}
            />
            Show low-power warnings
          </label>
          <label className="jas-ud-meter-toggle" style={{ cursor: 'pointer' }}>
            <input
              type="checkbox"
              checked={skipDeleteConfirmWS}
              onChange={toggleSkipDeleteConfirm}
              style={{ marginRight: 8 }}
            />
            Skip delete confirm
          </label>
        </div>

        {!hideThinkingPowerMeter && (
          <div className="jas-ud-section">
            <div className="jas-ud-section-label">THINKING POWER</div>
            {billingLoading && (
              <p className="jas-ud-usage-empty">Loading usage...</p>
            )}
            {!billingLoading && monthlyCreditLimit == null && (
              <p className="jas-ud-usage-note">Thinking power is managed by your contract on {currentPlanLabel}.</p>
            )}
            {!billingLoading && monthlyCreditLimit != null && (
              <>
                <p className="jas-ud-usage-credits-line">
                  <strong style={{ fontSize: '1.1rem' }}>{creditsPctRemaining == null ? 'Unlimited' : `${Math.round(creditsPctRemaining)}%`}</strong>
                  <span style={{ marginLeft: 6, color: '#64748b', fontSize: '0.8rem' }}>thinking power remaining</span>
                </p>
                {creditsPctRemaining != null && (
                  <div style={{ width: '100%', height: 6, borderRadius: 999, background: '#e2e8f0', overflow: 'hidden', margin: '6px 0' }}>
                    <div style={{
                      height: '100%', borderRadius: 999,
                      width: `${Math.round(creditsPctRemaining)}%`,
                      background: creditsPctRemaining > 50 ? '#7c3aed' : creditsPctRemaining > 20 ? '#f59e0b' : '#dc2626',
                      transition: 'width 0.4s ease',
                    }} />
                  </div>
                )}
                <p className="jas-ud-usage-note">Resets {formatNextResetDate(billingStatus?.cycle_reset_at)}</p>
                {creditsTone !== 'normal' && (
                  <div className="jas-account-actions">
                    <button type="button" className="jas-account-plan-cta" onClick={() => navigate('/account?tab=billing')}>
                      Add credits
                    </button>
                    <button type="button" className="jas-account-plan-cta jas-account-plan-cta-secondary" onClick={() => navigate('/account?tab=plans')}>
                      Upgrade plan
                    </button>
                  </div>
                )}
              </>
            )}
          </div>
        )}

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

  // Toggle voice dictation. When turning ON we proactively request mic access
  // via getUserMedia FIRST — this reliably triggers the browser's permission
  // prompt (the agent-style dialog users expect), whereas webkitSpeechRecognition
  // alone can silently fail with "not-allowed" when the OS/site grant is missing.
  // Only after permission is granted do we flip isRecording (the effect below
  // then starts SpeechRecognition).
  async function handleToggleMic() {
    if (isRecording) {
      setIsRecording(false);
      return;
    }
    const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
    if (!SpeechRecognition) {
      showToast('Voice input is not supported in this browser. Try Chrome.', 'warning');
      return;
    }
    try {
      if (navigator?.mediaDevices?.getUserMedia) {
        // Requesting the stream surfaces Chrome's permission prompt. We stop the
        // tracks immediately — SpeechRecognition opens its own stream; we only
        // needed this to obtain/verify the grant.
        const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
        stream.getTracks().forEach((track) => track.stop());
      }
      setIsRecording(true);
    } catch (err) {
      const name = err?.name || '';
      if (name === 'NotAllowedError' || name === 'SecurityError') {
        showToast(
          'Microphone access is blocked. Click the site/lock icon in the address bar and allow Microphone for jaspen.ai (on macOS also enable Chrome under System Settings → Privacy & Security → Microphone), then try again.',
          'warning',
          { durationMs: 9000 },
        );
      } else if (name === 'NotFoundError' || name === 'NotReadableError') {
        showToast('No microphone was found. Connect a mic and try again.', 'warning');
      } else {
        showToast('Could not start voice input. Please try again.', 'warning');
      }
    }
  }

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
        // Only COMMIT finalized results to the input. With interimResults=true
        // onresult fires repeatedly with the same (growing) interim text; the
        // old code appended every fire, producing garbled, duplicated text.
        let finalChunk = '';
        for (let i = event.resultIndex; i < event.results.length; i++) {
          const res = event.results[i];
          if (res && res.isFinal) {
            finalChunk += res[0].transcript;
          }
        }
        finalChunk = finalChunk.trim();
        if (!finalChunk) return;
        setInput(prev => {
          const separator = prev && !prev.endsWith(' ') ? ' ' : '';
          return prev + separator + finalChunk;
        });
      };

      recognition.onerror = (event) => {
        // 'no-speech' / 'aborted' are benign — the engine just paused or we
        // stopped it. Keep recording (onend will restart). Only a real
        // permission/service failure should turn the mic off.
        const err = event?.error;
        if (err === 'no-speech' || err === 'aborted') {
          return;
        }
        console.error('Speech recognition error:', err);
        recognitionRef.current = null;
        setIsRecording(false);
        // Surface an actionable message instead of failing silently. The most
        // common cause is a denied/blocked mic permission, which the user must
        // grant in the browser (and on macOS, System Settings → Privacy →
        // Microphone → Chrome) — we can't grant it from JS.
        if (err === 'not-allowed' || err === 'service-not-allowed') {
          showToast(
            'Microphone access is blocked. Click the mic/site icon in your browser address bar and allow microphone for jaspen.ai (on macOS also check System Settings → Privacy & Security → Microphone → Chrome), then try again.',
            'warning',
            { durationMs: 9000 },
          );
        } else if (err === 'audio-capture') {
          showToast('No microphone was found. Connect a mic and try again.', 'warning');
        } else if (err) {
          showToast('Voice input hit an error. Please try again.', 'warning');
        }
      };

      recognition.onend = () => {
        // With continuous=true the engine still ends on long pauses. If the
        // user hasn't toggled the mic off (ref still points at us), restart so
        // dictation keeps going. The cleanup/stop path nulls the ref first, so
        // a deliberate stop won't restart.
        if (recognitionRef.current === recognition) {
          try {
            recognition.start();
          } catch (e) {
            recognitionRef.current = null;
            setIsRecording(false);
          }
        }
      };

      recognitionRef.current = recognition;
      try {
        recognition.start();
      } catch (e) {
        // start() throws if called while already started — reset state.
        console.error('Speech recognition start failed:', e);
        recognitionRef.current = null;
        setIsRecording(false);
      }
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
  const buildOnboardingIntakeContext = useCallback((selectionLike = null) => {
    const fallbackSelection = readOnboardingState(user)?.selection || onboardingInitialSelection || {};
    const selection = (selectionLike && typeof selectionLike === 'object')
      ? selectionLike
      : fallbackSelection;
    const roleKey = String(selection?.role || '').trim().toLowerCase();
    const evaluationKey = String(selection?.evaluation || '').trim().toLowerCase();
    const startMode = String(selection?.startMode || '').trim().toLowerCase();
    const industryKey = String(selection?.industry || '').trim().toLowerCase();
    const companySizeKey = String(selection?.company_size || '').trim().toLowerCase();
    const companySizeContext = ONBOARDING_COMPANY_SIZE_TO_CONTEXT[companySizeKey] || '';

    const context = {
      role: roleKey || 'other',
      role_label: ONBOARDING_ROLE_LABELS[roleKey] || ONBOARDING_ROLE_LABELS.other,
      evaluation_focus: evaluationKey || 'new_initiative',
      evaluation_focus_label: ONBOARDING_EVALUATION_LABELS[evaluationKey] || ONBOARDING_EVALUATION_LABELS.new_initiative,
      start_preference: startMode || 'conversation',
      start_preference_label: ONBOARDING_START_LABELS[startMode] || ONBOARDING_START_LABELS.conversation,
      onboarding_complete: true,
    };
    if (industryKey) {
      context.industry = industryKey;
      context.industry_label = ONBOARDING_INDUSTRY_LABELS[industryKey] || ONBOARDING_INDUSTRY_LABELS.other;
    }
    if (companySizeContext) {
      context.company_size = companySizeContext;
      context.company_size_label = ONBOARDING_COMPANY_SIZE_LABELS[companySizeKey] || ONBOARDING_COMPANY_SIZE_LABELS['51_500'];
    }
    return context;
  }, [onboardingInitialSelection, user]);

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
        setTradeoffRequested(false);
        setStrategyObjective('balanced');
        setObjectiveExplicitlySet(false);
// (removed) sidebar uses main `messages` as the thread source of truth
        setCollectedData({});
        setKnowledgeSignals(null);
        setView('intake');
        setActiveTab('summary');
        dispatchSidebar({ type: 'CLOSE_ALL' });
        setInitialRestorePending(false);
        autoScoringTriggeredRef.current = false;
        return;
      }
      const sid = resolvedUrlSessionId;

      let session = await loadSessionById(sid);
      let restoreBundle = null;

      // Fallback: if session detail is blocked by auth on refresh, restore via thread bundle
      if (!session) {
        try {
          restoreBundle = await Jaspen.getThreadBundle(sid, { msg_limit: 50, scn_limit: 50 });

          // Normalize bundle messages into the same chat_history shape your UI expects
          const bundleMsgs = Array.isArray(restoreBundle?.messages) ? restoreBundle.messages : [];
          const chat_history = bundleMsgs
            .map((m) => toHistoryMessageShape(m))
            .filter((x) => {
              const text = String(x?.content || '').trim();
              return text.length > 0 || Boolean(x?.artifact);
            });

          session = {
            // Prefer bundle's resolved thread ID so canonicalSid resolves correctly below
            session_id: String(restoreBundle?.thread?.id || restoreBundle?.thread_id || sid).trim() || sid,
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

      // Prefer the backend-resolved session_id (e.g. "thread_XXX") over the raw URL sid
      // (which may be a UUID if the URL was written before the canonical ID was known).
      const canonicalSid = String(session.session_id || sid).trim() || sid;

      setSessionId(canonicalSid);
      setCurrentSessionId(canonicalSid);
      setLastSessionId(canonicalSid);
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
      // Restore collected_data
      if (session.collected_data && typeof session.collected_data === 'object') {
        setCollectedData(session.collected_data);
      }

      // Restore knowledge signals (if previously saved)
      const savedSignals = session.knowledge_signals || null;
      if (savedSignals && Array.isArray(savedSignals.signals)) {
        setKnowledgeSignals({ signals: savedSignals.signals, confidence: Number(savedSignals.confidence ?? 0) });
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
              canonicalSid,
            scorecardSnapshots: persistedRestoreSnapshots,
            sessionId: canonicalSid,
          })
        : buildScorecardSnapshots({
            threadId: canonicalSid,
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
        sessionId: canonicalSid,
        currentSessionId: canonicalSid,
        selectedScorecardId: restoreSelectedId,
        scorecardSnapshots: restoreSnapshots,
        selectedVariant: null,
        analysisResult: restoreBaseResult,
        bundleCurrentScorecard: currentScorecard,
        bundleBaselineScorecard: baselineScorecard,
        view: restoreInitialView,
        activeTab: 'summary',
      });
      // canonicalSid is already the backend-resolved thread_XXX ID; use it as the final authority.
      const restoredOwnerThreadId = restoreContext.ownerThreadId || canonicalSid;

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
        // Prevent auto-score from re-triggering on page reload — result already exists
        autoScoringTriggeredRef.current = true;
        setView('intake');
        setActiveTab('summary');
      } else {
        setView('intake');
      }

      // Always refresh scenarios from backend truth.
      // Pass the analysis result's thread_id as a fallback in case restoredOwnerThreadId
      // is an orphan session (e.g. created by a hard-reload) that has no baseline stored.
      refreshBundle(restoredOwnerThreadId, { fallbackTid: restoreBaseResult?.thread_id });

      // Refresh knowledge signals in background (get fresh signals on restore)
      void refreshKnowledgeSignals(restoredOwnerThreadId);

      setInitialRestorePending(false);
    })();

    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [allowedModelTypes]);

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

  }, [view, sessionId, analysisHistory, messages?.length]);

  // --- Upload (UI only) ---
  const fileInputRef = useRef(null);
  const chatTabInputRef = useRef(null);
  const intakeInputRef = useRef(null);
  const modelMenuRef = useRef(null);

const hasConversationMessages = Array.isArray(messages)
  && messages.some((m) => String(m?.text || '').trim().length > 0);

// canAnalyze: true once the user has provided at least 3 substantive messages
const canAnalyze = useMemo(() => {
  const userTurns = messages?.filter(m => m.role === 'user' && (m.text || '').trim().length > 0) || [];
  return userTurns.length >= 3;
}, [messages]);

// Advance sidebar pill to 'scoring' the moment a scorecard lands
useEffect(() => {
  if (analysisResult) setActivePill('scoring');
}, [analysisResult]); // eslint-disable-line react-hooks/exhaustive-deps

// On session resume: scorecardSnapshots load from the bundle before analysisResult
// is set (analysisResult requires hasMeaningfulScorecardData to pass). If the pill
// is still at the initial 'discovery' state and snapshots exist, advance it now.
// We use a ref so this only fires once — subsequent snapshot changes (user scores
// a new idea) don't reset a pill the user has explicitly navigated away from.
const _pillSeededRef = useRef(false);
useEffect(() => {
  if (_pillSeededRef.current) return;
  if (Array.isArray(scorecardSnapshots) && scorecardSnapshots.length > 0) {
    _pillSeededRef.current = true;
    setActivePill((prev) => prev === 'discovery' ? 'scoring' : prev);
  }
}, [scorecardSnapshots]); // eslint-disable-line react-hooks/exhaustive-deps

// On session resume: if there's already an execution plan, jump straight to
// the Execution pill so users land in the right place after a page refresh.
const _wbsPillSeededRef = useRef(false);
useEffect(() => {
  if (_wbsPillSeededRef.current) return;
  if (Array.isArray(threadWbs?.tasks) && threadWbs.tasks.length > 0) {
    _wbsPillSeededRef.current = true;
    setActivePill('execution');
  }
}, [threadWbs]); // eslint-disable-line react-hooks/exhaustive-deps

// Primary path: artifacts arrive as explicit assistant messages from backend
// and are rendered directly in thread order. Backward-compat fallback: older
// threads may still persist artifacts only in snapshot/WBS state; surface them
// inline when message artifacts are missing.
const displayMessages = useMemo(() => {
  const baseMessages = Array.isArray(messages) ? [...messages] : [];
  const existingArtifactTypes = new Set(
    baseMessages
      .map((entry) => String(entry?.artifact?.type || '').trim())
      .filter(Boolean)
  );

  const snapshotPool = Array.isArray(scorecardSnapshots) && scorecardSnapshots.length > 0
    ? scorecardSnapshots
    : (analysisResult && typeof analysisResult === 'object' ? [analysisResult] : []);
  const hasProjectPlan = Array.isArray(threadWbs?.tasks) && threadWbs.tasks.length > 0;
  const hasLegacyInputs = snapshotPool.length > 0 || hasProjectPlan;
  if (!hasLegacyInputs) return baseMessages;

  const existingIds = new Set(
    baseMessages.map((entry) => String(entry?.id || '').trim()).filter(Boolean)
  );
  const fallbackArtifacts = [];

  if (!existingArtifactTypes.has('scorecard')) {
    snapshotPool.forEach((snapshot, idx) => {
      if (!hasMeaningfulScorecardData(snapshot)) return;
      const snapshotId = String(
        snapshot?.id || snapshot?.analysis_id || snapshot?.analysisId || `legacy-${idx + 1}`
      ).trim();
      let messageId = `legacy-scorecard-${snapshotId}`;
      if (existingIds.has(messageId)) {
        messageId = `${messageId}-${idx + 1}`;
      }
      existingIds.add(messageId);
      fallbackArtifacts.push({
        id: messageId,
        role: 'ai',
        text: '',
        artifact: {
          type: 'scorecard',
          data: snapshot,
        },
        timestamp: snapshot?.created_at || snapshot?.createdAt || null,
      });
    });
  }

  if (!existingArtifactTypes.has('tradeoff') && snapshotPool.length >= 2 && tradeoffRequested) {
    const included = snapshotPool.filter((snapshot) => snapshot?.display_overrides?.tradeoff_included !== false);
    if (included.length >= 2) {
      let messageId = 'legacy-tradeoff-artifact';
      if (existingIds.has(messageId)) {
        messageId = `${messageId}-${Date.now()}`;
      }
      const latestSnapshotTs = included
        .map((snapshot) => Date.parse(String(snapshot?.created_at || snapshot?.createdAt || '')))
        .filter((value) => Number.isFinite(value))
        .sort((a, b) => b - a)[0];
      existingIds.add(messageId);
      fallbackArtifacts.push({
        id: messageId,
        role: 'ai',
        text: '',
        artifact: {
          type: 'tradeoff',
          data: {
            snapshots: included,
            generated_at: new Date().toISOString(),
          },
        },
        timestamp: Number.isFinite(latestSnapshotTs) ? new Date(latestSnapshotTs).toISOString() : null,
      });
    }
  }

  if (!existingArtifactTypes.has('execution_plan') && hasProjectPlan) {
    let messageId = 'legacy-execution-plan-artifact';
    if (existingIds.has(messageId)) {
      messageId = `${messageId}-${Date.now()}`;
    }
    existingIds.add(messageId);
    fallbackArtifacts.push({
      id: messageId,
      role: 'ai',
      text: '',
      artifact: {
        type: 'execution_plan',
        data: threadWbs,
      },
      timestamp: threadWbs?.updated_at || threadWbs?.created_at || null,
    });
  }

  if (!fallbackArtifacts.length) return baseMessages;

  const composed = [...baseMessages];
  const findAnchorIndex = (regex) => {
    for (let i = composed.length - 1; i >= 0; i -= 1) {
      const entry = composed[i];
      const text = String(entry?.text || '').trim();
      if (!text) continue;
      if (regex.test(text)) return i;
    }
    return -1;
  };

  const toMs = (value) => {
    const parsed = Date.parse(String(value || ''));
    return Number.isFinite(parsed) ? parsed : null;
  };

  const orderedFallback = [...fallbackArtifacts].sort((a, b) => {
    const aTs = toMs(a?.timestamp);
    const bTs = toMs(b?.timestamp);
    if (aTs === null && bTs === null) return 0;
    if (aTs === null) return 1;
    if (bTs === null) return -1;
    return aTs - bTs;
  });

  orderedFallback.forEach((artifactEntry) => {
    const artifactType = String(artifactEntry?.artifact?.type || '').trim();
    let anchor = -1;

    // Prefer chronological placement when timestamps exist.
    const artifactTs = toMs(artifactEntry?.timestamp);
    if (artifactTs !== null) {
      let lastBeforeIdx = -1;
      for (let i = 0; i < composed.length; i += 1) {
        const entryTs = toMs(composed[i]?.timestamp);
        if (entryTs !== null && entryTs <= artifactTs) {
          lastBeforeIdx = i;
        }
      }
      if (lastBeforeIdx >= 0) {
        anchor = lastBeforeIdx;
      }
    }

    // Fall back to semantic anchoring when timestamp positioning is unavailable.
    if (anchor < 0) {
      if (artifactType === 'scorecard') {
        anchor = findAnchorIndex(/\b(scorecard|score this|scored|building your scorecard)\b/i);
      } else if (artifactType === 'tradeoff') {
        anchor = findAnchorIndex(/\b(trade[-\s]?off|compare|rank|side[-\s]?by[-\s]?side)\b/i);
      } else if (artifactType === 'execution_plan') {
        anchor = findAnchorIndex(/\b(execution plan|wbs|work breakdown|build execution)\b/i);
      }
    }
    if (anchor >= 0) {
      composed.splice(anchor + 1, 0, artifactEntry);
    } else {
      composed.push(artifactEntry);
    }
  });

  return composed;
}, [analysisResult, messages, scorecardSnapshots, threadWbs, tradeoffRequested]);

const hasTradeoffArtifact = useMemo(
  () => (Array.isArray(displayMessages) ? displayMessages : []).some(
    (entry) => String(entry?.artifact?.type || '').trim() === 'tradeoff'
  ),
  [displayMessages]
);

  const scoredIdeaInsights = useMemo(() => {
  const parseScore = (value) => {
    const raw = Number(value?.jaspen_score ?? value?.score ?? NaN);
    if (!Number.isFinite(raw) || raw <= 0) return null;
    return Math.max(0, Math.min(100, raw));
  };

  const parseConfidence = (value) => {
    if (value == null) return null;
    if (typeof value === 'number' && Number.isFinite(value)) {
      return Math.max(0, Math.min(100, Math.round(value)));
    }
    const text = String(value || '').trim();
    if (!text) return null;
    const numeric = Number(text.replace('%', ''));
    return Number.isFinite(numeric) ? Math.max(0, Math.min(100, Math.round(numeric))) : null;
  };

  const inferConfidenceFromDimensions = (value) => {
    const dims = value?.dimensions && typeof value.dimensions === 'object' ? value.dimensions : {};
    const confidenceMap = { high: 85, medium: 70, low: 50, assumed: 35 };
    const values = Object.values(dims)
      .map((dim) => String(dim?.confidence || '').toLowerCase().trim())
      .map((conf) => confidenceMap[conf])
      .filter((conf) => Number.isFinite(conf));
    if (!values.length) return null;
    const avg = values.reduce((sum, item) => sum + item, 0) / values.length;
    return Math.max(0, Math.min(100, Math.round(avg)));
  };

  const deriveLabel = (value, fallbackLabel) => {
    const candidate = String(
      value?.display_overrides?.title
      || value?.label
      || value?.name
      || value?.project_name
      || value?.initiative_name
      || fallbackLabel
      || ''
    ).trim();
    if (!candidate) return null;
    return isBaselineLikeLabel(candidate) ? 'Scorecard' : _capTitleSmart(candidate);
  };

  const entries = [];
  const seen = new Set();

  const pushEntry = (rawValue, meta = {}) => {
    if (!rawValue || typeof rawValue !== 'object' || !hasMeaningfulScorecardData(rawValue)) return;
    const score = parseScore(rawValue);
    if (!Number.isFinite(score)) return;
    const entryId = String(
      rawValue?.id
      || rawValue?.analysis_id
      || rawValue?.analysisId
      || meta?.id
      || ''
    ).trim();
    const key = entryId || `${meta?.source || 'scorecard'}:${entries.length}`;
    if (seen.has(key)) return;
    seen.add(key);

    const explicitConfidence = parseConfidence(
      rawValue?.data_confidence
      ?? rawValue?.confidence_level
      ?? rawValue?.confidence
      ?? rawValue?.meta?.confidence
    );
    const inferredConfidence = inferConfidenceFromDimensions(rawValue);
    const confidence = Number.isFinite(explicitConfidence) ? explicitConfidence : inferredConfidence;

    entries.push({
      id: entryId || key,
      label: deriveLabel(rawValue, meta?.fallbackLabel || null) || `Scorecard ${entries.length + 1}`,
      score,
      confidence: Number.isFinite(confidence) ? confidence : null,
      timestamp: String(meta?.timestamp || rawValue?.created_at || rawValue?.updated_at || '').trim() || null,
      data: rawValue,
      source: meta?.source || 'unknown',
      index: Number.isFinite(meta?.index) ? meta.index : entries.length,
    });
  };

  (Array.isArray(scorecardSnapshots) ? scorecardSnapshots : []).forEach((snapshot, idx) => {
    pushEntry(snapshot, { source: 'snapshot', index: idx });
  });

  (Array.isArray(displayMessages) ? displayMessages : []).forEach((entry, idx) => {
    if (String(entry?.artifact?.type || '').trim() !== 'scorecard') return;
    const artifactData = entry?.artifact?.data;
    pushEntry(artifactData, {
      source: 'artifact',
      index: idx,
      timestamp: entry?.timestamp || artifactData?.created_at || artifactData?.updated_at || null,
      fallbackLabel: entry?.artifact?.label || null,
    });
  });

  pushEntry(activeScorecard, { source: 'active' });
  pushEntry(analysisResult, { source: 'analysisResult' });
  pushEntry(bundleCurrentScorecard, { source: 'bundleCurrent' });
  pushEntry(bundleBaselineScorecard, { source: 'bundleBaseline' });

  const orderedEntries = [...entries].sort((a, b) => {
    const aTs = Date.parse(String(a?.timestamp || ''));
    const bTs = Date.parse(String(b?.timestamp || ''));
    const aHasTs = Number.isFinite(aTs);
    const bHasTs = Number.isFinite(bTs);
    if (aHasTs && bHasTs && aTs !== bTs) return aTs - bTs;
    const aIndex = Number.isFinite(a?.index) ? a.index : 0;
    const bIndex = Number.isFinite(b?.index) ? b.index : 0;
    return aIndex - bIndex;
  });

  const ranked = orderedEntries.filter((entry) => Number.isFinite(entry.score));
  const confidenceSamples = orderedEntries
    .map((entry) => entry?.confidence)
    .filter((confidence) => Number.isFinite(confidence));
  const highest = ranked.length > 0
    ? ranked.reduce((winner, entry) => (winner == null || entry.score > winner.score ? entry : winner), null)
    : null;
  const averageScore = ranked.length > 0
    ? Math.round((ranked.reduce((sum, entry) => sum + entry.score, 0) / ranked.length) * 10) / 10
    : null;
  const averageConfidence = confidenceSamples.length > 0
    ? Math.round(confidenceSamples.reduce((sum, entry) => sum + entry, 0) / confidenceSamples.length)
    : null;

  return {
    items: orderedEntries,
    count: orderedEntries.length,
    highest,
    averageScore,
    averageConfidence,
  };
}, [
  activeScorecard,
  analysisResult,
  bundleBaselineScorecard,
  bundleCurrentScorecard,
  displayMessages,
  scorecardSnapshots,
]);

const insightsScoreSource = useMemo(() => {
  const selectedId = String(effectiveSelectedScorecardId || '').trim();
  const matchesSelectedId = (value) => {
    if (!selectedId || !value || typeof value !== 'object') return false;
    const candidateIds = [
      value?.id,
      value?.analysis_id,
      value?.analysisId,
      value?.scorecard_id,
      value?.snapshot_id,
    ]
      .map((entry) => String(entry || '').trim())
      .filter(Boolean);
    return candidateIds.includes(selectedId);
  };

  const selectedSnapshot = selectedId
    ? (Array.isArray(scorecardSnapshots) ? scorecardSnapshots : []).find((snapshot) => {
      return matchesSelectedId(snapshot);
    }) || null
    : null;

  const selectedInsightScorecard = selectedId
    ? (scoredIdeaInsights?.items || []).find((entry) => matchesSelectedId(entry) || matchesSelectedId(entry?.data))?.data || null
    : null;

  const latestScoredIdea = (() => {
    const items = Array.isArray(scoredIdeaInsights?.items) ? scoredIdeaInsights.items : [];
    if (!items.length) return null;
    return items[items.length - 1]?.data || null;
  })();

  const activeMatchesSelected = matchesSelectedId(activeScorecard);

  const candidates = [
    selectedSnapshot,
    selectedInsightScorecard,
    activeMatchesSelected ? activeScorecard : null,
    latestScoredIdea,
    activeScorecard,
    analysisResult,
    bundleCurrentScorecard,
    bundleBaselineScorecard,
  ].filter((entry) => entry && typeof entry === 'object' && hasMeaningfulScorecardData(entry));

  return candidates[0] || null;
}, [
  activeScorecard,
  analysisResult,
  bundleBaselineScorecard,
  bundleCurrentScorecard,
  effectiveSelectedScorecardId,
  scorecardSnapshots,
  scoredIdeaInsights,
]);

const insightsConfidenceSource = useMemo(() => {
  const selectedId = String(effectiveSelectedScorecardId || '').trim();
  const matchesSelectedId = (value) => {
    if (!selectedId || !value || typeof value !== 'object') return false;
    const candidateIds = [
      value?.id,
      value?.analysis_id,
      value?.analysisId,
      value?.scorecard_id,
      value?.snapshot_id,
      value?.data?.id,
      value?.data?.analysis_id,
      value?.data?.analysisId,
    ]
      .map((entry) => String(entry || '').trim())
      .filter(Boolean);
    return candidateIds.includes(selectedId);
  };

  const selectedSnapshot = selectedId
    ? (Array.isArray(scorecardSnapshots) ? scorecardSnapshots : []).find((snapshot) => {
      return matchesSelectedId(snapshot);
    }) || null
    : null;

  const selectedInsightEntry = selectedId
    ? (scoredIdeaInsights?.items || []).find((entry) => matchesSelectedId(entry) || matchesSelectedId(entry?.data)) || null
    : null;
  const selectedInsightScorecard = selectedInsightEntry?.data || null;

  const latestInsightEntry = (() => {
    const items = Array.isArray(scoredIdeaInsights?.items) ? scoredIdeaInsights.items : [];
    if (!items.length) return null;
    return items[items.length - 1] || null;
  })();
  const latestScoredIdea = latestInsightEntry?.data || null;

  const candidates = [
    selectedInsightEntry,
    selectedInsightScorecard,
    selectedSnapshot,
    insightsScoreSource,
    latestInsightEntry,
    latestScoredIdea,
    activeScorecard,
    analysisResult,
    bundleCurrentScorecard,
    bundleBaselineScorecard,
  ].filter((entry) => entry && typeof entry === 'object');

  for (const candidate of candidates) {
    const rawConfidence = Number(candidate?.confidence ?? candidate?.confidence_pct ?? candidate?.confidence_percent ?? NaN);
    if (Number.isFinite(rawConfidence)) {
      return Math.max(0, Math.min(100, rawConfidence));
    }
  }

  return null;
}, [
  activeScorecard,
  analysisResult,
  bundleBaselineScorecard,
  bundleCurrentScorecard,
  effectiveSelectedScorecardId,
  insightsScoreSource,
  scorecardSnapshots,
  scoredIdeaInsights,
]);

const tradeoffEligibleScoredItems = useMemo(() => {
  const items = Array.isArray(scoredIdeaInsights?.items) ? scoredIdeaInsights.items : [];
  return items
    .filter((entry) => Number.isFinite(entry?.score))
    .map((entry, idx) => ({
      id: String(entry?.id || '').trim() || `scorecard-${idx + 1}`,
      label: String(entry?.label || '').trim() || `Scorecard ${idx + 1}`,
      score: Math.max(0, Math.min(100, Number(entry.score))),
      confidence: Number.isFinite(entry?.confidence) ? Number(entry.confidence) : null,
      data: entry?.data && typeof entry.data === 'object' ? entry.data : null,
    }));
}, [scoredIdeaInsights]);

// Trade-off auto-evolves: as soon as the session has two or more scored ideas,
// enable the trade-off so it builds (and continuously refreshes) without the
// user having to ask. The local trade-off artifact is recomputed from the
// current snapshot pool on every render, so it stays in sync as new ideas are
// scored. (This only flips the flag on — never off — so the user can still
// dismiss individual ideas via tradeoff_included overrides.)
useEffect(() => {
  if (!tradeoffRequested && tradeoffEligibleScoredItems.length >= 2) {
    setTradeoffRequested(true);
  }
}, [tradeoffRequested, tradeoffEligibleScoredItems.length]);

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
      {activeSources.map((source) => {
        const srcData = contextSourceData[source.id] || '';
        const hasError = typeof srcData === 'string' && srcData.startsWith('__error__');
        const isLoading = contextSourceLoading && !srcData;
        return (
          <span
            key={source.id}
            className={`jas-objective-selection-pill${hasError ? ' jas-pill-error' : ''}${isLoading ? ' jas-pill-loading' : ''}`}
            title={hasError ? srcData.replace('__error__:', '') : `${source.label} data loaded as AI context`}
          >
            <span className="jas-objective-selection-pill-text">
              {isLoading ? `${source.label}…` : source.label}
            </span>
            <button
              type="button"
              className="jas-objective-selection-pill-clear"
              onClick={() => {
                // Clear error state and deactivate
                setContextSourceData((prev) => { const n = {...prev}; delete n[source.id]; return n; });
                setActiveContextSourceIds((prev) => { const n = new Set(prev); n.delete(source.id); return n; });
              }}
              aria-label={`Remove ${source.label} data context`}
              title={`Remove ${source.label} data context`}
              disabled={busy} aria-disabled={busy}
            >
              <FontAwesomeIcon icon={faTimes} />
            </button>
          </span>
        );
      })}
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

  const appendArtifactMessagesFromPayload = useCallback((payload) => {
    const artifactMessages = Array.isArray(payload?.artifact_messages) ? payload.artifact_messages : [];
    if (!artifactMessages.length) return;
    const incoming = toUiMessages(artifactMessages);
    if (!incoming.length) return;
    setMessages((prev) => {
      const next = Array.isArray(prev) ? [...prev] : [];
      incoming.forEach((entry) => {
        const artifactType = String(entry?.artifact?.type || '').trim();
        const artifactId = String(entry?.artifact?.data?.id || entry?.artifact?.data?.analysis_id || '').trim();
        const duplicate = next.some((existing) => {
          const existingType = String(existing?.artifact?.type || '').trim();
          const existingId = String(existing?.artifact?.data?.id || existing?.artifact?.data?.analysis_id || '').trim();
          if (!artifactType || artifactType !== existingType) return false;
          if (artifactId && existingId) return artifactId === existingId;
          return false;
        });
        if (!duplicate) next.push(entry);
      });
      return next;
    });
  }, []);

  const setStreamingAssistantError = useCallback((messageId, fallbackText, { keepPartial = false } = {}) => {
    setMessages((prev) => prev.map((message) => {
      if (message.id !== messageId) return message;
      const errorNote = fallbackText || 'Sorry — I hit an error. Please try again.';
      const partialText = keepPartial ? String(message.text || '').trim() : '';
      return {
        ...message,
        text: partialText ? `${partialText}\n\n---\n*${errorNote}*` : errorNote,
        streaming: false,
      };
    }));
  }, []);

  const toolStatusLabel = useCallback((toolName) => {
    switch (String(toolName || '').trim()) {
      case 'add_wbs_task':
      case 'update_wbs_task':
      case 'add_wbs_dependency':
      case 'remove_wbs_task':
      case 'generate_execution_plan':
        return 'Updating execution plan…';
      case 'generate_scorecard':
        return 'Building scorecard…';
      case 'generate_tradeoff_comparison':
        return 'Comparing scorecards…';
      case 'rename_thread':
        return 'Renaming initiative…';
      case 'get_readiness_snapshot':
        return 'Checking confidence signals…';
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
    intakeContext,
    viewContext,
    attachments,
  }) => {
    setIsStreamingReply(true);
    const placeholderId = createStreamingAssistantPlaceholder();
    // Wire up a fresh AbortController for this stream so the Stop button
    // can cancel mid-flight. Any prior controller is left to be GC'd —
    // we don't try to "stop the previous stream" since busy state prevents
    // concurrent sends.
    const controller = (typeof AbortController !== 'undefined') ? new AbortController() : null;
    streamAbortRef.current = controller;
    let finalPayload = null;
    try {
      finalPayload = await Jaspen.streamConversation({
        session_id: threadId,
        user_message: userText,
        model_type: modelType,
        strategy_objective: objective,
        intake_context: intakeContext && typeof intakeContext === 'object' ? intakeContext : undefined,
        view_context: viewContext && typeof viewContext === 'object' ? viewContext : undefined,
        attachments,
        abortSignal: controller?.signal,
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
          appendArtifactMessagesFromPayload(payload);
        },
      });
      finalizeStreamingAssistant(placeholderId, finalPayload?.reply || finalPayload?.message || '', {
        historyIndex: Number.isInteger(finalPayload?.assistant_message_index) ? finalPayload.assistant_message_index : null,
        hasMutations: Array.isArray(finalPayload?.mutations) && finalPayload.mutations.length > 0,
        canUndo: Boolean(finalPayload?.undo_available),
      });
      appendArtifactMessagesFromPayload(finalPayload);
      setStreamToolStatus('');
      return finalPayload;
    } catch (streamErr) {
      setStreamToolStatus('');
      // Stop button → AbortError. Treat as a clean cancel, not a failure.
      const wasAborted = streamErr?.name === 'AbortError' || controller?.signal?.aborted;
      if (wasAborted) {
        setStreamingAssistantError(placeholderId, 'Stopped.');
        return finalPayload;
      }
      setStreamingAssistantError(placeholderId, 'Sorry — I hit an error. Please try again.', { keepPartial: true });
      throw streamErr;
    } finally {
      streamAbortRef.current = null;
      setIsStreamingReply(false);
    }
  }, [
    appendStreamingAssistantDelta,
    createStreamingAssistantPlaceholder,
    finalizeStreamingAssistant,
    appendArtifactMessagesFromPayload,
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
          appendArtifactMessagesFromPayload(payload);
        },
      });
      finalizeStreamingAssistant(placeholderId, finalPayload?.reply || finalPayload?.message || '', {
        historyIndex: Number.isInteger(finalPayload?.assistant_message_index) ? finalPayload.assistant_message_index : null,
        hasMutations: Array.isArray(finalPayload?.mutations) && finalPayload.mutations.length > 0,
        canUndo: Boolean(finalPayload?.undo_available),
      });
      appendArtifactMessagesFromPayload(finalPayload);
      setStreamToolStatus('');
      return finalPayload;
    } catch (streamErr) {
      setStreamToolStatus('');
      setStreamingAssistantError(placeholderId, 'Sorry — I hit an error. Please try again.', { keepPartial: true });
      throw streamErr;
    } finally {
      setIsStreamingReply(false);
    }
  }, [
    appendStreamingAssistantDelta,
    createStreamingAssistantPlaceholder,
    finalizeStreamingAssistant,
    appendArtifactMessagesFromPayload,
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
  // Flow: Call Jaspen.convoStart → set session → append message → save
  async function startConversation(description, options = {}) {
    setBusy(true); setError(null);

    try {
      const starterIntakeContext = (selectedStarter && typeof selectedStarter.intake_context === 'object')
        ? selectedStarter.intake_context
        : {};
      const onboardingIntakeContext = buildOnboardingIntakeContext();
      const selectedObjectiveLabel = OBJECTIVE_LABEL_BY_KEY[strategyObjective] || OBJECTIVE_LABEL_BY_KEY.balanced;
      const intakeContext = {
        ...starterIntakeContext,
        ...(onboardingIntakeContext && typeof onboardingIntakeContext === 'object' ? onboardingIntakeContext : {}),
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

      if (data?.model_type) {
        setSelectedModelType(String(data.model_type).toLowerCase());
      }
      setStrategyObjective(normalizeStrategyObjective(data?.strategy_objective || strategyObjective));
      setObjectiveExplicitlySet(Boolean(data?.objective_explicitly_set) || objectiveExplicitlySet);
      await applyMutationRefreshes(data, sid);
      setSelectedStarterId('');


      // REMOVED - AI Agent backend handles persistence automatically
      // await saveSessionToBackend({...});
      await fetchSessions();

      // Kick off knowledge signal extraction in background
      void refreshKnowledgeSignals(sid);

      // Auto-scoring is OFF. Scoring is a user-initiated action, never
      // system-initiated. The Jaspen Insights panel surfaces a "Generate
      // scorecard" CTA when confidence is high enough; the user clicks it
      // when they're ready. The "+ New Version" button on existing
      // scorecards covers re-scoring. Conversations stay conversational.
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

  // === Knowledge signals refresh (background, non-blocking) ===
  // Calls the AI-powered knowledge extraction endpoint after each chat turn.
  // Updates knowledgeSignals state with captured items + gaps + confidence.
  const refreshKnowledgeSignals = useCallback(async (sid) => {
    if (!sid) return;
    try {
      const res = await fetch(
        `${API_BASE}/api/v1/ai-agent/threads/${encodeURIComponent(sid)}/knowledge/refresh`,
        {
          method: 'POST',
          credentials: 'include',
          headers: buildAuthHeaders({ 'Content-Type': 'application/json' }, 'POST'),
        }
      );
      if (!res.ok) return;
      const data = await res.json();
      if (Array.isArray(data?.signals)) {
        setKnowledgeSignals({ signals: data.signals, confidence: Number(data.confidence ?? 0) });
      }
    } catch (e) {
      devWarn('[refreshKnowledgeSignals] failed', e);
    }
  }, []);

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
    const ongoingIntakeContext = {
      ...(buildOnboardingIntakeContext() || {}),
      ...(pendingOnboardingContext && typeof pendingOnboardingContext === 'object' ? pendingOnboardingContext : {}),
      objective: OBJECTIVE_LABEL_BY_KEY[strategyObjective] || OBJECTIVE_LABEL_BY_KEY.balanced,
    };
    const data = await streamConversationReply({
      threadId: sessionId,
      userText,
      modelType: selectedModelType,
      objective: strategyObjective,
      intakeContext: ongoingIntakeContext,
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

    const updatedCollected = data?.collected_data || collectedData;
    setCollectedData(updatedCollected);

    await fetchSessions();

    // Refresh knowledge signals in background after each turn
    void refreshKnowledgeSignals(sessionId);

    // Auto-scoring is OFF. Scoring is a user-initiated action, never
    // system-initiated. See the matching comment on the start path above.

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
const [usedContextSourceIds, setUsedContextSourceIds] = useState(new Set()); // persistent: accumulates all sources ever successfully sent to AI this session
const [contextSourceData, setContextSourceData] = useState({});
const [contextSourceLoading, setContextSourceLoading] = useState(false);

// Confidence: AI-driven when available (from knowledgeSignals), falls back to local formula.
const confidence = useMemo(() => {
  if (!sessionId) return 0;
  // Prefer AI-computed confidence from background refresh
  if (knowledgeSignals && typeof knowledgeSignals.confidence === 'number') {
    return Math.min(100, Math.max(0, Math.round(knowledgeSignals.confidence)));
  }
  // Fallback: local formula from message depth + richness + connectors
  const userMsgs = messages.filter(m => m.role === 'user' && (m.text || '').trim().length > 0);
  if (userMsgs.length === 0) return 0;
  const msgScore = Math.min(60, userMsgs.length * 15);
  const totalChars = userMsgs.reduce((sum, m) => sum + (m.text || '').length, 0);
  const richScore = Math.min(20, Math.round(totalChars / 150));
  const connectorScore = Math.min(15, (activeContextSourceIds?.size || 0) * 5);
  const dataScore = Math.min(5, Object.values(collectedData || {}).filter(v => v && String(v).trim()).length);
  return Math.min(100, msgScore + richScore + connectorScore + dataScore);
}, [sessionId, knowledgeSignals, messages, activeContextSourceIds, collectedData]);

// Keep uiReadiness as an alias so existing render references don't need mass-updating
const uiReadiness = confidence;

// Signals for Discovery checklist: AI-driven when available, local fallback otherwise
const collectedSignals = useMemo(() => {
  // If AI-driven signals exist, use them (may include unchecked gaps with hints)
  if (knowledgeSignals && Array.isArray(knowledgeSignals.signals) && knowledgeSignals.signals.length > 0) {
    return knowledgeSignals.signals.map(s => ({
      id: s.id,
      label: s.label,
      complete: Boolean(s.captured),
      hint: s.hint || null,
    }));
  }
  // Fallback: milestone-based from message count + connectors
  const userMsgs = (messages || []).filter(m => m.role === 'user' && (m.text || '').trim().length > 0);
  const signals = [];
  if (userMsgs.length >= 1) signals.push({ id: 'idea', label: 'Initial idea captured', complete: true, hint: null });
  if (userMsgs.length >= 2) signals.push({ id: 'context', label: 'Context provided', complete: true, hint: null });
  if (userMsgs.length >= 3) signals.push({ id: 'detail', label: 'Detailed requirements shared', complete: true, hint: null });
  if (userMsgs.length >= 5) signals.push({ id: 'followup', label: 'Follow-up context captured', complete: true, hint: null });
  for (const source of (connectedDataSources || [])) {
    signals.push({ id: `src_${source.id}`, label: `${source.label || source.id} data`, complete: Boolean(activeContextSourceIds?.has(source.id)), hint: null });
  }
  return signals;
}, [knowledgeSignals, messages, connectedDataSources, activeContextSourceIds]);

const renderCollectedSignals = () => {
  if (!sessionId) return null;
  const complete = collectedSignals.filter(s => s.complete);
  const pending = collectedSignals.filter(s => !s.complete);
  return (
    <>
      <div className="jas-collected-section">
        <h4>What Jaspen knows</h4>
        {complete.length === 0 && !knowledgeSignals && (
          <p style={{ color: 'var(--color-text-muted)', fontSize: '13px', lineHeight: 1.5, margin: '6px 0 0' }}>
            Start the conversation to build context.
          </p>
        )}
      </div>
      {complete.length > 0 && (
        <div className="jas-checklist">
          {complete.map(s => (
            <label className="jas-check-item" key={s.id}>
              <input type="checkbox" className="jas-check" checked readOnly />
              <div className="jas-check-main">
                <div className="jas-check-label">{s.label}</div>
              </div>
            </label>
          ))}
        </div>
      )}
      {pending.length > 0 && (
        <div style={{ marginTop: pending.length > 0 && complete.length > 0 ? 12 : 0 }}>
          <p style={{ color: 'var(--color-text-muted)', fontSize: '11px', fontWeight: 600, textTransform: 'uppercase', letterSpacing: '0.05em', margin: '0 0 8px' }}>
            Would help Jaspen know
          </p>
          <div className="jas-checklist">
            {pending.map(s => (
              <label className="jas-check-item" key={s.id}>
                <input type="checkbox" className="jas-check" checked={false} readOnly />
                <div className="jas-check-main">
                  <div className="jas-check-label" style={{ color: 'var(--color-text-muted)' }}>{s.label}</div>
                  {s.hint && (
                    <div className="jas-check-meta" style={{ marginTop: 2, fontSize: '12px', lineHeight: 1.4 }}>{s.hint}</div>
                  )}
                </div>
              </label>
            ))}
          </div>
        </div>
      )}
    </>
  );
};

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

const openWorkspaceRoute = useCallback((threadIdValue, artifactIdValue) => {
  const tid = String(threadIdValue || '').trim();
  const aid = String(artifactIdValue || '').trim();
  if (!tid || !aid) return false;
  const href = `/workspace/${encodeURIComponent(tid)}/${encodeURIComponent(aid)}`;
  window.open(href, '_blank', 'noopener,noreferrer');
  return true;
}, []);

const resolveWorkspaceScorecardId = useCallback(async (rawCard) => {
  const tid = String(sessionId || currentSessionId || '').trim();
  if (!tid || !rawCard || typeof rawCard !== 'object') return null;
  const directCandidates = [
    rawCard?.analysis_id,
    rawCard?.analysisId,
    rawCard?.id,
  ].map((value) => String(value || '').trim()).filter(Boolean);
  const title = String(
    rawCard?.display_overrides?.title
    || rawCard?.project_name
    || rawCard?.name
    || rawCard?.label
    || ''
  ).trim().toLowerCase();
  const score = Number(rawCard?.jaspen_score ?? rawCard?.score ?? NaN);

  const bundle = await Jaspen.fetchBundle(tid).catch(() => null);
  const snapshots = Array.isArray(bundle?.scorecard_snapshots) ? bundle.scorecard_snapshots : [];
  const pool = [
    ...snapshots,
    bundle?.current_scorecard,
    bundle?.baseline_scorecard,
  ].filter((entry) => entry && typeof entry === 'object');

  const byId = (value) => {
    const needle = String(value || '').trim();
    if (!needle) return null;
    return pool.find((entry) => (
      String(entry?.analysis_id || '').trim() === needle
      || String(entry?.id || '').trim() === needle
    )) || null;
  };
  for (const candidateId of directCandidates) {
    const match = byId(candidateId);
    if (match?.analysis_id || match?.id) {
      return String(match.analysis_id || match.id).trim();
    }
  }

  const byNameAndScore = pool.find((entry) => {
    const entryTitle = String(
      entry?.display_overrides?.title
      || entry?.project_name
      || entry?.name
      || entry?.label
      || ''
    ).trim().toLowerCase();
    const entryScore = Number(entry?.jaspen_score ?? entry?.score ?? NaN);
    if (!entryTitle || !title) return false;
    if (entryTitle !== title) return false;
    if (Number.isFinite(score) && Number.isFinite(entryScore)) return Math.abs(entryScore - score) <= 0.5;
    return true;
  });
  if (byNameAndScore?.analysis_id || byNameAndScore?.id) {
    return String(byNameAndScore.analysis_id || byNameAndScore.id).trim();
  }

  // If the exact card isn't persisted yet, fall back to a persisted card id
  // so workspace opens to a real artifact instead of a 404 shell.
  const persistedFallback = pool.find((entry) => (
    String(entry?.analysis_id || entry?.id || '').trim().length > 0
  ));
  if (persistedFallback?.analysis_id || persistedFallback?.id) {
    return String(persistedFallback.analysis_id || persistedFallback.id).trim();
  }

  return directCandidates[0] || null;
}, [currentSessionId, sessionId]);

const openWorkspaceScorecard = useCallback(async (rawCard, { closeArtifacts = false } = {}) => {
  const tid = String(sessionId || currentSessionId || '').trim();
  if (!tid || !rawCard || typeof rawCard !== 'object') return;
  if (closeArtifacts) setArtifactsOpen(false);
  const resolvedId = await resolveWorkspaceScorecardId(rawCard);
  if (!resolvedId) {
    showToast('Could not resolve this scorecard in workspace yet. Please retry in a moment.', 'error');
    return;
  }
  const opened = openWorkspaceRoute(tid, resolvedId);
  if (!opened) {
    showToast('Could not open this scorecard in workspace.', 'error');
  }
}, [currentSessionId, openWorkspaceRoute, resolveWorkspaceScorecardId, sessionId, showToast]);

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
      const allowed = ['jira_sync', 'salesforce_insights', 'snowflake_insights', 'servicenow_insights', 'netsuite_insights', 'oracle_fusion_insights'];
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
  if (connectorType === 'jira') {
    // Backend returns a pre-formatted context_text — use it directly
    if (typeof data?.context_text === 'string' && data.context_text.trim()) {
      return data.context_text;
    }
    const s = (data && typeof data.summary === 'object') ? data.summary : {};
    return (
      `Jira Project: ${s.project_key || 'unknown'}\n` +
      `Active sprint: ${s.sprint_issue_count || 0} issues | ` +
      `Blocked: ${s.blocked_count || 0} | ` +
      `Completed last 14d: ${s.done_last_14d || 0} | ` +
      `High-priority backlog: ${s.high_priority_backlog || 0}`
    );
  }
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
  if (connectorType === 'salesforce') {
    const summary = (data && typeof data.summary === 'object') ? data.summary : {};
    const records = Array.isArray(data?.records) ? data.records : [];
    const stageRows = Array.isArray(summary?.stage_breakdown) ? summary.stage_breakdown.slice(0, 8) : [];
    const stageText = stageRows.length
      ? stageRows.map((row) => `${row?.stage || 'Unknown'}: count=${Number(row?.count || 0)}, amount=${Number(row?.amount || 0)}`).join('\n')
      : 'No stage breakdown available.';
    const preview = records.slice(0, 25).map((row, i) => `Row ${i + 1}: ${JSON.stringify(row)}`).join('\n');
    const accountList = Array.isArray(summary?.accounts) ? summary.accounts : [];
    const accountsText = accountList.length
      ? accountList.slice(0, 50).join(', ')
      : 'No account names available.';
    return (
      `Source: Salesforce | Lookback days: ${Number(summary?.lookback_days || 90)}\n` +
      `Opportunity count: ${Number(summary?.opportunity_count || records.length)}\n` +
      `Open: ${Number(summary?.open_count || 0)} | Closed: ${Number(summary?.closed_count || 0)}\n` +
      `Total amount: ${Number(summary?.total_amount || 0)} | Weighted amount: ${Number(summary?.weighted_amount || 0)}\n` +
      `Accounts (${Number(summary?.account_count || accountList.length)}): ${accountsText}\n` +
      `Stage breakdown:\n${stageText}\n\n` +
      `DATA:\n${preview || 'No records returned.'}`
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
    if (connectorId === 'jira_sync') {
      url = `${API_BASE}/api/v1/connectors/jira/context/summary?limit=60`;
    } else if (connectorId === 'salesforce_insights') {
      url = `${API_BASE}/api/v1/connectors/salesforce/pipeline/summary?days=90&limit=100`;
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
    const sourceType = connectorId === 'jira_sync'
      ? 'jira'
      : connectorId === 'snowflake_insights'
        ? 'snowflake'
        : connectorId === 'salesforce_insights'
          ? 'salesforce'
          : 'generic';
    const summary = formatConnectorContextForAgent(data, sourceType).slice(0, MAX_CONNECTOR_CONTEXT_CHARS).trim();
    if (!summary) throw new Error(`No ${label} context available.`);
    setContextSourceData((prev) => ({ ...prev, [connectorId]: summary }));
    showToast(`${label} data loaded as context.`, 'success');
  } catch (err) {
    // Keep the pill visible — don't silently remove it. Store an error marker
    // so the pill shows an error state and the AI knows the fetch failed.
    const rawMsg = err?.message || `Could not load ${label} data.`;
    // Detect Salesforce reconnect-needed errors and show a helpful action
    const needsReconnect = /reconnect|refresh token|not connected/i.test(rawMsg) && connectorId === 'salesforce_insights';
    const errMsg = needsReconnect
      ? `Salesforce token expired — please reconnect in Data Sources.`
      : rawMsg;
    setContextSourceData((prev) => ({ ...prev, [connectorId]: `__error__:${errMsg}` }));
    showToast(
      errMsg,
      'error',
      needsReconnect ? { label: 'Reconnect', action: () => window.open('/connectors-manage', '_blank') } : undefined
    );
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

  const PM_TOOL_LABELS = {
    jaspen: 'Jaspen only',
    jira_sync: 'Jira',
    smartsheet_sync: 'Smartsheet',
  };
  try {
    const syncRes = await fetch(
      `${API_BASE}/api/v1/connectors/threads/${encodeURIComponent(tid)}/sync`,
      {
        method: 'GET',
        headers: buildAuthHeaders({}, 'GET'),
        credentials: 'include',
      }
    );
    const syncJson = await syncRes.json().catch(() => ({}));
    if (syncRes.ok) {
      const currentPreferred = String(syncJson?.preferred_pm_tool || '').trim().toLowerCase();
      if (!currentPreferred) {
        const availableTools = Array.isArray(syncJson?.available_pm_tools)
          ? syncJson.available_pm_tools
          : [];
        const eligibleTools = availableTools.filter((tool) => {
          const id = String(tool?.id || '').trim().toLowerCase();
          if (id === 'jaspen') return true;
          return Boolean(tool?.connected);
        });
        if (eligibleTools.length > 0) {
          const lines = eligibleTools.map((tool, idx) => {
            const id = String(tool?.id || '').trim().toLowerCase();
            const label = PM_TOOL_LABELS[id] || String(tool?.label || id);
            return `${idx + 1}. ${label}`;
          });
          const defaultIndex = Math.max(1, eligibleTools.findIndex((tool) => String(tool?.id || '').trim().toLowerCase() === 'jaspen') + 1);
          const selected = window.prompt(
            `Choose the PM tool for this initiative:\n${lines.join('\n')}\n\nEnter the option number:`,
            String(defaultIndex || 1)
          );
          if (selected === null) return;
          const selectedIndex = Number.parseInt(String(selected || '').trim(), 10);
          if (!Number.isFinite(selectedIndex) || selectedIndex < 1 || selectedIndex > eligibleTools.length) {
            showToast('Invalid PM tool selection. Please try Begin Project again.', 'error');
            return;
          }
          const chosenTool = String(eligibleTools[selectedIndex - 1]?.id || 'jaspen').trim().toLowerCase();
          const bindRes = await fetch(
            `${API_BASE}/api/v1/connectors/threads/${encodeURIComponent(tid)}/preferred-pm-tool`,
            {
              method: 'POST',
              headers: buildAuthHeaders({ 'Content-Type': 'application/json' }, 'POST'),
              credentials: 'include',
              body: JSON.stringify({ preferred_pm_tool: chosenTool }),
            }
          );
          const bindJson = await bindRes.json().catch(() => ({}));
          if (!bindRes.ok) {
            showToast(bindJson?.error || 'Unable to bind PM tool for this thread.', 'error');
            return;
          }
          showToast(`PM tool set to ${PM_TOOL_LABELS[chosenTool] || chosenTool}.`, 'success');
        }
      }
    }
  } catch (syncErr) {
    console.warn('[Begin Project] PM tool pre-bind check failed', syncErr);
  }

  const activeScenarioName = activeScenarioProjectLabel;
  const sourceLabel = activeScenarioName
    ? `${activeScenarioName} (Active)`
    : 'Current scorecard';
  const ok = window.confirm(
    `Build an execution plan based on: ${sourceLabel}?\n\n` +
    `Jaspen will generate a full project WBS from this scorecard context and open it on the Execution page.`
  );
  if (!ok) return;

  setBeginBusy(true);
  setBeginMsg('Building your project plan…');

  try {
    const activeScenarioId = String(activeScenarioForProject?.id || activeScenarioForProject?.analysis_id || '').trim() || null;
    const body = { commit: true };
    if (activeScenarioId) body.scenario_id = activeScenarioId;
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
      // Prefer the analysis result's canonical thread_id when available —
      // the current sessionId may be an orphan (e.g. created by a hard-reload)
      // whose bundle has no baseline, while the real data lives on the owner thread.
      const tid = analysisResult?.thread_id || currentSessionId || sessionId;
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
      setView('intake');
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
  // Auto-scoring: called when backend signals ready_to_analyze.
  // No busy guard, no navigation, no progress bar — scorecard appears inline in conversation.
  async function triggerInlineScore(sid) {
    if (!sid) return;
    console.log('[triggerInlineScore] calling analyzeFromConversation for', sid);

    // Inject a loading placeholder at the CURRENT end of the thread so the card
    // holds its position even if the user sends more messages while scoring runs.
    const loadingId = 'scorecard-loading';
    setMessages((prev) => {
      if (prev.some((m) => m.id === loadingId || m?.artifact?.type === 'scorecard' || m?.artifact?.type === 'scorecard-loading')) return prev;
      return [...prev, { id: loadingId, role: 'ai', text: '', artifact: { type: 'scorecard-loading' } }];
    });

    setScorecardGenerating(true);
    try {
      const data = await Jaspen.analyzeFromConversation({
        session_id: sid,
        model_type: selectedModelType,
      });
      console.log('[triggerInlineScore] response received', data);

      const raw = data?.analysis || data?.analysis_result || data || {};
      const scoreNum = Number.parseInt(Number(raw.overall_score || raw.jaspen_score || 0), 10);
      const score = Number.isFinite(scoreNum) ? scoreNum : 0;

      const result = {
        ...raw,
        jaspen_score: score,
        score_category: raw.score_category || (score >= 80 ? 'Excellent' : score >= 60 ? 'Good' : score >= 40 ? 'Fair' : 'At Risk'),
        component_scores: raw.scores || raw.component_scores || {},
        project_name: raw.name || raw.project_name || deriveIdeaTitle({ messages, fallback: 'Untitled Idea' }),
        analysis_id: sid,
        _createdAt: Date.now(),
      };

      if (!result._baseline_scorecard || typeof result._baseline_scorecard !== 'object') {
        result._baseline_scorecard = { ...result };
      }
      result.selected_scorecard_id = sid;

      // Replace the placeholder with the real scorecard card, in-place
      setMessages((prev) => prev.map((m) =>
        m.id === loadingId
          ? { id: 'scorecard-card', role: 'ai', text: '', artifact: { type: 'scorecard', data: result } }
          : m
      ));

      // Wire up scorecard state
      setAnalysisResult(result);
      const baselineSnapshot = { ...result._baseline_scorecard, id: sid, label: BASELINE_INTERNAL_LABEL, isBaseline: true, createdAt: Date.now() };
      setScorecardSnapshots([baselineSnapshot]);
      setSelectedScorecardId(sid);
      setBaselineScorecardId(sid);
      baselineRef.current = result._baseline_scorecard;

      // Background refresh — don't block the UI
      setTimeout(() => { void refreshBundle(sid); void fetchSessions(); }, 0);
    } catch (e) {
      console.error('[triggerInlineScore]', e);
      // Replace placeholder with an inline error message so the user can see what failed.
      setMessages((prev) => prev.map((m) =>
        m.id === loadingId
          ? {
              id: `${loadingId}-err`,
              role: 'ai',
              text: 'I had enough context to score this, but the analysis call failed. Tap regenerate to retry.',
            }
          : m
      ));
      showToast('Scoring failed. Try again or rephrase the idea.', 'error');
    } finally {
      setScorecardGenerating(false);
    }
  }

  // Trade-off intent: phrases where the user is explicitly asking to compare,
  // rank, or weigh multiple ideas against each other. The Trade-off tab only
  // unlocks when one of these fires (or when the user kicks off the session
  // with a batch "rank these" request).
  const TRADEOFF_SIGNALS = /\b(trade[-\s]?off|trade\s+offs?|compare\s+(these|them|the\s+(ideas?|scorecards?|options?|scenarios?|versions?))|comparison|side[-\s]?by[-\s]?side|head[-\s]?to[-\s]?head|rank\s+(these|them|the\s+(ideas?|scorecards?|options?|scenarios?|versions?))|stack[-\s]?rank|prioriti[sz]e\s+(these|them|the\s+(ideas?|scorecards?|options?|scenarios?))|which\s+(one\s+)?(is\s+)?(best|better|should\s+(i|we)\s+(pick|choose|do|prioriti[sz]e|go\s+with))|impact\s+(vs|versus|and)\s+effort|effort\s+(vs|versus|and)\s+impact|portfolio\s+(view|analysis)|show\s+(me\s+)?(the\s+)?trade[-\s]?off)\b/i;

  function detectsTradeoffIntent(userText = '') {
    return TRADEOFF_SIGNALS.test(String(userText));
  }

  // Creates a new scored version from the current conversation and appends it to snapshots.
  // Uses create_as_version=true so the backend saves it as a scenario — baseline session
  // result is NOT overwritten, so restoring from bundle always shows both baseline + versions.
  async function triggerAutoVersion(sid) {
    if (!sid || !analysisResult || autoVersionGenerating) return; // need an existing scorecard; guard re-entry

    // Inject a loading placeholder immediately so it holds position in the thread
    const loadingId = `scorecard-v-loading-${Date.now()}`;
    setMessages((prev) => [
      ...prev,
      { id: loadingId, role: 'ai', text: '', artifact: { type: 'scorecard-loading', label: 'Scoring your updated idea…' } },
    ]);

    setAutoVersionGenerating(true);
    try {
      // Score the current conversation state, saving as a scenario (not replacing the first)
      const data = await Jaspen.analyzeFromConversation({
        session_id: sid,
        model_type: selectedModelType,
        create_as_version: true,
      });

      const raw = data?.analysis || data?.analysis_result || data || {};
      const scoreNum = Number.parseInt(Number(raw.overall_score || raw.jaspen_score || 0), 10);
      const score = Number.isFinite(scoreNum) ? scoreNum : 0;

      // Use the AI-generated project name as the label
      const ideaName = raw.name || raw.project_name || deriveIdeaTitle({ messages, fallback: 'Untitled Idea' });
      const currentSnaps = Array.isArray(scorecardSnapshots) ? scorecardSnapshots : [];
      const snapNum = currentSnaps.length + 1;
      const versionId = raw.id || raw.analysis_id || `${sid}-s${snapNum}-${Date.now()}`;

      const newSnapshot = {
        ...raw,
        jaspen_score: score,
        score_category: raw.score_category || (score >= 80 ? 'Excellent' : score >= 60 ? 'Good' : score >= 40 ? 'Fair' : 'At Risk'),
        component_scores: raw.scores || raw.component_scores || {},
        project_name: ideaName,
        id: versionId,
        analysis_id: versionId,
        label: ideaName,
        isBaseline: false,
        createdAt: Date.now(),
      };

      // Append new snapshot — baseline stays, new one added after.
      setScorecardSnapshots((prev) => {
        const arr = Array.isArray(prev) ? prev : [];
        if (arr.some((s) => String(s?.id || '') === String(versionId))) return arr;
        return [...arr, newSnapshot];
      });

      // Replace placeholder with real scorecard card, in-place
      setMessages((prev) => prev.map((m) =>
        m.id === loadingId
          ? { id: `scorecard-v${snapNum}`, role: 'ai', text: '', artifact: { type: 'scorecard', data: newSnapshot } }
          : m
      ));

      showToast(`Scored ✓`, 'success');

      // Refresh bundle so the scenario persists and survives a hard reload
      setTimeout(() => { void refreshBundle(sid); void fetchSessions(); }, 0);
    } catch (e) {
      console.error('[triggerAutoVersion]', e);
      // Replace placeholder with an inline error message so the user can see what failed
      // and the conversation flow stays coherent.
      setMessages((prev) => prev.map((m) =>
        m.id === loadingId
          ? {
              id: `${loadingId}-err`,
              role: 'ai',
              text: 'I tried to score that variation but ran into an error. Tap the regenerate button or rephrase the change to try again.',
            }
          : m
      ));
      showToast('Could not score that variation. Try again.', 'error');
    } finally {
      setAutoVersionGenerating(false);
    }
  }

  // === Input handling ===
  async function onSubmit(options = {}) {
    const now = Date.now();
    if (!options?.force && now - (lastSendAtRef.current || 0) < 500) return;
    lastSendAtRef.current = now;

    const text = (options.text ?? input ?? '').trim();
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

    // Unlock the Trade-off tab the moment the user explicitly asks to compare
    // or rank ideas. Latches once true; reset on new session.
    if (!tradeoffRequested && text && detectsTradeoffIntent(text)) {
      setTradeoffRequested(true);
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
    const successfulContextIds = selectedContextIds.filter(
      (id) => contextSourceData[id] && !String(contextSourceData[id]).startsWith('__error__')
    );
    const activeContextParts = successfulContextIds.map((id) => {
      const source = connectedDataSources.find((item) => item.id === id);
      return `[${source?.label || id} Context]\n${contextSourceData[id]}`;
    });
    // Mark these sources as "used this session" — persists in context bar even after user removes from toolbar
    if (successfulContextIds.length > 0) {
      setUsedContextSourceIds((prev) => {
        const next = new Set(prev);
        successfulContextIds.forEach((id) => next.add(id));
        return next;
      });
    }
    const erroredSources = selectedContextIds.filter(
      (id) => typeof contextSourceData[id] === 'string' && contextSourceData[id].startsWith('__error__')
    );
    if (selectedContextIds.length > 0 && activeContextParts.length === 0 && erroredSources.length === 0) {
      showToast('Selected data context is still loading. Please wait a moment, then send again.', 'info');
      return;
    }
    if (erroredSources.length > 0) {
      const labels = erroredSources.map((id) => connectedDataSources.find((item) => item.id === id)?.label || id).join(', ');
      showToast(`${labels} data could not be loaded — sending without that context.`, 'warning');
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

  async function requestTradeoffFromInsights({ refresh = false } = {}) {
    const sid = sessionId || currentSessionId;
    if (!sid) {
      showToast('Start or continue a conversation first.', 'info');
      return;
    }
    if (busy || scorecardGenerating || autoVersionGenerating) return;
    const scored = Array.isArray(tradeoffEligibleScoredItems) ? tradeoffEligibleScoredItems : [];
    if (scored.length < 2) {
      showToast('Score at least two ideas before building a trade-off.', 'info');
      return;
    }
    const scoredSnapshots = scored
      .map((item) => (item?.data && typeof item.data === 'object' ? item.data : null))
      .filter((entry) => entry && hasMeaningfulScorecardData(entry) && entry?.display_overrides?.tradeoff_included !== false);
    if (scoredSnapshots.length < 2) {
      showToast('Need at least two included scored ideas to build a trade-off.', 'info');
      return;
    }
    const scopedIdeas = scored
      .map((item, idx) => `${idx + 1}. ${item.label} (id: ${item.id}, score: ${Math.round(item.score)}/100)`)
      .join('\n');
    const prompt = refresh
      ? `Update the trade-off comparison using all currently scored ideas in this conversation.\n\nUse generate_tradeoff_comparison with the listed ideas. Do not generate or regenerate any scorecards.\n${scopedIdeas}`
      : `Generate a trade-off comparison using all currently scored ideas in this conversation.\n\nUse generate_tradeoff_comparison with the listed ideas. Do not generate or regenerate any scorecards.\n${scopedIdeas}`;
    setActivePill('scenarios');
    setTradeoffRequested(true);
    await onSubmit({ text: prompt, force: true });
  }

  function onKey(e) {
    const commandSend = e.key === 'Enter' && (e.metaKey || e.ctrlKey);
    const standardSend = e.key === 'Enter' && !e.shiftKey;
    if (commandSend || standardSend) {
      e.preventDefault();
      onSubmit();
    }
  }

  // Record uploaded files in the session-uploads tracker. Dedupes by
  // name+size so re-selecting the same file doesn't create duplicate entries.
  function registerSessionUploads(items) {
    const list = (Array.isArray(items) ? items : []).filter((f) => f && f.name);
    if (!list.length) return;
    setSessionUploads((prev) => {
      const seen = new Set(prev.map((f) => `${f.name}::${f.size ?? ''}`));
      const additions = list
        .filter((f) => !seen.has(`${f.name}::${f.size ?? ''}`))
        .map((f) => ({
          name: f.name,
          size: f.size ?? null,
          type: f.type || 'application/octet-stream',
          uploadedAt: new Date().toISOString(),
        }));
      const next = additions.length ? [...prev, ...additions] : prev;
      // Persist per-thread so uploads survive a hard refresh. Non-image/PDF/Word
      // files (e.g. .md, .csv) aren't stored as message attachments by the
      // backend, so localStorage is the only thing that rehydrates them.
      persistSessionUploads(next);
      return next;
    });
  }

  // localStorage helpers for upload persistence, keyed by the active thread id.
  function sessionUploadsStorageKey(id) {
    const tid = String(id || sessionId || currentSessionId || '').trim();
    return tid ? `jas_session_uploads_${tid}` : '';
  }
  function persistSessionUploads(listToSave, id) {
    const key = sessionUploadsStorageKey(id);
    if (!key) return;
    try {
      localStorage.setItem(key, JSON.stringify(Array.isArray(listToSave) ? listToSave : []));
    } catch {}
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
    // Attach-first UX: a selected/dropped file is added as a chip and waits for
    // the user to type an instruction, then send — matching the standard agent
    // pattern. We intentionally do NOT auto-submit/auto-analyze on drop, so the
    // user controls what happens with the file. Also record it in the session
    // uploads tracker so it's distinguishable from agent-created artifacts.
    setPendingFiles((prev) => [...prev, ...toAdd]);
    registerSessionUploads(toAdd);
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
      { key: 'execution_readiness',    label: 'Execution Confidence',    val: comps.execution_readiness ?? comps.executionReadiness ?? comps.readiness ?? comps.team ?? 0 },
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
      (analysisResult ? { ...analysisResult, id: baselineId, label: BASELINE_INTERNAL_LABEL, isBaseline: true } : null);

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
      if (s.id === baselineId) return { ...s, isBaseline: true, label: s.label || BASELINE_INTERNAL_LABEL };
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
  if (!tid) {
    showToast('No active session. Please refresh this thread and try again.', 'error');
    return;
  }
  if (aiWbsBusy) return;

  const scenarioId = (scorecardId && baselineScorecardId && scorecardId !== baselineScorecardId)
    ? scorecardId
    : null;

  setAiWbsBusy(true);
  // Track per-card busy so the matching scorecard's button shows "Building…"
  setBuildingExecutionPlanFor(scorecardId || tid);
  try {
    const resp = await Jaspen.generateAiWbs(tid, {
      scenario_id: scenarioId,
      scorecard_id: scorecardId || null,
      commit: true,
      prompt: 'Generate a recommended project WBS from this scorecard.',
      model_type: selectedModelType,
    });
    const wbsPayload = (
      (resp?.project_wbs && typeof resp.project_wbs === 'object') ? resp.project_wbs
      : ((resp?.wbs && typeof resp.wbs === 'object') ? resp.wbs : null)
    );
    const taskCount = Array.isArray(wbsPayload?.tasks) ? wbsPayload.tasks.length : 0;
    // Persist the new WBS to local state so the Execution tab unlocks
    // immediately without a reload.
    if (wbsPayload && typeof wbsPayload === 'object') {
      setThreadWbs(wbsPayload);
    }
    // Inject an inline execution artifact anchored at this exact generation point.
    setMessages((prev) => [
      ...prev,
      {
        role: 'ai',
        text: `Built an execution plan with ${taskCount} task${taskCount === 1 ? '' : 's'}. It's ready in the Execution tab — or open it directly in Workspace.`,
        artifact: {
          type: 'execution_plan',
          data: wbsPayload || { tasks: [] },
        },
      },
    ]);
    showToast('Execution plan built · open Execution tab', 'success');
    // Also unlock and switch to the Execution pill for immediate feedback.
    setActivePill('execution');
  } catch (err) {
    console.error('[handleGenerateAiWbsFromScorecard] failed', err);
    if (err?.status === 403) setBillingModalOpen(true);
    showToast(err?.message || 'Failed to build execution plan', 'error');
  } finally {
    setAiWbsBusy(false);
    setBuildingExecutionPlanFor(null);
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
    const industryKey = String(selection?.industry || '').trim().toLowerCase();
    const companySizeKey = String(selection?.company_size || '').trim().toLowerCase();
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
      industry: industryKey || 'other',
      company_size: companySizeKey || '51_500',
      startMode: startMode || 'conversation',
    };
    const nextContext = buildOnboardingIntakeContext(nextSelection);
    setPendingOnboardingContext(nextContext);
    setOnboardingInitialSelection(nextSelection);
    setGuidedFlowDismissed(false);
    writeGuidedFlowDismissed(user, false);
    writeOnboardingState(user, { completed: true, deferred: false, selection: nextSelection });
    void persistOnboardingProfileState({ completed: true, deferred: false, selection: nextSelection });
    dismissNotification(SETUP_REMINDER_NOTIFICATION.id);
    if (onboardingMode === 'settings') {
      const activeThreadId = String(currentSessionId || sessionId || '').trim();
      if (activeThreadId) {
        void Jaspen.setThreadIntakeContext(activeThreadId, {
          ...nextContext,
          objective: OBJECTIVE_LABEL_BY_KEY[mappedObjective] || OBJECTIVE_LABEL_BY_KEY.balanced,
        }, mappedObjective, nextExplicit).catch((err) => {
          console.error('[handleOnboardingComplete] intake context sync failed', err);
          showToast('Saved locally, but could not sync onboarding context to this thread yet.', 'warning');
        });
      }
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
  }, [user, onboardingMode, sessionId, currentSessionId, messages, showToast, dismissNotification, persistOnboardingProfileState, buildOnboardingIntakeContext]);

  const handleNewAnalysis = useCallback((forceNew = false) => {
    clearLastSessionId();
    setView('intake');
    setSessionId(null);
    setCurrentSessionId(null);
    setMessages([]);
    setInput('');
    setPendingFiles([]);
    setSessionUploads([]);
    setBusy(false);
    setAnalysisResult(null);
    setTradeoffRequested(false);
    setError(null);
    setSavedScenarios([]);
    setCollectedData({});
    setKnowledgeSignals(null);
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
    setView('intake');
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

    return;
  }

// Completed session -> workspace summary (prefer the persisted result blob)
try {
  const id = resolvedActiveThreadId;

  setSessionId(id);
  setLastSessionId(id);
  const bundleHistory = Array.isArray(bundle?.messages)
    ? bundle.messages.map((m) => toHistoryMessageShape(m))
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
  setView('intake');
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

  // Delete a session — returns { ok, status, body } so callers can react to
  // failures instead of swallowing the error silently. Pass { hard: true }
  // to permanently purge (skips the 30-day grace window).
  const deleteAnalysisById = async (itemId, { hard = false } = {}) => {
    try {
      const url = `${API_BASE}/api/v1/ai-agent/threads/${encodeURIComponent(itemId)}${hard ? '?hard=1' : ''}`;
      const resp = await authFetch(url, {
        method: 'DELETE',
        headers: buildAuthHeaders({}, 'DELETE'),
        credentials: 'include',
      });
      const status = resp?.status;
      let body = null;
      try { body = await resp.json(); } catch (_) { /* may be empty */ }
      return { ok: resp?.ok === true, status, body };
    } catch (error) {
      console.error('Error deleting session from backend:', error);
      return { ok: false, status: 0, body: { error: String(error?.message || error) } };
    }
  };

  // Restore a soft-deleted session (used by the Undo toast action).
  const restoreAnalysisById = async (itemId) => {
    try {
      const resp = await authFetch(`${API_BASE}/api/v1/ai-agent/threads/${encodeURIComponent(itemId)}/restore`, {
        method: 'POST',
        headers: buildAuthHeaders({}, 'POST'),
        credentials: 'include',
      });
      return resp?.ok === true;
    } catch (error) {
      console.error('Error restoring session:', error);
      return false;
    }
  };

  // Performs the actual delete after the user confirms (or after the opt-out
  // path skips the dialog). Pulled out so both flows hit the same code.
  const performDeleteAnalysis = useCallback(async (itemId) => {
    setAnalysisHistory((prev) => prev.filter((it) => String(it?.id || '') !== String(itemId)));
    const result = await deleteAnalysisById(itemId, { hard: true });
    if (!result.ok) {
      showToast(`Couldn't delete: ${result.body?.error || `HTTP ${result.status || '?'}`}`, 'error');
      await fetchSessions();
      return;
    }
    const wasActive = String(currentSessionId || sessionId || '') === String(itemId);
    if (wasActive) {
      clearLastSessionId();
      setSessionId(null);
      setCurrentSessionId(null);
      setAnalysisResult(null);
      setMessages([]);
      setTradeoffRequested(false);
      setView('intake');
    }
    await fetchSessions();
    showToast('Session deleted', 'success');
  }, [currentSessionId, sessionId, showToast]); // eslint-disable-line react-hooks/exhaustive-deps

  // Checkbox state for the delete-confirm dialog. Pulled out of the
  // confirmDialog state object so the onConfirm closure can read the latest
  // value directly from the ref — no stale-closure bugs under React
  // batching. The useState mirror is just so the checkbox visually flips
  // when the user clicks it.
  const deleteCheckboxRef = useRef(false);
  const [deleteCheckboxOpen, setDeleteCheckboxOpen] = useState(false);

  const handleDeleteAnalysis = (itemId) => {
    if (!itemId) return;
    const entry = analysisHistory.find((item) => String(item?.id || '').trim() === String(itemId).trim());
    const label = (entry?.name || entry?.title || entry?.result?.project_name || 'this analysis').trim();

    const skipConfirm = Boolean(skipDeleteConfirmWS)
      || Boolean(user?.ui_preferences?.skip_delete_confirm)
      || (typeof localStorage !== 'undefined' && localStorage.getItem('jaspen.skipDeleteConfirm') === '1');

    if (skipConfirm) {
      void performDeleteAnalysis(itemId);
      return;
    }

    // Reset checkbox state before opening the dialog.
    deleteCheckboxRef.current = false;
    setDeleteCheckboxOpen(false);

    // Same setConfirmDialog pattern handleClearHistory uses (which works).
    // Onconfirm reads the checkbox from a ref so there's no closure issue.
    setConfirmDialog({
      title: `Delete "${label}"?`,
      message: "This permanently removes the session and its chat history. Anonymized scores (no idea text) stay in your org's benchmarking ledger. This cannot be undone.",
      confirmLabel: 'Delete',
      confirmVariant: 'danger',
      checkboxLabel: "Don't ask me again",
      onConfirm: async () => {
        // Persist the opt-out BEFORE delete so the next click goes through.
        if (deleteCheckboxRef.current && !skipDeleteConfirmWS) {
          await toggleSkipDeleteConfirm();
        }
        await performDeleteAnalysis(itemId);
      },
    });
  };

  // Permanent purge — separate from soft-delete. Skips the 30-day grace
  // window and anonymizes the org ledger row. Exposed via the Settings →
  // Archived sessions drawer (TBD) for now.
  const handlePurgeAnalysis = async (itemId) => {
    if (!itemId) return;
    const entry = analysisHistory.find((item) => String(item?.id || '').trim() === String(itemId).trim());
    const label = (entry?.name || entry?.title || entry?.result?.project_name || 'this analysis').trim();

    setConfirmDialog({
      title: 'Purge permanently',
      message: `Permanently purge "${label}"? This removes the session AND anonymizes its ledger row — your org will no longer benchmark against this idea. Cannot be undone.`,
      confirmLabel: 'Purge permanently',
      confirmVariant: 'danger',
      onConfirm: async () => {
        setAnalysisHistory((prev) => prev.filter((it) => String(it?.id || '') !== String(itemId)));
        const result = await deleteAnalysisById(itemId, { hard: true });
        if (!result.ok) {
          showToast(`Couldn't purge: ${result.body?.error || `HTTP ${result.status || '?'}`}`, 'error');
          await fetchSessions();
          return;
        }
        const wasActive = String(currentSessionId || sessionId || '') === String(itemId);
        if (wasActive) {
          clearLastSessionId();
          setSessionId(null);
          setCurrentSessionId(null);
          setAnalysisResult(null);
          setMessages([]);
          setTradeoffRequested(false);
          setView('intake');
        }
        await fetchSessions();
        showToast('Session purged', 'success');
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
            setTradeoffRequested(false);
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
  setView('intake');
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
    setView('intake');
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
            label: formatScorecardLabel(
              snap.label,
              { isBaseline: Boolean(snap?.isBaseline), fallback: `Scorecard ${idx + 1}` }
            ),
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
      ? (
        snapshotOptions.find((option) => option.id === resolvedScoreSelectValue)?.label ||
        snapshotOptions[0]?.label ||
        BASELINE_DISPLAY_LABEL
      )
      : formatScorecardLabel(
        scoreVariants.find((variant) => variant.id === scoreSelectValue)?.label,
        { fallback: BASELINE_DISPLAY_LABEL }
      );
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

      {/* Scorecard lightbox: dark backdrop, scorecard at larger size, with
          per-artifact actions (Download is wired to print-to-PDF). */}
      {lightboxScorecard && (
        <div
          className="jas-lightbox-backdrop"
          role="dialog"
          aria-modal="true"
          aria-label="Scorecard"
          onClick={() => setLightboxScorecard(null)}
          style={{
            position: 'fixed', inset: 0, zIndex: 1000,
            background: 'rgba(8, 14, 28, 0.78)',
            display: 'flex', alignItems: 'center', justifyContent: 'center',
            padding: '40px 24px', overflow: 'auto',
          }}
        >
          <div
            className="jas-lightbox-card"
            onClick={(e) => e.stopPropagation()}
            style={{
              background: '#fff', borderRadius: 14, maxWidth: 900, width: '100%',
              maxHeight: 'calc(100vh - 80px)', overflow: 'auto',
              boxShadow: '0 20px 60px rgba(0,0,0,0.45)', position: 'relative',
            }}
          >
            <button
              type="button"
              aria-label="Close"
              onClick={() => setLightboxScorecard(null)}
              style={{
                position: 'absolute', top: 12, right: 12, zIndex: 2,
                width: 32, height: 32, borderRadius: 16, border: 'none',
                background: '#f1f5f9', color: '#0f172a', cursor: 'pointer',
                display: 'flex', alignItems: 'center', justifyContent: 'center',
                fontSize: 16,
              }}
            >
              <FontAwesomeIcon icon={faTimes} />
            </button>
            <div style={{ padding: 24 }}>
              {renderScorecardCard(lightboxScorecard, {
                lightbox: true,
                threadId: sessionId || currentSessionId,
                messages,
                onBuildExecutionPlan: (cid) => {
                  setLightboxScorecard(null);
                  void handleGenerateAiWbsFromScorecard({ threadBundleId: sessionId || currentSessionId, scorecardId: cid });
                },
                buildingExecutionPlanFor,
              })}
            </div>
            <div
              style={{
                padding: '12px 24px', borderTop: '1px solid #e6eaf2',
                display: 'flex', gap: 8, justifyContent: 'flex-end',
                background: '#fafbfc',
              }}
            >
              <button
                type="button"
                className="jas-mini-btn"
                onClick={() => window.print()}
                style={{
                  padding: '8px 14px', borderRadius: 8,
                  border: '1px solid #d6dce6', background: '#fff', cursor: 'pointer',
                  fontSize: 13, color: '#0f172a',
                }}
              >
                <FontAwesomeIcon icon={faDownload} style={{ marginRight: 6 }} />
                Download as PDF
              </button>
              <button
                type="button"
                className="jas-mini-btn"
                onClick={() => setLightboxScorecard(null)}
                style={{
                  padding: '8px 14px', borderRadius: 8, border: 'none',
                  background: '#0f172a', color: '#fff', cursor: 'pointer',
                  fontSize: 13,
                }}
              >
                Close
              </button>
            </div>
          </div>
        </div>
      )}

      <ConfirmDialog
        isOpen={Boolean(confirmDialog)}
        title={confirmDialog?.title || 'Confirm action'}
        message={confirmDialog?.message || 'Are you sure you want to continue?'}
        confirmLabel={confirmDialog?.confirmLabel || 'Confirm'}
        confirmVariant={confirmDialog?.confirmVariant || 'danger'}
        checkboxLabel={confirmDialog?.checkboxLabel || null}
        checkboxChecked={deleteCheckboxOpen}
        onCheckboxChange={(next) => {
          // Mirror to both ref (read by onConfirm) and state (drives UI).
          deleteCheckboxRef.current = Boolean(next);
          setDeleteCheckboxOpen(Boolean(next));
        }}
        onConfirm={async () => {
          // Same shape as handleClearHistory's working flow — capture the
          // handler reference, clear the dialog, then run the handler. The
          // handler reads the checkbox from deleteCheckboxRef so there's no
          // stale-closure concern.
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
    renderMessage={(m) => renderConversationMessage(m, {
      autoVersionGenerating,
      threadId: sessionId || currentSessionId,
      messages,
      onBuildExecutionPlan: (cid) => void handleGenerateAiWbsFromScorecard({ threadBundleId: sessionId || currentSessionId, scorecardId: cid }),
      buildingExecutionPlanFor,
      onOpenWorkspaceScorecard: (scorecard) => openWorkspaceScorecard(scorecard),
      onOpenWorkspaceRoute: (threadIdValue, artifactIdValue) => openWorkspaceRoute(threadIdValue, artifactIdValue),
    })}
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
        threadMode="strategy"
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
                    onClick={() => navigate('/account?tab=billing')}
                  >
                    Add credits
                  </button>
                  <button
                    type="button"
                    className="jas-low-credits-banner-link"
                    onClick={() => navigate('/account?tab=plans')}
                  >
                    Upgrade plan
                  </button>
                  <button
                    type="button"
                    className="jas-low-credits-banner-dismiss"
                    onClick={dismissLowCreditsBanner}
                    aria-label="Dismiss low thinking power reminder"
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
              <TabButton id="scenario" label="Trade-off" />

              {/* Scorecard dropdown rail — shown only on Scenarios tab for project actions */}
              {activeTab === 'scenario' && (
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
                                {formatScorecardLabel(option.label, { isBaseline: Boolean(option.isBaseline) || option.id === 'baseline' })}
                                {option.isBaseline
                                  ? (isBaselineLikeLabel(option.label) ? '' : ` (${BASELINE_DISPLAY_LABEL})`)
                                  : option.isActive ? ' (Active)' : ''}
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
{/* Score dashboard removed — scorecard renders inline in the conversation thread */}

            {activeTab === 'scenario' && (
              <TradeoffView
                scorecardSnapshots={scorecardSnapshots}
                strategyObjective={strategyObjective}
                portfolioAnalysis={null}
                onAsk={(text) => {
                  setActiveTab('summary');
                  void onSubmit({ text });
                }}
                asking={busy}
                threadId={sessionId || currentSessionId}
              />
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

  // Score dashboard removed — scorecard lives inline in the conversation thread.
  // Scenarios shell still available when explicitly on scenario tab.
  if (analysisResult && activeTab === 'scenario') {
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
  const intakeShellOpen = sidebarState.history || sidebarState.settings;
  const intakeHasReadinessTab = sessionId && messages.length > 0 && !sidebarState.readiness;
  const showIntakeTopbarUtilities = !sessionId && messages.length === 0;
  const showTopbarCredits = Boolean(user) && !hideThinkingPowerMeter;
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
  // readiness tab removed — info lives in Jaspen Insights panel
  const intakeSideTabBase = 128;
  const intakeSideTabGap = 46;
  const intakeTabTop = (key) => {
    const idx = intakeTabs.indexOf(key);
    return `${intakeSideTabBase + idx * intakeSideTabGap}px`;
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
        </button>
      )}
      {hasHistory && !sidebarState.history && (
        <button
          type="button"
          className="jas-drawer-tab jas-drawer-tab-history"
          style={{ top: intakeTabTop('history') }}
          onClick={() => dispatchSidebar({ type: 'TOGGLE_HISTORY' })}
          aria-label="Open session history"
          aria-expanded={sidebarState.history}
          aria-controls="jas-intake-history-panel"
        >
          <FontAwesomeIcon icon={faClockRotateLeft} />
        </button>
      )}
      {/* Readiness sidebar removed — info lives in Jaspen Insights panel */}

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
                    onClick={(e) => {
                      e.preventDefault();
                      e.stopPropagation();
                      console.log('[history delete] clicked for', item.id);
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

      {/* Row 1: Title bar — session title · notifications · credits */}
      <div className="jas-titlebar">
        {sessionId && (
          <div className="jas-titlebar-left" style={{ flex: 1, minWidth: 0 }}>
            <span className="jas-project-title">
              {deriveIdeaTitle({ messages, fallback: '' })}
            </span>
          </div>
        )}
        {!sessionId && <div className="jas-titlebar-left" />}

        <div className="jas-titlebar-right">
          {showIntakeTopbarUtilities && (
            <button
              type="button"
              className="jas-topbar-bell"
              onClick={() => { setNotificationsMode('bell'); setNotificationsOpen(true); }}
              title="Notifications"
              aria-label="Open notifications"
            >
              <FontAwesomeIcon icon={faBell} />
              {unreadNotificationCount > 0 && (
                <span className="jas-topbar-bell-count">{unreadNotificationCount}</span>
              )}
            </button>
          )}
          {showTopbarCredits && (
            <button
              type="button"
              className={`jas-topbar-credits jas-credits-${creditsLevel}${creditsLevel === 'critical' ? ' jas-credits-pulse' : ''}`}
              onClick={() => setBillingModalOpen(true)}
              title={creditsTitle}
              aria-label="View thinking power usage"
            >
              <FontAwesomeIcon icon={faBolt} />
              {intakeCreditsCompactLabel && <span>{intakeCreditsCompactLabel}</span>}
            </button>
          )}
        </div>
      </div>

      {/* Row 2: Stage pills + objective */}
      <div className="jas-context-bar">
        <div className="jas-context-left">
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
          <div className="jas-context-divider" aria-hidden="true" />

          {/* Artifacts button — left of Discovery */}
          {sessionId && (
            <div className="jas-artifacts-wrap">
              <button
                className={`jas-artifacts-btn${artifactsOpen ? ' open' : ''}`}
                onClick={() => setArtifactsOpen(o => !o)}
                title="Session artifacts"
                aria-label="Toggle session artifacts"
              >
                <FontAwesomeIcon icon={faLayerGroup} />
              </button>
              {artifactsOpen && (
                <div className="jas-artifacts-dropdown" role="menu">
                  <p className="jas-artifacts-label">Session Artifacts</p>
                  {/* Each scorecard is its own artifact. Clicking opens the
                      lightbox modal so the user can view it large and (later)
                      download / share / export from there. */}
                  {(() => {
                    const messageScorecards = (Array.isArray(displayMessages) ? displayMessages : [])
                      .filter((entry) => String(entry?.artifact?.type || '').trim() === 'scorecard')
                      .map((entry) => entry?.artifact?.data)
                      .filter((entry) => hasMeaningfulScorecardData(entry));
                    // UNION every scorecard source so all scored ideas appear
                    // (parity with the right-panel "Scored Ideas" list). Previously
                    // this OR-fell-back to snapshots only when zero message
                    // scorecards existed, which under-counted: a single message
                    // artifact would hide 2–3 other scored ideas. Dedupe by a
                    // stable key (analysis_id / id / created_at).
                    const _cardKey = (c) => String(
                      c?.analysis_id || c?.id
                      || c?.createdAt || c?._createdAt || c?.created_at
                      || ''
                    ).trim();
                    const _mergeCards = (...sources) => {
                      const seen = new Set();
                      const out = [];
                      sources.forEach((src) => {
                        (Array.isArray(src) ? src : []).forEach((c) => {
                          if (!hasMeaningfulScorecardData(c)) return;
                          const k = _cardKey(c);
                          // When no stable key, fall back to identity so we don't
                          // collapse genuinely distinct unkeyed cards together.
                          const dedupeKey = k || `__noKey_${out.length}`;
                          if (seen.has(dedupeKey)) return;
                          seen.add(dedupeKey);
                          out.push(c);
                        });
                      });
                      return out;
                    };
                    let allCards = _mergeCards(messageScorecards, scorecardSnapshots);
                    if (allCards.length === 0 && analysisResult) {
                      allCards = [analysisResult];
                    }
                    // Each scorecard stands on its own. Use the AI-generated
                    // project name. Disambiguate only when multiple cards share
                    // the SAME name (different iterations of the same idea) →
                    // suffix them v1, v2, v3 in chronological order.
                    const ordered = [...allCards].sort((a, b) => {
                      const ta = Date.parse(a?.createdAt || a?._createdAt || a?.created_at || '');
                      const tb = Date.parse(b?.createdAt || b?._createdAt || b?.created_at || '');
                      if (Number.isFinite(ta) && Number.isFinite(tb)) return ta - tb;
                      return 0;
                    });

                    // Each scorecard gets its OWN idea name. Resolution order:
                    //   1. User-edited title from Workspace overrides
                    //   2. AI-generated name field on the scorecard
                    //   3. project_name / label / initiative_name (legit values)
                    //   4. The user message that triggered THIS scorecard —
                    //      every scoring round is preceded by "Building your
                    //      scorecard now." in the AI chat, and a user message
                    //      describing the idea just before that.
                    //   5. The first user message of the session (oldest fallback)
                    // Generic placeholders are stripped. Also strip the
                    // backend's auto-generated "Version N" labels for legacy
                    // variations — we'll regenerate vN suffixes ourselves
                    // based on grouping by parent idea.
                    const _BANNED = new Set([
                      'baseline analysis', 'baseline', 'jaspen project', 'jaspen analysis',
                      'strategy analysis', 'initiative', 'untitled', 'untitled idea', 'project',
                    ]);
                    const _BANNED_PATTERNS = [/^version\s+\d+$/i, /^v\d+$/i, /^scenario\s+[a-z]$/i];
                    const _pickName = (s) => {
                      const v = String(s || '').trim();
                      if (!v) return null;
                      if (_BANNED.has(v.toLowerCase())) return null;
                      if (_BANNED_PATTERNS.some((re) => re.test(v))) return null;
                      return v;
                    };
                    // Reuse deriveIdeaTitle's logic (handles prefix stripping,
                    // first-sentence pick, and the 7-word natural-break cap).
                    const _snippetFromMsg = (text) => {
                      if (!text) return null;
                      const derived = deriveIdeaTitle({
                        result: null,
                        messages: [{ role: 'user', text: String(text) }],
                        fallback: '',
                      });
                      return derived || null;
                    };

                    // Build chronological maps of: triggers in the AI chat,
                    // and the user message that preceded each trigger.
                    const triggerRegex = /building your scorecard|scorecard now|generating your scorecard|scoring your idea/i;
                    const triggeringUserMsgByIdx = [];
                    const msgs = Array.isArray(messages) ? messages : [];
                    msgs.forEach((m, i) => {
                      if (m?.role === 'ai' && typeof m?.text === 'string' && triggerRegex.test(m.text)) {
                        let lastUser = null;
                        for (let j = i - 1; j >= 0; j--) {
                          if (msgs[j]?.role === 'user' && String(msgs[j]?.text || '').trim()) {
                            lastUser = msgs[j].text;
                            break;
                          }
                        }
                        triggeringUserMsgByIdx.push(lastUser);
                      }
                    });

                    const firstUserMsg = msgs.find(
                      (m) => m?.role === 'user' && String(m?.text || '').trim()
                    )?.text;

                    const sessionFallback = _pickName(_snippetFromMsg(firstUserMsg))
                      || 'Untitled idea';

                    // The "anchor idea name" is the meaningful name on the
                    // baseline (or the first card if no baseline marker), used
                    // as the shared label for all variations of that idea.
                    const anchorIdeaName = (() => {
                      const baseline = ordered.find((c) => c?.isBaseline) || ordered[0];
                      return (
                        _pickName(baseline?.display_overrides?.title)
                          || _pickName(baseline?.name)
                          || _pickName(baseline?.project_name)
                          || _pickName(baseline?.initiative_name)
                          || _pickName(_snippetFromMsg(triggeringUserMsgByIdx[0]))
                          || sessionFallback
                      );
                    })();

                    // For each card, prefer its OWN distinct name if the AI
                    // gave it one (a genuinely different idea). Otherwise
                    // collapse to the shared anchor name so v1/v2/v3 grouping
                    // works as the user expects.
                    const nameOf = (c, idx) => {
                      // A card has its own name only if it's NOT a baseline
                      // and the AI generated a meaningful, different name.
                      const ownName = _pickName(c?.display_overrides?.title)
                        || _pickName(c?.name)
                        || _pickName(c?.project_name)
                        || _pickName(c?.initiative_name);
                      if (ownName && ownName.toLowerCase() !== anchorIdeaName.toLowerCase()) {
                        return _capTitleSmart(ownName);
                      }
                      return _capTitleSmart(anchorIdeaName);
                    };
                    // Count occurrences of each name to know whether to
                    // attach v1/v2/v3 suffixes. When a name appears more than
                    // once → show v1, v2, v3... on every instance (not just
                    // the 2nd+). When unique → no suffix.
                    const nameCounts = {};
                    ordered.forEach((c, i) => {
                      const n = nameOf(c, i);
                      nameCounts[n] = (nameCounts[n] || 0) + 1;
                    });
                    const nameRunning = {};
                    const enriched = ordered.map((c, i) => {
                      const n = nameOf(c, i);
                      nameRunning[n] = (nameRunning[n] || 0) + 1;
                      const showVersion = nameCounts[n] > 1;
                      return {
                        card: c,
                        label: showVersion ? `${_capTitleSmart(n)} · v${nameRunning[n]}` : _capTitleSmart(n),
                      };
                    });

                    return enriched.map(({ card, label }, idx) => {
                      const score = Number(card?.jaspen_score || 0);
                      const cardId = card?.analysis_id || card?.id || `art-${idx}`;
                      return (
                        <div key={cardId} className="jas-artifact-row">
                          <button
                            className="jas-artifact-item"
                            onClick={() => { setLightboxScorecard(card); setArtifactsOpen(false); }}
                            title={`Preview ${label}`}
                          >
                            <FontAwesomeIcon icon={faGaugeHigh} />
                            <span>{label} · {score}/100</span>
                          </button>
                          {sessionId && (
                            <button
                              className="jas-artifact-ws-link"
                              type="button"
                              onClick={() => { void openWorkspaceScorecard(card, { closeArtifacts: true }); }}
                              title="Edit in Workspace (opens in new tab)"
                              style={{
                                fontSize:11, color:'#475569', padding:'4px 8px', borderRadius:6,
                                textDecoration:'none', whiteSpace:'nowrap', border:'none', background:'transparent', cursor:'pointer',
                              }}
                            >
                              Edit ↗
                            </button>
                          )}
                        </div>
                      );
                    });
                  })()}
                  {/* Trade-off artifact — surface whenever the user has at
                      least two scorecards to compare. The pill gating is now
                      "always available once a scorecard exists", but for the
                      artifact list we still want ≥2 since you can't compare
                      a single idea against itself. */}
                  {(hasTradeoffArtifact || (Array.isArray(scorecardSnapshots) && scorecardSnapshots.length >= 2)) && (
                    <div className="jas-artifact-row">
                      <button
                        className="jas-artifact-item"
                        onClick={() => { setActivePill('scenarios'); setArtifactsOpen(false); }}
                        title="Open the Trade-off comparison view"
                      >
                        <FontAwesomeIcon icon={faArrowRightArrowLeft} />
                        <span>Trade-off · {tradeoffEligibleScoredItems.length} ideas</span>
                      </button>
                      {sessionId && (
                        <button
                          className="jas-artifact-ws-link"
                          type="button"
                          onClick={() => { setArtifactsOpen(false); openWorkspaceRoute(sessionId, '__tradeoff__'); }}
                          title="Edit Trade-off in Workspace (opens in new tab) — coming soon in beta"
                          style={{ fontSize:11, color:'#475569', padding:'4px 8px', borderRadius:6, textDecoration:'none', whiteSpace:'nowrap', border:'none', background:'transparent', cursor:'pointer' }}
                        >
                          Edit ↗
                        </button>
                      )}
                    </div>
                  )}
                  {/* Execution Plan artifact */}
                  {Array.isArray(threadWbs?.tasks) && threadWbs.tasks.length > 0 && (
                    <div className="jas-artifact-row">
                      <button
                        className="jas-artifact-item"
                        onClick={() => { setActivePill('execution'); setArtifactsOpen(false); }}
                        title="Open the Execution Plan"
                      >
                        <FontAwesomeIcon icon={faListCheck} />
                        <span>Execution Plan · {threadWbs.tasks.length} tasks</span>
                      </button>
                      {sessionId && (
                        <button
                          className="jas-artifact-ws-link"
                          type="button"
                          onClick={() => { setArtifactsOpen(false); openWorkspaceRoute(sessionId, '__execution__'); }}
                          title="Edit Execution Plan in Workspace (opens in new tab) — coming soon in beta"
                          style={{ fontSize:11, color:'#475569', padding:'4px 8px', borderRadius:6, textDecoration:'none', whiteSpace:'nowrap', border:'none', background:'transparent', cursor:'pointer' }}
                        >
                          Edit ↗
                        </button>
                      )}
                    </div>
                  )}
                  {!analysisResult
                    && (!Array.isArray(scorecardSnapshots) || scorecardSnapshots.length === 0)
                    && !(Array.isArray(displayMessages) && displayMessages.some((entry) => entry?.artifact))
                    && !hasTradeoffArtifact
                    && !(Array.isArray(threadWbs?.tasks) && threadWbs.tasks.length > 0) && (
                    <p className="jas-artifacts-empty">No artifacts yet</p>
                  )}
                </div>
              )}
            </div>
          )}

          {/* Session Uploads button — mirrors the artifacts button and is
              ALWAYS visible (even when empty) so users know where their shared
              files live. Lists files the USER uploaded, distinct from artifacts
              Jaspen created. The list unions persisted message attachments
              (reload-safe) with in-memory pending uploads (shown the instant a
              file is attached, before it's sent). */}
          {sessionId && (() => {
            const seen = new Set();
            const uploads = [];
            const addUpload = (name, size) => {
              const nm = String(name || '').trim();
              if (!nm) return;
              const key = `${nm}::${size ?? ''}`;
              if (seen.has(key)) return;
              seen.add(key);
              uploads.push({ name: nm, size: Number.isFinite(size) ? size : null });
            };
            (Array.isArray(messages) ? messages : []).forEach((m) => {
              if (m?.role !== 'user') return;
              (Array.isArray(m?.attachments) ? m.attachments : []).forEach((a) => {
                addUpload(a?.name, a?.size);
              });
            });
            (Array.isArray(sessionUploads) ? sessionUploads : []).forEach((f) => {
              addUpload(f?.name, f?.size);
            });
            return (
              <div className="jas-artifacts-wrap">
                <button
                  className={`jas-artifacts-btn${uploadsOpen ? ' open' : ''}`}
                  onClick={() => setUploadsOpen((o) => !o)}
                  title="Session uploads"
                  aria-label="Toggle session uploads"
                >
                  <FontAwesomeIcon icon={faFolder} />
                </button>
                {uploadsOpen && (
                  <div className="jas-artifacts-dropdown" role="menu">
                    <p className="jas-artifacts-label">Session Uploads</p>
                    {uploads.length > 0 ? (
                      uploads.map((f, i) => (
                        <div className="jas-artifact-row" key={`${f.name}-${i}`}>
                          <div
                            className="jas-artifact-item jas-artifact-item--upload"
                            title={`Uploaded by you${f.size ? ` · ${Math.max(1, Math.round(f.size / 1024))} KB` : ''}`}
                          >
                            <FontAwesomeIcon icon={faFolder} />
                            <span>{f.name}</span>
                          </div>
                        </div>
                      ))
                    ) : (
                      <p className="jas-artifacts-empty">No uploads yet</p>
                    )}
                  </div>
                )}
              </div>
            );
          })()}

          <div className="jas-context-stages">
            {(() => {
              // Only the CURRENT stage is highlighted
              const currentStage = activePill || (
                (Array.isArray(scorecardSnapshots) && scorecardSnapshots.length > 0) || analysisResult
                  ? 'scoring'
                  : 'discovery'
              );
              // Trade-off is available for the whole session once the user has
              // any scorecard — they shouldn't lose access after building an
              // execution plan or refreshing. `tradeoffRequested` still gates
              // whether the inline comparison auto-renders in the chat thread.
              const artifactScorecardsCount = (Array.isArray(displayMessages) ? displayMessages : []).filter((entry) => (
                String(entry?.artifact?.type || '').trim() === 'scorecard'
                && hasMeaningfulScorecardData(entry?.artifact?.data)
              )).length;
              const scoredIdeasCount = Math.max(
                Array.isArray(scorecardSnapshots) && scorecardSnapshots.length > 0
                  ? scorecardSnapshots.length
                  : 0,
                analysisResult ? 1 : 0,
                artifactScorecardsCount
              );
              const canScoring = scoredIdeasCount >= 1;
              const canScenarios = scoredIdeasCount >= 2;
              const hasExecutionPlan = Array.isArray(threadWbs?.tasks) && threadWbs.tasks.length > 0;
              const canExecution = hasExecutionPlan;
              const stages = [
                { key: 'discovery',  label: 'Discovery',  disabled: false },
                { key: 'scoring',    label: 'Scoring',    disabled: !canScoring },
                { key: 'scenarios',  label: 'Trade-off',  disabled: !canScenarios,
                  title: !canScenarios
                    ? 'Create at least two scorecards to compare in Trade-off'
                    : undefined },
                { key: 'execution',  label: 'Execution',  disabled: !canExecution,
                  title: !canExecution
                    ? 'Build an execution plan from a scorecard first'
                    : undefined },
              ];
              // Everything stays inline — no setActiveTab navigation
              const handlePillClick = (key, disabled) => {
                if (disabled) return;
                setActivePill(key);
              };
              return stages.map((stage, i, arr) => (
                <React.Fragment key={stage.key}>
                  <button
                    className={`jas-stage-pill${currentStage === stage.key ? ' active' : ''}${stage.disabled ? ' disabled' : ''}`}
                    onClick={() => handlePillClick(stage.key, stage.disabled)}
                    disabled={stage.disabled}
                    title={stage.disabled ? (stage.title || 'Not available yet') : undefined}
                  >
                    {stage.label}
                  </button>
                  {i < arr.length - 1 && <span className="jas-stage-sep" aria-hidden="true">›</span>}
                </React.Fragment>
              ));
            })()}
          </div>
        </div>

        <div className="jas-context-right">
          {(objectiveExplicitlySet || sessionId) && (
            <span className="jas-context-pill" title={`Session objective: ${OBJECTIVE_LABEL_BY_KEY[strategyObjective] || 'Balanced'}`}>
              {OBJECTIVE_LABEL_BY_KEY[strategyObjective] || 'Balanced'}
            </span>
          )}
          {Array.isArray(connectedDataSources) && (() => {
            // Show ALL sources that were actually used this session. We union two
            // signals so the chips survive a page reload (usedContextSourceIds is
            // in-memory only and resets on refresh):
            //   1. usedContextSourceIds — live, set when a context send succeeds.
            //   2. Message history — every context-attached send writes a
            //      "[Data context attached: <labels>]" marker into the user
            //      message, which is persisted/reloaded with the thread. We scan
            //      those markers and map the labels back to source ids.
            const usedIds = new Set(usedContextSourceIds);
            const markerRe = /\[Data context attached:\s*([^\]]+)\]/gi;
            (Array.isArray(messages) ? messages : []).forEach((m) => {
              const txt = typeof m?.text === 'string' ? m.text : '';
              if (!txt) return;
              let match;
              while ((match = markerRe.exec(txt)) !== null) {
                String(match[1] || '')
                  .split(',')
                  .map((s) => s.trim().toLowerCase())
                  .filter(Boolean)
                  .forEach((label) => {
                    const hit = connectedDataSources.find(
                      (src) => String(src.label || '').trim().toLowerCase() === label
                        || String(src.id || '').trim().toLowerCase() === label
                    );
                    if (hit) usedIds.add(hit.id);
                  });
              }
            });
            const usedSrcs = connectedDataSources.filter((src) => usedIds.has(src.id));
            if (usedSrcs.length === 0) return null;
            return (
              <>
                <span className="jas-context-divider" aria-hidden="true" />
                {usedSrcs.map((src) => (
                  <span
                    key={src.id}
                    className="jas-context-pill jas-context-pill-used"
                    title={`${src.label} data was used in this session`}
                  >
                    {src.label}
                  </span>
                ))}
              </>
            );
          })()}
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
      <div
        id="jas-main-content"
        className={`jas-chat-content${messages.length > 0 && !insightsCollapsed ? ' has-insights-panel' : ''}${messages.length > 0 && insightsCollapsed ? ' has-insights-panel-collapsed' : ''}`}
      >
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
            {/* Single conversation surface for every stage. Trade-off and
                Execution used to swap the whole panel out for full-page
                views with their own chat input — that broke the mental
                model (users had to know to navigate back to Discovery to
                see chat replies). Now both are inline artifacts that pin
                to the bottom of the conversation when their pill is
                active. One chat input, always at the bottom. */}
            <div className="jas-messages">
              {error && (
                <div className="agent-chat-error">
                  <FontAwesomeIcon icon={faExclamationTriangle} />
                  <span>{error}</span>
                </div>
              )}

	              {displayMessages.map((m, idx) => (
	                <div key={m.id || idx} className={`jas-message ${m.role === 'ai' ? 'ai' : 'user'}`}>
	                  <div className="jas-message-bubble">{renderConversationMessage(m, {
                    autoVersionGenerating,
                    threadId: sessionId || currentSessionId,
                    messages,
                    onBuildExecutionPlan: (cid) => void handleGenerateAiWbsFromScorecard({ threadBundleId: sessionId || currentSessionId, scorecardId: cid }),
                    buildingExecutionPlanFor,
                    onOpenWorkspaceScorecard: (scorecard) => openWorkspaceScorecard(scorecard),
                    onOpenWorkspaceRoute: (threadIdValue, artifactIdValue) => openWorkspaceRoute(threadIdValue, artifactIdValue),
                  })}</div>
	                  {renderMessageAttachments(m)}
	                  {renderMessageActions(m, `main:${idx}`, idx, displayMessages.length)}
	                </div>
	              ))}

              {/* The pills (Discovery / Scoring / Trade-off / Execution) no
                  longer swap the conversation panel content. They only
                  change which Insights the right sidebar emphasizes. The
                  Trade-off table and Execution canvas live in Workspace
                  (Open in Workspace from any scorecard); inline artifacts
                  for both are TBD. The chat is the single source of truth. */}

              {/* Scorecard loading states are now rendered inline as placeholder messages
                  in the messages array (scorecard-loading artifact type), so the card
                  always holds its correct position in the thread even if the user
                  sends follow-up messages while scoring is in progress. */}

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
                  onClick={() => { void handleToggleMic(); }}
                >
                  <FontAwesomeIcon icon={faMicrophone} />
                </button>
                {/* Stop button replaces Send while a stream is in flight.
                    Click cancels the AbortController so the user isn't stuck
                    watching a slow / unwanted reply finish. */}
                {(busy || isStreamingReply) ? (
                  <button
                    className="jas-ci-btn send"
                    onClick={stopActiveStream}
                    title="Stop"
                    aria-label="Stop the in-flight reply"
                    style={{ background: '#a0036c' }}
                  >
                    <span style={{ width: 12, height: 12, background: '#fff', borderRadius: 2, display: 'inline-block' }} />
                  </button>
                ) : (
                  <button
                    className="jas-ci-btn send"
                    onClick={onSubmit}
                    disabled={effectiveIsViewer || (!input.trim() && pendingFiles.length === 0)}
                    aria-disabled={effectiveIsViewer || (!input.trim() && pendingFiles.length === 0)}
                    title="Send"
                  >
                    <FontAwesomeIcon icon={faArrowUp} />
                  </button>
                )}
              </div>
            </div>
          </div>

          {renderObjectiveTags('jas-chat-objective-tags')}
          {renderConnectorContextTags()}

          {/* Finish & Analyze footer removed — scoring triggered via Jaspen Insights panel CTA */}
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

        {/* Jaspen Insights Panel — collapses to a thin rail to free up
            real estate for the main canvas. State persists in localStorage. */}
        {messages.length > 0 && insightsCollapsed && (
          <aside
            className="jas-insights-panel jas-insights-panel--collapsed"
            aria-label="Jaspen Insights (collapsed)"
          >
            <button
              type="button"
              className="jas-insights-collapse-btn"
              onClick={toggleInsightsCollapsed}
              title="Expand Jaspen Insights"
              aria-label="Expand Jaspen Insights"
              aria-expanded="false"
            >
              <FontAwesomeIcon icon={faChevronLeft} />
            </button>
            <div className="jas-insights-rail-dot" aria-hidden="true" />
            <div
              className="jas-insights-rail-label"
              aria-hidden="true"
              title="Click to expand"
            >
              JASPEN INSIGHTS
            </div>
          </aside>
        )}
        {messages.length > 0 && !insightsCollapsed && (
          <aside className="jas-insights-panel" aria-label="Jaspen Insights">
            <div className="jas-insights-header">
              <span className="jas-insights-dot" aria-hidden="true" />
              <span className="jas-insights-title">Jaspen Insights</span>
              <button
                type="button"
                className="jas-insights-collapse-btn jas-insights-collapse-btn--inline"
                onClick={toggleInsightsCollapsed}
                title="Collapse panel"
                aria-label="Collapse Jaspen Insights"
                aria-expanded="true"
              >
                <FontAwesomeIcon icon={faChevronRight} />
              </button>
            </div>

            {/* ── Top cards: Confidence always shown; Score stacks below once scorecard exists ── */}
            <div className="jas-insights-confidence">
              {(() => {
                const displayConfidence = Number.isFinite(insightsConfidenceSource) ? insightsConfidenceSource : uiReadiness;
                const topGaps = (collectedSignals || []).filter((signal) => !signal.complete).slice(0, 3);
                return (
                  <>
                    {activePill === 'scoring' && Math.round(displayConfidence) < 80 && topGaps.length > 0 && (
                      <div className="jas-insights-score-flat" style={{ marginBottom: 10 }}>
                        <span className="jas-insights-score-flat-label">To reach 80% confidence</span>
                        <div style={{ fontSize: '0.72rem', color: 'var(--gray-700)', lineHeight: 1.45 }}>
                          Provide:
                          {' '}
                          {topGaps.map((signal) => signal.label).join(', ')}
                        </div>
                      </div>
                    )}
                    {scorecardGenerating ? (
                      <div className="jas-insights-score-flat">
                        <span className="jas-insights-score-flat-label">Building scorecard…</span>
                        <div className="jas-insights-readiness">
                          <div className="jas-insights-readiness-bar">
                            <div className="jas-insights-readiness-fill jas-readiness-fill--pulse" style={{ width: '100%', background: '#161f3b' }} />
                          </div>
                          <span className="jas-insights-score-flat-val">{Math.round(displayConfidence)}% confident</span>
                        </div>
                      </div>
                    ) : (canAnalyze && !analysisResult) ? (
                      <div className="jas-insights-score-flat">
                        <span className="jas-insights-score-flat-label">Ready for more context</span>
                        <div className="jas-insights-readiness">
                          <div className="jas-insights-readiness-bar">
                            <div className="jas-insights-readiness-fill" style={{ width: `${displayConfidence}%`, background: '#161f3b' }} />
                          </div>
                          <span className="jas-insights-score-flat-val">{Math.round(displayConfidence)}% confident</span>
                        </div>
                      </div>
                    ) : (
                      <div className="jas-insights-score-flat">
                        <span className="jas-insights-score-flat-label">{sessionId ? 'Confidence' : 'Getting started'}</span>
                        <div className="jas-insights-readiness">
                          <div className="jas-insights-readiness-bar">
                            <div className="jas-insights-readiness-fill" style={{ width: `${displayConfidence}%`, background: '#161f3b' }} />
                          </div>
                          <span className="jas-insights-score-flat-val">{Math.round(displayConfidence)}%</span>
                        </div>
                      </div>
                    )}
                  </>
                );
              })()}

              {/* Score row — stacks below confidence once scorecard exists */}
              {insightsScoreSource && (() => {
                const rawScoreCandidates = [
                  insightsScoreSource?.jaspen_score,
                  insightsScoreSource?.score,
                ];
                const resolvedRawScore = rawScoreCandidates.find((candidate) => (
                  candidate !== undefined
                  && candidate !== null
                  && String(candidate).trim() !== ''
                  && !Number.isNaN(Number(candidate))
                ));
                const scoreValue = resolvedRawScore === undefined ? 0 : Number(resolvedRawScore);
                return (
                <div className="jas-insights-score-flat" style={{ marginTop: 10 }}>
                  <span className="jas-insights-score-flat-label">Score</span>
                  <div className="jas-insights-readiness">
                    <div className="jas-insights-readiness-bar">
                      <div className="jas-insights-readiness-fill" style={{ width: `${Math.max(0, Math.min(100, scoreValue))}%`, background: '#161f3b' }} />
                    </div>
                    <span className="jas-insights-score-flat-val">{Math.round(scoreValue)} / 100</span>
                  </div>
                </div>
                );
              })()}
            </div>

            {/* ── Dynamic content per pill (driven by header stage pills) ── */}
            <div className="jas-insights-body">

              {/* Discovery: What Jaspen knows checklist + improvement coaching */}
              {activePill === 'discovery' && sessionId && (
                <div className="jas-insights-checklist">
                  {renderCollectedSignals()}
                  {/* Dynamic coaching: surface actionable gap hints */}
                  {(() => {
                    const gaps = (collectedSignals || []).filter(s => !s.complete && s.hint);
                    if (gaps.length === 0) return null;
                    return (
                      <div className="jas-insights-coaching" style={{ marginTop: 14, paddingTop: 12, borderTop: '1px solid var(--border)' }}>
                        <p className="jas-insights-tips-label" style={{ marginBottom: 8 }}>How to improve confidence</p>
                        {gaps.slice(0, 3).map(g => (
                          <div key={g.id} className="jas-insights-coaching-item" style={{ marginBottom: 10 }}>
                            <p style={{ fontSize: '0.72rem', fontWeight: 600, color: 'var(--gray-700)', marginBottom: 2 }}>{g.label}</p>
                            <p style={{ fontSize: '0.71rem', color: 'var(--gray-500)', lineHeight: 1.45 }}>{g.hint}</p>
                          </div>
                        ))}
                      </div>
                    );
                  })()}
                </div>
              )}

              {/* Scoring: dimension rationales + improvement coaching */}
              {activePill === 'scoring' && insightsScoreSource && (() => {
                const scoreSource = insightsScoreSource || {};
                const scoredItems = Array.isArray(scoredIdeaInsights?.items) ? scoredIdeaInsights.items : [];
                const dimensions = scoreSource?.dimensions || {};
                const componentScores = scoreSource?.component_scores || scoreSource?.scores || {};
                const firstRisk = Array.isArray(scoreSource?.top_risks) && scoreSource.top_risks.length > 0
                  ? (typeof scoreSource.top_risks[0] === 'string'
                    ? scoreSource.top_risks[0]
                    : (scoreSource.top_risks[0]?.risk || scoreSource.top_risks[0]?.text || ''))
                  : '';
                const dimensionDefs = [
                  { key: 'strategic_alignment', label: 'Strategic Fit', tip: 'Clarify how this aligns with your top strategic priorities.' },
                  { key: 'financial_viability', label: 'Cost Efficiency', tip: 'Provide budget guardrails, ROI targets, and payback thresholds.' },
                  { key: 'execution_readiness', label: 'Time-to-Value', tip: 'Provide team capacity, timeline constraints, and owner bandwidth.' },
                  { key: 'risk_profile', label: 'Execution Risk', tip: 'Provide dependency risks, failure modes, and mitigation options.' },
                  { key: 'market_opportunity', label: 'Market Opportunity', tip: 'Provide TAM/SAM assumptions, win-rate data, and competitor context.' },
                  { key: 'evidence_quality', label: 'Evidence Quality', tip: 'Provide supporting data, benchmarks, and historical performance evidence.' },
                ];

                const toInsightSummary = (label, score, rationale, tip) => {
                  if (rationale && String(rationale).trim()) return String(rationale).trim();
                  const normalized = Number.isFinite(score) ? score : 0;
                  const tenth = (normalized / 10).toFixed(1);
                  let band = 'is uncertain';
                  if (normalized >= 80) band = 'is strong';
                  else if (normalized >= 65) band = 'is solid with room to tighten';
                  else if (normalized >= 50) band = 'is moderate and needs more evidence';
                  else band = 'is weak and needs better grounding';
                  return `${label} is ${tenth}/10 and ${band}. ${tip}`;
                };

                const rows = dimensionDefs
                  .map(({ key, label, tip }) => {
                    const dim = dimensions[key] || {};
                    const score = Number(dim?.score ?? componentScores?.[key] ?? 0);
                    const rationale = dim?.rationale || dim?.summary || dim?.insight || dim?.explanation || '';
                    const improve = dim?.what_would_improve || tip;
                    if (!Number.isFinite(score) || score <= 0) return null;
                    return { key, label, score, rationale, improve };
                  })
                  .filter(Boolean);

                return (
                  <div className="jas-insights-dim-insights">
                    {scoredItems.length > 0 && (
                      <div className="jas-insights-score-summary">
                        <p className="jas-insights-tips-label" style={{ marginBottom: 8 }}>
                          Scored ideas · {scoredItems.length}
                        </p>
                        <div className="jas-insights-score-summary-list">
                          {scoredItems.map((item, idx) => {
                            const rowId = String(item?.id || '').trim();
                            const selectedId = String(effectiveSelectedScorecardId || '').trim();
                            const rowData = item?.data || {};
                            const rowIds = [
                              rowId,
                              rowData?.id,
                              rowData?.analysis_id,
                              rowData?.analysisId,
                            ].map((value) => String(value || '').trim()).filter(Boolean);
                            const isSelected = Boolean(selectedId && rowIds.includes(selectedId));
                            return (
                            <button
                              key={item?.id || `score-item-${idx}`}
                              type="button"
                              className={`jas-insights-score-summary-row${isSelected ? ' is-selected' : ''}`}
                              onClick={() => {
                                if (!rowId) return;
                                setSelectedScorecardId(rowId);
                              }}
                            >
                              <span className="jas-insights-score-summary-name">{item?.label || `Scorecard ${idx + 1}`}</span>
                              <span className="jas-insights-score-summary-val">
                                {Number.isFinite(item?.score) ? `${Math.round(item.score)}/100` : '—'}
                                {' · '}
                                {Number.isFinite(item?.confidence) ? `${Math.round(item.confidence)}% conf` : 'conf —'}
                              </span>
                            </button>
                          );})}
                        </div>
                        {scoredItems.length > 1 && (
                          <div className="jas-insights-score-summary-meta">
                            {Number.isFinite(scoredIdeaInsights?.averageScore) && (
                              <span>Avg score {scoredIdeaInsights.averageScore}/100</span>
                            )}
                            {scoredIdeaInsights?.highest?.label && Number.isFinite(scoredIdeaInsights?.highest?.score) && (
                              <span>Top idea: {scoredIdeaInsights.highest.label} ({Math.round(scoredIdeaInsights.highest.score)}/100)</span>
                            )}
                            {Number.isFinite(scoredIdeaInsights?.averageConfidence) && (
                              <span>Avg confidence {Math.round(scoredIdeaInsights.averageConfidence)}%</span>
                            )}
                          </div>
                        )}
                      </div>
                    )}
                    <p className="jas-insights-tips-label" style={{ marginBottom: 8 }}>Dimension Insights</p>
                    {rows.map(({ key, label, score, rationale, improve }) => {
                      const color = score >= 80 ? '#16a34a' : score >= 60 ? '#2563eb' : score >= 40 ? '#d97706' : '#dc2626';
                      const isWeak = score < 60;
                      const summary = toInsightSummary(label, score, rationale, improve);
                      return (
                        <div key={key} className="jas-insights-dim-row">
                          <div style={{ display: 'flex', alignItems: 'baseline', gap: 6 }}>
                            <span className="jas-insights-dim-name">{label}</span>
                            <span className="jas-insights-dim-score-badge" style={{ color }}>{(score / 10).toFixed(1)}/10</span>
                          </div>
                          <p className="jas-insights-dim-rationale">{summary}</p>
                          {isWeak && (
                            <p style={{ fontSize: '0.7rem', color: '#d97706', marginTop: 4, lineHeight: 1.4, fontStyle: 'italic' }}>
                              Improve next: {improve}
                            </p>
                          )}
                        </div>
                      );
                    })}
                    <div style={{ marginTop: 14, paddingTop: 12, borderTop: '1px solid var(--border)' }}>
                      {firstRisk ? (
                        <p style={{ fontSize: '0.72rem', color: 'var(--gray-600)', lineHeight: 1.45 }}>
                          Biggest current risk driver: {firstRisk}
                        </p>
                      ) : (
                        <p style={{ fontSize: '0.72rem', color: 'var(--gray-500)', lineHeight: 1.45, fontStyle: 'italic' }}>
                          Ask Jaspen to model a change and it will recommend what evidence to provide next.
                        </p>
                      )}
                    </div>
                  </div>
                );
              })()}

              {/* Trade-off: scored ideas summary list */}
              {activePill === 'scenarios' && tradeoffEligibleScoredItems.length >= 2 && (
                <div>
                  <p className="jas-insights-tips-label" style={{ marginBottom: 8 }}>
                    Scored ideas · {tradeoffEligibleScoredItems.length}
                  </p>
                  {tradeoffEligibleScoredItems.length > 0 ? (() => {
                    const scoredItems = tradeoffEligibleScoredItems;
                    const firstScore = Number(scoredItems[0]?.score ?? 0);
                    return scoredItems.map((snap, i) => {
                      const s = snap?.score ?? null;
                      const delta = (i > 0 && s !== null) ? Number(s) - firstScore : null;
                      const deltaColor = delta > 0 ? '#16a34a' : delta < 0 ? '#dc2626' : '#6b7280';
                      const displayLabel = snap?.label && !isBaselineLikeLabel(snap.label)
                        ? snap.label
                        : `Scorecard ${i + 1}`;
                      return (
                        <div key={snap?.id || i} className="jas-insights-scenario-row">
                          <span className="jas-insights-scenario-label">{displayLabel}</span>
                          <span style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                            <span className="jas-insights-scenario-score">{s ?? '—'}<span style={{ fontWeight: 400, color: 'var(--gray-400)' }}>/100</span></span>
                            {delta !== null && (
                              <span style={{ fontSize: '0.68rem', fontWeight: 600, color: deltaColor }}>
                                {delta > 0 ? `+${delta}` : delta}
                              </span>
                            )}
                          </span>
                        </div>
                      );
                    });
                  })() : (
                    <p style={{ fontSize: '0.73rem', color: 'var(--gray-500)', fontStyle: 'italic', marginBottom: 8 }}>
                      Score an idea to start comparing. Ask Jaspen to model a change and it will suggest scoring a new one.
                    </p>
                  )}
                  {/* The trade-off builds and refreshes automatically as ideas
                      are scored — no manual trigger. Show a passive status note
                      instead of a button. */}
                  <div className="jas-insights-tradeoff-cta">
                    <p style={{ fontSize: '0.71rem', color: 'var(--gray-500)', lineHeight: 1.45, marginTop: 10, fontStyle: 'italic' }}>
                      {busy || scorecardGenerating || autoVersionGenerating
                        ? 'Updating the trade-off…'
                        : 'This trade-off updates automatically as you score new ideas.'}
                    </p>
                  </div>
                </div>
              )}

              {/* Execution: recommendations */}
              {activePill === 'execution' && analysisResult && (() => {
                const planTasks = Array.isArray(threadWbs?.tasks) ? threadWbs.tasks : [];
                const total = planTasks.length;
                const done = planTasks.filter((t) => String(t?.status || '').toLowerCase() === 'done').length;
                const blocked = planTasks.filter((t) => String(t?.status || '').toLowerCase() === 'blocked').length;
                const inProgress = planTasks.filter((t) => {
                  const s = String(t?.status || '').toLowerCase();
                  return s === 'in_progress' || s === 'inprogress';
                }).length;
                // Plan completion as confidence proxy when no scorecard
                // confidence exists; otherwise reuse the scorecard's score.
                const planConfidence = total > 0 ? Math.round((done / total) * 100) : Math.round(uiReadiness);

                const risks = Array.isArray(analysisResult?.top_risks) ? analysisResult.top_risks : [];
                const recommendations = Array.isArray(analysisResult?.recommendations) ? analysisResult.recommendations : [];

                // Blocked task list (full, with owner) — only when any exist.
                const blockedTasks = planTasks
                  .filter((t) => String(t?.status || '').toLowerCase() === 'blocked')
                  .slice(0, 4);

                // Upcoming: next 4 tasks by due date that aren't done.
                const parseTs = (v) => {
                  const t = Date.parse(String(v || ''));
                  return Number.isFinite(t) ? t : Number.MAX_SAFE_INTEGER;
                };
                const upcoming = planTasks
                  .filter((t) => {
                    const s = String(t?.status || '').toLowerCase();
                    return s !== 'done' && t?.due_date;
                  })
                  .sort((a, b) => parseTs(a.due_date) - parseTs(b.due_date))
                  .slice(0, 4);

                // Owner workload (for quick action suggestion)
                const ownerCounts = new Map();
                planTasks.forEach((t) => {
                  const n = String(t?.owner || t?.suggested_role || '').trim();
                  if (n) ownerCounts.set(n, (ownerCounts.get(n) || 0) + 1);
                });
                const railOwners = Array.from(ownerCounts.entries())
                  .map(([name, count]) => ({ name, count }));

                // Quick AI-prompt chips — operational, not philosophical
                const quickActions = [];
                if (blocked > 0) quickActions.push(`Un-block the ${blocked} stalled task${blocked === 1 ? '' : 's'}`);
                if (inProgress > 3) quickActions.push('Push everything by 1 week — too much in flight');
                if (total > 0 && railOwners.length > 0) {
                  const heaviest = railOwners.slice().sort((a, b) => b.count - a.count)[0];
                  if (heaviest && heaviest.count >= 4) quickActions.push(`Rebalance — ${heaviest.name.split(/\s+/)[0]} has ${heaviest.count} tasks`);
                }
                if (quickActions.length === 0 && total > 0) {
                  quickActions.push('Regenerate the plan with a tighter timeline');
                }

                return (
                  <>
                    {/* Plan confidence */}
                    {total > 0 && (
                      <div style={{ marginBottom: 18 }}>
                        <p className="jas-insights-tips-label" style={{ marginBottom: 10 }}>Plan progress</p>
                        <div style={{ display: 'flex', alignItems: 'flex-end', gap: 12 }}>
                          <div style={{ fontFamily: 'JetBrains Mono, monospace', fontSize: 32, fontWeight: 600, color: '#161f3b', lineHeight: 0.95 }}>
                            {planConfidence}<span style={{ fontSize: 15, color: '#8a93ad', fontWeight: 500 }}>%</span>
                          </div>
                          <div style={{ flex: 1, paddingBottom: 3 }}>
                            <div style={{ height: 6, background: '#dfe7f1', borderRadius: 6, overflow: 'hidden' }}>
                              <div style={{ width: `${planConfidence}%`, height: '100%', background: '#a0036c' }} />
                            </div>
                            <div style={{ fontSize: 10.5, color: '#8a93ad', marginTop: 5 }}>
                              <span style={{ fontFamily: 'JetBrains Mono, monospace', color: '#5a6585' }}>{done}</span> done · <span style={{ fontFamily: 'JetBrains Mono, monospace', color: '#5a6585' }}>{inProgress}</span> in flight{blocked > 0 ? <> · <span style={{ fontFamily: 'JetBrains Mono, monospace', color: '#92590b' }}>{blocked}</span> blocked</> : null}
                            </div>
                          </div>
                        </div>
                      </div>
                    )}

                    {/* Blocked items — the most pressing thing during execution */}
                    {blockedTasks.length > 0 && (
                      <div style={{ marginBottom: 18 }}>
                        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 8 }}>
                          <p className="jas-insights-tips-label" style={{ margin: 0 }}>Blocked</p>
                          <span style={{ fontFamily: 'JetBrains Mono, monospace', fontSize: 9.5, color: '#92590b' }}>
                            {blockedTasks.length}
                          </span>
                        </div>
                        <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
                          {blockedTasks.map((t) => (
                            <div
                              key={t.id}
                              style={{
                                padding: '8px 10px', background: '#fff',
                                border: '1px solid #fcd9b8', borderLeft: '3px solid #f59e0b',
                                borderRadius: 6,
                              }}
                            >
                              <div style={{ fontSize: 12, color: '#161f3b', fontWeight: 500, lineHeight: 1.35 }}>
                                {t.title || 'Untitled task'}
                              </div>
                              {(t.owner || t.suggested_role) && (
                                <div style={{ fontSize: 10.5, color: '#8a93ad', marginTop: 3 }}>
                                  {t.owner || t.suggested_role}
                                </div>
                              )}
                            </div>
                          ))}
                        </div>
                      </div>
                    )}

                    {/* Upcoming due dates */}
                    {upcoming.length > 0 && (
                      <div style={{ marginBottom: 18 }}>
                        <p className="jas-insights-tips-label" style={{ marginBottom: 8 }}>Upcoming</p>
                        <div style={{ display: 'flex', flexDirection: 'column' }}>
                          {upcoming.map((t, i) => (
                            <div
                              key={t.id || i}
                              style={{
                                display: 'grid',
                                gridTemplateColumns: 'minmax(0, 1fr) auto',
                                gap: 10, alignItems: 'center',
                                padding: '8px 0',
                                borderBottom: i < upcoming.length - 1 ? '1px solid var(--border)' : 'none',
                              }}
                            >
                              <div style={{ minWidth: 0 }}>
                                <div style={{ fontSize: 12, color: '#161f3b', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                                  {t.title || 'Untitled task'}
                                </div>
                                <div style={{ fontSize: 10.5, color: '#8a93ad', marginTop: 2 }}>
                                  {t.owner || t.suggested_role || 'Unassigned'}
                                </div>
                              </div>
                              <span style={{ fontFamily: 'JetBrains Mono, monospace', fontSize: 11, color: '#5a6585', whiteSpace: 'nowrap' }}>
                                {t.due_date}
                              </span>
                            </div>
                          ))}
                        </div>
                      </div>
                    )}

                    {/* Risks (compact — still relevant during execution) */}
                    {risks.length > 0 && (
                      <div style={{ marginBottom: 18 }}>
                        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 8 }}>
                          <p className="jas-insights-tips-label" style={{ margin: 0 }}>Risks to watch</p>
                          <span style={{ fontFamily: 'JetBrains Mono, monospace', fontSize: 9.5, color: '#8a93ad' }}>{risks.length}</span>
                        </div>
                        {/* Flat list — no card chrome, just a rose left accent
                            and dividers. Matches the restraint of the
                            Upcoming list directly above. */}
                        <div style={{ display: 'flex', flexDirection: 'column' }}>
                          {risks.slice(0, 3).map((r, i) => {
                            const t = typeof r === 'string' ? r : (r?.risk || r?.text || String(r));
                            const isLast = i === Math.min(risks.length, 3) - 1;
                            return (
                              <div
                                key={i}
                                style={{
                                  padding: '8px 0 8px 10px',
                                  borderLeft: '2px solid #a0036c',
                                  borderBottom: isLast ? 'none' : '1px solid var(--border)',
                                  fontSize: 12, color: '#161f3b', lineHeight: 1.4,
                                }}
                              >{t}</div>
                            );
                          })}
                        </div>
                      </div>
                    )}

                    {/* Quick AI actions (cost credits) — operational nudges */}
                    {quickActions.length > 0 && (
                      <div>
                        <p className="jas-insights-tips-label" style={{ marginBottom: 6 }}>Ask Jaspen to…</p>
                        <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
                          {quickActions.map((q, i) => (
                            <button
                              key={i}
                              type="button"
                              onClick={() => { setInput(q); }}
                              style={{
                                textAlign: 'left',
                                display: 'flex', alignItems: 'center', gap: 8,
                                padding: '8px 10px',
                                background: '#fff', border: '1px solid var(--border)',
                                borderRadius: 7, cursor: 'pointer',
                                fontSize: 12, color: '#161f3b', lineHeight: 1.4,
                              }}
                              onMouseEnter={(e) => { e.currentTarget.style.borderColor = '#a0036c'; }}
                              onMouseLeave={(e) => { e.currentTarget.style.borderColor = 'var(--border)'; }}
                            >
                              <span style={{ color: '#a0036c', fontSize: 11 }}>✦</span>
                              <span style={{ flex: 1 }}>{q}</span>
                              <span style={{ fontFamily: 'JetBrains Mono, monospace', fontSize: 9.5, color: '#8a93ad' }}>~credits</span>
                            </button>
                          ))}
                        </div>
                      </div>
                    )}

                    {/* Fallback when no plan yet */}
                    {total === 0 && recommendations.length > 0 && (
                      <div style={{ marginTop: 6 }}>
                        <p className="jas-insights-tips-label" style={{ marginBottom: 6 }}>From the scorecard</p>
                        {recommendations.slice(0, 3).map((r, i) => (
                          <p key={i} style={{ fontSize: 12, color: '#5a6585', lineHeight: 1.5, marginTop: 6, borderLeft: '2px solid #a0036c', paddingLeft: 10 }}>
                            {typeof r === 'string' ? r : (r.text || r.action || String(r))}
                          </p>
                        ))}
                      </div>
                    )}
                  </>
                );
              })()}

              {/* No session yet */}
              {!sessionId && (
                <div className="jas-insights-tips">
                  <p className="jas-insights-tips-label">Tips</p>
                  {WORKSPACE_TIPS.slice(1, 4).map((tip) => (
                    <div key={tip.id} className="jas-insights-tip">
                      <p className="jas-insights-tip-title">{tip.title}</p>
                      <p className="jas-insights-tip-body">{tip.body}</p>
                    </div>
                  ))}
                </div>
              )}
            </div>
          </aside>
      )}
    </main>

      <ConfirmDialog
        isOpen={Boolean(confirmDialog)}
        title={confirmDialog?.title || 'Confirm action'}
        message={confirmDialog?.message || 'Are you sure you want to continue?'}
        confirmLabel={confirmDialog?.confirmLabel || 'Confirm'}
        confirmVariant={confirmDialog?.confirmVariant || 'danger'}
        checkboxLabel={confirmDialog?.checkboxLabel || null}
        checkboxChecked={deleteCheckboxOpen}
        onCheckboxChange={(next) => {
          deleteCheckboxRef.current = Boolean(next);
          setDeleteCheckboxOpen(Boolean(next));
        }}
        onConfirm={async () => {
          const action = confirmDialog?.onConfirm;
          setConfirmDialog(null);
          if (typeof action === 'function') await action();
        }}
        onCancel={() => setConfirmDialog(null)}
      />

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
