import { describe, expect, mock, test } from 'claude-code/testing'

import { TAIL_PY, scanTranscript, slug } from '../hooks/session-label'

const T = 'C:/t/s1.jsonl'
const key = (p: string) => p.replace(/\\/g, '/')

const aiTitle = (t: string) => JSON.stringify({ type: 'ai-title', aiTitle: t, sessionId: 's1' })
const agentName = (n: string) => JSON.stringify({ type: 'agent-name', agentName: n, sessionId: 's1' })
const agentColor = (c: string) => JSON.stringify({ type: 'agent-color', agentColor: c, sessionId: 's1' })
const userLine = (text: string) => JSON.stringify({ type: 'user', message: { role: 'user', content: text } })

type World = {
  files: Record<string, string>
  runs: { command: string; args: string }[]
  python: string[][]
  surfaces: string[]
  /** stat size override per path, to stand for a transcript over 4 MiB */
  sizes: Record<string, number>
  pythonOut: string
}

/** The engine beneath the plugin: the disk, the commands run, the surfaces, python. */
function world(on: any, init: Partial<World> = {}): World {
  const w: World = { files: {}, runs: [], python: [], surfaces: ['terminal'], sizes: {}, pythonOut: '', ...init }
  on('fs.stat', async (_$: any, e: any) => {
    const p = key(e.path)
    if (!(p in w.files) && !(p in w.sizes)) return { deny: `ENOENT: ${e.path}` }
    return { value: { kind: 'file', size: w.sizes[p] ?? (w.files[p] ?? '').length, mtimeMs: 0, isLink: false } }
  })
  on('fs.read', async (_$: any, e: any) =>
    key(e.path) in w.files ? { value: w.files[key(e.path)] } : { deny: `ENOENT: ${e.path}` },
  )
  on('process.run', async (_$: any, e: any) => {
    w.python.push([...e.argv])
    return { value: { exitCode: 0, stdout: w.pythonOut, stderr: '' } }
  })
  on('session.surfaces', async () => ({ value: w.surfaces }))
  // Tool calls never end: one started stays in the running list.
  on('tool.call', () => new Promise(() => {}) as any)
  // No settings hooks beneath: each classic event answers nothing.
  for (const ev of ['classic.SessionStart', 'classic.Stop', 'classic.UserPromptSubmit']) on(ev, async () => ({}))
  on('command.run', async (_$: any, e: any) => {
    w.runs.push({ command: e.command, args: e.args })
    return {}
  })
  return w
}

/** A tool call that starts (and never ends): the `running` list gets written. */
async function toolRan($: any, clock: any) {
  void $.tool.call({ tool: 'Read', file_path: '/a/x.ts', tool_use_id: 'u1' } as any)
  await clock.settle()
}

const start = ($: any, source: string, extra: any = {}) =>
  $.classic.SessionStart({ source, session_id: 's1', transcript_path: T, ...extra })

describe('slug', () => {
  test('lowercase hyphen slug of the AI title', () => {
    expect(slug('statusline.py usage accuracy')).toBe('statusline-py-usage-accuracy')
    expect(slug('Marshell Implementation Plan')).toBe('marshell-implementation-plan')
    expect(slug('  Fix: CI (GitHub Actions)!  ')).toBe('fix-ci-github-actions')
  })
  test('cut at a word boundary near 40 characters', () => {
    const s = slug('Investigate flaky integration tests in the payments service pipeline')
    expect(s.length).toBeLessThanOrEqual(40)
    expect(s).toBe('investigate-flaky-integration-tests-in')
  })
  test('keeps non-Latin letters', () => {
    expect(slug('תיקון באג')).toBe('תיקון-באג')
  })
})

describe('scanTranscript', () => {
  test('last AI title wins; agent name and color are seen', () => {
    const f = scanTranscript([aiTitle('First'), userLine('hi'), aiTitle('Second'), agentColor('blue')].join('\n'))
    expect(f).toEqual({ aiTitle: 'Second', isNamed: false, hasColor: true })
    expect(scanTranscript([aiTitle('A'), agentName('mine')].join('\n')).isNamed).toBe(true)
    expect(scanTranscript(JSON.stringify({ type: 'custom-title', customTitle: 'x', sessionId: 's1' })).isNamed).toBe(true)
  })
  test('the same words inside a message do not count', () => {
    const f = scanTranscript(userLine(`${agentName('fake')} ${agentColor('red')} ${aiTitle('nope')}`))
    expect(f).toEqual({ aiTitle: undefined, isNamed: false, hasColor: false })
  })
})

