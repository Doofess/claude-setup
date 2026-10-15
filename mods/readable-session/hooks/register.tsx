import { atom, read, update } from 'claude-code'
import type { Register } from 'claude-code'

import type { Activity, AgentTag } from '../types'

const running = atom({ plugin: 'readable-session', key: 'running' } as const, [])
const agents = atom({ plugin: 'readable-session', key: 'agents' } as const, {})

// Theme keys, so the mod follows `theme: auto` on dark and light terminals.
// One accent (`claude`), kept for your prompts and command cards; the kind of
// work is shown by its icon, not by color; green, amber and red mean state only.
const TEXT = 'text'
const SUB = 'subtle'
const ACCENT = 'claude'
const OK = 'success'
const WARN = 'warning'
const FAIL = 'error'
const WAIT = 'permission'

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
  web: '\u{F059F}', // md-web
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
      return { icon: I.shell, verb: 'Running Bash', past: 'Ran Bash', detail: commandLine(str(i.command)) }
    case 'PowerShell':
      return { icon: I.pwsh, verb: 'Running PowerShell', past: 'Ran PowerShell', detail: commandLine(str(i.command)) }
    case 'Write':
      return { icon: I.write, verb: 'Writing', past: 'Wrote', detail: fileDetail }
    case 'Edit':
    case 'MultiEdit':
    case 'NotebookEdit':
      return { icon: I.edit, verb: 'Editing', past: 'Edited', detail: fileDetail }
    case 'Read':
      return { icon: I.read, verb: 'Reading', past: 'Read', detail: fileDetail }
    case 'Grep':
      return {
        icon: I.search,
        
        verb: 'Searching code',
        past: 'Searched code',
        detail: `"${str(i.pattern)}"` + (str(i.path) ? `  in ${base(str(i.path))}` : ''),
      }
    case 'Glob':
      return { icon: I.search, verb: 'Finding files', past: 'Found files', detail: str(i.pattern) }
    case 'WebSearch':
      return { icon: I.web, verb: 'Searching the web', past: 'Searched the web', detail: `"${str(i.query)}"` }
    case 'WebFetch':
      return { icon: I.fetch, verb: 'Fetching', past: 'Fetched', detail: str(i.url).replace(/^https?:\/\//, '') }
    case 'Agent':
    case 'Task': {
      const type = str(i.subagent_type) || 'agent'
      return { icon: I.agent, verb: `Starting ${type}`, past: `Started ${type}`, detail: str(i.description) }
    }
    case 'Skill':
      return { icon: I.skill, verb: 'Using skill', past: 'Used skill', detail: str(i.skill) }
    case 'TodoWrite':
      return { icon: I.task, verb: 'Updating tasks', past: 'Updated tasks', detail: '' }
  }
  const mcp = /^mcp__(.+?)__(.+)$/.exec(tool)
  if (mcp && mcp[1] && mcp[2]) {
    const server = mcp[1].replace(/^plugin_[^_]+_/, '').replace(/^claude_ai_/, '').replace(/_/g, ' ')
    return {
      icon: I.plug,
      
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

/** One tool row, shared by the transcript's ToolUse and its folded ToolGroup:
 * icon, verb (past tense once done), plain-words detail, state mark. One Text,
 * so the row never wraps: it is cut at the edge instead. */
function row(Text: any, d: Described, state: RowState, key?: string, tag?: string) {
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
    <Text key={key} wrap="truncate-end">
      <Text color={TEXT} bold>
        {d.icon}  {state === 'running' ? d.verb : d.past}
      </Text>
      {d.detail ? <Text color={SUB}>{d.sep ?? '  '}{d.detail}</Text> : null}
      {tag ? <Text color={SUB}>  {tag}</Text> : null}
      {'  '}
      {mark}
    </Text>
  )
}

const callState = (c: { isRunning: boolean; isErrored: boolean; isInterrupted: boolean }): RowState =>
  c.isRunning ? 'running' : c.isInterrupted ? 'interrupted' : c.isErrored ? 'failed' : 'done'

async function sweepMain($: any) {
  const now: number = await $.clock.now()
  await update($, running, list => list.filter(x => x.agentId || (x.doneAt !== undefined && now - x.doneAt < LINGER_MS))).catch(noop)
}

export const register: Register = on => {
  on('session.start', async ($, e, next) => {
    await $.command.register({
      name: 'readable-session',
      description: 'Show what readable-session tracks (running tools)',
    })
    return next(e)
  })

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
        {shown.map((c, i) => row(Text, describeTool(c.tool, c.input), callState(c), `g${i}-${c.tool_use_id ?? ''}`))}
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
    // A row in an expanded group draws its output inline; keep it.
    if (p.output !== undefined && inGroup.has(p.tool_use_id)) return next(e)
    const { Text } = $.ui.resolve(e)
    return row(Text, describeTool(p.tool, p.input), callState(p))
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
      if (act.doneAt !== undefined) return row(Text, d, act.failed ? 'failed' : 'done', `call-${act.id}`, tag)
      return (
        <Text key={`call-${act.id}`} wrap="truncate-end">
          {act.awaiting
            ? <Text color={WAIT} bold>{I.now}  waiting for you</Text>
            : <Text color={TEXT} bold>{I.now}  {d.verb}</Text>}
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
