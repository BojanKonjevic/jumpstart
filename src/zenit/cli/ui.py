from __future__ import annotations

import itertools
import sys
import threading
import time
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from zenit.core.context import Context

# Enable VT100 / ANSI escape processing on Windows.
# This is a no-op on Windows 10 1511+ and all Unix systems, but required on
# older Windows builds.  Must run before any ANSI codes are written.
if sys.platform == "win32":
    try:
        import ctypes

        kernel32 = ctypes.windll.kernel32
        # Flags: ENABLE_PROCESSED_OUTPUT | ENABLE_WRAP_AT_EOL_OUTPUT |
        #        ENABLE_VIRTUAL_TERMINAL_PROCESSING
        kernel32.SetConsoleMode(kernel32.GetStdHandle(-11), 7)
    except Exception:  # noqa: BLE001 - non-fatal; colours just won't render
        pass

BOLD = "\033[1m"
DIM = "\033[2m"
RED = "\033[0;31m"
GREEN = "\033[0;32m"
YELLOW = "\033[0;33m"
CYAN = "\033[0;36m"
MAGENTA = "\033[1;35m"
BLUE = "\033[0;34m"
RESET = "\033[0m"

_HIDE_CURSOR = "\033[?25l"
_SHOW_CURSOR = "\033[?25h"


def abort() -> None:
    print()
    raise SystemExit(0)


def step(msg: str) -> None:
    print(f"\n{BOLD}{MAGENTA}▸{RESET} {msg}")


def info(msg: str) -> None:
    print(f"  {CYAN}ℹ{RESET}  {msg}")


def success(msg: str) -> None:
    print(f"  {GREEN}✓{RESET}  {msg}")


def warn(msg: str) -> None:
    print(f"  {YELLOW}⚠{RESET}  {msg}", file=sys.stderr)


def error(msg: str) -> None:
    print(f"\n  {RED}✗  {msg}{RESET}", file=sys.stderr)


# ── Dry-run display helpers ───────────────────────────────────────────────────


def dry_header(msg: str) -> None:
    print(f"\n{BOLD}{BLUE}❯ {msg}{RESET}")


def dry_file(path: str, note: str = "", action: str = "create") -> None:
    if action in ("create", "copy"):
        symbol = f"{GREEN}+{RESET}"
    elif action == "append":
        symbol = f"{GREEN}+{RESET}"
        note = note or "(appended)"
    elif action == "modify":
        symbol = f"{GREEN}△{RESET}"
    suffix = f"  {DIM}{note}{RESET}" if note else ""
    print(f"  {symbol} {path}{suffix}")


def dry_cmd(cmd: str) -> None:
    print(f"  {CYAN}${RESET} {DIM}{cmd}{RESET}")


def dry_dep(dep: str, group: str = "") -> None:
    suffix = f"  {DIM}[{group}]{RESET}" if group else ""
    print(f"  {YELLOW}·{RESET} {dep}{suffix}")


def dry_section(title: str) -> None:
    print(f"\n  {BOLD}{DIM}{title}{RESET}")


def addon_summary(action: str, addon_id: str, project_dir: Path, template: str) -> None:
    print(f"\n  {BOLD}Ready to {action} addon:{RESET}")
    print(f"\n    {'addon':<12}  {BOLD}{addon_id}{RESET}")
    print(f"    {'project':<12}  {DIM}{project_dir}{RESET}")
    print(f"    {'template':<12}  {CYAN}{template}{RESET}")
    print()


def dry_run_banner(action: str, addon_id: str) -> None:
    print(
        f"\n  {BOLD}{MAGENTA}Dry run:{RESET} zenit {action} {addon_id}"
        f"  {DIM}(nothing will be written){RESET}\n"
    )


def bullet_list(
    title: str, items: list[str], *, bullet: str, bullet_color: str, suffix: str = ""
) -> None:
    print()
    if title:
        print(f"  {BOLD}{title}{RESET}")
    for item in items:
        suffix_text = f"  {DIM}{suffix}{RESET}" if suffix else ""
        print(f"    {bullet_color}{bullet}{RESET} {item}{suffix_text}")


# ── Confirm prompt ────────────────────────────────────────────────────────────


def confirm(ctx: Context) -> bool:

    template_line = f"{CYAN}{ctx.template}{RESET}"
    addon_line = (
        "  ".join(f"{GREEN}{a}{RESET}" for a in ctx.addons)
        if ctx.addons
        else f"{DIM}none{RESET}"
    )

    print(f"\n  {BOLD}Ready to scaffold:{RESET}")
    print(f"\n    {'name':<12}  {BOLD}{ctx.name}{RESET}")
    print(f"    {'directory':<12}  {DIM}{ctx.project_dir}{RESET}")
    print(f"    {'template':<12}  {template_line}")
    print(f"    {'addons':<12}  {addon_line}")
    print()

    steps = ["copy common files + template"]
    for a in ctx.addons:
        steps.append(f"apply addon: {a}")
    steps += [
        "generate pyproject.toml, justfile",
        "git init + initial commit",
    ]
    for s in steps:
        print(f"    {CYAN}·{RESET}  {DIM}{s}{RESET}")

    print()

    if not sys.stdin.isatty():
        warn(
            "Non-interactive mode - proceeding automatically. Pass --dry-run to preview first."
        )
    return True


# ── Spinner ───────────────────────────────────────────────────────────────────


class _Spinner:
    _FRAMES = ("⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏")
    _INTERVAL = 0.08

    def __init__(self, label: str) -> None:
        self._label = label
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._spin, daemon=True)
        self._tty = sys.stdout.isatty()

    def _spin(self) -> None:
        frames = itertools.cycle(self._FRAMES)
        sys.stdout.write(_HIDE_CURSOR)
        while not self._stop.is_set():
            frame = next(frames)
            sys.stdout.write(f"\r  {MAGENTA}{frame}{RESET}  {self._label}…")
            sys.stdout.flush()
            time.sleep(self._INTERVAL)

    def __enter__(self) -> _Spinner:
        if self._tty:
            self._thread.start()
        else:
            print(f"\n{BOLD}{MAGENTA}▸{RESET} {self._label}…")
        return self

    def __exit__(self, exc_type: object, exc_val: object, exc_tb: object) -> None:
        if self._tty:
            self._stop.set()
            self._thread.join()
            sys.stdout.write("\r\033[2K")
            sys.stdout.write(_SHOW_CURSOR)
            sys.stdout.flush()
        if exc_type is None:
            success(self._label)


def spinner(label: str) -> _Spinner:
    return _Spinner(label)


def print_commands_from_just(project_dir: Path) -> None:
    """Run `just --list` if just is available."""
    import shutil
    import subprocess

    if not shutil.which("just"):
        return
    print()
    subprocess.run(["just", "--list"], cwd=project_dir)
