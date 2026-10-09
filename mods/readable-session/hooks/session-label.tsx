import { atom, read, update } from 'claude-code'
import type { EngineInterface as Dollar, On } from 'claude-code'

import type { SessionLabel } from '../types'

/**
 * The prompt bar's label and color, the way /rename and /color set them:
 *
 * - Name: every session shows Claude Code's own AI title as a slug
 *   ("statusline.py usage accuracy" -> "statusline-py-usage-accuracy"),
 *   never over a name the person gave (custom title or agent name).
 *   Resumed: at once, through SessionStart's `sessionTitle`. New: `/rename`
 *   right after the first reply; else UserPromptSubmit's `sessionTitle`.
 * - Color: orange, unless the session already has one (a resumed transcript
 *   with an `agent-color` entry).
 *
 * Both act only on sessions this module saw start (classic.SessionStart), so
 * a hot reload never renames or recolors a session that was already running.
 */

const label = atom({ plugin: 'readable-session', key: 'label' } as const, null)

export const DEFAULT_COLOR = 'orange'
export const MAX_SLUG = 40
/** What one `$.fs.read` copies at most (4 MiB); a bigger transcript is tailed. */
const READ_LIMIT = 4 * 1024 * 1024
/** Tries at turn end while the AI title is not in the transcript yet. */
const NAME_TRIES = 3
const RETRY_MS = 3000

const noop = () => undefined

/** "statusline.py usage accuracy" -> "statusline-py-usage-accuracy", cut at a word near MAX_SLUG. */
export function slug(title: string, max = MAX_SLUG): string {
  const s = title
    .toLowerCase()
    .replace(/[^\p{L}\p{N}]+/gu, '-')
    .replace(/^-+|-+$/g, '')
  if (s.length <= max) return s
  const cut = s.slice(0, max + 1)
  const dash = cut.lastIndexOf('-')
  return (dash >= max / 2 ? cut.slice(0, dash) : s.slice(0, max)).replace(/-+$/, '')
}

export type TranscriptFacts = {
  /** The newest AI-generated title, when the transcript has one. */
  aiTitle?: string
  /** The person named it: a non-empty custom title or agent name. */
  isNamed: boolean
  /** Some `/color` was set for it. */
  hasColor: boolean
}

const META = ['ai-title', 'custom-title', 'agent-name', 'agent-color'] as const
const PREFIXES = META.map(t => `{"type":"${t}"`)

/**
 * Reads the session metadata lines out of a transcript (or a tail of one).
 * Claude Code re-appends them as the session goes, so the last of each wins.
 * Only lines that start as a metadata entry count: the same words inside a
 * message are escaped and never match.
 */
export function scanTranscript(text: string): TranscriptFacts {
  let aiTitle: string | undefined
  let customTitle = ''
  let agentName = ''
  let hasColor = false
  for (const line of text.split('\n')) {
    if (!PREFIXES.some(p => line.startsWith(p))) continue
    let d: Record<string, unknown>
    try {
      d = JSON.parse(line)
    } catch {
      continue
    }
    const s = (k: string) => (typeof d[k] === 'string' ? (d[k] as string) : '')
    switch (d.type) {
      case 'ai-title':
        if (s('aiTitle').trim()) aiTitle = s('aiTitle').trim()
        break
      case 'custom-title':
        customTitle = s('customTitle').trim()
        break
      case 'agent-name':
        agentName = s('agentName').trim()
        break
      case 'agent-color':
        hasColor = true
        break
    }
  }
  return { aiTitle, isNamed: !!(customTitle || agentName), hasColor }
}

/** Prints the metadata lines of the transcript's last 8 MiB: for files over READ_LIMIT. */
export const TAIL_PY = [
  'import sys',
  'p = sys.argv[1]',
  'with open(p, "rb") as f:',
  '    f.seek(0, 2); n = f.tell(); f.seek(max(0, n - (8 << 20))); b = f.read()',
  `pre = (${PREFIXES.map(p => `b'${p}'`).join(', ')})`,
  'sys.stdout.buffer.write(b"\\n".join(l for l in b.split(b"\\n") if l.startswith(pre)))',
].join('\n')

/** The transcript's facts; undefined when it cannot be read (missing, python absent). */
export async function readFacts($: Dollar, path: string): Promise<TranscriptFacts | undefined> {
  if (!path) return undefined
  try {
    const stat = await $.fs.stat(path)
    if (stat.size <= READ_LIMIT) return scanTranscript(await $.fs.read(path))
    const r = await $.process.run(['python', '-I', '-c', TAIL_PY, path], { timeoutMs: 10000 })
    return r.exitCode === 0 ? scanTranscript(r.stdout) : undefined
  } catch {
    return undefined
  }
}

/** Runs a slash command once the hook that asked has returned (the session queues it until idle). */
function runLater($: Dollar, command: string, args: string) {
  $.clock.after(0, () => {
    void $.command.run({ command, args }).catch(noop)
  })
}

