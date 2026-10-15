import type {
  AddJobResult,
  AuthStatus,
  Backend,
  ClaudeJob,
  CreateJobApplicationRequest,
  DuplicateListingMatch,
  FilePreviewData,
  JobApplication,
  JobApplicationDetailData,
  JobApplicationEdit,
  JobApplicationFile,
  JobIdentityAnswer,
  ListingExtraction,
  LlmAppOpened,
  LlmAppStatus,
  ModelPrice,
  ParsedModelPrice,
  ProfileFile,
  ProfileFileKind,
  ProfileOutput,
  PromptExchange,
  ReviseTurn,
  RetryPolicy,
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
  // A 204 (DELETE routes) has no body - response.json() would throw trying to parse "".
  if (response.status === 204) {
    return undefined as T
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

// Shared by downloadJobFile and downloadProfileFile (D-160): fetches the file as a blob (so a
// failed request surfaces as a normal ApiError, instead of a browser-navigated 404 page) and
// saves it under its own name via a throwaway link, the same way a plain <a download> would.
async function downloadFile(path: string, name: string): Promise<void> {
  let response: Response
  try {
    response = await fetch(path)
  } catch {
    throw new ApiError('The API is not reachable on 127.0.0.1:8765.', null)
  }
  if (!response.ok) {
    throw new ApiError(await errorMessage(response), response.status)
  }
  const blob = await response.blob()
  const url = URL.createObjectURL(blob)
  const link = document.createElement('a')
  link.href = url
  link.download = name
  document.body.appendChild(link)
  link.click()
  link.remove()
  setTimeout(() => URL.revokeObjectURL(url), 0)
}

export function fetchJobApplications(): Promise<JobApplication[]> {
  return request<JobApplication[]>('/api/job-applications')
}

// The job page's full record for one application (D-113): everything GET /job-applications
// leaves out of the table row (job details, status history, files).
export function fetchJobApplicationDetail(id: number): Promise<JobApplicationDetailData> {
  return request<JobApplicationDetailData>(`/api/job-applications/${id}`)
}

// Removes the application and everything that belongs to it (status history, Claude Jobs, files,
// chat turns) - irreversible, confirmed by the caller before this is sent.
export async function deleteJobApplication(id: number): Promise<void> {
  let response: Response
  try {
    response = await fetch(`/api/job-applications/${id}`, { method: 'DELETE' })
  } catch {
    throw new ApiError('The API is not reachable on 127.0.0.1:8765.', null)
  }
  if (!response.ok) {
    throw new ApiError(await errorMessage(response), response.status)
  }
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

// Reveals one of a Job Application's own files in the system's file manager (D-160), the same
// way revealProfileFile does. The API answers 204 with no body.
export async function revealJobFile(applicationId: number, fileId: number): Promise<void> {
  let response: Response
  try {
    response = await fetch(`/api/job-applications/${applicationId}/files/${fileId}/reveal`, {
      method: 'POST',
    })
  } catch {
    throw new ApiError('The API is not reachable on 127.0.0.1:8765.', null)
  }
  if (!response.ok) {
    throw new ApiError(await errorMessage(response), response.status)
  }
}

export function downloadJobFile(applicationId: number, fileId: number, name: string): Promise<void> {
  return downloadFile(`/api/job-applications/${applicationId}/files/${fileId}/download`, name)
}

// Removes one of a Job Application's own files: the row and its copy on disk (D-211), the same
// way deleteProfileFile does.
export async function deleteJobFile(applicationId: number, fileId: number): Promise<void> {
  let response: Response
  try {
    response = await fetch(`/api/job-applications/${applicationId}/files/${fileId}`, {
      method: 'DELETE',
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

// Add Job's intake routes (Agent/specs/intake-steps.md): the same extraction, sanity check and
// duplicate detection as the existing-application Listing routes above, run before a row exists.

export function intakeExtractFromUrl(url: string): Promise<ListingExtraction> {
  return request<ListingExtraction>('/api/job-applications/intake/extract-url', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ url }),
  })
}

export function intakeExtractFromPaste(text: string): Promise<ListingExtraction> {
  return request<ListingExtraction>('/api/job-applications/intake/extract-paste', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ text }),
  })
}

export async function intakeExtractFromUpload(file: File): Promise<ListingExtraction> {
  let response: Response
  try {
    response = await fetch('/api/job-applications/intake/extract-upload', {
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

// Queues the same no-tools sanity check as the existing-application Listing routes, with no
// application yet (D-49's "linked to no application" case).
export function intakeCheckListingText(text: string): Promise<ClaudeJob> {
  return request<ClaudeJob>('/api/job-applications/intake/check', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ text }),
  })
}

// D-146: checked before any Claude call runs. null means no match.
export function intakeDuplicateCheck(
  text: string,
  sourceUrl: string | null,
): Promise<DuplicateListingMatch | null> {
  return request<DuplicateListingMatch | null>('/api/job-applications/intake/duplicate-check', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ text, source_url: sourceUrl }),
  })
}