describe('TAIL_PY', () => {
  test('a python script that keeps only the metadata lines of the last 8 MiB', () => {
    expect(TAIL_PY).toContain('f.seek(max(0, n - (8 << 20)))')
    expect(TAIL_PY).toContain(`b'{"type":"agent-color"'`)
    expect(TAIL_PY).toContain(String.raw`b"\n".join(`)
  })
})

describe('sessions running before this module loaded (hot reload)', () => {
  test('a late SessionStart in a session that already had turns changes nothing', async ($, on) => {
    const clock = mock.clock(on)
    const w = world(on, { files: { [T]: aiTitle('Running already') } })
    // A turn ran under the old module: a tool call wrote the running list.
    await toolRan($, clock)
    const r1 = await start($, 'startup')
    const r2 = await start($, 'resume')
    await clock.settle()
    expect(w.runs).toEqual([])
    expect(r1.sessionTitle).toBeUndefined()
    expect(r2.sessionTitle).toBeUndefined()
  })

  test('a session this module saw start still handles a later /clear or /resume', async ($, on) => {
    const clock = mock.clock(on)
    const w = world(on)
    await start($, 'startup')
    await toolRan($, clock)
    await start($, 'clear')
    await clock.settle()
    expect(w.runs).toEqual([
      { command: 'color', args: 'orange' },
      { command: 'color', args: 'orange' },
    ])
  })
})

describe('color', () => {
  test('a new terminal session is set to orange', async ($, on) => {
    const clock = mock.clock(on)
    const w = world(on)
    const r = await start($, 'startup')
    await clock.settle()
    expect(w.runs).toEqual([{ command: 'color', args: 'orange' }])
    expect(r.sessionTitle).toBeUndefined()
  })

  test('/clear gets orange again (Claude Code drops the color on clear)', async ($, on) => {
    const clock = mock.clock(on)
    const w = world(on)
    await start($, 'clear')
    await clock.settle()
    expect(w.runs).toEqual([{ command: 'color', args: 'orange' }])
  })

  test('nothing where no terminal draws (-p, SDK) or on compact', async ($, on) => {
    const clock = mock.clock(on)
    const w = world(on, { surfaces: [] })
    await start($, 'startup')
    w.surfaces = ['terminal']
    await start($, 'compact')
    await clock.settle()
    expect(w.runs).toEqual([])
  })

  test('a resumed session keeps the color it had', async ($, on) => {
    const clock = mock.clock(on)
    const w = world(on, { files: { [T]: [aiTitle('Old work'), agentName('mine'), agentColor('blue')].join('\n') } })
    const r = await start($, 'resume')
    await clock.settle()
    expect(w.runs).toEqual([])
    expect(r.sessionTitle).toBeUndefined()
  })

  test('a resumed transcript that cannot be read is left alone', async ($, on) => {
    const clock = mock.clock(on)
    const w = world(on)
    const r = await start($, 'resume')
    await clock.settle()
    expect(w.runs).toEqual([])
    expect(r.sessionTitle).toBeUndefined()
  })
})

describe('name on resume', () => {
  test('an unnamed resumed session is named from its AI title at once, and turns orange', async ($, on) => {
    const clock = mock.clock(on)
    const w = world(on, { files: { [T]: [userLine('hi'), aiTitle('statusline.py usage accuracy')].join('\n') } })
    const r = await start($, 'resume')
    await clock.settle()
    expect(r.sessionTitle).toBe('statusline-py-usage-accuracy')
    expect(w.runs).toEqual([{ command: 'color', args: 'orange' }])
  })

  test('a custom title (session_title, --name) is never replaced', async ($, on) => {
    world(on, { files: { [T]: aiTitle('Something') } })
    const r = await start($, 'resume', { session_title: 'my-name' })
    expect(r.sessionTitle).toBeUndefined()
  })

  test('a transcript over 4 MiB is tailed through python', async ($, on) => {
    const w = world(on, { sizes: { [T]: 6 * 1024 * 1024 }, pythonOut: aiTitle('Big session work') })
    const r = await start($, 'resume')
    expect(r.sessionTitle).toBe('big-session-work')
    expect(w.python[0]?.[0]).toBe('python')
    expect(w.python[0]?.at(-1)).toBe(T)
  })
})