async function setLabel($: Dollar, value: SessionLabel | null) {
  await update($, label, () => value).catch(noop)
}

/** Renames a session this module saw start, once its AI title is in the transcript. */
async function nameAtTurnEnd($: Dollar, sessionId: string, path: string, tries: number): Promise<void> {
  const cur = await read($, label).catch(() => null)
  if (!cur || cur.sessionId !== sessionId || cur.status !== 'pending') return
  const facts = await readFacts($, path)
  if (facts?.isNamed) return setLabel($, { ...cur, status: 'done' })
  const name = facts?.aiTitle ? slug(facts.aiTitle) : ''
  if (name) {
    await setLabel($, { ...cur, status: 'done', renamedTo: name })
    runLater($, 'rename', name)
    return
  }
  if (tries > 1) {
    $.clock.after(RETRY_MS, () => {
      void nameAtTurnEnd($, sessionId, path, tries - 1).catch(noop)
    })
  }
}

/**
 * True for a SessionStart raised late, into a session that was already
 * running before this module first saw one: the engine can run a plugin's
 * SessionStart hooks when a reload gives it hooks it lacked at start. Such a
 * session has had a turn (the `running` list was written) but this module
 * never tracked it (no `label` yet). It is left exactly as it is.
 */
async function startedBeforeThisModule($: Dollar): Promise<boolean> {
  try {
    const tracked = await $.state.get({ plugin: 'readable-session', key: 'label' })
    if (tracked.version > 0) return false
    const active = await $.state.get({ plugin: 'readable-session', key: 'running' })
    return active.version > 0
  } catch {
    return true
  }
}

export function registerSessionLabel(on: On) {
  // The output line of the /color and /rename this module runs is drawn
  // empty ("Session color set to: orange"); the stored row keeps it. The
  // command's echo row ("> /color orange") raises no render event to hook.
  on('ui.render', { component: 'CommandOutput' }, async ($, e, next) => {
    const p = e.props
    if (p.isErrored || (p.command !== 'color' && p.command !== 'rename')) return next(e)
    const cur = await read($, label).catch(() => null)
    const isOurs =
      p.command === 'color'
        ? !!cur?.colored && p.args.trim() === DEFAULT_COLOR && /color set to:? orange/i.test(p.text)
        : !!cur?.renamedTo && p.args.trim() === cur.renamedTo
    if (!isOurs) return next(e)
    const { Box } = $.ui.resolve(e)
    return <Box />
  })

  on('classic.SessionStart', async ($, e, next) => {
    const result = await next(e)
    if (e.source === 'compact') return result
    if (await startedBeforeThisModule($)) return result
    const surfaces = await $.session.surfaces().catch((): readonly string[] => [])
    if (!surfaces.includes('terminal')) return result

    const isResume = e.source === 'resume' || e.source === 'fork'
    const facts = isResume ? await readFacts($, e.transcript_path) : { isNamed: false, hasColor: false }
    // A resumed transcript that cannot be read: leave it as it was.
    if (!facts) return result

    if (!facts.hasColor) runLater($, 'color', DEFAULT_COLOR)

    const named = !!e.session_title?.trim() || !!result.sessionTitle || facts.isNamed
    const name = !named && facts.aiTitle ? slug(facts.aiTitle) : ''
    await setLabel($, {
      sessionId: e.session_id,
      transcriptPath: e.transcript_path,
      status: named || name ? 'done' : 'pending',
      colored: !facts.hasColor,
    })
    return name ? { ...result, sessionTitle: name } : result
  }).catch(($, e, next) => next(e))

  // Right after a reply: /rename to the AI title, which Claude Code writes
  // while the first reply runs (tried again a few times if it is late).
  on('classic.Stop', async ($, e, next) => {
    const result = await next(e)
    if (!e.agent_id) await nameAtTurnEnd($, e.session_id, e.transcript_path, NAME_TRIES).catch(noop)
    return result
  }).catch(($, e, next) => next(e))

  // The fallback: still unnamed at the next prompt, name it with that prompt.
  on('classic.UserPromptSubmit', async ($, e, next) => {
    const result = await next(e)
    const cur = await read($, label).catch(() => null)
    if (!cur || cur.sessionId !== e.session_id || cur.status !== 'pending') return result
    if (e.session_title?.trim() || result.sessionTitle) {
      await setLabel($, { ...cur, status: 'done' })
      return result
    }
    const facts = await readFacts($, e.transcript_path)
    if (facts?.isNamed) {
      await setLabel($, { ...cur, status: 'done' })
      return result
    }
    const name = facts?.aiTitle ? slug(facts.aiTitle) : ''
    if (!name) return result
    await setLabel($, { ...cur, status: 'done' })
    return { ...result, sessionTitle: name }
  }).catch(($, e, next) => next(e))
}
