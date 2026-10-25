import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useLocation, useNavigate } from 'react-router-dom';
import { FontAwesomeIcon } from '@fortawesome/react-fontawesome';
import {
  faArrowRightArrowLeft,
  faChevronDown,
  faChevronRight,
  faCircleInfo,
  faFlask,
  faPlugCircleCheck,
  faRotate,
  faServer,
  faSitemap,
} from '@fortawesome/free-solid-svg-icons';
import { API_BASE } from '../../config/apiBase';
import { useAuth } from '../../shared/auth/AuthContext';
import { authFetch, buildAuthHeaders } from '../../shared/auth/http';
import ConfirmDialog from '../../shared/components/ConfirmDialog';
import FieldError from '../../shared/components/FieldError';
import SkeletonBlock from '../../shared/components/SkeletonLoader';
import { PLAN_ORDER, PLAN_RANK } from '../../shared/constants/appConstants';
import JaspenAiDrawer from '../Workspace/JaspenAiDrawer';
import './ConnectorsManage.css';
import AppMenu from '../shared/AppMenu';

const CONNECTOR_ORDER = [
  'jira_sync',
  'smartsheet_sync',
  'salesforce_insights',
  'snowflake_insights',
  'oracle_fusion_insights',
  'servicenow_insights',
  'netsuite_insights',
];

// Connectors are intentionally available across every plan. Build this map
// from the canonical plan list so plan renames cannot silently hide the
// catalog. Keep the legacy/custom aliases accepted by persisted accounts.
const PLAN_CONNECTOR_IDS = Object.fromEntries(
  [...new Set([...PLAN_ORDER, 'enterprise', 'enterprise_custom'])]
    .map((planKey) => [planKey, CONNECTOR_ORDER])
);
const EXECUTION_SYNC_CONNECTOR_IDS = ['jira_sync', 'smartsheet_sync'];

const CONNECTOR_CATEGORIES = [
  { id: 'execution', label: 'Execution Sync', connectorIds: ['jira_sync', 'smartsheet_sync'] },
  { id: 'data', label: 'Data & Insights', connectorIds: ['jira_sync', 'smartsheet_sync', 'salesforce_insights', 'snowflake_insights'] },
  { id: 'enterprise', label: 'Enterprise Sources', connectorIds: ['oracle_fusion_insights', 'servicenow_insights', 'netsuite_insights'] },
];
const REQUIRED_FIELDS_BY_CONNECTOR = {
  jira_sync: ['jira_base_url', 'jira_email', 'jira_api_token'],
  smartsheet_sync: ['smartsheet_base_url', 'smartsheet_sheet_id', 'smartsheet_api_token'],
  salesforce_insights: [
    'salesforce_auth_base_url',
    'salesforce_instance_url',
    'salesforce_client_id',
    'salesforce_client_secret',
  ],
  snowflake_insights: [
    'snowflake_account',
    'snowflake_warehouse',
    'snowflake_database',
    'snowflake_schema',
    'snowflake_role',
    'snowflake_user',
    // password or private_key — handled by special case in validateRequiredFields
  ],
  oracle_fusion_insights: ['oracle_fusion_base_url', 'oracle_fusion_username', 'oracle_fusion_password'],
  servicenow_insights: ['servicenow_instance_url', 'servicenow_username', 'servicenow_password'],
  netsuite_insights: [
    'netsuite_account_id',
    'netsuite_consumer_key',
    'netsuite_consumer_secret',
    'netsuite_token_id',
    'netsuite_token_secret',
  ],
};

function authHeaders(json = false, method = 'GET') {
  return buildAuthHeaders(json ? { 'Content-Type': 'application/json' } : {}, method);
}

function normalizePlanKey(planKey) {
  return String(planKey || '').trim().toLowerCase();
}

function highestPlanKey(...plans) {
  return plans
    .map((plan) => normalizePlanKey(plan))
    .filter((plan) => Object.prototype.hasOwnProperty.call(PLAN_RANK, plan))
    .sort((a, b) => PLAN_RANK[b] - PLAN_RANK[a])[0] || 'free';
}

function connectorIcon(connectorId) {
  if (connectorId === 'jira_sync' || connectorId === 'smartsheet_sync') return faSitemap;
  if (connectorId === 'snowflake_insights') return faServer;
  if (connectorId === 'salesforce_insights') return faArrowRightArrowLeft;
  return faPlugCircleCheck;
}

function mapConnectors(items) {
  const map = new Map();
  (Array.isArray(items) ? items : []).forEach((item) => {
    map.set(item.id, item);
  });
  return CONNECTOR_ORDER.map((id) => map.get(id)).filter(Boolean);
}

function connectorIsImplemented(connector) {
  return String(connector?.implementation_status || 'implemented').trim().toLowerCase() === 'implemented';
}

function normalizeLifecycleStatus(connector) {
  return String(connector?.lifecycle_status || (connector?.connected ? 'connected' : 'disconnected')).trim().toLowerCase();
}

function connectorVerificationState(connector, connectionCheck) {
  const lifecycle = normalizeLifecycleStatus(connector);
  const health = String(connector?.health?.status || '').trim().toLowerCase();
  if (connectionCheck?.status === 'connected') return 'healthy';
  if (connectionCheck?.status === 'checking' || connectionCheck?.status === 'error') return 'attention';
  if (lifecycle === 'degraded' || ['failed', 'error', 'unhealthy', 'degraded', 'warning', 'warn', 'attention', 'needs_attention'].includes(health)) {
    return 'attention';
  }
  if (connector?.connected && connector?.freshness === 'confirmed') return 'healthy';
  if ((connector?.connected && connector?.freshness === 'unconfirmed') || connector?.connected || lifecycle === 'configured' || lifecycle === 'connected') return 'unconfirmed';
  return 'disconnected';
}

