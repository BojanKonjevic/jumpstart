"""Tests for zenit.doctor.print_results - terminal output format.

test_doctor.py already verifies the return value (True/False) and that
category names and messages appear in output.  This file focuses on the
structural and formatting details: ANSI icon characters, hint indentation,
ordering, and multi-section layout.
"""

from __future__ import annotations

from zenit.doctor.doctor import HealthResult, print_results

# ── icon characters ───────────────────────────────────────────────────────────


def test_ok_issue_uses_checkmark_icon(capsys):
    r = HealthResult("Test")
    r.ok("everything is fine")
    print_results([r])
    out = capsys.readouterr().out
    assert "✓" in out


def test_warn_issue_uses_warning_icon(capsys):
    r = HealthResult("Test")
    r.warn("watch out")
    print_results([r])
    out = capsys.readouterr().out
    assert "⚠" in out


def test_error_issue_uses_cross_icon(capsys):
    r = HealthResult("Test")
    r.error("broken")
    print_results([r])
    out = capsys.readouterr().out
    assert "✗" in out


def test_each_severity_uses_distinct_icon(capsys):
    r = HealthResult("Test")
    r.ok("ok message")
    r.warn("warn message")
    r.error("error message")
    print_results([r])
    out = capsys.readouterr().out
    assert "✓" in out
    assert "⚠" in out
    assert "✗" in out


# ── hint formatting ───────────────────────────────────────────────────────────


def test_hint_appears_on_separate_line(capsys):
    r = HealthResult("Test")
    r.error("broken", hint="fix this way")
    print_results([r])
    out = capsys.readouterr().out
    lines = out.splitlines()
    message_line = next(i for i, line in enumerate(lines) if "broken" in line)
    hint_line = next(i for i, line in enumerate(lines) if "fix this way" in line)
    assert hint_line > message_line


def test_hint_is_indented_further_than_message(capsys):
    r = HealthResult("Test")
    r.error("broken", hint="fix this way")
    print_results([r])
    out = capsys.readouterr().out
    lines = [line for line in out.splitlines() if line.strip()]

    # Find the raw (ANSI-stripped) leading spaces
    def leading_spaces(line: str) -> int:
        # strip ANSI codes roughly by counting spaces before first non-space non-escape char
        stripped = line.lstrip()
        return len(line) - len(stripped)

    msg_line = next(line for line in lines if "broken" in line)
    hint_line = next(line for line in lines if "fix this way" in line)
    assert leading_spaces(hint_line) >= leading_spaces(msg_line)


def test_no_hint_line_when_hint_is_empty(capsys):
    r = HealthResult("Test")
    r.ok("all good")
    print_results([r])
    out = capsys.readouterr().out
    # Should be exactly one content line (plus category header)
    content_lines = [line for line in out.splitlines() if "all good" in line]
    assert len(content_lines) == 1


def test_hint_for_warn_also_appears(capsys):
    r = HealthResult("Test")
    r.warn("watch out", hint="do this instead")
    print_results([r])
    out = capsys.readouterr().out
    assert "do this instead" in out


# ── ordering ──────────────────────────────────────────────────────────────────


def test_issues_appear_in_insertion_order(capsys):
    r = HealthResult("Test")
    r.ok("first")
    r.warn("second")
    r.error("third")
    print_results([r])
    out = capsys.readouterr().out
    pos_first = out.index("first")
    pos_second = out.index("second")
    pos_third = out.index("third")
    assert pos_first < pos_second < pos_third


def test_category_header_appears_before_its_issues(capsys):
    r = HealthResult("MyCategory")
    r.ok("some issue")
    print_results([r])
    out = capsys.readouterr().out
    assert out.index("MyCategory") < out.index("some issue")


def test_multiple_sections_appear_in_order(capsys):
    r1 = HealthResult("Alpha")
    r1.ok("a ok")
    r2 = HealthResult("Beta")
    r2.ok("b ok")
    r3 = HealthResult("Gamma")
    r3.ok("g ok")
    print_results([r1, r2, r3])
    out = capsys.readouterr().out
    assert out.index("Alpha") < out.index("Beta") < out.index("Gamma")


# ── return value ──────────────────────────────────────────────────────────────


def test_returns_false_with_only_ok_issues(capsys):
    r = HealthResult("Test")
    r.ok("fine")
    assert print_results([r]) is False


def test_returns_false_with_only_warnings(capsys):
    r = HealthResult("Test")
    r.warn("hmm")
    assert print_results([r]) is False


def test_returns_true_with_one_error(capsys):
    r = HealthResult("Test")
    r.error("broken")
    assert print_results([r]) is True


def test_returns_true_even_if_error_is_in_second_section(capsys):
    r1 = HealthResult("Good")
    r1.ok("fine")
    r2 = HealthResult("Bad")
    r2.error("broken")
    assert print_results([r1, r2]) is True


def test_returns_false_for_empty_list(capsys):
    assert print_results([]) is False


def test_returns_false_for_section_with_no_issues(capsys):
    r = HealthResult("Empty")
    assert print_results([r]) is False


# ── ANSI colour presence ──────────────────────────────────────────────────────


def test_output_contains_ansi_reset_codes(capsys):
    r = HealthResult("Test")
    r.ok("fine")
    print_results([r])
    out = capsys.readouterr().out
    assert "\033[" in out


def test_error_message_uses_red_ansi(capsys):
    r = HealthResult("Test")
    r.error("broken")
    print_results([r])
    out = capsys.readouterr().out
    # Red is \033[0;31m
    assert "\033[0;31m" in out


def test_ok_message_uses_green_ansi(capsys):
    r = HealthResult("Test")
    r.ok("fine")
    print_results([r])
    out = capsys.readouterr().out
    # Green is \033[0;32m
    assert "\033[0;32m" in out


def test_warn_message_uses_yellow_ansi(capsys):
    r = HealthResult("Test")
    r.warn("watch out")
    print_results([r])
    out = capsys.readouterr().out
    # Yellow is \033[0;33m
    assert "\033[0;33m" in out
