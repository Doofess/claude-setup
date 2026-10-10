/** A tool call that is running now, for the band above the prompt. */
export type Activity = {
  id: string
  tool: string
  input: unknown
  agentId?: string
  /** True once `tool.check` put the call to the person (verdict `ask`). */
  awaiting?: boolean
}

declare module 'claude-code' {
  interface PluginState {
    'readable-session': {
      running: Activity[]
    }
  }
}