describe('name in a new session', () => {
  test('right after the first reply: /rename to the AI title, once', async ($, on) => {
    const clock = mock.clock(on)
    const w = world(on)
    await start($, 'startup')
    w.files[T] = [userLine('hi'), aiTitle('statusline.py usage accuracy')].join('\n')
    await $.classic.Stop({ session_id: 's1', transcript_path: T, stop_hook_active: false })
    await clock.settle()
    await $.classic.Stop({ session_id: 's1', transcript_path: T, stop_hook_active: false })
    await clock.settle()
    expect(w.runs).toEqual([
      { command: 'color', args: 'orange' },
      { command: 'rename', args: 'statusline-py-usage-accuracy' },
    ])
  })

  test('a late AI title is tried again a few seconds on', async ($, on) => {
    const clock = mock.clock(on)
    const w = world(on)
    await start($, 'startup')
    w.files[T] = userLine('hi')
    await $.classic.Stop({ session_id: 's1', transcript_path: T, stop_hook_active: false })
    await clock.settle()
    w.files[T] += '\n' + aiTitle('Late title')
    await clock.advance(3000)
    expect(w.runs.at(-1)).toEqual({ command: 'rename', args: 'late-title' })
  })

  test('a name the person gave first is kept', async ($, on) => {
    const clock = mock.clock(on)
    const w = world(on)
    await start($, 'startup')
    w.files[T] = [aiTitle('Auto title'), agentName('my-own')].join('\n')
    await $.classic.Stop({ session_id: 's1', transcript_path: T, stop_hook_active: false })
    await clock.settle()
    expect(w.runs.map(r => r.command)).toEqual(['color'])
  })

  test('a session this module did not see start (running before a reload) is never renamed', async ($, on) => {
    const clock = mock.clock(on)
    const w = world(on, { files: { [T]: aiTitle('Running already') } })
    await $.classic.Stop({ session_id: 's1', transcript_path: T, stop_hook_active: false })
    const r = await $.classic.UserPromptSubmit({ session_id: 's1', transcript_path: T, prompt: 'hi' })
    await clock.settle()
    expect(w.runs).toEqual([])
    expect(r.sessionTitle).toBeUndefined()
  })

  test('fallback: still unnamed at the next prompt, that prompt names it', async ($, on) => {
    const clock = mock.clock(on)
    const w = world(on)
    await start($, 'startup')
    w.files[T] = userLine('hi')
    await $.classic.Stop({ session_id: 's1', transcript_path: T, stop_hook_active: false })
    await clock.advance(10000)
    w.files[T] += '\n' + aiTitle('Second prompt name')
    const r = await $.classic.UserPromptSubmit({ session_id: 's1', transcript_path: T, prompt: 'next' })
    expect(r.sessionTitle).toBe('second-prompt-name')
    const again = await $.classic.UserPromptSubmit({ session_id: 's1', transcript_path: T, prompt: 'more' })
    expect(again.sessionTitle).toBeUndefined()
    expect(w.runs.map(x => x.command)).toEqual(['color'])
  })

  test('the next prompt leaves a custom title alone', async ($, on) => {
    const w = world(on)
    await start($, 'startup')
    w.files[T] = aiTitle('Auto')
    const r = await $.classic.UserPromptSubmit({ session_id: 's1', transcript_path: T, prompt: 'x', session_title: 'mine' })
    expect(r.sessionTitle).toBeUndefined()
  })
})

describe('quiet rows', () => {
  const out = (command: string, args: string, text: string) => ({ command, args, text, isErrored: false }) as any
  const mount = ($: any, component: string, props: any) =>
    $.ui.mount({ plugin: 'readable-session', surface: 'terminal', component, props })

  test("the module's own /color and /rename output rows are drawn empty; others are the engine's", async ($, on) => {
    const clock = mock.clock(on)
    on('ui.render', async (_$: any, e: any) => {
      const { Text } = _$.ui.resolve(e)
      return <Text>ENGINE</Text>
    })
    const w = world(on)
    await start($, 'startup')
    w.files[T] = aiTitle('Quiet rows')
    await $.classic.Stop({ session_id: 's1', transcript_path: T, stop_hook_active: false })
    await clock.settle()

    const color = await mount($, 'CommandOutput', out('color', 'orange', 'Session color set to: orange'))
    expect(await color.findAll({ type: 'Text' })).toHaveLength(0)
    const rename = await mount($, 'CommandOutput', out('rename', 'quiet-rows', 'Session renamed to: quiet-rows'))
    expect(await rename.findAll({ type: 'Text' })).toHaveLength(0)

    const other = await mount($, 'CommandOutput', out('rename', 'my-own', 'Session renamed to: my-own'))
    expect((await other.findAll({ type: 'Text' }))[0]?.text).toBe('ENGINE')
    const blue = await mount($, 'CommandOutput', out('color', 'blue', 'Session color set to: blue'))
    expect((await blue.findAll({ type: 'Text' }))[0]?.text).toBe('ENGINE')
  })
})
