"""A two-row status line for Claude Code.

Usage: Claude Code runs `python statusbar.py` and pipes its session JSON to stdin; `--demo` prints
sample data instead. Column width comes from the COLUMNS environment variable (default 120).

Row 1 says where you are: repo (owner/name), git branch, PR number, then the model and its effort.
Row 2 says how much room is left: a context meter with tokens used out of the auto-compact point,
the 5-hour and 7-day plan usage meters with the time until each resets, then cost and lines changed.
Icons are Nerd Font glyphs, one cell wide. Colours are the terminal's own 16-colour palette
(green, yellow, red, bright black, bold), so the bar follows whatever scheme the terminal uses.

Width fitting: a row may use COLUMNS minus a small margin that Claude Code keeps for itself. Each
piece of a row (a segment) has a priority. While the row is too wide, the piece with the highest
priority number is dropped, so cost, lines and reset times go first, then the usage meters; the
branch, the model and the context meter always stay.

The 33k headroom: the context meter does not run to the full context window but to the point where
Claude Code auto-compacts. That point is the auto-compact window (from the environment or the
settings files, else the model's own window) minus 33,000 tokens, which is the 13,000 tokens Claude
Code keeps free plus the 20,000 it reserves for the reply. A meter at 100% means compaction is due.

Standard library only. The branch is read straight from .git/HEAD, with no git subprocess, and
nothing is written to disk. On any error the bar prints one plain `statusbar: <error>` row.
"""
import re

GREEN = 32
YELLOW = 33
RED = 31
DIM = 90  # bright black: icons and separators
BOLD = 1
FILLED = "█"
EMPTY = "░"

SGR_RE = re.compile(r"\x1b\[[0-9;]*m")


def sgr(code: int, text: str) -> str:
    return f"\x1b[{code}m{text}\x1b[0m"


def cells(text: str) -> int:
    """Width in terminal cells: every character counts one, colour codes count none."""
    return len(SGR_RE.sub("", text))


def _round_half_up(x: float) -> int:
    return int(x + 0.5)


def fmt_tokens(n: int) -> str:
    """950 -> 950, 12345 -> 12k, 1234567 -> 1.2M."""
    if n < 1000:
        return str(n)
    if _round_half_up(n / 1000) < 1000:
        return f"{_round_half_up(n / 1000)}k"
    return f"{n / 1_000_000:.1f}".removesuffix(".0") + "M"


def fmt_reset(resets_at: float, now: float) -> str:
    """Time until a usage window resets: 45m, 2h10m, 3d4h. Under a minute or already past is now."""
    minutes = int(resets_at - now) // 60  # rounded down to the minute
    if minutes < 1:
        return "→now"
    if minutes < 60:
        return f"→{minutes}m"
    hours = minutes // 60
    if hours < 24:
        return f"→{hours}h{minutes % 60}m"
    return f"→{hours // 24}d{hours % 24}h"  # minutes would be noise this far out


def meter(pct: float, cells: int) -> str:
    """A bar of `cells` cells filled to pct, coloured by how full it is."""
    filled = max(0, min(cells, _round_half_up(pct / 100 * cells)))
    colour = RED if pct >= 90 else YELLOW if pct >= 70 else GREEN
    return sgr(colour, FILLED * filled + EMPTY * (cells - filled))
