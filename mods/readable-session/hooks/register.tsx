import { atom, read, update } from 'claude-code'
import type { Register } from 'claude-code'

import type { Activity, AgentTag } from '../types'

const running = atom({ plugin: 'readable-session', key: 'running' } as const, [])
const agents = atom({ plugin: 'readable-session', key: 'agents' } as const, {})

// Theme keys, so the mod follows `theme: auto` on dark and light terminals.
// One accent (`claude`), kept for your prompts and command cards; green, amber
// and red mean state only. Each tool has its own tone (KIND).
const TEXT = 'text'
const SUB = 'subtle'
const ACCENT = 'claude'
const OK = 'success'
const WARN = 'warning'
const FAIL = 'error'
const WAIT = 'permission'

/** Which tool a call is; each draws its icon, verb and card border in its own
 * tone. A tool in none of them stays `text`. */
export type Kind =
  | 'bash' | 'pwsh' | 'write' | 'edit' | 'read' | 'grep' | 'glob'
  | 'websearch' | 'webfetch' | 'agent' | 'skill' | 'mcp'

// Same hue per tool on both: light on dark themes, darker on light ones. All from
// the repo's palettes (see statusline.py THEMES), no two tools alike: changes in
// orange, shells in yellow, reading and searching in browns and peaches,
// agents and skills in red, MCP servers in grey.
const KIND: Record<'dark' | 'light', Record<Kind, string>> = {
  dark: {
    edit: '#FF8700', write: '#FFAF5F',
    bash: '#FFFF87', pwsh: '#D7D75F',
    read: '#AF875F', grep: '#D7AF87', glob: '#AF5F00',
    websearch: '#FFD7AF', webfetch: '#D7875F',
    agent: '#FF8787', skill: '#FF5F5F', mcp: '#BCBCBC',
  },
  light: {
    edit: '#D75F00', write: '#AF5F00',
    bash: '#AF8700', pwsh: '#878700',
    read: '#875F00', grep: '#AF875F', glob: '#5F3000',
    websearch: '#D7875F', webfetch: '#AF5F5F',
    agent: '#D75F5F', skill: '#D70000', mcp: '#6C6C6C',
  },
}

/** Set from the `theme` setting at session start and on each change; a theme
 * named `light…` takes the darker set, any other (`auto` too) the lighter. */
let tone: 'dark' | 'light' = 'dark'
const toneOf = (theme: unknown): 'dark' | 'light' => (/light/i.test(String(theme ?? '')) ? 'light' : 'dark')

export function kindColor(kind: Kind | undefined, t: 'dark' | 'light' = tone): string {
  return kind ? KIND[t][kind] : TEXT
}

/** A finished call stays in the band this long, so a fast one is seen. */
const LINGER_MS = 2000
const GROUP_ROWS = 6
const noop = () => undefined

// Nerd Font icons (the terminal uses CaskaydiaMono Nerd Font).
const I = {
  you: '\u{F0004}', // md-account
  command: '\u{F07B7}', // md-console_line
  shell: '\u{F018D}', // md-console
  pwsh: '\u{F0A0A}', // md-powershell
  write: '\u{F0DC9}', // md-file_document_edit_outline
  edit: '\u{F03EB}', // md-pencil
  read: '\u{F0214}', // md-file
  search: '\u{F0349}', // md-magnify
  web: '\u{F0349}', // md-magnify
  fetch: '\u{F0C66}', // md-download_network_outline
  agent: '\u{F167A}', // md-robot_outline
  skill: '\u{F140B}', // md-lightning_bolt
  plug: '\u{F06A5}', // md-power_plug
  task: '\u{F0756}', // md-format_list_checks
  tool: '\u{F1064}', // md-tools
  now: '\u{F040A}', // md-play
}

// State marks: plain glyphs, so they draw the same in any font.
const MARK = { ok: '\u2713', fail: '\u2717', stop: '\u25A0' }
// A row that expands, and an expanded card that folds back.
const ARROW = { down: '\u{F0140}', up: '\u{F0143}' } // md-chevron_down, md-chevron_up

