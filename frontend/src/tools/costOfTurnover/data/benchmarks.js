// =====================================================
// Cost of Turnover — Benchmark Library
// Source of truth: docs/marketing/"Utility_Lead - Cost_of_Turnover (refined).xlsx"
//   sheet "05 Benchmark Library" (methodology v1.0, frozen).
//
// Every record carries full provenance so the results page can show source,
// year, methodology, limitation, and benchmark type without a code rewrite.
// Benchmarks can be re-versioned by bumping BENCHMARK_VERSION and editing values
// here; no calculation code needs to change.
//
// Two provenance classes are preserved and must never be conflated:
//   - 'published'  Published Benchmark  — a value directly measured and
//                  published by an authoritative source for the same variable.
//   - 'research'   Research-Based Estimate — a value Jaspen derives through
//                  documented methodology from credible published research when
//                  no direct benchmark exists for the exact variable.
// =====================================================

export const BENCHMARK_VERSION = '1.0.0';
export const METHODOLOGY_VERSION = '1.0';

// Provenance classes (used by the engine + Built Using composition).
export const PROVENANCE = {
  PUBLISHED: 'published', // Published Benchmark
  RESEARCH: 'research', // Research-Based Estimate
  ORG: 'org', // Your Organization's Inputs
};

export const PROVENANCE_LABEL = {
  published: 'Published Benchmark',
  research: 'Research-Based Estimate',
  org: "Your Organization's Inputs",
};

// Reliability tiers, as defined in the workbook's "How We Built These Estimates".
export const RELIABILITY = {
  A_PRIMARY: 'A — Primary',
  B_PROXY: 'B — Research-based proxy',
  C_SECONDARY: 'C — Secondary citation',
};

// A benchmark record. `type` is the user-facing classification and is the field
// the results page uses to label a value as a Published Benchmark vs a
// Research-Based Estimate. Do not derive one from the other.
function bench(record) {
  return {
    status: 'Adopted',
    effectiveDate: '2026-07-16',
    lastReviewed: '2026-07',
    ...record,
  };
}

