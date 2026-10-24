import { expect, mock, test, type TestBody } from 'claude-code/testing'

import { fmtElapsed, turnLine } from '../hooks/register'

type Raise = Parameters<TestBody>[0]
type On = Parameters<TestBody>[1]

const AT = new Date(2026, 9, 24, 12, 34).getTime()

const ROW = (requestId: string, props: object = {}, extra: object = {}) =>
  ({
    plugin: 'session-cards',
    surface: 'terminal',
    component: 'TurnDuration',
    requestId,
    props: { word: 'Brewed', durationMs: 1_016_000, isExpanded: false, ...props },
    ...extra,
  }) as const

const NOTE = (requestId: string, id: string) =>
  ({
    plugin: 'session-cards',
    surface: 'terminal',
    component: 'UserMessage',
    requestId,
    props: { text: 'done', origin: { kind: 'task-notification' }, isExpanded: false, task: { id, status: 'completed' } },
  }) as const

// Nothing sits beneath the plugin: these hooks stand for the engine.
// A call whose tool_use_id starts with `b` went to the background and answers with that id as the task id, unless `bash` says otherwise.
const engine = (on: On, bash?: object) => {
  on('turn.complete', () => ({ text: '' }))
  on('tool.call', { tool: 'Bash' }, (_, e) => {
    const call = e as { tool_use_id: string }
    const plain = { stdout: '', stderr: '', interrupted: false }

    return { ref: 'r', text: '', result: bash ?? (call.tool_use_id.startsWith('b') ? { ...plain, backgroundTaskId: call.tool_use_id } : plain) } as never
  })
  on('tool.call', { tool: 'TaskStop' }, (_, e) => ({ ref: 'r', text: '', result: { message: 'stopped', task_id: (e as { task_id?: string }).task_id ?? '', task_type: 'shell' } }) as never)
  on('ui.render', ($, e) => {
    const { Text } = $.ui.resolve(e)

    return <Text>engine</Text>
  })
}

const finish = ($: Raise, durationMs: number, agentId?: string) =>
  $.turn.complete({ answer: 'done', durationMs, isAborted: false, turnId: 't1', reason: 'answer', agentId })

const background = ($: Raise, id: string) => $.tool.call({ tool: 'Bash', tool_use_id: id, command: 'sleep 120', run_in_background: true } as never)

const runs = async (ui: { findAll: (q: { type: 'Text' }) => Promise<{ text: string; props: Record<string, unknown> }[]> }) =>
  (await ui.findAll({ type: 'Text' })).filter(t => t.text.trim() !== '')

/** The row's runs as one string (`✻Brewed for 4s · done 12:34 PM`), or `engine`. */
const line = async (ui: Parameters<typeof runs>[0]) => (await ui.findAll({ type: 'Text' })).map(t => t.text).join('')

test('a finished turn is coloured', async ($, on) => {
  mock.clock(on, { now: AT })
  engine(on)
  await finish($, 1_016_000)

  const ui = await $.ui.mount(ROW('r1'))
  const parts = await runs(ui)
  expect(parts.map(t => t.text)).toEqual(['✻', 'Brewed for', '16m 56s', ' · done 12:34 PM'])
  expect(parts[0]?.props.color).toBe('claude')
  expect(parts[1]?.props.dimColor).toBe(true)
  expect(parts[2]?.props.bold).toBe(true)
  expect(parts[2]?.props.color).toBe('text')
  expect(parts[3]?.props.color).toBe('success')
  expect(await ui.find({ type: 'Text', text: /still running/ })).toBeUndefined()

  // The ✻ sits in a cell two wide, in a row a blank line below the reply, as the engine lays it out.
  expect((await ui.find({ type: 'Box' }))?.props.flexDirection).toBe('row')
  expect((await ui.find({ type: 'Box' }))?.props.marginTop).toBe(1)
  await ui.unmount()
})

