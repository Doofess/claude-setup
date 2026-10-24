import { expect, mock, test, type TestBody } from 'claude-code/testing'

type On = Parameters<TestBody>[1]

const HINT = '? for shortcuts'
const FILE = 'C:/Users/me/.claude/statusbar-overflow/s1.json'

const HINT_ROW = (hint: string, columns: number, extra: object = {}) =>
  ({
    plugin: 'session-cards',
    surface: 'terminal',
    component: 'PromptHint',
    requestId: 'h1',
    props: { isDraft: false, isWorking: false, hint },
    viewport: { columns, rows: 30 },
    ...extra,
  }) as const

const SHIELD = '\u{F0BC5}'

const span = (text: string, colour: string | null = null, bold = false) => ({ text, colour, bold })

// Nothing sits beneath the plugin: these hooks stand for the engine, the
// session id and the one file the status bar wrote (null: there is none).
const engine = (
  on: On,
  file: string | null | (() => string | null),
  env: Record<string, string> = { HOME: 'C:/Users/me' },
) => {
  mock.env(on, env)
  on('session.id', () => ({ value: 's1' }))
  on('fs.read', (_, e) => {
    const text = typeof file === 'function' ? file() : file

    if (text === null || e.path.replace(/\\/g, '/') !== FILE) {
      throw new Error('ENOENT')
    }

    return { value: text }
  })
  on('ui.render', ($, e) => {
    const { Text } = $.ui.resolve(e)

    return <Text>{`engine ${e.props.hint}`}</Text>
  })
}

// The row is one Text holding the hint and the pieces; its text is the whole line.
const line = async (ui: { findAll: (q: { type: 'Text' }) => Promise<{ text: string }[]> }) =>
  (await ui.findAll({ type: 'Text' }))[0]?.text

test('test_overflow_is_drawn_after_the_hint', async ($, on) => {
  engine(on, JSON.stringify({ written_at: 1, columns: 160, pieces: [[span('$1.23', 'green')]] }))

  const ui = await $.ui.mount(HINT_ROW(HINT, 160))
  expect(await line(ui)).toBe(`${HINT}  $1.23`)
  expect((await ui.find({ type: 'Text', text: /^\$1\.23$/ }))?.props.color).toBe('green')
  expect((await ui.find({ type: 'Text', text: /^\? for shortcuts$/ }))?.props.dimColor).toBe(true)
  await ui.unmount()
})

test('pieces are joined by a bar, spans keep their colour and bold', async ($, on) => {
  const pieces = [[span('\ue0b0 a', '#4cc86e', true), span('b')], [span('c', 'redBright')]]
  engine(on, JSON.stringify({ written_at: 1, columns: 160, pieces }))

  const ui = await $.ui.mount(HINT_ROW(HINT, 160))
  expect(await line(ui)).toBe(`${HINT}  \ue0b0 ab │ c`)
  const first = await ui.find({ type: 'Text', text: /a$/ })
  expect(first?.props.color).toBe('#4cc86e')
  expect(first?.props.bold).toBe(true)
  expect((await ui.find({ type: 'Text', text: /^b$/ }))?.props.bold).not.toBe(true)
  expect((await ui.find({ type: 'Text', text: /^c$/ }))?.props.color).toBe('redBright')
  expect((await ui.find({ type: 'Text', text: /^ │ $/ }))?.props.color).toBe('text')
  await ui.unmount()
})

