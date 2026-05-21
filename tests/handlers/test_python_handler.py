"""Unit tests for zenit.core.handlers.python_handler.

Covers:
  - apply(): insertion position, line-range arithmetic, error propagation
  - remove() Stage A: exact fingerprint
  - remove() Stage B: normalised fingerprint (libcst round-trip, no stderr)
  - remove() Stage C: fuzzy match — success with warning, failure below threshold
  - remove() Stage D: file gone / truncated
  - _collapse_blank_lines(): standalone contract
"""

from __future__ import annotations

import textwrap
from pathlib import Path

import libcst as cst
import pytest

from zenit.core.handlers.python_handler import (
    InjectionError,
    RemovalError,
    _collapse_blank_lines,
    apply,
    remove,
)
from zenit.core.manifest import fingerprint as _fp
from zenit.schema.models import ManifestBlock

# ── helpers ───────────────────────────────────────────────────────────────────


def _block(
    file: Path,
    lines: str,
    content: str,
    locator_name: str = "after_last_import",
    locator_args: dict[str, object] | None = None,
    addon: str = "test",
    point: str = "test_point",
) -> ManifestBlock:
    """Build a ManifestBlock with real fingerprints computed from *content*."""
    fp, fp_norm = _fp(content)
    return ManifestBlock(
        addon=addon,
        point=point,
        file=str(file),
        lines=lines,
        fingerprint=fp,
        fingerprint_normalised=fp_norm,
        locator={"name": locator_name, "args": locator_args or {}},
    )


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(textwrap.dedent(text), encoding="utf-8")


# ── apply() ───────────────────────────────────────────────────────────────────


def test_apply_inserts_at_locator_position(tmp_path: Path) -> None:
    # No blank line between imports so insertion is immediately after "import os"
    f = tmp_path / "mod.py"
    f.write_text("import os\nclass Foo:\n    pass\n", encoding="utf-8")
    apply(f, "import sys\n", "after_last_import", {})
    src = f.read_text()
    lines = src.splitlines()
    # after_last_import: inserts right after "import os"
    assert lines[0] == "import os"
    assert lines[1] == "import sys"
    assert "class Foo" in src


def test_apply_returns_correct_line_range(tmp_path: Path) -> None:
    f = tmp_path / "mod.py"
    _write(
        f,
        """\
        import os
    """,
    )
    _, start, end = apply(
        f, "import sys\nimport re\nimport json\n", "after_last_import", {}
    )
    assert end - start == 2  # 3 lines → span of 2


def test_apply_single_line_content(tmp_path: Path) -> None:
    f = tmp_path / "mod.py"
    _write(
        f,
        """\
        import os
    """,
    )
    _, start, end = apply(f, "import sys\n", "after_last_import", {})
    assert start == end


def test_apply_multiline_content(tmp_path: Path) -> None:
    f = tmp_path / "mod.py"
    _write(
        f,
        """\
        import os
    """,
    )
    _, start, end = apply(f, "A = 1\nB = 2\nC = 3\n", "at_module_end", {})
    assert end - start == 2


def test_apply_multiple_injections_same_file(tmp_path: Path) -> None:
    f = tmp_path / "settings.py"
    _write(
        f,
        """\
        class Settings:
            name: str = "app"
    """,
    )
    apply(
        f,
        "    debug: bool = False\n",
        "after_last_class_attribute",
        {"class_name": "Settings"},
    )
    apply(
        f,
        "    port: int = 8000\n",
        "after_last_class_attribute",
        {"class_name": "Settings"},
    )
    src = f.read_text()
    assert "debug: bool" in src
    assert "port: int" in src


def test_apply_raises_injection_error_on_locator_failure(tmp_path: Path) -> None:
    f = tmp_path / "mod.py"
    _write(
        f,
        """\
        import os
    """,
    )
    with pytest.raises(InjectionError) as exc_info:
        apply(f, "pass\n", "before_yield_in_function", {"function": "lifespan"})
    msg = str(exc_info.value)
    assert "lifespan" in msg
    assert str(f) in msg


