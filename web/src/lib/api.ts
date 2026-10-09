import type {
  ClaudeJob,
  FilePreviewData,
  JobApplication,
  JobApplicationDetailData,
  JobApplicationEdit,
  JobApplicationFile,
  ListingExtraction,
  ProfileFile,
  ProfileFileKind,
  ProfileOutput,
  PromptExchange,
  ReviseTurn,
  RunResult,
  Settings,
  StatusHistoryEntry,
} from '@/lib/types'

export class ApiError extends Error {
  readonly status: number | null

  constructor(message: string, status: number | null) {
    super(message)
    this.status = status
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let response: Response
  try {
    response = await fetch(path, init)
  } catch {
    throw new ApiError('The API is not reachable on 127.0.0.1:8765.', null)
  }
  // The dev proxy answers 502-504 when the API process is not listening.
  if (response.status >= 502 && response.status <= 504) {
    throw new ApiError('The API is not running on 127.0.0.1:8765.', response.status)
  }
  if (response.status === 401) {
    throw new ApiError('The API rejected the launch token. Restart the dev launcher.', 401)
  }
  if (!response.ok) {
    throw new ApiError(await errorMessage(response), response.status)
  }
  return (await response.json()) as T
}

// The API gives a reason in `detail` for refusals (for example a bad date). Show it when it is there.
async function errorMessage(response: Response): Promise<string> {
  const detail = await response
    .json()
    .then((body: { detail?: unknown }) => (typeof body.detail === 'string' ? body.detail : null))
    .catch(() => null)
  return detail ?? `The API returned HTTP ${response.status}.`
}

export function fetchJobApplications(): Promise<JobApplication[]> {
  return request<JobApplication[]>('/api/job-applications')
}

// The job page's full record for one application (D-113): everything GET /job-applications
// leaves out of the table row (job details, status history, files).
export function fetchJobApplicationDetail(id: number): Promise<JobApplicationDetailData> {
  return request<JobApplicationDetailData>(`/api/job-applications/${id}`)
}

// Saves one of the job page's Edit forms (D-116). Only the fields `edit` sets are written.
export function patchJobApplication(
  id: number,
  edit: JobApplicationEdit,
): Promise<JobApplicationDetailData> {
  return request<JobApplicationDetailData>(`/api/job-applications/${id}`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(edit),
  })
}

// Sets or clears the Master CV selector (D-116) — a reference to a Profile page master CV, not
// a copy.
export function setMasterCv(
  id: number,
  profileFileId: number | null,
): Promise<JobApplicationDetailData> {
  return request<JobApplicationDetailData>(`/api/job-applications/${id}/master-cv`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ profile_file_id: profileFileId }),
  })
}

// Replaces every stage date on Application history's timeline (D-117) — at most one entry per
// status, unlike status_history's append-only model elsewhere; the editor shows and edits one
// date per stage. The application's current status is recomputed server-side to match.
export function replaceStatusHistory(
  id: number,
  entries: StatusHistoryEntry[],
): Promise<JobApplicationDetailData> {
  return request<JobApplicationDetailData>(`/api/job-applications/${id}/status-history`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ entries }),
  })
}

// Sends the file's bytes to a Job Application's own files (D-116), the same way
// uploadProfileFile does.
export async function uploadJobFile(
  applicationId: number,
  kind: string,
  file: File,
): Promise<JobApplicationFile> {
  let response: Response
  try {
    response = await fetch(`/api/job-applications/${applicationId}/files/${kind}`, {
      method: 'POST',
      headers: { 'X-File-Name': encodeURIComponent(file.name) },
      body: file,
    })
  } catch {
    throw new ApiError('The API is not reachable on 127.0.0.1:8765.', null)
  }
  if (!response.ok) {
    throw new ApiError(await errorMessage(response), response.status)
  }
  return (await response.json()) as JobApplicationFile
}

// Opens one of a Job Application's own files in the program the system uses for it (D-116), the
// same way openProfileFile does. The API answers 204 with no body.
export async function openJobFile(applicationId: number, fileId: number): Promise<void> {
  let response: Response
  try {
    response = await fetch(`/api/job-applications/${applicationId}/files/${fileId}/open`, {
      method: 'POST',
    })
  } catch {
    throw new ApiError('The API is not reachable on 127.0.0.1:8765.', null)
  }
  if (!response.ok) {
    throw new ApiError(await errorMessage(response), response.status)
  }
}