function connectorAccountLabel(connector) {
  if (connector?.id === 'jira_sync') {
    const site = String(connector?.jira?.base_url || '').replace(/^https?:\/\//, '').replace(/\/$/, '');
    return `${connector?.jira?.email || 'unknown account'} on ${site || 'Jira'}`;
  }
  if (connector?.id === 'smartsheet_sync') return 'Smartsheet account';
  if (connector?.id === 'salesforce_insights') return String(connector?.salesforce?.instance_url || 'Salesforce account').replace(/^https?:\/\//, '').replace(/\/$/, '');
  if (connector?.id === 'snowflake_insights') return `${connector?.snowflake?.user || 'unknown user'} on ${connector?.snowflake?.account || 'Snowflake'}`;
  return connector?.label || 'connector';
}

function utcDate(value) {
  const text = String(value || '').trim();
  if (!text) return null;
  const hasTimezone = /(?:Z|[+-]\d{2}:?\d{2})$/i.test(text);
  const parsed = new Date(hasTimezone ? text : `${text}Z`);
  return Number.isNaN(parsed.getTime()) ? null : parsed;
}

function formatLocalTimestamp(value) {
  const parsed = utcDate(value);
  return parsed ? parsed.toLocaleString() : 'Time unavailable';
}

function activityDescription(row) {
  const action = String(row?.action || '').toLowerCase();
  const status = String(row?.status || '').toLowerCase();
  const raw = String(row?.message || '');
  const count = Number(row?.items_synced || row?.metadata?.items_synced || 0);
  if ((action === 'pm_sync' || action === 'pm_sync_push') && /(?:HTTP\s*)?405|method not allowed/i.test(raw)) {
    return "Some Jira links couldn't be added — fixed in a later sync";
  }
  if (action === 'context_summary') return status === 'success' ? 'Portfolio evidence refreshed' : 'Portfolio evidence could not be refreshed';
  if (action === 'pm_sync' || action === 'pm_sync_push') {
    if (status === 'failed') return 'Execution plan sync needs attention';
    return count ? `Execution plan synced · ${count} item${count === 1 ? '' : 's'}` : 'Execution plan sync completed';
  }
  if (action === 'config_update') return row?.metadata?.connected === false ? 'Connector disconnected' : 'Connection or settings saved';
  if (action === 'health_check') return status === 'success' ? 'Connection checked' : 'Connection check needs attention';
  if (action === 'import') return status === 'failed' ? 'Connected updates could not be imported' : 'Updates imported from the connected tool';
  return status === 'failed' ? 'Connector activity needs attention' : 'Connector activity completed';
}

function activityDetails(row) {
  const raw = String(row?.message || '').trim();
  const metadata = row?.metadata && Object.keys(row.metadata).length ? JSON.stringify(row.metadata, null, 2) : '';
  return [raw, metadata].filter(Boolean).join('\n');
}

function normalizeDraft(connector) {
  return {
    connection_status: connector?.connected ? 'connected' : 'disconnected',
    sync_mode: connector?.sync_mode || 'import',
    conflict_policy: connector?.conflict_policy || 'prefer_external',
    auto_sync: Boolean(connector?.auto_sync),
    external_workspace: String(connector?.external_workspace || ''),
    jira_base_url: String(connector?.jira?.base_url || ''),
    jira_project_key: String(connector?.jira?.project_key || ''),
    jira_email: String(connector?.jira?.email || ''),
    jira_issue_type: String(connector?.jira?.issue_type || 'Task'),
    jira_api_token: '',
    jira_field_mapping: JSON.stringify(connector?.jira?.field_mapping || {}, null, 2),
    jira_data_enabled: Boolean(connector?.jira?.data_enabled),
    jira_data_project_scope: String(connector?.jira?.data_project_scope || 'all'),
    jira_data_selected_projects: Array.isArray(connector?.jira?.data_selected_projects) ? connector.jira.data_selected_projects : [],
    jira_data_window_days: Number(connector?.jira?.data_window_days || 90),
    jira_data_workload_threshold: Number(connector?.jira?.data_workload_threshold || 8),
    smartsheet_base_url: String(connector?.smartsheet?.base_url || 'https://api.smartsheet.com'),
    smartsheet_sheet_id: String(connector?.smartsheet?.sheet_id || ''),
    smartsheet_api_token: '',
    smartsheet_field_mapping: JSON.stringify(connector?.smartsheet?.field_mapping || {}, null, 2),
    smartsheet_data_enabled: Boolean(connector?.smartsheet?.data_enabled),
    salesforce_auth_base_url: String(connector?.salesforce?.auth_base_url || ''),
    salesforce_instance_url: String(connector?.salesforce?.instance_url || ''),
    salesforce_client_id: String(connector?.salesforce?.client_id || ''),
    salesforce_client_secret: '',
    salesforce_refresh_token: '',
    snowflake_account: String(connector?.snowflake?.account || ''),
    snowflake_warehouse: String(connector?.snowflake?.warehouse || ''),
    snowflake_database: String(connector?.snowflake?.database || ''),
    snowflake_schema: String(connector?.snowflake?.schema || ''),
    snowflake_role: String(connector?.snowflake?.role || ''),
    snowflake_user: String(connector?.snowflake?.user || ''),
    snowflake_password: '',
    snowflake_private_key: '',
    snowflake_table_allowlist: Array.isArray(connector?.snowflake?.table_allowlist)
      ? connector.snowflake.table_allowlist.join(', ')
      : '',
    oracle_fusion_base_url: String(connector?.oracle_fusion?.base_url || ''),
    oracle_fusion_username: String(connector?.oracle_fusion?.username || ''),
    oracle_fusion_password: '',
    oracle_fusion_business_unit: String(connector?.oracle_fusion?.business_unit || ''),
    servicenow_instance_url: String(connector?.servicenow?.instance_url || ''),
    servicenow_username: String(connector?.servicenow?.username || ''),
    servicenow_password: '',
    servicenow_table_allowlist: Array.isArray(connector?.servicenow?.table_allowlist)
      ? connector.servicenow.table_allowlist.join(', ')
      : '',
    netsuite_account_id: String(connector?.netsuite?.account_id || ''),
    netsuite_consumer_key: String(connector?.netsuite?.consumer_key || ''),
    netsuite_consumer_secret: '',
    netsuite_token_id: String(connector?.netsuite?.token_id || ''),
    netsuite_token_secret: '',
    netsuite_rest_base_url: String(connector?.netsuite?.rest_base_url || ''),
  };
}

function parseObject(text) {
  try {
    const parsed = JSON.parse(String(text || '{}'));
    return parsed && typeof parsed === 'object' && !Array.isArray(parsed) ? parsed : {};
  } catch {
    return {};
  }
}

function parseList(text) {
  return String(text || '')
    .split(',')
    .map((item) => item.trim())
    .filter(Boolean);
}

function connectorDraftChanged(connector, draft) {
  if (!connector || !draft) return false;
  const base = normalizeDraft(connector);
  const fields = [
    'connection_status',
    'sync_mode',
    'conflict_policy',
    'auto_sync',
    'external_workspace',
    'jira_base_url',
    'jira_project_key',
    'jira_email',
    'jira_issue_type',
    'jira_field_mapping',
    'jira_data_enabled',
    'jira_data_project_scope',
    'jira_data_selected_projects',
    'jira_data_window_days',
    'jira_data_workload_threshold',
    'smartsheet_base_url',
    'smartsheet_sheet_id',
    'smartsheet_field_mapping',
    'smartsheet_data_enabled',
    'salesforce_auth_base_url',
    'salesforce_instance_url',
    'salesforce_client_id',
    'snowflake_account',
    'snowflake_warehouse',
    'snowflake_database',
    'snowflake_schema',
    'snowflake_role',
    'snowflake_user',
    'snowflake_table_allowlist',
    'oracle_fusion_base_url',
    'oracle_fusion_username',
    'oracle_fusion_business_unit',
    'servicenow_instance_url',
    'servicenow_username',
    'servicenow_table_allowlist',
    'netsuite_account_id',
    'netsuite_consumer_key',
    'netsuite_token_id',
    'netsuite_rest_base_url',
  ];
  const differs = fields.some((field) => String(base[field] ?? '') !== String(draft[field] ?? ''));
  const hasSecretUpdates = [
    'jira_api_token',
    'smartsheet_api_token',
    'salesforce_client_secret',
    'salesforce_refresh_token',
    'snowflake_password',
    'snowflake_private_key',
    'oracle_fusion_password',
    'servicenow_password',
    'netsuite_consumer_secret',
    'netsuite_token_secret',
  ].some((field) => String(draft[field] || '').trim().length > 0);
  return differs || hasSecretUpdates;
}

function fieldLabel(text, required = false) {
  return (
    <>
      {text}
      {required && <span className="connector-required-marker" aria-hidden="true"> *</span>}
      {required && <span className="connector-required-copy">Required to connect</span>}
    </>
  );
}

export function fitCredentialHelpToViewport(anchorRect, viewportWidth, desiredWidth = 360, gutter = 16) {
  const safeViewportWidth = Math.max(0, Number(viewportWidth) || 0);
  const availableWidth = Math.max(0, safeViewportWidth - (gutter * 2));
  const width = Math.min(desiredWidth, availableWidth);
  const anchorLeft = Number(anchorRect?.left) || 0;
  const anchorRight = Number(anchorRect?.right) || anchorLeft;
  const opensRight = anchorLeft + width <= safeViewportWidth - gutter;
  const preferredLeft = opensRight ? anchorLeft : anchorRight - width;
  const furthestLeft = Math.max(gutter, safeViewportWidth - gutter - width);
  const left = Math.min(Math.max(gutter, preferredLeft), furthestLeft);
  return { left, width, placement: opensRight ? 'right' : 'left' };
}

function CredentialHelp({ id, ariaLabel, children, href, linkLabel }) {
  const summaryRef = useRef(null);
  const popoverRef = useRef(null);
  const [open, setOpen] = useState(false);
  const [popoverStyle, setPopoverStyle] = useState(null);

  const positionPopover = useCallback(() => {
    const anchor = summaryRef.current?.getBoundingClientRect();
    if (!anchor || typeof window === 'undefined') return;
    const gutter = 16;
    const gap = 6;
    const horizontal = fitCredentialHelpToViewport(anchor, window.innerWidth, 360, gutter);
    const availableHeight = Math.max(80, window.innerHeight - (gutter * 2));
    const contentHeight = Math.min(popoverRef.current?.scrollHeight || 220, availableHeight);
    const opensBelow = anchor.bottom + gap + contentHeight <= window.innerHeight - gutter;
    const top = opensBelow
      ? anchor.bottom + gap
      : Math.max(gutter, anchor.top - gap - contentHeight);
    setPopoverStyle({
      left: `${horizontal.left}px`,
      top: `${top}px`,
      width: `${horizontal.width}px`,
      maxHeight: `${availableHeight}px`,
    });
  }, []);

  useEffect(() => {
    if (!open) return undefined;
    positionPopover();
    window.addEventListener('resize', positionPopover);
    window.addEventListener('scroll', positionPopover, true);
    return () => {
      window.removeEventListener('resize', positionPopover);
      window.removeEventListener('scroll', positionPopover, true);
    };
  }, [open, positionPopover]);

  return (
    <details
      className="connector-credential-help"
      onToggle={(event) => {
        const nextOpen = event.currentTarget.open;
        setOpen(nextOpen);
        if (!nextOpen) setPopoverStyle(null);
      }}
    >
      <summary ref={summaryRef} aria-label={ariaLabel} aria-describedby={id}>
        <FontAwesomeIcon icon={faCircleInfo} aria-hidden="true" />
      </summary>
      <div
        className="connector-credential-help-popover"
        id={id}
        role="note"
        ref={popoverRef}
        style={popoverStyle || { visibility: 'hidden' }}
      >
        <p>{children}</p>
        <a href={href} target="_blank" rel="noreferrer">{linkLabel}</a>
      </div>
    </details>
  );
}

// Secret fields that are write-only in the UI (never echoed back from the server).
// The backend provides a has_<field> boolean instead. Validation must consult that
// flag rather than the always-empty draft value to avoid false "Required field" errors
// on connectors that already have a saved credential.
const SAVED_SECRET_FLAG = {
  jira_api_token:            (connector) => Boolean(connector?.jira?.has_api_token),
  smartsheet_api_token:      (connector) => Boolean(connector?.smartsheet?.has_api_token),
  salesforce_client_secret:  (connector) => Boolean(connector?.salesforce?.has_client_secret),
  salesforce_refresh_token:  (connector) => Boolean(connector?.salesforce?.has_refresh_token),
  snowflake_password:        (connector) => Boolean(connector?.snowflake?.has_password),
  snowflake_private_key:     (connector) => Boolean(connector?.snowflake?.has_private_key),
  oracle_fusion_password:    (connector) => Boolean(connector?.oracle_fusion?.has_password),
  servicenow_password:       (connector) => Boolean(connector?.servicenow?.has_password),
  netsuite_consumer_secret:  (connector) => Boolean(connector?.netsuite?.has_consumer_secret),
  netsuite_token_secret:     (connector) => Boolean(connector?.netsuite?.has_token_secret),
};

function validateRequiredFields(connectorId, draft, connector) {
  const requiredFields = REQUIRED_FIELDS_BY_CONNECTOR[connectorId] || [];
  const errors = {};
  requiredFields.forEach((field) => {
    const inDraft = Boolean(String(draft?.[field] || '').trim());
    const alreadySaved = SAVED_SECRET_FLAG[field] ? SAVED_SECRET_FLAG[field](connector) : false;
    if (!inDraft && !alreadySaved) {
      errors[field] = 'Required field';
    }
  });
  if (connectorId === 'snowflake_insights') {
    const hasPassword = String(draft?.snowflake_password || '').trim() || Boolean(connector?.snowflake?.has_password);
    const hasPrivateKey = String(draft?.snowflake_private_key || '').trim() || Boolean(connector?.snowflake?.has_private_key);
    if (!hasPassword && !hasPrivateKey) {
      errors.snowflake_password = 'Password or private key is required';
      errors.snowflake_private_key = 'Password or private key is required';
    } else {
      delete errors.snowflake_password;
      delete errors.snowflake_private_key;
    }
  }
  return errors;
}

function isMissingThreadSyncContextError(message) {
  const text = String(message || '').trim().toLowerCase();
  return text.includes('thread not found') || text.includes('no wbs found for thread');
}

function buildUpdatePayload(connectorId, draft) {
  const payload = {
    sync_mode: draft.sync_mode,
    conflict_policy: draft.conflict_policy,
    auto_sync: Boolean(draft.auto_sync),
    external_workspace: draft.external_workspace,
  };

  if (connectorId === 'jira_sync') {
    payload.jira_base_url = draft.jira_base_url;
    payload.jira_project_key = draft.jira_project_key;
    payload.jira_email = draft.jira_email;
    payload.jira_issue_type = draft.jira_issue_type;
    payload.jira_field_mapping = parseObject(draft.jira_field_mapping);
    payload.jira_data_enabled = Boolean(draft.jira_data_enabled);
    payload.jira_data_project_scope = draft.jira_data_project_scope;
    payload.jira_data_selected_projects = draft.jira_data_selected_projects;
    payload.jira_data_window_days = Number(draft.jira_data_window_days || 90);
    payload.jira_data_workload_threshold = Number(draft.jira_data_workload_threshold || 8);
    if (String(draft.jira_api_token || '').trim()) payload.jira_api_token = draft.jira_api_token.trim();
  } else if (connectorId === 'smartsheet_sync') {
    payload.smartsheet_base_url = draft.smartsheet_base_url;
    payload.smartsheet_sheet_id = draft.smartsheet_sheet_id;
    payload.smartsheet_field_mapping = parseObject(draft.smartsheet_field_mapping);
    payload.smartsheet_data_enabled = Boolean(draft.smartsheet_data_enabled);
    if (String(draft.smartsheet_api_token || '').trim()) payload.smartsheet_api_token = draft.smartsheet_api_token.trim();
  } else if (connectorId === 'salesforce_insights') {
    payload.salesforce_auth_base_url = draft.salesforce_auth_base_url;
    payload.salesforce_instance_url = draft.salesforce_instance_url;
    payload.salesforce_client_id = draft.salesforce_client_id;
    if (String(draft.salesforce_client_secret || '').trim()) payload.salesforce_client_secret = draft.salesforce_client_secret.trim();
    if (String(draft.salesforce_refresh_token || '').trim()) payload.salesforce_refresh_token = draft.salesforce_refresh_token.trim();
  } else if (connectorId === 'snowflake_insights') {
    payload.snowflake_account = draft.snowflake_account;
    payload.snowflake_warehouse = draft.snowflake_warehouse;
    payload.snowflake_database = draft.snowflake_database;
    payload.snowflake_schema = draft.snowflake_schema;
    payload.snowflake_role = draft.snowflake_role;
    payload.snowflake_user = draft.snowflake_user;
    payload.snowflake_table_allowlist = parseList(draft.snowflake_table_allowlist);
    if (String(draft.snowflake_password || '').trim()) payload.snowflake_password = draft.snowflake_password.trim();
    if (String(draft.snowflake_private_key || '').trim()) payload.snowflake_private_key = draft.snowflake_private_key.trim();
  } else if (connectorId === 'oracle_fusion_insights') {
    payload.oracle_fusion_base_url = draft.oracle_fusion_base_url;
    payload.oracle_fusion_username = draft.oracle_fusion_username;
    payload.oracle_fusion_business_unit = draft.oracle_fusion_business_unit;
    if (String(draft.oracle_fusion_password || '').trim()) payload.oracle_fusion_password = draft.oracle_fusion_password.trim();
  } else if (connectorId === 'servicenow_insights') {
    payload.servicenow_instance_url = draft.servicenow_instance_url;
    payload.servicenow_username = draft.servicenow_username;
    payload.servicenow_table_allowlist = parseList(draft.servicenow_table_allowlist);
    if (String(draft.servicenow_password || '').trim()) payload.servicenow_password = draft.servicenow_password.trim();
  } else if (connectorId === 'netsuite_insights') {
    payload.netsuite_account_id = draft.netsuite_account_id;
    payload.netsuite_consumer_key = draft.netsuite_consumer_key;
    payload.netsuite_token_id = draft.netsuite_token_id;
    payload.netsuite_rest_base_url = draft.netsuite_rest_base_url;
    if (String(draft.netsuite_consumer_secret || '').trim()) payload.netsuite_consumer_secret = draft.netsuite_consumer_secret.trim();
    if (String(draft.netsuite_token_secret || '').trim()) payload.netsuite_token_secret = draft.netsuite_token_secret.trim();
  }

  return payload;
}

export default function ConnectorsManage() {
  const navigate = useNavigate();
  const location = useLocation();
  const { user } = useAuth();
  const [connectors, setConnectors] = useState([]);
  const [drafts, setDrafts] = useState({});
  const [selectedConnectorId, setSelectedConnectorId] = useState('');
  const [auditRows, setAuditRows] = useState([]);
  const [activityVisibleCount, setActivityVisibleCount] = useState(10);
  const [expandedActivityDetails, setExpandedActivityDetails] = useState(() => new Set());
  const [threads, setThreads] = useState([]);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState('');
  const [error, setError] = useState('');
  const [draftErrors, setDraftErrors] = useState({});
  const [discardDialog, setDiscardDialog] = useState(null);
  const [snowflakeProbeBusy, setSnowflakeProbeBusy] = useState(false);
  const [snowflakeProbeResult, setSnowflakeProbeResult] = useState(null);
  const [jiraProjects, setJiraProjects] = useState([]);
  const [jiraProjectsBusy, setJiraProjectsBusy] = useState(false);
  const [jiraPortfolioBusy, setJiraPortfolioBusy] = useState(false);
  const [jiraPortfolioError, setJiraPortfolioError] = useState(null);
  const [connectionCheckByConnector, setConnectionCheckByConnector] = useState({});
  const [testedConnectionByConnector, setTestedConnectionByConnector] = useState({});
  const [planBindings, setPlanBindings] = useState([]);
  const [collapsedGroups, setCollapsedGroups] = useState(() => new Set(['enterprise']));
  const autoCheckedConnectionsRef = useRef(new Set());

  // Jaspen AI drawer
  const [jaspenOpen, setJaspenOpen] = useState(false);
  const [jaspenMessages, setJaspenMessages] = useState([]);
  const [jaspenInput, setJaspenInput] = useState('');
  const [jaspenBusy, setJaspenBusy] = useState(false);
  const [jaspenError, setJaspenError] = useState('');
  const jaspenThreadRef = useRef(`connectors_${Math.random().toString(36).slice(2, 10)}`);
  const jaspenIsFirstRef = useRef(true);
  const jaspenAbortRef = useRef(null);

  const adminPreviewPlan = useMemo(() => {
    if (!Boolean(user?.is_admin)) return '';
    const params = new URLSearchParams(location.search);
    if (String(params.get('admin_preview') || '').trim().toLowerCase() !== 'workspace') return '';
    const planKey = normalizePlanKey(params.get('plan_key'));
    return PLAN_ORDER.includes(planKey) ? planKey : '';
  }, [location.search, user?.is_admin]);

  // Handle Salesforce OAuth callback result — backend redirects back here with ?sf_oauth=success|error
  useEffect(() => {
    const params = new URLSearchParams(location.search);
    const sfOauth = String(params.get('sf_oauth') || '').trim().toLowerCase();
    const reason = String(params.get('reason') || '').trim();
    if (!sfOauth) return;

    if (sfOauth === 'success') {
      setMessage('Salesforce connected successfully.');
      // Refresh connector list (with short retries) so badge flips reliably.
      waitForSalesforceConnected();
      // Auto-select Salesforce in the sidebar so user sees the updated status
      setSelectedConnectorId('salesforce_insights');
    } else {
      setError(`Salesforce connection failed${reason ? `: ${reason.replace(/_/g, ' ')}` : ''}. Check your credentials and try again.`);
    }

    // Clean the URL so refreshing doesn't re-trigger
    params.delete('sf_oauth');
    params.delete('reason');
    const cleanSearch = params.toString();
    navigate(
      `${location.pathname}${cleanSearch ? `?${cleanSearch}` : ''}`,
      { replace: true }
    );
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const effectivePlanKey = useMemo(() => (
    adminPreviewPlan || highestPlanKey(user?.active_organization_plan_key, user?.subscription_plan)
  ), [adminPreviewPlan, user?.active_organization_plan_key, user?.subscription_plan]);

  const allowedConnectorIds = useMemo(() => (
    PLAN_CONNECTOR_IDS[effectivePlanKey] || []
  ), [effectivePlanKey]);


  const loadConnectors = useCallback(async () => {
    const res = await authFetch(`${API_BASE}/api/v1/connectors/status`, {
      credentials: 'include',
      headers: authHeaders(false, 'GET'),
    });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(data?.error || `Failed to load connectors (${res.status})`);

    const ordered = mapConnectors(data?.connectors || []);
    setConnectors(ordered);
    setDrafts((prev) => {
      const next = { ...prev };
      ordered.forEach((item) => {
        next[item.id] = normalizeDraft(item);
      });
      return next;
    });
    if (ordered.length) {
      setSelectedConnectorId((current) => current || ordered[0].id);
    }
  }, []);

  const waitForSalesforceConnected = useCallback(async () => {
    const maxAttempts = 8;
    for (let attempt = 0; attempt < maxAttempts; attempt += 1) {
      let connected = false;
      try {
        const res = await authFetch(`${API_BASE}/api/v1/connectors/status`, {
          credentials: 'include',
          headers: authHeaders(false, 'GET'),
        });
        const data = await res.json().catch(() => ({}));
        if (res.ok) {
          const ordered = mapConnectors(data?.connectors || []);
          setConnectors(ordered);
          setDrafts((prev) => {
            const next = { ...prev };
            ordered.forEach((item) => {
              next[item.id] = normalizeDraft(item);
            });
            return next;
          });
          connected = Boolean(ordered.find((item) => item.id === 'salesforce_insights')?.connected);
        }
      } catch {
        // best effort retries
      }
      if (connected) return true;
      // eslint-disable-next-line no-await-in-loop
      await new Promise((resolve) => setTimeout(resolve, 600));
    }
    return false;
  }, []);

  const loadThreads = useCallback(async () => {
    const res = await authFetch(`${API_BASE}/api/v1/ai-agent/threads`, {
      credentials: 'include',
      headers: authHeaders(false, 'GET'),
    });
    const data = await res.json().catch(() => ({}));
    if (!res.ok || !data?.success) {
      setThreads([]);
      return;
    }
    const rows = (Array.isArray(data.sessions) ? data.sessions : [])
      .map((item) => ({
        threadId: String(item?.session_id || '').trim(),
        name: String(item?.name || item?.result?.project_name || '').trim(),
      }))
      .filter((item) => item.threadId);
    setThreads(rows);
  }, []);

  const loadAudit = useCallback(async (connectorId) => {
    if (!connectorId) {
      setAuditRows([]);
      return;
    }
    const res = await authFetch(`${API_BASE}/api/v1/connectors/${encodeURIComponent(connectorId)}/audit?limit=100`, {
      credentials: 'include',
      headers: authHeaders(false, 'GET'),
    });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) {
      setAuditRows([]);
      return;
    }
    setAuditRows((Array.isArray(data?.events) ? data.events : []).sort((a, b) => String(b?.timestamp || '').localeCompare(String(a?.timestamp || ''))));
  }, []);

  const loadPlanBindings = useCallback(async () => {
    const res = await authFetch(`${API_BASE}/api/v1/pm-sync/bindings`, {
      credentials: 'include',
      headers: authHeaders(false, 'GET'),
    });
    const data = await res.json().catch(() => ({}));
    setPlanBindings(res.ok && Array.isArray(data?.bindings) ? data.bindings : []);
  }, []);

  const refresh = useCallback(async () => {
    setLoading(true);
    setError('');
    try {
      await Promise.all([loadConnectors(), loadThreads(), loadPlanBindings()]);
    } catch (err) {
      setError(err?.message || 'Failed to load connector management data.');
    } finally {
      setLoading(false);
    }
  }, [loadConnectors, loadPlanBindings, loadThreads]);

  useEffect(() => {
    refresh();
  }, [refresh]);

  useEffect(() => {
    setActivityVisibleCount(10);
    setExpandedActivityDetails(new Set());
    loadAudit(selectedConnectorId);
  }, [loadAudit, selectedConnectorId]);

  const selectedConnector = useMemo(
    () => connectors.find((item) => item.id === selectedConnectorId && allowedConnectorIds.includes(item.id)) || null,
    [allowedConnectorIds, connectors, selectedConnectorId]
  );

  const visibleConnectors = useMemo(
    () => connectors.filter((item) => allowedConnectorIds.includes(item.id)),
    [allowedConnectorIds, connectors]
  );

  const selectedDraft = selectedConnector ? drafts[selectedConnector.id] || normalizeDraft(selectedConnector) : null;
  const selectedDraftErrors = selectedConnector ? draftErrors[selectedConnector.id] || {} : {};
  const selectedConnectorImplemented = connectorIsImplemented(selectedConnector);
  const selectedConnectorDirty = useMemo(
    () => connectorDraftChanged(selectedConnector, selectedDraft),
    [selectedConnector, selectedDraft]
  );
  const selectedConnectionDirty = connectionFieldsChanged(selectedConnector, selectedDraft);
  const threadNameById = useMemo(() => Object.fromEntries(threads.map((thread) => [thread.threadId, thread.name || thread.threadId])), [threads]);
  const selectedConnectorBindings = useMemo(
    () => planBindings.filter((binding) => binding.connector_id === selectedConnector?.id),
    [planBindings, selectedConnector?.id]
  );
  const selectedConnectionCheck = selectedConnector ? connectionCheckByConnector[selectedConnector.id] : null;
  const selectedVerificationState = selectedConnector
    ? connectorVerificationState(selectedConnector, selectedConnectionCheck)
    : 'disconnected';
  const selectedLastConfirmedAt = selectedConnectionCheck?.status === 'connected'
    ? selectedConnectionCheck.checkedAt
    : selectedConnector?.last_confirmed_at || null;
  const visibleActivityRows = auditRows.slice(0, activityVisibleCount);

  const loadJiraProjects = useCallback(async () => {
    setJiraProjectsBusy(true);
    try {
      const res = await authFetch(`${API_BASE}/api/v1/connectors/jira/projects`, {
        credentials: 'include',
        headers: authHeaders(false, 'GET'),
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(data?.error || 'Could not load Jira projects.');
      setJiraProjects(Array.isArray(data?.projects) ? data.projects : []);
    } catch (err) {
      setJiraProjects([]);
      setError(err?.message || 'Could not load Jira projects.');
    } finally {
      setJiraProjectsBusy(false);
    }
  }, []);

  const refreshJiraPortfolio = useCallback(async () => {
    setJiraPortfolioBusy(true);
    setJiraPortfolioError(null);
    try {
      const res = await authFetch(`${API_BASE}/api/v1/connectors/jira/context/summary?refresh=true`, {
        credentials: 'include',
        headers: authHeaders(false, 'GET'),
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) {
        setJiraPortfolioError({
          category: data?.category || 'provider',
          message: data?.error || data?.message || "Jaspen couldn't read Jira data — we've logged the details.",
          reconnect_required: Boolean(data?.reconnect_required),
          projects: Array.isArray(data?.projects) ? data.projects : [],
        });
        return;
      }
      const refreshError = data?.snapshot?.refresh_error || null;
      setJiraPortfolioError(refreshError);
      setMessage(refreshError ? 'Showing the last successful Jira portfolio snapshot.' : 'Jira portfolio evidence refreshed.');
      await loadConnectors();
    } catch (err) {
      setJiraPortfolioError({ category: 'provider', message: err?.message || "Jaspen couldn't read Jira data — we've logged the details." });
    } finally {
      setJiraPortfolioBusy(false);
    }
  }, [loadConnectors]);

  useEffect(() => {
    if (selectedConnectorId === 'jira_sync' && connectors.find((item) => item.id === 'jira_sync')?.connected) {
      loadJiraProjects();
    }
  }, [connectors, loadJiraProjects, selectedConnectorId]);

  useEffect(() => {
    if (!selectedConnector?.connected) return;
    const key = `${selectedConnector.id}:${selectedConnector.updated_at || selectedConnector.last_sync_at || 'saved'}`;
    if (autoCheckedConnectionsRef.current.has(key)) return;
    autoCheckedConnectionsRef.current.add(key);
    testConnection(selectedConnector, false);
    // The connection identity above intentionally controls when the live probe repeats.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedConnector?.connected, selectedConnector?.id, selectedConnector?.last_sync_at, selectedConnector?.updated_at]);
  const hasUnsavedChanges = useMemo(
    () => connectors.some((connector) => connectorDraftChanged(connector, drafts[connector.id] || normalizeDraft(connector))),
    [connectors, drafts]
  );

  const healthSummary = useMemo(() => {
    const allowed = connectors.filter((c) => allowedConnectorIds.includes(c.id) && connectorIsImplemented(c));
    const confirmed = allowed.filter((c) => c.freshness === 'confirmed').length;
    const unconfirmed = allowed.filter((c) => c.freshness === 'unconfirmed').length;
    const degraded = allowed.filter((c) => normalizeLifecycleStatus(c) === 'degraded').length;
    const STALE_THRESHOLD_MS = 24 * 60 * 60 * 1000;
    const staleNames = allowed
      .filter((c) => {
        if (normalizeLifecycleStatus(c) !== 'connected') return false;
        if (!c.last_sync_at) return false;
        const age = Date.now() - new Date(c.last_sync_at).getTime();
        return age > STALE_THRESHOLD_MS;
      })
      .map((c) => c.label);
    return { confirmed, unconfirmed, degraded, total: allowed.length, staleNames };
  }, [allowedConnectorIds, connectors]);

  // Mutual exclusion: close Jaspen drawer whenever App Menu opens
  useEffect(() => {
    const observer = new MutationObserver(() => {
      if (document.body.classList.contains('jaspen-sidebar-open')) {
        setJaspenOpen(false);
      }
    });
    observer.observe(document.body, { attributes: true, attributeFilter: ['class'] });
    return () => observer.disconnect();
  }, []);

  // Open Jaspen drawer and close App Menu if it was open
  const openJaspen = useCallback(() => {
    document.body.classList.remove('jaspen-sidebar-open');
    setJaspenOpen(true);
  }, []);

  useEffect(() => {
    if (!visibleConnectors.length) {
      setSelectedConnectorId('');
      return;
    }
    if (!visibleConnectors.some((item) => item.id === selectedConnectorId)) {
      setSelectedConnectorId(visibleConnectors[0].id);
    }
  }, [selectedConnectorId, visibleConnectors]);

  useEffect(() => {
    const onBeforeUnload = (event) => {
      if (!hasUnsavedChanges) return;
      event.preventDefault();
      event.returnValue = '';
    };
    window.addEventListener('beforeunload', onBeforeUnload);
    return () => window.removeEventListener('beforeunload', onBeforeUnload);
  }, [hasUnsavedChanges]);

  function connectionDraftSignature(connectorId, draft) {
    if (connectorId === 'jira_sync') {
      return JSON.stringify([
        String(draft?.jira_base_url || '').trim(),
        String(draft?.jira_email || '').trim().toLowerCase(),
        String(draft?.jira_api_token || '').trim(),
      ]);
    }
    return '';
  }

  function jiraCredentialDraftChanged(connector, draft) {
    if (connector?.id !== 'jira_sync') return false;
    return String(draft?.jira_base_url || '').trim() !== String(connector?.jira?.base_url || '').trim()
      || String(draft?.jira_email || '').trim().toLowerCase() !== String(connector?.jira?.email || '').trim().toLowerCase()
      || Boolean(String(draft?.jira_api_token || '').trim());
  }

  function connectionFieldsChanged(connector, draft) {
    if (!connector || !draft) return false;
    if (connector.id === 'jira_sync') return jiraCredentialDraftChanged(connector, draft);
    if (connector.id === 'smartsheet_sync') {
      return String(draft.smartsheet_base_url || '').trim() !== String(connector?.smartsheet?.base_url || '').trim()
        || Boolean(String(draft.smartsheet_api_token || '').trim());
    }
    if (connector.id === 'salesforce_insights') {
      return String(draft.salesforce_auth_base_url || '').trim() !== String(connector?.salesforce?.auth_base_url || '').trim()
        || String(draft.salesforce_instance_url || '').trim() !== String(connector?.salesforce?.instance_url || '').trim()
        || String(draft.salesforce_client_id || '').trim() !== String(connector?.salesforce?.client_id || '').trim()
        || Boolean(String(draft.salesforce_client_secret || '').trim())
        || Boolean(String(draft.salesforce_refresh_token || '').trim());
    }
    if (connector.id === 'snowflake_insights') {
      const saved = connector?.snowflake || {};
      return ['account', 'warehouse', 'database', 'schema', 'role', 'user'].some((field) => String(draft[`snowflake_${field}`] || '').trim() !== String(saved[field] || '').trim())
        || Boolean(String(draft.snowflake_password || '').trim())
        || Boolean(String(draft.snowflake_private_key || '').trim());
    }
    return connectorDraftChanged(connector, draft);
  }

  function updateDraft(field, value) {
    if (!selectedConnector) return;
    setDrafts((prev) => ({
      ...prev,
      [selectedConnector.id]: {
        ...(prev[selectedConnector.id] || normalizeDraft(selectedConnector)),
        [field]: value,
      },
    }));
    setDraftErrors((prev) => ({
      ...prev,
      [selectedConnector.id]: {
        ...(prev[selectedConnector.id] || {}),
        [field]: '',
      },
    }));
    if (selectedConnector.id === 'jira_sync' && ['jira_base_url', 'jira_email', 'jira_api_token'].includes(field)) {
      setTestedConnectionByConnector((prev) => ({ ...prev, jira_sync: '' }));
    }
  }

  async function saveConnector(saveConnection = false) {
    if (!selectedConnector || !selectedDraft) return;
    const validationErrors = validateRequiredFields(selectedConnector.id, selectedDraft, selectedConnector);
    if (Object.keys(validationErrors).length > 0) {
      setDraftErrors((prev) => ({
        ...prev,
        [selectedConnector.id]: validationErrors,
      }));
      setError('Please fix the highlighted required fields.');
      setMessage('');
      return;
    }
    const isJiraConnectionSave = selectedConnector.id === 'jira_sync' && saveConnection;
    if (isJiraConnectionSave && testedConnectionByConnector.jira_sync !== connectionDraftSignature('jira_sync', selectedDraft)) {
      setError('Test the Jira connection before saving.');
      setMessage('');
      return;
    }
    setBusy(true);
    setError('');
    setMessage('');
    try {
      const payload = {
        ...buildUpdatePayload(selectedConnector.id, selectedDraft),
        connection_status: 'connected',
      };
      const res = await authFetch(isJiraConnectionSave
        ? `${API_BASE}/api/v1/pm-sync/jira/connect`
        : `${API_BASE}/api/v1/connectors/${encodeURIComponent(selectedConnector.id)}`, {
        method: isJiraConnectionSave ? 'POST' : 'PATCH',
        credentials: 'include',
        headers: authHeaders(true, isJiraConnectionSave ? 'POST' : 'PATCH'),
        body: JSON.stringify(payload),
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(data?.error || `Save failed (${res.status})`);

      setMessage(`${selectedConnector.label} saved.`);
      await loadConnectors();
      await loadAudit(selectedConnector.id);
    } catch (err) {
      setError(err?.message || 'Failed to save connector.');
    } finally {
      setBusy(false);
    }
  }

  async function disconnectConnector() {
    if (!selectedConnector) return;
    setBusy(true);
    setError('');
    try {
      const res = await authFetch(`${API_BASE}/api/v1/connectors/${encodeURIComponent(selectedConnector.id)}`, {
        method: 'PATCH', credentials: 'include', headers: authHeaders(true, 'PATCH'),
        body: JSON.stringify({ connection_status: 'disconnected' }),
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(data?.error || 'Could not disconnect this account.');
      setMessage(`${selectedConnector.label} disconnected.`);
      setConnectionCheckByConnector((prev) => ({ ...prev, [selectedConnector.id]: { status: 'disconnected', checkedAt: new Date().toISOString(), message: 'Disconnected' } }));
      await Promise.all([loadConnectors(), loadAudit(selectedConnector.id)]);
    } catch (err) {
      setError(err?.message || 'Could not disconnect this account.');
    } finally {
      setBusy(false);
    }
  }

  async function testConnection(connector = selectedConnector, announce = true) {
    if (!connector) return;
    if (announce) {
      setBusy(true);
      setError('');
      setMessage('');
    }
    setConnectionCheckByConnector((prev) => ({ ...prev, [connector.id]: { status: 'checking', checkedAt: null, message: 'Checking connection…' } }));
    try {
      const testDraft = drafts[connector.id] || normalizeDraft(connector);
      const isJiraCandidate = connector.id === 'jira_sync' && announce && jiraCredentialDraftChanged(connector, testDraft);
      const res = await authFetch(isJiraCandidate
        ? `${API_BASE}/api/v1/pm-sync/jira/test-connection`
        : `${API_BASE}/api/v1/connectors/${encodeURIComponent(connector.id)}/health`, {
        method: isJiraCandidate ? 'POST' : 'GET',
        credentials: 'include',
        headers: authHeaders(isJiraCandidate, isJiraCandidate ? 'POST' : 'GET'),
        ...(isJiraCandidate ? { body: JSON.stringify({
          jira_base_url: testDraft.jira_base_url,
          jira_email: testDraft.jira_email,
          jira_api_token: testDraft.jira_api_token,
        }) } : {}),
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error('The saved connection could not be verified. Reconnect and check the credentials.');
      const live = data?.live_status;
      const healthy = !live || live.status !== 'error';
      if (!healthy) throw new Error('The saved connection could not be verified. Reconnect and check the credentials.');
      const checkedAt = new Date().toISOString();
      if (isJiraCandidate) {
        setTestedConnectionByConnector((prev) => ({ ...prev, jira_sync: connectionDraftSignature('jira_sync', testDraft) }));
      }
      setConnectionCheckByConnector((prev) => ({ ...prev, [connector.id]: { status: 'connected', checkedAt, message: 'Connection verified' } }));
      if (announce) setMessage('Connection verified.');
      await loadAudit(connector.id);
    } catch (err) {
      const plainMessage = err?.message || 'The saved connection could not be verified. Reconnect and check the credentials.';
      setConnectionCheckByConnector((prev) => ({ ...prev, [connector.id]: { status: 'error', checkedAt: new Date().toISOString(), message: plainMessage } }));
      if (announce) setError(plainMessage);
    } finally {
      if (announce) setBusy(false);
    }
  }

  async function validateSnowflakeDataAccess() {
    if (!selectedConnector || selectedConnector.id !== 'snowflake_insights' || !selectedDraft) return;
    const tables = parseList(selectedDraft.snowflake_table_allowlist).slice(0, 10);
    if (!tables.length) {
      setError('Add at least one table in Table Allowlist before running data validation.');
      return;
    }

    setSnowflakeProbeBusy(true);
    setError('');
    setMessage('');
    setSnowflakeProbeResult(null);
    try {
      const results = [];
      for (const table of tables) {
        const response = await authFetch(`${API_BASE}/api/v1/connectors/snowflake/query`, {
          method: 'POST',
          credentials: 'include',
          headers: authHeaders(true, 'POST'),
          body: JSON.stringify({ table, limit: 1 }),
        });
        const data = await response.json().catch(() => ({}));
        if (!response.ok) {
          results.push({
            table,
            ok: false,
            message: data?.error || `HTTP ${response.status}`,
          });
          continue;
        }
        results.push({
          table,
          ok: true,
          message: `Readable (${Array.isArray(data?.rows) ? data.rows.length : 0} row sampled)`,
        });
      }

      const okCount = results.filter((row) => row.ok).length;
      const failCount = results.length - okCount;
      setSnowflakeProbeResult({
        checkedAt: Date.now(),
        rows: results,
        okCount,
        failCount,
      });
      if (failCount === 0) {
        setMessage(`Snowflake data validation passed for ${okCount}/${results.length} allowlisted table(s).`);
      } else {
        setError(`Snowflake data validation failed for ${failCount}/${results.length} table(s). Review diagnostics below.`);
      }
    } catch (err) {
      setError(err?.message || 'Snowflake data validation failed.');
    } finally {
      setSnowflakeProbeBusy(false);
    }
  }

  async function connectWithSalesforce() {
    try {
      // Save credentials first so the backend has them before starting OAuth
      if (selectedConnector?.id === 'salesforce_insights' && selectedDraft) {
        const validationErrors = validateRequiredFields('salesforce_insights', selectedDraft, selectedConnector);
        if (Object.keys(validationErrors).length > 0) {
          setDraftErrors((prev) => ({ ...prev, salesforce_insights: validationErrors }));
          setError('Please fill in all required Salesforce fields before connecting.');
          return;
        }
        setBusy(true);
        setError('');
        setMessage('');
        const savePayload = buildUpdatePayload('salesforce_insights', selectedDraft);
        // Keep status disconnected until OAuth callback completes. This avoids
        // false "configuration incomplete" failures from stale connected state.
        savePayload.connection_status = 'disconnected';
        const saveRes = await authFetch(`${API_BASE}/api/v1/connectors/salesforce_insights`, {
          method: 'PATCH',
          credentials: 'include',
          headers: authHeaders(true, 'PATCH'),
          body: JSON.stringify(savePayload),
        });
        const saveData = await saveRes.json().catch(() => ({}));
        if (!saveRes.ok) throw new Error(saveData?.error || 'Failed to save Salesforce credentials.');
        await loadConnectors();
        setBusy(false);
      }

      const nextPath = window.location.pathname + window.location.search;
      const response = await fetch(
        `${API_BASE}/api/v1/connectors/salesforce/oauth/start?next=${encodeURIComponent(nextPath)}`,
        {
          method: 'GET',
          headers: authHeaders(false, 'GET'),
          credentials: 'include',
        }
      );
      const data = await response.json().catch(() => ({}));
      if (!response.ok || !data?.auth_url) {
        throw new Error(data?.error || 'Could not start Salesforce OAuth. Check your Client ID and Secret.');
      }
      window.location.href = data.auth_url;
    } catch (err) {
      setBusy(false);
      setError(err?.message || 'Failed to connect to Salesforce. Try again.');
    }
  }

  async function submitJaspenMessage(rawText) {
    const text = String(rawText || jaspenInput || '').trim();
    if (!text || jaspenBusy) return;
    setJaspenInput('');
    setJaspenBusy(true);
    setJaspenError('');
    openJaspen();
    setJaspenMessages((prev) => [...prev, { role: 'user', text }]);
    const controller = typeof AbortController !== 'undefined' ? new AbortController() : null;
    jaspenAbortRef.current = controller;
    const threadId = jaspenThreadRef.current;
    const endpoint = jaspenIsFirstRef.current
      ? `${API_BASE}/api/v1/ai-agent/conversation/start`
      : `${API_BASE}/api/v1/ai-agent/conversation/continue`;
    if (jaspenIsFirstRef.current) jaspenIsFirstRef.current = false;
    try {
      const res = await authFetch(endpoint, {
        method: 'POST',
        credentials: 'include',
        headers: buildAuthHeaders({ 'Content-Type': 'application/json' }),
        signal: controller?.signal,
        body: JSON.stringify({
          message: text,
          thread_id: threadId,
          name: 'Connectors Advisor',
          view_context: {
            current_view: 'connectors',
            page_facts: `Connectors visible: ${connectors.length}. Connected connectors: ${connectors.filter((item) => item.connected).length}.`,
          },
        }),
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(data?.error || `Request failed (${res.status})`);
      const reply = String(data?.reply || data?.message || '').trim() || 'I could not generate a response right now.';
      setJaspenMessages((prev) => [...prev, { role: 'assistant', text: reply }]);
    } catch (err) {
      if (err?.name === 'AbortError' || controller?.signal?.aborted) {
        setJaspenMessages((prev) => [...prev, { role: 'assistant', text: 'Stopped.' }]);
        return;
      }
      const msg = err?.message || 'Something went wrong. Please try again.';
      setJaspenError(msg);
      setJaspenMessages((prev) => [...prev, { role: 'assistant', text: "This reply didn't finish. Try again." }]);
    } finally {
      if (jaspenAbortRef.current === controller) {
        jaspenAbortRef.current = null;
      }
      setJaspenBusy(false);
    }
  }

  function stopJaspenMessage() {
    try {
      jaspenAbortRef.current?.abort();
    } catch (_) { /* no-op */ }
    jaspenAbortRef.current = null;
    setJaspenBusy(false);
  }

  function renderConnectorSpecificFields(connectorId, draft, section = 'data') {
    if (!draft) return null;
    const fieldError = (field) => selectedDraftErrors?.[field] || '';
    const credentialsRequired = !selectedConnector?.connected || selectedConnectionCheck?.status === 'error';
    const savedSecret = (field) => Boolean(SAVED_SECRET_FLAG[field]?.(selectedConnector));
    const savedSecretPlaceholder = (field) => {
      if (!savedSecret(field)) return null;
      if (field.includes('token')) return 'Token saved · enter a new one only to replace it';
      if (field.includes('private_key')) return 'Private key saved · enter a new one only to replace it';
      if (field.includes('password')) return 'Password saved · enter a new one only to replace it';
      return 'Secret saved · enter a new one only to replace it';
    };
    const describedBy = (field, helpId) => [
      fieldError(field) ? `connector-field-error-${connectorId}-${field}` : '',
      helpId || '',
    ].filter(Boolean).join(' ') || undefined;
    const inputClassName = (field) => (fieldError(field) ? 'connector-input-invalid' : '');
    const renderRequiredField = (field, label, options = {}) => {
      const type = options.type || 'text';
      const inputId = `connector-field-${connectorId}-${field}`;
      const helpId = options.help ? `connector-field-help-${connectorId}-${field}` : undefined;
      const placeholder = type === 'password'
        ? (savedSecretPlaceholder(field) || options.emptyPlaceholder || options.placeholder)
        : options.placeholder;
      return (
        <div className="connector-form-field">
          <div className="connector-field-label-row">
            <label htmlFor={inputId}>{fieldLabel(label, credentialsRequired)}</label>
            {options.help && <CredentialHelp id={helpId} {...options.help} />}
          </div>
          <input
            id={inputId}
            type={type}
            value={draft[field]}
            onChange={(event) => updateDraft(field, event.target.value)}
            placeholder={placeholder}
            className={inputClassName(field)}
            aria-invalid={Boolean(fieldError(field))}
            aria-describedby={describedBy(field, helpId)}
          />
          <FieldError id={`connector-field-error-${connectorId}-${field}`} message={fieldError(field)} />
        </div>
      );
    };

    if (connectorId === 'jira_sync') {
      if (section === 'connection') {
        return <>
          {renderRequiredField('jira_base_url', 'Jira site URL', { placeholder: 'https://yourcompany.atlassian.net' })}
          {renderRequiredField('jira_email', 'Email', { placeholder: 'you@yourcompany.com' })}
          {renderRequiredField('jira_api_token', 'API token', {
            type: 'password',
            emptyPlaceholder: 'Paste your API token',
            help: {
              ariaLabel: 'About Jira credentials',
              href: 'https://id.atlassian.com/manage-profile/security/api-tokens',
              linkLabel: 'Create a Jira API token',
              children: "Jaspen uses this token to sign in to Jira. It's shared by Data & Insights (reading project health) and execution plan sync (writing tasks). You only need to enter it to connect, or if it expires. Create one at id.atlassian.com → Security → API tokens.",
            },
          })}
        </>;
      }
      const snapshot = selectedConnector?.jira?.portfolio_snapshot || {};
      const projectRows = Array.isArray(snapshot?.projects) ? snapshot.projects : [];
      const refreshError = jiraPortfolioError || snapshot?.refresh_error || null;
      const noAccessProjects = Array.isArray(snapshot?.no_access_projects) ? snapshot.no_access_projects : [];
      return (
        <section className="connector-data-source-settings connector-field-full">
            <h3>Data &amp; Insights</h3>
            <label className="connector-auto-sync">
              <input type="checkbox" checked={Boolean(draft.jira_data_enabled)} onChange={(event) => updateDraft('jira_data_enabled', event.target.checked)} />
              <span><strong>Use Jira data in analysis</strong><br />When on, Jaspen's AI uses summary metrics from your Jira projects (counts, rates, health — never issue content or names) when analyzing decisions.</span>
            </label>
            <fieldset className="connector-project-scope">
              <legend>Projects included</legend>
              <label><input type="radio" name="jira-project-scope" checked={draft.jira_data_project_scope === 'all'} onChange={() => updateDraft('jira_data_project_scope', 'all')} /> All projects I can access</label>
              <label><input type="radio" name="jira-project-scope" checked={draft.jira_data_project_scope === 'selected'} onChange={() => updateDraft('jira_data_project_scope', 'selected')} /> Selected projects</label>
              {draft.jira_data_project_scope === 'selected' && (
                <select
                  multiple
                  aria-label="Selected Jira projects"
                  value={draft.jira_data_selected_projects}
                  onChange={(event) => updateDraft('jira_data_selected_projects', Array.from(event.target.selectedOptions).map((option) => option.value))}
                >
                  {jiraProjects.map((project) => <option key={project.key} value={project.key}>{project.key} · {project.name}</option>)}
                </select>
              )}
              <small>Archived projects are excluded. {jiraProjectsBusy ? 'Loading projects…' : `${jiraProjects.length} available.`}</small>
            </fieldset>
            <div className="connector-metric-settings">
              <label>Analysis window (days)<input type="number" min="14" max="365" value={draft.jira_data_window_days} onChange={(event) => updateDraft('jira_data_window_days', event.target.value)} /></label>
              <label>Workload threshold<input type="number" min="1" max="100" value={draft.jira_data_workload_threshold} onChange={(event) => updateDraft('jira_data_workload_threshold', event.target.value)} /></label>
              <button type="button" className="int-btn int-btn-ghost" onClick={refreshJiraPortfolio} disabled={jiraPortfolioBusy || !selectedConnector?.connected}>{jiraPortfolioBusy ? 'Refreshing…' : 'Refresh portfolio evidence'}</button>
            </div>
            {refreshError && (
              <div className="connector-inline-notice connector-inline-notice-error" role="alert">
                <strong>{snapshot?.stale ? 'Showing the last successful snapshot. ' : ''}{refreshError.message}</strong>
                {refreshError.reconnect_required && (
                  <button type="button" className="int-btn int-btn-ghost" onClick={() => {
                    setTimeout(() => document.querySelector('input[type="password"]')?.focus(), 0);
                  }}>Reconnect Jira</button>
                )}
              </div>
            )}
            {noAccessProjects.length > 0 && (
              <div className="connector-inline-notice" role="status">
                Jira could not read: {noAccessProjects.map((row) => `${row.project_key} · ${row.project_name}`).join(', ')}. Check this account's project permissions.
              </div>
            )}
            {projectRows.length > 0 && (
              <div className="connector-portfolio-table-wrap">
                <h3>Portfolio evidence</h3>
                <table className="connector-portfolio-table">
                  <thead><tr><th>Project</th><th>Health</th><th>Complete</th><th>Open</th><th>Overdue</th><th>Trend</th><th>Cycle time</th></tr></thead>
                  <tbody>
                    {projectRows.map((row) => (
                      <tr key={row.project_key}>
                        <td><a href={row.jira_url} target="_blank" rel="noreferrer">{row.project_key} · {row.project_name}</a></td>
                        <td>{String(row.health?.status || 'unknown').replace('_', ' ')}</td>
                        <td><a href={row.jira_links?.done || row.jira_url} target="_blank" rel="noreferrer">{row.completion_percent == null ? '—' : `${row.completion_percent}%`}</a></td>
                        <td><a href={row.jira_links?.open || row.jira_url} target="_blank" rel="noreferrer">{Number(row.status_counts?.to_do || 0) + Number(row.status_counts?.in_progress || 0)}</a></td>
                        <td><a href={row.jira_links?.overdue || row.jira_url} target="_blank" rel="noreferrer">{row.overdue_count}</a></td>
                        <td>{row.throughput?.trend || 'flat'}</td>
                        <td>{row.cycle_time?.median_days == null ? '—' : `${row.cycle_time.median_days}d (n=${row.cycle_time.sample_size})`}</td>
                      </tr>
                    ))}
                    <tr className="connector-portfolio-summary"><td>Portfolio</td><td>{String(snapshot?.portfolio?.health?.status || 'unknown').replace('_', ' ')}</td><td>{snapshot?.portfolio?.completion_percent == null ? '—' : `${snapshot.portfolio.completion_percent}%`}</td><td>{Number(snapshot?.portfolio?.status_counts?.to_do || 0) + Number(snapshot?.portfolio?.status_counts?.in_progress || 0)}</td><td>{snapshot?.portfolio?.overdue_count || 0}</td><td>{snapshot?.portfolio?.throughput?.trend || 'flat'}</td><td>{snapshot?.portfolio?.cycle_time?.median_days == null ? '—' : `${snapshot.portfolio.cycle_time.median_days}d`}</td></tr>
                  </tbody>
                </table>
              </div>
            )}
        </section>
      );
    }

    if (connectorId === 'smartsheet_sync') {
      if (section === 'data') {
        return <section className="connector-data-source-settings connector-field-full"><h3>Data &amp; Insights</h3><p>Portfolio evidence from Smartsheet is coming soon.</p></section>;
      }
      return (
        <>
          {renderRequiredField('smartsheet_base_url', 'Smartsheet Base URL')}
          {renderRequiredField('smartsheet_api_token', 'API Token', {
            type: 'password',
            emptyPlaceholder: 'Paste your API token',
            help: {
              ariaLabel: 'About Smartsheet credentials',
              href: 'https://help.smartsheet.com/articles/2482389-generate-API-key',
              linkLabel: 'Create a Smartsheet API token',
              children: "Jaspen uses this token to sign in to Smartsheet for execution plan sync. You only need to enter it to connect, replace it, or if it expires. Create one in Smartsheet under Personal Settings → API Access.",
            },
          })}
        </>
      );
    }

    if (connectorId === 'salesforce_insights') {
      if (section === 'data') {
        return <section className="connector-data-source-settings connector-field-full"><h3>Data &amp; Insights</h3><p>Salesforce pipeline summaries are available to decision analysis when this connection is active.</p></section>;
      }
      return (
        <>
          {renderRequiredField('salesforce_auth_base_url', 'Auth Base URL')}
          {renderRequiredField('salesforce_instance_url', 'Instance URL')}
          {renderRequiredField('salesforce_client_id', 'Client ID')}
          {renderRequiredField('salesforce_client_secret', 'Client Secret', {
            type: 'password',
            emptyPlaceholder: 'Paste your client secret',
            help: {
              ariaLabel: 'About Salesforce credentials',
              href: 'https://help.salesforce.com/s/articleView?id=connected_app_create_api_integration.htm&type=5',
              linkLabel: 'Set up Salesforce API credentials',
              children: 'Jaspen uses the client ID and client secret from your Salesforce External Client App or Connected App to authorize access. Enter the secret when connecting or rotating the app credentials.',
            },
          })}
          <label>
            Refresh Token <span className="connector-field-optional">(auto-populated after OAuth)</span>
            <input
              type="password"
              value={draft.salesforce_refresh_token}
              onChange={(event) => updateDraft('salesforce_refresh_token', event.target.value)}
              placeholder={savedSecretPlaceholder('salesforce_refresh_token') || 'Auto-populated after connecting via OAuth'}
            />
          </label>
          <div className="connector-oauth-row">
            <button
              type="button"
              className="connector-oauth-btn"
              onClick={connectWithSalesforce}
              title="Authorize Jaspen to access your Salesforce data via OAuth"
            >
              <img
                src="https://c1.sfdcstatic.com/content/dam/sfdc-docs/www/logos/logo-salesforce.svg"
                alt=""
                className="connector-oauth-logo"
                onError={(event) => { event.currentTarget.style.display = 'none'; }}
              />
              Connect with Salesforce
            </button>
            <p className="connector-oauth-hint">
              Enter your Client ID and Secret above, save credentials, then click Connect to authorize via OAuth.
              You will not need to enter a refresh token manually after authorization.
            </p>
          </div>
        </>
      );
    }

    if (connectorId === 'snowflake_insights') {
      if (section === 'data') {
        return (
          <section className="connector-data-source-settings connector-field-full">
            <h3>Data &amp; Insights</h3>
            <label>Table allowlist<input value={draft.snowflake_table_allowlist} onChange={(event) => updateDraft('snowflake_table_allowlist', event.target.value)} placeholder="e.g. analytics.projects, analytics.capacity" /></label>
            <button type="button" className="int-btn int-btn-ghost" onClick={validateSnowflakeDataAccess} disabled={snowflakeProbeBusy}>{snowflakeProbeBusy ? 'Validating…' : 'Validate data access'}</button>
          </section>
        );
      }
      // Snowflake renders its own grid — caller must NOT wrap in connector-field-grid
      return (
        <div className="connector-sf-grid">
          {/* Setup guide */}
          <p className="connector-sf-guide">
            <strong>Account:</strong> Snowsight → Admin → Accounts. Format: <code>abc12345.us-east-1</code> — no <em>.snowflakecomputing.com</em>.{' '}
            <strong>Role:</strong> Must have SELECT on your tables; <code>SYSADMIN</code> works for testing.{' '}
            <strong>Table Allowlist:</strong> Required — Jaspen only queries tables you explicitly list here.
          </p>

          {/* Row 1: Account + Warehouse */}
          {renderRequiredField('snowflake_account', 'Account Identifier', { placeholder: 'e.g. qzc42998.us-east-1' })}
          {renderRequiredField('snowflake_warehouse', 'Warehouse', { placeholder: 'e.g. COMPUTE_WH' })}

          {/* Row 2: Database + Schema */}
          {renderRequiredField('snowflake_database', 'Database', { placeholder: 'e.g. SNOWFLAKE_SAMPLE_DATA' })}
          {renderRequiredField('snowflake_schema', 'Schema', { placeholder: 'e.g. TPCH_SF1' })}

          {/* Row 3: Role + Username */}
          {renderRequiredField('snowflake_role', 'Role', { placeholder: 'e.g. SYSADMIN' })}
          {renderRequiredField('snowflake_user', 'Username', { placeholder: 'Your Snowflake username' })}

          {/* Credentials section */}
          <p className="connector-sf-section">Credentials — password or private key required</p>
          {renderRequiredField('snowflake_password', 'Password', {
            type: 'password',
            emptyPlaceholder: 'Enter your Snowflake password',
            help: {
              ariaLabel: 'About Snowflake credentials',
              href: 'https://docs.snowflake.com/en/user-guide/key-pair-auth',
              linkLabel: 'Set up Snowflake authentication',
              children: 'Jaspen uses either this password or a private key to sign in to Snowflake. Enter a credential when connecting, replacing it, or after it expires. Snowflake recommends key-pair authentication for service connections.',
            },
          })}
          <label>
            Private Key (alternative)
            <input
              type="password"
              value={draft.snowflake_private_key}
              onChange={(event) => updateDraft('snowflake_private_key', event.target.value)}
              placeholder={savedSecretPlaceholder('snowflake_private_key') || 'Paste your PEM private key'}
              className={inputClassName('snowflake_private_key')}
              aria-invalid={Boolean(fieldError('snowflake_private_key'))}
              aria-describedby={describedBy('snowflake_private_key')}
            />
            <FieldError id={`connector-field-error-${connectorId}-snowflake_private_key`} message={fieldError('snowflake_private_key')} />
          </label>
          {fieldError('snowflake_password') && fieldError('snowflake_password') === fieldError('snowflake_private_key') && (
            <p className="connector-sf-error-text">{fieldError('snowflake_password')}</p>
          )}

        </div>
      );
    }

    if (connectorId === 'oracle_fusion_insights') {
      if (section === 'data') return null;
      return (
        <>
          {renderRequiredField('oracle_fusion_base_url', 'Oracle Fusion URL')}
          {renderRequiredField('oracle_fusion_username', 'Username')}
          {renderRequiredField('oracle_fusion_password', 'Password', { type: 'password', placeholder: 'Enter password to set or rotate' })}
          <label>Business Unit<input value={draft.oracle_fusion_business_unit} onChange={(event) => updateDraft('oracle_fusion_business_unit', event.target.value)} /></label>
        </>
      );
    }

    if (connectorId === 'servicenow_insights') {
      if (section === 'data') return null;
      return (
        <>
          {renderRequiredField('servicenow_instance_url', 'Instance URL')}
          {renderRequiredField('servicenow_username', 'Username')}
          {renderRequiredField('servicenow_password', 'Password', { type: 'password', placeholder: 'Enter password to set or rotate' })}
          <label>Table Allowlist (comma-separated)<input value={draft.servicenow_table_allowlist} onChange={(event) => updateDraft('servicenow_table_allowlist', event.target.value)} /></label>
        </>
      );
    }

    if (connectorId === 'netsuite_insights') {
      if (section === 'data') return null;
      return (
        <>
          {renderRequiredField('netsuite_account_id', 'Account ID')}
          {renderRequiredField('netsuite_consumer_key', 'Consumer Key')}
          {renderRequiredField('netsuite_consumer_secret', 'Consumer Secret', { type: 'password', placeholder: 'Enter secret to set or rotate' })}
          {renderRequiredField('netsuite_token_id', 'Token ID')}
          {renderRequiredField('netsuite_token_secret', 'Token Secret', { type: 'password', placeholder: 'Enter secret to set or rotate' })}
          <label>REST Base URL<input value={draft.netsuite_rest_base_url} onChange={(event) => updateDraft('netsuite_rest_base_url', event.target.value)} /></label>
        </>
      );
    }

    return null;
  }

  return (
    <div className={`connectors-manage-page int-page${jaspenOpen ? ' drawer-open' : ''}`}>
      <AppMenu />
      <div className="connectors-manage-inner int-page-inner">
      <header className="connectors-manage-header int-page-head">
        <div>
          <p className="int-eyebrow">Data Sources</p>
          <h1>Connectors</h1>
          <p>Centralized connector management with monitoring, health checks, and sync history.</p>
        </div>
      </header>

      {loading && (
        <section className="connectors-skeleton" role="status" aria-live="polite" aria-label="Loading connectors">
          <SkeletonBlock width="26%" height={14} />
          <SkeletonBlock width="68%" height={52} />
          <div className="connectors-skeleton-layout">
            <div className="connectors-skeleton-list">
              {Array.from({ length: 6 }).map((_, idx) => (
                <div key={`connectors-skeleton-list-${idx}`} className="connectors-skeleton-card">
                  <div className="connectors-skeleton-card-top">
                    <SkeletonBlock width={34} height={34} />
                    <SkeletonBlock width={92} height={20} />
                  </div>
                  <SkeletonBlock width="58%" height={20} />
                  <SkeletonBlock width="88%" height={12} />
                  <SkeletonBlock width="44%" height={12} />
                </div>
              ))}
            </div>
            <div className="connectors-skeleton-detail">
              <div className="connectors-skeleton-detail-head">
                <SkeletonBlock width="34%" height={30} />
                <div className="connectors-skeleton-detail-actions">
                  <SkeletonBlock width={118} height={36} />
                  <SkeletonBlock width={108} height={36} />
                  <SkeletonBlock width={122} height={36} />
                </div>
              </div>
              <div className="connectors-skeleton-form">
                {Array.from({ length: 8 }).map((__, formIdx) => (
                  <SkeletonBlock key={`connectors-skeleton-field-${formIdx}`} width="100%" height={40} />
                ))}
              </div>
            </div>
          </div>
        </section>
      )}
      {!loading && error && (
        <div className="connectors-manage-state is-error" role="status" aria-live="polite">
          <p>{error}</p>
          <button type="button" className="int-btn int-btn-ghost connectors-retry-btn" onClick={refresh}>
            Retry
          </button>
        </div>
      )}
      {!loading && !error && message && <div className="connectors-manage-state is-success" role="status" aria-live="polite">{message}</div>}

      {!loading && !error && (
        <>
          {/* Slim health + plan bar */}
          <div className="connectors-health-bar">
            <div className="connectors-health-bar-stats">
              <span className="connectors-health-stat is-connected">
                <span className="connectors-health-dot" />
                {healthSummary.confirmed} confirmed
              </span>
              {healthSummary.unconfirmed > 0 && (
                <span className="connectors-health-stat is-unconfirmed">
                  <span className="connectors-health-dot" />
                  {healthSummary.unconfirmed} set up
                </span>
              )}
              {healthSummary.degraded > 0 && (
                <span className="connectors-health-stat is-degraded">
                  <span className="connectors-health-dot" />
                  {healthSummary.degraded} issue{healthSummary.degraded !== 1 ? 's' : ''}
                </span>
              )}
              {healthSummary.staleNames.length > 0 && (
                <span className="connectors-health-stat is-stale" title="Last sync was more than 24 hours ago — consider resyncing">
                  <span className="connectors-health-dot" />
                  {healthSummary.staleNames.join(', ')} may be outdated
                </span>
              )}
              <span className="connectors-health-stat is-muted">
                {healthSummary.total} available on your {effectivePlanKey} plan
              </span>
            </div>
            <button
              type="button"
              className="int-btn int-btn-ghost connectors-health-refresh"
              onClick={refresh}
              disabled={loading || busy}
              aria-label="Refresh connector status"
            >
              <FontAwesomeIcon icon={faRotate} />
              Refresh
            </button>
          </div>
          <div className="connectors-manage-layout">
            {/* ── Left sidebar: categorized connector list ── */}
            <nav className="connectors-sidebar" aria-label="Connector list">
              {CONNECTOR_CATEGORIES.map((category) => {
                const categoryConnectors = visibleConnectors.filter((c) =>
                  category.connectorIds.includes(c.id)
                );
                if (categoryConnectors.length === 0) return null;
                const isCollapsed = collapsedGroups.has(category.id);
                const toggleCollapsed = () =>
                  setCollapsedGroups((prev) => {
                    const next = new Set(prev);
                    if (next.has(category.id)) next.delete(category.id);
                    else next.add(category.id);
                    return next;
                  });
                return (
                  <div key={category.id} className="connector-category-group">
                    <button
                      type="button"
                      className="connector-category-header"
                      onClick={toggleCollapsed}
                      aria-expanded={!isCollapsed}
                    >
                      <FontAwesomeIcon
                        icon={isCollapsed ? faChevronRight : faChevronDown}
                        className="connector-category-chevron"
                      />
                      <span>{category.label}</span>
                      <span className="connector-category-count">
                        {categoryConnectors.filter((c) => normalizeLifecycleStatus(c) === 'connected').length}/{categoryConnectors.length}
                      </span>
                    </button>
                    {!isCollapsed && (
                      <ul className="connector-list">
                        {categoryConnectors.map((connector) => {
                          const implemented = connectorIsImplemented(connector);
                          const verification = connectorVerificationState(connector, connectionCheckByConnector[connector.id]);
                          const isSelected = selectedConnectorId === connector.id;
                          return (
                            <li key={connector.id}>
                              <button
                                type="button"
                                className={`connector-list-item ${isSelected ? 'is-selected' : ''} ${!implemented ? 'is-coming-soon' : ''}`}
                                onClick={() => setSelectedConnectorId(connector.id)}
                                title={!implemented ? 'Coming soon' : connector.description}
                              >
                                <span className="connector-list-item-icon">
                                  <FontAwesomeIcon icon={connectorIcon(connector.id)} />
                                </span>
                                <span className="connector-list-item-label">{connector.label}</span>
                                {implemented ? (
                                  <span className={`connector-list-item-dot ${verification === 'healthy' ? 'is-on' : verification === 'attention' ? 'is-warn' : verification === 'unconfirmed' ? 'is-unconfirmed' : ''}`} />
                                ) : (
                                  <span className="connector-list-item-soon">Soon</span>
                                )}
                              </button>
                            </li>
                          );
                        })}
                      </ul>
                    )}
                  </div>
                );
              })}
            </nav>

            <section className="connector-detail-panel">
              {!selectedConnector && <div className="connectors-manage-state">Select a connector.</div>}
              {selectedConnector && selectedDraft && (
                <>
                  <header className="connector-detail-header">
                    <div>
                      <h2>{selectedConnector.label}</h2>
                      <p>{selectedConnector.description}</p>
                    </div>
                  </header>
                  {!selectedConnectorImplemented ? (
                    <div className="connectors-manage-state">
                      This connector is marked as coming soon and is currently read-only.
                    </div>
                  ) : (
                    <>
                  <section className="connector-connection-section">
                    <div className="connector-connection-summary">
                      <span className={`connector-status-dot ${selectedVerificationState === 'healthy' ? 'is-connected' : selectedVerificationState === 'attention' ? 'is-attention' : selectedVerificationState === 'unconfirmed' ? 'is-unconfirmed' : ''}`} />
                      <div>
                        <strong>{selectedConnector.connected ? `Connected as ${connectorAccountLabel(selectedConnector)}` : `${selectedConnector.label} is not connected`}</strong>
                        <p>{selectedConnectionCheck?.status === 'checking' ? 'Checking connection…' : selectedConnectionCheck?.status === 'error' ? selectedConnectionCheck.message : selectedLastConfirmedAt ? `Last confirmed ${formatLocalTimestamp(selectedLastConfirmedAt)}` : 'Not confirmed yet'}</p>
                      </div>
                    </div>
                    {selectedConnectionCheck?.status === 'error' && <div className="connector-inline-notice connector-inline-notice-error" role="alert">{selectedConnectionCheck.message}</div>}
                    <div className={selectedConnector.id === 'snowflake_insights' ? '' : 'connector-field-grid'}>{renderConnectorSpecificFields(selectedConnector.id, selectedDraft, 'connection')}</div>
                    <div className="connector-connect-form-actions">
                      <button type="button" className="int-btn int-btn-ghost" onClick={() => testConnection(selectedConnector, true)} disabled={busy}><FontAwesomeIcon icon={faFlask} /> Test connection</button>
                      <button type="button" className="int-btn int-btn-primary" onClick={() => saveConnector(true)} disabled={busy || !selectedConnectionDirty || (selectedConnector.id === 'jira_sync' && testedConnectionByConnector.jira_sync !== connectionDraftSignature('jira_sync', selectedDraft))}><FontAwesomeIcon icon={faServer} /> Save</button>
                      {selectedConnector.connected && <button type="button" className="int-btn int-btn-ghost" onClick={disconnectConnector} disabled={busy}>Disconnect</button>}
                    </div>
                  </section>

                  {renderConnectorSpecificFields(selectedConnector.id, selectedDraft, 'data')}
                  {selectedConnectorDirty && !selectedConnectionDirty && <div className="connector-settings-save"><button type="button" className="int-btn int-btn-primary" onClick={() => saveConnector(false)} disabled={busy || !selectedConnectorDirty}>Save changes</button></div>}

                  {EXECUTION_SYNC_CONNECTOR_IDS.includes(selectedConnector.id) && (
                    <section className="connector-execution-sync-section">
                      <h3>Execution plan sync</h3>
                      <p>Sync is turned on per execution plan.</p>
                      {selectedConnectorBindings.length === 0 ? <p>No execution plans are linked to {selectedConnector.label}.</p> : (
                        <ul className="connector-linked-plans">
                          {selectedConnectorBindings.map((binding) => <li key={binding.id}>
                            <a href={`/workspace/${encodeURIComponent(binding.thread_id)}/__execution__?idea=${encodeURIComponent(binding.plan_key)}`}>{threadNameById[binding.thread_id] || 'Execution plan'}</a>
                            <span>{binding.external_container_id}</span>
                            <span>{binding.last_success_at ? `Last synced ${formatLocalTimestamp(binding.last_success_at)}` : 'Not synced yet'}</span>
                            <span>{String(binding.status || 'active').replace('_', ' ')}</span>
                            <span>Synced by {binding.sync_owner?.name || binding.sync_owner?.email || 'the person who connected Jira'} with their Jira account</span>
                            {(binding.sync_warning_code === 'authorization_expired' || binding.status === 'reconnect_required') && (
                              <span role="alert">Jira needs to be reconnected by {binding.sync_owner?.name || binding.sync_owner?.email || 'the connection owner'} before this plan can sync.</span>
                            )}
                            {['sync_owner_left_organization', 'sync_owner_unavailable'].includes(binding.pause_reason || binding.sync_warning_code) && (
                              <span role="alert">Sync is paused because the person who connected Jira no longer has access.</span>
                            )}
                            {binding.sync_warning_code === 'sync_failed' && (
                              <span role="alert">Jira sync needs attention. Open the plan to retry.</span>
                            )}
                          </li>)}
                        </ul>
                      )}
                    </section>
                  )}
                  {selectedConnector.id === 'snowflake_insights' && snowflakeProbeResult && (
                    <section className="connector-diagnostics">
                      <h3>Snowflake Diagnostics</h3>
                      <p className="connector-diagnostics-summary">
                        Checked {snowflakeProbeResult.rows.length} table(s): {snowflakeProbeResult.okCount} passed, {snowflakeProbeResult.failCount} failed.
                      </p>
                      <div className="connector-audit-table-wrap">
                        <table>
                          <thead>
                            <tr>
                              <th>Table</th>
                              <th>Status</th>
                              <th>Details</th>
                            </tr>
                          </thead>
                          <tbody>
                            {snowflakeProbeResult.rows.map((row) => (
                              <tr key={`sf-probe-${row.table}`}>
                                <td>{row.table}</td>
                                <td>{row.ok ? 'pass' : 'fail'}</td>
                                <td>{row.message}</td>
                              </tr>
                            ))}
                          </tbody>
                        </table>
                      </div>
                    </section>
                  )}

                  <section className="connector-audit-history">
                    <h3>Activity</h3>
                    {auditRows.length === 0 ? (
                      <p>No activity yet.</p>
                    ) : (
                      <>
                        <ul className="connector-activity-list">
                          {visibleActivityRows.map((row) => {
                            const rowKey = row.id || `${row.timestamp}-${row.action}`;
                            const details = activityDetails(row);
                            const detailsOpen = expandedActivityDetails.has(rowKey);
                            return (
                              <li key={rowKey}>
                                <span className={`connector-activity-status is-${row.status || 'unknown'}`} />
                                <div>
                                  <strong>{activityDescription(row)}</strong>
                                  {details && <button
                                    type="button"
                                    className="connector-activity-details-toggle"
                                    aria-expanded={detailsOpen}
                                    onClick={() => setExpandedActivityDetails((current) => {
                                      const next = new Set(current);
                                      if (next.has(rowKey)) next.delete(rowKey); else next.add(rowKey);
                                      return next;
                                    })}
                                  >{detailsOpen ? 'Hide details' : 'Details'}</button>}
                                  {detailsOpen && <pre className="connector-activity-details">{details}</pre>}
                                </div>
                                <time>{formatLocalTimestamp(row.timestamp)}</time>
                              </li>
                            );
                          })}
                        </ul>
                        {activityVisibleCount < auditRows.length && <button type="button" className="int-btn int-btn-ghost connector-activity-show-more" onClick={() => setActivityVisibleCount((count) => count + 10)}>Show more</button>}
                      </>
                    )}
                  </section>
                    </>
                  )}
                </>
              )}
            </section>
          </div>
        </>
      )}
      <ConfirmDialog
        isOpen={Boolean(discardDialog)}
        title={discardDialog?.title || 'Discard unsaved changes?'}
        message={discardDialog?.message || 'You have unsaved changes. Leave this page and discard them?'}
        confirmLabel={discardDialog?.confirmLabel || 'Discard changes'}
        confirmVariant={discardDialog?.confirmVariant || 'danger'}
        onConfirm={discardDialog?.onConfirm}
        onCancel={() => setDiscardDialog(null)}
      />
      </div>

      <JaspenAiDrawer
        isOpen={jaspenOpen}
        onOpen={openJaspen}
        onClose={() => setJaspenOpen(false)}
        showSideTab={true}
        sideTabTop={228}
        id="connectors-jaspen-drawer"
        messages={jaspenMessages}
        input={jaspenInput}
        onInputChange={setJaspenInput}
        onSend={() => submitJaspenMessage()}
        onStop={stopJaspenMessage}
        busy={jaspenBusy}
        placeholder="Ask about your connectors…"
        starterPrompts={[
          'Which of my connectors needs attention?',
          'How do I set up Salesforce for the first time?',
          'What does a degraded connection mean?',
          'What\'s the difference between import and bidirectional sync?',
        ]}
        contextLabel="Data Sources"
        contextTitle="Connector Management"
        contextDescription="Ask Jaspen about connector status, setup, sync behavior, or next steps."
      />
    </div>
  );
}