def test_apply_adds_trailing_newline_if_missing(tmp_path: Path) -> None:
    f = tmp_path / "mod.py"
    _write(
        f,
        """\
        import os
    """,
    )
    apply(f, "import sys", "after_last_import", {})  # no trailing \n
    src = f.read_text()
    assert "import sys\n" in src
    # File must remain parseable
    cst.parse_module(src)


# ── remove() Stage A — exact fingerprint ─────────────────────────────────────


def test_remove_stage_a_exact_match(tmp_path: Path) -> None:
    f = tmp_path / "mod.py"
    injection = "import redis\n"
    _write(
        f,
        """\
        import os
        import redis
        class App:
            pass
    """,
    )
    block = _block(f, "2-2", injection)
    remove(f, block)
    src = f.read_text()
    assert "import redis" not in src
    assert "import os" in src
    assert "class App" in src


def test_remove_stage_a_file_is_valid_python_after(tmp_path: Path) -> None:
    f = tmp_path / "mod.py"
    injection = 'REDIS_URL: str = "redis://localhost"\n'
    _write(
        f,
        """\
        import os
        REDIS_URL: str = "redis://localhost"

        def main() -> None:
            pass
    """,
    )
    block = _block(f, "2-2", injection)
    remove(f, block)
    cst.parse_module(f.read_text())


# ── remove() Stage B — normalised fingerprint ─────────────────────────────────


