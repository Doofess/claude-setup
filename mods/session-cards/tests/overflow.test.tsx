import { expect, mock, test, type TestBody } from 'claude-code/testing'
import { placeRow } from '../hooks/register'

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

// The second row from statusbar.py's placed record (since the second-row layout): `under` reset times at their bar's
// screen column, moved `bars` lined up under the top row, the `right` group ending at the margin.
const HINT_X = 2
const BYPASS = '(shift+tab to cycle)'
const cellsOf = (text: string) => [...text].length
const record = (extra: object) => ({ written_at: 1, columns: 120, pieces: [], label: 27, under: [], bars: [], right: [], ...extra })
const placedText = (placed: { col: number; spans: { text: string }[] }[] | null) =>
  placed?.map(p => ({ col: p.col, text: p.spans.map(s => s.text).join('') }))

test('under piece lands at its column', async ($, on) => {
  const r = record({ under: [{ col: 60, rank: 4, spans: [span('3d4h')] }] })
  expect(placedText(placeRow(r, 22, 120))).toEqual([{ col: 60 - HINT_X - 27, text: '3d4h' }])
  expect(placedText(placeRow({ ...r, label: 0 }, 15, 120))).toEqual([{ col: 60 - HINT_X, text: '3d4h' }])

  // Drawn on the row: the hint, then spaces up to the piece.
  engine(on, JSON.stringify(r))
  const ui = await $.ui.mount(HINT_ROW(BYPASS, 120))
  const text = await line(ui)
  expect(cellsOf(text?.slice(0, text.indexOf('3d4h')) ?? '')).toBe(60 - HINT_X - 27) // by code point: the shield is two UTF-16 units
  expect(text?.startsWith(`${SHIELD} ${BYPASS}  `)).toBe(true)
  await ui.unmount()
})

test('right pieces end at the margin', async ($, on) => {
  const r = record({ right: [{ rank: 5, spans: [span('$1.23', 'green')] }, { rank: 6, spans: [span('1h 33m')] }] })
  const placed = placedText(placeRow(r, 22, 120))
  expect(placed).toEqual([{ col: 120 - 4 - HINT_X - 27 - cellsOf('$1.23 │ 1h 33m'), text: '$1.23 │ 1h 33m' }])

  engine(on, JSON.stringify(r))
  const ui = await $.ui.mount(HINT_ROW(BYPASS, 120))
  const text = (await line(ui)) ?? ''
  expect(text.endsWith('$1.23 │ 1h 33m')).toBe(true)
  expect(cellsOf(text)).toBe(120 - 4 - HINT_X - 27)
  expect((await ui.find({ type: 'Text', text: /^ │ $/ }))?.props.color).toBe('text')
  await ui.unmount()
})

test('right pieces drop by rank on collision', () => {
  const right = [{ rank: 5, spans: [span('$1.23')] }, { rank: 6, spans: [span('1h 33m')] }]
  const end = 120 - 4 - HINT_X - 27 // tree offset of the margin
  // An under piece ending 12 cells before the margin: `$1.23 │ 1h 33m` (14) does not fit beside it, `$1.23` does.
  const at = (offset: number) => offset + HINT_X + 27
  const one = placedText(placeRow(record({ under: [{ col: at(end - 16), rank: 3, spans: [span('2h10m')] }], right }), 22, 120))
  expect(one?.map(p => p.text)).toEqual(['2h10m', '$1.23'])
  // Closer still: the cost goes too, and the reset time keeps its place.
  const none = placedText(placeRow(record({ under: [{ col: at(end - 8), rank: 3, spans: [span('2h10m')] }], right }), 22, 120))
  expect(none).toEqual([{ col: end - 8, text: '2h10m' }])
})

test('moved bar lines up', () => {
  const bar = { col: 70, rank: 2, spans: [span('7D ████████ 41%  → 3d4h')] }
  const placed = placedText(placeRow(record({ bars: [bar], right: [{ rank: 6, spans: [span('1h 33m')] }] }), 22, 120))
  expect(placed?.[0]).toEqual({ col: 70 - HINT_X - 27, text: '7D ████████ 41%  → 3d4h' })
  const last = placed?.[placed.length - 1]
  expect(last && last.col + cellsOf(last.text)).toBe(120 - 4 - HINT_X - 27)

  // A second bar a separator after the first is drawn with the separator.
  const second = { col: 70 + cellsOf(bar.spans[0].text) + 3, rank: 1, spans: [span('5H ████████ 23%')] }
  expect(placedText(placeRow(record({ bars: [bar, second] }), 22, 140))).toEqual([
    { col: 70 - HINT_X - 27, text: `7D ████████ 41%  → 3d4h │ 5H ████████ 23%` },
  ])
})

