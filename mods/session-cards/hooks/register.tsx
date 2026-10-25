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
  high: 'error', // the red of `bypass permissions on`, as the status bar draws it
  // xhigh and max are still frames of the /effort picker's animations, as the status bar holds them: xhigh's
  // autoAccept shimmer lit on its middle letter, max's rainbow starting at the bolt (red) and running on through the word.
  xhigh: 'autoAccept',
  max: '#eb5f57',
}
/** The status bar's model icon (md-robot), drawn before an agent's model in the model's colour. */
const ROBOT = '\u{F06A9}'
const SHIMMER = '#d0b4ff'
const RAINBOW = ['#f58b57', '#fac35f', '#91c882'] // orange, yellow, green: the steps after the bolt's red

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

/** An effort level as coloured runs: xhigh and max letter by letter, as the /effort picker draws them, held still. */
export function effortLetters(level: string): { text: string; color: string }[] {
  const letters = [...level]

  if (level === 'xhigh') {
    return letters.map((text, i) => ({ text, color: i === Math.floor(letters.length / 2) ? SHIMMER : 'autoAccept' }))
  }

  if (level === 'max') {
    return letters.map((text, i) => ({ text, color: RAINBOW[i % RAINBOW.length] as string }))
  }

  return [{ text: level, color: effortColour(level) ?? 'text' }]
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

/** The ids of the background shells that run now: the turn-end lines read it, so they redraw as one starts or ends. */
const runningShells = atom({ plugin: 'session-cards', key: 'runningShells' } as const, [] as string[])

/** Bumped every minute so the hint line reads the overflow file again. */
const overflowTick = atom({ plugin: 'session-cards', key: 'overflowTick' } as const, 0)

const SEPARATOR = ' │ '

/** Screen column where the engine starts the mode label, or the hint when there is none (measured on 2.1.310). */
const HINT_X = 2

/**
 * Cells of the mode label the engine draws in front of the hint on the same row, the widest one with its
 * separator (`⏵⏵ bypass permissions on · `), for a record from an older statusbar.py that does not say the
 * label's width. The hint text leaves the label out and the mode is not on the event, so it is reserved in front
 * of every hint but the default mode's own (`? for shortcuts`), which has no label: a background shell's hint is
 * `1 shell` in any mode.
 */
const MODE_LABEL = 27

/**
 * The permissions shield (md-shield_key_outline) that starts the hint behind a mode label. The engine draws the
 * label's ` · ` itself, outside this hook, so the shield follows the dot: `⏵⏵ bypass permissions on · <shield> (…)`.
 * The mode is not on the event, so it is dim like the hint rather than in the mode's colour.
 */
const SHIELD = '\u{F0BC5}'

/**
 * The hints the engine draws as plain text, which the hook may rewrite. Any other hint may hold live pills (`1 shell`,
 * monitors, agents) that the user clicks to see what runs; a rewritten hint or a tree of the hook's own turns them
 * into dead text, so beside those the engine keeps its line and the pieces go in its dim `tail`.
 */
const isPlainHint = (hint: string) => hint.startsWith('? for shortcuts') || hint.startsWith('(shift+tab to cycle)')

/** The background-tasks pill as the engine labels it (2.1.310): shells and monitors, agents, or a count of tasks. */
const PILL = /^(?:\d+ shells?(?:, \d+ monitors?)?|\d+ (?:monitors?|local agents?|MCP tasks?|background tasks?))$/

/** The PR badge as the hint line reads it: `PR #12`, or GitLab's `MR !12`. */
const PR_BADGE = /^([PM]R) ([#!])(\d+)$/

/** The PR badge's mark in the status bar's meter yellow, its number in the bar's white. */
const BADGE_MARK = '#EBC83C'
const BADGE_NUMBER = '#FFFFFF'

/** One part of a hint the hook draws: dim text, the PR badge, or the background-tasks pill. */
export type HintPiece =
  | { kind: 'text'; text: string }
  | { kind: 'badge'; word: string; mark: string; number: string }
  | { kind: 'pill'; text: string }

/** The hint's ` · `-separated parts as pieces, with the separators in the text pieces around them. */
export function hintPieces(hint: string): HintPiece[] {
  const pieces: HintPiece[] = []
  const text = (more: string) => {
    const last = pieces[pieces.length - 1]

    if (last?.kind === 'text') {
      last.text += more
    } else if (more !== '') {
      pieces.push({ kind: 'text', text: more })
    }
  }

  hint.split(' · ').forEach((part, i) => {
    text(i === 0 ? '' : ' · ')
    const badge = PR_BADGE.exec(part)

    if (PILL.test(part)) {
      pieces.push({ kind: 'pill', text: part })
    } else if (badge !== null) {
      pieces.push({ kind: 'badge', word: badge[1], mark: badge[2], number: badge[3] })
    } else {
      text(part)
    }
  })

  return pieces
}

function isSpan(value: unknown): value is Span {
  return typeof field(value, 'text') === 'string'
}

/** A moved piece of the status bar: `col` is a screen column, `rank` its drop priority (higher drops first). */
type Placed = { col: number; spans: Span[] }
type Ranked = { rank: number; spans: Span[] }

/**
 * The status bar's overflow file: `pieces` is the flat list every statusbar.py writes; a newer one also says
 * where each piece goes (`under` its bar, moved `bars`, the `right` group) and the mode label's width.
 */
export type Overflow = {
  pieces: Span[][]
  label?: number
  under?: (Placed & Ranked)[]
  bars?: (Placed & Ranked)[]
  right?: Ranked[]
  /** The address a PR number goes after (`https://github.com/<owner>/<name>/pull/`), in a GitHub repo. */
  pull?: string
}

const spansOf = (value: unknown): Span[] | null => {
  const spans = field(value, 'spans')
  return Array.isArray(spans) ? spans.filter(isSpan) : null
}

const numberOf = (value: unknown, key: string): number | null => {
  const n = field(value, key)
  return typeof n === 'number' && Number.isFinite(n) ? n : null
}

/** The entries of `key` that have a span list and every number in `numbers`, or undefined when there is no list. */
function entries<T>(parsed: unknown, key: string, numbers: string[]): T[] | undefined {
  const list = field(parsed, key)

  if (!Array.isArray(list)) {
    return undefined
  }

  return list.flatMap(item => {
    const spans = spansOf(item)
    const values = numbers.map(n => numberOf(item, n))
    return spans === null || values.includes(null) ? [] : [{ ...Object.fromEntries(numbers.map((n, i) => [n, values[i]])), spans } as T]
  })
}

/** The status bar's overflow file, or null when it is missing, unreadable or not the shape. */
function parseOverflow(text: string): Overflow | null {
  let parsed: unknown

  try {
    parsed = JSON.parse(text)
  } catch {
    return null
  }

  const pieces = field(parsed, 'pieces')
  const pull = field(parsed, 'pull')

  if (!Array.isArray(pieces)) {
    return null
  }

  return {
    pieces: pieces.map(piece => (Array.isArray(piece) ? piece.filter(isSpan) : [])),
    label: numberOf(parsed, 'label') ?? undefined,
    under: entries<Placed & Ranked>(parsed, 'under', ['col', 'rank']),
    bars: entries<Placed & Ranked>(parsed, 'bars', ['col', 'rank']),
    right: entries<Ranked>(parsed, 'right', ['rank']),
    pull: typeof pull === 'string' && pull.startsWith('https://') ? pull : undefined,
  }
}

// By code point: a Nerd Font icon past U+FFFF (the clock, the robot) is two UTF-16 units but one cell.
const widthOf = (piece: Span[]): number => piece.reduce((sum, span) => sum + [...span.text].length, 0)

const separatorSpan: Span = { text: SEPARATOR, colour: 'text', bold: false }

/** The pieces joined by the separator, as one run of spans. */
const joined = (pieces: Span[][]): Span[] => pieces.flatMap((piece, i) => (i === 0 ? piece : [separatorSpan, ...piece]))

/**
 * Where the second row's pieces go, as offsets inside the hook's tree, which starts after the mode label at screen
 * column `HINT_X + record.label` and opens with `hintCells` of hint and two spaces. Reset times go under their bar
 * (one the hint reaches is not drawn); moved bars go where the record lines them up, or join the right group when
 * one would start inside the hint or run past the margin; the right group ends at the margin of `columns - 4`, or,
 * when a piece there blocks it and it holds no moved bar, in the rightmost gap that fits, a separator before a piece.
 * While the right group reaches the hint or a piece before it, the highest rank among those pieces drops, so a
 * moved bar outranks a reset time it collides with. Null when nothing is left to draw.
 */
export function placeRow(record: Overflow, hintCells: number, columns: number): Placed[] | null {
  const origin = HINT_X + (record.label ?? 0)
  const end = columns - 4 - origin
  const left = hintCells + 2
  const endOf = (piece: Placed) => piece.col + widthOf(piece.spans)
  const inRow = (piece: Placed) => piece.col >= left && endOf(piece) <= end
  let fixed: (Placed & Ranked)[] = []

  for (const piece of record.under ?? []) {
    const at = { ...piece, col: piece.col - origin }
    const before = fixed[fixed.length - 1]

    if (inRow(at) && (!before || at.col >= endOf(before))) {
      fixed.push(at)
    }
  }

  const bars = (record.bars ?? []).map(bar => ({ ...bar, col: bar.col - origin }))
  const clear = (bar: Placed) => fixed.every(piece => endOf(piece) <= bar.col || endOf(bar) <= piece.col)
  let right: Ranked[] = record.right ?? []
  const barsLinedUp = bars.every(bar => inRow(bar) && clear(bar))

  if (barsLinedUp) {
    fixed = [...fixed, ...bars]
  } else {
    right = [...bars.map(({ rank, spans }) => ({ rank, spans })), ...right]
  }

  let group: Placed | null = null

  while (right.length > 0) {
    const spans = joined(right.map(piece => piece.spans))
    const width = widthOf(spans)
    const start = end - width
    // Two spaces between a piece before and the right group, as after the hint.
    const blocking = fixed.filter(piece => endOf(piece) + 2 > start)

    if (start >= left && blocking.length === 0) {
      group = { col: start, spans }
      break
    }

    // With the margin taken, a group of no moved bar (which would leave the meters' order) goes in the rightmost
    // free gap, ending a separator before the piece after it.
    const fits = (col: number) =>
      col >= left && fixed.every(piece => endOf(piece) + 2 <= col || col + width + SEPARATOR.length <= piece.col)
    const gap = barsLinedUp ? Math.max(...fixed.map(piece => piece.col - SEPARATOR.length - width).filter(fits)) : -Infinity

    if (gap > -Infinity) {
      group = { col: gap, spans }
      break
    }

    const contenders: Ranked[] = start < left ? right : [...right, ...blocking]
    const worst = contenders.reduce((a, b) => (b.rank > a.rank ? b : a))
    right = right.filter(piece => piece !== worst)
    fixed = fixed.filter(piece => piece !== worst)
  }

  const placed: Placed[] = []

  for (const piece of [...fixed, ...(group ? [group] : [])].sort((a, b) => a.col - b.col)) {
    const before = placed[placed.length - 1]

    // A piece a separator after the one before it is drawn with the separator, as on the top row.
    if (before && endOf(before) + SEPARATOR.length === piece.col) {
      before.spans = [...before.spans, separatorSpan, ...piece.spans]
    } else {
      placed.push({ col: piece.col, spans: piece.spans })
    }
  }

  return placed.length === 0 ? null : placed
}

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
      const all = [...value, { seq, durationMs: e.durationMs, endedAt: await $.clock.now() }]
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
  // Event hooks publish the set to `runningShells`, which the turn-end lines
  // read, so they redraw as shells start and end. A ui.render hook may not
  // write $.state but may write the module, so the task-notification row can
  // end one too; the lines count from here and show it on their next redraw.
  const shells = new Set<string>()
  const all = () => [...shells]

  // A call that went to the background (run_in_background, ctrl+b, a timeout) answers with the task's id.
  const backgrounded = (answer: { result?: unknown }) => {
    const id = answer.result === undefined ? undefined : (answer.result as { backgroundTaskId?: string }).backgroundTaskId

    if (id !== undefined && id !== '') {
      shells.add(id)
    }

    return id !== undefined && id !== ''
  }

  on('tool.call', { tool: 'Bash' }, async ($, e, next) => {
    const answer = await next(e)

    if (backgrounded(answer)) {
      await update($, runningShells, all)
    }

    return answer
  })

  on('tool.call', { tool: 'PowerShell' }, async ($, e, next) => {
    const answer = await next(e)

    if (backgrounded(answer)) {
      await update($, runningShells, all)
    }

    return answer
  })

  on('tool.call', { tool: 'TaskStop' }, async ($, e, next) => {
    const answer = await next(e)
    const id = answer.result === undefined ? undefined : (answer.result as { task_id?: string }).task_id

    if (id !== undefined && shells.delete(id)) {
      await update($, runningShells, all)
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

    // A background agent still ran when the turn ended: the engine's line says so
    // (`Waiting for 1 background agent to finish`), and only it knows when one ends.
    const waiting = (r: TurnRecord) => [...agents.values()].some(a => a.background && a.finishedAt === undefined && a.startedAt <= r.endedAt)

    if (record === undefined || waiting(record)) {
      return next(e)
    }

    // As the engine's line does, every turn-end line says while a background shell runs.
    // Reading the state redraws the line when a shell starts or ends; the count is the module's.
    await read($, runningShells)
    const running = shells.size

    const line = turnLine(record)
    const { Box, Text } = $.ui.resolve(e)

    // The engine's line keeps a blank line above it; the row it replaces is that whole line.
    return (
      <Box flexDirection="row" width="100%" marginTop={1}>
        <Box minWidth={2}>
          <Text color="claude">✻</Text>
        </Box>
        <Text dimColor>{`${word} for`}</Text>
        <Text>{' '}</Text>
        <Text bold color="text">
          {line.duration}
        </Text>
        <Text color="success">{` · done ${line.done}`}</Text>
        {running > 0 && <Text dimColor>{` · ${running} ${running === 1 ? 'shell' : 'shells'} still running`}</Text>}
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

    // A finished background task reaches the session as a notification naming it.
    const ended = e.origin.kind === 'task-notification' ? /<task-id>([^<]+)<\/task-id>/.exec(e.text)?.[1] : undefined

    if (ended !== undefined && shells.delete(ended)) {
      await update($, runningShells, all)
    }

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
    // A slash command's row (the one /compact keeps reaches here; a typed one is the engine's echo) is a card in the
    // permission blue of the command output cards. A prompt that starts with a path (`/tmp is full`) names no command.
    const name = /^\/(\S+)/.exec(text)?.[1]

    if (name !== undefined && (await $.command.list()).some(c => c.name === name)) {
      return (
        <Box borderStyle="round" borderColor="permission" paddingX={1}>
          <Text color="permission" bold>
            {`  You ran ${text}`}
          </Text>
        </Box>
      )
    }

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

    const header = `  You prompted${at === null ? '' : ` · ${clock(at)}`}`

    return (
      <Box flexDirection="column" borderStyle="round" borderColor="claude" paddingX={1}>
        <Text color="claude" bold>
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
        (row.model === undefined ? 0 : [...` · ${ROBOT} ${row.model}`].length) +
        (row.effort === undefined ? 0 : `  ${row.effort}`.length) +
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
          {row.model !== undefined && <Text color={modelColour(row.model) ?? 'text'}>{`${ROBOT} `}</Text>}
          {row.model !== undefined && <Text color={modelColour(row.model) ?? 'text'} {...modelStyle}>
              {row.model}
            </Text>}
          {/* The bolt between model and effort takes the level's colour, as on the status bar. */}
          {row.effort !== undefined && <Text color={effortColour(row.effort) ?? 'text'}>{'  '}</Text>}
          {row.effort !== undefined && effortLetters(row.effort).map(run => <Text color={run.color}>{run.text}</Text>)}
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

    const { hint } = e.props
    const defaultHint = hint.startsWith('? for shortcuts')
    const plain = isPlainHint(hint)
    const withShield = (label: number) => (label === 0 || !plain ? hint : `${SHIELD} ${hint}`)
    const pass = (shown: string) => next(shown === hint ? e : { ...e, props: { ...e.props, hint: shown } })

    // statusbar.py writes under Python's expanduser("~"), which on Windows is USERPROFILE.
    const home = (await $.env.get('USERPROFILE')) || (await $.env.get('HOME'))
    const guess = withShield(defaultHint ? 0 : MODE_LABEL)

    if (!home) {
      return pass(guess)
    }

    let record: Overflow | null

    try {
      record = parseOverflow(await $.fs.read(`${home}/.claude/statusbar-overflow/${await $.session.id()}.json`))
    } catch {
      return pass(guess)
    }

    if (record === null) {
      return pass(guess)
    }

    const columns = e.viewport?.columns ?? 80
    const placedRecord = record.under !== undefined || record.bars !== undefined || record.right !== undefined
    // The record's label is the transcript's mode; the default mode's own hint never has one in front.
    const label = defaultHint ? 0 : placedRecord ? (record.label ?? MODE_LABEL) : MODE_LABEL
    const shown = withShield(label)
    const cells = [...shown].length

    const overflow: Overflow = record // narrowed, for the closures below
    const withTail = () => {
      // The engine draws its own ` · ` before the tail and squeezes its spaces, so the pieces cannot line up under
      // their bars: the flat list packs left, the ` · ` counted as the hint's two spaces and one more cell. The tail is
      // one dim grey, so a meter's full and empty blocks look alike: they are left out and its percentage stays.
      const pieces = overflow.pieces.map(piece => piece.map(span => ({ ...span, text: span.text.replace(/█+/g, '') })))
      const fits = fitPieces(pieces, label + cells + 1, columns - 4)
      const tail = joined(fits)
        .map(span => span.text)
        .join('')
        .replace(/ {2,}/g, ' ')
      return fits.length === 0 ? next(e) : next({ ...e, props: { ...e.props, tail } })
    }

    // Idle, a hint of the pill and the PR badge alone is drawn here like a plain one, the pill as the hook's own
    // Button. While a turn runs the engine's pill stays: a plugin's /tasks waits for the turn's end, the engine's opens
    // at once. Any other part may be live too (a cloud session, the bridge), so such a hint keeps the engine's line.
    const parts = hintPieces(shown)
    const hasPill = parts.some(part => part.kind === 'pill')
    const ownPill =
      !e.props.isWorking && hasPill && parts.every(part => part.kind !== 'text' || /^(?: · )+$/.test(part.text))

    if (!plain && !ownPill) {
      return withTail()
    }

    let placed: Placed[] | null

    if (placedRecord) {
      placed = placeRow({ ...record, label }, cells, columns)
    } else {
      // An older statusbar.py: its pieces packed left after the hint, the label's cells reserved in front.
      const fits = fitPieces(record.pieces, label + cells, columns - 4)
      placed = fits.length === 0 ? null : [{ col: cells + 2, spans: joined(fits) }]
    }

    if (placed === null) {
      return plain ? pass(shown) : withTail()
    }

    const { Box, Text, Link, Button } = $.ui.resolve(e)
    let at = cells

    const rest = placed.map(piece => {
      const gap = piece.col - at
      at = piece.col + widthOf(piece.spans)
      return [
        <Text>{' '.repeat(gap)}</Text>,
        ...piece.spans.map(span => (
          <Text color={span.colour ?? undefined} bold={span.bold === true} underline={span.underline === true}>
            {span.text}
          </Text>
        )),
      ]
    })

    // The hint dim, but the PR badge: its mark yellow and its number white and underlined, a link to the PR when the
    // status bar knows the repo (the engine's badge is one, and a rewritten line would lose it).
    const run = (part: Exclude<HintPiece, { kind: 'pill' }>) => {
      if (part.kind === 'text') {
        return <Text dimColor>{part.text}</Text>
      }

      const number = [
        <Text color={BADGE_MARK}>{part.mark}</Text>,
        <Text color={BADGE_NUMBER} underline>
          {part.number}
        </Text>,
      ]
      return [
        <Text dimColor>{`${part.word} `}</Text>,
        overflow.pull !== undefined && part.mark === '#' ? <Link href={`${overflow.pull}${part.number}`}>{number}</Link> : number,
      ]
    }

    if (!hasPill) {
      // One Text, so a row narrower than the estimate cuts its end instead of wrapping onto a second line.
      return (
        <Text wrap="truncate-end">
          {parts.map(part => (part.kind === 'pill' ? null : run(part)))}
          {rest}
        </Text>
      )
    }

    // The pill inverted at rest, as the engine's is under the pointer; a press opens the background tasks list.
    return (
      <Box flexDirection="row">
        {parts.map(part =>
          part.kind === 'pill' ? (
            <Button key="tasks" plain onPress={() => void $.command.run({ command: 'tasks' })}>
              <Text color="background" inverse>
                {part.text}
              </Text>
            </Button>
          ) : (
            <Text>{run(part)}</Text>
          ),
        )}
        <Text wrap="truncate-end">{rest}</Text>
      </Box>
    )
  })
}