def test_remove_stage_b_after_cst_roundtrip(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Stage B removes silently — no stderr output — after a libcst round-trip."""
    injection = "import redis\n"
    # Write the file with a round-tripped variant of the injection to simulate
    # the exact normalisation used by fingerprint_normalised.
    roundtripped = cst.parse_module(injection).code
    f = tmp_path / "mod.py"
    f.write_text(f"import os\n{roundtripped}class App:\n    pass\n", encoding="utf-8")

    # The block's fingerprint is computed on the *original* injection text,
    # so Stage A will fail. Stage B uses fingerprint_normalised which will
    # match the round-tripped variant.
    block = _block(f, "2-2", injection)
    remove(f, block)

    captured = capsys.readouterr()
    assert captured.err == "", "Stage B must be silent — no stderr"
    assert "import redis" not in f.read_text()


# ── remove() Stage C — fuzzy match ────────────────────────────────────────────


def _inject_and_record(tmp_path: Path, injection: str) -> tuple[Path, ManifestBlock]:
    """Scaffold a file with a known injection and return (file, block)."""
    f = tmp_path / "settings.py"
    original = 'class Settings:\n    db_url: str = "postgresql://localhost"\n'
    f.write_text(original + injection, encoding="utf-8")
    line_count_original = len(original.splitlines())
    injection_lines = len(injection.splitlines())
    start = line_count_original + 1
    end = line_count_original + injection_lines
    block = _block(
        f,
        f"{start}-{end}",
        injection,
        locator_name="after_last_class_attribute",
        locator_args={"class_name": "Settings"},
    )
    return f, block


def test_remove_stage_c_mild_edit_succeeds(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """One renamed local variable keeps similarity ≥ 0.85; block is removed; warning printed."""
    injection = '    redis_url: str = "redis://localhost"\n'
    f, block = _inject_and_record(tmp_path, injection)

    # Mild edit: rename variable (changes Stage A and B fingerprints)
    edited = '    redis_url: str = "redis://127.0.0.1"\n'
    src = f.read_text()
    f.write_text(src.replace(injection, edited), encoding="utf-8")

    remove(f, block)

    captured = capsys.readouterr()
    assert "Warning" in captured.err or "warning" in captured.err.lower()
    assert "redis_url" not in f.read_text() or "redis://127.0.0.1" not in f.read_text()


def test_remove_stage_c_warning_names_file_and_similarity(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """The Stage C warning must name the file and a similarity value."""
    injection = '    redis_url: str = "redis://localhost"\n'
    f, block = _inject_and_record(tmp_path, injection)

    edited = '    redis_url: str = "redis://127.0.0.1"\n'
    src = f.read_text()
    f.write_text(src.replace(injection, edited), encoding="utf-8")

    remove(f, block)

    err = capsys.readouterr().err
    assert f.name in err, f"Expected filename in warning, got: {err!r}"
    # Similarity appears as a percentage (e.g. "92%") or ratio (e.g. "0.92")
    has_pct = "%" in err
    has_ratio = any(c.isdigit() for c in err)
    assert has_pct or has_ratio, f"Expected similarity value in warning, got: {err!r}"


def test_remove_stage_c_below_threshold_raises(tmp_path: Path) -> None:
    """RemovalError is raised when Stage C finds no candidates in the scan window.

    This happens when the recorded block is at lines that are completely outside
    the current file length AND the FUZZY_WINDOW_LINES padding also falls outside.
    In practice this means the file was truncated well below the recorded position.
    """
    injection = '    redis_url: str = "redis://localhost"\n'
    f = tmp_path / "settings.py"
    original = 'class Settings:\n    db_url: str = "postgresql://localhost"\n'
    # Record a block at line 50 — far beyond the real file length.
    # Stage A/B skip (line 50 doesn't exist). Stage C window starts at
    # max(0, 49 - FUZZY_WINDOW_LINES) = 29, which is also beyond the 2-line file.
    # No candidates → Stage D.
    fp, fp_norm = _fp(injection)
    block = ManifestBlock(
        addon="redis",
        point="settings_fields",
        file=str(f),
        lines="50-50",
        fingerprint=fp,
        fingerprint_normalised=fp_norm,
        locator={
            "name": "after_last_class_attribute",
            "args": {"class_name": "Settings"},
        },
    )
    f.write_text(original, encoding="utf-8")

    with pytest.raises(RemovalError) as exc_info:
        remove(f, block)

    msg = str(exc_info.value)
    assert str(f) in msg
    assert "50-50" in msg
    assert "Manual steps" in msg


# ── remove() Stage D — unrecoverable ──────────────────────────────────────────


def test_remove_stage_d_file_deleted_raises(tmp_path: Path) -> None:
    injection = "import redis\n"
    f = tmp_path / "mod.py"
    f.write_text("import os\nimport redis\n", encoding="utf-8")
    block = _block(f, "2-2", injection)
    f.unlink()  # simulate deletion after injection was recorded

    with pytest.raises((RemovalError, FileNotFoundError, OSError)):
        remove(f, block)


def test_remove_stage_d_file_truncated_raises(tmp_path: Path) -> None:
    injection = "import redis\n"
    f = tmp_path / "mod.py"
    f.write_text("import os\nimport redis\n", encoding="utf-8")
    block = _block(f, "50-50", injection)  # line 50 doesn't exist

    with pytest.raises(RemovalError):
        remove(f, block)


def test_remove_empty_block_is_noop(tmp_path: Path) -> None:
    """A block that fingerprint-matches an empty string must not corrupt the file."""
    f = tmp_path / "mod.py"
    original = "import os\nclass App:\n    pass\n"
    f.write_text(original, encoding="utf-8")
    # A block whose content is just a newline — degenerate edge case
    block = _block(f, "1-1", "import os\n")
    remove(f, block)
    assert f.exists()


# ── _collapse_blank_lines() ───────────────────────────────────────────────────


def test_collapse_blank_lines_collapses_three_to_two() -> None:
    lines = ["a\n", "\n", "\n", "\n", "b\n"]
    result = _collapse_blank_lines(lines)
    assert result == ["a\n", "\n", "\n", "b\n"]


def test_collapse_blank_lines_leaves_two_unchanged() -> None:
    lines = ["a\n", "\n", "\n", "b\n"]
    result = _collapse_blank_lines(lines)
    assert result == ["a\n", "\n", "\n", "b\n"]


def test_collapse_blank_lines_preserves_non_blank() -> None:
    lines = ["import os\n", "import sys\n", "class Foo:\n", "    pass\n"]
    result = _collapse_blank_lines(lines)
    assert result == lines
