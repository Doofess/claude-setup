import type { Register } from 'claude-code'


/** Claude Code's own wrapper lines around a pasted block: `<pasted_content …>` and `</pasted_content …>`. */
const WRAPPER = /^[ \t]*<\/?pasted_content\b[^>\n]*>[ \t]*(?:\r?\n|$)/gm

/** The prompt as typed, with the paste wrapper lines taken out. */
export function promptText(text: string): string {
  return text.replace(WRAPPER, '')
}

/** `HH:MM`, 24-hour, in the machine's local time. */
export function clock(ms: number): string {
  const at = new Date(ms)
  const two = (n: number) => String(n).padStart(2, '0')

  return `${two(at.getHours())}:${two(at.getMinutes())}`
}

export const register: Register = on => {
  // A row's time is settled at its first draw and kept for every redraw. A
  // ui.render hook may not write $.state, so the claims live here, in the
  // module: `claimed` maps a row (e.requestId, the message id) to its time or
  // null, and `taken` counts the times each text has handed out, which is the
  // cursor into promptTimes[text]. So two identical prompts show their own
  // times, the earlier row the earlier time. A hot reload empties both; rows
  // are then claimed again in draw order, which is their order in the log.
  const claimed = new Map<string, number | null>()
  const taken = new Map<string, number>()

  on('prompt.submit', async ($, e, next) => {
    const now = await $.clock.now()
    const { value = {} } = await $.state.get({ plugin: 'session-cards', key: 'promptTimes' })
    await $.state.set({ plugin: 'session-cards', key: 'promptTimes' }, { ...value, [e.text]: [...(value[e.text] ?? []), now] })

    return next(e)
  })

  on('ui.render', { component: 'UserMessage' }, async ($, e, next) => {
    if (e.surface !== 'terminal' || e.props.origin.kind !== 'composer') {
      return next(e)
    }

    const { Box, Text } = $.ui.resolve(e)
    const { text } = e.props
    let at = claimed.get(e.requestId)

    if (at === undefined) {
      const { value = {} } = await $.state.get({ plugin: 'session-cards', key: 'promptTimes' })
      const used = taken.get(text) ?? 0
      at = value[text]?.[used] ?? null
      claimed.set(e.requestId, at)

      if (at !== null) {
        taken.set(text, used + 1)
      }
    }

    const header = `  You prompted${at === null ? '' : ` · ${clock(at)}`}`

    return (
      <Box flexDirection="column" borderStyle="round" borderColor="claude" paddingX={1}>
        <Text color="claude" bold>
          {header}
        </Text>
        <Text>{promptText(text)}</Text>
      </Box>
    )
  })

  on('ui.render', { component: 'CommandOutput' }, async ($, e, next) => {
    if (e.surface !== 'terminal') {
      return next(e)
    }

    const inner = await next(e)

    // A row the engine drew empty (a Box with no children) stays empty.
    if (inner.type === 'Box' && !inner.children?.length) {
      return inner
    }

    const { Box, Text } = $.ui.resolve(e)
    const { command, args, isErrored } = e.props
    const colour = isErrored ? 'error' : 'permission'

    return (
      <Box flexDirection="column" borderStyle="round" borderColor={colour} paddingX={1}>
        <Text color={colour} bold>
          {`  /${command}${args === '' ? '' : ` ${args}`}`}
        </Text>
        {inner}
      </Box>
    )
  })
}
