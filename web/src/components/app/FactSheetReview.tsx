import { useEffect, useState } from 'react'

import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { ApiError, fetchFactSheet, updateFact } from '@/lib/api'
import type { Fact, FactChange, FactSheet, FactStatus } from '@/lib/types'

type LoadState =
  | { kind: 'loading' }
  | { kind: 'error'; message: string }
  | { kind: 'ready'; sheet: FactSheet }

const TONE: Record<FactStatus, string> = {
  unverified: 'border-muted-foreground/40 text-muted-foreground',
  verified: 'border-[#005333] bg-[#00210f] text-[#84e7b0]',
  rejected: 'border-[#93000a] bg-[#2a0a0a] text-[#ffb4ab]',
}

// Shows the Fact Sheet for review. Only verified facts are used by later documents (D-09).
export function FactSheetReview() {
  const [state, setState] = useState<LoadState>({ kind: 'loading' })

  function load() {
    fetchFactSheet()
      .then((sheet) => setState({ kind: 'ready', sheet }))
      .catch((error: unknown) => {
        const message = error instanceof ApiError ? error.message : 'Could not load the Fact Sheet.'
        setState({ kind: 'error', message })
      })
  }

  useEffect(() => {
    load()
  }, [])

  return (
    <section aria-labelledby="fact-sheet-heading" className="flex flex-col gap-3 rounded border border-border bg-card p-4">
      <div className="flex items-baseline justify-between gap-4">
        <div>
          <h2 id="fact-sheet-heading" className="text-sm font-semibold">
            Fact Sheet
          </h2>
          <p className="text-xs text-muted-foreground">
            Check each fact against your CV. Only verified facts are used in documents.
          </p>
        </div>
        {state.kind === 'ready' && state.sheet.facts.length > 0 && (
          <span className="font-mono text-xs text-muted-foreground">
            {state.sheet.facts.filter((fact) => fact.status === 'verified').length} of{' '}
            {state.sheet.facts.length} verified
            {state.sheet.version !== null && ` · version ${state.sheet.version}`}
          </span>
        )}
      </div>

      {state.kind === 'loading' && <p className="text-sm text-muted-foreground">Loading the Fact Sheet...</p>}

      {state.kind === 'error' && (
        <p role="alert" className="text-sm text-destructive">
          {state.message}
        </p>
      )}

      {state.kind === 'ready' && state.sheet.facts.length === 0 && (
        <p className="text-sm text-muted-foreground">
          No Fact Sheet yet. It is made by the profile analysis, once the uploads are in.
        </p>
      )}

      {state.kind === 'ready' &&
        state.sheet.facts.map((fact) => (
          <FactRow key={fact.id} fact={fact} onSaved={load} />
        ))}

      {state.kind === 'ready' && state.sheet.conflicts.length > 0 && (
        <div className="flex flex-col gap-2 rounded border border-[#5c4300] bg-[#2a1800]/40 p-3">
          <h3 className="text-xs font-semibold uppercase tracking-wider text-[#ffca85]">
            Conflicts between sources
          </h3>
          <ul className="flex flex-col gap-1 text-sm">
            {state.sheet.conflicts.map((conflict) => (
              <li key={conflict.id}>
                <span className="font-mono text-xs text-muted-foreground">
                  {conflict.fact_ids.join(' and ')}:
                </span>{' '}
                {conflict.note}
              </li>
            ))}
          </ul>
        </div>
      )}
    </section>
  )
}

type RowProps = { fact: Fact; onSaved: () => void }

function FactRow({ fact, onSaved }: RowProps) {
  const [editing, setEditing] = useState(false)
  const [text, setText] = useState(fact.text)
  const [date, setDate] = useState(fact.date)
  const [location, setLocation] = useState(fact.source_location)
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  async function save(change: FactChange) {
    setBusy(true)
    setError(null)
    try {
      await updateFact(fact.id, change)
      setEditing(false)
      onSaved()
    } catch (saveError) {
      setError(saveError instanceof ApiError ? saveError.message : 'The change was not saved.')
    } finally {
      setBusy(false)
    }
  }

  if (editing) {
    return (
      <div className="flex flex-col gap-2 rounded border border-border bg-background p-3">
        <label className="flex flex-col gap-1 text-xs text-muted-foreground">
          Fact
          <textarea
            className="rounded border border-border bg-card p-2 text-sm text-foreground"
            rows={2}
            value={text}
            onChange={(event) => setText(event.target.value)}
          />
        </label>
        <div className="flex gap-3">
          <label className="flex flex-col gap-1 text-xs text-muted-foreground">
            Date
            <input
              className="rounded border border-border bg-card p-1 font-mono text-sm text-foreground"
              value={date}
              onChange={(event) => setDate(event.target.value)}
            />
          </label>
          <label className="flex flex-1 flex-col gap-1 text-xs text-muted-foreground">
            Location in the source
            <input
              className="rounded border border-border bg-card p-1 text-sm text-foreground"
              value={location}
              onChange={(event) => setLocation(event.target.value)}
            />
          </label>
        </div>
        {error && (
          <p role="alert" className="text-sm text-destructive">
            {error}
          </p>
        )}
        <div className="flex gap-2">
          <Button
            disabled={busy}
            onClick={() => void save({ text, date, source_location: location })}
          >
            Save
          </Button>
          <Button variant="ghost" disabled={busy} onClick={() => setEditing(false)}>
            Cancel
          </Button>
        </div>
      </div>
    )
  }

  return (
    <div className="flex flex-col gap-2 rounded border border-border bg-background p-3">
      <div className="flex items-start justify-between gap-4">
        <div className="flex flex-col gap-1">
          <p className="text-sm">
            <span className="mr-2 font-mono text-xs text-muted-foreground">{fact.fact_key}</span>
            {fact.text}
          </p>
          <p className="font-mono text-xs text-muted-foreground">
            {fact.date} · {fact.source_name} · {fact.source_location}
          </p>
        </div>
        <Badge variant="outline" className={`shrink-0 rounded-sm font-mono text-[11px] font-normal ${TONE[fact.status]}`}>
          {fact.status}
        </Badge>
      </div>
      {error && (
        <p role="alert" className="text-sm text-destructive">
          {error}
        </p>
      )}
      <div className="flex gap-2">
        {fact.status !== 'verified' && (
          <Button size="sm" disabled={busy} onClick={() => void save({ status: 'verified' })}>
            Verify
          </Button>
        )}
        {fact.status !== 'rejected' && (
          <Button size="sm" variant="outline" disabled={busy} onClick={() => void save({ status: 'rejected' })}>
            Reject
          </Button>
        )}
        <Button size="sm" variant="ghost" disabled={busy} onClick={() => setEditing(true)}>
          Edit
        </Button>
      </div>
    </div>
  )
}
