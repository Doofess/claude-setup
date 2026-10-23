import { atom, read, update } from 'claude-code'
import type { Register } from 'claude-code'


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

const firstLine = (text: string): string => text.split(/\r?\n/)[0].trim()

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

/** One run of the status bar's overflow: `colour` is a colour name, a hex string, or null for the default. */
type Span = { text: string; colour: string | null; bold: boolean }

/** Bumped every minute so the hint line reads the overflow file again. */
const overflowTick = atom({ plugin: 'session-cards', key: 'overflowTick' } as const, 0)

const SEPARATOR = ' │ '

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

const widthOf = (piece: Span[]): number => piece.reduce((sum, span) => sum + span.text.length, 0)

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

    return next(e)
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

    // Expanded rows (ctrl+o, --verbose, an unfolded group) and agents are the engine's.
    if (e.surface !== 'terminal' || isExpanded === true || tool === 'Agent' || tool === 'Task') {
      return next(e)
    }

    const { Box, Text } = $.ui.resolve(e)
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

    const home = (await $.env.get('HOME')) || (await $.env.get('USERPROFILE'))

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
    const fits = pieces === null ? [] : fitPieces(pieces, hint.length, (e.viewport?.columns ?? 80) - 4)

    if (fits.length === 0) {
      return next(e)
    }

    const { Box, Text } = $.ui.resolve(e)

    return (
      <Box flexDirection="row">
        <Text dimColor>{hint}</Text>
        <Text>{'  '}</Text>
        {fits.map((piece, i) => [
          i > 0 && <Text color="text">{SEPARATOR}</Text>,
          ...piece.map(span => (
            <Text color={span.colour ?? undefined} bold={span.bold === true}>
              {span.text}
            </Text>
          )),
        ])}
      </Box>
    )
  })
}
