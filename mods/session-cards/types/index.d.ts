/** Prompt text -> the times (ms since the epoch) prompt.submit saw it, oldest first. */
export type PromptTimes = Record<string, number[]>

/** One finished main-loop turn: its number (counting from the session's first), how long it ran and when it ended (ms since the epoch). */
export type TurnRecord = { seq: number; durationMs: number; endedAt: number }

declare module 'claude-code' {
  interface PluginState {
    'session-cards': {
      promptTimes: PromptTimes
      /** Bumped every minute so the hint line reads the status bar's overflow file again. */
      overflowTick: number
      /** Bumped when an agent record changes and each second while a subagent runs, so Agent rows redraw. */
      agentTick: number
      /** Bumped every 500 ms while a Fable subagent runs: the frame of neon on its row. */
      neonTick: number
      /** The main loop's finished turns, oldest first, the last 200: what the turn-end line draws. */
      turns: TurnRecord[]
      /** The ids of the background shells that run now, so the turn-end lines redraw as one starts or ends. */
      runningShells: string[]
    }
  }
}
