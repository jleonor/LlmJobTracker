import { useEffect, useRef, useState } from 'react'

import { MarkdownDocument } from '@/components/app/MarkdownDocument'
import { RunTrace } from '@/components/app/RunTrace'
import { Button } from '@/components/ui/button'
import { Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { Textarea } from '@/components/ui/textarea'
import {
  ApiError,
  checkListingText,
  extractListingFromPaste,
  extractListingFromUpload,
  extractListingFromUrl,
  fetchJobFilePreview,
  fetchPromptExchange,
  generateListing,
} from '@/lib/api'
import { useClaudeJobs } from '@/lib/useClaudeJobs'
import type { JobApplicationFile, ListingExtraction } from '@/lib/types'

type Method = ListingExtraction['method']
type Stage = 'source' | 'review' | 'running'

// Reads the sanity check's first line itself (job_pipeline.py's parse_check_answer, mirrored
// client-side): the job only carries a character count, not the text, until the exchange is
// fetched (D-105's trace is a count-and-status feed, not a text one).
function parseCheckAnswer(text: string): { looksLikePosting: boolean; reason: string } {
  const match = /LOOKS_LIKE_A_JOB_POSTING:\s*(yes|no)\b/i.exec(text)
  const looksLikePosting = match !== null && match[1].toLowerCase() === 'yes'
  const rest = match ? text.slice(match.index + match[0].length) : text
  const reason = rest
    .split('\n')
    .map((line) => line.trim())
    .find((line) => line.length > 0)
  return { looksLikePosting, reason: reason ?? '' }
}

// The Listing's Generate (LLM) flow (D-121, job-llm-steps.md): pick a source, review the
// code-extracted text (a sanity check runs alongside, informing but never blocking), then
// generate. Follows ReviseOverlay's layout - the current document on one side, this flow's own
// steps on the other - but is a one-shot wizard, not a repeatable chat.
export function GenerateListingOverlay({
  applicationId,
  currentListing,
  open,
  onOpenChange,
  onChanged,
}: {
  applicationId: number
  currentListing: JobApplicationFile | null
  open: boolean
  onOpenChange: (open: boolean) => void
  onChanged: () => void
}) {
  const [stage, setStage] = useState<Stage>('source')
  const [method, setMethod] = useState<Method>('paste')
  const [pasteValue, setPasteValue] = useState('')
  const [urlValue, setUrlValue] = useState('')
  const [extraction, setExtraction] = useState<ListingExtraction | null>(null)
  const [reviewText, setReviewText] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [checkJobId, setCheckJobId] = useState<number | null>(null)
  const [checkAnswer, setCheckAnswer] = useState<{ looksLikePosting: boolean; reason: string } | null>(
    null,
  )
  const [generateJobId, setGenerateJobId] = useState<number | null>(null)
  const [currentText, setCurrentText] = useState<string | null>(null)
  const fileInput = useRef<HTMLInputElement>(null)

  const { jobs } = useClaudeJobs()
  const checkJob = jobs.find((job) => job.id === checkJobId) ?? null
  const generateJob = jobs.find((job) => job.id === generateJobId) ?? null

  // Reset to a clean wizard each time the overlay opens, so a cancelled attempt never leaks
  // into the next one.
  useEffect(() => {
    if (!open) return
    setStage('source')
    setMethod('paste')
    setPasteValue('')
    setUrlValue('')
    setExtraction(null)
    setReviewText('')
    setBusy(false)
    setError(null)
    setCheckJobId(null)
    setCheckAnswer(null)
    setGenerateJobId(null)
  }, [open])

  // The current listing's text, for the left pane - only when it is something previewable as
  // text (a generated .md listing; an uploaded PDF/DOCX isn't rendered inline here).
  useEffect(() => {
    if (!open || !currentListing) {
      setCurrentText(null)
      return
    }
    let cancelled = false
    fetchJobFilePreview(applicationId, currentListing.id)
      .then((preview) => {
        if (cancelled) return
        setCurrentText(preview.kind === 'markdown' || preview.kind === 'text' ? preview.text : null)
      })
      .catch(() => {
        if (!cancelled) setCurrentText(null)
      })
    return () => {
      cancelled = true
    }
  }, [open, applicationId, currentListing])

  // Once the check job finishes, read its answer back and parse it (it carries no text of its
  // own until then).
  useEffect(() => {
    if (!checkJob || checkJob.status !== 'done') return
    let cancelled = false
    fetchPromptExchange(checkJob.id, 0)
      .then((exchange) => {
        if (!cancelled && exchange.result_text) setCheckAnswer(parseCheckAnswer(exchange.result_text))
      })
      .catch(() => undefined)
    return () => {
      cancelled = true
    }
  }, [checkJob])

  useEffect(() => {
    if (generateJob?.status === 'done') onChanged()
    // onChanged is stable in practice; generateJob.status is the real trigger.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [generateJob?.status])

  function startReview(result: ListingExtraction) {
    setExtraction(result)
    if (result.status !== 'ok') {
      setError(result.message ?? 'That did not produce any readable text.')
      return
    }
    setError(null)
    setReviewText(result.text)
    setStage('review')
    checkListingText(applicationId, result.text)
      .then((job) => setCheckJobId(job.id))
      .catch(() => undefined) // the sanity check is informational only; a failure to queue it is not fatal
  }

  async function runExtraction(run: () => Promise<ListingExtraction>) {
    setBusy(true)
    setError(null)
    try {
      startReview(await run())
    } catch (failure) {
      setError(failure instanceof ApiError ? failure.message : 'That could not be read.')
    } finally {
      setBusy(false)
    }
  }

  async function chooseFile(chosen: FileList | null) {
    const file = chosen?.[0]
    if (!file) return
    await runExtraction(() => extractListingFromUpload(applicationId, file))
    if (fileInput.current) fileInput.current.value = ''
  }

  async function generate() {
    if (!extraction || !reviewText.trim()) return
    setBusy(true)
    setError(null)
    try {
      const job = await generateListing(applicationId, extraction.method, reviewText)
      setGenerateJobId(job.id)
      setStage('running')
    } catch (failure) {
      setError(failure instanceof ApiError ? failure.message : 'The generate step could not start.')
    } finally {
      setBusy(false)
    }
  }

  const hasData = currentListing !== null

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="flex h-[85vh] w-full max-w-6xl flex-col gap-3 sm:max-w-6xl">
        <DialogHeader>
          <DialogTitle>{hasData ? 'Revise (LLM): Listing' : 'Generate (LLM): Listing'}</DialogTitle>
        </DialogHeader>
        <div className="grid min-h-0 flex-1 grid-cols-1 gap-4 lg:grid-cols-2">
          <div className="min-h-0 overflow-y-auto rounded border border-border p-3">
            {currentText ? (
              <MarkdownDocument text={currentText} />
            ) : (
              <p className="text-sm text-muted-foreground">
                {hasData ? 'This listing is not previewable as text here.' : 'No listing file yet.'}
              </p>
            )}
          </div>
          <div className="flex min-h-0 flex-col gap-3 overflow-y-auto">
            {stage === 'source' && (
              <div className="flex flex-col gap-3">
                <div className="flex gap-2">
                  {(['paste', 'url', 'upload'] as const).map((candidate) => (
                    <Button
                      key={candidate}
                      type="button"
                      size="sm"
                      variant={method === candidate ? 'default' : 'outline'}
                      onClick={() => {
                        setMethod(candidate)
                        setError(null)
                      }}
                    >
                      {candidate === 'paste' ? 'Paste text' : candidate === 'url' ? 'URL' : 'Upload a file'}
                    </Button>
                  ))}
                </div>
                {method === 'paste' && (
                  <div className="flex flex-col gap-2">
                    <Textarea
                      rows={10}
                      placeholder="Paste the job listing text here..."
                      value={pasteValue}
                      onChange={(event) => setPasteValue(event.target.value)}
                    />
                    <Button
                      disabled={busy || !pasteValue.trim()}
                      onClick={() => void runExtraction(() => extractListingFromPaste(applicationId, pasteValue))}
                      className="self-start"
                    >
                      {busy ? 'Reading...' : 'Use this text'}
                    </Button>
                  </div>
                )}
                {method === 'url' && (
                  <div className="flex flex-col gap-2">
                    <Input
                      type="url"
                      placeholder="https://..."
                      value={urlValue}
                      onChange={(event) => setUrlValue(event.target.value)}
                    />
                    <Button
                      disabled={busy || !urlValue.trim()}
                      onClick={() => void runExtraction(() => extractListingFromUrl(applicationId, urlValue))}
                      className="self-start"
                    >
                      {busy ? 'Fetching...' : 'Fetch'}
                    </Button>
                  </div>
                )}
                {method === 'upload' && (
                  <div className="flex flex-col gap-2">
                    <input
                      ref={fileInput}
                      type="file"
                      accept=".pdf,.docx,.txt,.md,.html,.htm"
                      className="sr-only"
                      aria-label="Choose a listing file"
                      onChange={(event) => void chooseFile(event.target.files)}
                    />
                    <Button
                      disabled={busy}
                      onClick={() => fileInput.current?.click()}
                      className="self-start"
                    >
                      {busy ? 'Reading...' : 'Choose a file'}
                    </Button>
                  </div>
                )}
                {error && (
                  <div className="flex flex-col gap-1">
                    <p role="alert" className="text-sm text-destructive">
                      {error}
                    </p>
                    {method !== 'paste' && (
                      <Button
                        variant="outline"
                        size="sm"
                        className="self-start"
                        onClick={() => {
                          setMethod('paste')
                          setError(null)
                        }}
                      >
                        Try pasting the text instead
                      </Button>
                    )}
                  </div>
                )}
              </div>
            )}

            {stage === 'review' && (
              <div className="flex min-h-0 flex-1 flex-col gap-2">
                <p className="text-xs text-muted-foreground">
                  Review the extracted text below - edit anything that looks wrong before
                  generating.
                </p>
                <Textarea
                  rows={14}
                  className="flex-1"
                  value={reviewText}
                  onChange={(event) => setReviewText(event.target.value)}
                />
                {!checkAnswer && checkJobId !== null && (
                  <p className="text-xs text-muted-foreground">Checking this looks like a job posting...</p>
                )}
                {checkAnswer && !checkAnswer.looksLikePosting && (
                  <p role="alert" className="text-xs text-amber-600 dark:text-amber-400">
                    This might not be a job posting{checkAnswer.reason ? `: ${checkAnswer.reason}` : '.'} You
                    can still continue, or go back and try a different source.
                  </p>
                )}
                {error && (
                  <p role="alert" className="text-xs text-destructive">
                    {error}
                  </p>
                )}
                <div className="flex gap-2">
                  <Button variant="outline" size="sm" onClick={() => setStage('source')}>
                    Back
                  </Button>
                  <Button disabled={busy || !reviewText.trim()} onClick={() => void generate()}>
                    {busy ? 'Starting...' : 'Generate'}
                  </Button>
                </div>
              </div>
            )}

            {stage === 'running' && (
              <div className="flex flex-col gap-3">
                <RunTrace job={generateJob} />
                {generateJob?.status === 'done' && (
                  <Button variant="outline" size="sm" className="self-start" onClick={() => setStage('source')}>
                    Generate another version
                  </Button>
                )}
              </div>
            )}
          </div>
        </div>
        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)}>
            Close
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
