import type { JobApplicationDetail } from '@/lib/types'

// Seed data for designing the Job Application page (D-56) before the migration and a real
// detail endpoint exist (Phase 3 step list). Mirrors tests/fixtures/synthetic/job_applications.json
// so the two stay easy to compare; it is not read from that file to keep the API/web boundary
// untouched during this design pass.

type JobApplicationDetailBase = Pick<
  JobApplicationDetail,
  'id' | 'company' | 'role_title' | 'lane' | 'location' | 'status' | 'last_updated'
>

// match_score is mock data here too, not the table row's value: the dev database may predate
// this fixture's fields, and a design pass should show both the filled and the "not run yet"
// states regardless of what a given dev database currently holds (Phase 5 wires the real score).
type SampleDetail = Omit<JobApplicationDetail, keyof JobApplicationDetailBase>

const SAMPLES_BY_COMPANY: Record<string, SampleDetail> = {
  'Northwind Analytics': {
    queue_status: 'idle',
    match_score: 78.5,
    portal_name: 'Example Careers',
    portal_url: 'https://example.com/careers/1001',
    work_mode: 'Hybrid',
    contract_type: 'Full-Time',
    description:
      'Northwind Analytics is hiring a Data Analyst to support its retail reporting team. You will build dashboards, maintain data pipelines feeding weekly business reviews, and work with stakeholders to define new metrics.',
    requirements: [
      '3+ years in a data analyst or BI role',
      'Strong SQL and at least one BI tool (Power BI or Tableau)',
      'Comfortable presenting findings to non-technical stakeholders',
      'Experience with retail or e-commerce data is a plus',
    ],
    fit: [
      'Several years of hands-on SQL and dashboarding work line up directly with the core reporting responsibilities.',
      'Comfortable presenting to non-technical stakeholders, which the listing calls out explicitly.',
    ],
    gaps: [
      'No direct retail or e-commerce experience; the listing lists it as a plus, not a requirement.',
      "The listing doesn't say which BI tool is in use — confirm before the interview.",
    ],
    notes: 'Recruiter mentioned a short take-home exercise may follow the first screen.',
    next_action: 'Follow up on application',
    due_date: '2026-10-12',
    status_history: [
      { status: 'Identified', changed_at: '2026-09-28T09:00:00Z' },
      { status: 'Applied', changed_at: '2026-10-01T10:30:00Z' },
    ],
    files: [
      { name: 'listing.txt', kind: 'listing' },
      { name: 'Positioning breakdown.md', kind: 'positioning_breakdown' },
    ],
  },
  'Contoso Health': {
    queue_status: 'idle',
    match_score: 64.0,
    portal_name: 'Email',
    portal_url: null,
    work_mode: 'Remote',
    contract_type: 'Contract/Short Term',
    description:
      "A 6-month contract supporting Contoso Health's clinical operations reporting. Deliverables are a handful of recurring reports and one new quarterly dashboard.",
    requirements: [
      'Experience building recurring operational reports',
      'SQL and spreadsheet modelling',
      'Healthcare or another regulated industry background preferred',
    ],
    fit: ["Recurring report-building experience matches the contract's deliverables closely."],
    gaps: [
      'No healthcare or regulated-industry background, which the listing prefers.',
      'Contract length (6 months) is shorter than the roles usually targeted.',
    ],
    notes: null,
    next_action: 'Read listing and draft positioning',
    due_date: '2026-10-09',
    status_history: [{ status: 'Identified', changed_at: '2026-10-02T08:15:00Z' }],
    files: [
      { name: 'listing.txt', kind: 'listing' },
      { name: 'Positioning breakdown.md', kind: 'positioning_breakdown' },
    ],
  },
  'Fabrikam Logistics': {
    queue_status: 'processing',
    match_score: 81.0,
    portal_name: 'Example Jobs Board',
    portal_url: 'https://example.com/jobs/2002',
    work_mode: 'Onsite',
    contract_type: 'Full-Time',
    description:
      "Fabrikam Logistics is growing its ops analytics function. The role owns on-time delivery reporting and partners with the warehouse network on process improvements.",
    requirements: [
      'Analyst experience in logistics, supply chain or manufacturing',
      'Advanced Excel; SQL is a strong plus',
      'Comfortable on-site with warehouse operations teams',
      'Prior exposure to WMS or ERP data',
    ],
    fit: [
      'Ops analytics background in a comparable industry (manufacturing) matches well.',
      'Advanced Excel and some SQL cover the listed tools.',
    ],
    gaps: [
      'No direct WMS experience; the listing mentions a WMS migration as a current project.',
    ],
    notes:
      'Panel interview is with the ops director and two analysts. Ask about the WMS migration mentioned in the listing.',
    next_action: 'Prepare for panel interview',
    due_date: '2026-10-07',
    status_history: [
      { status: 'Identified', changed_at: '2026-09-20T09:00:00Z' },
      { status: 'Applied', changed_at: '2026-09-22T14:00:00Z' },
      { status: 'Screening', changed_at: '2026-09-29T11:00:00Z' },
      { status: 'Interview', changed_at: '2026-10-03T16:00:00Z' },
    ],
    files: [
      { name: 'listing.txt', kind: 'listing' },
      { name: 'Positioning breakdown.md', kind: 'positioning_breakdown' },
    ],
  },
  'Litware Finance': {
    queue_status: 'queued',
    match_score: null,
    portal_name: null,
    portal_url: null,
    work_mode: 'Unknown',
    contract_type: 'Unknown',
    description: null,
    requirements: [],
    fit: [],
    gaps: [],
    notes: null,
    next_action: null,
    due_date: null,
    status_history: [{ status: 'Identified', changed_at: '2026-10-04T07:45:00Z' }],
    files: [],
  },
  'Adatum Retail': {
    queue_status: 'idle',
    match_score: 55.0,
    portal_name: 'Email',
    portal_url: null,
    work_mode: 'Onsite',
    contract_type: 'Full-Time',
    description:
      "Adatum Retail sought a lead to run its customer insights function, owning a small analyst team and the roadmap for a new customer data platform.",
    requirements: [
      '5+ years in customer insights or CRM analytics',
      'People management experience',
      'Comfortable owning a roadmap, not just delivering reports',
    ],
    fit: ['Strong customer insights and CRM analytics background.'],
    gaps: [
      'No formal people-management experience, and the role leads a small team.',
      'Roadmap ownership experience so far has been in a supporting role, not the lead.',
    ],
    notes:
      'Rejected after the first screen: they wanted more hands-on people-management experience than this role has had so far.',
    next_action: null,
    due_date: null,
    status_history: [
      { status: 'Identified', changed_at: '2026-09-10T09:00:00Z' },
      { status: 'Applied', changed_at: '2026-09-12T09:00:00Z' },
      { status: 'Rejected', changed_at: '2026-09-25T13:00:00Z' },
    ],
    files: [
      { name: 'listing.txt', kind: 'listing' },
      { name: 'Positioning breakdown.md', kind: 'positioning_breakdown' },
    ],
  },
  'Tailspin Energy': {
    queue_status: 'failed',
    match_score: 70.0,
    portal_name: 'Example Careers',
    portal_url: 'https://example.com/careers/3003',
    work_mode: 'Hybrid',
    contract_type: 'Part-Time',
    description:
      "Part-time commercial analyst role (3 days/week) supporting Tailspin Energy's pricing team with margin analysis and competitor tracking.",
    requirements: [
      'Commercial or pricing analyst background',
      'Strong Excel modelling',
      'Energy sector experience is a plus, not required',
    ],
    fit: ['Commercial/pricing analyst background and strong Excel modelling match the core of the role.'],
    gaps: ['No energy-sector experience, though the listing says this is a plus, not required.'],
    notes: 'Confirm part-time hours are still 3 days/week before the next step.',
    next_action: 'Check for reply',
    due_date: '2026-10-15',
    status_history: [
      { status: 'Identified', changed_at: '2026-09-30T09:00:00Z' },
      { status: 'Applied', changed_at: '2026-10-01T09:00:00Z' },
    ],
    files: [
      { name: 'listing.txt', kind: 'listing' },
      { name: 'Positioning breakdown.md', kind: 'positioning_breakdown' },
    ],
  },
}

const FALLBACK_DETAIL: SampleDetail = {
  queue_status: 'idle',
  match_score: null,
  portal_name: null,
  portal_url: null,
  work_mode: 'Unknown',
  contract_type: 'Unknown',
  description: null,
  requirements: [],
  fit: [],
  gaps: [],
  notes: null,
  next_action: null,
  due_date: null,
  status_history: [],
  files: [],
}

// Merges a table row with its seed detail fields, by company (the seed fixture has one role per
// company). Falls back to empty detail fields for a row the sample set does not cover.
export function sampleDetailFor(app: JobApplicationDetailBase): JobApplicationDetail {
  const extra = SAMPLES_BY_COMPANY[app.company] ?? FALLBACK_DETAIL
  return { ...app, ...extra }
}
