/** Prompt text -> the times (ms since the epoch) prompt.submit saw it, oldest first. */
export type PromptTimes = Record<string, number[]>

declare module 'claude-code' {
  interface PluginState {
    'session-cards': {
      promptTimes: PromptTimes
    }
  }
}
