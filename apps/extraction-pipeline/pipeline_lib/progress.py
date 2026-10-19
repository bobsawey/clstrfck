"""Verbose stdout logging + a modest interactive terminal UI for stages.

`StageProgress` wraps a stage's per-file loop with:

- a single redrawing progress-bar line (count, percent, elapsed, ETA, and
  the file currently being worked on),
- timestamped per-item log lines (`verbose`, on by default),
- pause/resume/stop keys: `p` pauses, `r`/space resumes, `q` stops after
  the current item. Ctrl+C likewise stops after the current item; a second
  Ctrl+C aborts immediately.

Keys take effect at the next file boundary -- a slow model call always
finishes (and commits) first. Stopping is a checkpoint, not an abort:
stages commit after every item and skip already-finished work, so
re-running the same command resumes where it left off.

Everything degrades cleanly outside a real terminal: when stdout is not a
TTY there are no ANSI codes and no redraw (plain log lines only, safe to
pipe to a file), and when stdin is not a TTY the keyboard is ignored
(Ctrl+C still checkpoints). Stdlib only -- no curses, no rich.
"""

from __future__ import annotations

import datetime as _dt
import select
import shutil
import signal
import sys
import time

BAR_WIDTH = 22
FILLED = "█"
EMPTY = "░"
SPARK_CHARS = "▁▂▃▄▅▆▇█"


def _now() -> str:
    return _dt.datetime.now().strftime("%H:%M:%S")


def fmt_hms(seconds: float) -> str:
    seconds = max(0, int(seconds))
    minutes, secs = divmod(seconds, 60)
    hours, minutes = divmod(minutes, 60)
    return f"{hours}:{minutes:02d}:{secs:02d}" if hours else f"{minutes}:{secs:02d}"


def human_bytes(n: int) -> str:
    size = float(n)
    for unit in ("B", "KiB", "MiB", "GiB", "TiB"):
        if size < 1024 or unit == "TiB":
            return f"{int(size)} {unit}" if unit == "B" else f"{size:.1f} {unit}"
        size /= 1024
    return f"{n} B"  # unreachable; keeps type checkers happy


def bar_chart(counts: dict, width: int = 26, indent: str = "  ") -> list[str]:
    """Horizontal ASCII bars scaled to the largest count."""
    if not counts:
        return []
    label_w = max(len(str(k)) for k in counts)
    count_w = max(len(str(v)) for v in counts.values())
    peak = max(counts.values()) or 1
    lines = []
    for key, value in counts.items():
        filled = round(width * value / peak)
        if value and filled == 0:
            filled = 1
        lines.append(
            f"{indent}{str(key):<{label_w}}  {value:>{count_w}}  {FILLED * filled}"
        )
    return lines


def sparkline(values: list) -> str:
    if not values:
        return ""
    peak = max(values) or 1.0
    top = len(SPARK_CHARS) - 1
    return "".join(SPARK_CHARS[round(v / peak * top)] for v in values)


class NullProgress:
    """No-op stand-in so stage loops need no `if progress:` branching."""

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def set_total(self, total: int) -> None:
        pass

    def checkpoint(self) -> bool:
        return True

    def item_start(self, label: str) -> None:
        pass

    def item_done(self, label: str, detail: str = "") -> None:
        pass

    def log(self, text: str) -> None:
        pass


