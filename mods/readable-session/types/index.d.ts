/** A tool call that is running now, or just finished, for the band above the prompt. */
export type Activity = {
  id: string
  tool: string
  input: unknown
  agentId?: string
  /** True once `tool.check` put the call to the person (verdict `ask`). */
  awaiting?: boolean
  /** When the call began, in `$.clock.now()`'s milliseconds. */
  startedAt: number
  /** Set when the call finished; the band keeps it a moment, marked done. */
  doneAt?: number
  /** True when the finished call errored, was denied or threw. */
  failed?: boolean
}

/** The model a subagent got: `explicit` when the Agent call named one. */
export type AgentTag = {
  model: string
  explicit: boolean
}

declare module 'claude-code' {
  interface PluginState {
    'readable-session': {
      running: Activity[]
      agents: Record<string, AgentTag>
    }
  }
}
