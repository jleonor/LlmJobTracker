import { useEffect, useState } from 'react'

import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { LlmCheck } from '@/components/app/LlmCheck'
import { RunTrace } from '@/components/app/RunTrace'
import {
  ApiError,
  deleteModelPrice,
  exportData,
  fetchAuthStatus,
  fetchJobApplications,
  fetchLlmAppStatus,
  fetchModelPrices,
  fetchPricesFromProvider,
  fetchPricesResult,
  fetchPricingUrls,
  loginBackend,
  logoutBackend,
  openLlmApp,
  renameModelPrice,
  saveBackendSettings,
  saveLlmExportPath,
  saveModelPrice,
  saveModelPrices,
  savePricingUrl,
} from '@/lib/api'
import { BACKEND_LABELS, BACKENDS, MODEL_FIELD } from '@/lib/backends'
import type { QueueState } from '@/lib/useClaudeJobs'
import type {
  AuthStatus,
  Backend,
  LlmAppStatus,
  ModelPrice,
  ParsedModelPrice,
  RetryPolicy,
  Settings,
} from '@/lib/types'

// "Open LLM app" (D-202, D-210) launches the desktop *app*, not the reasoning-task CLI the
// same setting otherwise names - "Claude Code" there would wrongly suggest the CLI.
const LLM_APP_LABELS: Record<Backend, string> = {
  claude_code: 'Claude Desktop',
  codex: 'the ChatGPT desktop app',
}
const RETRY_POLICY_LABELS: Record<RetryPolicy, string> = {
  reset_time: 'Auto-resume at the reported reset time',
  fixed_interval: 'Retry on a fixed interval',
  manual_only: 'Always pause for manual Resume',
}
const RETRY_POLICIES: RetryPolicy[] = ['reset_time', 'fixed_interval', 'manual_only']

type Props = {
  settings: Settings
  onSettingsChanged: () => void
  queue: QueueState
}

export function SettingsPage({ settings, onSettingsChanged, queue }: Props) {
  return (
    <div className="flex max-w-3xl flex-col gap-6">
      <h1 className="text-xl font-semibold">Settings</h1>
      <BackendSection settings={settings} onSaved={onSettingsChanged} />
      <OpenLlmAppSection settings={settings} onSaved={onSettingsChanged} />
      <LlmCheck />
      <AuthSection />
      {BACKENDS.map((backend) => (
        <PriceSection key={backend} backend={backend} queue={queue} settings={settings} onSaved={onSettingsChanged} />
      ))}
    </div>
  )
}

// --- Backend and retry policy (D-195, D-201) ---------------------------------------------------

