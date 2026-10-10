import { atom, read, update } from 'claude-code'
import type { Register } from 'claude-code'

import type { Activity } from '../types'

const running = atom({ plugin: 'readable-session', key: 'running' } as const, [])

// Secondary text: the terminal's usual light grey, not a faint dim.
const GREY = '#d0d0d0'
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
  ok: '\u{F05E0}', // md-check_circle
  fail: '\u{F0159}', // md-close_circle
  stop: '\u{F04DB}', // md-stop
  now: '\u{F040A}', // md-play
}

// Verb colors by kind of work.
const C = {
  you: 'claude', // the theme's own Claude orange
  shell: '#ffaf5f',
  write: '#87d75f',
  read: '#5fafff',
  search: '#d787ff',
  web: '#5fd7d7',
  agent: '#ff87af',
  other: '#d7af5f',
  ok: '#5fd75f',
  fail: '#ff5f5f',
  wait: 'permission', // the theme's own permission-prompt color
}

const LANGS: Record<string, string> = {
  ts: 'TypeScript', tsx: 'TypeScript React', js: 'JavaScript', jsx: 'JavaScript React', mjs: 'JavaScript',
  py: 'Python', ps1: 'PowerShell', psm1: 'PowerShell', sh: 'Shell', bash: 'Shell', json: 'JSON',
  md: 'Markdown', css: 'CSS', scss: 'SCSS', html: 'HTML', go: 'Go', rs: 'Rust', java: 'Java',
  cs: 'C#', cpp: 'C++', c: 'C', rb: 'Ruby', php: 'PHP', sql: 'SQL', yml: 'YAML', yaml: 'YAML',
  toml: 'TOML', xml: 'XML', svg: 'SVG', swift: 'Swift', kt: 'Kotlin',
}