test("a turn that ended with a shell running is the engine's line", async ($, on) => {
  // The mod only learns a shell ended when its notification row is drawn, which can come after the turn:
  // the engine knows the real count, so its line stands.
  mock.clock(on, { now: AT })
  engine(on)
  await background($, 'b1')
  await finish($, 5_000)

  const ui = await $.ui.mount(ROW('r1', { durationMs: 5_000 }))
  expect(await line(ui)).toBe('engine')
  await ui.unmount()
})

test("a turn that ended while a background agent ran is the engine's line", async ($, on) => {
  // The engine draws `Waiting for 1 background agent to finish` there, and leaves waitingFor out when its counts differ.
  mock.clock(on, { now: AT })
  engine(on)
  on('agent.spawn', () => ({ model: 'claude-sonnet-5-5', agentId: 'a1' }))
  await $.agent.spawn({ prompt: 'p', description: 'd', subagentType: 'worker', tool_use_id: 'tu-a', background: true } as never)
  await finish($, 5_000)

  const waiting = await $.ui.mount(ROW('r1', { durationMs: 5_000 }))
  expect(await line(waiting)).toBe('engine')
  await waiting.unmount()

  // Once it has finished, the line is the mod's again.
  await finish($, 6_000, 'a1')
  const done = await $.ui.mount(ROW('r1', { durationMs: 5_000 }))
  expect(await line(done)).toBe('✻Brewed for 5s · done 12:34 PM')
  await done.unmount()
})

test('no record falls back', async ($, on) => {
  mock.clock(on, { now: AT })
  engine(on)

  const ui = await $.ui.mount(ROW('r1'))
  expect((await runs(ui)).map(t => t.text)).toEqual(['engine'])
  await ui.unmount()
})

test('expanded and waiting fall back', async ($, on) => {
  mock.clock(on, { now: AT })
  engine(on)
  await finish($, 1_016_000)

  const expanded = await $.ui.mount(ROW('r1', { isExpanded: true }))
  expect((await runs(expanded)).map(t => t.text)).toEqual(['engine'])
  await expanded.unmount()

  const waiting = await $.ui.mount(ROW('r2', { waitingFor: 'a shell' }))
  expect((await runs(waiting)).map(t => t.text)).toEqual(['engine'])
  await waiting.unmount()

  const desktop = await $.ui.mount({ ...ROW('r3'), surface: 'desktop' })
  expect((await runs(desktop)).map(t => t.text)).toEqual(['engine'])
  await desktop.unmount()
})

test("a subagent's end stores nothing", async ($, on) => {
  mock.clock(on, { now: AT })
  engine(on)
  await finish($, 1_016_000, 'a1')

  const ui = await $.ui.mount(ROW('r1'))
  expect(await line(ui)).toBe('engine')
  await ui.unmount()

  // The main loop's own end of the same length is the one the row draws.
  await finish($, 1_016_000)
  const again = await $.ui.mount(ROW('r2'))
  expect(await line(again)).toBe('✻Brewed for 16m 56s · done 12:34 PM')
  await again.unmount()
})

test('equal durations pair in order', async ($, on) => {
  const time = mock.clock(on, { now: AT })
  engine(on)
  await finish($, 3000)
  await time.advance(60 * 60 * 1000)
  await finish($, 3000)

  const first = await $.ui.mount(ROW('r1', { durationMs: 3000 }))
  const second = await $.ui.mount(ROW('r2', { durationMs: 3000 }))
  const done = async (ui: typeof first) => (await ui.find({ type: 'Text', text: /done/ }))?.text
  expect(await done(first)).toBe(' · done 12:34 PM')
  expect(await done(second)).toBe(' · done 1:34 PM')

  // Drawing the first row again keeps its record and takes no other.
  await first.unmount()
  const again = await $.ui.mount(ROW('r1', { durationMs: 3000 }))
  expect(await done(again)).toBe(' · done 12:34 PM')

  // A third row has no record left.
  const third = await $.ui.mount(ROW('r3', { durationMs: 3000 }))
  expect((await runs(third)).map(t => t.text)).toEqual(['engine'])
  await again.unmount()
  await second.unmount()
  await third.unmount()
})

