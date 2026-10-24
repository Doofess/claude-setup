import { expect, test, type TestBody } from 'claude-code/testing'

import { describeTool, rowText } from '../hooks/register'

const TOOL = (tool: string, input: unknown, props: object = {}, extra: object = {}) =>
  ({
    plugin: 'session-cards',
    surface: 'terminal',
    component: 'ToolUse',
    requestId: 't1',
    props: { tool_use_id: 't1', tool, input, isRunning: false, isErrored: false, isInterrupted: false, ...props },
    ...extra,
  }) as const

// Nothing sits beneath the plugin: this hook stands for the engine.
const engine = (on: Parameters<TestBody>[1]) => {
  on('session.cwd', () => ({ value: 'C:/dev' }))
  on('ui.render', ($, e) => {
    const { Text } = $.ui.resolve(e)

    return <Text>engine</Text>
  })
}

const BASH = { command: 'git status', description: 'Show status' }

test('describeTool names each tool in plain words', () => {
  expect(describeTool('Bash', BASH, 'C:/dev')).toEqual({ icon: '\uf120', verb: ['Running', 'Ran'], detail: 'Show status' })
  expect(describeTool('Bash', { command: 'git status\nmore' }, 'C:/dev').detail).toBe('git status')
  expect(describeTool('PowerShell', { command: 'ls' }, 'C:/dev')).toEqual({ icon: '\uf120', verb: ['Running', 'Ran'], detail: 'ls' })
  expect(describeTool('Edit', { file_path: 'C:/dev/a/b.py' }, 'C:/dev')).toEqual({ icon: '\uf040', verb: ['Editing', 'Edited'], detail: 'a/b.py' })
  expect(describeTool('Edit', { file_path: 'C:\\dev\\a\\b.py' }, 'C:\\dev').detail).toBe('a/b.py')
  expect(describeTool('MultiEdit', { file_path: 'D:\\other\\b.py' }, 'C:/dev').detail).toBe('D:/other/b.py')
  expect(describeTool('Write', { file_path: 'C:/dev/n.md' }, 'C:/dev')).toEqual({ icon: '\uf15c', verb: ['Writing', 'Wrote'], detail: 'n.md' })
  expect(describeTool('NotebookEdit', { notebook_path: 'C:/dev/n.ipynb' }, 'C:/dev')).toEqual({ icon: '\uf15c', verb: ['Editing', 'Edited'], detail: 'n.ipynb' })
  expect(describeTool('Read', { file_path: 'C:/dev/x/y.ts' }, 'C:/dev')).toEqual({ icon: '\uf0f6', verb: ['Reading', 'Read'], detail: 'x/y.ts' })
  expect(describeTool('Grep', { pattern: 'foo', path: 'src' }, 'C:/dev')).toEqual({ icon: '\uf002', verb: ['Searching', 'Searched'], detail: 'foo in src' })
  expect(describeTool('Glob', { pattern: '**/*.ts' }, 'C:/dev').detail).toBe('**/*.ts')
  expect(describeTool('Skill', { skill: 'plugin-authoring' }, 'C:/dev')).toEqual({ icon: '\uf0e7', verb: ['Using skill', 'Used skill'], detail: 'plugin-authoring' })
  expect(describeTool('AskUserQuestion', { questions: [{ question: 'Which?' }] }, 'C:/dev')).toEqual({ icon: '\uf059', verb: ['Asking you', 'Asked you'], detail: 'Which?' })
  expect(describeTool('WebFetch', { url: 'https://a.b/c' }, 'C:/dev')).toEqual({ icon: '\uf0ac', verb: ['Fetching', 'Fetched'], detail: 'https://a.b/c' })
  expect(describeTool('WebSearch', { query: 'cats' }, 'C:/dev')).toEqual({ icon: '\uf0ac', verb: ['Searching', 'Searched'], detail: 'cats' })
  expect(describeTool('mcp__plugin_context7_context7__query-docs', {}, 'C:/dev')).toEqual({ icon: '\uf1e6', verb: ['Calling', 'Called'], detail: 'plugin_context7_context7 query-docs' })
  expect(describeTool('Mystery', { n: 3, s: 'x'.repeat(80), t: 'short' }, 'C:/dev')).toEqual({ icon: '\uf111', verb: ['Using', 'Used'], detail: 'Mystery short' })
  expect(describeTool('Mystery', null, 'C:/dev').detail).toBe('Mystery')
})