// Queues extract_job_identity (D-145): company/role/lane/location/portal, before a row exists.
export function intakeExtractIdentity(text: string): Promise<ClaudeJob> {
  return request<ClaudeJob>('/api/job-applications/intake/identity', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ text }),
  })
}

// Reads back and parses the identity job's answer once it is done. Throws (ApiError, 400) if
// the answer was rejected (no identifiable company or role title) - the overlay falls back to
// manual entry.
export function fetchIntakeIdentityResult(jobId: number): Promise<JobIdentityAnswer> {
  return request<JobIdentityAnswer>(`/api/job-applications/intake/identity/${jobId}`)
}

// Creates the row and queues the rest of the chosen workflow (D-143 to D-146).
export function createJobApplication(body: CreateJobApplicationRequest): Promise<AddJobResult> {
  return request<AddJobResult>('/api/job-applications', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
}

// Steps 30-32 of job-llm-steps.md: each reads current stored data, so the request body is empty.

export function generateJobDetails(id: number): Promise<ClaudeJob> {
  return request<ClaudeJob>(`/api/job-applications/${id}/job-details/generate`, { method: 'POST' })
}

export function generatePositioning(id: number): Promise<ClaudeJob> {
  return request<ClaudeJob>(`/api/job-applications/${id}/positioning/generate`, { method: 'POST' })
}

// Positioning analysis's Edit dialog "Clear all" (D-208): also wipes match_score, the per-
// requirement scores and the breakdown document - not a PATCH, since none of those are fields
// an Edit form may touch.
export function clearPositioning(id: number): Promise<JobApplicationDetailData> {
  return request<JobApplicationDetailData>(`/api/job-applications/${id}/positioning/clear`, {
    method: 'POST',
  })
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

// Step 13 of job-llm-steps.md §7 (D-166): Interview preparation, added after Phase 4's step list
// was already approved.
export function generateInterviewPrep(id: number): Promise<ClaudeJob> {
  return request<ClaudeJob>(`/api/job-applications/${id}/interview-prep/generate`, {
    method: 'POST',
  })
}

// Checks whichever backend and model are currently selected (D-195, D-206).
export function runLlmCheck(): Promise<RunResult> {
  return request<RunResult>('/api/runs/check', { method: 'POST' })
}

// "Open LLM app" (D-202, D-210): rebuilds the full-data export and launches it in whichever
// desktop app the selected backend (D-195) points at.
export function openLlmApp(): Promise<LlmAppOpened> {
  return request<LlmAppOpened>('/api/llm-app/open', { method: 'POST' })
}

// Whether each backend's desktop app is installed (D-210) - checked fresh each call, so the
// button can be disabled for whichever one isn't.
export function fetchLlmAppStatus(): Promise<Record<Backend, LlmAppStatus>> {
  return request<Record<Backend, LlmAppStatus>>('/api/llm-app/status')
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

// Saves the Phase 7 fields (D-195, D-201) alongside the current name, which PUT /settings
// always requires - the other fields are optional there and keep their stored value if left out.
export function saveBackendSettings(
  userName: string,
  fields: {
    backend: Backend
    retry_policy: RetryPolicy
    retry_interval_minutes: number
    retry_max_attempts: number
    claude_code_model: string
    codex_model: string
  },
): Promise<Settings> {
  return request<Settings>('/api/settings', {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ user_name: userName, ...fields }),
  })
}

export function fetchModelPrices(): Promise<ModelPrice[]> {
  return request<ModelPrice[]>('/api/settings/prices')
}

export function saveModelPrice(
  provider: Backend,
  model: string,
  fields: { input_price_per_token: number; output_price_per_token: number },
): Promise<ModelPrice> {
  return request<ModelPrice>(
    `/api/settings/prices/${encodeURIComponent(provider)}/${encodeURIComponent(model)}`,
    {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(fields),
    },
  )
}

// Confirms a proposed table (or several hand-edited rows) in one call (D-198).
export function saveModelPrices(rows: ModelPrice[]): Promise<ModelPrice[]> {
  return request<ModelPrice[]>('/api/settings/prices', {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(
      rows.map(({ provider, model, input_price_per_token, output_price_per_token }) => ({
        provider,
        model,
        input_price_per_token,
        output_price_per_token,
      })),
    ),
  })
}

// Fixes a stored model id's spelling in place, keeping its prices (D-198's "editing by hand").
export function renameModelPrice(
  provider: Backend,
  model: string,
  newModel: string,
): Promise<ModelPrice> {
  return request<ModelPrice>(
    `/api/settings/prices/${encodeURIComponent(provider)}/${encodeURIComponent(model)}/rename`,
    {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ new_model: newModel }),
    },
  )
}