const LANGS: Record<string, string> = {
  ts: 'TypeScript', tsx: 'TypeScript React', js: 'JavaScript', jsx: 'JavaScript React', mjs: 'JavaScript',
  py: 'Python', ps1: 'PowerShell', psm1: 'PowerShell', sh: 'Shell', bash: 'Shell', json: 'JSON',
  md: 'Markdown', css: 'CSS', scss: 'SCSS', html: 'HTML', go: 'Go', rs: 'Rust', java: 'Java',
  cs: 'C#', cpp: 'C++', c: 'C', rb: 'Ruby', php: 'PHP', sql: 'SQL', yml: 'YAML', yaml: 'YAML',
  toml: 'TOML', xml: 'XML', svg: 'SVG', swift: 'Swift', kt: 'Kotlin',
}

export type Described = {
  icon: string
  /** While it runs: `Writing`. */
  verb: string
  /** Once it ran: `Wrote`. */
  past: string
  detail: string
  /** What stands between verb and detail; two spaces when absent. */
  sep?: string
  kind?: Kind
}

const str = (v: unknown) => (typeof v === 'string' ? v : '')
const base = (p: string) => p.split(/[\\/]/).pop() || p

/** The file's parent folder and name: `src/server.ts`. */
export function shortPath(p: string): string {
  const parts = p.split(/[\\/]/).filter(s => s && !/^[A-Za-z]:$/.test(s))
  return parts.slice(-2).join('/') || p
}

/** A command's first line, with `…` when more lines follow. */
export function commandLine(cmd: string): string {
  const lines = cmd.split('\n').map(s => s.trim()).filter(Boolean)
  return (lines[0] ?? '') + (lines.length > 1 ? ' …' : '')
}

export function language(path: string): string {
  const ext = base(path).split('.').pop()?.toLowerCase() ?? ''
  return LANGS[ext] ?? ''
}

