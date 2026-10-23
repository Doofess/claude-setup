/** Prompt text -> the times (ms since the epoch) prompt.submit saw it, oldest first. */
export type PromptTimes = Record<string, number[]>

declare module 'claude-code' {
  interface PluginState {
    'session-cards': {
      promptTimes: PromptTimes
      /** Bumped every minute so the hint line reads the status bar's overflow file again. */
      overflowTick: number
    }
  }
}
