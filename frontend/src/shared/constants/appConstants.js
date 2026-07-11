export const PLAN_ORDER = ['free', 'starter', 'essential', 'team', 'enterprise'];

export const PLAN_RANK = {
  free: 0,
  starter: 1,
  essential: 2,
  team: 3,
  enterprise: 4,
};

export const ROLE_OPTIONS = ['owner', 'admin', 'creator', 'collaborator', 'viewer'];
export const INVITE_ROLE_OPTIONS = ['admin', 'creator', 'collaborator', 'viewer'];

export const ONBOARDING_ROLE_OPTIONS = [
  { key: 'executive', label: 'Executive', description: 'I need quick tradeoff visibility, confidence, and decision-ready outputs.' },
  { key: 'pm', label: 'PM', description: 'I need sequencing, dependencies, ownership, and delivery risk surfaced clearly.' },
  { key: 'analyst', label: 'Analyst', description: 'I need structured evidence, assumptions, and a clean scoring rationale.' },
  { key: 'other', label: 'Other', description: 'I want Jaspen to adapt as we learn more about how I work.' },
];

export const EVALUATION_OPTIONS = [
  { key: 'new_initiative', label: 'New initiative', description: 'Shape a fresh project or investment from first principles.' },
  { key: 'cost_optimization', label: 'Cost optimization', description: 'Find waste, tighten spend, and protect margin.' },
  { key: 'growth_strategy', label: 'Growth strategy', description: 'Prioritize expansion bets, upside, and leverage points.' },
  { key: 'operational_improvement', label: 'Operational improvement', description: 'Improve throughput, execution quality, and handoffs.' },
];
