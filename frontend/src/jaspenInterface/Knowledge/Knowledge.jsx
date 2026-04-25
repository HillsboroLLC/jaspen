import React, { useEffect, useMemo, useState } from 'react';
import './Knowledge.css';
import AppMenu from '../shared/AppMenu';

const TOPICS = {
  gettingStarted: {
    short: 'GS',
    label: 'Getting Started',
    title: 'Getting Started',
    summary: 'End-to-end workflow from project kickoff to execution sync.',
    sections: [
      {
        heading: 'Recommended Flow',
        body: [
          'Use this sequence for consistent outcomes and faster team alignment.',
        ],
        steps: [
          'Start a project in New Project.',
          'Complete discovery with the AI intake conversation.',
          'Review the scorecard and key risks.',
          'Model scenarios and adopt the best option.',
          'Generate WBS and adjust owners, timelines, and dependencies.',
          'Sync to your PM system from Connectors.',
        ],
      },
      {
        heading: 'Output Surfaces',
        body: [
          'Use Scores for historical results, Projects for portfolio tracking, Activity for timeline events, and Reports for exported executive outputs.',
        ],
      },
    ],
    links: [
      { label: 'New Project', href: '/new' },
      { label: 'Projects', href: '/projects' },
      { label: 'Scores', href: '/scores' },
      { label: 'Connectors', href: '/connectors-manage' },
    ],
  },
  agent: {
    short: 'AG',
    label: 'The Agent',
    title: 'The Agent',
    summary: 'Execution-focused decision intelligence from intake through operational handoff.',
    sections: [
      {
        heading: 'What It Does',
        body: [
          'Jaspen transforms goals, constraints, and operational context into scoreable recommendations and execution-ready plans.',
        ],
      },
      {
        heading: 'Why It Matters',
        body: [
          'The platform reduces strategy-to-execution drift by making assumptions explicit and outputs auditable.',
        ],
      },
    ],
    links: [{ label: 'Workspace', href: '/new' }],
  },
  components: {
    short: 'CP',
    label: 'Agent Components',
    title: 'Agent Components',
    summary: 'Composable services for intake, scoring, scenarios, execution planning, and integrations.',
    sections: [
      {
        heading: 'Core Layers',
        body: [
          'Intake captures context, scoring quantifies readiness, scenarios model tradeoffs, WBS planning operationalizes execution, and connectors sync external systems.',
        ],
      },
      {
        heading: 'Why This Structure',
        body: [
          'Each layer can be inspected and tuned independently, which improves reliability and governance.',
        ],
      },
    ],
    links: [{ label: 'Workspace', href: '/new' }],
  },
  jaspenScore: {
    short: 'JS',
    label: 'Jaspen Score',
    title: 'Jaspen Score',
    summary: 'What the score measures, how component scores work, and how category bands are interpreted.',
    sections: [
      {
        heading: 'Score Meaning',
        body: [
          'Jaspen Score is a 0-100 summary of readiness and execution quality. It is supported by component-level scores so teams can see which capability areas are helping or hurting outcomes.',
        ],
      },
      {
        heading: 'Category Bands',
        body: [
          'Excellent: 80-100. Good: 60-79. Fair: 40-59. At Risk: 0-39.',
          'Use category changes over time to track whether interventions and scenario choices are improving execution confidence.',
        ],
      },
      {
        heading: 'How To Improve Scores',
        body: [
          'Review weak components first, create scenarios that target those constraints, adopt the strongest scenario, then re-run analysis after execution updates.',
        ],
      },
    ],
    links: [{ label: 'Open Scores', href: '/scores' }],
  },
  scenarioModeling: {
    short: 'SM',
    label: 'Scenario Modeling',
    title: 'Scenario Modeling',
    summary: 'Create manual scenarios, ask AI to suggest lever adjustments, compare outcomes, and adopt a scenario.',
    sections: [
      {
        heading: 'Manual Scenarios',
        body: [
          'Use the scenario modeler to adjust lever values directly. Levers represent controllable drivers such as budget, scope, timeline, staffing, and operational constraints.',
        ],
      },
      {
        heading: 'AI-Assisted Scenarios',
        body: [
          'Ask the AI in chat or use AI Suggest in the modeler for proposals like "increase budget by 15%" or "cut timeline by one quarter".',
          'AI returns rationale plus lever-by-lever adjustments so you can accept as-is or modify before committing.',
        ],
      },
      {
        heading: 'Adoption',
        body: [
          'Adopting a scenario marks it as your chosen path and uses it as the working context for planning, WBS generation, and downstream sync.',
        ],
      },
    ],
    links: [{ label: 'Open Workspace', href: '/new' }],
  },
  projectPlansWbs: {
    short: 'WB',
    label: 'Project Plans & WBS',
    title: 'Project Plans & WBS',
    summary: 'Generate and edit execution-ready plans from your analysis, including dependencies and role assignments.',
    sections: [
      {
        heading: 'AI WBS Generation',
        body: [
          'AI can generate a phased work breakdown structure from scorecard insights and adopted scenario context.',
          'Generated tasks include title, description, priority, estimated duration, suggested owner role, and dependencies.',
        ],
      },
      {
        heading: 'Editing and Control',
        body: [
          'All generated tasks remain editable. Teams can refine sequencing, dependencies, role ownership, and risk focus areas before execution.',
        ],
      },
      {
        heading: 'Sync Targets',
        body: [
          'WBS plans can be synced to Jira, Workfront, and Smartsheet when connector credentials and sync settings are configured.',
        ],
      },
    ],
    links: [{ label: 'Open Workspace', href: '/new' }],
  },
  aiDataInsights: {
    short: 'DI',
    label: 'AI Data Insights',
    title: 'AI Data Insights',
    summary: 'Upload datasets, analyze trends and anomalies, and combine uploaded and connected-source insights.',
    sections: [
      {
        heading: 'Dataset Upload and Analysis',
        body: [
          'Upload CSV/Excel datasets in Insights, then run AI analysis to produce trend summaries, anomaly detection, opportunity highlights, and risk indicators.',
        ],
      },
      {
        heading: 'Connected Tool Context',
        body: [
          'When connectors are enabled, insights can include context from linked systems so recommendations reflect CRM, PM, and data warehouse signals.',
        ],
      },
      {
        heading: 'How To Read Results',
        body: [
          'Trends show sustained directional changes. Anomalies flag outliers or sudden shifts. Opportunities identify upside interventions. Risks identify downside exposure requiring mitigation.',
        ],
      },
    ],
    links: [{ label: 'Open Insights', href: '/insights' }],
  },
  reportsGuide: {
    short: 'RP',
    label: 'Reports',
    title: 'Reports',
    summary: 'Generate PDF reports from analyses and portfolio data for leadership sharing.',
    sections: [
      {
        heading: 'Report Types',
        body: [
          'Executive Summary: concise decision-ready overview.',
          'Detailed Analysis: full breakdown of scorecard, drivers, and recommendations.',
          'Portfolio Overview: multi-project summary across the workspace.',
        ],
      },
      {
        heading: 'Generation and Download',
        body: [
          'Select a project and report type, generate the report, then download the PDF from the reports list.',
        ],
      },
    ],
    links: [{ label: 'Open Reports', href: '/reports' }],
  },
  connectors: {
    short: 'CN',
    label: 'Connectors',
    title: 'Connectors',
    summary: 'Configure integrations for execution sync and data enrichment across PM, CRM, and warehouse systems.',
    sections: [
      {
        heading: 'Supported Connectors',
        body: [
          'Execution: Jira, Workfront, Smartsheet. Data/Insights: Salesforce, Snowflake, Oracle Fusion, ServiceNow, NetSuite.',
        ],
      },
      {
        heading: 'Sync Modes',
        body: [
          'Import pulls external updates into Jaspen. Push sends Jaspen updates to external systems. Two-way runs bidirectional synchronization.',
        ],
      },
      {
        heading: 'Conflict Policies',
        body: [
          'latest_wins applies newest update, prefer_external favors external values, prefer_jaspen keeps Jaspen values, manual_review flags records for explicit resolution.',
        ],
      },
    ],
    links: [{ label: 'Open Connectors', href: '/connectors-manage' }],
  },
  teamManagement: {
    short: 'TM',
    label: 'Team Management',
    title: 'Team Management',
    summary: 'Manage organizations, members, invitations, roles, and seat policy by plan.',
    sections: [
      {
        heading: 'Role Model',
        body: [
          'Roles are owner, admin, creator, collaborator, and viewer. Owner is unique per org and has full admin privileges.',
        ],
      },
      {
        heading: 'Seat Defaults',
        body: [
          'Team: admin 2, creator 5, collaborator 10, viewer unlimited. Enterprise: admin 5, creator 25, collaborator unlimited, viewer unlimited.',
        ],
      },
    ],
    links: [{ label: 'Open Team', href: '/team' }],
  },
  savedStarters: {
    short: 'ST',
    label: 'Saved Starters',
    title: 'Saved Starters',
    summary: 'Save reusable intake and scoring configurations from completed analyses.',
    sections: [
      {
        heading: 'What Is Saved',
        body: [
          'Starters can preserve objective, intake context, lever defaults, and scoring preferences for repeatable launches.',
        ],
      },
      {
        heading: 'How Teams Use It',
        body: [
          'Create starters from strong analyses, share with your organization, and begin future projects from those baselines.',
        ],
      },
    ],
    links: [{ label: 'Open Workspace', href: '/new' }],
  },
  jira: {
    short: 'JR',
    label: 'Jira',
    title: 'Jira Connector (Execution)',
    summary: 'Bidirectional issue and sprint alignment for execution planning.',
    sections: [
      {
        heading: 'Required Settings',
        body: [
          'Base URL, project key, email, API token, issue type, sync mode, and conflict policy.',
        ],
      },
    ],
    links: [{ label: 'Open Connectors', href: '/connectors-manage' }],
  },
  workfront: {
    short: 'WF',
    label: 'Workfront',
    title: 'Workfront Connector (Execution)',
    summary: 'Milestone and owner synchronization with Workfront projects.',
    sections: [
      {
        heading: 'Required Settings',
        body: ['Workfront base URL, project ID, API token, sync mode, and conflict policy.'],
      },
    ],
    links: [{ label: 'Open Connectors', href: '/connectors-manage' }],
  },
  smartsheet: {
    short: 'SM',
    label: 'Smartsheet',
    title: 'Smartsheet Connector (Execution)',
    summary: 'Task-row synchronization for schedule and execution status alignment.',
    sections: [
      {
        heading: 'Required Settings',
        body: ['Smartsheet sheet ID, access token, sync mode, and conflict policy.'],
      },
    ],
    links: [{ label: 'Open Connectors', href: '/connectors-manage' }],
  },
  salesforce: {
    short: 'SF',
    label: 'Salesforce',
    title: 'Salesforce Connector (Data)',
    summary: 'CRM pipeline and customer context for prioritization insights.',
    sections: [
      {
        heading: 'Required Settings',
        body: [
          'Instance URL, client ID, client secret, and refresh token for OAuth-backed data pulls.',
        ],
      },
    ],
    links: [{ label: 'Open Connectors', href: '/connectors-manage' }],
  },
  snowflake: {
    short: 'SN',
    label: 'Snowflake',
    title: 'Snowflake Connector (Data)',
    summary: 'Governed warehouse metrics and trend extraction for enriched analysis.',
    sections: [
      {
        heading: 'Required Settings',
        body: [
          'Account, warehouse, database, schema, role, user credentials, and table allowlist.',
        ],
      },
    ],
    links: [{ label: 'Open Connectors', href: '/connectors-manage' }],
  },
  oracleFusion: {
    short: 'OF',
    label: 'Oracle Fusion',
    title: 'Oracle Fusion Connector (Data)',
    summary: 'ERP operations and finance context for enterprise planning decisions.',
    sections: [
      {
        heading: 'Required Settings',
        body: ['Base URL, username, password, optional business unit, sync mode, and policy.'],
      },
    ],
    links: [{ label: 'Open Connectors', href: '/connectors-manage' }],
  },
  serviceNow: {
    short: 'SV',
    label: 'ServiceNow',
    title: 'ServiceNow Connector (Data)',
    summary: 'Service and change metrics for execution risk visibility.',
    sections: [
      {
        heading: 'Required Settings',
        body: ['Instance URL, username, password, optional table allowlist, sync mode, and policy.'],
      },
    ],
    links: [{ label: 'Open Connectors', href: '/connectors-manage' }],
  },
  netSuite: {
    short: 'NS',
    label: 'NetSuite',
    title: 'NetSuite Connector (Data)',
    summary: 'Operational and finance trend context for tradeoff planning.',
    sections: [
      {
        heading: 'Required Settings',
        body: [
          'Account ID, consumer key/secret, token ID/secret, REST base URL, sync mode, and policy.',
        ],
      },
    ],
    links: [{ label: 'Open Connectors', href: '/connectors-manage' }],
  },
  billing: {
    short: 'BL',
    label: 'Billing and Usage',
    title: 'Billing and Usage',
    summary: 'Plan entitlement, credits, and access governance.',
    sections: [
      {
        heading: 'Scope',
        body: [
          'Billing determines feature access, connector eligibility, and model availability by plan.',
        ],
      },
    ],
    links: [{ label: 'Open Account', href: '/account' }],
  },
  api: {
    short: 'AP',
    label: 'API and Integrations',
    title: 'API and Integrations',
    summary: 'Programmatic access for sessions, connectors, reports, activity, and organization workflows.',
    sections: [
      {
        heading: 'Integration Pattern',
        body: [
          'Authenticate, read current state, apply explicit writes, then verify responses and audit logs.',
        ],
      },
    ],
    links: [{ label: 'Open API Console', href: '/pages/api' }],
  },
};

