import { useState } from 'react'

import { AppShell, type Screen } from '@/components/app/AppShell'
import { JobsPage } from '@/pages/JobsPage'
import { ProfilePage } from '@/pages/ProfilePage'

function App() {
  const [screen, setScreen] = useState<Screen>('jobs')

  return (
    <AppShell current={screen} onNavigate={setScreen}>
      {screen === 'jobs' ? <JobsPage /> : <ProfilePage />}
    </AppShell>
  )
}

export default App
