// The three documents the profile analysis writes (D-86), and what's shown about each one in
// the analysis overlay and the revise overlay alike.

export const PROFILE_DOCUMENT_ORDER = ['full_cv_history', 'questionnaire_analysis', 'strategy'] as const

export const PROFILE_DOCUMENT_TITLES: Record<string, string> = {
  full_cv_history: 'Career history',
  questionnaire_analysis: 'Questionnaire report',
  strategy: 'Strategy',
}

// What is in context for each document, read by its generating prompt (profile_pipeline.py's
// inputs_for) and its Revise (LLM) prompt alike (Agent/specs/revise-steps.md) — shown as chips
// so the user can see what the model reads without opening the prompt itself.
export const PROFILE_DOCUMENT_CONTEXT: Record<string, string[]> = {
  full_cv_history: ['Master CVs', 'Older CVs', 'Older cover letters', 'Additional files'],
  questionnaire_analysis: ['Questionnaire', 'Career history'],
  strategy: ['Questionnaire analysis', 'Career history'],
}

// Career history's evidence, by kind (profile_pipeline.py's EVIDENCE_KINDS, minus
// own_full_cv_history, which isn't a file group - D-261). Revise (LLM) only: a turn may exclude
// one or more of these groups (D-260), shown as the same badges PROFILE_DOCUMENT_CONTEXT already
// uses for full_cv_history, made clickable.
export const CAREER_HISTORY_EVIDENCE_GROUPS: { kind: string; label: string }[] = [
  { kind: 'master_cv', label: 'Master CVs' },
  { kind: 'older_cv', label: 'Older CVs' },
  { kind: 'older_letter', label: 'Older cover letters' },
  { kind: 'additional_file', label: 'Additional files' },
]
