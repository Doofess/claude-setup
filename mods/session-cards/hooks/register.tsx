import { atom, read, update } from 'claude-code'
import type { Register } from 'claude-code'

import type { TurnRecord } from '../types'
import { neon, NEON_MS } from './neon'

export type { TurnRecord }


/** Claude Code's own wrapper lines around a pasted block: `<pasted_content …>` and `</pasted_content …>`. */
const WRAPPER = /^[ \t]*<\/?pasted_content\b[^>\n]*>[ \t]*(?:\r?\n|$)/gm

/** The prompt as typed, with the paste wrapper lines taken out. */
export function promptText(text: string): string {
  return text.replace(WRAPPER, '')
}

/** A prompt that runs a slash command: `/name` first, then a space or the end. A path such as `/c/dev …` is not one. */
export function isSlashCommand(text: string): boolean {
  return /^\/[A-Za-z0-9:_-]+(\s|$)/.test(promptText(text).trimStart())
}

/** `HH:MM`, 24-hour, in the machine's local time. */
export function clock(ms: number): string {
  const at = new Date(ms)
  const two = (n: number) => String(n).padStart(2, '0')

  return `${two(at.getHours())}:${two(at.getMinutes())}`
}

type Described = { icon: string; verb: [string, string]; detail: string }
type RowState = 'running' | 'done' | 'failed' | 'stopped'

const asString = (value: unknown): string => (typeof value === 'string' ? value : '')

const field = (input: unknown, key: string): unknown =>
  typeof input === 'object' && input !== null ? (input as Record<string, unknown>)[key] : undefined

/** Forward slashes, relative to `cwd` when under it, else as given. */
function relative(path: string, cwd: string): string {
  const slashed = path.replace(/\\/g, '/')
  const root = cwd.replace(/\\/g, '/').replace(/\/+$/, '')
  const drive = /^[a-z]:/i.test(slashed)
  const same = (a: string, b: string) => (drive ? a.toLowerCase() === b.toLowerCase() : a === b)

  if (root !== '' && slashed.length > root.length && slashed[root.length] === '/' && same(slashed.slice(0, root.length), root)) {
    return slashed.slice(root.length + 1)
  }

  return slashed
}

/** The cut to `width` cells: the end becomes `…` when anything was dropped. */
function cut(text: string, width: number): string {
  if (text.length <= width) {
    return text
  }

  return width <= 0 ? '' : `${text.slice(0, width - 1)}…`
}

const firstLine = (text: string): string => (text.split(/\r?\n/)[0] ?? '').trim()

/** An icon, a verb pair (present, past) and a detail for one tool call, in plain words. */
export function describeTool(tool: string, input: unknown, cwd: string): Described {
  const path = (value: unknown) => relative(asString(value), cwd)

  switch (tool) {
    case 'Bash':
    case 'PowerShell': {
      const description = firstLine(asString(field(input, 'description')))

      return { icon: '', verb: ['Running', 'Ran'], detail: description !== '' ? description : firstLine(asString(field(input, 'command'))) }
    }
    case 'Edit':
    case 'MultiEdit':
      return { icon: '', verb: ['Editing', 'Edited'], detail: path(field(input, 'file_path')) }
    case 'Write':
      return { icon: '', verb: ['Writing', 'Wrote'], detail: path(field(input, 'file_path')) }
    case 'NotebookEdit':
      return { icon: '', verb: ['Editing', 'Edited'], detail: path(field(input, 'notebook_path')) }
    case 'Read':
      return { icon: '', verb: ['Reading', 'Read'], detail: path(field(input, 'file_path')) }
    case 'Glob':
    case 'Grep': {
      const where = path(field(input, 'path'))

      return { icon: '', verb: ['Searching', 'Searched'], detail: `${asString(field(input, 'pattern'))}${where === '' ? '' : ` in ${where}`}` }
    }
    case 'Skill':
      return { icon: '', verb: ['Using skill', 'Used skill'], detail: asString(field(input, 'skill')) }
    case 'AskUserQuestion': {
      const questions = field(input, 'questions')

      return { icon: '', verb: ['Asking you', 'Asked you'], detail: Array.isArray(questions) ? asString(field(questions[0], 'question')) : '' }
    }
    case 'WebFetch':
      return { icon: '', verb: ['Fetching', 'Fetched'], detail: asString(field(input, 'url')) }
    case 'WebSearch':
      return { icon: '', verb: ['Searching', 'Searched'], detail: asString(field(input, 'query')) }
  }

  if (tool.startsWith('mcp__')) {
    const split = tool.indexOf('__', 5)
    const detail = split < 0 ? tool.slice(5) : `${tool.slice(5, split)} ${tool.slice(split + 2)}`

    return { icon: '', verb: ['Calling', 'Called'], detail }
  }

  const values = typeof input === 'object' && input !== null ? Object.values(input) : []
  const first = values.find((value): value is string => typeof value === 'string' && value !== '' && value.length < 60)

  return { icon: '', verb: ['Using', 'Used'], detail: first === undefined ? tool : `${tool} ${first}` }
}

