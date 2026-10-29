import { useEffect, useState } from 'react'

// Windows' titleBarOverlay (electron/main.js) draws the native min/max/close controls on top of
// the web page's own header, in the window's top-right corner - nothing in CSS can see them, and
// AppShell's header previously got away with it only because its one right-aligned element
// (the LLM status text) happened to sit clear of that area. Adding the Trigger workflows button
// (D-288) widened that group enough to go underneath the controls, found live in the packaged
// Electron shell (D-269/D-278's titleBarOverlay).
//
// The Window Controls Overlay API becomes available in the renderer whenever a BrowserWindow is
// created with `titleBarOverlay` set (true outside Electron/Windows and in a plain browser,
// where this returns 0 and the header is unaffected). It reports the real, DPI-correct reserved
// width - no guessed pixel constant to keep in sync with Windows' own control sizing.
type WindowControlsOverlay = {
  getTitlebarAreaRect: () => { x: number; width: number }
  addEventListener: (type: 'geometrychange', listener: () => void) => void
  removeEventListener: (type: 'geometrychange', listener: () => void) => void
}

function windowControlsOverlay(): WindowControlsOverlay | undefined {
  return (navigator as Navigator & { windowControlsOverlay?: WindowControlsOverlay })
    .windowControlsOverlay
}

export function useTitlebarOverlayGutter(): number {
  const [gutter, setGutter] = useState(0)

  useEffect(() => {
    const overlay = windowControlsOverlay()
    if (!overlay) return

    function update() {
      const rect = overlay!.getTitlebarAreaRect()
      setGutter(Math.max(0, window.innerWidth - rect.x - rect.width))
    }

    update()
    overlay.addEventListener('geometrychange', update)
    return () => overlay.removeEventListener('geometrychange', update)
  }, [])

  return gutter
}
