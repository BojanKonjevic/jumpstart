"""Tests for zenit.cli.prompt — TUI, fallback, rendering, and key reading.

Covers every module in zenit/cli/prompt/:

_keys
    tty_available detection, read_key Unix path (raw byte, escape seq,
    termios restore, ctrl-c).

_render
    Cursor control (hide/show), line helpers (clear_lines, reserve_lines),
    single-select renderer (cursor, unavailable, flash, defaults, line count),
    TUI loop (render, clear, rerender, cursor-show on exit/exception),
    and fallback numbered-list picker (by number, by name, default, retry,
    unavailable, eof, keyboard-interrupt).

_single
    TUI path for prompt_template (navigation, vi keys, wrap, preselected
    default, ctrl-c) and prompt_single_addon (navigation, unavailable flash,
    template-required flash).  Also covers the _fallback_single_add path and
    the existing _fallback_template tests.

_multi
    Multi-select renderer (cursor, selected, locked, incompatible, requires
    hints, flash, defaults, line counts) and the full _tui_multi state
    machine: space toggling, dependency auto-select, dependency locking,
    always-locked immovability, incompatible rejection, default preselection,
    incompatible stripping, and ctrl-c.  Also covers prompt_addons entry
    point (empty available, TUI path with incompatible filtering) and the
    existing _fallback_multi tests.
"""

from __future__ import annotations

import sys
from unittest.mock import MagicMock, patch

import pytest

from zenit.cli.prompt._keys import read_key, tty_available
from zenit.cli.prompt._multi import (
    _fallback_multi,
    _fallback_multi_addon,
    _render_multi,
    _tui_multi,
    prompt_addons,
    prompt_multi_addon,
)
from zenit.cli.prompt._render import (
    _DONE,
    clear_lines,
    filter_indices,
    hide_cursor,
    render_single,
    reserve_lines,
    run_fallback,
    run_tui,
    show_cursor,
)
from zenit.cli.prompt._single import (
    _fallback_single_add,
    _fallback_template,
    prompt_single_addon,
    prompt_template,
)
from zenit.schema.models import AddonMeta

# ═══════════════════════════════════════════════════════════════════════════════
# _keys
# ═══════════════════════════════════════════════════════════════════════════════


class TestTtyAvailable:
    def test_true_when_isatty(self) -> None:
        with patch.object(sys.stdin, "isatty", return_value=True):
            assert tty_available() is True

    def test_false_when_not_isatty(self) -> None:
        with patch.object(sys.stdin, "isatty", return_value=False):
            assert tty_available() is False


@pytest.mark.skipif(sys.platform == "win32", reason="Unix-specific test")
class TestReadKeyUnix:
    """read_key() Unix path — replaces sys.modules entries so that the
    lazy ``import termios`` / ``import tty`` inside the function body
    resolve to mocks."""

    _STDIN_READ_PATCH = "sys.stdin.read"
    _STDIN_FILENO_PATCH = "sys.stdin.fileno"

    @pytest.fixture(autouse=True)
    def _mock_termios(self) -> None:
        """Replace termios/tty in sys.modules before each test and restore."""
        self._mock_termios_mod = MagicMock()
        self._mock_termios_mod.tcgetattr.return_value = MagicMock()
        self._mock_tty_mod = MagicMock()

        self._real_termios = sys.modules.get("termios")
        self._real_tty = sys.modules.get("tty")
        sys.modules["termios"] = self._mock_termios_mod
        sys.modules["tty"] = self._mock_tty_mod

    def teardown_method(self) -> None:
        if self._real_termios:
            sys.modules["termios"] = self._real_termios
        elif "termios" in sys.modules:
            del sys.modules["termios"]
        if self._real_tty:
            sys.modules["tty"] = self._real_tty
        elif "tty" in sys.modules:
            del sys.modules["tty"]

    def test_reads_single_byte(self) -> None:
        with (
            patch(self._STDIN_FILENO_PATCH, return_value=0),
            patch(self._STDIN_READ_PATCH, return_value="j"),
        ):
            assert read_key() == "j"
        self._mock_tty_mod.setraw.assert_called_once()

    def test_reads_escape_sequence(self) -> None:
        with (
            patch(self._STDIN_FILENO_PATCH, return_value=0),
            patch(self._STDIN_READ_PATCH, side_effect=["\x1b", "[", "A"]),
        ):
            assert read_key() == "\x1b[A"

    def test_restores_termios_after_read(self) -> None:
        with (
            patch(self._STDIN_FILENO_PATCH, return_value=0),
            patch(self._STDIN_READ_PATCH, return_value="a"),
        ):
            read_key()
        self._mock_termios_mod.tcsetattr.assert_called_once()

    def test_ctrl_c_returns_raw_byte_on_unix(self) -> None:
        """On Unix, read_key() returns the raw \\x03 byte — tty.setraw()
        suppresses SIGINT so the caller (run_tui / on_key) must handle it
        explicitly by checking for ``\\x03``."""
        with (
            patch(self._STDIN_FILENO_PATCH, return_value=0),
            patch(self._STDIN_READ_PATCH, return_value="\x03"),
        ):
            assert read_key() == "\x03"


# ═══════════════════════════════════════════════════════════════════════════════
# _render — cursor control / line helpers
# ═══════════════════════════════════════════════════════════════════════════════


class TestHideShowCursor:
    def test_hide_cursor_writes_ansi(self, capsys: pytest.CaptureFixture[str]) -> None:
        hide_cursor()
        assert capsys.readouterr().out == "\033[?25l"

    def test_show_cursor_writes_ansi(self, capsys: pytest.CaptureFixture[str]) -> None:
        show_cursor()
        assert capsys.readouterr().out == "\033[?25h"


class TestClearLines:
    def test_clear_single_line(self, capsys: pytest.CaptureFixture[str]) -> None:
        clear_lines(1)
        out = capsys.readouterr().out
        assert out.count("\033[2K\r") == 2
        assert out.count("\033[A") == 1

    def test_clear_multiple_lines(self, capsys: pytest.CaptureFixture[str]) -> None:
        clear_lines(3)
        out = capsys.readouterr().out
        assert out.count("\033[2K\r") == 4
        assert out.count("\033[A") == 3


