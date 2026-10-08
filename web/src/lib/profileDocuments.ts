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
  full_cv_history: ['Master CVs', 'Older CVs', 'Older cover letters'],
  questionnaire_analysis: ['Questionnaire', 'Career history'],
  strategy: ['Questionnaire analysis', 'Career history'],
}
