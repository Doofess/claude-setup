import { describe, expect, mock, test } from 'claude-code/testing'

const BAND = {
  hasSurvey: false,
  isWorking: true,
  maxRows: 10,
  bodyColumns: 100,
  scroll: { bodyRows: 10, offset: 0 },
  view: {},
} as any

const band = ($: any) =>
  $.ui.mount({ plugin: 'readable-session', surface: 'terminal', component: 'AbovePrompt', props: BAND })

const rowsOf = async (ui: any) => (await ui.findAll({ type: 'Text' })).filter((t: any) => t.props.wrap === 'truncate-end')

describe('linger', () => {
  test('a fast call stays 2 s from its start, marked done, then drops', async ($, on) => {
    const clock = mock.clock(on)
    on('ui.render', async (_$: any, e: any) => {
      const { Text } = _$.ui.resolve(e)
      return <Text>ENGINE</Text>
    })
    on('tool.call', async () => ({ result: { stdout: '' } }) as any)
    await $.tool.call({ tool: 'Read', file_path: '/a/b.ts', tool_use_id: 'u1' } as any)
    await clock.settle()
    const ui = await band($)
    const row = (await rowsOf(ui))[0]?.text ?? ''
    expect(row).toContain('Read')
    expect(row).toContain('✓')
    expect(row).not.toContain('Reading')

    await clock.advance(1500)
    expect((await rowsOf(ui)).length).toBe(1)
    await clock.advance(600)
    expect(await ui.find({ text: /Read/ })).toBe(undefined)
  })

  test('survives turn.complete while young, and a failed call shows ✗', async ($, on) => {
    const clock = mock.clock(on)
    on('ui.render', async (_$: any, e: any) => {
      const { Text } = _$.ui.resolve(e)
      return <Text>ENGINE</Text>
    })
    on('turn.complete', async () => ({ text: '' }))
    on('tool.call', async () => ({ result: undefined, isError: true }) as any)
    await $.tool.call({ tool: 'Bash', command: 'false', tool_use_id: 'u1' } as any)
    await clock.settle()
    await $.turn.complete({ answer: '', durationMs: 1, isAborted: false, turnId: 'T1', reason: 'answer' } as any)
    const ui = await band($)
    const row = (await rowsOf(ui))[0]?.text ?? ''
    expect(row).toContain('Ran Bash')
    expect(row).toContain('✗')
    await clock.advance(2100)
    expect(await ui.find({ text: /Ran Bash/ })).toBe(undefined)
  })

  test('a call slower than the linger leaves at once', async ($, on) => {
    const clock = mock.clock(on)
    on('ui.render', async (_$: any, e: any) => {
      const { Text } = _$.ui.resolve(e)
      return <Text>ENGINE</Text>
    })
    on('tool.call', async () => {
      await clock.sleep(3000)
      return { result: { stdout: '' } } as any
    })
    const call = $.tool.call({ tool: 'Bash', command: 'sleep 3', tool_use_id: 'u1' } as any)
    await clock.advance(3100)
    await call
    const ui = await band($)
    expect(await ui.find({ text: /Ran Bash/ })).toBe(undefined)
  })

  test('running calls come before lingering ones', async ($, on) => {
    const clock = mock.clock(on)
    let n = 0
    on('tool.call', async (_$: any, e: any) => {
      if (e.tool_use_id === 'slow') return new Promise(() => {}) as any
      n++
      return { result: { stdout: '' } } as any
    })
    await $.tool.call({ tool: 'Glob', pattern: '*.md', tool_use_id: 'fast' } as any)
    void $.tool.call({ tool: 'Bash', command: 'npm test', tool_use_id: 'slow' } as any)
    await clock.settle()
    const rows = await rowsOf(await band($))
    expect(n).toBe(1)
    expect(rows[0]?.text).toContain('Running Bash')
    expect(rows[1]?.text).toContain('Found files')
  })
})

describe('folded ToolGroup', () => {
  const call = (id: string, over: any = {}) => ({
    tool_use_id: id,
    tool: 'Read',
    input: { file_path: `/a/${id}.ts` },
    isRunning: false,
    isErrored: false,
    isInterrupted: false,
    ...over,
  })
  const mountGroup = ($: any, calls: any[], isExpanded = false) =>
    $.ui.mount({
      plugin: 'readable-session',
      surface: 'terminal',
      component: 'ToolGroup',
      props: { calls, isActive: false, isExpanded },
    })

  test('draws one row per call with its mark', async $ => {
    const ui = await mountGroup($, [call('a'), call('b', { isErrored: true }), call('c', { isRunning: true })])
    const rows = await rowsOf(ui)
    expect(rows).toHaveLength(3)
    expect(rows[0]?.text).toContain('Read')
    expect(rows[0]?.text).toContain('✓')
    expect(rows[1]?.text).toContain('failed')
    expect(rows[2]?.text).toContain('Reading')
  })

  test('caps at six rows with +N more', async $ => {
    const ui = await mountGroup($, ['a', 'b', 'c', 'd', 'e', 'f', 'g', 'h'].map(id => call(id)))
    const rows = await rowsOf(ui)
    expect(rows).toHaveLength(7)
    expect(rows[6]?.text).toBe('+2 more')
  })

  test('an expanded group keeps the engine drawing', async ($, on) => {
    on('ui.render', async (_$: any, e: any) => {
      const { Text } = _$.ui.resolve(e)
      return <Text>ENGINE</Text>
    })
    const ui = await mountGroup($, [call('a')], true)
    expect((await ui.find({ text: /ENGINE/ }))?.text).toBe('ENGINE')
  })
})

describe('subagent model tag', () => {
  const mountAgent = ($: any) =>
    $.ui.mount({
      plugin: 'readable-session',
      surface: 'terminal',
      component: 'ToolUse',
      props: {
        tool_use_id: 'ag1',
        tool: 'Agent',
        input: { subagent_type: 'general-purpose', description: 'dig' },
        isRunning: true,
        isErrored: false,
        isInterrupted: false,
      },
    })

  test('grey when the call named a model', async ($, on) => {
    on('ui.render', async (_$: any, e: any) => {
      const { Text } = _$.ui.resolve(e)
      return <Text>ENGINE</Text>
    })
    on('agent.spawn', async () => ({ model: 'claude-sonnet-5-5', agentId: 'a1' }) as any)
    await $.agent.spawn({ prompt: 'x', description: 'dig', subagentType: 'general-purpose', model: 'sonnet', tool_use_id: 'ag1' } as any)
    const tag = (await (await mountAgent($)).findAll({ type: 'Text' })).find((t: any) => /sonnet/.test(t.text) && t.props.color)
    expect(tag?.text).toContain('sonnet')
    expect(tag?.props.color).toBe('subtle')
  })

  test('amber when it inherited Opus', async ($, on) => {
    on('ui.render', async (_$: any, e: any) => {
      const { Text } = _$.ui.resolve(e)
      return <Text>ENGINE</Text>
    })
    on('agent.spawn', async () => ({ model: 'claude-opus-5-5', agentId: 'a1' }) as any)
    await $.agent.spawn({ prompt: 'x', description: 'dig', subagentType: 'general-purpose', tool_use_id: 'ag1' } as any)
    const tag = (await (await mountAgent($)).findAll({ type: 'Text' })).find((t: any) => /opus/.test(t.text) && t.props.color)
    expect(tag?.text).toContain('no model set')
    expect(tag?.props.color).toBe('warning')
  })
})
