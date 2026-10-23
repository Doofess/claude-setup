import { expect, mock, test } from 'claude-code/testing'

import { clock, promptText } from '../hooks/register'

const MESSAGE = (requestId: string, text: string, origin: object = { kind: 'composer' }) =>
  ({
    plugin: 'session-cards',
    surface: 'terminal',
    component: 'UserMessage',
    requestId,
    props: { text, origin, isExpanded: false },
  }) as const

// Nothing sits beneath the plugin: these two hooks stand for the engine.
const engine = (on: Parameters<Parameters<typeof test>[1]>[1]) => {
  on('prompt.submit', (_, e) => ({ text: e.text }))
  on('ui.render', ($, e) => {
    const { Text } = $.ui.resolve(e)

    return <Text>engine</Text>
  })
}

const HEADER = '\uf007  You prompted'

test('a prompt is an accent card headed You prompted and the time', async ($, on) => {
  const time = mock.clock(on, { now: new Date(2026, 9, 23, 14, 32).getTime() })
  engine(on)

  await $.prompt.submit({ text: 'hello', wait: false })

  const ui = await $.ui.mount(MESSAGE('m1', 'hello'))
  const box = await ui.find({ type: 'Box' })
  expect(box?.props.borderColor).toBe('claude')
  expect(box?.props.borderStyle).toBe('round')

  const head = await ui.find({ type: 'Text', text: /You prompted/ })
  expect(head?.text).toBe(`${HEADER} · ${clock(time.now())}`)
  expect(head?.text).toMatch(/ · \d\d:\d\d$/)
  expect(head?.props.bold).toBe(true)
  expect(head?.props.color).toBe('claude')

  expect((await ui.find({ type: 'Text', text: /^hello$/ }))?.props.color).toBeUndefined()
  await ui.unmount()
})

test('a row with no recorded time has no clock', async ($, on) => {
  mock.clock(on)
  engine(on)

  const ui = await $.ui.mount(MESSAGE('m1', 'from before the mod loaded'))
  expect((await ui.find({ type: 'Text', text: /You prompted/ }))?.text).toBe(HEADER)
  await ui.unmount()
})

test('test_repeated_prompt_keeps_both_times', async ($, on) => {
  const time = mock.clock(on, { now: new Date(2026, 9, 23, 9, 5).getTime() })
  engine(on)

  const first = time.now()
  await $.prompt.submit({ text: 'x', wait: false })
  await time.advance(90 * 60 * 1000)
  const second = time.now()
  await $.prompt.submit({ text: 'x', wait: false })
  expect(clock(first)).not.toBe(clock(second))

  const one = await $.ui.mount(MESSAGE('m1', 'x'))
  const two = await $.ui.mount(MESSAGE('m2', 'x'))
  const head = async (ui: typeof one) => (await ui.find({ type: 'Text', text: /You prompted/ }))?.text

  expect(await head(one)).toBe(`${HEADER} · ${clock(first)}`)
  expect(await head(two)).toBe(`${HEADER} · ${clock(second)}`)

  // Drawing the first row again must not claim the next time.
  await one.unmount()
  const again = await $.ui.mount(MESSAGE('m1', 'x'))
  expect(await head(again)).toBe(`${HEADER} · ${clock(first)}`)
  await two.unmount()
  await again.unmount()
})

test('test_paste_wrapper_lines_are_hidden', () => {
  expect(promptText('see:\n<pasted_content id="a1">\nline\n</pasted_content id="a1">\nthanks')).toBe('see:\nline\nthanks')
  expect(promptText('plain')).toBe('plain')
})

test('the body shows the text without the wrapper lines', async ($, on) => {
  mock.clock(on)
  engine(on)

  const ui = await $.ui.mount(MESSAGE('m1', 'see:\n<pasted_content id="a1">\nline\n</pasted_content id="a1">\nthanks'))
  expect((await ui.find({ type: 'Text', text: /thanks/ }))?.text).toBe('see:\nline\nthanks')
  await ui.unmount()
})

test('clock is 24-hour local HH:MM', () => {
  expect(clock(new Date(2026, 9, 23, 14, 32).getTime())).toBe('14:32')
  expect(clock(new Date(2026, 9, 23, 0, 7).getTime())).toBe('00:07')
})

test("other origins and other surfaces are the engine's", async ($, on) => {
  mock.clock(on)
  engine(on)

  const note = await $.ui.mount(MESSAGE('n1', 'task done', { kind: 'task-notification' }))
  expect((await note.find({ type: 'Text', text: /engine/ }))?.text).toBe('engine')
  expect(await note.find({ type: 'Text', text: /You prompted/ })).toBeUndefined()
  await note.unmount()

  const desktop = await $.ui.mount({ ...MESSAGE('d1', 'hello'), surface: 'desktop' })
  expect((await desktop.find({ type: 'Text', text: /engine/ }))?.text).toBe('engine')
  expect(await desktop.find({ type: 'Text', text: /You prompted/ })).toBeUndefined()
  await desktop.unmount()
})

const COMMAND = (props: object = {}) =>
  ({
    plugin: 'session-cards',
    surface: 'terminal',
    component: 'CommandOutput',
    requestId: 'c1',
    props: { command: 'review', args: 'ultra', text: 'done', isErrored: false, ...props },
  }) as const

test('a slash command is a violet card headed by the command and its arguments', async ($, on) => {
  engine(on)

  const ui = await $.ui.mount(COMMAND())
  const box = await ui.find({ type: 'Box' })
  expect(box?.props.borderColor).toBe('permission')
  expect(box?.props.borderStyle).toBe('round')

  const head = await ui.find({ type: 'Text', text: /review/ })
  expect(head?.text).toBe('  /review ultra')
  expect(head?.props.bold).toBe(true)
  expect(head?.props.color).toBe('permission')

  // The engine's own output sits inside the card.
  expect((await ui.find({ type: 'Text', text: /^engine$/ }))?.text).toBe('engine')
  await ui.unmount()
})

test('a command with no arguments has no trailing space', async ($, on) => {
  engine(on)

  const ui = await $.ui.mount(COMMAND({ command: 'compact', args: '' }))
  expect((await ui.find({ type: 'Text', text: /compact/ }))?.text).toBe('  /compact')
  await ui.unmount()
})

test('an errored command is bordered in error', async ($, on) => {
  engine(on)

  const ui = await $.ui.mount(COMMAND({ isErrored: true }))
  expect((await ui.find({ type: 'Box' }))?.props.borderColor).toBe('error')
  expect((await ui.find({ type: 'Text', text: /review/ }))?.props.color).toBe('error')
  await ui.unmount()
})

test('a command the engine drew empty stays empty', async ($, on) => {
  on('ui.render', ($, e) => {
    const { Box } = $.ui.resolve(e)

    return <Box />
  })

  const ui = await $.ui.mount(COMMAND())
  expect((await ui.find({ type: 'Box' }))?.props.borderStyle).toBeUndefined()
  expect(await ui.find({ type: 'Text', text: /review/ })).toBeUndefined()
  await ui.unmount()
})
