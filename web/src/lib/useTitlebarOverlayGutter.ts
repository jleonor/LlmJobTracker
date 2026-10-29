// Windows' titleBarOverlay (electron/main.js) draws the native min/max/close controls on top of
// the web page's own header, in the window's top-right corner - nothing in CSS can see them, and
// AppShell's header previously got away with it only because its one right-aligned element
// (the LLM status text) happened to sit clear of that area. Adding the Trigger workflows button
// (D-288) widened that group enough to go underneath the controls, found live in the packaged
// Electron shell (D-269/D-278's titleBarOverlay).
//
// A first version of this hook measured the reserved width live via the Window Controls Overlay
// API (`navigator.windowControlsOverlay`). In practice its `geometrychange` event did not fire
// reliably on a plain resize or maximize in this Electron BrowserWindow setup (it is normally
// used with a PWA manifest, not this app's own titleBarOverlay option), so the gutter froze at
// whatever it measured once at startup - wrong for every other window state, found live by the
// user (the group ending up hidden on maximize, or stranded mid-header on a small window). A
// fixed, hand-tuned width is reserved instead, the same way electron/main.js hand-syncs
// NAVBAR_COLOR/NAVBAR_SYMBOL_COLOR for this same integration point: Windows' default three-button
// caption cluster is consistently around 138 CSS px regardless of window size or DPI (Chromium
// handles DPI scaling transparently in CSS pixels), so a flat, generous constant is both simpler
// and more reliable than a live measurement that could not be trusted.
const WINDOWS_TITLEBAR_CONTROLS_WIDTH = 150

// 0 outside Electron on Windows, so the plain browser and macOS (which has no titleBarOverlay,
// per main.js) are unaffected. Checked via the renderer's own user agent, which Electron sets by
// default - no IPC/preload plumbing exists yet to ask the main process directly.
function isElectronOnWindows(): boolean {
  if (typeof navigator === 'undefined') return false
  return navigator.userAgent.includes('Electron') && navigator.userAgent.includes('Windows')
}

export function useTitlebarOverlayGutter(): number {
  return isElectronOnWindows() ? WINDOWS_TITLEBAR_CONTROLS_WIDTH : 0
}
