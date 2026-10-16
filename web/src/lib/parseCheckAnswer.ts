// Reads the listing sanity check's answer client-side (job_pipeline.py's parse_check_answer,
// mirrored here): the job only carries a character count, not the text, until the exchange is
// fetched. Shared by AddJobOverlay and GenerateListingOverlay, which both show this check's
// result as part of their own wizard.
export type CheckAnswer = { looksLikePosting: boolean; reason: string }

export function parseCheckAnswer(text: string): CheckAnswer {
  const match = /LOOKS_LIKE_A_JOB_POSTING:\s*(yes|no)\b/i.exec(text)
  const looksLikePosting = match !== null && match[1].toLowerCase() === 'yes'
  const rest = match ? text.slice(match.index + match[0].length) : text
  const reason = rest
    .split('\n')
    .map((line) => line.trim())
    .find((line) => line.length > 0)
  return { looksLikePosting, reason: reason ?? '' }
}