class TestReserveLines:
    def test_reserves_blank_lines(self, capsys: pytest.CaptureFixture[str]) -> None:
        reserve_lines(2)
        assert capsys.readouterr().out == "\n" * 2


# ═══════════════════════════════════════════════════════════════════════════════
# _render — render_single
# ═══════════════════════════════════════════════════════════════════════════════


class TestRenderSingle:
    """render_single() is the TUI single-select list renderer.

    Assertions use visible character patterns rather than exact ANSI codes
    so that tests remain robust if colour constants change in ui.py.
    """

    ITEMS: list[tuple[str, str]] = [
        ("blank", "minimal setup"),
        ("fastapi", "full web framework"),
    ]

    def test_renders_all_items(self, capsys: pytest.CaptureFixture[str]) -> None:
        lines = render_single(self.ITEMS, cursor=0)
        captured = capsys.readouterr()
        assert "blank" in captured.out
        assert "fastapi" in captured.out
        assert lines > 0

    def test_cursor_line_has_arrow(self, capsys: pytest.CaptureFixture[str]) -> None:
        render_single(self.ITEMS, cursor=0)
        first_line = capsys.readouterr().out.split("\n")[0]
        assert "›" in first_line

    def test_non_cursor_line_has_empty(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        render_single(self.ITEMS, cursor=0)
        second_line = capsys.readouterr().out.split("\n")[1]
        assert "○" in second_line

    def test_unavailable_shows_cross(self, capsys: pytest.CaptureFixture[str]) -> None:
        render_single(self.ITEMS, cursor=0, unavailable={1})
        captured = capsys.readouterr()
        assert "—" in captured.out

    def test_default_indicator_on_non_cursor(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        render_single(self.ITEMS, cursor=1, default_name="blank")
        captured = capsys.readouterr()
        assert "(default)" in captured.out

    def test_default_not_shown_on_cursor(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        render_single(self.ITEMS, cursor=0, default_name="blank")
        captured = capsys.readouterr()
        assert captured.out.count("(default)") == 0

    def test_flash_message_displayed(self, capsys: pytest.CaptureFixture[str]) -> None:
        render_single(self.ITEMS, cursor=0, flash="some warning")
        captured = capsys.readouterr()
        assert "some warning" in captured.out

    def test_no_flash_shows_hint(self, capsys: pytest.CaptureFixture[str]) -> None:
        render_single(self.ITEMS, cursor=0)
        captured = capsys.readouterr()
        assert "enter" in captured.out.lower()

    def test_returns_line_count(self, capsys: pytest.CaptureFixture[str]) -> None:
        assert render_single(self.ITEMS, cursor=0) == len(self.ITEMS) + 2

    def test_returns_line_count_with_flash(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        assert render_single(self.ITEMS, cursor=0, flash="x") == len(self.ITEMS) + 2

    def test_unavailable_reason_in_hint(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        items = [("a", "A"), ("b", "B")]
        full = [("a", "A", []), ("b", "B", ["redis"])]
        render_single(items, cursor=0, unavailable={1}, full_items=full)
        assert "needs" in capsys.readouterr().out

    def test_search_query_shows_footer(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        render_single(self.ITEMS, cursor=0, search_query="bla")
        assert "esc clear" in capsys.readouterr().out

    def test_search_shows_type_hint_by_default(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        render_single(self.ITEMS, cursor=0)
        assert "type to search" in capsys.readouterr().out

    def test_filtered_indices_shows_subset(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        render_single(self.ITEMS, cursor=0, filtered_indices=[1])
        captured = capsys.readouterr()
        assert "blank" not in captured.out
        assert "fastapi" in captured.out

    def test_filtered_indices_empty_shows_no_matches(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        render_single(self.ITEMS, cursor=0, filtered_indices=[])
        assert "No matches" in capsys.readouterr().out


# ═══════════════════════════════════════════════════════════════════════════════
# _render — filter_indices


class TestFilterIndices:
    ITEMS: list[tuple[str, str]] = [
        ("docker", "Container support"),
        ("redis", "Redis cache"),
        ("celery", "Task queue"),
    ]

    def test_empty_query_returns_all(self) -> None:
        assert filter_indices(self.ITEMS, "") == [0, 1, 2]

    def test_matches_name(self) -> None:
        assert filter_indices(self.ITEMS, "docker") == [0]

    def test_matches_description(self) -> None:
        assert filter_indices(self.ITEMS, "cache") == [1]

    def test_case_insensitive(self) -> None:
        assert filter_indices(self.ITEMS, "DOCKER") == [0]

    def test_matches_multiple(self) -> None:
        assert filter_indices(self.ITEMS, "e") == [0, 1, 2]

    def test_no_match(self) -> None:
        assert filter_indices(self.ITEMS, "zzzz") == []


# ═══════════════════════════════════════════════════════════════════════════════
# _render — run_tui
# ═══════════════════════════════════════════════════════════════════════════════


class TestRunTui:
    """run_tui() orchestration: render → read_key → on_key → loop."""

    def test_calls_render_once_on_immediate_done(self) -> None:
        render = MagicMock(return_value=0)
        on_key = MagicMock(return_value=_DONE)
        with patch("zenit.cli.prompt._render.read_key", return_value="\r"):
            run_tui(render, on_key)
        render.assert_called_once()

    def test_calls_on_key_with_each_key(self) -> None:
        render = MagicMock(return_value=0)
        on_key = MagicMock(side_effect=[None, _DONE])
        with patch("zenit.cli.prompt._render.read_key", side_effect=["a", "\r"]):
            run_tui(render, on_key)
        on_key.assert_any_call("a")
        on_key.assert_any_call("\r")

    def test_breaks_when_on_key_returns_done(self) -> None:
        render = MagicMock(return_value=0)
        on_key = MagicMock(return_value=_DONE)
        with patch("zenit.cli.prompt._render.read_key", return_value="\r"):
            run_tui(render, on_key)
        assert on_key.call_count == 1

    def test_clears_and_rerenders_when_continued(self) -> None:
        render = MagicMock(return_value=1)
        on_key = MagicMock(side_effect=[None, None, _DONE])
        with patch("zenit.cli.prompt._render.read_key", side_effect=["a", "b", "\r"]):
            run_tui(render, on_key)
        assert render.call_count == 3

    def test_shows_cursor_on_normal_exit(self) -> None:
        render = MagicMock(return_value=0)
        on_key = MagicMock(return_value=_DONE)
        with (
            patch("zenit.cli.prompt._render.read_key", return_value="\r"),
            patch("zenit.cli.prompt._render.show_cursor") as show,
        ):
            run_tui(render, on_key)
        show.assert_called_once()

    def test_shows_cursor_on_exception(self) -> None:
        render = MagicMock(return_value=0)
        on_key = MagicMock(side_effect=ValueError("boom"))
        with (
            patch("zenit.cli.prompt._render.read_key", return_value="\r"),
            patch("zenit.cli.prompt._render.show_cursor") as show,
            pytest.raises(ValueError),
        ):
            run_tui(render, on_key)
        show.assert_called_once()

    def test_hides_cursor_on_entry(self) -> None:
        render = MagicMock(return_value=0)
        on_key = MagicMock(return_value=_DONE)
        with (
            patch("zenit.cli.prompt._render.read_key", return_value="\r"),
            patch("zenit.cli.prompt._render.hide_cursor") as hide,
        ):
            run_tui(render, on_key)
        hide.assert_called_once()


# ═══════════════════════════════════════════════════════════════════════════════
# _render — run_fallback
# ═══════════════════════════════════════════════════════════════════════════════


class TestRunFallback:
    """run_fallback() — numbered-list non-TTY picker."""

    ITEMS: list[tuple[str, str]] = [("a", "Item A"), ("b", "Item B")]

    def test_select_by_number(self) -> None:
        with patch("builtins.input", return_value="2"):
            assert run_fallback(self.ITEMS) == 1

    def test_select_by_name(self) -> None:
        with patch("builtins.input", return_value="a"):
            assert run_fallback(self.ITEMS) == 0

    def test_enter_returns_default(self) -> None:
        with patch("builtins.input", return_value=""):
            assert run_fallback(self.ITEMS, default_name="a") == 0

    def test_enter_returns_none_when_no_default(self) -> None:
        with patch("builtins.input", return_value=""):
            assert run_fallback(self.ITEMS) is None

    def test_unknown_input_retries(self) -> None:
        with patch("builtins.input", side_effect=["z", "1"]):
            assert run_fallback(self.ITEMS) == 0

    def test_unavailable_shows_warning_and_retries(self) -> None:
        with patch("builtins.input", side_effect=["1", "2"]):
            assert run_fallback(self.ITEMS, unavailable={0}) == 1

    def test_eof_exits(self) -> None:
        with (
            patch("builtins.input", side_effect=EOFError),
            pytest.raises(SystemExit) as exc,
        ):
            run_fallback(self.ITEMS)
        assert exc.value.code == 0

    def test_keyboard_interrupt_exits(self) -> None:
        with (
            patch("builtins.input", side_effect=KeyboardInterrupt),
            pytest.raises(SystemExit),
        ):
            run_fallback(self.ITEMS)


# ═══════════════════════════════════════════════════════════════════════════════
# _single — fallback_template  (existing tests preserved)
# ═══════════════════════════════════════════════════════════════════════════════


def test_fallback_template_select_by_number_1() -> None:
    with patch("builtins.input", return_value="1"):
        assert _fallback_template() == "blank"


def test_fallback_template_select_by_number_2() -> None:
    with patch("builtins.input", return_value="2"):
        assert _fallback_template() == "fastapi"


def test_fallback_template_select_by_name_blank() -> None:
    with patch("builtins.input", return_value="blank"):
        assert _fallback_template() == "blank"


def test_fallback_template_select_by_name_fastapi() -> None:
    with patch("builtins.input", return_value="fastapi"):
        assert _fallback_template() == "fastapi"


def test_fallback_template_case_insensitive() -> None:
    with patch("builtins.input", return_value="BLANK"):
        assert _fallback_template() == "blank"


def test_fallback_template_retries_on_invalid_then_accepts() -> None:
    with patch("builtins.input", side_effect=["99", "1"]):
        assert _fallback_template() == "blank"


def test_fallback_template_retries_multiple_times() -> None:
    with patch("builtins.input", side_effect=["x", "y", "z", "2"]):
        assert _fallback_template() == "fastapi"


def test_fallback_template_eof_raises_system_exit() -> None:
    with (
        patch("builtins.input", side_effect=EOFError),
        pytest.raises(SystemExit) as exc,
    ):
        _fallback_template()
    assert exc.value.code == 0


def test_fallback_template_keyboard_interrupt_raises_system_exit() -> None:
    with (
        patch("builtins.input", side_effect=KeyboardInterrupt),
        pytest.raises(SystemExit) as exc,
    ):
        _fallback_template()
    assert exc.value.code == 0


# ═══════════════════════════════════════════════════════════════════════════════
# _single — _fallback_single_add
# ═══════════════════════════════════════════════════════════════════════════════


class TestFallbackSingleAdd:
    """_fallback_single_add() — non-TTY single-addon picker."""

    ITEMS: list[tuple[str, str, list[str]]] = [
        ("docker", "Docker support", []),
        ("redis", "Redis cache", []),
    ]

    def test_select_first(self) -> None:
        with patch("builtins.input", return_value="1"):
            assert _fallback_single_add(self.ITEMS, set()) == "docker"

    def test_select_second(self) -> None:
        with patch("builtins.input", return_value="2"):
            assert _fallback_single_add(self.ITEMS, set()) == "redis"

    def test_enter_returns_none(self) -> None:
        with patch("builtins.input", return_value=""):
            assert _fallback_single_add(self.ITEMS, set()) is None


# ═══════════════════════════════════════════════════════════════════════════════
# _single — prompt_template TUI path
# ═══════════════════════════════════════════════════════════════════════════════


class TestPromptTemplateTui:
    """prompt_template() TUI path via mocked keystrokes."""

    def test_default_selected_first(self) -> None:
        with (
            patch("zenit.cli.prompt._render.read_key", return_value="\r"),
            patch("zenit.cli.prompt._single.tty_available", return_value=True),
        ):
            assert prompt_template() == "blank"

    def test_navigate_down_selects_second(self) -> None:
        with (
            patch("zenit.cli.prompt._render.read_key", side_effect=["\x1b[B", "\r"]),
            patch("zenit.cli.prompt._single.tty_available", return_value=True),
        ):
            assert prompt_template() == "fastapi"

    def test_navigate_up_wraps_to_last(self) -> None:
        with (
            patch("zenit.cli.prompt._render.read_key", side_effect=["\x1b[A", "\r"]),
            patch("zenit.cli.prompt._single.tty_available", return_value=True),
        ):
            assert prompt_template() == "fastapi"

    def test_j_is_search_char(self) -> None:
        """j is a search character, not navigation — filtering to nothing,
        then escape to clear, enter to confirm default."""
        with (
            patch("zenit.cli.prompt._render.read_key", side_effect=["j", "\x1b", "\r"]),
            patch("zenit.cli.prompt._single.tty_available", return_value=True),
        ):
            assert prompt_template() == "blank"

    def test_k_is_search_char(self) -> None:
        """k is a search character, not navigation — filtering to nothing,
        then escape to clear, enter to confirm default."""
        with (
            patch("zenit.cli.prompt._render.read_key", side_effect=["k", "\x1b", "\r"]),
            patch("zenit.cli.prompt._single.tty_available", return_value=True),
        ):
            assert prompt_template() == "blank"

    def test_ctrl_c_exits(self) -> None:
        with (
            patch("zenit.cli.prompt._render.read_key", return_value="\x03"),
            patch("zenit.cli.prompt._single.tty_available", return_value=True),
            pytest.raises(SystemExit),
        ):
            prompt_template()

    def test_default_template_pre_selected(self) -> None:
        with (
            patch("zenit.cli.prompt._render.read_key", return_value="\r"),
            patch("zenit.cli.prompt._single.tty_available", return_value=True),
        ):
            assert prompt_template(default="fastapi") == "fastapi"

    def test_search_filters_to_one(self) -> None:
        with (
            patch(
                "zenit.cli.prompt._render.read_key",
                side_effect=["f", "a", "\r"],
            ),
            patch("zenit.cli.prompt._single.tty_available", return_value=True),
        ):
            assert prompt_template() == "fastapi"

    def test_search_escape_clears(self) -> None:
        with (
            patch(
                "zenit.cli.prompt._render.read_key",
                side_effect=["f", "\x1b", "\r"],
            ),
            patch("zenit.cli.prompt._single.tty_available", return_value=True),
        ):
            assert prompt_template() == "blank"

    def test_search_backspace_edits(self) -> None:
        with (
            patch(
                "zenit.cli.prompt._render.read_key",
                side_effect=["x", "\x7f", "\r"],
            ),
            patch("zenit.cli.prompt._single.tty_available", return_value=True),
        ):
            assert prompt_template() == "blank"

    def test_search_j_registered_as_search_when_active(self) -> None:
        with (
            patch(
                "zenit.cli.prompt._render.read_key",
                side_effect=["a", "j", "\x1b", "\r"],
            ),
            patch("zenit.cli.prompt._single.tty_available", return_value=True),
        ):
            # "a" starts search, "j" should add to query (not navigate down),
            # then escape clears, enter confirms default
            assert prompt_template() == "blank"

    def test_search_k_registered_as_search_when_active(self) -> None:
        with (
            patch(
                "zenit.cli.prompt._render.read_key",
                side_effect=["a", "k", "\x1b", "\r"],
            ),
            patch("zenit.cli.prompt._single.tty_available", return_value=True),
        ):
            # "a" starts search, "k" should add to query (not navigate up),
            # then escape clears, enter confirms default
            assert prompt_template() == "blank"


# ═══════════════════════════════════════════════════════════════════════════════
# _single — prompt_single_addon TUI path
# ═══════════════════════════════════════════════════════════════════════════════


class TestPromptSingleAddonTui:
    """prompt_single_addon() TUI path via mocked keystrokes."""

    ITEMS: list[tuple[str, str, list[str]]] = [
        ("docker", "Docker support", []),
        ("redis", "Redis cache", []),
        ("celery", "Task queue", ["redis"]),
    ]

    def test_selects_first_addon(self) -> None:
        with (
            patch("zenit.cli.prompt._render.read_key", return_value="\r"),
            patch("zenit.cli.prompt._single.tty_available", return_value=True),
        ):
            assert prompt_single_addon(self.ITEMS) == "docker"

    def test_selects_second_after_navigation(self) -> None:
        with (
            patch("zenit.cli.prompt._render.read_key", side_effect=["\x1b[B", "\r"]),
            patch("zenit.cli.prompt._single.tty_available", return_value=True),
        ):
            assert prompt_single_addon(self.ITEMS) == "redis"

    def test_unavailable_addon_shows_flash_and_stays_in_loop(self) -> None:
        """Pressing enter on an unavailable item emits a flash and stays in
        the loop — the user must move to an available item to confirm."""
        keys = iter(["\x1b[B", "\x1b[B", "\r", "\x1b[A", "\r"])
        with (
            patch("zenit.cli.prompt._render.read_key", side_effect=keys),
            patch("zenit.cli.prompt._single.tty_available", return_value=True),
        ):
            result = prompt_single_addon(self.ITEMS, unavailable_indices={2})
        assert result == "redis"

    def test_template_required_shows_flash(self) -> None:
        items = [
            ("docker", "Docker", []),
            ("sentry", "Sentry", ["__template__fastapi"]),
        ]
        keys = iter(["\x1b[B", "\r", "\x1b[A", "\r"])
        with (
            patch("zenit.cli.prompt._render.read_key", side_effect=keys),
            patch("zenit.cli.prompt._single.tty_available", return_value=True),
        ):
            assert prompt_single_addon(items, unavailable_indices={1}) == "docker"

    def test_ctrl_c_exits(self) -> None:
        with (
            patch("zenit.cli.prompt._render.read_key", return_value="\x03"),
            patch("zenit.cli.prompt._single.tty_available", return_value=True),
            pytest.raises(SystemExit),
        ):
            prompt_single_addon(self.ITEMS)

    def test_search_filters_selection(self) -> None:
        with (
            patch("zenit.cli.prompt._render.read_key", side_effect=["c", "e", "\r"]),
            patch("zenit.cli.prompt._single.tty_available", return_value=True),
        ):
            assert prompt_single_addon(self.ITEMS) == "celery"

    def test_search_escape_then_navigate(self) -> None:
        keys = iter(["c", "\x1b", "\x1b[B", "\r"])
        with (
            patch("zenit.cli.prompt._render.read_key", side_effect=keys),
            patch("zenit.cli.prompt._single.tty_available", return_value=True),
        ):
            assert prompt_single_addon(self.ITEMS) == "redis"

    def test_search_j_registered_as_search_when_active(self) -> None:
        items = [
            ("docker", "Docker support", []),
            ("redis", "Redis cache", []),
        ]
        keys = iter(["a", "j", "\x1b", "\r"])
        with (
            patch("zenit.cli.prompt._render.read_key", side_effect=keys),
            patch("zenit.cli.prompt._single.tty_available", return_value=True),
        ):
            # "a" starts search, "j" adds to query (not navigate),
            # escape clears, enter confirms first item
            assert prompt_single_addon(items) == "docker"


# ═══════════════════════════════════════════════════════════════════════════════
# _multi — _render_multi
# ═══════════════════════════════════════════════════════════════════════════════


class TestRenderMulti:
    """_render_multi() — multi-select TUI renderer.

    Assertions use visible characters (›, ●, ○, —) rather than exact
    ANSI codes so that tests remain robust if colour constants change.
    """

    ITEMS: list[tuple[str, str]] = [
        ("docker", "Container support"),
        ("redis", "Redis cache"),
        ("celery", "Task queue"),
    ]

    def test_renders_all_items(self, capsys: pytest.CaptureFixture[str]) -> None:
        _render_multi(self.ITEMS, cursor=0, selected=set(), requires_map={})
        captured = capsys.readouterr()
        for name, desc in self.ITEMS:
            assert name in captured.out
            assert desc in captured.out

    def test_cursor_line_has_arrow(self, capsys: pytest.CaptureFixture[str]) -> None:
        _render_multi(self.ITEMS, cursor=1, selected=set(), requires_map={})
        lines = capsys.readouterr().out.split("\n")
        cursor_line = lines[1]  # cursor=1 → second line
        assert "›" in cursor_line
        assert "redis" in cursor_line

    def test_non_cursor_lines_have_no_arrow(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        _render_multi(self.ITEMS, cursor=1, selected=set(), requires_map={})
        lines = capsys.readouterr().out.split("\n")
        assert "›" not in lines[0]
        assert "›" not in lines[2]

    def test_selected_shows_check(self, capsys: pytest.CaptureFixture[str]) -> None:
        _render_multi(self.ITEMS, cursor=0, selected={1}, requires_map={})
        captured = capsys.readouterr()
        assert "●" in captured.out

    def test_empty_unselected(self, capsys: pytest.CaptureFixture[str]) -> None:
        _render_multi(self.ITEMS, cursor=0, selected=set(), requires_map={})
        captured = capsys.readouterr()
        assert "○" in captured.out

    def test_locked_shows_locked_indicator(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        _render_multi(self.ITEMS, cursor=0, selected=set(), requires_map={}, locked={0})
        captured = capsys.readouterr()
        assert "●" in captured.out

    def test_incompatible_shows_cross(self, capsys: pytest.CaptureFixture[str]) -> None:
        _render_multi(
            self.ITEMS,
            cursor=0,
            selected=set(),
            requires_map={},
            incompatible={2},
        )
        captured = capsys.readouterr()
        assert "—" in captured.out
        assert "celery" in captured.out

    def test_requires_hint_displayed(self, capsys: pytest.CaptureFixture[str]) -> None:
        _render_multi(
            self.ITEMS, cursor=1, selected=set(), requires_map={"celery": ["redis"]}
        )
        captured = capsys.readouterr()
        assert "needs" in captured.out

    def test_flash_replaces_hint(self, capsys: pytest.CaptureFixture[str]) -> None:
        _render_multi(self.ITEMS, cursor=0, selected=set(), requires_map={}, flash="x")
        captured = capsys.readouterr()
        assert "x" in captured.out

    def test_hint_when_no_flash(self, capsys: pytest.CaptureFixture[str]) -> None:
        _render_multi(self.ITEMS, cursor=0, selected=set(), requires_map={})
        captured = capsys.readouterr()
        assert "navigate" in captured.out.lower()

    def test_returns_line_count(self, capsys: pytest.CaptureFixture[str]) -> None:
        lines = _render_multi(self.ITEMS, cursor=0, selected=set(), requires_map={})
        assert lines == len(self.ITEMS) + 2

    def test_default_indicator(self, capsys: pytest.CaptureFixture[str]) -> None:
        _render_multi(
            self.ITEMS,
            cursor=2,
            selected=set(),
            requires_map={},
            default_selected={0},
        )
        captured = capsys.readouterr()
        assert "default" in captured.out

    def test_default_not_on_cursor_item(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        _render_multi(
            self.ITEMS,
            cursor=0,
            selected=set(),
            requires_map={},
            default_selected={0},
        )
        captured = capsys.readouterr()
        assert captured.out.count("default") == 0

    def test_incompatible_hint(self, capsys: pytest.CaptureFixture[str]) -> None:
        _render_multi(
            self.ITEMS,
            cursor=0,
            selected=set(),
            requires_map={},
            incompatible={2},
        )
        captured = capsys.readouterr()
        assert "only" in captured.out

    def test_search_query_shows_esc_footer(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        _render_multi(
            self.ITEMS,
            cursor=0,
            selected=set(),
            requires_map={},
            search_query="red",
        )
        assert "esc clear" in capsys.readouterr().out

    def test_search_empty_shows_type_hint(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        _render_multi(
            self.ITEMS,
            cursor=0,
            selected=set(),
            requires_map={},
        )
        assert "type to search" in capsys.readouterr().out

    def test_filtered_indices_shows_subset(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        _render_multi(
            self.ITEMS,
            cursor=0,
            selected=set(),
            requires_map={},
            filtered_indices=[1],
        )
        captured = capsys.readouterr()
        assert "docker" not in captured.out
        assert "redis" in captured.out

    def test_filtered_empty_shows_no_matches(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        _render_multi(
            self.ITEMS,
            cursor=0,
            selected=set(),
            requires_map={},
            filtered_indices=[],
        )
        assert "No matches" in capsys.readouterr().out


# ═══════════════════════════════════════════════════════════════════════════════
# _multi — _tui_multi state machine
# ═══════════════════════════════════════════════════════════════════════════════


class TestTuiMulti:
    """_tui_multi() — full multi-select TUI with keyboard-driven state.

    Tests inject keystrokes via patching _render.read_key and verify the
    returned addon list.
    """

    ITEMS: list[tuple[str, str]] = [
        ("docker", "Docker support"),
        ("redis", "Redis cache"),
        ("celery", "Task queue"),
    ]

    def test_enter_with_no_selection_returns_empty(self) -> None:
        with patch("zenit.cli.prompt._render.read_key", return_value="\r"):
            assert _tui_multi("test", self.ITEMS, {}, set()) == []

    def test_space_toggles_selection(self) -> None:
        with patch("zenit.cli.prompt._render.read_key", side_effect=[" ", "\r"]):
            assert _tui_multi("test", self.ITEMS, {}, set()) == ["docker"]

    def test_space_toggles_off_selection(self) -> None:
        with patch("zenit.cli.prompt._render.read_key", side_effect=[" ", " ", "\r"]):
            assert _tui_multi("test", self.ITEMS, {}, set()) == []

    def test_multiple_selections(self) -> None:
        with patch(
            "zenit.cli.prompt._render.read_key",
            side_effect=[" ", "\x1b[B", " ", "\r"],
        ):
            result = _tui_multi("test", self.ITEMS, {}, set())
        assert "docker" in result
        assert "redis" in result

    def test_select_auto_includes_deps(self) -> None:
        with patch(
            "zenit.cli.prompt._render.read_key",
            side_effect=["\x1b[B", "\x1b[B", " ", "\r"],
        ):
            result = _tui_multi("test", self.ITEMS, {"celery": ["redis"]}, set())
        assert "celery" in result
        assert "redis" in result

    def test_locked_items_remain_in_result(self) -> None:
        with patch("zenit.cli.prompt._render.read_key", return_value="\r"):
            result = _tui_multi("test", self.ITEMS, {}, always_locked={0})
        assert "docker" in result

    def test_locked_item_cannot_be_toggled_off(self) -> None:
        with patch("zenit.cli.prompt._render.read_key", side_effect=[" ", "\r"]):
            result = _tui_multi("test", self.ITEMS, {}, always_locked={0})
        assert "docker" in result

    def test_toggling_dep_auto_locks_requirement(self) -> None:
        """Selecting celery locks redis in place — toggling redis shows
        a flash but doesn't remove it from the result."""
        keys = iter(["\x1b[B", "\x1b[B", " ", "\x1b[A", " ", "\r"])
        with patch("zenit.cli.prompt._render.read_key", side_effect=keys):
            result = _tui_multi("test", self.ITEMS, {"celery": ["redis"]}, set())
        assert "celery" in result
        assert "redis" in result

    def test_incompatible_cannot_be_selected(self) -> None:
        keys = iter(["\x1b[B", "\x1b[B", " ", "\r"])
        with patch("zenit.cli.prompt._render.read_key", side_effect=keys):
            result = _tui_multi("test", self.ITEMS, {}, set(), incompatible={2})
        assert "celery" not in result

    def test_incompatible_stripped_from_final_selection(self) -> None:
        with patch("zenit.cli.prompt._render.read_key", return_value="\r"):
            result = _tui_multi(
                "test",
                self.ITEMS,
                {},
                set(),
                default_selected={0, 2},
                incompatible={2},
            )
        assert "docker" in result
        assert "celery" not in result

    def test_defaults_pre_selected(self) -> None:
        with patch("zenit.cli.prompt._render.read_key", return_value="\r"):
            result = _tui_multi("test", self.ITEMS, {}, set(), default_selected={0, 2})
        assert "docker" in result
        assert "celery" in result

    def test_default_selected_with_deps(self) -> None:
        """Default_selected must already include transitive deps when
        passed to _tui_multi — this mirrors what prompt_addons does."""
        with patch("zenit.cli.prompt._render.read_key", return_value="\r"):
            result = _tui_multi(
                "test",
                self.ITEMS,
                {"celery": ["redis"]},
                set(),
                default_selected={1, 2},  # redis + celery
            )
        assert "celery" in result
        assert "redis" in result

    def test_ctrl_c_exits(self) -> None:
        with (
            patch("zenit.cli.prompt._render.read_key", return_value="\x03"),
            patch("zenit.cli.prompt._multi.show_cursor"),
            pytest.raises(SystemExit),
        ):
            _tui_multi("test", self.ITEMS, {}, set())

    def test_search_filters_and_selects(self) -> None:
        with patch(
            "zenit.cli.prompt._render.read_key",
            side_effect=["r", "e", " ", "\r"],
        ):
            result = _tui_multi("test", self.ITEMS, {}, set())
        assert "docker" not in result
        assert "redis" in result

    def test_search_escape_clears_then_select_all(self) -> None:
        with patch(
            "zenit.cli.prompt._render.read_key",
            side_effect=["r", "\x1b", " ", "\x1b[B", " ", "\x1b[B", " ", "\r"],
        ):
            result = _tui_multi("test", self.ITEMS, {}, set())
        assert len(result) == 3

    def test_search_backspace_restores_items(self) -> None:
        with patch(
            "zenit.cli.prompt._render.read_key",
            side_effect=["r", "e", "\x7f", " ", "\r"],
        ):
            result = _tui_multi("test", self.ITEMS, {}, set())
        # After typing "re" → matches redis; backspace → "r" → matches redis, docker
        # " " toggles first match (docker after backspace, since filtered list is [docker, redis], cursor=0)
        assert "docker" in result

    def test_search_no_match_then_escape(self) -> None:
        with patch(
            "zenit.cli.prompt._render.read_key",
            side_effect=["z", "z", "\x1b", " ", "\r"],
        ):
            result = _tui_multi("test", self.ITEMS, {}, set())
        assert "docker" in result

    def test_search_j_registered_as_search_when_active(self) -> None:
        with patch(
            "zenit.cli.prompt._render.read_key",
            side_effect=["a", "j", "\x1b", " ", "\r"],
        ):
            # "a" starts search, "j" adds to query (not navigate down),
            # escape clears, space selects first, enter confirms
            result = _tui_multi("test", self.ITEMS, {}, set())
        assert "docker" in result


# ═══════════════════════════════════════════════════════════════════════════════
# _multi — prompt_addons entry point
# ═══════════════════════════════════════════════════════════════════════════════


class TestPromptAddons:
    """prompt_addons() — dispatches to TUI or fallback based on tty."""

    def test_empty_available_returns_empty(self) -> None:
        assert prompt_addons([], template="blank") == []

    def test_fallback_path_when_no_tty(self) -> None:
        addons = [
            AddonMeta(id="docker", description="Docker"),
            AddonMeta(id="redis", description="Redis"),
        ]
        with patch("builtins.input", return_value="1"):
            result = prompt_addons(addons, template="blank")
        assert "docker" in result

    def test_incompatible_filtered_in_tui(self) -> None:
        addons = [
            AddonMeta(id="docker", description=""),
            AddonMeta(id="auth-manual", description="", templates=["fastapi"]),
        ]
        with (
            patch("zenit.cli.prompt._render.read_key", return_value="\r"),
            patch("zenit.cli.prompt._multi.tty_available", return_value=True),
        ):
            result = prompt_addons(addons, template="blank")
        assert "auth-manual" not in result

    def test_default_addons_pre_selected_in_tui(self) -> None:
        addons = [
            AddonMeta(id="docker", description=""),
            AddonMeta(id="redis", description=""),
        ]
        with (
            patch("zenit.cli.prompt._render.read_key", return_value="\r"),
            patch("zenit.cli.prompt._multi.tty_available", return_value=True),
        ):
            result = prompt_addons(addons, template="blank", default_addons=["docker"])
        assert "docker" in result
        assert "redis" not in result

    def test_default_addons_auto_include_deps_in_tui(self) -> None:
        """prompt_addons computes transitive deps for default_selected
        before passing to _tui_multi."""
        addons = [
            AddonMeta(id="docker", description=""),
            AddonMeta(id="redis", description=""),
            AddonMeta(id="celery", description="", requires=["redis"]),
        ]
        with (
            patch("zenit.cli.prompt._render.read_key", return_value="\r"),
            patch("zenit.cli.prompt._multi.tty_available", return_value=True),
        ):
            result = prompt_addons(addons, template="blank", default_addons=["celery"])
        assert "celery" in result
        assert "redis" in result


# ═══════════════════════════════════════════════════════════════════════════════
# _multi — prompt_multi_addon
# ═══════════════════════════════════════════════════════════════════════════════


class TestPromptMultiAddon:
    """prompt_multi_addon() — multi-select for add/remove context."""

    ITEMS: list[tuple[str, str, list[str]]] = [
        ("docker", "Docker support", []),
        ("redis", "Redis cache", []),
        ("celery", "Task queue", ["redis"]),
    ]

    def test_select_none_returns_empty(self) -> None:
        with (
            patch("zenit.cli.prompt._render.read_key", return_value="\r"),
            patch("zenit.cli.prompt._multi.tty_available", return_value=True),
        ):
            assert prompt_multi_addon(self.ITEMS) == []

    def test_select_one(self) -> None:
        with (
            patch("zenit.cli.prompt._render.read_key", side_effect=[" ", "\r"]),
            patch("zenit.cli.prompt._multi.tty_available", return_value=True),
        ):
            assert prompt_multi_addon(self.ITEMS) == ["docker"]

    def test_select_multiple(self) -> None:
        with (
            patch(
                "zenit.cli.prompt._render.read_key",
                side_effect=[" ", "\x1b[B", " ", "\r"],
            ),
            patch("zenit.cli.prompt._multi.tty_available", return_value=True),
        ):
            result = prompt_multi_addon(self.ITEMS)
        assert "docker" in result
        assert "redis" in result

    def test_auto_selects_deps_on_toggle(self) -> None:
        keys = iter(["\x1b[B", "\x1b[B", " ", "\r"])
        requires_map = {"docker": [], "redis": [], "celery": ["redis"]}
        with (
            patch("zenit.cli.prompt._render.read_key", side_effect=keys),
            patch("zenit.cli.prompt._multi.tty_available", return_value=True),
        ):
            result = prompt_multi_addon(self.ITEMS, requires_map=requires_map)
        assert "celery" in result
        assert "redis" in result

    def test_fallback_path(self) -> None:
        with (
            patch("builtins.input", return_value="1 2"),
            patch("zenit.cli.prompt._multi.tty_available", return_value=False),
        ):
            result = prompt_multi_addon(self.ITEMS)
        assert "docker" in result
        assert "redis" in result


# ═══════════════════════════════════════════════════════════════════════════════
# _multi — _fallback_multi_addon
# ═══════════════════════════════════════════════════════════════════════════════


class TestFallbackMultiAddon:
    """_fallback_multi_addon() — non-TTY multi-addon picker."""

    ITEMS: list[tuple[str, str, list[str]]] = [
        ("docker", "Docker support", []),
        ("redis", "Redis cache", []),
        ("celery", "Task queue", ["redis"]),
    ]

    def test_empty_input_returns_empty(self) -> None:
        with patch("builtins.input", return_value=""):
            assert _fallback_multi_addon(self.ITEMS) == []

    def test_select_by_number(self) -> None:
        with patch("builtins.input", return_value="2"):
            assert _fallback_multi_addon(self.ITEMS) == ["redis"]

    def test_select_by_name(self) -> None:
        with patch("builtins.input", return_value="celery"):
            assert _fallback_multi_addon(self.ITEMS) == ["celery"]

    def test_select_multiple(self) -> None:
        with patch("builtins.input", return_value="1 2"):
            result = _fallback_multi_addon(self.ITEMS)
        assert "docker" in result
        assert "redis" in result

    def test_fallback_add_auto_selects_deps(self) -> None:
        requires_map = {"docker": [], "redis": [], "celery": ["redis"]}
        with patch("builtins.input", return_value="3"):
            result = _fallback_multi_addon(
                self.ITEMS, context="add", requires_map=requires_map
            )
        assert "celery" in result
        assert "redis" in result

    def test_out_of_range_retries(self) -> None:
        with (
            patch("builtins.input", side_effect=["5", "1"]),
        ):
            assert _fallback_multi_addon(self.ITEMS) == ["docker"]

    def test_unknown_name_retries(self) -> None:
        with (
            patch("builtins.input", side_effect=["zzz", "1"]),
        ):
            assert _fallback_multi_addon(self.ITEMS) == ["docker"]

    def test_context_remove_shows_template_marker(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        items = [
            ("redis", "Redis", []),
            ("celery", "Celery", ["__template__fastapi"]),
        ]
        with (
            patch("builtins.input", return_value=""),
            patch("zenit.cli.prompt._multi.tty_available", return_value=False),
        ):
            prompt_multi_addon(items, context="remove")
        captured = capsys.readouterr()
        assert "required by fastapi template" in captured.out

    def test_context_add_fallback_lists_items(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        items = [
            ("celery", "Celery", ["redis"]),
            ("redis", "Redis", []),
        ]
        with (
            patch("builtins.input", return_value=""),
            patch("zenit.cli.prompt._multi.tty_available", return_value=False),
        ):
            prompt_multi_addon(items, context="add")
        captured = capsys.readouterr()
        assert "celery" in captured.out
        assert "redis" in captured.out


# ═══════════════════════════════════════════════════════════════════════════════
# _multi — _fallback_multi  (existing tests preserved)
# ═══════════════════════════════════════════════════════════════════════════════


def _items(*names: str) -> list[tuple[str, str]]:
    return [(n, f"{n} description") for n in names]


def _requires(*pairs: tuple[str, list[str]]) -> dict[str, list[str]]:
    return dict(pairs)


def test_fallback_multi_empty_input_returns_only_locked() -> None:
    items = _items("docker", "redis", "celery")
    with patch("builtins.input", return_value=""):
        result = _fallback_multi(
            items, _requires(), template="", default_addon_names=[]
        )
    assert result == []


def test_fallback_multi_empty_input_no_locked_returns_empty() -> None:
    items = _items("docker", "redis")
    with patch("builtins.input", return_value=""):
        result = _fallback_multi(
            items, _requires(), template="", default_addon_names=[]
        )
    assert result == []


def test_fallback_multi_no_items_returns_empty() -> None:
    result = _fallback_multi(
        [], _requires(), template="fastapi", default_addon_names=[]
    )
    assert result == []


def test_fallback_multi_select_first() -> None:
    items = _items("docker", "redis", "celery")
    with patch("builtins.input", return_value="1"):
        result = _fallback_multi(
            items, _requires(), template="", default_addon_names=[]
        )
    assert "docker" in result


def test_fallback_multi_select_second() -> None:
    items = _items("docker", "redis", "celery")
    with patch("builtins.input", return_value="2"):
        result = _fallback_multi(
            items, _requires(), template="", default_addon_names=[]
        )
    assert "redis" in result


def test_fallback_multi_select_multiple() -> None:
    items = _items("docker", "redis", "sentry")
    with patch("builtins.input", return_value="1 3"):
        result = _fallback_multi(
            items, _requires(), template="", default_addon_names=[]
        )
    assert "docker" in result
    assert "sentry" in result
    assert "redis" not in result


def test_fallback_multi_auto_selects_required() -> None:
    items = _items("docker", "redis", "celery")
    with patch("builtins.input", return_value="3"):
        result = _fallback_multi(
            items,
            _requires(("celery", ["redis"])),
            template="",
            default_addon_names=[],
        )
    assert "docker" not in result
    assert "redis" in result
    assert "celery" in result


def test_fallback_multi_locked_not_duplicated() -> None:
    items = _items("docker", "redis")
    with patch("builtins.input", return_value="1"):
        result = _fallback_multi(
            items, _requires(), template="", default_addon_names=[]
        )
    assert result.count("docker") == 1


def test_fallback_multi_auto_selects_only_direct_requirements() -> None:
    items = _items("docker", "redis", "celery")
    requires = _requires(("celery", ["redis"]), ("redis", ["docker"]))
    with patch("builtins.input", return_value="3"):
        result = _fallback_multi(items, requires, template="", default_addon_names=[])
    assert "celery" in result
    assert "redis" in result
    assert "docker" not in result


def test_fallback_multi_retries_on_out_of_range() -> None:
    items = _items("docker", "redis")
    with patch("builtins.input", side_effect=["5", "1"]):
        result = _fallback_multi(
            items, _requires(), template="", default_addon_names=[]
        )
    assert "docker" in result


def test_fallback_multi_retries_on_non_numeric() -> None:
    items = _items("docker", "redis")
    with patch("builtins.input", side_effect=["abc", "2"]):
        result = _fallback_multi(
            items, _requires(), template="", default_addon_names=[]
        )
    assert "redis" in result


def test_fallback_multi_retries_on_zero_index() -> None:
    items = _items("docker", "redis")
    with patch("builtins.input", side_effect=["0", "1"]):
        result = _fallback_multi(
            items, _requires(), template="", default_addon_names=[]
        )
    assert "docker" in result


def test_fallback_multi_retries_on_mixed_valid_invalid() -> None:
    items = _items("docker", "redis", "sentry")
    with patch("builtins.input", side_effect=["1 abc", "2"]):
        result = _fallback_multi(
            items, _requires(), template="", default_addon_names=[]
        )
    assert "redis" in result
    assert "docker" not in result


def test_fallback_multi_eof_raises_system_exit() -> None:
    items = _items("docker", "redis")
    with (
        patch("builtins.input", side_effect=EOFError),
        pytest.raises(SystemExit) as exc,
    ):
        _fallback_multi(items, _requires(), template="", default_addon_names=[])
    assert exc.value.code == 0


def test_fallback_multi_keyboard_interrupt_raises_system_exit() -> None:
    items = _items("docker", "redis")
    with (
        patch("builtins.input", side_effect=KeyboardInterrupt),
        pytest.raises(SystemExit),
    ):
        _fallback_multi(items, _requires(), template="", default_addon_names=[])


def test_fallback_multi_enter_returns_defaults() -> None:
    items = _items("docker", "redis", "sentry")
    with patch("builtins.input", return_value=""):
        result = _fallback_multi(
            items,
            _requires(),
            template="",
            default_addon_names=["redis", "sentry"],
        )
    assert "redis" in result
    assert "sentry" in result
    assert "docker" not in result