const MARK = { running: '', done: '', failed: ' ✗', stopped: ' (stopped)' } as const

/** The row as plain text: `<icon> <Verb> <detail>` plus the mark, cut to `width`. */
export function rowText(d: Described, state: RowState, width: number): string {
  const verb = state === 'running' ? d.verb[0] : d.verb[1]

  return cut(`${d.icon} ${verb} ${d.detail}${MARK[state]}`, width)
}

const FAMILIES = ['opus', 'sonnet', 'haiku', 'fable', 'mythos'] as const
const FAMILY_COLOURS: Record<(typeof FAMILIES)[number], string> = {
  opus: 'claude',
  sonnet: 'blue',
  haiku: 'cyan',
  fable: 'yellowBright',
  mythos: 'greenBright',
}
const EFFORT_COLOURS: Record<string, string> = {
  low: 'green',
  medium: 'yellow',
  high: 'red',
  xhigh: 'magentaBright',
  max: 'whiteBright',
}

const familyOf = (model: string) => FAMILIES.find(family => model.toLowerCase().includes(family))

/** The colour name for a model name or id (as the status bar colours it), undefined when unknown. */
export function modelColour(model: string): string | undefined {
  const family = familyOf(model)

  return family === undefined ? undefined : FAMILY_COLOURS[family]
}

/** The colour name for an effort level, undefined when unknown. */
export function effortColour(level: string): string | undefined {
  return EFFORT_COLOURS[level]
}

/** The family capitalised (`Sonnet`), or the id as given when the family is unknown. */
function modelName(model: string): string {
  const family = familyOf(model)

  return family === undefined ? model : family.charAt(0).toUpperCase() + family.slice(1)
}

/** `0s`, `48s`, `1m 0s`, `12m 5s`, `1h 2m`. */
export function fmtElapsed(ms: number): string {
  const seconds = Math.max(0, Math.floor(ms / 1000))

  if (seconds < 60) {
    return `${seconds}s`
  }

  const minutes = Math.floor(seconds / 60)

  return minutes < 60 ? `${minutes}m ${seconds % 60}s` : `${Math.floor(minutes / 60)}h ${minutes % 60}m`
}

/** `950`, `72k`, `1.2M`, rounded as the status bar does. */
export function fmtTokens(n: number): string {
  if (n < 1000) {
    return String(n)
  }

  if (Math.floor(n / 1000 + 0.5) < 1000) {
    return `${Math.floor(n / 1000 + 0.5)}k`
  }

  return `${(n / 1_000_000).toFixed(1).replace(/\.0$/, '')}M`
}

/** What the mod knows of one subagent. */
export type AgentRecord = {
  type: string
  description: string
  model?: string
  effort?: string
  background: boolean
  startedAt: number
  finishedAt?: number
  tokens: number
  action?: string
}

