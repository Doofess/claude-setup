import { expect, mock, test } from 'claude-code/testing'

import { effortColour, fmtElapsed, fmtTokens, modelColour } from '../hooks/register'

type On = Parameters<Parameters<typeof test>[1]>[1]

test('modelColour names the family colour', () => {
  expect(modelColour('claude-opus-5-5')).toBe('magenta')
  expect(modelColour('Sonnet')).toBe('blue')
  expect(modelColour('haiku')).toBe('cyan')
  expect(modelColour('claude-fable-5-1')).toBe('yellowBright')
  expect(modelColour('Mythos')).toBe('greenBright')
  expect(modelColour('other')).toBeUndefined()
})

test('effortColour names the level colour', () => {
  expect(effortColour('low')).toBe('green')
  expect(effortColour('medium')).toBe('yellow')
  expect(effortColour('high')).toBe('red')
  expect(effortColour('xhigh')).toBe('magentaBright')
  expect(effortColour('max')).toBe('whiteBright')
  expect(effortColour('7')).toBeUndefined()
})

test('fmtElapsed', () => {
  expect(fmtElapsed(0)).toBe('0s')
  expect(fmtElapsed(48_000)).toBe('48s')
  expect(fmtElapsed(60_000)).toBe('1m 0s')
  expect(fmtElapsed(12 * 60_000 + 5_000)).toBe('12m 5s')
  expect(fmtElapsed(62 * 60_000)).toBe('1h 2m')
})

test('fmtTokens', () => {
  expect(fmtTokens(950)).toBe('950')
  expect(fmtTokens(72_000)).toBe('72k')
  expect(fmtTokens(1_234_567)).toBe('1.2M')
})

const ROW = (toolUseId: string, props: object = {}, extra: object = {}) =>
  ({
    plugin: 'session-cards',
    surface: 'terminal',
    component: 'ToolUse',
    requestId: toolUseId,
    props: {
      tool_use_id: toolUseId,
      tool: 'Agent',
      input: { description: 'Implement Task 1', subagent_type: 'worker' },
      isRunning: true,
      isErrored: false,
      isInterrupted: false,
      ...props,
    },
    ...extra,
  }) as const

// The Agent call's tool_use_id: the kit does not fill one, so the test gives it.
const TU = 'tu1'

// Nothing sits beneath the plugin: these hooks stand for the engine.
const engine = (on: On, stepResult: { toolUses?: { name: string; input: unknown }[]; usage?: object } = {}) => {
  on('session.cwd', () => ({ value: 'C:/dev' }))
  on('agent.spawn', () => ({ model: 'claude-sonnet-5-5', agentId: 'a1' }))
  on('turn.step', async function* () {
    return {
      turnId: 'u1',
      index: 0,
      answer: '',
      toolUses: stepResult.toolUses ?? [],
      stopReason: 'end_turn',
      usage: {
        input_tokens: 40_000,
        output_tokens: 32_000,
        cache_read_input_tokens: 0,
        cache_creation_input_tokens: 0,
        model: 'claude-sonnet-5-5',
        ...stepResult.usage,
      },
    } as never
  })
  on('turn.complete', () => ({ text: '' }))
  on('ui.render', ($, e) => {
    const { Text } = $.ui.resolve(e)

    return <Text>engine</Text>
  })

}

type Raise = Parameters<Parameters<typeof test>[1]>[0]

const spawn = ($: Raise, background = false) =>
  $.agent.spawn({
    prompt: 'Do Task 1',
    description: 'Implement Task 1',
    subagentType: 'worker',
    tool_use_id: TU,
    background,
  } as never)

const step = async ($: Raise, agentId: string) => {
  for await (const _ of $.turn.step({ turnId: 'u1', index: 0, model: 'claude-sonnet-5-5', effort: 'high', messageCount: 1, agentId })) {
    // the chunks are the engine's; the hook reads the result
  }
}

const finish = ($: Raise, agentId: string) =>
  $.turn.complete({ answer: 'done', durationMs: 1, isAborted: false, turnId: 'u1', reason: 'answer', agentId })

const line = async (ui: { findAll: (q: { type: 'Text' }) => Promise<{ text: string }[]> }) =>
  (await ui.findAll({ type: 'Text' })).map(t => t.text).join('')

test('test_agent_row_shows_type_model_effort_and_action', async ($, on) => {
  const time = mock.clock(on)
  engine(on, { toolUses: [{ name: 'Grep', input: { pattern: 'cwd', path: 'reference.md' } }] })
  on('session.start', (_, e) => ({ cwd: e.cwd }))
  await $.session.start({ cwd: '/', surface: 'terminal', isInteractive: true })

  const { agentId } = await spawn($)
  await step($, agentId as string)
  await time.advance(48_000)

  const ui = await $.ui.mount(ROW(TU))
  expect(await line(ui)).toBe('\uf0c0 Running worker · Sonnet · high  Searching cwd in reference.md   48s · 72k')
  expect((await ui.find({ type: 'Box' }))?.props.flexDirection).toBe('row')

  const verb = await ui.find({ type: 'Text', text: /^Running$/ })
  expect(verb?.props.bold).toBe(true)
  expect(verb?.props.color).toBe('text')
  expect((await ui.find({ type: 'Text', text: /Sonnet/ }))?.props.color).toBe('blue')
  expect((await ui.find({ type: 'Text', text: /^high$/ }))?.props.color).toBe('red')

  for (const t of await ui.findAll({ type: 'Text' })) {
    if (!/^(Sonnet|high)$/.test(t.text)) {
      expect(t.props.color).toBe('text')
    }
  }

  // The row redraws as time passes.
  await time.advance(12_000)
  expect(await line(ui)).toMatch(/ {3}1m 0s · 72k$/)
  await ui.unmount()
})

