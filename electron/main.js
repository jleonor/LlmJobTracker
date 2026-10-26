// Phase 13 (D-17, D-264): dev-mode Electron shell. Starts the API and the web dev server the
// same way scripts/dev.py does (Electron owns the child processes directly here, rather than
// scripts/dev.py, so it can start and stop them from its own window lifecycle), then opens a
// window at the Vite dev server's URL instead of the system browser. Because this still goes
// through the Vite dev server, its existing proxy keeps injecting X-Launch-Token
// (web/vite.config.ts) - no token handling is needed here. That only arrives in Phase 14, once
// the window loads the built static files with no dev-server proxy in front.

const { app, BrowserWindow } = require('electron')
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

function startBackendAndWebServer() {
  const python = apiPython()
  if (!fs.existsSync(python)) {
    throw new Error(`The API environment is missing (${python}). Run "uv sync" in api/ first.`)
  }

  const token = crypto.randomBytes(32).toString('base64url')
  const env = { ...process.env, LJT_TOKEN: token }
  const spawnOptions = IS_WINDOWS ? { detached: false } : { detached: true }

  apiProcess = spawn(python, ['-m', 'llmjobtracker'], { cwd: API_DIR, env, ...spawnOptions })
  webProcess = spawn(
    IS_WINDOWS ? 'npm.cmd' : 'npm',
    ['run', 'dev', '--', '--port', '5173', '--strictPort'],
    { cwd: WEB_DIR, env, ...spawnOptions }
  )

  for (const [name, child] of [['API', apiProcess], ['web', webProcess]]) {
    child.stdout?.on('data', (chunk) => process.stdout.write(`[${name}] ${chunk}`))
    child.stderr?.on('data', (chunk) => process.stderr.write(`[${name}] ${chunk}`))
  }
}

function stopBackendAndWebServer() {
  stopTree(apiProcess)
  stopTree(webProcess)
  apiProcess = null
  webProcess = null
}

async function createWindow() {
  startBackendAndWebServer()
  await waitForUrl(WEB_URL, 60_000)

  const window = new BrowserWindow({ width: 1400, height: 900 })
  await window.loadURL(WEB_URL)
}

app.whenReady().then(() => {
  createWindow().catch((error) => {
    console.error(error)
    app.quit()
  })
})

app.on('window-all-closed', () => {
  app.quit()
})

app.on('will-quit', () => {
  stopBackendAndWebServer()
})