/** The words of an agent row: `finishedAt` set means finished. */
export function agentRow(a: AgentRecord, now: number) {
  const finished = a.finishedAt !== undefined

  return {
    verb: finished ? 'Ran' : 'Running',
    type: a.type,
    model: a.model === undefined ? undefined : modelName(a.model),
    effort: a.effort,
    action: finished ? (a.action === 'remote' ? 'remote' : 'done') : a.action ?? a.description,
    elapsed: fmtElapsed((a.finishedAt ?? now) - a.startedAt),
    tokens: fmtTokens(a.tokens),
  }
}

/** The words of a turn-end line: the duration and the time it ended as `12:34 PM`. */
export function turnLine(r: TurnRecord): { duration: string; done: string } {
  return {
    duration: fmtElapsed(r.durationMs),
    // Newer ICU puts a narrow no-break space before PM; the engine's line has a plain one.
    done: new Date(r.endedAt).toLocaleTimeString('en-US', { hour: 'numeric', minute: '2-digit' }).replace(/ /g, ' '),
  }
}

/** Bumped on every change to an agent record and once a second while one runs. */
const agentTick = atom({ plugin: 'session-cards', key: 'agentTick' } as const, 0)

/** One run of the status bar's overflow: `colour` is a colour name, a hex string, or null for the default. */
type Span = { text: string; colour: string | null; bold: boolean; underline?: boolean }

/** Bumped every NEON_MS while a Fable subagent runs: the frame of chalk-animation's neon on its row. */
const neonTick = atom({ plugin: 'session-cards', key: 'neonTick' } as const, 0)

/** Bumped every minute so the hint line reads the overflow file again. */
const overflowTick = atom({ plugin: 'session-cards', key: 'overflowTick' } as const, 0)

const SEPARATOR = ' │ '

/**
 * Cells of the mode label the engine draws in front of the hint on the same row, the widest one with its
 * separator (`⏵⏵ bypass permissions on · `). The hint text leaves the label out and the mode is not on the event,
 * so it is reserved in front of every hint but the default mode's own (`? for shortcuts`), which has no label:
 * a background shell's hint is `1 shell` in any mode.
 */
const MODE_LABEL = 27

function isSpan(value: unknown): value is Span {
  return typeof field(value, 'text') === 'string'
}

/** The pieces in the status bar's overflow file, or null when it is missing, unreadable or not the shape. */
function parseOverflow(text: string): Span[][] | null {
  let parsed: unknown

  try {
    parsed = JSON.parse(text)
  } catch {
    return null
  }

  const pieces = field(parsed, 'pieces')

  if (!Array.isArray(pieces)) {
    return null
  }

  return pieces.map(piece => (Array.isArray(piece) ? piece.filter(isSpan) : []))
}

// By code point: a Nerd Font icon past U+FFFF (the clock, the robot) is two UTF-16 units but one cell.
const widthOf = (piece: Span[]): number => piece.reduce((sum, span) => sum + [...span.text].length, 0)

/** The leading pieces whose line (`hint`, two spaces, the pieces joined) fits in `room` cells. */
export function fitPieces(pieces: Span[][], hintWidth: number, room: number): Span[][] {
  const fits: Span[][] = []
  let used = hintWidth + 2

  for (const piece of pieces) {
    const next = used + (fits.length === 0 ? 0 : SEPARATOR.length) + widthOf(piece)

    if (next > room) {
      break
    }

    fits.push(piece)
    used = next
  }

  return fits
}