test('an underlined span stays underlined, and only that one', async ($, on) => {
  const pieces = [[{ ...span('#12', 'yellow'), underline: true }], [span('$1.23', 'green')]]
  engine(on, JSON.stringify({ written_at: 1, columns: 160, pieces }))

  const ui = await $.ui.mount(HINT_ROW(HINT, 160))
  expect((await ui.find({ type: 'Text', text: /^#12$/ }))?.props.underline).toBe(true)
  expect((await ui.find({ type: 'Text', text: /^\$1\.23$/ }))?.props.underline).not.toBe(true)
  await ui.unmount()
})

test('test_overflow_is_cut_to_the_room', async ($, on) => {
  // `? for shortcuts` is the default mode's hint: no mode label in front of it.
  const hint = `${HINT}${'h'.repeat(15)}`
  const pieces = [[span('a'.repeat(10), 'green')], [span('b'.repeat(10), 'green')]]
  engine(on, JSON.stringify({ written_at: 1, columns: 50, pieces }))

  // 30 + 2 + 10 = 42 fits in 50 - 4 = 46; adding " │ " and 10 more makes 55.
  const ui = await $.ui.mount(HINT_ROW(hint, 50))
  expect(await line(ui)).toBe(`${hint}  ${'a'.repeat(10)}`)
  expect(await ui.find({ type: 'Text', text: /│/ })).toBeUndefined()
  await ui.unmount()

  // Nothing fits: the engine's own line stays.
  const none = await $.ui.mount(HINT_ROW(hint, 40))
  expect(await none.find({ type: 'Text', text: /^engine / })).toBeDefined()
  await none.unmount()
})

test('a mode label in front of the hint is counted, and the row is cut rather than wrapped', async ($, on) => {
  // Logged live at 169 columns while a subagent ran: the hint text leaves out the `⏵⏵ bypass permissions on · `
  // the engine draws before it on the same row, so the mod reserves that label's cells.
  const hint = '(shift+tab to cycle) · /tasks to see subagents'
  const pieces = [[span('a'.repeat(10), 'green')], [span('b'.repeat(10), 'green')]]
  engine(on, JSON.stringify({ written_at: 1, columns: 80, pieces }))

  // At 103 columns the room is 99: 27 + 2 + 46 + 2 + 10 = 87 fits, and the second piece would make 87 + 3 + 10 = 100.
  const ui = await $.ui.mount(HINT_ROW(hint, 103))
  expect(await line(ui)).toBe(`${SHIELD} ${hint}  ${'a'.repeat(10)}`)
  await ui.unmount()

  // Whatever the estimate, the row is one Text that truncates at the row's edge instead of wrapping.
  const row = await $.ui.mount(HINT_ROW(hint, 120))
  expect((await row.find({ type: 'Text', text: /shift\+tab/ }))?.props.wrap).toBe('truncate-end')
  await row.unmount()
})

test('any hint but the default mode\'s may have a mode label in front', async ($, on) => {
  // Logged live with a background shell running: the hint was `1 shell`, the engine drew
  // `⏵⏵ bypass permissions on · ` before it, and a row 27 cells too wide squeezed that ` · ` onto a line of its own.
  const pieces = [[span('a'.repeat(10), 'green')]]
  engine(on, JSON.stringify({ written_at: 1, columns: 80, pieces }))

  // 27 + 2 + 7 + 2 + 10 = 48 is one more than the room of 51 - 4.
  const tight = await $.ui.mount(HINT_ROW('1 shell', 51))
  expect(await line(tight)).toBe(`engine ${SHIELD} 1 shell`)
  await tight.unmount()

  const room = await $.ui.mount(HINT_ROW('1 shell', 52))
  expect(await line(room)).toBe(`${SHIELD} 1 shell  ${'a'.repeat(10)}`)
  await room.unmount()

  // The default mode's hint has no label: 15 + 2 + 10 = 27 fits 31 - 4.
  const plain = await $.ui.mount(HINT_ROW(HINT, 31))
  expect(await line(plain)).toBe(`${HINT}  ${'a'.repeat(10)}`)
  await plain.unmount()
})

test('a Nerd Font glyph counts as one cell and no viewport means 80 columns', async ($, on) => {
  const pieces = [[span('\uf120'.repeat(10))], [span('\uf120'.repeat(10))]]
  engine(on, JSON.stringify({ written_at: 1, columns: 80, pieces }))

  // 15 + 2 + 10 = 27; with the second piece 27 + 3 + 10 = 40 <= 76.
  const ui = await $.ui.mount({ ...HINT_ROW(HINT, 0), viewport: undefined })
  expect(await line(ui)).toBe(`${HINT}  ${'\uf120'.repeat(10)} │ ${'\uf120'.repeat(10)}`)
  await ui.unmount()
})

test('an icon past U+FFFF counts as one cell too', async ($, on) => {
  // The status bar's clock (U+F0150) and robot (U+F06A9) are two UTF-16 units each.
  const piece = [span('\u{F0150} 1h 33m')]
  engine(on, JSON.stringify({ written_at: 1, columns: 80, pieces: [piece] }))

  // 15 + 2 + 8 = 25 fills the room of 29 - 4 exactly.
  const ui = await $.ui.mount(HINT_ROW(HINT, 29))
  expect(await line(ui)).toBe(`${HINT}  \u{F0150} 1h 33m`)
  await ui.unmount()
})

test('test_no_overflow_file_passes_to_the_engine', async ($, on) => {
  engine(on, null)

  const ui = await $.ui.mount(HINT_ROW(HINT, 160))
  expect(await ui.find({ type: 'Text', text: /^engine / })).toBeDefined()
  await ui.unmount()
})

test('test_bad_overflow_file_passes_to_the_engine', async ($, on) => {
  let file = '{'
  engine(on, () => file)

  for (const bad of ['{', '{"written_at":1}', '{"pieces":"x"}', '{"pieces":[]}', 'null']) {
    file = bad

    const ui = await $.ui.mount(HINT_ROW(HINT, 160))
    expect(await ui.find({ type: 'Text', text: /^engine / })).toBeDefined()
    await ui.unmount()
  }
})

test('test_other_surfaces_pass', async ($, on) => {
  engine(on, JSON.stringify({ written_at: 1, columns: 160, pieces: [[span('$1.23', 'green')]] }))

  const ui = await $.ui.mount(HINT_ROW(HINT, 160, { surface: 'desktop' }))
  expect(await ui.find({ type: 'Text', text: /^engine / })).toBeDefined()
  expect(await ui.find({ type: 'Text', text: /\$1\.23/ })).toBeUndefined()
  await ui.unmount()
})

test('the file is read again when the minute ticks', async ($, on) => {
  const time = mock.clock(on)
  let file = JSON.stringify({ written_at: 1, columns: 160, pieces: [[span('$1.00')]] })
  engine(on, () => file)
  on('session.start', (_, e) => ({ cwd: e.cwd }))
  await $.session.start({ cwd: '/', surface: 'terminal', isInteractive: true })

  const ui = await $.ui.mount(HINT_ROW(HINT, 160))
  expect(await line(ui)).toBe(`${HINT}  $1.00`)

  file = JSON.stringify({ written_at: 2, columns: 160, pieces: [[span('$2.00')]] })
  await time.advance(60_000)
  expect(await line(ui)).toBe(`${HINT}  $2.00`)
  await ui.unmount()
})

test('the folder is looked up under USERPROFILE before HOME', async ($, on) => {
  engine(on, JSON.stringify({ written_at: 1, columns: 160, pieces: [[span('$1.23', 'green')]] }), {
    HOME: 'C:/msys/home/me',
    USERPROFILE: 'C:/Users/me',
  })

  const ui = await $.ui.mount(HINT_ROW(HINT, 160))
  expect(await line(ui)).toBe(`${HINT}  $1.23`)
  await ui.unmount()
})

test('a mode label is followed by the permissions shield, dim like the hint', async ($, on) => {
  // The engine draws `⏵⏵ bypass permissions on` and its own dim ` · ` before the hint; the shield (md-shield_key_outline)
  // starts the hint, so the row reads `⏵⏵ bypass permissions on · <shield> (shift+tab to cycle)`.
  const hint = '(shift+tab to cycle)'
  engine(on, null)

  const passed = await $.ui.mount(HINT_ROW(hint, 160))
  expect(await line(passed)).toBe(`engine ${SHIELD} ${hint}`)
  await passed.unmount()

  // The default mode has no label, so no shield.
  const plain = await $.ui.mount(HINT_ROW(HINT, 160))
  expect(await line(plain)).toBe(`engine ${HINT}`)
  await plain.unmount()
})

test('the shield is drawn dim in front of the hint beside the overflow', async ($, on) => {
  engine(on, JSON.stringify({ written_at: 1, columns: 160, pieces: [[span('$1.23', 'green')]] }))

  const ui = await $.ui.mount(HINT_ROW('(shift+tab to cycle)', 160))
  expect(await line(ui)).toBe(`${SHIELD} (shift+tab to cycle)  $1.23`)
  expect((await ui.find({ type: 'Text', text: /^\u{F0BC5} \(shift\+tab to cycle\)$/u }))?.props.dimColor).toBe(true)
  await ui.unmount()
})