// Reads the preview the API built for one of a Job Application's own files (D-116), the same
// way fetchProfileFilePreview does.
export async function fetchJobFilePreview(
  applicationId: number,
  fileId: number,
): Promise<FilePreviewData> {
  let response: Response
  try {
    response = await fetch(`/api/job-applications/${applicationId}/files/${fileId}/preview`)
  } catch {
    throw new ApiError('The API is not reachable on 127.0.0.1:8765.', null)
  }
  if (!response.ok) {
    throw new ApiError(await errorMessage(response), response.status)
  }
  const contentType = response.headers.get('content-type') ?? ''
  if (contentType.includes('application/pdf')) {
    return { kind: 'pdf', blob: await response.blob() }
  }
  if (contentType.includes('text/markdown')) {
    return { kind: 'markdown', text: await response.text() }
  }
  if (contentType.includes('text/html')) {
    return { kind: 'html', text: await response.text() }
  }
  return { kind: 'text', text: await response.text() }
}

// The Listing's three extraction routes (D-121, job-llm-steps.md): code-only, nothing saved.

export function extractListingFromUrl(id: number, url: string): Promise<ListingExtraction> {
  return request<ListingExtraction>(`/api/job-applications/${id}/listing/extract-url`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ url }),
  })
}

export function extractListingFromPaste(id: number, text: string): Promise<ListingExtraction> {
  return request<ListingExtraction>(`/api/job-applications/${id}/listing/extract-paste`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ text }),
  })
}

// Sends the file's bytes, the same way uploadJobFile does - nothing is saved server-side.
export async function extractListingFromUpload(
  id: number,
  file: File,
): Promise<ListingExtraction> {
  let response: Response
  try {
    response = await fetch(`/api/job-applications/${id}/listing/extract-upload`, {
      method: 'POST',
      headers: { 'X-File-Name': encodeURIComponent(file.name) },
      body: file,
    })
  } catch {
    throw new ApiError('The API is not reachable on 127.0.0.1:8765.', null)
  }
  if (!response.ok) {
    throw new ApiError(await errorMessage(response), response.status)
  }
  return (await response.json()) as ListingExtraction
}

// Queues the sanity check that runs automatically once extraction produces text (step 26).
export function checkListingText(id: number, text: string): Promise<ClaudeJob> {
  return request<ClaudeJob>(`/api/job-applications/${id}/listing/check`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ text }),
  })
}

// Queues the Listing's Generate (LLM) step on the reviewed text (step 27).
export function generateListing(
  id: number,
  method: ListingExtraction['method'],
  text: string,
): Promise<ClaudeJob> {
  return request<ClaudeJob>(`/api/job-applications/${id}/listing/generate`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ method, text }),
  })
}

// Steps 30-32 of job-llm-steps.md: each reads current stored data, so the request body is empty.

export function generateJobDetails(id: number): Promise<ClaudeJob> {
  return request<ClaudeJob>(`/api/job-applications/${id}/job-details/generate`, { method: 'POST' })
}

export function generatePositioning(id: number): Promise<ClaudeJob> {
  return request<ClaudeJob>(`/api/job-applications/${id}/positioning/generate`, { method: 'POST' })
}

export function generateApplicationHistory(id: number): Promise<ClaudeJob> {
  return request<ClaudeJob>(`/api/job-applications/${id}/application-history/generate`, {
    method: 'POST',
  })
}

// Steps 36-37 of job-llm-steps.md: Phase 5's primary goal, pulled forward (D-129).

export function generateTailoredCv(id: number): Promise<ClaudeJob> {
  return request<ClaudeJob>(`/api/job-applications/${id}/tailored-cv/generate`, {
    method: 'POST',
  })
}

export function generateCoverLetter(id: number): Promise<ClaudeJob> {
  return request<ClaudeJob>(`/api/job-applications/${id}/cover-letter/generate`, {
    method: 'POST',
  })
}

export function runClaudeCheck(): Promise<RunResult> {
  return request<RunResult>('/api/runs/check', { method: 'POST' })
}

export function fetchSettings(): Promise<Settings> {
  return request<Settings>('/api/settings')
}

export function saveSettings(userName: string): Promise<Settings> {
  return request<Settings>('/api/settings', {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ user_name: userName }),
  })
}