test('before any step or call the row shows the description and no effort', async ($, on) => {
  mock.clock(on)
  engine(on)

  await spawn($)

  const ui = await $.ui.mount(ROW(TU))
  expect(await line(ui)).toBe('\uf0c0 Running worker · Sonnet  Implement Task 1   0s · 0')
  await ui.unmount()
})

test('test_finished_agent_row', async ($, on) => {
  const time = mock.clock(on)
  engine(on)
  on('session.start', (_, e) => ({ cwd: e.cwd }))
  await $.session.start({ cwd: '/', surface: 'terminal', isInteractive: true })

  const { agentId } = await spawn($)
  await step($, agentId as string)
  await time.advance(48_000)
  await finish($, agentId as string)
  await time.advance(30_000)

  const done = await $.ui.mount(ROW(TU, { isRunning: false }))
  expect(await line(done)).toBe('\uf0c0 Ran worker · Sonnet · high  done   48s · 72k')
  expect((await done.find({ type: 'Text', text: /^Ran$/ }))?.props.bold).toBe(true)
  await done.unmount()

  const failed = await $.ui.mount(ROW(TU, { isRunning: false, isErrored: true }))
  expect(await line(failed)).toBe('\uf0c0 Ran worker · Sonnet · high  done ✗   48s · 72k')
  expect((await failed.find({ type: 'Text', text: /✗/ }))?.props.color).toBe('error')
  await failed.unmount()

  const stopped = await $.ui.mount(ROW(TU, { isRunning: false, isInterrupted: true }))
  expect(await line(stopped)).toBe('\uf0c0 Ran worker · Sonnet · high  done (stopped)   48s · 72k')
  expect((await stopped.find({ type: 'Text', text: /stopped/ }))?.props.color).toBe('text')
  await stopped.unmount()
})

test('events of an agent the mod never saw spawn change nothing', async ($, on) => {
  mock.clock(on)
  engine(on)

  await spawn($)
  await step($, 'unknown')
  await finish($, 'unknown')

  const ui = await $.ui.mount(ROW(TU))
  expect(await line(ui)).toBe('\uf0c0 Running worker · Sonnet  Implement Task 1   0s · 0')
  await ui.unmount()
})

test('test_unknown_agent_row_shows_the_description', async ($, on) => {
  engine(on)

  const running = await $.ui.mount(ROW('never-seen'))
  expect(await line(running)).toBe('\uf0c0 Running worker  Implement Task 1')
  expect((await running.find({ type: 'Text', text: /^Running$/ }))?.props.bold).toBe(true)
  await running.unmount()

  const done = await $.ui.mount(ROW('never-seen', { isRunning: false, isErrored: true }))
  expect(await line(done)).toBe('\uf0c0 Ran worker  Implement Task 1')
  await done.unmount()
})

test('test_other_surfaces_and_expanded_rows_pass', async ($, on) => {
  engine(on)

  const same = async (mount: Parameters<typeof $.ui.mount>[0]) => {
    const ui = await $.ui.mount(mount)
    const own = await ui.find({ type: 'Text', text: /^engine$/ })
    const row = await ui.find({ type: 'Text', text: /Ran|Running/ })
    await ui.unmount()

    return own?.text === 'engine' && row === undefined
  }

  expect(await same(ROW('never-seen', { isExpanded: true }))).toBe(true)
  expect(await same({ ...ROW('never-seen'), surface: 'desktop' })).toBe(true)
  expect(await same(ROW('never-seen', { tool: 'Task' }))).toBe(true)
  expect(await same(ROW('never-seen', { isExpanded: false }))).toBe(false)
})

test('the action comes from the last tool use of the step', async ($, on) => {
  mock.clock(on)
  engine(on, {
    toolUses: [
      { name: 'Read', input: { file_path: 'C:/dev/a.md' } },
      { name: 'Grep', input: { pattern: 'cwd', path: 'reference.md' } },
    ],
  })
  on('session.start', (_, e) => ({ cwd: e.cwd }))
  await $.session.start({ cwd: '/', surface: 'terminal', isInteractive: true })

  const { agentId } = await spawn($)
  await step($, agentId as string)

  const ui = await $.ui.mount(ROW(TU))
  expect(await line(ui)).toMatch(/ {2}Searching cwd in reference\.md {3}/)
  await ui.unmount()
})

test('the token figure counts cache reads and writes', async ($, on) => {
  mock.clock(on)
  engine(on, {
    usage: { input_tokens: 1000, cache_read_input_tokens: 60_000, cache_creation_input_tokens: 5000, output_tokens: 6000 },
  })

  const { agentId } = await spawn($)
  await step($, agentId as string)

  const ui = await $.ui.mount(ROW(TU))
  expect(await line(ui)).toMatch(/ · 72k$/)
  await ui.unmount()
})

test('a background agent stays running while its row is not', async ($, on) => {
  mock.clock(on)
  engine(on)

  await spawn($, true)

  const ui = await $.ui.mount(ROW(TU, { isRunning: false }))
  const text = await line(ui)
  expect(text).toMatch(/^ Running worker/)
  expect(text).not.toContain('done')
  await ui.unmount()
})

test('a foreground agent whose row stopped running is finished, and its time stays fixed', async ($, on) => {
  const time = mock.clock(on)
  engine(on)

  await spawn($)
  await time.advance(5000)

  const first = await $.ui.mount(ROW(TU, { isRunning: false }))
  expect(await line(first)).toMatch(/^ Ran worker .* done {3}5s · /)
  await first.unmount()

  await time.advance(10_000)

  const second = await $.ui.mount(ROW(TU, { isRunning: false }))
  expect(await line(second)).toMatch(/ done {3}5s · /)
  await second.unmount()
})
