import { describe, expect, test } from 'claude-code/testing'

import { brief, describeTool, kindColor, outputLines } from '../hooks/register.tsx'

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
    expect(diff.map(l => l.color)).toEqual(['subtle', 'diffRemoved', 'diffAdded'])
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
