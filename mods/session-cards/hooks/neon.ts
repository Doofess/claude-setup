/**
 * The `neon` effect of chalk-animation 2.0.3 (MIT, https://github.com/bokub/chalk-animation), ported because a
 * mod cannot import npm packages and the library prints ANSI on its own timer.
 *
 * Its algorithm: frame `n` every 500 ms; even frames are dim, odd frames bold. Its own colours (rgb 88,80,85 and
 * 213,70,242) are replaced by Fable's gold: both frames are `yellowBright`.
 */
export const NEON_MS = 500

export function neon(frame: number): { color: string; bold: boolean; dimColor: boolean } {
  return frame % 2 === 0
    ? { color: 'yellowBright', bold: false, dimColor: true }
    : { color: 'yellowBright', bold: true, dimColor: false }
}
