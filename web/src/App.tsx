import { useState } from 'react'

import { AppShell, type Screen } from '@/components/app/AppShell'
import { JobApplicationsPage } from '@/pages/JobApplicationsPage'
import { LlmHistoryPage } from '@/pages/LlmHistoryPage'
import { ProfilePage } from '@/pages/ProfilePage'
import { queueLabel, useClaudeJobs } from '@/lib/useClaudeJobs'

function App() {
  const [screen, setScreen] = useState<Screen>('jobs')
  const queue = useClaudeJobs()

  return (
    <AppShell current={screen} onNavigate={setScreen} queueText={queueLabel(queue.jobs)}>
      {screen === 'jobs' && <JobApplicationsPage />}
      {screen === 'profile' && <ProfilePage />}
      {screen === 'queue' && <LlmHistoryPage queue={queue} />}
    </AppShell>
  )
}

export default App