/** What a tool call does, in plain words, for its row and the band. */
export function describeTool(tool: string, input: unknown): Described {
  const i = (input ?? {}) as Record<string, unknown>
  const file = str(i.file_path) || str(i.notebook_path) || str(i.path)
  const lang = file ? language(file) : ''
  const fileDetail = file ? shortPath(file) + (lang ? ` · ${lang}` : '') : ''
  switch (tool) {
    case 'Bash':
      return { icon: I.shell, verb: 'Running Bash', past: 'Ran Bash', kind: 'bash', detail: commandLine(str(i.command)) }
    case 'PowerShell':
      return { icon: I.pwsh, verb: 'Running PowerShell', past: 'Ran PowerShell', kind: 'pwsh', detail: commandLine(str(i.command)) }
    case 'Write':
      return { icon: I.write, verb: 'Writing', past: 'Wrote', kind: 'write', detail: fileDetail }
    case 'Edit':
    case 'MultiEdit':
    case 'NotebookEdit':
      return { icon: I.edit, verb: 'Editing', past: 'Edited', kind: 'edit', detail: fileDetail }
    case 'Read':
      return { icon: I.read, verb: 'Reading', past: 'Read', kind: 'read', detail: fileDetail }
    case 'Grep':
      return {
        icon: I.search,
        kind: 'grep',
        verb: 'Searching code',
        past: 'Searched code',
        detail: `"${str(i.pattern)}"` + (str(i.path) ? `  in ${base(str(i.path))}` : ''),
      }
    case 'Glob':
      return { icon: I.search, verb: 'Finding files', past: 'Found files', kind: 'glob', detail: str(i.pattern) }
    case 'WebSearch':
      return { icon: I.web, verb: 'Searching the web', past: 'Searched the web', kind: 'websearch', detail: `"${str(i.query)}"` }
    case 'WebFetch':
      return { icon: I.fetch, verb: 'Fetching', past: 'Fetched', kind: 'webfetch', detail: str(i.url).replace(/^https?:\/\//, '') }
    case 'Agent':
    case 'Task': {
      const type = str(i.subagent_type) || 'agent'
      return { icon: I.agent, verb: `Starting ${type}`, past: `Started ${type}`, kind: 'agent', detail: str(i.description) }
    }
    case 'Skill':
      return { icon: I.skill, verb: 'Using skill', past: 'Used skill', kind: 'skill', detail: str(i.skill) }
    case 'TodoWrite':
      return { icon: I.task, verb: 'Updating tasks', past: 'Updated tasks', detail: '' }
  }
  const mcp = /^mcp__(.+?)__(.+)$/.exec(tool)
  if (mcp && mcp[1] && mcp[2]) {
    const server = mcp[1].replace(/^plugin_[^_]+_/, '').replace(/^claude_ai_/, '').replace(/_/g, ' ')
    return {
      icon: I.plug,
      kind: 'mcp',
      verb: `Using ${server}`,
      past: `Used ${server}`,
      detail: mcp[2].replace(/_/g, ' '),
      sep: ' · ',
    }
  }
  return { icon: I.tool, verb: tool, past: tool, detail: '' }
}

const BRIEF_KEYS = ['command', 'file_path', 'notebook_path', 'path', 'pattern', 'query', 'url', 'description', 'subagent_type', 'skill']

/** The few short input fields describeTool reads; never a file's content. */
export function brief(input: unknown): Record<string, string> {
  const i = (input ?? {}) as Record<string, unknown>
  const out: Record<string, string> = {}
  for (const k of BRIEF_KEYS) {
    if (typeof i[k] === 'string') out[k] = (i[k] as string).slice(0, 300)
  }
  return out
}

/** Calls that an expanded ToolGroup draws inline, output included. Module
 * memory: a hot reload empties it and the next group drawing refills it. */
const inGroup = new Set<string>()

export type RowState = 'running' | 'done' | 'failed' | 'interrupted'

/** The model family a subagent runs on: `sonnet`, `haiku`, `opus`, `fable`. */
export function family(model: string): string {
  return /opus|sonnet|haiku|fable/i.exec(model)?.[0]?.toLowerCase() ?? model
}

/** Amber when a subagent got an expensive model nobody asked for. */
export function isInheritedHeavy(tag: AgentTag): boolean {
  return !tag.explicit && /^(opus|fable)$/.test(family(tag.model))
}

// Cells a row may need beyond its own text: the transcript's gutter, and a
// glyph some terminals draw two cells wide.
const ROW_SLACK = 4
const CARD_SLACK = ROW_SLACK + 4

/** Cuts `text` to `room` cells (code points; the Nerd Font is one cell each). */
export function cut(text: string, room: number): string {
  const chars = [...text]
  return chars.length <= room ? text : chars.slice(0, Math.max(0, room)).join('').trimEnd()
}

type RowOpts = {
  key?: string
  tag?: string
  /** Cells the row draws into; when its detail does not fit, the detail is
   * cut and a down arrow (the row expands) stands where the cut is. */
  cols?: number
  /** An expanded card's header: an up arrow after the detail, always. */
  expanded?: boolean
}

/** The state mark's text, for measuring; `row` draws the same. */
const markText = (state: RowState) =>
  state === 'running' ? '…' : state === 'interrupted' ? `${MARK.stop}  interrupted` : state === 'failed' ? `${MARK.fail}  failed` : MARK.ok

/** One tool row, shared by the transcript's ToolUse and its folded ToolGroup:
 * icon and verb (past tense once done) in the kind's tone, plain-words detail,
 * state mark. One Text, so the row never wraps: a detail too long is cut by
 * the row itself, a down arrow in the kind's tone marking the cut, so the
 * state mark stays in view. */
function row(Text: any, d: Described, state: RowState, o: RowOpts = {}) {
  const color = kindColor(d.kind)
  const head = `${d.icon}  ${state === 'running' ? d.verb : d.past}`
  const sep = d.sep ?? '  '
  const tail = (o.tag ? `  ${o.tag}` : '') + '  ' + markText(state)
  let detail = d.detail
  let arrow: string | undefined = o.expanded ? ARROW.up : undefined
  if (o.cols && o.cols > 0) {
    const arrowCells = 2
    const room = o.cols - [...head].length - [...tail].length - (detail ? [...sep].length : 0) - (o.expanded ? arrowCells : 0)
    if (detail && [...detail].length > room) {
      detail = cut(detail, room - (o.expanded ? 0 : arrowCells))
      if (!o.expanded) arrow = ARROW.down
    }
  }
  const mark =
    state === 'running' ? (
      <Text color={TEXT}>…</Text>
    ) : state === 'interrupted' ? (
      <Text color={SUB}>{MARK.stop}  interrupted</Text>
    ) : state === 'failed' ? (
      <Text color={FAIL}>{MARK.fail}  failed</Text>
    ) : (
      <Text color={OK}>{MARK.ok}</Text>
    )
  return (
    <Text key={o.key} wrap="truncate-end">
      <Text color={color} bold>
        {head}
      </Text>
      {detail ? <Text color={SUB}>{sep}{detail}</Text> : null}
      {arrow ? <Text color={color}> {arrow}</Text> : null}
      {o.tag ? <Text color={SUB}>  {o.tag}</Text> : null}
      {'  '}
      {mark}
    </Text>
  )
}

/** At most this many output lines in an expanded card; the rest is counted. */
const OUT_LINES = 40

export type OutLine = { text: string; color: string }

const plain = (s: string) =>
  s
    .replace(/\x1b\[[0-9;?]*[A-Za-z]/g, '')
    .replace(/<\/?tool_use_error>/g, '')
    .replace(/\t/g, '  ')
    .replace(/\r/g, '')
const linesOf = (s: string) => plain(s).replace(/\n+$/, '').split('\n')
const kb = (bytes: number) => `${Math.max(1, Math.round(bytes / 1024))}KB`
const plural = (n: number, one: string) => `${n} ${one}${n === 1 ? '' : 's'}`

/** Caps `lines` at OUT_LINES, counting what is left out. */
function capped(lines: OutLine[]): OutLine[] {
  if (lines.length <= OUT_LINES) return lines
  return [...lines.slice(0, OUT_LINES), { text: `+${lines.length - OUT_LINES} more lines`, color: SUB }]
}

/** A diff's hunks as lines, added green and removed red. */
function diffLines(patch: unknown): OutLine[] {
  const hunks = Array.isArray(patch) ? (patch as { lines?: unknown }[]) : []
  const out: OutLine[] = []
  for (const h of hunks) {
    for (const l of Array.isArray(h.lines) ? (h.lines as unknown[]) : []) {
      const s = plain(str(l))
      out.push({ text: s, color: s.startsWith('+') ? 'diffAdded' : s.startsWith('-') ? 'diffRemoved' : SUB })
    }
  }
  return out
}

/** What an expanded card draws under its header, from the call's stored
 * result: a shell's stdout (stderr red), a diff, a list of files, or a line
 * that says what came back. A failed call draws the error the model read. */
export function outputLines(tool: string, output: unknown, state: RowState): OutLine[] {
  if (state === 'interrupted') return [{ text: 'Interrupted', color: SUB }]
  if (typeof output === 'string') {
    return capped(linesOf(output).map(text => ({ text, color: state === 'failed' ? FAIL : TEXT })))
  }
  const o = (output ?? {}) as Record<string, any>
  switch (tool) {
    case 'Bash':
    case 'PowerShell': {
      if (o.backgroundTaskId) return [{ text: 'Running in the background', color: SUB }]
      const out = str(o.stdout).trim() ? linesOf(str(o.stdout)).map(text => ({ text, color: TEXT })) : []
      const err = str(o.stderr).trim() ? linesOf(str(o.stderr)).map(text => ({ text, color: FAIL })) : []
      const lines = capped([...out, ...err])
      if (typeof o.timedOutAfterMs === 'number') lines.push({ text: `Timed out after ${Math.round(o.timedOutAfterMs / 1000)}s`, color: WARN })
      return lines.length ? lines : [{ text: 'No output', color: SUB }]
    }
    case 'Read': {
      const f = (o.file ?? {}) as Record<string, any>
      if (o.type === 'image') return [{ text: `Read image (${kb(Number(f.originalSize) || 0)})`, color: SUB }]
      if (o.type === 'pdf') return [{ text: 'Read PDF', color: SUB }]
      if (o.type === 'notebook') return [{ text: `Read notebook (${plural((f.cells as unknown[] | undefined)?.length ?? 0, 'cell')})`, color: SUB }]
      if (o.type === 'parts') return [{ text: `Read ${plural((o.pages as unknown[] | undefined)?.length ?? 0, 'page')}`, color: SUB }]
      return [{ text: `Read ${plural(Number(f.numLines) || 0, 'line')}`, color: SUB }]
    }
    case 'Edit':
    case 'MultiEdit':
    case 'Write': {
      const diff = diffLines(o.structuredPatch)
      if (diff.length) return capped(diff)
      if (tool === 'Write') return [{ text: `Wrote ${plural(linesOf(str(o.content)).length, 'line')}`, color: SUB }]
      return [{ text: 'No changes', color: SUB }]
    }
    case 'Grep': {
      if (o.mode === 'content' || o.mode === 'count') {
        return str(o.content).trim()
          ? capped(linesOf(str(o.content)).map(text => ({ text, color: TEXT })))
          : [{ text: 'No matches', color: SUB }]
      }
      return fileList(o)
    }
    case 'Glob':
      return fileList(o)
    case 'WebFetch':
      return [{ text: `${o.code ?? ''} ${str(o.codeText)} · ${kb(Number(o.bytes) || 0)}`.trim(), color: SUB }]
    case 'WebSearch': {
      const n = Array.isArray(o.results) ? (o.results as unknown[]).length : 0
      return [{ text: `Searched in ${Math.round(Number(o.durationSeconds) || 0)}s · ${plural(n, 'result block')}`, color: SUB }]
    }
  }
  // An MCP tool's result: its text blocks.
  const blocks = Array.isArray(output) ? (output as { type?: string; text?: unknown }[]) : []
  const text = blocks.filter(b => b?.type === 'text').map(b => str(b.text)).join('\n')
  return text.trim() ? capped(linesOf(text).map(t => ({ text: t, color: TEXT }))) : []
}

function fileList(o: Record<string, any>): OutLine[] {
  const files = Array.isArray(o.filenames) ? (o.filenames as unknown[]).map(f => shortPath(str(f))) : []
  if (!files.length) return [{ text: 'No files found', color: SUB }]
  const n = Number(o.numFiles) || files.length
  return capped([{ text: `Found ${plural(n, 'file')}`, color: SUB }, ...files.map(text => ({ text, color: TEXT }))])
}

/** The cells a row has: the viewport's width less `slack`; undefined where no
 * surface measured, and the row is then cut at the edge as before. */
const cols = (e: { viewport?: { columns: number } }, slack: number) =>
  e.viewport?.columns ? e.viewport.columns - slack : undefined

const callState = (c: { isRunning: boolean; isErrored: boolean; isInterrupted: boolean }): RowState =>
  c.isRunning ? 'running' : c.isInterrupted ? 'interrupted' : c.isErrored ? 'failed' : 'done'

async function sweepMain($: any) {
  const now: number = await $.clock.now()
  await update($, running, list => list.filter(x => x.agentId || (x.doneAt !== undefined && now - x.doneAt < LINGER_MS))).catch(noop)
}

export const register: Register = on => {
  on('session.start', async ($, e, next) => {
    const theme = (await $.config.list().catch(() => [])).find(r => r.key === 'theme')
    tone = toneOf(theme?.value)
    await $.command.register({
      name: 'readable-session',
      description: 'Show what readable-session tracks (running tools)',
    })
    return next(e)
  })

  on('config.set', { key: 'theme' }, async ($, e, next) => {
    const r = await next(e)
    if (!r.deny) tone = toneOf(r.value)
    return r
  }).catch(($, e, next) => next(e))

  on('command.run', { command: 'readable-session' }, async $ => {
    const r = (await read($, running)).filter(x => x.doneAt === undefined)
    return {
      text: `running: ${r.map(x => x.tool + (x.awaiting ? ' (waiting for you)' : '')).join(', ') || 'none'}`,
    }
  })

  // Main-loop calls left in `running` (a reload dropped their tool.call's
  // finally) are cleared as a main-loop turn starts and ends; a subagent's
  // as it finishes. A call that just finished is kept until its linger ends.
  on('turn.start', async ($, e, next) => {
    // A subagent's turn starting says nothing about the main loop's calls.
    if (!e.agentId) await sweepMain($)
    return next(e)
  })

  on('turn.complete', async ($, e, next) => {
    const id = e.agentId
    if (id) {
      await update($, running, list => list.filter(x => x.agentId !== id)).catch(noop)
    } else {
      await sweepMain($)
    }
    return next(e)
  })

  // What is running now, for the band above the prompt. A finished call
  // stays LINGER_MS from its start, marked done, so a fast one is seen.
  on('tool.call', async ($, e, next) => {
    const id = e.tool_use_id ?? `${e.tool}-${Math.random().toString(36).slice(2)}`
    const startedAt: number = await $.clock.now()
    const act: Activity = { id, tool: e.tool, input: brief(e), agentId: e.agentId, startedAt }
    // Bookkeeping must never break the call itself.
    await update($, running, list => [...list, act].slice(-20)).catch(noop)
    let failed = false
    try {
      const r = await next(e)
      failed = !!(r as { isError?: boolean; deny?: string }).isError || !!(r as { deny?: string }).deny
      return r
    } catch (err) {
      failed = true
      throw err
    } finally {
      const doneAt: number = await $.clock.now()
      const remaining = Math.max(0, LINGER_MS - (doneAt - startedAt))
      const drop = () => update($, running, list => list.filter(x => x.id !== id)).catch(noop)
      if (remaining === 0) {
        await drop()
      } else {
        await update($, running, list => list.map(x => (x.id === id ? { ...x, doneAt, failed, awaiting: false } : x))).catch(noop)
        $.clock.after(remaining, drop)
      }
    }
  }).catch(($, e, next) => next(e))

  // A call put to the person (verdict `ask`) waits at the permission prompt.
  // Observe only: the verdict beneath is returned unchanged.
  on('tool.check', async ($, e, next) => {
    const verdict = await next(e)
    const id = e.tool_use_id
    if (verdict.decision === 'ask' && id) {
      await update($, running, list => list.map(x => (x.id === id ? { ...x, awaiting: true } : x))).catch(noop)
    }
    return verdict
  }).catch(($, e, next) => next(e))

  // The model each subagent actually got, and whether the call named it.
  on('agent.spawn', async ($, e, next) => {
    const r = await next(e)
    const tag: AgentTag = { model: r.model, explicit: !!e.model }
    await update($, agents, m => {
      const entries = Object.entries({ ...m, [e.tool_use_id]: tag })
      return Object.fromEntries(entries.slice(-200))
    }).catch(noop)
    return r
  }).catch(($, e, next) => next(e))

  // Your own prompts: a compact bordered card with a label.
  on('ui.render', { component: 'UserMessage' }, ($, e, next) => {
    if (e.surface !== 'terminal' || e.props.origin.kind !== 'composer') return next(e)
    const { Box, Text } = $.ui.resolve(e)
    return (
      <Box flexDirection="column" borderStyle="round" borderColor={ACCENT} paddingX={1}>
        <Text color={ACCENT} bold>
          {I.you}  You prompted
        </Text>
        <Text>{e.props.text}</Text>
      </Box>
    )
  })

  // A slash command's output: the same accent card as your prompts, headed by
  // the command and its arguments. A row another module drew empty stays empty.
  on('ui.render', { component: 'CommandOutput' }, async ($, e, next) => {
    const inner = await next(e)
    if (e.surface !== 'terminal') return inner
    if (inner.type === 'Box' && !(inner.children as unknown[] | undefined)?.length) return inner
    const { Box, Text } = $.ui.resolve(e)
    const { command, args, isErrored } = e.props
    return (
      <Box flexDirection="column" borderStyle="round" borderColor={isErrored ? FAIL : ACCENT} paddingX={1}>
        <Text color={isErrored ? FAIL : ACCENT} bold>
          {I.command}  /{command}
          {args ? ` ${args}` : ''}
        </Text>
        {inner}
      </Box>
    )
  })

  // A folded group draws one stable row per call (what ToolUse draws), so a
  // row does not change shape when the group closes. An expanded group draws
  // each call's output inline under its row: note which calls those are, so
  // their rows keep the engine's drawing.
  on('ui.render', { component: 'ToolGroup' }, ($, e, next) => {
    if (e.props.isExpanded) {
      for (const c of e.props.calls) {
        if (c.tool_use_id) inGroup.add(c.tool_use_id)
      }
      while (inGroup.size > 500) {
        const oldest = inGroup.values().next().value
        if (oldest === undefined) break
        inGroup.delete(oldest)
      }
      return next(e)
    }
    if (e.surface !== 'terminal') return next(e)
    const { Box, Text } = $.ui.resolve(e)
    const calls = e.props.calls
    const shown = calls.slice(0, GROUP_ROWS)
    const hidden = calls.length - shown.length
    return (
      <Box flexDirection="column">
        {shown.map((c, i) => row(Text, describeTool(c.tool, c.input), callState(c), { key: `g${i}-${c.tool_use_id ?? ''}`, cols: cols(e, ROW_SLACK) }))}
        {hidden > 0 ? <Text key="more" color={SUB} wrap="truncate-end">+{hidden} more</Text> : null}
      </Box>
    )
  })

  // Tool rows: icon, verb (past tense once done), plain-words detail, state mark.
  on('ui.render', { component: 'ToolUse' }, async ($, e, next) => {
    if (e.surface !== 'terminal') return next(e)
    const p = e.props
    // An agent's row carries its nested progress; keep the engine's, with the
    // model it runs on in one line above.
    if (p.tool === 'Agent' || p.tool === 'Task') {
      const inner = await next(e)
      const tag = (await read($, agents))[p.tool_use_id]
      if (!tag) return inner
      const { Box, Text } = $.ui.resolve(e)
      const heavy = isInheritedHeavy(tag)
      return (
        <Box flexDirection="column">
          <Text color={heavy ? WARN : SUB} wrap="truncate-end">
            {I.agent}  {family(tag.model)}
            {heavy ? ' (no model set)' : ''}
          </Text>
          {inner}
        </Box>
      )
    }
    // A row in an expanded group draws its output inline: a card like your
    // prompts', bordered in the kind's tone (red once it failed), headed by the
    // row, the output drawn here (the engine's block paints a grey fill).
    if (p.output !== undefined && inGroup.has(p.tool_use_id)) {
      const { Box, Text } = $.ui.resolve(e)
      const state = callState(p)
      const d = describeTool(p.tool, p.input)
      const lines = outputLines(p.tool, p.output, state)
      return (
        <Box flexDirection="column" borderStyle="round" borderColor={state === 'failed' ? FAIL : kindColor(d.kind)} paddingX={1}>
          {row(Text, d, state, { expanded: true, cols: cols(e, CARD_SLACK) })}
          {lines.map((l, i) => (
            <Text key={`o${i}`} color={l.color}>
              {l.text || ' '}
            </Text>
          ))}
        </Box>
      )
    }
    const { Text } = $.ui.resolve(e)
    return row(Text, describeTool(p.tool, p.input), callState(p), { cols: cols(e, ROW_SLACK) })
  })

  // The band above the prompt: the calls running now or just finished, and
  // those waiting for you. Running calls come first, so a lingering one never
  // pushes a live one out.
  on('ui.render', { component: 'AbovePrompt' }, async ($, e, next) => {
    if (e.surface !== 'terminal' || e.props.hasSurvey) return next(e)
    const [list, tags] = [await read($, running), await read($, agents)]
    if (list.length === 0) return next(e)
    const { Box, Text } = $.ui.resolve(e)

    const live = list.filter(x => x.doneAt === undefined)
    const done = list.filter(x => x.doneAt !== undefined)
    const calls = [...live.slice(-5), ...done].slice(0, 5)

    const rows = calls.map(act => {
      const d = describeTool(act.tool, act.input)
      const t = tags[act.id]
      const tag = t ? family(t.model) : undefined
      if (act.doneAt !== undefined) return row(Text, d, act.failed ? 'failed' : 'done', { key: `call-${act.id}`, tag, cols: e.props.bodyColumns })
      return (
        <Text key={`call-${act.id}`} wrap="truncate-end">
          {act.awaiting
            ? <Text color={WAIT} bold>{I.now}  waiting for you</Text>
            : <Text color={kindColor(d.kind)} bold>{I.now}  {d.verb}</Text>}
          {d.detail ? <Text color={SUB}>{d.sep ?? '  '}{d.detail}</Text> : null}
          {t ? <Text color={isInheritedHeavy(t) ? WARN : SUB}>  {family(t.model)}</Text> : null}
        </Text>
      )
    })

    const max = typeof e.props.maxRows === 'number' && e.props.maxRows > 0 ? e.props.maxRows : rows.length
    const shown = rows.length > max ? rows.slice(0, Math.max(0, max - 1)) : rows
    const hidden = rows.length - shown.length
    return (
      <Box flexDirection="column">
        {shown}
        {hidden > 0 ? <Text key="more" color={SUB} wrap="truncate-end">+{hidden} more</Text> : null}
      </Box>
    )
  })
}