export const BENCHMARKS = {
  // ---- Published Benchmarks (direct measurements) -------------------------
  B001: bench({
    id: 'B001',
    variable: 'Cost per hire',
    segment: 'Nonexecutive',
    value: 5475,
    unit: 'USD per hire',
    type: PROVENANCE.PUBLISHED,
    reliability: RELIABILITY.A_PRIMARY,
    source: 'SHRM',
    sourceUrl:
      'https://www.shrm.org/about/press-room/shrm-releases-2025-benchmarking-reports--how-does-your-organizat',
    year: '2025',
    methodology:
      'Average recruiting spend per hire across U.S. industries and organization sizes (SHRM 2025 benchmarking survey).',
    limitation:
      'Survey average across industries and sizes; the exact cost components included vary by respondent.',
  }),
  B002: bench({
    id: 'B002',
    variable: 'Cost per hire',
    segment: 'Executive',
    value: 35879,
    unit: 'USD per hire',
    type: PROVENANCE.PUBLISHED,
    reliability: RELIABILITY.A_PRIMARY,
    source: 'SHRM',
    sourceUrl:
      'https://www.shrm.org/about/press-room/shrm-releases-2025-benchmarking-reports--how-does-your-organizat',
    year: '2025',
    methodology: 'Average executive cost per hire (SHRM 2025 benchmarking survey).',
    limitation: 'Executive average; smaller sample and wide variation by function.',
  }),
  B003: bench({
    id: 'B003',
    variable: 'Time to fill',
    segment: 'Nonexecutive',
    value: 39,
    unit: 'calendar days',
    type: PROVENANCE.PUBLISHED,
    reliability: RELIABILITY.A_PRIMARY,
    source: 'SHRM',
    sourceUrl: 'https://www.shrm.org/topics-tools/research/recruiting-benchmarking',
    year: '2026',
    methodology: 'Median non-executive time to fill (SHRM recruiting benchmarking).',
    limitation: 'Median; varies by role, seniority, and labor market.',
  }),
  B004: bench({
    id: 'B004',
    variable: 'Time to fill',
    segment: 'Executive',
    value: 45,
    unit: 'calendar days',
    // Research-Based: SHRM describes executive fill as "about a month and a half";
    // used as an approximation until an exact licensed figure is obtained.
    type: PROVENANCE.RESEARCH,
    reliability: RELIABILITY.B_PROXY,
    status: 'Under Review',
    source: 'SHRM (approximation)',
    sourceUrl:
      'https://www.shrm.org/executive-network/insights/people-strategy/state-of-recruiting-2025-insights-to-maximize-recruitment',
    year: '2025',
    methodology:
      'SHRM describes executive fill as roughly a month and a half; used as a research-based approximation until an exact licensed figure is obtained.',
    limitation:
      'Approximation ("about a month and a half"); replace with a licensed exact figure before public claims.',
  }),
  B006: bench({
    id: 'B006',
    variable: 'Fully loaded compensation multiplier',
    segment: 'National private industry',
    value: 1.430615,
    unit: 'salary multiplier',
    type: PROVENANCE.PUBLISHED,
    reliability: RELIABILITY.A_PRIMARY,
    source: 'BLS ECEC',
    sourceUrl: 'https://www.bls.gov/news.release/pdf/ecec.pdf',
    year: 'March 2026',
    methodology:
      'Derived directly from the published ECEC wage share: wages/salaries are 69.9% of total employer compensation, so the loaded multiplier is 1 / 0.699.',
    limitation:
      'Derived from the national private-industry average; a company-specific loaded rate may differ.',
  }),
  B023: bench({
    id: 'B023',
    variable: 'Share of role knowledge unique to the individual',
    segment: 'All knowledge roles',
    value: 0.42,
    unit: 'percent',
    type: PROVENANCE.PUBLISHED,
    reliability: RELIABILITY.A_PRIMARY,
    source: 'Panopto',
    sourceUrl:
      'https://www.panopto.com/company/news/inefficient-knowledge-sharing-costs-large-businesses-47-million-per-year/',
    year: '2018 (n=1,001)',
    methodology:
      'Published survey measure: ~42% of a role’s institutional knowledge is unique to the person who holds it.',
    limitation: 'Self-reported survey; single study (n=1,001).',
  }),

  // ---- Research-Based Estimates (documented derivations) -----------------
  B015: bench({
    id: 'B015',
    variable: 'Uncovered work during vacancy',
    segment: 'All roles',
    value: 0.5,
    unit: 'percent',
    type: PROVENANCE.RESEARCH,
    reliability: RELIABILITY.B_PROXY,
    status: 'Under Review',
    source: 'Jaspen structural assumption',
    sourceUrl: '',
    year: 'n/a',
    methodology:
      'No published benchmark exists for how much vacant work goes uncovered. This is a structural model assumption exposed so users set it for their own situation.',
    limitation:
      'No published basis — a structural model assumption. Must be user-set or validated; not for public claims.',
  }),
  B016: bench({
    id: 'B016',
    variable: 'Average productivity during ramp',
    segment: 'All roles',
    value: 0.6,
    unit: 'percent',
    type: PROVENANCE.RESEARCH,
    reliability: RELIABILITY.B_PROXY,
    status: 'Under Review',
    source: 'Ramp / onboarding research (Gallup)',
    sourceUrl:
      'https://www.gallup.com/workplace/246242/essential-ingredients-effective-onboarding-program.aspx',
    year: '2024',
    methodology:
      'Derived from onboarding/ramp research showing new hires operate well below full output during ramp. Represents the average of a gradual ramp curve; the model applies the productivity gap, so the full period is not treated as lost.',
    limitation: 'Averaged from ramp/onboarding research; varies materially by role complexity.',
  }),
  B017: bench({
    id: 'B017',
    variable: 'Ramp-up duration',
    segment: 'Manager / corporate knowledge role',
    value: 8,
    unit: 'months',
    type: PROVENANCE.RESEARCH,
    reliability: RELIABILITY.A_PRIMARY,
    source: 'Gallup',
    sourceUrl:
      'https://www.gallup.com/workplace/246242/essential-ingredients-effective-onboarding-program.aspx',
    year: '2024',
    methodology:
      'Anchored to Gallup 2024 median time to full productivity (8.2 months, mid-level professionals), rounded to 8. Combined with the productivity gap, not full cost: 8 months × ~40% gap ≈ 3.2 month-equivalents lost.',
    limitation:
      'Gallup median is for mid-level professionals; full range across roles is ~5–12 months.',
  }),
  B018: bench({
    id: 'B018',
    variable: 'Direct onboarding / training cost',
    segment: 'Nonexecutive',
    value: 2500,
    unit: 'USD per hire',
    type: PROVENANCE.RESEARCH,
    reliability: RELIABILITY.C_SECONDARY,
    status: 'Future Research',
    source: 'Jaspen placeholder',
    sourceUrl: '',
    year: 'TBD',
    methodology:
      'No robust public benchmark for direct onboarding/training cash cost per hire. Placeholder pending an organization value or a licensed benchmark.',
    limitation: 'Weak default; replace with your organization value or a validated benchmark.',
  }),
  B019: bench({
    id: 'B019',
    variable: 'Knowledge transfer time',
    segment: 'Manager / knowledge role',
    value: 40,
    unit: 'total employee hours',
    type: PROVENANCE.RESEARCH,
    reliability: RELIABILITY.B_PROXY,
    source: 'HR handover practice (Enboarder / SHRM)',
    sourceUrl: 'https://enboarder.com/blog/checklist-knowledge-transfer/',
    year: '2018–2025',
    methodology:
      'Anchored to typical planned handover practice (2–4 weeks for ICs; 30–90 days senior). Includes source and recipient time. Applies only when a departure is planned.',
    limitation: 'Practitioner consensus, not a controlled study; applies only when a departure is planned.',
  }),
  B020: bench({
    id: 'B020',
    variable: 'Context rediscovery time',
    segment: 'Manager / knowledge role',
    value: 130,
    unit: 'working hours',
    type: PROVENANCE.RESEARCH,
    reliability: RELIABILITY.B_PROXY,
    source: 'APQC / McKinsey',
    sourceUrl:
      'https://www.apqc.org/blog/km-makes-knowledge-workers-more-productive-and-less-stressed-out',
    year: '2021 / MGI',
    methodology:
      'Derived from published research on time knowledge workers spend searching for and recreating information (APQC 8.2 hrs/wk, n=982; McKinsey 9.3 hrs/wk): ~4 hrs/wk incremental across a ~33-week ramp ≈ 130 hours, counted only where incremental to the normal ramp curve.',
    limitation:
      'Ongoing per-worker averages used as a proxy; must strip overlap with the ramp-up productivity gap.',
  }),
  B021: bench({
    id: 'B021',
    variable: 'Institutional-memory reconstruction',
    segment: 'Manager / knowledge role',
    value: 60,
    unit: 'coworker / leader hours',
    type: PROVENANCE.RESEARCH,
    reliability: RELIABILITY.A_PRIMARY,
    source: 'Panopto',
    sourceUrl:
      'https://www.panopto.com/company/news/inefficient-knowledge-sharing-costs-large-businesses-47-million-per-year/',
    year: '2018 (n=1,001)',
    methodology:
      'Anchored to Panopto: knowledge workers lose 5.3 hrs/wk waiting for or recreating colleagues’ knowledge. Applied as affected coworkers × weeks × a share of that rate.',
    limitation: 'Derived from a per-worker rate; number of helpers and hours varies by role.',
  }),
  B022: bench({
    id: 'B022',
    variable: 'Project disruption hours',
    segment: 'Per affected project',
    value: 24,
    unit: 'team hours',
    type: PROVENANCE.RESEARCH,
    reliability: RELIABILITY.B_PROXY,
    status: 'Under Review',
    source: 'Cost-of-vacancy / PMI',
    sourceUrl: 'https://builtin.com/recruiting/cost-of-vacancy',
    year: '2012–2024',
    methodology:
      'Labor-only proxy, sanity-checked against cost-of-vacancy analyses (~$500–$1,154/day) and PMI (24% of orgs delayed an initiative due to talent constraints). Excludes speculative project-value loss.',
    limitation: 'Labor-only proxy; excludes speculative lost project value.',
  }),
  B024: bench({
    id: 'B024',
    variable: 'Documentation coverage (explicit share of knowledge)',
    segment: 'All organizations',
    value: 0.25,
    unit: 'percent',
    type: PROVENANCE.RESEARCH,
    reliability: RELIABILITY.C_SECONDARY,
    status: 'Under Review',
    source: 'Gartner',
    sourceUrl:
      'https://www.gartner.com/en/information-technology/glossary/km-knowledge-management',
    year: '2024',
    methodology:
      'Gartner estimates 70–80% of enterprise knowledge is tacit (undocumented), implying ~20–30% explicit. Used for context/messaging, not as a per-departure default.',
    limitation:
      'Estimate range reached via secondary citation — verify the primary source before public claims.',
  }),
};

// Model conventions (not benchmarks — fixed structural constants).
export const MODEL_CONSTANTS = {
  workingDaysPerYear: 260,
  hoursPerYear: 2080,
  monthsPerYear: 12,
  workingDayConversion: 5 / 7, // calendar days -> working days
};

// Marketing / context facts (headline stats — never a per-departure default).
export const CONTEXT_STATS = {
  uniqueKnowledge: BENCHMARKS.B023, // 42% unique to the individual
  tacitKnowledge: BENCHMARKS.B024, // ~70-80% tacit
};

export function getBenchmark(id) {
  return BENCHMARKS[id] || null;
}
