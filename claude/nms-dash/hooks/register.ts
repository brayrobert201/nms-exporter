// nms-dash: the No Man's Sky exporter at the prompt.
//
//   /nms            the rundown scripts/nms-rundown.py prints: craftable devices,
//                   farms by time to full, refiners, plants
//   /nms diff       what changed since the previous save (the exporter's /diff)
//   /deploy-nms     scripts/dev-deploy.sh: test the working tree on :9878, install
//                   to /opt, reload the wall screens ("render" also renders the
//                   right screen, "test" stops before installing)
//
// The status line carries the one-line summary, refreshed every minute, and the
// rundown as it stood when the session started is added to the system prompt so a
// conversation opens already knowing the state. It is captured once: a section
// that changed every minute would invalidate the prompt cache every turn.
import type { EngineInterface, Register } from 'claude-code'

const REPO = '/home/bob/Projects/nms-exporter'
const RUNDOWN = `${REPO}/scripts/nms-rundown.py`
const DEPLOY = `${REPO}/scripts/dev-deploy.sh`
const STATUS_EVERY_MS = 60_000

let openingState = ''

async function rundown($: EngineInterface, args: readonly string[] = []): Promise<string> {
  const { exitCode, stdout, stderr } = await $.process.run(['python3', RUNDOWN, ...args], { timeoutMs: 20_000 })
  return exitCode === 0 ? stdout.trim() : `rundown failed (exit ${exitCode}): ${stderr.trim()}`
}

export const register: Register = on => {
  on('session.start', async ($, e, next) => {
    await $.command.register({
      name: 'nms',
      description: "No Man's Sky state: craftable devices, farms, refiners, plants. Add \"diff\" for what changed since the previous save.",
    })
    await $.command.register({
      name: 'deploy-nms',
      description: 'Test the nms-exporter working tree on :9878, install to /opt and reload the wall screens. Add "render" to render the right screen, "test" to stop before installing.',
    })
    const refreshStatus = async () => {
      try {
        $.ui.status(await rundown($, ['--short']))
      } catch {
        $.ui.status('NMS: exporter unreachable')
      }
    }
    try {
      openingState = await rundown($)
    } catch {
      openingState = ''
    }
    await refreshStatus()
    $.clock.every(STATUS_EVERY_MS, refreshStatus)
    return next(e)
  })

  on('command.run', { command: 'nms' }, async ($, e) => {
    const text = /\bdiff\b/i.test(e.args) ? await rundown($, ['--diff']) : await rundown($)
    return { text }
  })

  on('command.run', { command: 'deploy-nms' }, async ($, e) => {
    const flags: string[] = []
    if (/\brender\b/i.test(e.args)) flags.push('--render')
    if (/\btest\b/i.test(e.args)) flags.push('--test')
    const { exitCode, stdout, stderr } = await $.process.run(['bash', DEPLOY, ...flags], { cwd: REPO, timeoutMs: 600_000 })
    const tail = `${stdout}\n${stderr}`.trim().split('\n').slice(-40).join('\n')
    const head = exitCode === 0 ? 'deploy ok' : `deploy failed (exit ${exitCode})`
    return { text: `${head}\n${tail}` }
  })

  on('prompt.compose', async ($, e, next) => {
    const { sections } = await next(e)
    if (!openingState) return { sections }
    return {
      sections: [
        ...sections,
        {
          id: 'nms-dash:state',
          scope: 'session',
          text: `No Man's Sky state when this session started, from the local nms-exporter (run /nms for the current rundown, /nms diff for changes since the previous save):\n${openingState}`,
        },
      ],
    }
  })
}