test('a shell that ends inside its turn is not counted, then or later', async ($, on) => {
  mock.clock(on, { now: AT })
  engine(on)
  await background($, 'b1')

  // The shell's notification is drawn while the turn still runs.
  const note = await $.ui.mount(NOTE('n1', 'b1'))
  await note.unmount()
  await finish($, 4000)
  await finish($, 5000)

  for (const [id, durationMs] of [['r1', 4000], ['r2', 5000]] as const) {
    const ui = await $.ui.mount(ROW(id, { durationMs }))
    expect(await ui.find({ type: 'Text', text: /still running/ })).toBeUndefined()
    expect((await ui.find({ type: 'Text', text: /done/ }))?.text).toBe(' · done 12:34 PM')
    await ui.unmount()
  }
})

test('stopping a shell ends it', async ($, on) => {
  mock.clock(on, { now: AT })
  engine(on)
  await background($, 'b1')
  await $.tool.call({ tool: 'TaskStop', tool_use_id: 'tu-s', task_id: 'b1' } as never)
  await finish($, 4000)

  const ui = await $.ui.mount(ROW('r1', { durationMs: 4000 }))
  expect(await line(ui)).toBe('✻Brewed for 4s · done 12:34 PM')
  await ui.unmount()
})

test('a call that did not go to the background is not a running shell', async ($, on) => {
  mock.clock(on, { now: AT })
  engine(on)
  await $.tool.call({ tool: 'Bash', tool_use_id: 'tu-f', command: 'ls' } as never)
  await finish($, 4000)

  const ui = await $.ui.mount(ROW('r1', { durationMs: 4000 }))
  expect(await line(ui)).toBe('✻Brewed for 4s · done 12:34 PM')
  await ui.unmount()
})

test('a call that went to the background by ctrl+b is a running shell', async ($, on) => {
  mock.clock(on, { now: AT })
  engine(on, { stdout: '', stderr: '', interrupted: false, backgroundTaskId: 'b9', backgroundedByUser: true })
  await $.tool.call({ tool: 'Bash', tool_use_id: 'tu-c', command: 'sleep 120' } as never)
  await finish($, 4000)

  const ui = await $.ui.mount(ROW('r1', { durationMs: 4000 }))
  expect(await line(ui)).toBe('engine')
  await ui.unmount()
})

test('only the last 200 records are kept, and a row keeps its record when the oldest drop', async ($, on) => {
  const time = mock.clock(on, { now: AT })
  engine(on)

  for (let i = 0; i < 205; i++) {
    await finish($, 1000 + i)
    await time.advance(60_000)
  }

  const dropped = await $.ui.mount(ROW('r0', { durationMs: 1004 }))
  expect(await line(dropped)).toBe('engine')
  await dropped.unmount()

  const oldest = await $.ui.mount(ROW('r1', { durationMs: 1005 }))
  expect(await line(oldest)).toBe('✻Brewed for 1s · done 12:39 PM')
  await oldest.unmount()
  const next = await $.ui.mount(ROW('r2', { durationMs: 1006 }))
  expect(await line(next)).toBe('✻Brewed for 1s · done 12:40 PM')
  await next.unmount()

  // One more turn drops the oldest record from the front: r2 still reads its own, r1's is gone.
  await finish($, 9000)
  const again = await $.ui.mount(ROW('r2', { durationMs: 1006 }))
  expect(await line(again)).toBe('✻Brewed for 1s · done 12:40 PM')
  await again.unmount()
  const gone = await $.ui.mount(ROW('r1', { durationMs: 1005 }))
  expect(await line(gone)).toBe('engine')
  await gone.unmount()
})

test('turnLine holds the words', () => {
  expect(turnLine({ seq: 0, durationMs: 1_016_000, endedAt: AT, shells: 0 })).toEqual({ duration: fmtElapsed(1_016_000), done: '12:34 PM' })
})
