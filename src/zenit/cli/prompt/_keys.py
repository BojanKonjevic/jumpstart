"""Cross-platform key reader for terminal input."""

from __future__ import annotations

import sys


def read_key() -> str:
    """Return a key identifier string such as ``'\r'``, ``' '``, or ``'\x1b[A'``."""
    if sys.platform == "win32":
        import msvcrt

        ch = msvcrt.getwch()
        if ch in ("\x00", "\xe0"):
            ch2 = msvcrt.getwch()
            if ch2 == "H":
                return "\x1b[A"
            if ch2 == "P":
                return "\x1b[B"
            return ch + ch2
        if ch == "\x03":
            raise KeyboardInterrupt
        return ch
    else:
        import termios
        import tty

        fd = sys.stdin.fileno()
        old = termios.tcgetattr(fd)
        try:
            tty.setraw(fd)
            ch = sys.stdin.read(1)
            if ch == "\x1b":
                ch2 = sys.stdin.read(1)
                ch3 = sys.stdin.read(1)
                return ch + ch2 + ch3
            return ch
        finally:
            termios.tcsetattr(fd, termios.TCSADRAIN, old)


def tty_available() -> bool:
    return sys.stdin.isatty()