const TOPIC_GROUPS = [
  { label: 'Start Here', items: ['gettingStarted'] },
  {
    label: 'Core Features',
    items: [
      'agent',
      'components',
      'jaspenScore',
      'scenarioModeling',
      'projectPlansWbs',
      'aiDataInsights',
      'reportsGuide',
      'connectors',
      'teamManagement',
      'savedStarters',
    ],
  },
  {
    label: 'Connectors',
    items: ['jira', 'workfront', 'smartsheet', 'salesforce', 'snowflake', 'oracleFusion', 'serviceNow', 'netSuite'],
  },
  { label: 'Platform', items: ['billing', 'api'] },
];

function toSearchBlob(topic) {
  const sections = Array.isArray(topic?.sections) ? topic.sections : [];
  const sectionText = sections
    .map((section) => {
      const body = Array.isArray(section?.body) ? section.body.join(' ') : String(section?.body || '');
      const list = Array.isArray(section?.list) ? section.list.join(' ') : '';
      const steps = Array.isArray(section?.steps) ? section.steps.join(' ') : '';
      return `${section?.heading || ''} ${body} ${list} ${steps}`;
    })
    .join(' ');
  return `${topic?.title || ''} ${topic?.summary || ''} ${sectionText}`.toLowerCase();
}

export default function Knowledge() {
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false);
  const [activeTopicId, setActiveTopicId] = useState('gettingStarted');
  const [query, setQuery] = useState('');

  const normalizedQuery = query.trim().toLowerCase();

  const filteredGroups = useMemo(() => {
    return TOPIC_GROUPS.map((group) => {
      const items = group.items.filter((topicId) => {
        const topic = TOPICS[topicId];
        if (!topic) return false;
        if (!normalizedQuery) return true;
        return toSearchBlob(topic).includes(normalizedQuery);
      });
      return { ...group, items };
    }).filter((group) => group.items.length > 0);
  }, [normalizedQuery]);

  const visibleTopicIds = useMemo(
    () => filteredGroups.flatMap((group) => group.items),
    [filteredGroups]
  );

  useEffect(() => {
    if (!visibleTopicIds.length) return;
    if (!visibleTopicIds.includes(activeTopicId)) {
      setActiveTopicId(visibleTopicIds[0]);
    }
  }, [activeTopicId, visibleTopicIds]);

  const activeTopic = useMemo(() => {
    if (!visibleTopicIds.length) return null;
    return TOPICS[activeTopicId] || TOPICS[visibleTopicIds[0]];
  }, [activeTopicId, visibleTopicIds]);

  return (
    <div className="knowledge-page">
      <AppMenu />
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
            {filteredGroups.map((group) => (
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
            {!filteredGroups.length && !sidebarCollapsed && (
              <p className="knowledge-index-empty">No topics match your search.</p>
            )}
          </div>
        </aside>

        <main className="knowledge-main">
          <header className="knowledge-header">
            <p className="knowledge-eyebrow">Knowledge</p>
            <h1>Internal Product Documentation</h1>
            <p className="knowledge-header-summary">
              Contextual documentation for scoring, AI workflows, team collaboration, connectors, and operational setup.
            </p>
            <div className="knowledge-search-wrap">
              <input
                type="search"
                className="knowledge-search-input"
                placeholder="Search topics, summaries, and section content..."
                value={query}
                onChange={(event) => setQuery(event.target.value)}
                aria-label="Search knowledge topics"
              />
            </div>
          </header>

          {activeTopic ? (
            <article className="knowledge-topic" aria-live="polite">
              <header className="knowledge-topic-head">
                <h2>{activeTopic.title}</h2>
                <p>{activeTopic.summary}</p>
              </header>

              {(activeTopic.sections || []).map((section) => (
                <section key={`${activeTopic.title}-${section.heading}`} className="knowledge-doc-section">
                  <h3>{section.heading}</h3>
                  {(Array.isArray(section.body) ? section.body : [section.body])
                    .filter(Boolean)
                    .map((paragraph) => (
                      <p key={`${section.heading}-${paragraph}`}>{paragraph}</p>
                    ))}
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
                        <a href={link.href} className="knowledge-link">
                          {link.label}
                        </a>
                      </li>
                    ))}
                  </ul>
                </section>
              )}
            </article>
          ) : (
            <div className="knowledge-topic">
              <section className="knowledge-doc-section">
                <h3>No topics found</h3>
                <p>Try a broader keyword or clear the search field.</p>
              </section>
            </div>
          )}
        </main>
      </div>
    </div>
  );
}
