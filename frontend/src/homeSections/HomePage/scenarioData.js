/* Two distinct workplace perspectives — deliberately different shapes and
   language. #1 is a group meeting that stalls, then spills into a private 1:1.
   #2 is just two peers in a DM, circling a recurring meeting nobody can decide
   to keep. Each carries a `demo` config that drives the live Work-with-Jaspen
   workspace so it partners on that exact problem. */

export const SCENARIOS = [
  {
    id: 'financial-gap',
    title: 'Financial Gap to Plan',
    format: 'meeting',
    you: 'Marcus',
    tilt: { rx: 0, ry: 0 },
    people: {
      Marcus: { role: 'Sales', color: '#2f6f8f', initials: 'M' },
      Priya: { role: 'VP Finance', color: '#a0036c', initials: 'P' },
      Dana: { role: 'Operations', color: '#0f8a5f', initials: 'D' },
    },
    favorites: ['Priya', 'Dana'],
    group: [
      { from: 'Priya', text: "We're $2.4M under plan for Q3. I need a path to close it before the board call." },
      { from: 'Marcus', text: "Pipeline's there, deals just keep slipping. We could discount to pull a few forward." },
      { from: 'Dana', text: "Discounting again? That's exactly what crushed margin last quarter." },
      { from: 'Priya', text: "Then we trim marketing to make the number." },
      { from: 'Marcus', text: "That just pushes the gap into Q4. Same problem, later." },
      { from: 'Priya', text: "…let's pick this up again after lunch." },
    ],
    dmWith: 'Dana',
    dm: [
      { from: 'Marcus', text: "otw to the room. running behind, been in back-to-backs all morning 😮‍💨", early: true },
      { from: 'Dana', text: "ha, take your time", early: true },
      { from: 'Marcus', text: "ok be honest… we still don't know what we're going to do.", punch: true },
    ],
    demo: {
      prompt: "We're $2.4M under plan for Q3 and the board call is Friday. What do we actually do?",
      agent: "I pulled your CRM and finance data. The gap is real but closeable. I scored four ways to close it on impact, margin, and timing:",
      objectiveChips: [{ label: 'Balanced' }, { label: 'Close the gap', active: true }, { label: 'Speed to Market' }, { label: 'Growth' }],
      dataChips: [{ label: 'NetSuite' }, { label: 'Snowflake' }, { label: 'Salesforce', active: true }],
      criteria: ['Gap closed', 'Margin protected', 'Speed to Friday', 'Q4 risk'],
      scorecards: [
        { name: 'Accelerate renewals + re-time services', score: 87, tag: 'Strong', rec: true, crit: [8.5, 9.0, 7.5, 8.6] },
        { name: 'Discount late-stage deals', score: 64, tag: 'Fair', rec: false, crit: [7.2, 4.5, 8.6, 5.0] },
        { name: 'Cut marketing spend', score: 58, tag: 'Watch', rec: false, crit: [6.0, 7.0, 7.4, 3.5] },
        { name: 'Hold and explain to the board', score: 49, tag: 'Weak', rec: false, crit: [3.0, 9.2, 9.0, 6.0] },
      ],
      insights: [
        { label: 'Q3 gap to plan', value: '$2.4M' },
        { label: 'Board call', value: 'Friday' },
        { label: 'Closeable now', value: '~$2.1M', accent: true },
        { label: 'Margin risk', value: 'Low' },
      ],
      tradeoffEyebrow: 'Trade-offs · impact vs. margin vs. speed',
      tradeoffs: [
        { label: 'Accelerate renewals + re-time', score: 87, rec: true, dims: [{ label: 'Impact', level: 3, kind: 'egg' }, { label: 'Margin', level: 3, kind: 'amber' }, { label: 'Effort', level: 2, kind: 'slate' }] },
        { label: 'Discount late-stage deals', score: 64, rec: false, dims: [{ label: 'Impact', level: 2, kind: 'egg' }, { label: 'Margin', level: 1, kind: 'amber' }, { label: 'Effort', level: 1, kind: 'slate' }] },
        { label: 'Cut marketing spend', score: 58, rec: false, dims: [{ label: 'Impact', level: 2, kind: 'egg' }, { label: 'Margin', level: 2, kind: 'amber' }, { label: 'Effort', level: 1, kind: 'slate' }] },
        { label: 'Hold and explain', score: 49, rec: false, dims: [{ label: 'Impact', level: 1, kind: 'egg' }, { label: 'Margin', level: 3, kind: 'amber' }, { label: 'Effort', level: 1, kind: 'slate' }] },
      ],
      exec: { title: 'Accelerate renewals + re-time services', score: 87, tag: 'Excellent', meta: '2 phases · 3 tasks · starts this week' },
      plan: [
        {
          phase: 'Lock the number',
          tasks: [
            { name: 'Fast-track the 3 at-risk renewals', desc: 'CS engages the accounts; target signatures by Thursday.', owner: 'Dana · Ops', init: 'D', color: '#0f8a5f', date: 'Thu', pri: 'High' },
            { name: 'Re-time $0.4M services revenue into Q3', desc: 'Pull eligible services revenue forward per policy.', owner: 'Priya · Finance', init: 'P', color: '#a0036c', date: 'Wed', pri: 'High' },
          ],
        },
        {
          phase: 'Close the gap',
          tasks: [
            { name: 'Approve targeted discount on 2 deals', desc: 'Late-stage only. Stays inside the margin guardrail.', owner: 'Marcus · Sales', init: 'M', color: '#2f6f8f', date: 'Thu', pri: 'Medium' },
          ],
        },
      ],
    },
  },
  {
    id: 'meeting-value',
    title: 'Is this meeting worth keeping?',
    format: 'peer',
    you: 'Tess',
    tilt: { rx: 0, ry: 0 },
    people: {
      Tess: { role: 'Ops Lead', color: '#a0036c', initials: 'T' },
      Owen: { role: 'Strategy Lead', color: '#2f6f8f', initials: 'O' },
    },
    favorites: ['Owen'],
    dmWith: 'Owen',
    thread: [
      { from: 'Tess', text: "real q: is the biweekly workstream sync even worth keeping?" },
      { from: 'Owen', text: "honestly? not sure what it's even for anymore." },
      { from: 'Tess', text: "it's supposed to be progress updates. but progress is slow because we're stretched too thin." },
      { from: 'Owen', text: "right. the people who'd move the workstream are the same ones running the business all day." },
      { from: 'Tess', text: "and every time we try to decide whether to kill it, we go off topic and never land it." },
      { from: 'Owen', text: "the meeting about the meeting just gets rescheduled 😅" },
      { from: 'Tess', text: "and the question we never answer: is slow progress even better than no progress? or is there a smarter way to use the same people?", punch: true },
    ],
    demo: {
      prompt: "Should we keep our biweekly workstream sync? Progress is slow because the people delivering it also run the business, and we can't tell if slow progress beats no progress, or if there's a better way.",
      agent: "I looked at what the meeting actually produces, where this workstream's hours go, and who's on the hook. I scored four options on progress vs. the cost of everyone's time:",
      objectiveChips: [{ label: 'Balanced', active: true }, { label: 'Focus' }, { label: 'Speed to Market' }, { label: 'Growth' }],
      dataChips: [{ label: 'Calendar' }, { label: 'Slack' }, { label: 'Asana', active: true }],
      criteria: ['Workstream progress', 'Time cost', 'Decision clarity', 'Team load'],
      scorecards: [
        { name: 'Async updates + one protected focus block', score: 84, tag: 'Strong', rec: true, crit: [8.0, 8.8, 8.2, 8.6] },
        { name: 'Tighten to a 15-min decision-only check-in', score: 72, tag: 'Good', rec: false, crit: [6.8, 7.6, 8.5, 7.4] },
        { name: 'Pause the workstream until capacity frees up', score: 58, tag: 'Fair', rec: false, crit: [3.0, 9.2, 7.0, 9.0] },
        { name: 'Keep the biweekly as it is', score: 44, tag: 'Watch', rec: false, crit: [4.2, 3.0, 3.8, 3.2] },
      ],
      insights: [
        { label: 'Meeting cost', value: '~6 hrs/mo' },
        { label: 'Decisions made', value: 'rarely', accent: true },
        { label: 'Owner also runs', value: 'the business' },
        { label: 'Real blocker', value: 'capacity' },
      ],
      tradeoffEyebrow: 'Trade-offs · progress vs. time cost vs. focus',
      tradeoffs: [
        { label: 'Async + protected focus block', score: 84, rec: true, dims: [{ label: 'Progress', level: 3, kind: 'egg' }, { label: 'Time cost', level: 1, kind: 'amber' }, { label: 'Focus', level: 3, kind: 'slate' }] },
        { label: '15-min decision check-in', score: 72, rec: false, dims: [{ label: 'Progress', level: 2, kind: 'egg' }, { label: 'Time cost', level: 1, kind: 'amber' }, { label: 'Focus', level: 2, kind: 'slate' }] },
        { label: 'Pause the workstream', score: 58, rec: false, dims: [{ label: 'Progress', level: 1, kind: 'egg' }, { label: 'Time cost', level: 1, kind: 'amber' }, { label: 'Focus', level: 3, kind: 'slate' }] },
        { label: 'Keep as-is', score: 44, rec: false, dims: [{ label: 'Progress', level: 1, kind: 'egg' }, { label: 'Time cost', level: 3, kind: 'amber' }, { label: 'Focus', level: 1, kind: 'slate' }] },
      ],
      exec: { title: 'Async updates + protected focus block', score: 84, tag: 'Strong', meta: '2 phases · 3 steps · starts next cycle' },
      plan: [
        {
          phase: 'Replace the ritual',
          tasks: [
            { name: 'Swap the biweekly for an async update thread', desc: 'Owners post progress + blockers; no live meeting.', owner: 'Owen · Strategy', init: 'O', color: '#2f6f8f', date: 'Next cycle', pri: 'High' },
            { name: 'Add one monthly 20-min decision review', desc: 'Only to make the calls the async thread surfaces.', owner: 'Tess · Ops', init: 'T', color: '#a0036c', date: 'Monthly', pri: 'Medium' },
          ],
        },
        {
          phase: 'Protect the time',
          tasks: [
            { name: 'Block one focused half-day for the workstream', desc: 'So progress is real, not "slow vs. none."', owner: 'Tess · Ops', init: 'T', color: '#a0036c', date: 'Weekly', pri: 'High' },
          ],
        },
      ],
    },
  },
];
