import { expect, mock, test } from 'claude-code/testing'

type On = Parameters<Parameters<typeof test>[1]>[1]

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

const span = (text: string, colour: string | null = null, bold = false) => ({ text, colour, bold })

// Nothing sits beneath the plugin: these hooks stand for the engine, the
// session id and the one file the status bar wrote (null: there is none).
const engine = (on: On, file: string | null | (() => string | null)) => {
  mock.env(on, { HOME: 'C:/Users/me' })
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

    return <Text>engine</Text>
  })
}

const line = async (ui: { findAll: (q: { type: 'Text' }) => Promise<{ text: string }[]> }) =>
  (await ui.findAll({ type: 'Text' })).map(t => t.text).join('')

test('test_overflow_is_drawn_after_the_hint', async ($, on) => {
  engine(on, JSON.stringify({ written_at: 1, columns: 160, pieces: [[span('$1.23', 'green')]] }))

  const ui = await $.ui.mount(HINT_ROW(HINT, 160))
  expect(await line(ui)).toBe(`${HINT}  $1.23`)
  expect((await ui.find({ type: 'Text', text: /^\$1\.23$/ }))?.props.color).toBe('green')
  expect((await ui.find({ type: 'Text', text: /shortcuts/ }))?.props.dimColor).toBe(true)
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
  expect((await ui.find({ type: 'Text', text: /│/ }))?.props.color).toBe('text')
  await ui.unmount()
})

test('test_overflow_is_cut_to_the_room', async ($, on) => {
  const hint = 'h'.repeat(30)
  const pieces = [[span('a'.repeat(10), 'green')], [span('b'.repeat(10), 'green')]]
  engine(on, JSON.stringify({ written_at: 1, columns: 50, pieces }))

  // 30 + 2 + 10 = 42 fits in 50 - 4 = 46; adding " │ " and 10 more makes 55.
  const ui = await $.ui.mount(HINT_ROW(hint, 50))
  expect(await line(ui)).toBe(`${hint}  ${'a'.repeat(10)}`)
  expect(await ui.find({ type: 'Text', text: /│/ })).toBeUndefined()
  await ui.unmount()

  // Nothing fits: the engine's own line stays.
  const none = await $.ui.mount(HINT_ROW(hint, 40))
  expect(await none.find({ type: 'Text', text: /^engine$/ })).toBeDefined()
  await none.unmount()
})

test('a Nerd Font glyph counts as one cell and no viewport means 80 columns', async ($, on) => {
  const pieces = [[span('\uf120'.repeat(10))], [span('\uf120'.repeat(10))]]
  engine(on, JSON.stringify({ written_at: 1, columns: 80, pieces }))

  // 15 + 2 + 10 = 27; with the second piece 27 + 3 + 10 = 40 <= 76.
  const ui = await $.ui.mount({ ...HINT_ROW(HINT, 0), viewport: undefined })
  expect(await line(ui)).toBe(`${HINT}  ${'\uf120'.repeat(10)} │ ${'\uf120'.repeat(10)}`)
  await ui.unmount()
})

test('test_no_overflow_file_passes_to_the_engine', async ($, on) => {
  engine(on, null)

  const ui = await $.ui.mount(HINT_ROW(HINT, 160))
  expect(await ui.find({ type: 'Text', text: /^engine$/ })).toBeDefined()
  await ui.unmount()
})

test('test_bad_overflow_file_passes_to_the_engine', async ($, on) => {
  let file = '{'
  engine(on, () => file)

  for (const bad of ['{', '{"written_at":1}', '{"pieces":"x"}', '{"pieces":[]}', 'null']) {
    file = bad

    const ui = await $.ui.mount(HINT_ROW(HINT, 160))
    expect(await ui.find({ type: 'Text', text: /^engine$/ })).toBeDefined()
    await ui.unmount()
  }
})

test('test_other_surfaces_pass', async ($, on) => {
  engine(on, JSON.stringify({ written_at: 1, columns: 160, pieces: [[span('$1.23', 'green')]] }))

  const ui = await $.ui.mount(HINT_ROW(HINT, 160, { surface: 'desktop' }))
  expect(await ui.find({ type: 'Text', text: /^engine$/ })).toBeDefined()
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