function BackendSection({ settings, onSaved }: { settings: Settings; onSaved: () => void }) {
  const [backend, setBackend] = useState<Backend>(settings.backend)
  const [retryPolicy, setRetryPolicy] = useState<RetryPolicy>(settings.retry_policy)
  const [retryIntervalMinutes, setRetryIntervalMinutes] = useState(
    String(settings.retry_interval_minutes),
  )
  const [retryMaxAttempts, setRetryMaxAttempts] = useState(String(settings.retry_max_attempts))
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const dirty =
    backend !== settings.backend ||
    retryPolicy !== settings.retry_policy ||
    retryIntervalMinutes !== String(settings.retry_interval_minutes) ||
    retryMaxAttempts !== String(settings.retry_max_attempts)

  async function save() {
    setBusy(true)
    setError(null)
    try {
      await saveBackendSettings(settings.user_name, {
        backend,
        retry_policy: retryPolicy,
        retry_interval_minutes: Number(retryIntervalMinutes) || 1,
        retry_max_attempts: Number(retryMaxAttempts) || 1,
        claude_code_model: settings.claude_code_model,
        codex_model: settings.codex_model,
      })
      onSaved()
    } catch (failure) {
      setError(failure instanceof ApiError ? failure.message : 'The settings were not saved.')
    } finally {
      setBusy(false)
    }
  }

  return (
    <section
      aria-labelledby="backend-heading"
      className="flex flex-col gap-4 rounded border border-border bg-card p-4"
    >
      <h2 id="backend-heading" className="text-sm font-semibold">
        Backend
      </h2>
      <div className="flex flex-col gap-2">
        <Label>Reasoning backend</Label>
        <Select
          items={BACKEND_LABELS}
          value={backend}
          onValueChange={(next) => setBackend(next as Backend)}
        >
          <SelectTrigger className="w-64">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            {BACKENDS.map((option) => (
              <SelectItem key={option} value={option}>
                {BACKEND_LABELS[option]}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
        <p className="text-xs text-muted-foreground">
          Used for every reasoning task across the app. A job already running finishes on the
          backend it started with.
        </p>
      </div>
      <div className="flex flex-col gap-2">
        <Label>When a rate limit is hit</Label>
        <Select
          items={RETRY_POLICY_LABELS}
          value={retryPolicy}
          onValueChange={(next) => setRetryPolicy(next as RetryPolicy)}
        >
          <SelectTrigger className="w-80">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            {RETRY_POLICIES.map((option) => (
              <SelectItem key={option} value={option}>
                {RETRY_POLICY_LABELS[option]}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </div>
      {retryPolicy === 'fixed_interval' && (
        <div className="flex items-end gap-4">
          <div className="flex flex-col gap-1">
            <Label htmlFor="retry-interval">Retry interval (minutes)</Label>
            <Input
              id="retry-interval"
              type="number"
              min={1}
              className="w-32"
              value={retryIntervalMinutes}
              onChange={(event) => setRetryIntervalMinutes(event.target.value)}
            />
          </div>
          <div className="flex flex-col gap-1">
            <Label htmlFor="retry-max-attempts">Max consecutive attempts</Label>
            <Input
              id="retry-max-attempts"
              type="number"
              min={1}
              className="w-32"
              value={retryMaxAttempts}
              onChange={(event) => setRetryMaxAttempts(event.target.value)}
            />
          </div>
        </div>
      )}
      {error && <p className="text-sm text-destructive">{error}</p>}
      <div>
        <Button disabled={busy || !dirty} onClick={() => void save()}>
          Save
        </Button>
      </div>
    </section>
  )
}

// --- Open LLM app (D-202, D-210) ----------------------------------------------------------------

function OpenLlmAppSection({
  settings,
  onSaved,
}: {
  settings: Settings
  onSaved: () => void
}) {
  const [installStatus, setInstallStatus] = useState<Record<Backend, LlmAppStatus> | null>(null)
  const [statusError, setStatusError] = useState<string | null>(null)
  const [exportPath, setExportPath] = useState(settings.llm_export_path ?? '')
  const [pathBusy, setPathBusy] = useState(false)
  const [pathError, setPathError] = useState<string | null>(null)
  const [confirmOpen, setConfirmOpen] = useState(false)
  const [appCount, setAppCount] = useState<number | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [opened, setOpened] = useState<string | null>(null)
  const [exportBusy, setExportBusy] = useState(false)
  const [exportError, setExportError] = useState<string | null>(null)
  const [exportedPath, setExportedPath] = useState<string | null>(null)

  useEffect(() => {
    setExportPath(settings.llm_export_path ?? '')
  }, [settings.llm_export_path])

  async function saveExportPath() {
    setPathBusy(true)
    setPathError(null)
    try {
      await saveLlmExportPath(settings.user_name, exportPath.trim())
      onSaved()
    } catch (failure) {
      setPathError(failure instanceof ApiError ? failure.message : 'The path was not saved.')
    } finally {
      setPathBusy(false)
    }
  }

  function reloadInstallStatus() {
    fetchLlmAppStatus()
      .then((result) => {
        setInstallStatus(result)
        setStatusError(null)
      })
      .catch((failure: unknown) => {
        setStatusError(
          failure instanceof ApiError ? failure.message : 'Could not check installed apps.',
        )
      })
  }

  useEffect(reloadInstallStatus, [])

  // Optimistic until the check actually says otherwise - matches the backend's own "can't
  // check, so assume available" default rather than disabling the button on a slow load.
  const installed = installStatus ? installStatus[settings.backend].installed : true

  function openConfirm() {
    setError(null)
    setOpened(null)
    setConfirmOpen(true)
    fetchJobApplications()
      .then((apps) => setAppCount(apps.length))
      .catch(() => setAppCount(null))
  }

  async function confirmAndOpen() {
    setBusy(true)
    setError(null)
    try {
      const result = await openLlmApp()
      setOpened(result.bundle_path)
      setConfirmOpen(false)
    } catch (failure) {
      setError(failure instanceof ApiError ? failure.message : 'Could not open the LLM app.')
    } finally {
      setBusy(false)
    }
  }

  // Export Data (D-265, Phase 13): a manual backup, reusing the same export with no deep link.
  async function runExportData() {
    setExportBusy(true)
    setExportError(null)
    try {
      const result = await exportData()
      setExportedPath(result.bundle_path)
    } catch (failure) {
      setExportError(failure instanceof ApiError ? failure.message : 'Could not export the data.')
    } finally {
      setExportBusy(false)
    }
  }

  return (
    <section
      aria-labelledby="open-llm-app-heading"
      className="flex flex-col gap-3 rounded border border-border bg-card p-4"
    >
      <div className="flex items-center justify-between">
        <h2 id="open-llm-app-heading" className="text-sm font-semibold">
          Open LLM app
        </h2>
        <Button variant="ghost" size="sm" onClick={reloadInstallStatus}>
          Refresh
        </Button>
      </div>

      <div className="flex flex-col gap-1">
        <Label htmlFor="llm-export-path">Export location</Label>
        <div className="flex items-end gap-2">
          <Input
            id="llm-export-path"
            className="flex-1"
            placeholder="Downloads\LlmJobTrackerExport (default)"
            value={exportPath}
            onChange={(event) => setExportPath(event.target.value)}
          />
          <Button
            variant="outline"
            disabled={pathBusy || exportPath.trim() === (settings.llm_export_path ?? '')}
            onClick={() => void saveExportPath()}
          >
            Save path
          </Button>
        </div>
        {pathError && <p className="text-xs text-destructive">{pathError}</p>}
        <p className="text-xs text-muted-foreground">
          Leave blank to use the default (your Downloads folder). Rebuilt fresh at this exact
          path every time, so the external app only needs to be trusted here once.
        </p>
      </div>

      {statusError && <p className="text-sm text-destructive">{statusError}</p>}
      <div className="flex flex-col gap-2">
        {BACKENDS.map((backend) => (
          <div key={backend} className="flex items-center gap-2">
            <span className="text-sm font-medium">{LLM_APP_LABELS[backend]}</span>
            {installStatus ? (
              <>
                <Badge variant={installStatus[backend].installed ? 'secondary' : 'destructive'}>
                  {installStatus[backend].installed ? 'Installed' : 'Not installed'}
                </Badge>
                <span className="text-xs text-muted-foreground">
                  {installStatus[backend].detail}
                </span>
              </>
            ) : (
              <span className="text-xs text-muted-foreground">Checking...</span>
            )}
          </div>
        ))}
      </div>

      <div className="flex items-center justify-between gap-4 border-t border-border pt-3">
        <p className="text-xs text-muted-foreground">
          A manual backup: the same export below, without opening anything.
        </p>
        <Button variant="outline" disabled={exportBusy} onClick={() => void runExportData()}>
          {exportBusy ? 'Exporting...' : 'Export Data'}
        </Button>
      </div>
      {exportedPath && (
        <p className="text-xs text-muted-foreground">
          Exported to <span className="font-mono">{exportedPath}</span>.
        </p>
      )}
      {exportError && <p className="text-sm text-destructive">{exportError}</p>}

      <div className="flex items-center justify-between gap-4 border-t border-border pt-3">
        <p className="text-xs text-muted-foreground">
          Exports a read-only copy of every job application, your profile documents, and a
          database snapshot, then opens it in {LLM_APP_LABELS[settings.backend]}.
        </p>
        <Button
          disabled={!installed}
          title={installed ? undefined : `${LLM_APP_LABELS[settings.backend]} is not installed.`}
          onClick={openConfirm}
        >
          Open LLM app
        </Button>
      </div>
      {opened && (
        <p className="text-xs text-muted-foreground">
          Exported to <span className="font-mono">{opened}</span> and opened in{' '}
          {LLM_APP_LABELS[settings.backend]}.
        </p>
      )}
      {error && <p className="text-sm text-destructive">{error}</p>}

      <Dialog open={confirmOpen} onOpenChange={setConfirmOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Open LLM app?</DialogTitle>
          </DialogHeader>
          <p className="text-sm text-muted-foreground">
            {appCount === null ? 'Every' : appCount} job application
            {appCount === 1 ? '' : 's'} and their files, your profile documents, and a database
            snapshot will be exported and opened in {LLM_APP_LABELS[settings.backend]}. Nothing
            you do there changes the live tracker.
          </p>
          <DialogFooter>
            <Button variant="outline" onClick={() => setConfirmOpen(false)}>
              Cancel
            </Button>
            <Button disabled={busy || !installed} onClick={() => void confirmAndOpen()}>
              {busy ? 'Opening...' : 'Open'}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </section>
  )
}

// --- Auth status / logout (D-203) ---------------------------------------------------------------

function AuthSection() {
  const [status, setStatus] = useState<Record<Backend, AuthStatus> | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState<Backend | null>(null)
  const [loginStarted, setLoginStarted] = useState<Backend | null>(null)

  function reload() {
    fetchAuthStatus()
      .then((result) => {
        setStatus(result)
        setError(null)
      })
      .catch((failure: unknown) => {
        setError(failure instanceof ApiError ? failure.message : 'Could not check the login status.')
      })
  }

  useEffect(reload, [])

  async function logout(backend: Backend) {
    setBusy(backend)
    setLoginStarted(null)
    try {
      const fresh = await logoutBackend(backend)
      setStatus((current) => (current ? { ...current, [backend]: fresh } : current))
    } catch (failure) {
      setError(failure instanceof ApiError ? failure.message : 'Could not log out.')
    } finally {
      setBusy(null)
    }
  }

  async function login(backend: Backend) {
    setBusy(backend)
    setError(null)
    try {
      await loginBackend(backend)
      setLoginStarted(backend)
    } catch (failure) {
      setError(failure instanceof ApiError ? failure.message : 'Could not start login.')
    } finally {
      setBusy(null)
    }
  }

  return (
    <section
      aria-labelledby="auth-heading"
      className="flex flex-col gap-3 rounded border border-border bg-card p-4"
    >
      <div className="flex items-center justify-between">
        <h2 id="auth-heading" className="text-sm font-semibold">
          Login status
        </h2>
        <Button variant="ghost" size="sm" onClick={reload}>
          Refresh
        </Button>
      </div>
      {error && <p className="text-sm text-destructive">{error}</p>}
      {!status && !error && <p className="text-sm text-muted-foreground">Checking...</p>}
      {status && (
        <div className="flex flex-col gap-2">
          {BACKENDS.map((backend) => (
            <div key={backend} className="flex flex-col gap-1">
              <div className="flex items-center justify-between gap-4">
                <div className="flex items-center gap-2">
                  <span className="text-sm font-medium">{BACKEND_LABELS[backend]}</span>
                  <Badge variant={status[backend].logged_in ? 'secondary' : 'destructive'}>
                    {status[backend].logged_in ? 'Logged in' : 'Not logged in'}
                  </Badge>
                  <span className="text-xs text-muted-foreground">{status[backend].detail}</span>
                </div>
                {status[backend].logged_in ? (
                  <Button
                    variant="outline"
                    size="sm"
                    disabled={busy === backend}
                    onClick={() => void logout(backend)}
                  >
                    Log out
                  </Button>
                ) : (
                  <Button
                    variant="outline"
                    size="sm"
                    disabled={busy === backend}
                    onClick={() => void login(backend)}
                  >
                    Log in
                  </Button>
                )}
              </div>
              {loginStarted === backend && !status[backend].logged_in && (
                <p className="text-xs text-muted-foreground">
                  Check your browser to finish signing in, then Refresh above.
                </p>
              )}
            </div>
          ))}
        </div>
      )}
      <p className="text-xs text-muted-foreground">
        Log in opens the CLI's own browser sign-in flow (<code>claude auth login</code> or{' '}
        <code>codex login</code>) - nothing you type here is involved.
      </p>
    </section>
  )
}

// --- Price table and the "fetch and update" scrape (D-198) --------------------------------------

function PriceSection({
  backend,
  queue,
  settings,
  onSaved,
}: {
  backend: Backend
  queue: QueueState
  settings: Settings
  onSaved: () => void
}) {
  const [prices, setPrices] = useState<ModelPrice[]>([]);
  const [pricingUrl, setPricingUrl] = useState('')
  const [savedUrl, setSavedUrl] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [fetchJobId, setFetchJobId] = useState<number | null>(null)
  const [proposed, setProposed] = useState<ParsedModelPrice[] | null>(null)
  const [busy, setBusy] = useState(false)

  const activeModel = settings[MODEL_FIELD[backend]]
  // The current model stays selectable even if it isn't (or isn't yet) one of the stored rows.
  const modelOptions = Array.from(new Set([activeModel, ...prices.map((row) => row.model)]))

  function reloadPrices() {
    fetchModelPrices()
      .then((all) => setPrices(all.filter((row) => row.provider === backend)))
      .catch((failure: unknown) => {
        setError(failure instanceof ApiError ? failure.message : 'Could not read the price table.')
      })
  }

  useEffect(() => {
    reloadPrices()
    fetchPricingUrls()
      .then((urls) => {
        setPricingUrl(urls[backend] ?? '')
        setSavedUrl(urls[backend] ?? '')
      })
      .catch(() => undefined)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [backend])

  const job = fetchJobId === null ? null : (queue.jobs.find((item) => item.id === fetchJobId) ?? null)

  useEffect(() => {
    if (!job || job.status !== 'done') return
    fetchPricesResult(backend, job.id)
      .then((rows) => setProposed(rows))
      .catch((failure: unknown) => {
        setError(failure instanceof ApiError ? failure.message : 'Could not read the proposed table.')
      })
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [job?.status])

  async function saveUrl() {
    setBusy(true)
    setError(null)
    try {
      await savePricingUrl(backend, pricingUrl.trim() || null)
      setSavedUrl(pricingUrl.trim())
    } catch (failure) {
      setError(failure instanceof ApiError ? failure.message : 'The pricing URL was not saved.')
    } finally {
      setBusy(false)
    }
  }

  async function startFetch() {
    setBusy(true)
    setError(null)
    setProposed(null)
    try {
      const job = await fetchPricesFromProvider(backend)
      setFetchJobId(job.id)
      queue.reload()
    } catch (failure) {
      setError(failure instanceof ApiError ? failure.message : 'Could not start the fetch.')
    } finally {
      setBusy(false)
    }
  }

  async function confirmProposed(rows: ParsedModelPrice[]) {
    setBusy(true)
    setError(null)
    try {
      await saveModelPrices(rows.map((row) => ({ provider: backend, updated_at: '', ...row })))
      setProposed(null)
      setFetchJobId(null)
      reloadPrices()
    } catch (failure) {
      setError(failure instanceof ApiError ? failure.message : 'Could not save the price table.')
    } finally {
      setBusy(false)
    }
  }

  async function saveRow(model: string, fields: { input_price_per_token: number; output_price_per_token: number }) {
    setBusy(true)
    setError(null)
    try {
      await saveModelPrice(backend, model, fields)
      reloadPrices()
    } catch (failure) {
      setError(failure instanceof ApiError ? failure.message : 'The price was not saved.')
    } finally {
      setBusy(false)
    }
  }

  async function renameRow(model: string, newModel: string) {
    setBusy(true)
    setError(null)
    try {
      await renameModelPrice(backend, model, newModel)
      reloadPrices()
      onSaved()
    } catch (failure) {
      setError(failure instanceof ApiError ? failure.message : 'The model name was not changed.')
      throw failure
    } finally {
      setBusy(false)
    }
  }

  async function removeRow(model: string) {
    setBusy(true)
    setError(null)
    try {
      await deleteModelPrice(backend, model)
      reloadPrices()
    } catch (failure) {
      setError(failure instanceof ApiError ? failure.message : 'The price was not removed.')
    } finally {
      setBusy(false)
    }
  }

  async function saveActiveModel(model: string) {
    setBusy(true)
    setError(null)
    try {
      await saveBackendSettings(settings.user_name, {
        backend: settings.backend,
        retry_policy: settings.retry_policy,
        retry_interval_minutes: settings.retry_interval_minutes,
        retry_max_attempts: settings.retry_max_attempts,
        claude_code_model: backend === 'claude_code' ? model : settings.claude_code_model,
        codex_model: backend === 'codex' ? model : settings.codex_model,
      })
      onSaved()
    } catch (failure) {
      setError(failure instanceof ApiError ? failure.message : 'The active model was not saved.')
    } finally {
      setBusy(false)
    }
  }

  return (
    <section
      aria-labelledby={`price-heading-${backend}`}
      className="flex flex-col gap-3 rounded border border-border bg-card p-4"
    >
      <h2 id={`price-heading-${backend}`} className="text-sm font-semibold">
        {BACKEND_LABELS[backend]} prices
      </h2>
      <div className="flex flex-col gap-2">
        <Label htmlFor={`active-model-${backend}`}>Active model</Label>
        <Select
          items={Object.fromEntries(modelOptions.map((model) => [model, model]))}
          value={activeModel}
          onValueChange={(next) => next && void saveActiveModel(next)}
        >
          <SelectTrigger id={`active-model-${backend}`} className="w-64" disabled={busy}>
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            {modelOptions.map((model) => (
              <SelectItem key={model} value={model}>
                {model}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
        <p className="text-xs text-muted-foreground">
          Used for every {BACKEND_LABELS[backend]} reasoning task. Add a model to the price table
          below to make it selectable here.
        </p>
      </div>
      <div className="flex items-end gap-2">
        <div className="flex flex-1 flex-col gap-1">
          <Label htmlFor={`pricing-url-${backend}`}>Pricing page URL</Label>
          <Input
            id={`pricing-url-${backend}`}
            placeholder="https://..."
            value={pricingUrl}
            onChange={(event) => setPricingUrl(event.target.value)}
          />
        </div>
        <Button variant="outline" disabled={busy || pricingUrl.trim() === savedUrl} onClick={() => void saveUrl()}>
          Save URL
        </Button>
        <Button disabled={busy || !savedUrl} onClick={() => void startFetch()}>
          Fetch and update
        </Button>
      </div>
      {error && <p className="text-sm text-destructive">{error}</p>}

      {job && job.status !== 'done' && <RunTrace job={job} />}

      {proposed && (
        <ProposedTable
          rows={proposed}
          busy={busy}
          onConfirm={(rows) => void confirmProposed(rows)}
          onDiscard={() => {
            setProposed(null)
            setFetchJobId(null)
          }}
        />
      )}

      <PriceTable rows={prices} busy={busy} onSave={saveRow} onRename={renameRow} onDelete={removeRow} />
    </section>
  )
}

function ProposedTable({
  rows,
  busy,
  onConfirm,
  onDiscard,
}: {
  rows: ParsedModelPrice[]
  busy: boolean
  onConfirm: (rows: ParsedModelPrice[]) => void
  onDiscard: () => void
}) {
  const [edited, setEdited] = useState(rows)

  return (
    <div className="flex flex-col gap-2 rounded border border-primary/40 bg-primary/5 p-3">
      <p className="text-xs font-medium text-muted-foreground">
        Proposed prices - review before saving. Nothing is written until you confirm.
      </p>
      <table className="w-full text-sm">
        <thead>
          <tr className="text-left text-xs text-muted-foreground">
            <th className="py-1">Model</th>
            <th className="py-1">Input $/token</th>
            <th className="py-1">Output $/token</th>
          </tr>
        </thead>
        <tbody>
          {edited.map((row, index) => (
            <tr key={row.model}>
              <td className="py-1 pr-2">{row.model}</td>
              <td className="py-1 pr-2">
                <Input
                  type="number"
                  value={row.input_price_per_token}
                  onChange={(event) => {
                    const value = Number(event.target.value)
                    setEdited((current) =>
                      current.map((item, i) => (i === index ? { ...item, input_price_per_token: value } : item)),
                    )
                  }}
                />
              </td>
              <td className="py-1">
                <Input
                  type="number"
                  value={row.output_price_per_token}
                  onChange={(event) => {
                    const value = Number(event.target.value)
                    setEdited((current) =>
                      current.map((item, i) => (i === index ? { ...item, output_price_per_token: value } : item)),
                    )
                  }}
                />
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      <div className="flex gap-2">
        <Button disabled={busy} onClick={() => onConfirm(edited)}>
          Confirm and save
        </Button>
        <Button variant="ghost" disabled={busy} onClick={onDiscard}>
          Discard
        </Button>
      </div>
    </div>
  )
}

function PriceTable({
  rows,
  busy,
  onSave,
  onRename,
  onDelete,
}: {
  rows: ModelPrice[]
  busy: boolean
  onSave: (model: string, fields: { input_price_per_token: number; output_price_per_token: number }) => void
  onRename: (model: string, newModel: string) => Promise<void>
  onDelete: (model: string) => void
}) {
  const [newModel, setNewModel] = useState('')
  const [newInput, setNewInput] = useState('0')
  const [newOutput, setNewOutput] = useState('0')

  return (
    <div className="flex flex-col gap-2">
      <table className="w-full text-sm">
        <thead>
          <tr className="text-left text-xs text-muted-foreground">
            <th className="py-1">Model</th>
            <th className="py-1">Input $/token</th>
            <th className="py-1">Output $/token</th>
            <th className="py-1" />
          </tr>
        </thead>
        <tbody>
          {rows.length === 0 && (
            <tr>
              <td colSpan={4} className="py-2 text-xs text-muted-foreground">
                No prices stored yet.
              </td>
            </tr>
          )}
          {rows.map((row) => (
            <PriceRow
              key={row.model}
              row={row}
              busy={busy}
              onSave={onSave}
              onRename={onRename}
              onDelete={onDelete}
            />
          ))}
        </tbody>
      </table>
      <div className="flex items-end gap-2 border-t border-border pt-2">
        <div className="flex flex-col gap-1">
          <Label htmlFor="new-model">Model</Label>
          <Input id="new-model" className="w-40" value={newModel} onChange={(event) => setNewModel(event.target.value)} />
        </div>
        <div className="flex flex-col gap-1">
          <Label htmlFor="new-input">Input $/token</Label>
          <Input
            id="new-input"
            type="number"
            className="w-28"
            value={newInput}
            onChange={(event) => setNewInput(event.target.value)}
          />
        </div>
        <div className="flex flex-col gap-1">
          <Label htmlFor="new-output">Output $/token</Label>
          <Input
            id="new-output"
            type="number"
            className="w-28"
            value={newOutput}
            onChange={(event) => setNewOutput(event.target.value)}
          />
        </div>
        <Button
          variant="outline"
          disabled={busy || !newModel.trim()}
          onClick={() => {
            onSave(newModel.trim(), {
              input_price_per_token: Number(newInput) || 0,
              output_price_per_token: Number(newOutput) || 0,
            })
            setNewModel('')
            setNewInput('0')
            setNewOutput('0')
          }}
        >
          Add model
        </Button>
      </div>
    </div>
  )
}

function PriceRow({
  row,
  busy,
  onSave,
  onRename,
  onDelete,
}: {
  row: ModelPrice
  busy: boolean
  onSave: (model: string, fields: { input_price_per_token: number; output_price_per_token: number }) => void
  onRename: (model: string, newModel: string) => Promise<void>
  onDelete: (model: string) => void
}) {
  const [modelName, setModelName] = useState(row.model)
  const [inputPrice, setInputPrice] = useState(String(row.input_price_per_token))
  const [outputPrice, setOutputPrice] = useState(String(row.output_price_per_token))
  const [renaming, setRenaming] = useState(false)
  const trimmedModel = modelName.trim()
  const dirty =
    (trimmedModel !== '' && trimmedModel !== row.model) ||
    inputPrice !== String(row.input_price_per_token) ||
    outputPrice !== String(row.output_price_per_token)

  async function save() {
    const pricesChanged =
      inputPrice !== String(row.input_price_per_token) ||
      outputPrice !== String(row.output_price_per_token)
    const fields = {
      input_price_per_token: Number(inputPrice) || 0,
      output_price_per_token: Number(outputPrice) || 0,
    }
    const renamed = trimmedModel !== '' && trimmedModel !== row.model
    if (renamed) {
      setRenaming(true)
      try {
        await onRename(row.model, trimmedModel)
      } finally {
        setRenaming(false)
      }
    }
    if (pricesChanged) {
      onSave(renamed ? trimmedModel : row.model, fields)
    }
  }

  return (
    <tr>
      <td className="py-1 pr-2">
        <Input value={modelName} onChange={(event) => setModelName(event.target.value)} />
      </td>
      <td className="py-1 pr-2">
        <Input type="number" value={inputPrice} onChange={(event) => setInputPrice(event.target.value)} />
      </td>
      <td className="py-1 pr-2">
        <Input type="number" value={outputPrice} onChange={(event) => setOutputPrice(event.target.value)} />
      </td>
      <td className="py-1">
        <div className="flex gap-1">
          <Button variant="outline" size="sm" disabled={busy || renaming || !dirty} onClick={() => void save()}>
            Save
          </Button>
          <Button variant="ghost" size="sm" disabled={busy} onClick={() => onDelete(row.model)}>
            Remove
          </Button>
        </div>
      </td>
    </tr>
  )
}
