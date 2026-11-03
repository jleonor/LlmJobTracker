import { useEffect, useState } from 'react'

import { Button } from '@/components/ui/button'
import { Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { ApiError, fetchLlmAppStatus, openLlmApp } from '@/lib/api'
import { LLM_APP_LABELS } from '@/lib/backends'
import { useSettings } from '@/lib/useSettings'
import type { LlmAppStatus, OpenLlmAppTarget } from '@/lib/types'

// A per-application "Open LLM app" (D-294, Phase 17) next to Delete on the Job Application and
// Open Application detail pages - Settings' own OpenLlmAppSection install-check/confirm-dialog
// pattern, trimmed to one application: no export-path field, no appCount fetch (the dialog
// names this one application instead). Self-contained (own useSettings/status fetch) rather than
// threading settings down through JobApplicationsPage/OpenApplicationsPage, which don't carry it
// today.
export function OpenLlmAppButton({ target, label }: { target: OpenLlmAppTarget; label: string }) {
  const { settings } = useSettings()
  const [installStatus, setInstallStatus] = useState<LlmAppStatus | null>(null)
  const [confirmOpen, setConfirmOpen] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [opened, setOpened] = useState<string | null>(null)

  useEffect(() => {
    fetchLlmAppStatus()
      .then((result) => setInstallStatus(result[settings.backend]))
      .catch(() => undefined) // optimistic fallback below, same as Settings' own section
  }, [settings.backend])

  // Optimistic until the check actually says otherwise, matching Settings' own default.
  const installed = installStatus ? installStatus.installed : true

  function openConfirm() {
    setError(null)
    setOpened(null)
    setConfirmOpen(true)
  }

  async function confirmAndOpen() {
    setBusy(true)
    setError(null)
    try {
      const result = await openLlmApp(target)
      setOpened(result.opened_path)
      setConfirmOpen(false)
    } catch (failure) {
      setError(failure instanceof ApiError ? failure.message : 'Could not open the LLM app.')
    } finally {
      setBusy(false)
    }
  }

  const appLabel = LLM_APP_LABELS[settings.backend]

  return (
    <>
      <Button
        variant="outline"
        size="sm"
        disabled={!installed}
        title={installed ? undefined : `${appLabel} is not installed.`}
        onClick={openConfirm}
      >
        Open LLM app
      </Button>
      {opened && (
        <p className="text-xs text-muted-foreground">
          Opened <span className="font-mono">{opened}</span> in {appLabel}.
        </p>
      )}
      {error && <p className="text-sm text-destructive">{error}</p>}

      <Dialog open={confirmOpen} onOpenChange={setConfirmOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Open LLM app?</DialogTitle>
          </DialogHeader>
          <p className="text-sm text-muted-foreground">
            A backup export will be rebuilt first, then your real, live data folder will open in{' '}
            {appLabel}, told to focus on {label} - it can read and change the live files there.
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
    </>
  )
}
