// Phase 13 (D-17, D-264): dev-mode Electron shell. Starts the API and the web dev server the
// same way scripts/dev.py does (Electron owns the child processes directly here, rather than
// scripts/dev.py, so it can start and stop them from its own window lifecycle), then opens a
// window at the Vite dev server's URL instead of the system browser. Because this still goes
// through the Vite dev server, its existing proxy keeps injecting X-Launch-Token
// (web/vite.config.ts) - no token handling is needed here. That only arrives in Phase 14, once
// the window loads the built static files with no dev-server proxy in front.

const { app, BrowserWindow, Menu, shell } = require('electron')
const { spawn, execFile } = require('node:child_process')
const crypto = require('node:crypto')
const http = require('node:http')
const path = require('node:path')
const fs = require('node:fs')

const ROOT = path.resolve(__dirname, '..')
const API_DIR = path.join(ROOT, 'api')
const WEB_DIR = path.join(ROOT, 'web')
const WEB_URL = 'http://127.0.0.1:5173/'
const IS_WINDOWS = process.platform === 'win32'
const WINDOW_TITLE = 'LLM Job Tracker'
const ICON_PATH = path.join(__dirname, 'assets', 'icon.png')

// No File/Edit/View/Window menu bar - this is a single-purpose app shell, not a document editor.
Menu.setApplicationMenu(null)

function apiPython() {
  const relative = IS_WINDOWS ? ['Scripts', 'python.exe'] : ['bin', 'python']
  return path.join(API_DIR, '.venv', ...relative)
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
let webProcess = null
let shuttingDown = false

function spawnWebServer(env, spawnOptions) {
  if (IS_WINDOWS) {
    // npm's Windows launcher is a .cmd file - Node's spawn needs shell:true to run one
    // directly (EINVAL otherwise, a well-known Node-on-Windows limitation). Passed as one
    // command string, not args+shell:true, to avoid Node's "arguments not escaped" warning
    // for that combination.
    return spawn('npm run dev -- --port 5173 --strictPort', {
      cwd: WEB_DIR,
      env,
      ...spawnOptions,
      shell: true,
    })
  }
  return spawn('npm', ['run', 'dev', '--', '--port', '5173', '--strictPort'], {
    cwd: WEB_DIR,
    env,
    ...spawnOptions,
  })
}

function startBackendAndWebServer() {
  const python = apiPython()
  if (!fs.existsSync(python)) {
    throw new Error(`The API environment is missing (${python}). Run "uv sync" in api/ first.`)
  }

  const token = crypto.randomBytes(32).toString('base64url')
  const env = { ...process.env, LJT_TOKEN: token }
  const spawnOptions = IS_WINDOWS ? { detached: false } : { detached: true }

  apiProcess = spawn(python, ['-m', 'llmjobtracker'], { cwd: API_DIR, env, ...spawnOptions })
  webProcess = spawnWebServer(env, spawnOptions)

  for (const [name, child] of [['API', apiProcess], ['web', webProcess]]) {
    child.stdout?.on('data', (chunk) => process.stdout.write(`[${name}] ${chunk}`))
    child.stderr?.on('data', (chunk) => process.stderr.write(`[${name}] ${chunk}`))
    // Without this, an unhandled 'error' event (e.g. the executable not found) throws
    // synchronously and crashes the whole main process before any cleanup can run, leaving
    // the other child orphaned - caught live while building this (D-17's "stops the backend"
    // promise failing exactly when it mattered most, on a spawn error).
    child.on('error', (error) => {
      console.error(`[${name}] failed to start:`, error)
      quitAndCleanUp()
    })
    child.on('exit', (code, signal) => {
      if (shuttingDown) return
      console.error(`[${name}] exited unexpectedly (code ${code}, signal ${signal})`)
      quitAndCleanUp()
    })
  }
}

function stopBackendAndWebServer() {
  stopTree(apiProcess)
  stopTree(webProcess)
  apiProcess = null
  webProcess = null
}

function quitAndCleanUp() {
  if (shuttingDown) return
  shuttingDown = true
  stopBackendAndWebServer()
  app.quit()
}

async function createWindow() {
  startBackendAndWebServer()
  await waitForUrl(WEB_URL, 60_000)

  const window = new BrowserWindow({
    width: 1400,
    height: 900,
    title: WINDOW_TITLE,
    icon: ICON_PATH,
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
  stopBackendAndWebServer()
})