export const register: Register = on => {
  on('session.start', async ($, e, next) => {
    // The status bar rewrites the overflow file about once a minute; the hint
    // line only redraws on its own events, so a tick makes it read the file again.
    $.clock.every(60_000, () => update($, overflowTick, n => n + 1))

    // Agent rows show elapsed time: redraw them each second while a subagent runs.
    $.clock.every(1000, () => {
      if ([...agents.values()].some(a => a.finishedAt === undefined)) {
        return update($, agentTick, n => n + 1)
      }
    })

    // A running Fable agent's row pulses (neon): one tick per frame.
    $.clock.every(NEON_MS, () => {
      if ([...agents.values()].some(a => a.finishedAt === undefined && familyOf(a.model ?? '') === 'fable')) {
        return update($, neonTick, n => n + 1)
      }
    })

    return next(e)
  })

  // What the mod knows of each subagent, by the Agent call's tool_use_id, and
  // the subagent id its loop's events carry, mapped back to that tool_use_id.
  // A hot reload empties both; rows are then the unknown kind until the next spawn.
  const agents = new Map<string, AgentRecord>()
  const byAgentId = new Map<string, string>()

  const known = (agentId: string | undefined) => {
    const toolUseId = agentId === undefined ? undefined : byAgentId.get(agentId)

    return toolUseId === undefined ? undefined : agents.get(toolUseId)
  }

  // The Agent call wraps the agent's whole run: it returns at completion, or at
  // once when the agent was backgrounded (from the start or by ctrl+b mid-run).
  on('tool.call', { tool: 'Agent' }, async ($, e, next) => {
    const answer = await next(e)
    const record = agents.get(e.tool_use_id)
    const status = answer.result === undefined ? undefined : (answer.result as { status?: string }).status

    if (record !== undefined && status !== undefined) {
      const now = await $.clock.now()

      if (status === 'async_launched' || status === 'remote_launched') {
        record.background = true
      }

      // A remote agent has no local loop: no event will ever end its row.
      if (status === 'remote_launched') {
        record.action = 'remote'
        record.finishedAt ??= now
      }

      if (status === 'completed') {
        record.finishedAt ??= now
      }

      await update($, agentTick, n => n + 1)
    }

    return answer
  })

  on('agent.spawn', async ($, e, next) => {
    const result = await next(e)
    const now = await $.clock.now()

    agents.set(e.tool_use_id, {
      type: e.subagentType,
      description: e.description,
      model: result.model,
      background: e.background,
      startedAt: now,
      tokens: 0,
    })

    if (result.agentId !== undefined) {
      byAgentId.set(result.agentId, e.tool_use_id)
    }

    await update($, agentTick, n => n + 1)

    return result
  })

  on('turn.step', async function* ($, e, next) {
    const record = known(e.agentId)

    if (record !== undefined && e.effort !== undefined) {
      record.effort = String(e.effort)
      await update($, agentTick, n => n + 1)
    }

    const result = yield* next(e)

    if (record !== undefined && result.usage !== null) {
      const u = result.usage
      // The latest step's counts: each call reads the whole context again, so a sum would count it once per step.
      record.tokens = u.input_tokens + u.output_tokens + u.cache_read_input_tokens + u.cache_creation_input_tokens
      await update($, agentTick, n => n + 1)
    }

    // A subagent runs nested inside this mod's own tool.call frame for the Agent
    // call, so its tool.call never reaches a hook: the step's tool uses say what it does.
    const last = record === undefined ? undefined : result.toolUses.at(-1)

    if (record !== undefined && last !== undefined) {
      const d = describeTool(last.name, last.input as Record<string, unknown>, await $.session.cwd())
      record.action = `${d.verb[0]} ${d.detail}`
      await update($, agentTick, n => n + 1)
    }

    return result
  })

  on('turn.complete', async ($, e, next) => {
    // A subagent's turn is not the main loop's: no turn-end line, so no record.
    if (e.agentId === undefined) {
      const key = { plugin: 'session-cards', key: 'turns' } as const
      const { value = [] } = await $.state.get(key)
      const seq = (value.at(-1)?.seq ?? -1) + 1
      const all = [...value, { seq, durationMs: e.durationMs, endedAt: await $.clock.now(), shells: shells.size }]
      await $.state.set(key, all.slice(-TURNS_KEPT))
    }

    const record = known(e.agentId)

    if (record !== undefined) {
      record.finishedAt = await $.clock.now()
      await update($, agentTick, n => n + 1)
    }

    return next(e)
  })

  // Background shells that run now, by the id the Bash/PowerShell result gave.
  // A ui.render hook may not write $.state but may write the module, so the
  // task-notification row can end one. That row can come after the turn ended
  // (a shell that finished during the final answer), so the count is only ever
  // too high: a turn that ended with one counted keeps the engine's line.
  const shells = new Set<string>()

  // A call that went to the background (run_in_background, ctrl+b, a timeout) answers with the task's id.
  const backgrounded = <T extends { result?: unknown }>(answer: T): T => {
    const id = answer.result === undefined ? undefined : (answer.result as { backgroundTaskId?: string }).backgroundTaskId

    if (id !== undefined && id !== '') {
      shells.add(id)
    }

    return answer
  }

  on('tool.call', { tool: 'Bash' }, async ($, e, next) => backgrounded(await next(e)))
  on('tool.call', { tool: 'PowerShell' }, async ($, e, next) => backgrounded(await next(e)))

  on('tool.call', { tool: 'TaskStop' }, async ($, e, next) => {
    const answer = await next(e)
    const id = answer.result === undefined ? undefined : (answer.result as { task_id?: string }).task_id

    if (id !== undefined) {
      shells.delete(id)
    }

    return answer
  })

  // Rows of the turn-end line pair with `turns` the way prompts pair with their times:
  // `claimedTurns` pins a row (e.requestId) to its record's `seq`, so each row keeps
  // its own record on every redraw, and as the cap drops the oldest.
  const TURNS_KEPT = 200
  const claimedTurns = new Map<string, number>()

  on('ui.render', { component: 'TurnDuration' }, async ($, e, next) => {
    const { word, durationMs, isExpanded, waitingFor } = e.props

    if (e.surface !== 'terminal' || isExpanded === true || waitingFor !== undefined) {
      return next(e)
    }

    const { value = [] } = await $.state.get({ plugin: 'session-cards', key: 'turns' })
    let at = claimedTurns.get(e.requestId)

    if (at === undefined) {
      const used = new Set(claimedTurns.values())
      const found = value.find(r => r.durationMs === durationMs && !used.has(r.seq))

      if (found === undefined) {
        return next(e)
      }

      at = found.seq
      claimedTurns.set(e.requestId, at)
    }

    const record = value.find(r => r.seq === at)

    // A shell or a background agent still ran when the turn ended: the engine's line says
    // so (`Waiting for 1 background agent to finish`), and only it knows when they end.
    const waiting = (r: TurnRecord) =>
      r.shells > 0 || [...agents.values()].some(a => a.background && a.finishedAt === undefined && a.startedAt <= r.endedAt)

    if (record === undefined || waiting(record)) {
      return next(e)
    }

    const line = turnLine(record)
    const { Box, Text } = $.ui.resolve(e)

    return (
      <Box flexDirection="row" width="100%">
        <Box minWidth={2}>
          <Text color="claude">✻</Text>
        </Box>
        <Text dimColor>{`${word} for`}</Text>
        <Text>{' '}</Text>
        <Text bold color="text">
          {line.duration}
        </Text>
        <Text color="success">{` · done ${line.done}`}</Text>
      </Box>
    )
  })

  // A row's time is settled at its first draw and kept for every redraw. A
  // ui.render hook may not write $.state, so the claims live here, in the
  // module: `claimed` maps a row (e.requestId, the message id) to its time or
  // null, and `taken` counts the times each text has handed out, which is the
  // cursor into promptTimes[text]. So two identical prompts show their own
  // times, the earlier row the earlier time. A hot reload empties both; rows
  // are then claimed again in draw order, which is their order in the log.
  const claimed = new Map<string, number | null>()
  const taken = new Map<string, number>()

  on('prompt.submit', async ($, e, next) => {
    const now = await $.clock.now()
    const { value = {} } = await $.state.get({ plugin: 'session-cards', key: 'promptTimes' })
    await $.state.set({ plugin: 'session-cards', key: 'promptTimes' }, { ...value, [e.text]: [...(value[e.text] ?? []), now] })

    return next(e)
  })

  on('ui.render', { component: 'UserMessage' }, async ($, e, next) => {
    // The engine reports a finished background task as a notification row: its id ends the shell.
    const ended = e.props.origin.kind === 'task-notification' ? e.props.task?.id : undefined

    if (ended !== undefined) {
      shells.delete(ended)
    }

    if (e.surface !== 'terminal' || e.props.origin.kind !== 'composer') {
      return next(e)
    }

    const { Box, Text } = $.ui.resolve(e)
    const { text } = e.props
    let at = claimed.get(e.requestId)

    if (at === undefined) {
      const { value = {} } = await $.state.get({ plugin: 'session-cards', key: 'promptTimes' })
      const used = taken.get(text) ?? 0
      at = value[text]?.[used] ?? null
      claimed.set(e.requestId, at)

      if (at !== null) {
        taken.set(text, used + 1)
      }
    }

    // A slash command is a card of its own, in the permission violet.
    const command = isSlashCommand(text)
    const colour = command ? 'permission' : 'claude'
    const header = `  ${command ? 'You ran' : 'You prompted'}${at === null ? '' : ` · ${clock(at)}`}`

    return (
      <Box flexDirection="column" borderStyle="round" borderColor={colour} paddingX={1}>
        <Text color={colour} bold>
          {header}
        </Text>
        <Text>{promptText(text)}</Text>
      </Box>
    )
  })

  on('ui.render', { component: 'CommandOutput' }, async ($, e, next) => {
    if (e.surface !== 'terminal') {
      return next(e)
    }

    const inner = await next(e)

    // A row the engine drew empty (a Box with no children) stays empty.
    if (inner.type === 'Box' && !inner.children?.length) {
      return inner
    }

    const { Box, Text } = $.ui.resolve(e)
    const { command, args, isErrored } = e.props
    const colour = isErrored ? 'error' : 'permission'

    return (
      <Box flexDirection="column" borderStyle="round" borderColor={colour} paddingX={1}>
        <Text color={colour} bold>
          {`  /${command}${args === '' ? '' : ` ${args}`}`}
        </Text>
        {inner}
      </Box>
    )
  })

  on('ui.render', { component: 'ToolUse' }, async ($, e, next) => {
    const { tool, input, isRunning, isErrored, isInterrupted, isExpanded } = e.props

    // Expanded rows (ctrl+o, --verbose, an unfolded group) and tasks are the engine's.
    if (e.surface !== 'terminal' || isExpanded === true || tool === 'Task') {
      return next(e)
    }

    const { Box, Text } = $.ui.resolve(e)

    if (tool === 'Agent') {
      await read($, agentTick)

      const columns = e.viewport?.columns ?? 120
      const running = isRunning === true
      const record = agents.get(e.props.tool_use_id)

      // A spawn the mod never saw: the call's description and nothing else.
      if (record === undefined) {
        const type = asString(field(input, 'subagent_type')) || 'general-purpose'
        const head = ` ${running ? 'Running' : 'Ran'} ${type}  `

        return (
          <Box flexDirection="row">
            <Text color="text">{' '}</Text>
            <Text color="text" bold>
              {running ? 'Running' : 'Ran'}
            </Text>
            <Text color="text">{` ${type}  ${cut(asString(field(input, 'description')), columns - head.length)}`}</Text>
          </Box>
        )
      }

      const now = await $.clock.now()
      // Last resort: a foreground call whose row stopped running without the Agent
      // call's result reaching the mod is over all the same, and the time is kept.
      // A background call's row stops running at launch; its turn.complete ends it.
      if (!running && !record.background && record.finishedAt === undefined) {
        record.finishedAt = now
      }

      const row = agentRow(record, now)
      const pulsing = row.verb === 'Running' && familyOf(row.model ?? '') === 'fable'
      const frame = pulsing ? await read($, neonTick) : 0
      const modelStyle = pulsing ? neon(frame) : familyOf(row.model ?? '') === 'fable' ? { color: 'yellowBright', bold: true } : {}
      const mark = isInterrupted ? ' (stopped)' : isErrored ? ' ✗' : ''
      const tail = `   ${row.elapsed} · ${row.tokens}`
      const fixed =
        ` ${row.verb} ${row.type}`.length +
        (row.model === undefined ? 0 : ` · ${row.model}`.length) +
        (row.effort === undefined ? 0 : ` · ${row.effort}`.length) +
        2 +
        mark.length +
        tail.length

      return (
        <Box flexDirection="row">
          <Text color="text">{' '}</Text>
          <Text color="text" bold>
            {row.verb}
          </Text>
          <Text color="text">{` ${row.type}`}</Text>
          {row.model !== undefined && <Text color="text">{' · '}</Text>}
          {row.model !== undefined && <Text color={modelColour(row.model) ?? 'text'} {...modelStyle}>
              {row.model}
            </Text>}
          {row.effort !== undefined && <Text color="text">{' · '}</Text>}
          {row.effort !== undefined && <Text color={effortColour(row.effort) ?? 'text'}>{row.effort}</Text>}
          <Text color="text">{`  ${cut(row.action, columns - fixed)}`}</Text>
          {mark === ' ✗' && <Text color="error">{mark}</Text>}
          {mark === ' (stopped)' && <Text color="text">{mark}</Text>}
          <Text color="text">{tail}</Text>
        </Box>
      )
    }

    const d = describeTool(tool, input, await $.session.cwd())
    const state: RowState = isInterrupted ? 'stopped' : isErrored ? 'failed' : isRunning ? 'running' : 'done'
    const verb = state === 'running' ? d.verb[0] : d.verb[1]
    const mark = MARK[state]
    const room = (e.viewport?.columns ?? 120) - `${d.icon} ${verb} `.length - mark.length

    return (
      <Box flexDirection="row">
        <Text color="text">{`${d.icon} `}</Text>
        <Text color="text" bold>
          {verb}
        </Text>
        <Text color="text">{` ${cut(d.detail, room)}`}</Text>
        {state === 'failed' && <Text color="error">{mark}</Text>}
        {state === 'stopped' && <Text color="text">{mark}</Text>}
      </Box>
    )
  })

  on('ui.render', { component: 'PromptHint' }, async ($, e, next) => {
    if (e.surface !== 'terminal') {
      return next(e)
    }

    await read($, overflowTick)

    // statusbar.py writes under Python's expanduser("~"), which on Windows is USERPROFILE.
    const home = (await $.env.get('USERPROFILE')) || (await $.env.get('HOME'))

    if (!home) {
      return next(e)
    }

    let pieces: Span[][] | null

    try {
      pieces = parseOverflow(await $.fs.read(`${home}/.claude/statusbar-overflow/${await $.session.id()}.json`))
    } catch {
      return next(e)
    }

    const { hint } = e.props
    const label = hint.startsWith('? for shortcuts') ? 0 : MODE_LABEL
    const fits = pieces === null ? [] : fitPieces(pieces, label + [...hint].length, (e.viewport?.columns ?? 80) - 4)

    if (fits.length === 0) {
      return next(e)
    }

    const { Box, Text } = $.ui.resolve(e)

    // One Text, so a row narrower than the estimate cuts its end instead of wrapping onto a second line.
    return (
      <Text wrap="truncate-end">
        <Text dimColor>{hint}</Text>
        <Text>{'  '}</Text>
        {fits.map((piece, i) => [
          i > 0 && <Text color="text">{SEPARATOR}</Text>,
          ...piece.map(span => (
            <Text color={span.colour ?? undefined} bold={span.bold === true} underline={span.underline === true}>
              {span.text}
            </Text>
          )),
        ])}
      </Text>
    )
  })
}
