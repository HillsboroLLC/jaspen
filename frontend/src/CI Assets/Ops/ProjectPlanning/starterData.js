// Comprehensive starter data for Project Planning component
// This will be used when no real data is available from the backend

export const STARTER_PLAN = {
  wbs: {
    items: [
      {
        id: 'phase_1',
        name: 'Initialization',
        children: [
          {
            id: 'task_1_1',
            name: 'Define scope & objectives',
            assignee: '',
            priority: '',
            status: 'todo',
            due_date: '2025-12-15',
            notes: '',
            lead_time_days: 3,
            completed: false
          },
          {
            id: 'task_1_2',
            name: 'Stakeholder alignment',
            assignee: '',
            priority: '',
            status: 'todo',
            due_date: '2025-12-18',
            notes: '',
            lead_time_days: 2,
            completed: false
          }
        ]
      },
      {
        id: 'phase_2',
        name: 'Execution',
        children: [
          {
            id: 'task_2_1',
            name: 'Build core features',
            assignee: '',
            priority: '',
            status: 'todo',
            due_date: '2026-01-10',
            notes: '',
            lead_time_days: 14,
            completed: false
          },
          {
            id: 'task_2_2',
            name: 'QA & UAT',
            assignee: '',
            priority: '',
            status: 'todo',
            due_date: '2026-01-20',
            notes: '',
            lead_time_days: 5,
            completed: false
          }
        ]
      }
    ]
  },
  timeline: {
    start_date: '2025-12-09',
    end_date: '2026-03-31',
    phases: [
      {
        id: 'timeline_1',
        name: 'Initialization',
        start_date: '2025-12-09',
        end_date: '2025-12-20',
        description: 'Project setup and planning phase',
        progress: 25
      },
      {
        id: 'timeline_2',
        name: 'Execution',
        start_date: '2025-12-21',
        end_date: '2026-01-31',
        description: 'Core development and implementation',
        progress: 10
      },
      {
        id: 'timeline_3',
        name: 'Testing & QA',
        start_date: '2026-02-01',
        end_date: '2026-02-28',
        description: 'Quality assurance and user acceptance testing',
        progress: 0
      },
      {
        id: 'timeline_4',
        name: 'Launch',
        start_date: '2026-03-01',
        end_date: '2026-03-31',
        description: 'Production deployment and go-live',
        progress: 0
      }
    ]
  },
  objectives: [
    {
      id: 'obj_1',
      title: 'Achieve Market Leadership',
      description: 'Establish our product as the leading solution in the target market segment',
      progress: 35,
      key_results: [
        { label: 'Market Share', value: '15%' },
        { label: 'Customer Satisfaction', value: '4.5/5.0' },
        { label: 'NPS Score', value: '45' }
      ]
    },
    {
      id: 'obj_2',
      title: 'Revenue Growth',
      description: 'Achieve significant revenue growth through market expansion',
      progress: 42,
      key_results: [
        { label: 'ARR Growth', value: '$2.5M' },
        { label: 'Customer Acquisition', value: '150 new customers' },
        { label: 'Retention Rate', value: '92%' }
      ]
    },
    {
      id: 'obj_3',
      title: 'Product Excellence',
      description: 'Deliver a best-in-class product experience',
      progress: 60,
      key_results: [
        { label: 'Feature Completion', value: '85%' },
        { label: 'Bug Resolution Rate', value: '95%' },
        { label: 'Performance Score', value: '98/100' }
      ]
    },
    {
      id: 'obj_4',
      title: 'Team Development',
      description: 'Build a high-performing, engaged team',
      progress: 50,
      key_results: [
        { label: 'Team Size', value: '25 members' },
        { label: 'Employee Satisfaction', value: '4.2/5.0' },
        { label: 'Skill Development', value: '40 certifications' }
      ]
    }
  ],
  stakeholders: [
    {
      id: 'stake_1',
      name: 'Jennifer Martinez',
      role: 'Chief Executive Officer',
      role_type: 'executive',
      email: 'jennifer.martinez@company.com',
      influence: 3
    },
    {
      id: 'stake_2',
      name: 'David Chen',
      role: 'Chief Technology Officer',
      role_type: 'executive',
      email: 'david.chen@company.com',
      influence: 3
    },
    {
      id: 'stake_3',
      name: 'Sarah Johnson',
      role: 'Product Manager',
      role_type: 'core_team',
      email: 'sarah.johnson@company.com',
      influence: 2
    },
    {
      id: 'stake_4',
      name: 'Michael Torres',
      role: 'Lead Developer',
      role_type: 'core_team',
      email: 'michael.torres@company.com',
      influence: 2
    },
    {
      id: 'stake_5',
      name: 'Emily Wang',
      role: 'UX Designer',
      role_type: 'core_team',
      email: 'emily.wang@company.com',
      influence: 2
    },
    {
      id: 'stake_6',
      name: 'Robert Kim',
      role: 'Marketing Director',
      role_type: 'core_team',
      email: 'robert.kim@company.com',
      influence: 2
    },
    {
      id: 'stake_7',
      name: 'Lisa Anderson',
      role: 'Key Customer - TechCorp',
      role_type: 'external',
      email: 'lisa.anderson@techcorp.com',
      influence: 2
    },
    {
      id: 'stake_8',
      name: 'James Wilson',
      role: 'Strategic Partner - CloudSys',
      role_type: 'external',
      email: 'james.wilson@cloudsys.com',
      influence: 1
    }
  ],
  risks: [
    {
      id: 'risk_1',
      name: 'Technical Complexity',
      category: 'Technical',
      likelihood: 'Medium',
      impact: 'High',
      severity: 'high',
      owner: 'David Chen',
      status: 'Monitoring',
      mitigation: 'Implement phased rollout with extensive testing at each stage. Maintain technical documentation and conduct regular code reviews.'
    },
    {
      id: 'risk_2',
      name: 'Resource Constraints',
      category: 'Resource',
      likelihood: 'High',
      impact: 'Medium',
      severity: 'medium',
      owner: 'Sarah Johnson',
      status: 'Mitigating',
      mitigation: 'Prioritize critical features, consider contractor support for peak periods, and maintain buffer in timeline.'
    },
    {
      id: 'risk_3',
      name: 'Market Competition',
      category: 'Market',
      likelihood: 'Medium',
      impact: 'Medium',
      severity: 'medium',
      owner: 'Robert Kim',
      status: 'Monitoring',
      mitigation: 'Continuous competitive analysis, focus on unique value proposition, and accelerate go-to-market strategy.'
    },
    {
      id: 'risk_4',
      name: 'Regulatory Changes',
      category: 'Compliance',
      likelihood: 'Low',
      impact: 'High',
      severity: 'medium',
      owner: 'Jennifer Martinez',
      status: 'Identified',
      mitigation: 'Engage legal counsel early, build compliance framework into product design, monitor regulatory developments.'
    },
    {
      id: 'risk_5',
      name: 'Integration Challenges',
      category: 'Technical',
      likelihood: 'Medium',
      impact: 'Medium',
      severity: 'medium',
      owner: 'Michael Torres',
      status: 'Mitigating',
      mitigation: 'Conduct integration testing early, maintain API documentation, establish fallback procedures.'
    }
  ],
  resources: {
    budget: {
      total: 500000,
      spent: 157000,
      items: [
        {
          category: 'Personnel',
          description: 'Salaries and contractor fees',
          amount: 250000
        },
        {
          category: 'Technology',
          description: 'Software licenses and infrastructure',
          amount: 100000
        },
        {
          category: 'Marketing',
          description: 'Campaign and promotional activities',
          amount: 75000
        },
        {
          category: 'Operations',
          description: 'Office and operational expenses',
          amount: 50000
        },
        {
          category: 'Contingency',
          description: 'Risk buffer and unexpected costs',
          amount: 25000
        }
      ]
    },
    team: [
      { name: 'Sarah Johnson', role: 'Product Manager', availability: '100%' },
      { name: 'Michael Torres', role: 'Lead Developer', availability: '100%' },
      { name: 'Emily Wang', role: 'UX Designer', availability: '80%' },
      { name: 'Robert Kim', role: 'Marketing Director', availability: '60%' }
    ]
  },
  documents: [
    {
      id: 'doc_1',
      filename: 'Project Charter.pdf',
      category: 'Planning',
      size: '2.4 MB',
      owner: 'Sarah Johnson',
      updated_at: '2025-12-01T10:00:00Z'
    },
    {
      id: 'doc_2',
      filename: 'Market Research Report.pdf',
      category: 'Research',
      size: '5.8 MB',
      owner: 'Robert Kim',
      updated_at: '2025-12-03T14:30:00Z'
    },
    {
      id: 'doc_3',
      filename: 'Technical Architecture.docx',
      category: 'Planning',
      size: '1.2 MB',
      owner: 'David Chen',
      updated_at: '2025-12-05T09:15:00Z'
    },
    {
      id: 'doc_4',
      filename: 'Brand Guidelines.pdf',
      category: 'Marketing',
      size: '8.5 MB',
      owner: 'Robert Kim',
      updated_at: '2025-11-28T16:45:00Z'
    },
    {
      id: 'doc_5',
      filename: 'User Personas.pptx',
      category: 'Research',
      size: '3.1 MB',
      owner: 'Emily Wang',
      updated_at: '2025-12-02T11:20:00Z'
    },
    {
      id: 'doc_6',
      filename: 'Legal Agreement Template.docx',
      category: 'Legal',
      size: '890 KB',
      owner: 'Jennifer Martinez',
      updated_at: '2025-11-25T13:00:00Z'
    },
    {
      id: 'doc_7',
      filename: 'Sprint Planning Notes.xlsx',
      category: 'Planning',
      size: '456 KB',
      owner: 'Sarah Johnson',
      updated_at: '2025-12-08T08:30:00Z'
    },
    {
      id: 'doc_8',
      filename: 'Stakeholder Meeting Minutes.docx',
      category: 'Meetings',
      size: '234 KB',
      owner: 'Sarah Johnson',
      updated_at: '2025-12-07T15:00:00Z'
    }
  ],
  assumptions: [
    'Market conditions remain stable throughout project duration',
    'Key team members remain available for project duration',
    'Technology stack remains current and supported',
    'Customer requirements do not significantly change'
  ],
  notes: {
    general: 'This is a comprehensive project plan generated from Market IQ analysis.',
    risks: 'Regular risk reviews scheduled bi-weekly',
    budget: 'Monthly budget reviews with finance team'
  }
};
