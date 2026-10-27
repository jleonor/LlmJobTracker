// Phase 15 (D-17, D-268): production Electron shell. Launches the PyInstaller-bundled backend
// executable (no separate Python/uv needed) and serves the built frontend (web/dist) from a
// small static file server this process runs itself, with that same server proxying /api/* to
// the backend and injecting X-Launch-Token - taking over the role Vite's dev-mode proxy played
// in Phase 13 (web/vite.config.ts), since there is no dev server in front of the built app.

const { app, BrowserWindow, Menu, shell, nativeTheme } = require('electron')
const { spawn, execFile } = require('node:child_process')
const crypto = require('node:crypto')
const http = require('node:http')
const path = require('node:path')
const fs = require('node:fs')

const ROOT = path.resolve(__dirname, '..')
const API_DIR = path.join(ROOT, 'api')
const WEB_DIR = path.join(ROOT, 'web')
const IS_WINDOWS = process.platform === 'win32'
const API_PORT = 8765
const WEB_PORT = 5173
const WEB_URL = `http://127.0.0.1:${WEB_PORT}/`
const TOKEN_HEADER = 'x-launch-token'
const WINDOW_TITLE = 'LLM Job Tracker'
const ICON_PATH = path.join(__dirname, 'assets', 'icon.png')
// The app's own --card/--foreground tokens (web/src/index.css) - kept in sync by hand, since the
// native title bar overlay can't read CSS. Used for the Windows titleBarOverlay below so the
// native strip matches the web page's own header exactly.
const NAVBAR_COLOR = '#181c21'
const NAVBAR_SYMBOL_COLOR = '#e0e2e9'

const MIME_TYPES = {
  '.html': 'text/html; charset=utf-8',
  '.js': 'text/javascript; charset=utf-8',
  '.css': 'text/css; charset=utf-8',
  '.svg': 'image/svg+xml',
  '.woff': 'font/woff',
  '.woff2': 'font/woff2',
  '.json': 'application/json; charset=utf-8',
  '.png': 'image/png',
  '.ico': 'image/x-icon',
}

// No File/Edit/View/Window menu bar - this is a single-purpose app shell, not a document editor.
Menu.setApplicationMenu(null)
// Windows draws the titleBarOverlay's window-control glyphs per the OS's own light/dark setting
// when this is 'system' - matches the system theme (the page content itself stays dark-only for
// now, D-17's phase).
nativeTheme.themeSource = 'system'

// In a packaged build, electron-builder copies these under extraResources (electron-builder.yml);
// in a repo checkout, they're the ordinary build output of steps 2 and the web build.
function backendExecutablePath() {
  const dir = app.isPackaged ? path.join(process.resourcesPath, 'backend') : path.join(API_DIR, 'dist', 'llmjobtracker-api')
  const exeName = IS_WINDOWS ? 'llmjobtracker-api.exe' : 'llmjobtracker-api'
  return path.join(dir, exeName)
}

function webDistPath() {
  return app.isPackaged ? path.join(process.resourcesPath, 'web') : path.join(WEB_DIR, 'dist')
}

function waitForUrl(url, timeoutMs) {
  const deadline = Date.now() + timeoutMs
  return new Promise((resolve, reject) => {
    const attempt = () => {
      const request = http.get(url, (response) => {
        response.resume()
        resolve()
      })
      request.on('error', () => {
        if (Date.now() > deadline) {
          reject(new Error(`Timed out waiting for ${url}`))
          return
        }
        setTimeout(attempt, 500)
      })
    }
    attempt()
  })
}

function stopTree(child) {
  if (!child || child.exitCode !== null || child.killed) return
  if (IS_WINDOWS) {
    execFile('taskkill', ['/PID', String(child.pid), '/T', '/F'])
  } else {
    try {
      process.kill(-child.pid, 'SIGTERM')
    } catch {
      child.kill('SIGTERM')
    }
  }
}

let apiProcess = null
let localServer = null
let shuttingDown = false

function startBackend() {
  const exe = backendExecutablePath()
  if (!fs.existsSync(exe)) {
    throw new Error(`The backend executable is missing (${exe}). Run PyInstaller in api/ first.`)
  }

  const token = crypto.randomBytes(32).toString('base64url')
  const env = { ...process.env, LJT_TOKEN: token }
  const spawnOptions = IS_WINDOWS ? { detached: false } : { detached: true }

  apiProcess = spawn(exe, [], { cwd: path.dirname(exe), env, ...spawnOptions })
  apiProcess.stdout?.on('data', (chunk) => process.stdout.write(`[api] ${chunk}`))
  apiProcess.stderr?.on('data', (chunk) => process.stderr.write(`[api] ${chunk}`))
  // Without this, an unhandled 'error' event (e.g. the executable not found) throws
  // synchronously and crashes the whole main process before any cleanup can run - caught live
  // while building Phase 13's version of this (D-17's "stops the backend" promise failing
  // exactly when it mattered most, on a spawn error).
  apiProcess.on('error', (error) => {
    console.error('[api] failed to start:', error)
    quitAndCleanUp()
  })
  apiProcess.on('exit', (code, signal) => {
    if (shuttingDown) return
    console.error(`[api] exited unexpectedly (code ${code}, signal ${signal})`)
    quitAndCleanUp()
  })

  return token
}