test('describeTool survives input that is not the expected shape', () => {
  expect(describeTool('Bash', undefined, 'C:/dev').detail).toBe('')
  expect(describeTool('Read', {}, 'C:/dev').detail).toBe('')
  expect(describeTool('AskUserQuestion', { questions: [] }, 'C:/dev').detail).toBe('')
})

test('rowText: words per state', () => {
  const d = describeTool('Bash', BASH, 'C:/dev')

  expect(rowText(d, 'running', 80)).toBe('\uf120 Running Show status')
  expect(rowText(d, 'done', 80)).toBe('\uf120 Ran Show status')
  expect(rowText(d, 'failed', 80)).toBe('\uf120 Ran Show status ✗')
  expect(rowText(d, 'stopped', 80)).toBe('\uf120 Ran Show status (stopped)')
})

test('test_long_command_is_cut_to_the_row', () => {
  const d = describeTool('Bash', { command: 'a'.repeat(200) + '\nsecond' }, 'C:/dev')

  expect(rowText(d, 'done', 40).length).toBeLessThanOrEqual(40)
  expect(rowText(d, 'done', 40).endsWith('…')).toBe(true)
  expect(rowText(d, 'done', 40)).not.toContain('second')
})

test('a running row and a done row', async ($, on) => {
  engine(on)

  const running = await $.ui.mount(TOOL('Bash', BASH, { isRunning: true }))
  const box = await running.find({ type: 'Box' })
  expect(box?.props.flexDirection).toBe('row')
  expect((await running.find({ type: 'Text', text: /^\uf120 $/ }))?.props.color).toBe('text')

  const verb = await running.find({ type: 'Text', text: /^Running$/ })
  expect(verb?.props.bold).toBe(true)
  expect(verb?.props.color).toBe('text')
  expect((await running.find({ type: 'Text', text: /Show status/ }))?.props.color).toBe('text')
  expect(await running.find({ type: 'Text', text: /✗|stopped/ })).toBeUndefined()
  await running.unmount()

  const done = await $.ui.mount(TOOL('Bash', BASH))
  const ran = await done.find({ type: 'Text', text: /^Ran$/ })
  expect(ran?.props.bold).toBe(true)
  expect(ran?.props.color).toBe('text')
  expect(await done.find({ type: 'Text', text: /^Running$/ })).toBeUndefined()
  await done.unmount()
})

test('the detail is cut to the viewport width', async ($, on) => {
  engine(on)

  const ui = await $.ui.mount(TOOL('Bash', { command: 'b'.repeat(300) }, {}, { viewport: { columns: 50, rows: 20 } }))
  const detail = await ui.find({ type: 'Text', text: /b{5}/ })
  expect(detail?.text.endsWith('…')).toBe(true)
  expect(detail?.text.length).toBeLessThan(50)
  await ui.unmount()
})

test('test_failed_call_adds_a_mark', async ($, on) => {
  engine(on)

  const failed = await $.ui.mount(TOOL('Bash', BASH, { isErrored: true }))
  const mark = await failed.find({ type: 'Text', text: /✗/ })
  expect(mark?.text).toBe(' ✗')
  expect(mark?.props.color).toBe('error')
  expect((await failed.find({ type: 'Text', text: /^Ran$/ }))?.props.color).toBe('text')
  await failed.unmount()

  const stopped = await $.ui.mount(TOOL('Bash', BASH, { isInterrupted: true }))
  const note = await stopped.find({ type: 'Text', text: /stopped/ })
  expect(note?.text).toBe(' (stopped)')
  expect(note?.props.color).toBe('text')
  await stopped.unmount()
})

test("expanded rows, tasks and other surfaces are the engine's", async ($, on) => {
  engine(on)

  const same = async (mount: Parameters<typeof $.ui.mount>[0]) => {
    const ui = await $.ui.mount(mount)
    const own = await ui.find({ type: 'Text', text: /^engine$/ })
    const row = await ui.find({ type: 'Text', text: /Ran|Running/ })
    await ui.unmount()

    return own?.text === 'engine' && row === undefined
  }

  expect(await same(TOOL('Bash', BASH, { isExpanded: true }))).toBe(true)
  expect(await same(TOOL('Task', { description: 'dig' }))).toBe(true)
  expect(await same({ ...TOOL('Bash', BASH), surface: 'desktop' })).toBe(true)
  expect(await same(TOOL('Bash', BASH, { isExpanded: false }))).toBe(false)
})