test('bar that cannot line up goes right', () => {
  const bar = { col: 40, rank: 2, spans: [span('7D ████████ 41%')] } // tree offset 11, inside the 22-cell hint
  const placed = placedText(placeRow(record({ bars: [bar], right: [{ rank: 6, spans: [span('1h 33m')] }] }), 22, 120))
  expect(placed).toEqual([{ col: 120 - 4 - HINT_X - 27 - cellsOf('7D ████████ 41% │ 1h 33m'), text: '7D ████████ 41% │ 1h 33m' }])
  // Ranks are kept: on a narrower row the session time (6) drops before the moved bar (2).
  expect(placedText(placeRow(record({ bars: [bar], right: [{ rank: 6, spans: [span('1h 33m')] }] }), 22, 74))?.map(p => p.text)).toEqual([
    '7D ████████ 41%',
  ])
})

test('hint wins over an under piece', () => {
  const r = record({ under: [{ col: 20, rank: 3, spans: [span('2h10m')] }, { col: 100, rank: 4, spans: [span('3d4h')] }] })
  expect(placedText(placeRow(r, 50, 120))).toEqual([{ col: 100 - HINT_X - 27, text: '3d4h' }])
})

test('old record falls back', async ($, on) => {
  // Only `pieces`: an older statusbar.py. Left-packed after the hint, as before.
  engine(on, JSON.stringify({ written_at: 1, columns: 160, pieces: [[span('$1.23', 'green')], [span('c')]] }))
  const ui = await $.ui.mount(HINT_ROW(HINT, 160))
  expect(await line(ui)).toBe(`${HINT}  $1.23 │ c`)
  await ui.unmount()
})

test('too narrow returns engine line', async ($, on) => {
  const r = record({ under: [{ col: 60, rank: 4, spans: [span('3d4h')] }], right: [{ rank: 6, spans: [span('1h 33m')] }] })
  expect(placeRow(r, 22, 50)).toBeNull()
  engine(on, JSON.stringify(r))
  const ui = await $.ui.mount(HINT_ROW(BYPASS, 50))
  expect(await line(ui)).toBe(`engine ${SHIELD} ${BYPASS}`)
  await ui.unmount()
})

test('the record\'s label decides the shield', async ($, on) => {
  // label 0: the transcript says default mode, so a `1 shell` hint has no mode label and no shield in front.
  engine(on, JSON.stringify(record({ label: 0, right: [{ rank: 6, spans: [span('1h 33m')] }] })))
  const ui = await $.ui.mount(HINT_ROW('1 shell', 120))
  const text = (await line(ui)) ?? ''
  expect(text.startsWith('1 shell  ')).toBe(true)
  expect(cellsOf(text)).toBe(120 - 4 - HINT_X)
  await ui.unmount()
})

test('rank decides a collision, reset times included', () => {
  // Live at 104 columns: the 5H reset under its bar, a 7D bar too wide to line up, the cost and the session time.
  // The moved 7D bar (rank 2) outranks the 5H reset (3), so the reset gives way and the bar shows on the right.
  const r = record({
    under: [{ col: 87, rank: 3, spans: [span('1h59m')] }],
    bars: [{ col: 95, rank: 2, spans: [span(' 7D ████████ 32%  → 4d21h')] }],
    right: [{ rank: 5, spans: [span('$0.12')] }, { rank: 6, spans: [span('\u{F0150} 0m')] }],
  })
  const end = 104 - 4 - HINT_X - 27
  const bar = ' 7D ████████ 32%  → 4d21h'
  expect(placedText(placeRow(r, 22, 104))).toEqual([{ col: end - cellsOf(bar), text: bar }])
  // With room for both, the reset keeps its place and the bar lines up after it with a separator.
  expect(placedText(placeRow(r, 22, 145))).toEqual([
    { col: 87 - HINT_X - 27, text: '1h59m │  7D ████████ 32%  → 4d21h' },
    { col: 145 - 4 - HINT_X - 27 - cellsOf('$0.12 │ \u{F0150} 0m'), text: '$0.12 │ \u{F0150} 0m' },
  ])
})