class StageProgress:
    """Progress display + pause/resume controller for one stage's loop.

    Usage:

        with StageProgress("extract") as prog:
            prog.set_total(len(items))
            for item in items:
                if not prog.checkpoint():   # False => user asked to stop
                    stats.stopped = True
                    break
                prog.item_start(label)
                ...work...
                prog.item_done(label, "grounded=3 ungrounded=0")
    """

    def __init__(
        self, stage: str, *, verbose: bool = True, interactive: bool = True,
        stream=None,
    ):
        self.stage = stage
        self.verbose = verbose
        self.stream = stream if stream is not None else sys.stdout
        self.total: int | None = None
        self.done = 0
        self.current: str | None = None
        self._t0 = time.monotonic()
        self._paused_secs = 0.0
        self._bar_on_screen = False
        self._stop = False
        self._paused = False
        self._tty_out = interactive and self.stream.isatty()
        self._keys_on = self._tty_out and sys.stdin.isatty()
        self._saved_termios = None
        self._orig_sigint = None

    # -- lifecycle ---------------------------------------------------------

    def __enter__(self):
        self._orig_sigint = signal.signal(signal.SIGINT, self._on_sigint)
        if self._keys_on:
            import termios
            import tty

            self._saved_termios = termios.tcgetattr(sys.stdin.fileno())
            tty.setcbreak(sys.stdin.fileno())
            self.log("keys: [p]ause  [r]esume  [q]uit after current item "
                     "(Ctrl+C does the same; twice aborts)")
        return self

    def __exit__(self, *exc):
        self._clear_bar()
        if self._saved_termios is not None:
            import termios

            termios.tcsetattr(
                sys.stdin.fileno(), termios.TCSADRAIN, self._saved_termios,
            )
            self._saved_termios = None
        if self._orig_sigint is not None:
            signal.signal(signal.SIGINT, self._orig_sigint)
            self._orig_sigint = None
        return False

    def _on_sigint(self, signum, frame):
        if self._stop:
            if self._orig_sigint is not None:
                signal.signal(signal.SIGINT, self._orig_sigint)
            raise KeyboardInterrupt
        self._stop = True
        self._println(
            f"[{_now()}] {self.stage} · Ctrl+C — stopping after the current "
            "item (press again to abort now)"
        )
        self._draw()

    # -- control -----------------------------------------------------------

    def checkpoint(self) -> bool:
        """Handle pending keys; block while paused. False means stop."""
        for key in self._pending_keys():
            self._handle_key(key)
        while self._paused and not self._stop:
            pause_start = time.monotonic()
            self._draw(status="⏸ paused — [r]esume · [q]uit")
            ready = select.select([sys.stdin], [], [], 0.25)[0]
            for _ in ready:
                self._handle_key(sys.stdin.read(1))
            self._paused_secs += time.monotonic() - pause_start
        if self._stop:
            return False
        return True

    def _handle_key(self, key: str) -> None:
        key = key.lower()
        if key == "p" and not self._paused:
            self._paused = True
            self.log(f"paused at {self.done}/{self.total or '?'}")
        elif key in ("r", " ", "p") and self._paused:
            self._paused = False
            self.log("resumed")
        elif key == "q":
            self._stop = True
            self._paused = False
            self.log("stop requested — finishing current item, then checkpointing")

    def _pending_keys(self) -> list:
        keys = []
        if not self._keys_on:
            return keys
        while select.select([sys.stdin], [], [], 0)[0]:
            keys.append(sys.stdin.read(1))
        return keys

    # -- display -----------------------------------------------------------

    def set_total(self, total: int) -> None:
        self.total = total
        self.log(f"{total} item(s) to consider")
        self._draw()

    def item_start(self, label: str) -> None:
        self.current = label
        self._draw()

    def item_done(self, label: str, detail: str = "") -> None:
        self.done += 1
        self.current = None
        if self.verbose:
            counter = (
                f"{self.done}/{self.total}" if self.total is not None else str(self.done)
            )
            line = f"[{_now()}] {self.stage} {counter} {label}"
            if detail:
                line += f" — {detail}"
            self._println(line)
        self._draw()

    def log(self, text: str) -> None:
        self._println(f"[{_now()}] {self.stage} · {text}")
        self._draw()

    def elapsed(self) -> float:
        return time.monotonic() - self._t0 - self._paused_secs

    def _println(self, text: str) -> None:
        if self._bar_on_screen:
            self.stream.write("\r\x1b[K")
            self._bar_on_screen = False
        self.stream.write(text + "\n")
        self.stream.flush()

    def _draw(self, status: str | None = None) -> None:
        if not self._tty_out:
            return
        elapsed = self.elapsed()
        if self.total:
            frac = min(self.done / self.total, 1.0)
            filled = round(BAR_WIDTH * frac)
            bar = FILLED * filled + EMPTY * (BAR_WIDTH - filled)
            line = f"{self.stage} [{bar}] {self.done}/{self.total} {frac * 100:3.0f}%"
            if self.done and self.done < self.total:
                eta = elapsed / self.done * (self.total - self.done)
                line += f" · {fmt_hms(elapsed)} · eta {fmt_hms(eta)}"
            else:
                line += f" · {fmt_hms(elapsed)}"
        else:
            line = f"{self.stage} [{self.done}] · {fmt_hms(elapsed)}"
        if status:
            line += f" · {status}"
        elif self.current:
            line += f" · {self.current}"
        width = shutil.get_terminal_size().columns
        if len(line) > width - 1:
            line = line[: width - 2] + "…"
        self.stream.write("\r\x1b[K" + line)
        self.stream.flush()
        self._bar_on_screen = True

    def _clear_bar(self) -> None:
        if self._bar_on_screen:
            self.stream.write("\r\x1b[K")
            self.stream.flush()
            self._bar_on_screen = False
