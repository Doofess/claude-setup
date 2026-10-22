import { describe, expect, test } from 'claude-code/testing'

import { bashDiffs, brief, describeTool, diffOf, diffRuns, kindColor, outputLines, promptText } from '../hooks/register.tsx'

describe('describeTool', () => {
  test('names the kind of work in plain words', () => {
    expect(describeTool('Bash', { command: 'git status --short\necho hi' })).toMatchObject({
      verb: 'Running Bash',
      past: 'Ran Bash',
      detail: 'git status --short …',
    })
    expect(describeTool('Bash', { command: 'ls\n\n' }).detail).toBe('ls')
    expect(describeTool('PowerShell', { command: 'Get-Process' })).toMatchObject({
      verb: 'Running PowerShell',
      past: 'Ran PowerShell',
    })
    expect(describeTool('Write', { file_path: 'C:\\dev\\app\\src\\server.ts' })).toMatchObject({
      verb: 'Writing',
      past: 'Wrote',
      detail: 'src/server.ts · TypeScript',
    })
    expect(describeTool('Edit', { file_path: '/repo/statusline.py' })).toMatchObject({
      past: 'Edited',
      detail: 'repo/statusline.py · Python',
    })
    expect(describeTool('Read', { file_path: 'main.py' })).toMatchObject({ past: 'Read', detail: 'main.py · Python' })
    expect(describeTool('WebSearch', { query: 'claude code statusline' })).toMatchObject({
      verb: 'Searching the web',
      past: 'Searched the web',
      detail: '"claude code statusline"',
    })
    expect(describeTool('Grep', { pattern: 'x' }).past).toBe('Searched code')
    expect(describeTool('Glob', { pattern: '*.ts' }).past).toBe('Found files')
    expect(describeTool('WebFetch', { url: 'https://a.dev' }).past).toBe('Fetched')
    expect(describeTool('Skill', { skill: 'tdd' }).past).toBe('Used skill')
    expect(describeTool('mcp__claude_ai_Gmail__search_threads', {})).toMatchObject({
      verb: 'Using Gmail',
      past: 'Used Gmail',
      detail: 'search threads',
      sep: ' · ',
    })
  })

  test('gives each tool its own tone; the rest stay text', () => {
    const kinds = {
      Bash: 'bash', PowerShell: 'pwsh', Write: 'write', Edit: 'edit', MultiEdit: 'edit', Read: 'read',
      Grep: 'grep', Glob: 'glob', WebSearch: 'websearch', WebFetch: 'webfetch', Agent: 'agent', Task: 'agent',
      Skill: 'skill', mcp__x__y: 'mcp',
    } as const
    for (const [tool, kind] of Object.entries(kinds)) expect(describeTool(tool, {}).kind).toBe(kind)
    expect(describeTool('TodoWrite', {}).kind).toBe(undefined)
    expect(kindColor(undefined)).toBe('text')
    const all = [...new Set(Object.values(kinds))]
    for (const t of ['dark', 'light'] as const) expect(new Set(all.map(k => kindColor(k, t))).size).toBe(all.length)
    expect(kindColor('read', 'light')).not.toBe(kindColor('read', 'dark'))
    expect(kindColor('edit', 'dark')).toBe('#FFFFFF')
  })

  test("draws each tool's output from its stored result", () => {
    const shell = outputLines('Bash', { stdout: 'a\x1b[32mb\x1b[0m\n', stderr: 'boom', interrupted: false }, 'done')
    expect(shell).toEqual([
      { text: 'ab', color: 'text' },
      { text: 'boom', color: 'error' },
    ])
    expect(outputLines('PowerShell', { stdout: '', stderr: '', interrupted: false }, 'done')[0]?.text).toBe('No output')
    const long = outputLines('Bash', { stdout: Array.from({ length: 50 }, (_, i) => `l${i}`).join('\n'), stderr: '' }, 'done')
    expect(long).toHaveLength(41)
    expect(long[40]?.text).toBe('+10 more lines')
    expect(outputLines('Read', { type: 'image', file: { originalSize: 58 * 1024 } }, 'done')[0]?.text).toBe('Read image (58KB)')
    const diff = outputLines('Edit', { structuredPatch: [{ lines: [' a', '-b', '+c'] }] }, 'done')
    expect(diff.map(l => l.color)).toEqual(['subtle', '#FF8787', '#87D787'])
    expect(outputLines('Glob', { numFiles: 1, filenames: ['C:/dev/app/x.ts'] }, 'done').map(l => l.text)).toEqual([
      'Found 1 file',
      'app/x.ts',
    ])
    expect(outputLines('mcp__x__y', [{ type: 'text', text: 'hi' }], 'done')).toEqual([{ text: 'hi', color: 'text' }])
    expect(outputLines('Bash', 'stopped', 'interrupted')[0]?.text).toBe('Interrupted')
  })

  test('keeps only short input fields for the running list', () => {
    expect(brief({ file_path: 'a.ts', content: 'x'.repeat(10_000) })).toEqual({ file_path: 'a.ts' })
  })
})

