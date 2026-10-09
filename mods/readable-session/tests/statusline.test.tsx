import { describe, expect, mock, test } from 'claude-code/testing'

import { TOGGLE_ACTION, nextMode } from '../hooks/register'

/** The engine spells paths its own way (backslashes on Windows): key by forward slashes. */
const key = (p: string) => p.replace(/\\/g, '/')

/** A disk in memory: reads answer from `files`, a missing one is denied (rejects); writes land in it. */
function disk(on: any, files: Record<string, string>) {
  on('fs.read', async (_$: any, e: any) =>
    key(e.path) in files ? { value: files[key(e.path)] } : { deny: `ENOENT: ${e.path}` },
  )
  on('fs.write', async (_$: any, e: any) => {
    files[key(e.path)] = e.text
    return { value: undefined }
  })
  return files
}

function toasts(on: any) {
  const seen: string[] = []
  on('ui.toast', async (_$: any, e: any) => {
    seen.push(e.text)
    return { value: undefined }
  })
  return seen
}

describe('nextMode', () => {
  test('flips compact and full; missing or junk reads as compact, the default', () => {
    expect(nextMode('compact')).toBe('full')
    expect(nextMode('compact\n')).toBe('full')
    expect(nextMode('full')).toBe('compact')
    expect(nextMode(' FULL\n')).toBe('compact')
    expect(nextMode(undefined)).toBe('full')
    expect(nextMode('')).toBe('full')
    expect(nextMode('bananas')).toBe('full')
  })
})

describe('/statusline-toggle', () => {
  test('missing file: writes full under CLAUDE_CONFIG_DIR, toasts, shows no text', async ($, on) => {
    mock.env(on, { CLAUDE_CONFIG_DIR: 'C:/cfg/' })
    const files = disk(on, {})
    const seen = toasts(on)
    const r = await $.command.run({ command: 'statusline-toggle' })
    expect(files['C:/cfg/statusline-mode']).toBe('full')
    expect(r.text).toBeUndefined()
    expect(seen).toEqual(['Status line: full'])
  })

  test('compact flips back to full under USERPROFILE/.claude', async ($, on) => {
    mock.env(on, { USERPROFILE: 'C:\\Users\\me' })
    const files = disk(on, { 'C:/Users/me/.claude/statusline-mode': 'compact' })
    const seen = toasts(on)
    await $.command.run({ command: 'statusline-toggle' })
    expect(files['C:/Users/me/.claude/statusline-mode']).toBe('full')
    expect(seen).toEqual(['Status line: full'])
  })
})

describe('Ctrl+Alt+S button', () => {
  const footer = ($: any, modes: string[] = []) =>
    $.ui.mount({ plugin: 'readable-session', surface: 'terminal', component: 'SessionMode', props: { modes } })

  test('the footer holds a hidden Button on the bound action; pressing it flips the mode', async ($, on) => {
    mock.env(on, { CLAUDE_CONFIG_DIR: 'C:/cfg' })
    const files = disk(on, { 'C:/cfg/statusline-mode': 'compact' })
    const seen = toasts(on)
    const ui = await footer($)
    const button = await ui.find({ type: 'Button' })
    expect(button?.props.action).toBe(TOGGLE_ACTION)
    expect(await ui.findAll({ type: 'Text' })).toHaveLength(0)
    await $.ui.press({ plugin: 'readable-session', key: 'statusline-toggle' } as any)
    expect(files['C:/cfg/statusline-mode']).toBe('full')
    expect(seen).toEqual(['Status line: full'])
  })

  test("the engine's mode labels still show", async ($, on) => {
    const ui = await footer($, ['focus', 'memory paused'])
    expect((await ui.findAll({ type: 'Text' }))[0]?.text).toBe('focus & memory paused')
  })
})