function serveStatic(req, res, rootDir) {
  const urlPath = decodeURIComponent(req.url.split('?')[0])
  let filePath = path.join(rootDir, urlPath === '/' ? 'index.html' : urlPath)
  // Keep the resolved path inside rootDir - a malicious or malformed urlPath (e.g. "/../../x")
  // must not escape it.
  if (!filePath.startsWith(rootDir)) {
    filePath = path.join(rootDir, 'index.html')
  }
  if (!fs.existsSync(filePath) || fs.statSync(filePath).isDirectory()) {
    // No client-side router today, but falling back to index.html for an unknown path is the
    // standard single-page-app behavior and costs nothing if one is ever added.
    filePath = path.join(rootDir, 'index.html')
  }
  const contentType = MIME_TYPES[path.extname(filePath)] ?? 'application/octet-stream'
  res.writeHead(200, { 'Content-Type': contentType })
  fs.createReadStream(filePath).pipe(res)
}

function proxyToApi(req, res, token) {
  const headers = { ...req.headers, [TOKEN_HEADER]: token }
  delete headers.host
  const upstream = http.request(
    {
      hostname: '127.0.0.1',
      port: API_PORT,
      path: req.url.replace(/^\/api/, ''),
      method: req.method,
      headers,
    },
    (upstreamRes) => {
      res.writeHead(upstreamRes.statusCode, upstreamRes.headers)
      upstreamRes.pipe(res)
    },
  )
  upstream.on('error', (error) => {
    console.error('[proxy] backend request failed:', error)
    res.writeHead(502)
    res.end('Bad gateway')
  })
  req.pipe(upstream)
}

function startLocalServer(webDir, token) {
  const server = http.createServer((req, res) => {
    if (req.url.startsWith('/api/')) {
      proxyToApi(req, res, token)
      return
    }
    serveStatic(req, res, webDir)
  })
  return new Promise((resolve, reject) => {
    server.once('error', reject)
    server.listen(WEB_PORT, '127.0.0.1', () => resolve(server))
  })
}

function stopBackendAndServer() {
  stopTree(apiProcess)
  apiProcess = null
  localServer?.close()
  localServer = null
}

function quitAndCleanUp() {
  if (shuttingDown) return
  shuttingDown = true
  stopBackendAndServer()
  app.quit()
}

async function createWindow() {
  const token = startBackend()
  await waitForUrl(`http://127.0.0.1:${API_PORT}/health`, 60_000)
  localServer = await startLocalServer(webDistPath(), token)

  const window = new BrowserWindow({
    width: 1400,
    height: 900,
    title: WINDOW_TITLE,
    icon: ICON_PATH,
    backgroundColor: NAVBAR_COLOR,
    // Windows/Linux only (BrowserWindow ignores titleBarOverlay elsewhere): hides the native
    // title text/strip, keeping just the min/max/close controls, overlaid in the navbar's own
    // color - the web page's own header (AppShell.tsx) becomes the rest of that strip, draggable.
    // macOS has no equivalent color-themed overlay.
    ...(IS_WINDOWS
      ? {
          titleBarStyle: 'hidden',
          titleBarOverlay: { color: NAVBAR_COLOR, symbolColor: NAVBAR_SYMBOL_COLOR, height: 56 },
        }
      : {}),
  })
  window.removeMenu()
  // The page's own <title>("LlmJobTracker") would otherwise replace this once it loads.
  window.on('page-title-updated', (event) => event.preventDefault())

  // Job postings, portal links, etc. (target="_blank") should open in the user's own browser,
  // not another copy of this app's own shell window.
  window.webContents.setWindowOpenHandler(({ url }) => {
    shell.openExternal(url)
    return { action: 'deny' }
  })
  // A plain (same-window) link to an outside site is treated the same way, so it can't
  // navigate this app's own window away from itself either.
  window.webContents.on('will-navigate', (event, url) => {
    if (new URL(url).origin !== new URL(WEB_URL).origin) {
      event.preventDefault()
      shell.openExternal(url)
    }
  })

  await window.loadURL(WEB_URL)
}

app.whenReady().then(() => {
  createWindow().catch((error) => {
    console.error(error)
    quitAndCleanUp()
  })
})

app.on('window-all-closed', () => {
  quitAndCleanUp()
})

app.on('will-quit', () => {
  stopBackendAndServer()
})