export function fetchProfileFiles(): Promise<ProfileFile[]> {
  return request<ProfileFile[]>('/api/profile/files')
}

// Sends the file's bytes. The name goes in a header, URL-encoded (the API decodes it).
// The API's own message (for example "already uploaded") is shown when it gives one.
export async function uploadProfileFile(kind: ProfileFileKind, file: File): Promise<ProfileFile> {
  let response: Response
  try {
    response = await fetch(`/api/profile/files/${kind}`, {
      method: 'POST',
      headers: { 'X-File-Name': encodeURIComponent(file.name) },
      body: file,
    })
  } catch {
    throw new ApiError('The API is not reachable on 127.0.0.1:8765.', null)
  }
  if (!response.ok) {
    throw new ApiError(await errorMessage(response), response.status)
  }
  return (await response.json()) as ProfileFile
}

export function startProfileAnalysis(): Promise<ClaudeJob> {
  return request<ClaudeJob>('/api/profile/analysis', { method: 'POST' })
}

// The newest version of each of the three generated documents, for the analysis overlay's
// right-hand panes (D-84, D-86).
export function fetchProfileOutputs(): Promise<ProfileOutput[]> {
  return request<ProfileOutput[]>('/api/profile/outputs')
}

// A Revise (LLM) conversation's turns so far, oldest first (D-106).
export function fetchReviseTurns(outputKind: string): Promise<ReviseTurn[]> {
  return request<ReviseTurn[]>(`/api/profile/revise/${outputKind}/turns`)
}

// Sends one chat message, which queues a new Claude Job for it (D-106).
export function postReviseTurn(outputKind: string, message: string): Promise<ReviseTurn> {
  return request<ReviseTurn>(`/api/profile/revise/${outputKind}/turns`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ message }),
  })
}

export function fetchClaudeJobs(): Promise<ClaudeJob[]> {
  return request<ClaudeJob[]>('/api/claude-jobs')
}

export function resumeClaudeJob(id: number): Promise<ClaudeJob> {
  return request<ClaudeJob>(`/api/claude-jobs/${id}/resume`, { method: 'POST' })
}

export function cancelClaudeJob(id: number): Promise<ClaudeJob> {
  return request<ClaudeJob>(`/api/claude-jobs/${id}/cancel`, { method: 'POST' })
}

export function fetchPromptExchange(jobId: number, position: number): Promise<PromptExchange> {
  return request<PromptExchange>(`/api/claude-jobs/${jobId}/prompts/${position}`)
}

// Opens the uploaded copy in the program the system uses for it. The API answers 204 with no body.
export async function openProfileFile(id: number): Promise<void> {
  let response: Response
  try {
    response = await fetch(`/api/profile/files/${id}/open`, { method: 'POST' })
  } catch {
    throw new ApiError('The API is not reachable on 127.0.0.1:8765.', null)
  }
  if (!response.ok) {
    throw new ApiError(await errorMessage(response), response.status)
  }
}

// Reads the preview the API built for one profile file (D-107), picked by its response's
// content type rather than the file's own extension, since the API decides what it could
// convert the file into.
export async function fetchProfileFilePreview(id: number): Promise<FilePreviewData> {
  let response: Response
  try {
    response = await fetch(`/api/profile/files/${id}/preview`)
  } catch {
    throw new ApiError('The API is not reachable on 127.0.0.1:8765.', null)
  }
  if (!response.ok) {
    throw new ApiError(await errorMessage(response), response.status)
  }
  const contentType = response.headers.get('content-type') ?? ''
  if (contentType.includes('application/pdf')) {
    return { kind: 'pdf', blob: await response.blob() }
  }
  if (contentType.includes('text/markdown')) {
    return { kind: 'markdown', text: await response.text() }
  }
  if (contentType.includes('text/html')) {
    return { kind: 'html', text: await response.text() }
  }
  return { kind: 'text', text: await response.text() }
}

// Removes an upload and its copy (D-82).
export async function deleteProfileFile(id: number): Promise<void> {
  let response: Response
  try {
    response = await fetch(`/api/profile/files/${id}`, { method: 'DELETE' })
  } catch {
    throw new ApiError('The API is not reachable on 127.0.0.1:8765.', null)
  }
  if (!response.ok) {
    throw new ApiError(await errorMessage(response), response.status)
  }
}
