/** A tool call that is running now, for the band above the prompt. */
export type Activity = {
  id: string
  tool: string
  input: unknown
  agentId?: string
  /** True once `tool.check` put the call to the person (verdict `ask`). */
  awaiting?: boolean
}

/** The session the prompt-bar label tracks: `pending` until it has a name. */
export type SessionLabel = {
  sessionId: string
  transcriptPath: string
  status: 'pending' | 'done'
  /** This module ran `/color orange` for it: that row is drawn empty. */
  colored?: boolean
  /** The name this module's `/rename` gave it: that row is drawn empty. */
  renamedTo?: string
}

declare module 'claude-code' {
  interface PluginState {
    'readable-session': {
      running: Activity[]
      label: SessionLabel | null
    }
  }
}