describe('diffs', () => {
  const patch = [
    { oldStart: 9, oldLines: 4, newStart: 9, newLines: 4, lines: [' a', '-b', '-c', '+B', '+C', ' d'] },
    { oldStart: 99, oldLines: 2, newStart: 99, newLines: 3, lines: [' x', '+y\u0007', ' z'] },
  ]

  test('removed runs are the mod\'s, the rest are engine hunks with their own numbers', () => {
    const d = diffRuns(patch)
    expect(d.width).toBe(3)
    expect(d.runs).toEqual([
      { kind: 'kept', hunk: '@@ -9,1 +9,1 @@\n a' },
      { kind: 'removed', rows: [{ no: 10, code: 'b' }, { no: 11, code: 'c' }] },
      { kind: 'kept', hunk: '@@ -12,1 +10,3 @@\n+B\n+C\n d' },
      { kind: 'gap' },
      { kind: 'kept', hunk: '@@ -99,2 +99,3 @@\n x\n+y\n z' },
    ])
  })

  test('the engine keeps new files, staged edits and other tools', () => {
    expect(diffOf('Write', { type: 'create', structuredPatch: [] })).toBe(null)
    expect(diffOf('Edit', { staged: true, structuredPatch: patch })).toBe(null)
    expect(diffOf('Bash', { structuredPatch: patch })).toBe(null)
    expect(diffOf('Edit', { structuredPatch: patch })?.runs.length).toBe(5)
  })

  test('an Edit result draws removed lines in white on the removed background', async $ => {
    const ui = await $.ui.mount({
      plugin: 'readable-session',
      surface: 'terminal',
      component: 'ToolResult',
      props: { tool_use_id: 't1', tool: 'Edit', isErrored: false, output: { filePath: 'C:/dev/x.py', structuredPatch: patch } },
    })
    const removed = await ui.findAll({ type: 'Box', text: /-b$/ })
    expect(removed[0]?.props.backgroundColor).toBe('diffRemoved')
    const code = await ui.find({ type: 'Text', text: 'b' })
    expect(code?.props.color).toBe('text')
    expect(code?.props.dimColor).toBe(undefined)
    const kept = await ui.findAll({ type: 'Code' })
    expect(kept.map(k => k.props.format)).toEqual(['diff', 'diff', 'diff'])
    expect(kept[0]?.props.path).toBe('C:/dev/x.py')
  })
})

describe('bash diffs', () => {
  const hunks = [{ oldStart: 3, oldLines: 2, newStart: 3, newLines: 2, lines: ['-old', '+new', ' same'] }]
  const output = (files: unknown[]) => ({ stdout: 'done', stderr: '', bashEditDiff: { files } })

  test("a command that removed lines is the mod's; one that only added stays the engine's", () => {
    expect(bashDiffs(output([{ filePath: 'C:/dev/a.py', hunks }]))?.map(f => f.path)).toEqual(['C:/dev/a.py'])
    expect(bashDiffs(output([{ filePath: 'C:/dev/n.py', created: true, hunks: [{ oldStart: 0, oldLines: 0, newStart: 1, newLines: 1, lines: ['+x'] }] }]))).toBe(null)
    expect(bashDiffs({ stdout: 'hi' })).toBe(null)
  })

  test("the output stays the engine's, the diff below it has white removed lines", async ($, on) => {
    on('ui.render', async (_$: any, e: any) => {
      const { Text } = _$.ui.resolve(e)
      return <Text>{`ENGINE ${Object.keys(e.props.output).join(',')}`}</Text>
    })
    const ui = await $.ui.mount({
      plugin: 'readable-session',
      surface: 'terminal',
      component: 'ToolResult',
      props: { tool_use_id: 't2', tool: 'Bash', isErrored: false, output: output([{ filePath: 'C:/dev/a.py', hunks }]) },
    })
    const removed = await ui.findAll({ type: 'Box', text: /-old$/ })
    expect(removed[0]?.props.backgroundColor).toBe('diffRemoved')
    expect(await ui.find({ type: 'Text', text: 'ENGINE stdout,stderr' })).toBeTruthy()
    expect(await ui.find({ type: 'Text', text: 'C:/dev/a.py' })).toBeTruthy()
    expect((await ui.findAll({ type: 'Code' })).map(k => k.props.format)).toEqual(['diff'])
  })
})