export type Described = {
  icon: string
  color: string
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
      return { icon: I.shell, color: C.shell, verb: 'Running Bash', past: 'Ran Bash', detail: commandLine(str(i.command)) }
    case 'PowerShell':
      return { icon: I.pwsh, color: C.shell, verb: 'Running PowerShell', past: 'Ran PowerShell', detail: commandLine(str(i.command)) }
    case 'Write':
      return { icon: I.write, color: C.write, verb: 'Writing', past: 'Wrote', detail: fileDetail }
    case 'Edit':
    case 'MultiEdit':
    case 'NotebookEdit':
      return { icon: I.edit, color: C.write, verb: 'Editing', past: 'Edited', detail: fileDetail }
    case 'Read':
      return { icon: I.read, color: C.read, verb: 'Reading', past: 'Read', detail: fileDetail }
    case 'Grep':
      return {
        icon: I.search,
        color: C.search,
        verb: 'Searching code',
        past: 'Searched code',
        detail: `"${str(i.pattern)}"` + (str(i.path) ? `  in ${base(str(i.path))}` : ''),
      }
    case 'Glob':
      return { icon: I.search, color: C.search, verb: 'Finding files', past: 'Found files', detail: str(i.pattern) }
    case 'WebSearch':
      return { icon: I.web, color: C.web, verb: 'Searching the web', past: 'Searched the web', detail: `"${str(i.query)}"` }
    case 'WebFetch':
      return { icon: I.fetch, color: C.web, verb: 'Fetching', past: 'Fetched', detail: str(i.url).replace(/^https?:\/\//, '') }
    case 'Agent':
    case 'Task': {
      const type = str(i.subagent_type) || 'agent'
      return { icon: I.agent, color: C.agent, verb: `Starting ${type}`, past: `Started ${type}`, detail: str(i.description) }
    }
    case 'Skill':
      return { icon: I.skill, color: C.agent, verb: 'Using skill', past: 'Used skill', detail: str(i.skill) }
    case 'TodoWrite':
      return { icon: I.task, color: C.other, verb: 'Updating tasks', past: 'Updated tasks', detail: '' }
  }
  const mcp = /^mcp__(.+?)__(.+)$/.exec(tool)
  if (mcp && mcp[1] && mcp[2]) {
    const server = mcp[1].replace(/^plugin_[^_]+_/, '').replace(/^claude_ai_/, '').replace(/_/g, ' ')
    return {
      icon: I.plug,
      color: C.other,
      verb: `Using ${server}`,
      past: `Used ${server}`,
      detail: mcp[2].replace(/_/g, ' '),
      sep: ' · ',
    }
  }
  return { icon: I.tool, color: C.other, verb: tool, past: tool, detail: '' }
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

export const register: Register = on => {
  on('session.start', async ($, e, next) => {
    await $.command.register({
      name: 'readable-session',
      description: 'Show what readable-session tracks (running tools)',
    })
    return next(e)
  })

  on('command.run', { command: 'readable-session' }, async $ => {
    const r = await read($, running)
    return {
      text: `running: ${r.map(x => x.tool + (x.awaiting ? ' (waiting for you)' : '')).join(', ') || 'none'}`,
    }
  })

  // Main-loop calls left in `running` (a reload dropped their tool.call's
  // finally) are cleared as a main-loop turn starts and ends; a subagent's
  // as it finishes.
  on('turn.start', async ($, e, next) => {
    await update($, running, list => list.filter(x => x.agentId)).catch(noop)
    return next(e)
  })

  on('turn.complete', async ($, e, next) => {
    const id = e.agentId
    if (id) {
      await update($, running, list => list.filter(x => x.agentId !== id)).catch(noop)
    } else {
      await update($, running, list => list.filter(x => x.agentId)).catch(noop)
    }
    return next(e)
  })

  // What is running now, for the band above the prompt.
  on('tool.call', async ($, e, next) => {
    const id = e.tool_use_id ?? `${e.tool}-${Math.random().toString(36).slice(2)}`
    const act: Activity = { id, tool: e.tool, input: brief(e), agentId: e.agentId }
    // Bookkeeping must never break the call itself.
    await update($, running, list => [...list, act].slice(-20)).catch(noop)
    try {
      return await next(e)
    } finally {
      await update($, running, list => list.filter(x => x.id !== id)).catch(noop)
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

  // Your own prompts: a compact bordered card with a label.
  on('ui.render', { component: 'UserMessage' }, ($, e, next) => {
    if (e.surface !== 'terminal' || e.props.origin.kind !== 'composer') return next(e)
    const { Box, Text } = $.ui.resolve(e)
    return (
      <Box flexDirection="column" borderStyle="round" borderColor={C.you} paddingX={1}>
        <Text color={C.you} bold>
          {I.you}  You prompted
        </Text>
        <Text>{e.props.text}</Text>
      </Box>
    )
  })

  // A slash command's output: the same orange card as your prompts, headed by
  // the command and its arguments. A row another module drew empty stays empty.
  on('ui.render', { component: 'CommandOutput' }, async ($, e, next) => {
    const inner = await next(e)
    if (e.surface !== 'terminal') return inner
    if (inner.type === 'Box' && !(inner.children as unknown[] | undefined)?.length) return inner
    const { Box, Text } = $.ui.resolve(e)
    const { command, args, isErrored } = e.props
    return (
      <Box flexDirection="column" borderStyle="round" borderColor={isErrored ? C.fail : C.you} paddingX={1}>
        <Text color={isErrored ? C.fail : C.you} bold>
          {I.command}  /{command}
          {args ? ` ${args}` : ''}
        </Text>
        {inner}
      </Box>
    )
  })

  // An expanded group draws each call's output inline under its row: note
  // which calls those are, so their rows keep the engine's drawing.
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
    }
    return next(e)
  })

  // Tool rows: icon, colored verb (past tense once done), plain-words detail, state mark.
  on('ui.render', { component: 'ToolUse' }, ($, e, next) => {
    if (e.surface !== 'terminal') return next(e)
    const p = e.props
    // An agent's row carries its nested progress; keep the engine's.
    if (p.tool === 'Agent' || p.tool === 'Task') return next(e)
    // A row in an expanded group draws its output inline; keep it.
    if (p.output !== undefined && inGroup.has(p.tool_use_id)) return next(e)
    const d = describeTool(p.tool, p.input)
    const { Text } = $.ui.resolve(e)
    const mark = p.isRunning
      ? <Text color={d.color}>…</Text>
      : p.isInterrupted
        ? <Text color={GREY}>{I.stop}  interrupted</Text>
        : p.isErrored
          ? <Text color={C.fail}>{I.fail}  failed</Text>
          : <Text color={C.ok}>{I.ok}</Text>
    // One Text, so the row never wraps: it is cut at the edge instead.
    return (
      <Text wrap="truncate-end">
        <Text color={d.color} bold>
          {d.icon}  {p.isRunning ? d.verb : d.past}
        </Text>
        {d.detail ? <Text color={GREY}>{d.sep ?? '  '}{d.detail}</Text> : null}
        {'  '}
        {mark}
      </Text>
    )
  })

  // The band above the prompt: the calls running now, or waiting for you.
  on('ui.render', { component: 'AbovePrompt' }, async ($, e, next) => {
    if (e.surface !== 'terminal' || e.props.hasSurvey) return next(e)
    const calls = await read($, running)
    if (calls.length === 0) return next(e)
    const { Box, Text } = $.ui.resolve(e)

    const rows = calls.slice(-5).map(act => {
      const d = describeTool(act.tool, act.input)
      return (
        <Text key={`call-${act.id}`} wrap="truncate-end">
          {act.awaiting
            ? <Text color={C.wait} bold>{I.now}  waiting for you</Text>
            : <Text color={d.color} bold>{I.now}  {d.verb}</Text>}
          {d.detail ? <Text color={GREY}>{d.sep ?? '  '}{d.detail}</Text> : null}
        </Text>
      )
    })

    const max = typeof e.props.maxRows === 'number' && e.props.maxRows > 0 ? e.props.maxRows : rows.length
    const shown = rows.length > max ? rows.slice(0, Math.max(0, max - 1)) : rows
    const hidden = rows.length - shown.length
    return (
      <Box flexDirection="column">
        {shown}
        {hidden > 0 ? <Text key="more" color={GREY} wrap="truncate-end">+{hidden} more</Text> : null}
      </Box>
    )
  })
}
