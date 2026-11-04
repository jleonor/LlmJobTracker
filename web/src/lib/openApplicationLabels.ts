// Shared Open Application display constants (D-249). Previously declared separately in
// OpenApplicationsPage.tsx, OpenApplicationDetailPage.tsx and AddOpenApplicationOverlay.tsx;
// centralized here once openApplicationColumns.tsx (Phase 17, D-298) needed the same map a
// fourth time, mirroring how lib/backends.ts centralizes LLM_APP_LABELS.
export const TARGET_TYPE_LABELS: Record<string, string> = {
  talent_pool: 'Talent pool',
  unsolicited: 'Unsolicited CV drop',
  cold_outreach: 'Cold outreach',
}
