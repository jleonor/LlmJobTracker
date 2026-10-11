import { useState } from 'react'

import { AppShell, type Screen } from '@/components/app/AppShell'
import { JobApplicationsPage } from '@/pages/JobApplicationsPage'
import { LlmHistoryPage } from '@/pages/LlmHistoryPage'
import { ProfilePage } from '@/pages/ProfilePage'
import { queueLabel, useClaudeJobs } from '@/lib/useClaudeJobs'
import { useSettings } from '@/lib/useSettings'

function App() {
  const [screen, setScreen] = useState<Screen>('jobs')
  const queue = useClaudeJobs()
  const { settings, reload: reloadSettings } = useSettings()

  return (
    <AppShell
      current={screen}
      onNavigate={setScreen}
      queueText={queueLabel(queue.jobs)}
      userName={settings.user_name}
    >
      {screen === 'jobs' && <JobApplicationsPage queue={queue} />}
      {screen === 'profile' && (
        <ProfilePage userName={settings.user_name} onNameChanged={reloadSettings} />
      )}
      {screen === 'queue' && <LlmHistoryPage queue={queue} />}
    </AppShell>
  )
}

export default App