describe('prompts', () => {
  test('pasted text shows without the tags Claude Code wraps it in', () => {
    expect(promptText('look:\n<pasted_content id="c2f9">\nline 1\n</pasted_content id="c2f9">\nthanks')).toBe(
      'look:\nline 1\nthanks',
    )
  })
})

describe('drawing on terminal', () => {
  test('your prompt is a compact labeled card', async $ => {
    const ui = await $.ui.mount({
      plugin: 'readable-session',
      surface: 'terminal',
      component: 'UserMessage',
      props: { text: 'make my prompts visible', origin: { kind: 'composer' }, isExpanded: true },
    })
    const card = await ui.find({ type: 'Box' })
    expect(card?.text ?? '').toContain('You prompted')
    expect(card?.text ?? '').toContain('make my prompts visible')
    expect(card?.props.borderColor).toBe('claude')
    expect(card?.props.marginY).toBe(undefined)
  })

  test('a command row is a bordered card headed by the command and its arguments', async ($, on) => {
    on('ui.render', async (_$: any, e: any) => {
      const { Text } = _$.ui.resolve(e)
      return <Text>{e.props.text}</Text>
    })
    const ui = await $.ui.mount({
      plugin: 'readable-session',
      surface: 'terminal',
      component: 'CommandOutput',
      props: { command: 'effort', args: 'high', text: 'Effort set to high', isErrored: false },
    })
    const card = await ui.find({ type: 'Box' })
    expect(card?.props.borderColor).toBe('claude')
    expect(card?.props.borderStyle).toBe('round')
    expect(card?.text ?? '').toContain('/effort high')
    expect(card?.text ?? '').toContain('Effort set to high')
  })

  test('a command without arguments shows just the command; a failed one has a red border', async ($, on) => {
    on('ui.render', async (_$: any, e: any) => {
      const { Text } = _$.ui.resolve(e)
      return <Text>{e.props.text}</Text>
    })
    const ok = await $.ui.mount({
      plugin: 'readable-session',
      surface: 'terminal',
      component: 'CommandOutput',
      props: { command: 'context', args: '', text: 'x', isErrored: false },
    })
    expect((await ok.find({ type: 'Box' }))?.text ?? '').toContain('/context')
    expect((await ok.find({ type: 'Box' }))?.text ?? '').not.toContain('/context ')
    const bad = await $.ui.mount({
      plugin: 'readable-session',
      surface: 'terminal',
      component: 'CommandOutput',
      props: { command: 'effort', args: 'bogus', text: 'Unknown effort', isErrored: true },
    })
    expect((await bad.find({ type: 'Box' }))?.props.borderColor).toBe('error')
  })

  test('a running tool row says what it does; a finished one, what it did', async $ => {
    const props = {
      tool_use_id: 't1',
      tool: 'Write',
      input: { file_path: 'C:/dev/app/main.py', content: 'print(1)' },
      isRunning: true,
      isErrored: false,
      isInterrupted: false,
    }
    const ui = await $.ui.mount({ plugin: 'readable-session', surface: 'terminal', component: 'ToolUse', props })
    const row = (await ui.find({ text: /Writing/ }))?.text ?? ''
    expect(row).toContain('app/main.py · Python')
    await ui.redraw({ ...props, isRunning: false, output: { type: 'create' } })
    const done = (await ui.find({ text: /Wrote/ }))?.text ?? ''
    expect(done).toContain('Wrote')
    expect(done).not.toContain('Writing')
  })

  test("an expanded group row is a card in the kind's tone, headed by the row, its output drawn by the mod", async ($, on) => {
    on('ui.render', async (_$: any, e: any) => {
      const { Text } = _$.ui.resolve(e)
      return <Text>ENGINE BLOCK</Text>
    })
    const call = {
      tool_use_id: 'g1',
      tool: 'Read',
      input: { file_path: 'C:/dev/app/main.py' },
      isRunning: false,
      isErrored: false,
      isInterrupted: false,
    }
    await $.ui.mount({
      plugin: 'readable-session',
      surface: 'terminal',
      component: 'ToolGroup',
      props: { calls: [call], isActive: false, isExpanded: true },
    })
    const ui = await $.ui.mount({
      plugin: 'readable-session',
      surface: 'terminal',
      component: 'ToolUse',
      props: { ...call, output: { type: 'text', file: { numLines: 40 } } },
    })
    const card = await ui.find({ type: 'Box' })
    expect(card?.props.borderStyle).toBe('round')
    expect(card?.props.borderColor).toBe(kindColor('read'))
    expect(card?.props.backgroundColor).toBe(undefined)
    expect(card?.text ?? '').toContain('app/main.py · Python')
    expect(card?.text ?? '').toContain('Read 40 lines')
    expect(card?.text ?? '').not.toContain('ENGINE BLOCK')
    await ui.redraw({ ...call, isErrored: true, output: '<tool_use_error>File does not exist.</tool_use_error>' })
    const bad = await ui.find({ type: 'Box' })
    expect(bad?.props.borderColor).toBe('error')
    expect(bad?.text ?? '').toContain('File does not exist.')
    expect(bad?.text ?? '').not.toContain('tool_use_error')
  })

  const DOWN = '\u{F0140}'
  const UP = '\u{F0143}'

  test('a row too wide is cut by the row: a down arrow marks the cut and the mark stays', async $ => {
    const props = {
      tool_use_id: 'w1',
      tool: 'Bash',
      input: { command: 'cd /c/dev/claude-setup/mods/readable-session && claude plugin validate . 2>&1 | grep -E "x"' },
      isRunning: false,
      isErrored: false,
      isInterrupted: false,
      output: { stdout: '' },
    }
    const viewport = { columns: 60, rows: 20, isFullscreen: true }
    const ui = await $.ui.mount({ plugin: 'readable-session', surface: 'terminal', component: 'ToolUse', props, viewport })
    const text = (await ui.find({ text: /Ran Bash/ }))?.text ?? ''
    expect(text).toContain(DOWN)
    expect(text).toContain('✓')
    expect([...text].length).toBeLessThanOrEqual(60 - 4)
    const short = await $.ui.mount({
      plugin: 'readable-session',
      surface: 'terminal',
      component: 'ToolUse',
      props: { ...props, input: { command: 'ls' } },
      viewport,
    })
    expect((await short.find({ text: /Ran Bash/ }))?.text ?? '').not.toContain(DOWN)
  })

  test('an expanded card header carries an up arrow', async ($, on) => {
    on('ui.render', async (_$: any, e: any) => {
      const { Text } = _$.ui.resolve(e)
      return <Text>ENGINE BLOCK</Text>
    })
    const call = { tool_use_id: 'u1', tool: 'Bash', input: { command: 'ls' }, isRunning: false, isErrored: false, isInterrupted: false }
    await $.ui.mount({
      plugin: 'readable-session',
      surface: 'terminal',
      component: 'ToolGroup',
      props: { calls: [call], isActive: false, isExpanded: true },
    })
    const ui = await $.ui.mount({
      plugin: 'readable-session',
      surface: 'terminal',
      component: 'ToolUse',
      props: { ...call, output: { stdout: 'a' } },
      viewport: { columns: 80, rows: 20, isFullscreen: true },
    })
    const header = (await ui.find({ text: /Ran Bash/ }))?.text ?? ''
    expect(header).toContain(UP)
    expect(header).not.toContain(DOWN)
  })
})

describe('drawing on desktop', () => {
  test('the engine draws its own rows (no Nerd Font glyphs there)', async ($, on) => {
    on('ui.render', async ($x: any, e: any) => {
      const { Text } = $x.ui.resolve(e)
      return <Text>ENGINE</Text>
    })
    const msg = await $.ui.mount({
      plugin: 'readable-session',
      surface: 'desktop',
      component: 'UserMessage',
      props: { text: 'make my prompts visible', origin: { kind: 'composer' }, isExpanded: true },
    })
    expect(await msg.find({ text: /You prompted/ })).toBe(undefined)
    const row = await $.ui.mount({
      plugin: 'readable-session',
      surface: 'desktop',
      component: 'ToolUse',
      props: {
        tool_use_id: 't1',
        tool: 'Write',
        input: { file_path: 'C:/dev/app/main.py', content: 'print(1)' },
        isRunning: true,
        isErrored: false,
        isInterrupted: false,
      },
    })
    expect(await row.find({ text: /Writing/ })).toBe(undefined)
  })
})
