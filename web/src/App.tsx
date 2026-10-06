import { useState } from 'react'

import { AppShell, type Screen } from '@/components/app/AppShell'
import { JobsPage } from '@/pages/JobsPage'
import { ClaudeJobsPage } from '@/pages/ClaudeJobsPage'
import { ProfilePage } from '@/pages/ProfilePage'
import { queueLabel, useClaudeJobs } from '@/lib/useClaudeJobs'

function App() {
  const [screen, setScreen] = useState<Screen>('jobs')
  const queue = useClaudeJobs()

  return (
    <AppShell current={screen} onNavigate={setScreen} queueText={queueLabel(queue.jobs)}>
      {screen === 'jobs' && <JobsPage />}
      {screen === 'profile' && <ProfilePage />}
      {screen === 'queue' && <ClaudeJobsPage queue={queue} />}
    </AppShell>
  )
}

export default App
