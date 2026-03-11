import React, { useMemo, useState } from 'react';
import './Knowledge.css';

const TOPICS = {
  agent: {
    short: 'AG',
    label: 'The Agent',
    title: 'The Agent',
    summary:
      'Jaspen is an execution-focused decision agent that converts complex project context into operating decisions teams can execute.',
    sections: [
      {
        heading: 'What',
        paragraphs: [
          'The agent ingests structured and unstructured inputs including goals, constraints, owner context, timelines, and system signals. It then generates recommendation-grade outputs instead of generic summaries.',
          'Jaspen is designed to bridge strategy and execution. It produces direction that can be scored, reviewed, and translated into operational actions rather than leaving teams with only narrative advice.',
        ],
      },
      {
        heading: 'Why',
        paragraphs: [
          'Most delivery drift happens between planning and handoff. Jaspen reduces that drift by combining reasoning, readiness checks, and integration controls in one workflow.',
          'This structure lets leaders move from decision to execution with fewer interpretation gaps, clearer ownership, and stronger confidence in downstream system updates.',
        ],
      },
      {
        heading: 'Where',
        paragraphs: [
          'The primary runtime is the workspace at /new. This is where teams enter goals, review outputs, compare options, and progress approved direction into implementation.',
        ],
      },
      {
        heading: 'How',
        paragraphs: [
          'Use the workspace in a consistent sequence so outputs are auditable and easier to operationalize across teams.',
        ],
        steps: [
          'Open /new and define objective, constraints, and expected outcomes.',
          'Select the model tier your plan supports, then generate recommendations.',
          'Review readiness and scenario tradeoffs before choosing a path.',
          'Apply connector settings and save integration behavior for production sync.',
        ],
      },
    ],
    links: [
      { label: 'Open workspace', href: '/new' },
      { label: 'Open billing and usage', href: '/account' },
    ],
  },
  components: {
    short: 'CP',
    label: 'Agent Components',
    title: 'Agent Components',
    summary:
      'The agent is built as explicit components so each stage can be inspected, tuned, and governed.',
    sections: [
      {
        heading: 'What',
        paragraphs: [
          'The stack is composed of an Intake Layer, Reasoning Core, Scoring and Readiness layer, Scenario Modeler, Execution Translator, and Connector Orchestrator.',
          'Each component has a narrow responsibility. This keeps behavior explainable and makes failures easier to isolate when teams troubleshoot plan quality or sync outcomes.',
        ],
      },
      {
        heading: 'Why',
        paragraphs: [
          'Component separation improves reliability. It also allows policy controls to be applied at the right stage instead of relying on one opaque end-to-end operation.',
        ],
      },
      {
        heading: 'How components map to user flow',
        paragraphs: [
          'Intake captures context and constraints. Reasoning generates options. Scoring validates confidence. Scenario Modeler quantifies tradeoffs. Execution Translator formats approved direction. Connector Orchestrator controls external sync behavior.',
        ],
        list: [
          'Intake Layer: prompt, goals, constraints, and workspace context capture.',
          'Reasoning Core: options, tradeoffs, and recommendation generation.',
          'Scoring and Readiness: confidence and checklist progression.',
          'Scenario Modeler: quantified impact, cost, and risk comparison.',
          'Execution Translator: milestone and owner-ready action output.',
          'Connector Orchestrator: credentialed sync and conflict policy handling.',
        ],
      },
    ],
    links: [{ label: 'Open workspace', href: '/new' }],
  },
  billing: {
    short: 'BL',
    label: 'Billing and Usage',
    title: 'Billing and Usage Service',
    summary:
      'Billing and Usage is the entitlement and access control layer for plans, credits, connectors, and model availability.',
    sections: [
      {
        heading: 'What',
        paragraphs: [
          'This service determines what a workspace can use based on plan tier and current credit state. It controls connector eligibility, model access, and purchased capacity visibility.',
        ],
      },
      {
        heading: 'Why',
        paragraphs: [
          'Without explicit entitlement checks, connector and model behavior becomes inconsistent across teams. Billing and Usage ensures feature availability is enforced before sync or execution starts.',
        ],
      },
      {
        heading: 'Where',
        paragraphs: [
          'Use /account for the internal account surface. The sidebar tabs segment plan overview, plans, connectors, packs, models, system administration, and knowledge access.',
        ],
      },
      {
        heading: 'How',
        steps: [
          'Review current plan and credit posture in Overview.',
          'Adjust plan or pack strategy in Plans and Credit packs.',
          'Configure and save connector settings in Connectors.',
          'Validate model access by plan in Models.',
        ],
      },
    ],
    links: [{ label: 'Open billing and usage', href: '/account' }],
  },
  connectorPlatform: {
    short: 'OR',
    label: 'Connector Platform',
    title: 'Connector Platform',
    summary:
      'All connectors follow a shared lifecycle: entitlement check, settings capture, toggle state change, and explicit save.',
    sections: [
      {
        heading: 'What',
        paragraphs: [
          'Connector controls expose a consistent surface across execution and data tools. Each connector can define required settings, sync direction options, and conflict resolution policy.',
        ],
      },
      {
        heading: 'Why',
        paragraphs: [
          'A common interaction model reduces user friction during setup and prevents accidental drift when teams manage multiple tools at once.',
        ],
      },
      {
        heading: 'How connector state works',
        paragraphs: [
          'Toggles are draft state changes until saved. Save is the commit action that persists connector configuration and status.',
        ],
        list: [
          'On unlocks connector-specific sync or data ingestion behavior.',
          'Off blocks connector-specific sync and context ingestion.',
          'Locked connectors cannot be enabled until plan requirements are met.',
          'Settings can still be reviewed even when activation is blocked by tier.',
        ],
      },
    ],
    links: [{ label: 'Open connector settings', href: '/account' }],
  },
  jira: {
    short: 'JR',
    label: 'Jira',
    title: 'Jira Connector (Execution)',
    summary:
      'Jira connects execution issues, ownership, and sprint state so planning outputs stay aligned with delivery reality.',
    sections: [
      {
        heading: 'What',
        paragraphs: [
          'The Jira connector supports controlled synchronization between Jaspen execution plans and Jira issue data. It can run in directional or bi-directional sync modes depending on policy.',
        ],
      },
      {
        heading: 'Why',
        paragraphs: [
          'Teams need planning confidence and sprint-level truth at the same time. Jira integration prevents stale task status from undermining execution decisions.',
        ],
      },
      {
        heading: 'Where',
        paragraphs: [
          'Navigate to Billing and Usage > Connectors, locate Jira, and open Settings. Jira can also trigger API settings capture when the toggle is turned on without token configuration.',
        ],
      },
      {
        heading: 'How',
        steps: [
          'Toggle Jira on to begin setup intent.',
          'Enter Jira URL, project key, Jira email, API token, and issue type.',
          'Select sync mode and conflict policy.',
          'Save to persist settings and activation state.',
        ],
      },
      {
        heading: 'Required settings',
        list: [
          'Jira base URL',
          'Jira project key',
          'Jira email',
          'Jira API token',
          'Jira issue type',
          'Sync mode',
          'Conflict policy',
        ],
      },
      {
        heading: 'Toggle behavior',
        paragraphs: [
          'On unlocks issue sync, sprint/state alignment, ownership mapping, and execution status visibility in context-aware planning.',
          'Off blocks Jira-based sync and prevents Jira execution updates from contributing to planning context.',
        ],
      },
    ],
    links: [
      { label: 'Open connector settings', href: '/account' },
      {
        label: 'Jira API token docs',
        href: 'https://support.atlassian.com/atlassian-account/docs/manage-api-tokens-for-your-atlassian-account/',
      },
    ],
  },
  workfront: {
    short: 'WF',
    label: 'Workfront',
    title: 'Workfront Connector (Execution)',
    summary:
      'Workfront integration aligns milestones, ownership, and schedule signals with Jaspen execution plans.',
    sections: [
      {
        heading: 'What',
        paragraphs: [
          'The Workfront connector exchanges project structure and status data so approved direction in Jaspen remains aligned with active Workfront execution.',
        ],
      },
      {
        heading: 'How',
        steps: [
          'Enable Workfront from the Connectors tab.',
          'Set external workspace or account identifier.',
          'Choose sync mode and conflict policy.',
          'Save connector draft to commit changes.',
        ],
      },
      {
        heading: 'Required settings',
        list: ['External workspace/account id', 'Sync mode', 'Conflict policy'],
      },
      {
        heading: 'Toggle behavior',
        paragraphs: [
          'On unlocks milestone alignment, owner alignment, and schedule change visibility.',
          'Off blocks Workfront status and ownership exchange.',
        ],
      },
    ],
    links: [{ label: 'Open connector settings', href: '/account' }],
  },
  smartsheet: {
    short: 'SM',
    label: 'Smartsheet',
    title: 'Smartsheet Connector (Execution)',
    summary:
      'Smartsheet integration maps row-level execution data to planning and readiness workflows.',
    sections: [
      {
        heading: 'What',
        paragraphs: [
          'The Smartsheet connector synchronizes row status, date fields, and execution state signals to reduce mismatch between spreadsheet operations and program planning.',
        ],
      },
      {
        heading: 'How',
        steps: [
          'Enable Smartsheet from Connectors.',
          'Set external workspace or account id.',
          'Choose sync mode and conflict policy.',
          'Save connector configuration.',
        ],
      },
      {
        heading: 'Required settings',
        list: ['External workspace/account id', 'Sync mode', 'Conflict policy'],
      },
      {
        heading: 'Toggle behavior',
        paragraphs: [
          'On unlocks task-row status sync, date alignment, and execution signal ingestion.',
          'Off blocks Smartsheet-driven delivery-state exchange.',
        ],
      },
    ],
    links: [{ label: 'Open connector settings', href: '/account' }],
  },
  salesforce: {
    short: 'SF',
    label: 'Salesforce',
    title: 'Salesforce Connector (Data)',
    summary:
      'Salesforce adds account and pipeline context to recommendation quality and prioritization tradeoffs.',
    sections: [
      {
        heading: 'What',
        paragraphs: [
          'This connector ingests CRM-oriented trend and account signal data. It enriches planning context used by recommendation and scoring logic.',
        ],
      },
      {
        heading: 'How',
        steps: [
          'Enable Salesforce connector state.',
          'Set external workspace or account id.',
          'Configure sync mode and conflict policy.',
          'Save to commit connector changes.',
        ],
      },
      {
        heading: 'Required settings',
        list: ['External workspace/account id', 'Sync mode', 'Conflict policy'],
      },
      {
        heading: 'Toggle behavior',
        paragraphs: [
          'On unlocks pipeline and customer context in analysis workflows.',
          'Off blocks Salesforce-derived insight context from recommendation pipelines.',
        ],
      },
    ],
    links: [{ label: 'Open connector settings', href: '/account' }],
  },
  snowflake: {
    short: 'SN',
    label: 'Snowflake',
    title: 'Snowflake Connector (Data)',
    summary:
      'Snowflake contributes warehouse KPI and financial trend data to scenario and scoring quality.',
    sections: [
      {
        heading: 'What',
        paragraphs: [
          'Snowflake integration reads governed analytical context that can materially improve confidence in planning and prioritization recommendations.',
        ],
      },
      {
        heading: 'How',
        steps: [
          'Enable Snowflake connector state.',
          'Set external workspace or account id.',
          'Select sync mode and conflict policy.',
          'Save connector settings.',
        ],
      },
      {
        heading: 'Required settings',
        list: ['External workspace/account id', 'Sync mode', 'Conflict policy'],
      },
      {
        heading: 'Toggle behavior',
        paragraphs: [
          'On unlocks warehouse KPI and financial trend ingestion.',
          'Off blocks Snowflake context from recommendation generation.',
        ],
      },
    ],
    links: [{ label: 'Open connector settings', href: '/account' }],
  },
  oracleFusion: {
    short: 'OF',
    label: 'Oracle Fusion',
    title: 'Oracle Fusion Connector (Data)',
    summary:
      'Oracle Fusion adds ERP operations and finance signals for enterprise-ready decision context.',
    sections: [
      {
        heading: 'What',
        paragraphs: [
          'This connector ingests ERP-backed operational and financial data to ground recommendation output in real enterprise constraints and current-state conditions.',
        ],
      },
      {
        heading: 'How',
        steps: [
          'Enable Oracle Fusion connector state.',
          'Enter external workspace or account id.',
          'Choose sync mode and conflict policy.',
          'Save connector settings.',
        ],
      },
      {
        heading: 'Required settings',
        list: ['External workspace/account id', 'Sync mode', 'Conflict policy'],
      },
      {
        heading: 'Toggle behavior',
        paragraphs: [
          'On unlocks ERP signal ingestion and finance/operations context.',
          'Off blocks Oracle Fusion signals from planning analysis.',
        ],
      },
    ],
    links: [{ label: 'Open connector settings', href: '/account' }],
  },
  serviceNow: {
    short: 'SV',
    label: 'ServiceNow',
    title: 'ServiceNow Connector (Data)',
    summary:
      'ServiceNow contributes service and change-management context to execution risk visibility.',
    sections: [
      {
        heading: 'What',
        paragraphs: [
          'The ServiceNow connector ingests service and change signals to improve risk detection and dependency awareness in execution planning.',
        ],
      },
      {
        heading: 'How',
        steps: [
          'Enable ServiceNow connector state.',
          'Set external workspace or account id.',
          'Configure sync mode and conflict policy.',
          'Save connector settings.',
        ],
      },
      {
        heading: 'Required settings',
        list: ['External workspace/account id', 'Sync mode', 'Conflict policy'],
      },
      {
        heading: 'Toggle behavior',
        paragraphs: [
          'On unlocks service/change signal context and execution-risk insights.',
          'Off blocks ServiceNow signal ingestion for analysis.',
        ],
      },
    ],
    links: [{ label: 'Open connector settings', href: '/account' }],
  },
  netSuite: {
    short: 'NS',
    label: 'NetSuite',
    title: 'NetSuite Connector (Data)',
    summary:
      'NetSuite adds finance and operations trend context for stronger execution tradeoff decisions.',
    sections: [
      {
        heading: 'What',
        paragraphs: [
          'NetSuite integration contributes operational and financial context to improve feasibility and cost-awareness in recommendation workflows.',
        ],
      },
      {
        heading: 'How',
        steps: [
          'Enable NetSuite connector state.',
          'Set external workspace or account id.',
          'Choose sync mode and conflict policy.',
          'Save connector settings.',
        ],
      },
      {
        heading: 'Required settings',
        list: ['External workspace/account id', 'Sync mode', 'Conflict policy'],
      },
      {
        heading: 'Toggle behavior',
        paragraphs: [
          'On unlocks finance and operations trend context in tradeoff modeling.',
          'Off blocks NetSuite context from recommendation pipelines.',
        ],
      },
    ],
    links: [{ label: 'Open connector settings', href: '/account' }],
  },
  api: {
    short: 'AP',
    label: 'API and Integrations',
    title: 'API and Integration Surface',
    summary:
      'The API surface enables programmatic management of sessions, billing context, connector settings, and administrative workflows.',
    sections: [
      {
        heading: 'What',
        paragraphs: [
          'Internal endpoints back the account and workspace UI. These routes expose read and write operations for connector state, billing status, and operational administration.',
        ],
      },
      {
        heading: 'Why',
        paragraphs: [
          'Programmatic access supports automation, repeatable provisioning, and better operational observability than manual-only setup.',
        ],
      },
      {
        heading: 'How',
        steps: [
          'Authenticate using the same account/session model as internal UI.',
          'Read current billing and connector state before changes.',
          'Patch connector settings with required fields and explicit status.',
          'Persist via save-style update and verify response state.',
        ],
      },
      {
        heading: 'Operational notes',
        list: [
          'Connector updates are explicit save operations, not auto-commit toggles.',
          'Jira activation requires API credential fields.',
          'Plan entitlements are enforced before connector write operations.',
        ],
      },
    ],
    links: [
      { label: 'Open API console', href: '/pages/api' },
      { label: 'Open billing and usage', href: '/account' },
    ],
  },
};

