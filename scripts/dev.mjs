#!/usr/bin/env node
/**
 * One command, both processes: the Python API and the Vite dev server.
 *
 * Node builtins only — no npm dependency of its own, so `node scripts/dev.mjs`
 * works before anything is installed and can tell you *what* is missing instead
 * of dying inside a module resolver.
 *
 * Lifecycle: if either child exits, the other is torn down. A dev runner that
 * leaves a stray API bound to 8765 after the UI dies costs more time than it
 * saves.
 */
import { spawn } from 'node:child_process'
import { existsSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'

const ROOT = dirname(dirname(fileURLToPath(import.meta.url)))
const UI = join(ROOT, 'ui')
const VENV_PY = join(ROOT, 'coa_mapper', '.venv', 'bin', 'python')
const API_PORT = Number(process.env.COA_API_PORT ?? 8765)
const UI_PORT = Number(process.env.COA_UI_PORT ?? 5173)

const c = {
  dim: (s) => `\x1b[2m${s}\x1b[0m`,
  bold: (s) => `\x1b[1m${s}\x1b[0m`,
  red: (s) => `\x1b[31m${s}\x1b[0m`,
  green: (s) => `\x1b[32m${s}\x1b[0m`,
  cyan: (s) => `\x1b[36m${s}\x1b[0m`,
}

function die(msg, hint) {
  console.error(`\n${c.red('✕')} ${msg}`)
  if (hint) console.error(`  ${c.dim(hint)}\n`)
  process.exit(1)
}

// -------------------------------------------------------------- preflight
if (!existsSync(VENV_PY)) {
  die(
    `no Python virtualenv at ${c.bold('coa_mapper/.venv')}`,
    'run: make install    (or: python3 -m venv coa_mapper/.venv && coa_mapper/.venv/bin/pip install -e "coa_mapper[dev]")',
  )
}
if (!existsSync(join(UI, 'node_modules'))) {
  die(
    `UI dependencies are not installed`,
    'run: npm --prefix ui install',
  )
}

const children = []
let shuttingDown = false

function shutdown(code = 0) {
  if (shuttingDown) return
  shuttingDown = true
  for (const ch of children) {
    if (!ch.killed) ch.kill('SIGTERM')
  }
  // SIGTERM first, then insist. Vite occasionally ignores the polite request.
  setTimeout(() => {
    for (const ch of children) if (!ch.killed) ch.kill('SIGKILL')
    process.exit(code)
  }, 1200).unref()
}

function start(name, cmd, args, opts = {}) {
  const child = spawn(cmd, args, { stdio: ['ignore', 'pipe', 'pipe'], ...opts })
  children.push(child)

  const tag = c.dim(`[${name}]`)
  const pipe = (stream, to) => {
    let buf = ''
    stream.on('data', (chunk) => {
      buf += chunk.toString()
      const lines = buf.split('\n')
      buf = lines.pop() ?? ''
      for (const line of lines) if (line.trim()) to(`${tag} ${line}`)
    })
  }
  pipe(child.stdout, (l) => console.log(l))
  pipe(child.stderr, (l) => console.error(l))

  child.on('exit', (code, signal) => {
    if (shuttingDown) return
    const how = signal ? `signal ${signal}` : `code ${code}`
    console.error(`\n${c.red('✕')} ${c.bold(name)} exited (${how}) — stopping everything.`)
    shutdown(code ?? 1)
  })
  child.on('error', (err) => die(`could not start ${name}: ${err.message}`))
  return child
}

// -------------------------------------------------------------- go
console.log(`\n${c.bold('coa-mapper')} ${c.dim('dev — API + UI')}\n`)

start('api', VENV_PY, ['-m', 'coa_mapper.cli', 'serve', '--port', String(API_PORT)], {
  cwd: join(ROOT, 'coa_mapper'),
  env: { ...process.env, PYTHONUNBUFFERED: '1' },
})

start('ui', process.execPath, [join(UI, 'node_modules', 'vite', 'bin', 'vite.js'), '--port', String(UI_PORT), '--strictPort'], {
  cwd: UI,
  env: { ...process.env, COA_API: `http://127.0.0.1:${API_PORT}`, FORCE_COLOR: '1' },
})

setTimeout(() => {
  if (shuttingDown) return
  console.log(
    `\n  ${c.green('▸')} UI   ${c.cyan(`http://localhost:${UI_PORT}`)}` +
      `\n  ${c.green('▸')} API  ${c.cyan(`http://127.0.0.1:${API_PORT}/api/health`)}` +
      `\n  ${c.dim('ctrl-c to stop both')}\n`,
  )
}, 1400).unref()

for (const sig of ['SIGINT', 'SIGTERM']) {
  process.on(sig, () => {
    console.log(`\n${c.dim('shutting down…')}`)
    shutdown(0)
  })
}
