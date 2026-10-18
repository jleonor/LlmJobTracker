import { useState } from 'react'

import { AppShell, type Screen } from '@/components/app/AppShell'
import { DashboardPage } from '@/pages/DashboardPage'
import { JobApplicationsPage } from '@/pages/JobApplicationsPage'
import { LlmHistoryPage } from '@/pages/LlmHistoryPage'
import { ProfilePage } from '@/pages/ProfilePage'
import { SettingsPage } from '@/pages/SettingsPage'
import { queueLabel, useClaudeJobs } from '@/lib/useClaudeJobs'
import { useSettings } from '@/lib/useSettings'

function App() {
  const [screen, setScreen] = useState<Screen>('jobs')
  // Clicking "Job Applications" while it's already the current screen doesn't change `screen`
  // (same value, no re-render for that reason) - this signal gives JobApplicationsPage something
  // that always changes on a click, so it can drop back to the table from a job's detail view the
  // same way its own Back button does, even when the screen itself was never "away."
  const [jobsResetSignal, setJobsResetSignal] = useState(0)
  const queue = useClaudeJobs()
  const { settings, reload: reloadSettings } = useSettings()

  function navigate(next: Screen) {
    if (next === 'jobs') setJobsResetSignal((count) => count + 1)
    setScreen(next)
  }

  return (
    <AppShell
      current={screen}
      onNavigate={navigate}
      queueText={queueLabel(queue.jobs)}
      userName={settings.user_name}
    >
      {screen === 'jobs' && <JobApplicationsPage queue={queue} resetSignal={jobsResetSignal} />}
      {screen === 'dashboard' && <DashboardPage />}
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
