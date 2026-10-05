import { Button } from '@/components/ui/button'

function App() {
  return (
    <main className="mx-auto flex min-h-screen max-w-2xl flex-col justify-center gap-4 px-4">
      <h1 className="text-2xl font-semibold">LocalJobTracker</h1>
      <p className="font-mono text-sm text-muted-foreground">Skeleton. Stack check: Inter, JetBrains Mono, shadcn Button.</p>
      <div>
        <Button>Stack check</Button>
      </div>
    </main>
  )
}

export default App
