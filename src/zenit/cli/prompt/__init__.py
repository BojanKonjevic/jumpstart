"""Interactive prompt — arrow keys and space to select, enter to confirm.

Works on Unix (termios) and Windows (msvcrt).  Falls back to numbered input
when stdin is not a tty (CI / piped input).
"""

from ._multi import prompt_addons
from ._single import prompt_single_addon, prompt_template

__all__ = ["prompt_template", "prompt_addons", "prompt_single_addon"]