const TOPIC_GROUPS = [
  {
    label: 'Core Services',
    items: ['agent', 'components', 'billing', 'connectorPlatform', 'api'],
  },
  {
    label: 'Execution Connectors',
    items: ['jira', 'workfront', 'smartsheet'],
  },
  {
    label: 'Data Connectors',
    items: ['salesforce', 'snowflake', 'oracleFusion', 'serviceNow', 'netSuite'],
  },
];

export default function Knowledge() {
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false);
  const [activeTopicId, setActiveTopicId] = useState('agent');
  const activeTopic = useMemo(() => TOPICS[activeTopicId] || TOPICS.agent, [activeTopicId]);

  return (
    <div className="knowledge-page">
      <div className={`knowledge-layout ${sidebarCollapsed ? 'is-sidebar-collapsed' : ''}`}>
        <aside className={`knowledge-sidebar ${sidebarCollapsed ? 'is-collapsed' : ''}`}>
          <div className="knowledge-sidebar-head">
            {!sidebarCollapsed && <p className="knowledge-sidebar-title">Docs index</p>}
            <button
              type="button"
              className="knowledge-sidebar-toggle"
              onClick={() => setSidebarCollapsed((prev) => !prev)}
              aria-label={sidebarCollapsed ? 'Expand docs index' : 'Collapse docs index'}
              aria-expanded={!sidebarCollapsed}
            >
              {sidebarCollapsed ? '=' : 'x'}
            </button>
          </div>
          <div className="knowledge-sidebar-scroll">
            {TOPIC_GROUPS.map((group) => (
              <section key={group.label} className="knowledge-index-group">
                {!sidebarCollapsed && <p className="knowledge-index-label">{group.label}</p>}
                <div className="knowledge-index-items">
                  {group.items.map((topicId) => {
                    const topic = TOPICS[topicId];
                    if (!topic) return null;
                    return (
                      <button
                        key={topicId}
                        type="button"
                        className={`knowledge-index-item ${activeTopicId === topicId ? 'is-active' : ''}`}
                        onClick={() => setActiveTopicId(topicId)}
                        title={sidebarCollapsed ? topic.label : undefined}
                      >
                        <span className="knowledge-index-icon">{topic.short}</span>
                        {!sidebarCollapsed && <span className="knowledge-index-text">{topic.label}</span>}
                      </button>
                    );
                  })}
                </div>
              </section>
            ))}
          </div>
        </aside>

        <main className="knowledge-main">
          <header className="knowledge-header">
            <p className="knowledge-eyebrow">Knowledge</p>
            <h1>Internal Product Documentation</h1>
            <p className="knowledge-header-summary">
              Central documentation for every service and connector, including operational behavior, required settings,
              and setup expectations.
            </p>
          </header>

          <article className="knowledge-topic" aria-live="polite">
            <header className="knowledge-topic-head">
              <h2>{activeTopic.title}</h2>
              <p>{activeTopic.summary}</p>
            </header>

            {(activeTopic.sections || []).map((section) => (
              <section key={`${activeTopic.title}-${section.heading}`} className="knowledge-doc-section">
                <h3>{section.heading}</h3>
                {Array.isArray(section.paragraphs) &&
                  section.paragraphs.map((paragraph) => <p key={paragraph}>{paragraph}</p>)}
                {Array.isArray(section.steps) && section.steps.length > 0 && (
                  <ol>
                    {section.steps.map((step) => (
                      <li key={step}>{step}</li>
                    ))}
                  </ol>
                )}
                {Array.isArray(section.list) && section.list.length > 0 && (
                  <ul>
                    {section.list.map((item) => (
                      <li key={item}>{item}</li>
                    ))}
                  </ul>
                )}
              </section>
            ))}

            {Array.isArray(activeTopic.links) && activeTopic.links.length > 0 && (
              <section className="knowledge-doc-section knowledge-links">
                <h3>Related links</h3>
                <ul className="knowledge-link-list">
                  {activeTopic.links.map((link) => (
                    <li key={`${activeTopic.title}-${link.href}`}>
                      <a
                        href={link.href}
                        target="_blank"
                        rel="noopener noreferrer"
                        className="knowledge-link"
                      >
                        {link.label}
                      </a>
                    </li>
                  ))}
                </ul>
              </section>
            )}
          </article>
        </main>
      </div>
    </div>
  );
}