export async function deleteModelPrice(provider: Backend, model: string): Promise<void> {
  await request<void>(
    `/api/settings/prices/${encodeURIComponent(provider)}/${encodeURIComponent(model)}`,
    { method: 'DELETE' },
  )
}

export function fetchPricingUrls(): Promise<Record<Backend, string | null>> {
  return request<Record<Backend, string | null>>('/api/settings/pricing-urls')
}

export function savePricingUrl(
  provider: Backend,
  pricingUrl: string | null,
): Promise<Record<string, string | null>> {
  return request<Record<string, string | null>>(
    `/api/settings/pricing-urls/${encodeURIComponent(provider)}`,
    {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ pricing_url: pricingUrl }),
    },
  )
}

export function fetchPricesFromProvider(provider: Backend): Promise<ClaudeJob> {
  return request<ClaudeJob>(`/api/settings/prices/${encodeURIComponent(provider)}/fetch`, {
    method: 'POST',
  })
}

export function fetchPricesResult(provider: Backend, jobId: number): Promise<ParsedModelPrice[]> {
  return request<ParsedModelPrice[]>(
    `/api/settings/prices/${encodeURIComponent(provider)}/fetch/${jobId}`,
  )
}

export function fetchAuthStatus(): Promise<Record<Backend, AuthStatus>> {
  return request<Record<Backend, AuthStatus>>('/api/settings/auth-status')
}

export function logoutBackend(backend: Backend): Promise<AuthStatus> {
  return request<AuthStatus>(`/api/settings/${encodeURIComponent(backend)}/logout`, {
    method: 'POST',
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

// A job-page section's chat-revise conversation so far, oldest first (D-136). The turn shape is
// the same as a profile ReviseTurn's, just scoped to one application and one section instead of
// one output kind.
export function fetchJobReviseTurns(
  applicationId: number,
  sectionKind: string,
): Promise<ReviseTurn[]> {
  return request<ReviseTurn[]>(`/api/job-applications/${applicationId}/revise/${sectionKind}/turns`)
}

// `attachmentJobFileId` is a job_files row already filed before this call (D-138, Application
// history only so far) - the file itself is uploaded through uploadJobFile, not here.
export function postJobReviseTurn(
  applicationId: number,
  sectionKind: string,
  message: string,
  attachmentJobFileId?: number,
): Promise<ReviseTurn> {
  return request<ReviseTurn>(`/api/job-applications/${applicationId}/revise/${sectionKind}/turns`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ message, attachment_job_file_id: attachmentJobFileId ?? null }),
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

// Reveals the uploaded copy in the system's file manager (D-160). The API answers 204 with no body.
export async function revealProfileFile(id: number): Promise<void> {
  let response: Response
  try {
    response = await fetch(`/api/profile/files/${id}/reveal`, { method: 'POST' })
  } catch {
    throw new ApiError('The API is not reachable on 127.0.0.1:8765.', null)
  }
  if (!response.ok) {
    throw new ApiError(await errorMessage(response), response.status)
  }
}

export function downloadProfileFile(id: number, name: string): Promise<void> {
  return downloadFile(`/api/profile/files/${id}/download`, name)
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
