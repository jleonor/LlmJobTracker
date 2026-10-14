import { useCallback, useEffect, useState } from 'react'

import { fetchSettings } from '@/lib/api'
import type { Settings } from '@/lib/types'

const DEFAULT_SETTINGS: Settings = {
  user_name: 'YourName',
  backend: 'claude_code',
  retry_policy: 'reset_time',
  retry_interval_minutes: 60,
  retry_max_attempts: 24,
}

export type SettingsState = { settings: Settings; reload: () => void }

// The sidebar's display name. Shared by the App shell and the Profile page, which edits it, so
// saving there updates the sidebar right away (D-94).
export function useSettings(): SettingsState {
  const [settings, setSettings] = useState<Settings>(DEFAULT_SETTINGS)

  const reload = useCallback(() => {
    fetchSettings()
      .then(setSettings)
      .catch(() => undefined) // The sidebar falls back to the default name; not worth an alert.
  }, [])

  useEffect(() => {
    reload()
  }, [reload])

  return { settings, reload }
}
