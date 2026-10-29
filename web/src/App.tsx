import { useState } from 'react'

import { AppShell, type Screen } from '@/components/app/AppShell'
import { DashboardPage } from '@/pages/DashboardPage'
import { JobApplicationsPage } from '@/pages/JobApplicationsPage'
import { LlmHistoryPage } from '@/pages/LlmHistoryPage'
import { ProfilePage } from '@/pages/ProfilePage'
import { SettingsPage } from '@/pages/SettingsPage'
import { triggerStagedJobs } from '@/lib/api'
import { queueLabel, stagedCount, useClaudeJobs } from '@/lib/useClaudeJobs'
import { useScrollbarAutoHide } from '@/lib/scrollbarAutoHide'
import { useSettings } from '@/lib/useSettings'

function App() {
  useScrollbarAutoHide()
  const [screen, setScreen] = useState<Screen>('jobs')
  // Clicking "Job Applications" while it's already the current screen doesn't change `screen`
  // (same value, no re-render for that reason) - this signal gives JobApplicationsPage something
  // that always changes on a click, so it can drop back to the table from a job's detail view the
  // same way its own Back button does, even when the screen itself was never "away."
  const [jobsResetSignal, setJobsResetSignal] = useState(0)
  const queue = useClaudeJobs()
  const { settings, reload: reloadSettings } = useSettings()
  const [triggeringStaged, setTriggeringStaged] = useState(false)

  function navigate(next: Screen) {
    if (next === 'jobs') setJobsResetSignal((count) => count + 1)
    setScreen(next)
  }

  // The header's "Trigger workflows" button (D-288): fires immediately, no confirmation - the
  // user's explicit choice, matching how Resume/Cancel already work elsewhere in the app.
  async function triggerStaged() {
    setTriggeringStaged(true)
    try {
      await triggerStagedJobs()
      queue.reload()
    } catch (failure) {
      console.error('Could not trigger staged workflows.', failure)
    } finally {
      setTriggeringStaged(false)
    }
  }

  return (
    <AppShell
      current={screen}
      onNavigate={navigate}
      queueText={queueLabel(queue.jobs)}
      userName={settings.user_name}
      stagedCount={stagedCount(queue.jobs)}
      onTriggerStaged={() => void triggerStaged()}
      triggeringStaged={triggeringStaged}
    >
      {screen === 'jobs' && <JobApplicationsPage queue={queue} resetSignal={jobsResetSignal} />}
      {screen === 'dashboard' && <DashboardPage settings={settings} queue={queue} />}
      {screen === 'profile' && (
        <ProfilePage userName={settings.user_name} onNameChanged={reloadSettings} />
      )}
      {screen === 'queue' && <LlmHistoryPage queue={queue} />}
      {screen === 'settings' && (
        <SettingsPage settings={settings} onSettingsChanged={reloadSettings} queue={queue} />
      )}
    </AppShell>
  )
}

export default App
