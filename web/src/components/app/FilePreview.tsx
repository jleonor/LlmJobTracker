import { useEffect, useState } from 'react'

import { MarkdownDocument } from '@/components/app/MarkdownDocument'
import { Dialog, DialogContent, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { ApiError, fetchProfileFilePreview } from '@/lib/api'
import type { FilePreviewData } from '@/lib/types'
import { cn } from '@/lib/utils'

// Where a previewed file's bytes come from. Profile files are the only real source today
// (D-109); a job application's own files get a second case once that table exists
// (planning/files.md), reusing this same overlay rather than a new one.
export type PreviewSource = { table: 'profile_file'; id: number }

async function load(source: PreviewSource): Promise<FilePreviewData> {
  if (source.table === 'profile_file') return fetchProfileFilePreview(source.id)
  throw new Error(`Unknown preview source: ${JSON.stringify(source)}`)
}

type State =
  | { stage: 'loading' }
  | { stage: 'error'; message: string }
  // pdfUrl is the one object URL created for this load, built once here rather than in render,
  // so it is revoked exactly once too (see the effect's cleanup).
  | { stage: 'ready'; data: FilePreviewData; pdfUrl: string | null }

// The reusable file preview overlay (brainstorm #3): a "Preview" button anywhere a file is
// listed opens this, instead of each caller building its own viewer. Rendering strategy is
// picked from the API response's own content type (file_preview.py, D-107), not the file name:
// PDF and converted-docx both arrive as "pdf" and render in an <iframe>; the three generated
// documents arrive as "markdown"; untrusted email content (D-26, D-38) arrives as "html" and
// renders in a fully sandboxed iframe (`sandbox=""`: no scripts, no forms, no same-origin).
export function FilePreview({
  source,
  name,
  open,
  onOpenChange,
}: {
  source: PreviewSource
  name: string
  open: boolean
  onOpenChange: (open: boolean) => void
}) {
  const [state, setState] = useState<State>({ stage: 'loading' })

  useEffect(() => {
    if (!open) return
    setState({ stage: 'loading' })
    let cancelled = false
    let objectUrl: string | null = null
    load(source)
      .then((data) => {
        if (cancelled) return
        if (data.kind === 'pdf') objectUrl = URL.createObjectURL(data.blob)
        setState({ stage: 'ready', data, pdfUrl: objectUrl })
      })
      .catch((error: unknown) => {
        if (cancelled) return
        const message = error instanceof ApiError ? error.message : 'The file could not be previewed.'
        setState({ stage: 'error', message })
      })
    return () => {
      cancelled = true
      if (objectUrl) URL.revokeObjectURL(objectUrl)
    }
    // `source` is a plain object literal from the caller; comparing its fields, not identity,
    // avoids re-fetching on every render while still refetching when the target file changes.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, source.table, source.table === 'profile_file' ? source.id : null])

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="flex h-[85vh] w-full max-w-4xl flex-col gap-3 sm:max-w-4xl">
        <DialogHeader>
          <DialogTitle className="truncate pr-8">{name}</DialogTitle>
        </DialogHeader>
        <div className="flex-1 overflow-hidden rounded border border-border bg-background">
          {state.stage === 'loading' && <Centered>Loading preview...</Centered>}
          {state.stage === 'error' && (
            <Centered className="text-destructive">{state.message}</Centered>
          )}
          {state.stage === 'ready' && (
            <Rendered name={name} data={state.data} pdfUrl={state.pdfUrl} />
          )}
        </div>
      </DialogContent>
    </Dialog>
  )
}

function Centered({ children, className }: { children: React.ReactNode; className?: string }) {
  return (
    <div className={cn('flex h-full items-center justify-center text-sm', className)}>
      {children}
    </div>
  )
}

function Rendered({
  name,
  data,
  pdfUrl,
}: {
  name: string
  data: FilePreviewData
  pdfUrl: string | null
}) {
  if (data.kind === 'pdf') {
    return pdfUrl ? <iframe title={name} src={pdfUrl} className="h-full w-full" /> : null
  }
  if (data.kind === 'html') {
    // Untrusted content (D-26, D-38): every sandbox restriction stays on. No allow-scripts,
    // no allow-same-origin, no allow-forms, no allow-popups.
    return <iframe title={name} srcDoc={data.text} sandbox="" className="h-full w-full bg-white" />
  }
  if (data.kind === 'markdown') {
    return (
      <div className="h-full overflow-auto p-4">
        <MarkdownDocument text={data.text} />
      </div>
    )
  }
  return (
    <pre className="h-full overflow-auto whitespace-pre-wrap p-4 font-mono text-sm">{data.text}</pre>
  )
}
