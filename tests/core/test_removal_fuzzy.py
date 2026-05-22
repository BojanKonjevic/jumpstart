"""Integration tests — fuzzy removal threshold, warning emission, Stage B silence.

Tests the 4-stage removal cascade in python_handler.remove() under realistic
conditions: libcst round-trips (Stage B), mild edits (Stage C success + warn),
heavy edits (Stage C failure → Stage D), and multi-block disambiguation.

Each test works directly against python_handler.apply() / remove() to stay
focused on the removal mechanics without the overhead of a full scaffold run.
"""

from __future__ import annotations

import textwrap
from pathlib import Path

import libcst as cst
import pytest

from zenit.core.handlers.python_handler import (
    FUZZY_WINDOW_LINES,
    RemovalError,
    apply,
    remove,
)
from zenit.core.manifest import fingerprint as _fp
from zenit.schema.models import LocatorSpec, ManifestBlock

# ── helpers ───────────────────────────────────────────────────────────────────


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(textwrap.dedent(text), encoding="utf-8")


_DEFAULT_LOCATOR = "after_last_class_attribute"
_DEFAULT_LOCATOR_ARGS: dict[str, object] = {"class_name": "Settings"}


def _inject(
    file: Path,
    content: str,
    locator_name: str = _DEFAULT_LOCATOR,
    locator_args: dict[str, object] | None = None,
    addon: str = "redis",
    point: str = "settings_fields",
) -> ManifestBlock:
    """Apply *content* to *file* and return the resulting ManifestBlock."""
    resolved_args = _DEFAULT_LOCATOR_ARGS if locator_args is None else locator_args
    _, start_line, end_line = apply(file, content, locator_name, resolved_args)
    fp, fp_norm = _fp(content)
    return ManifestBlock(
        addon=addon,
        point=point,
        file=str(file),
        lines=f"{start_line}-{end_line}",
        fingerprint=fp,
        fingerprint_normalised=fp_norm,
        locator=LocatorSpec(name=locator_name, args=resolved_args),
    )


_SETTINGS_SOURCE = """\
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    database_url: str = "postgresql://localhost"
    debug: bool = False
"""


# ── Stage B — libcst round-trip: silent success ───────────────────────────────


def test_fuzzy_removal_after_cst_roundtrip(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Stage B: a libcst round-trip changes the raw fingerprint but not the
    normalised one.  Removal must succeed without any stderr output."""
    f = tmp_path / "settings.py"
    _write(f, _SETTINGS_SOURCE)

    block = _inject(f, '    redis_url: str = "redis://localhost"\n')

    # Simulate what a formatter does: libcst round-trip on the whole file.
    # This preserves semantics but may alter whitespace, triggering Stage B.
    original = f.read_text(encoding="utf-8")
    f.write_text(cst.parse_module(original).code, encoding="utf-8")

    remove(f, block)

    captured = capsys.readouterr()
    assert captured.err == "", (
        "Stage B removal must be silent — no warning expected after a "
        f"libcst round-trip, got: {captured.err!r}"
    )
    assert "redis_url" not in f.read_text(encoding="utf-8")


# ── Stage C — mild edit: success with warning ─────────────────────────────────


def test_fuzzy_removal_mild_edit_warns(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Stage C: renaming one local variable keeps similarity above the threshold.
    Removal succeeds and a warning is printed to stderr."""
    f = tmp_path / "settings.py"
    _write(f, _SETTINGS_SOURCE)

    block = _inject(f, '    redis_url: str = "redis://localhost"\n')

    # Mild edit: rename the attribute — similarity stays ≥ 0.85.
    text = f.read_text(encoding="utf-8")
    f.write_text(
        text.replace(
            '    redis_url: str = "redis://localhost"',
            '    cache_url: str = "redis://localhost"',
        ),
        encoding="utf-8",
    )

    remove(f, block)

    captured = capsys.readouterr()
    assert captured.err != "", "Stage C removal must emit a warning to stderr"
    assert "cache_url" not in f.read_text(encoding="utf-8")


def test_fuzzy_removal_warning_message_format(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Stage C warning must include the file name, the matched line range,
    and a similarity score expressed as a percentage or ratio."""
    f = tmp_path / "settings.py"
    _write(f, _SETTINGS_SOURCE)

    block = _inject(f, '    redis_url: str = "redis://localhost"\n')

    text = f.read_text(encoding="utf-8")
    f.write_text(
        text.replace(
            '    redis_url: str = "redis://localhost"',
            '    cache_url: str = "redis://localhost"',
        ),
        encoding="utf-8",
    )

    remove(f, block)

    warning = capsys.readouterr().err
    assert f.name in warning, (
        f"Warning must contain the file name {f.name!r}, got: {warning!r}"
    )
    # Similarity is printed as e.g. "85%" or "0.85" — match either form.
    has_percent = "%" in warning
    has_ratio = any(
        part.replace(".", "", 1).isdigit()
        for part in warning.split()
        if "." in part and len(part) <= 6
    )
    assert has_percent or has_ratio, (
        f"Warning must contain a similarity score, got: {warning!r}"
    )
    # Line range: something like "6-6" or "at lines 6-6"
    assert any(
        "-" in word and all(p.isdigit() for p in word.split("-", 1))
        for word in warning.split()
    ), f"Warning must contain a line range (e.g. '6-6'), got: {warning!r}"


# ── Stage C — heavy edit: failure → RemovalError ──────────────────────────────


def test_fuzzy_removal_heavy_edit_raises(tmp_path: Path) -> None:
    """Stage D: the file has been so heavily restructured that the recorded
    position is far beyond the new end-of-file, making the Stage C window
    loop run zero iterations.  remove() must raise RemovalError containing
    the file path, the expected line range, and manual resolution instructions.

    Stage C computes norm_ref from the *current* file at the clamped recorded
    position, so content edits alone cannot push below the threshold — when
    s == ref_start the candidate equals norm_ref and similarity is always 100%.
    The only reliable path to Stage D is an empty scan window, which requires
    len(lines) < rec_start - FUZZY_WINDOW_LINES (== 20).  We achieve this by
    injecting into a long file and then shrinking it drastically.
    """
    # Must push injection past FUZZY_WINDOW_LINES (20). With ~4 boilerplate lines
    # before the first field, FUZZY_WINDOW_LINES + 10 fields guarantees rec_start > threshold.
    many_fields = "\n".join(
        f"    field_{i}: int = {i}" for i in range(FUZZY_WINDOW_LINES + 10)
    )
    long_source = (
        "from pydantic_settings import BaseSettings\n\n\n"
        "class Settings(BaseSettings):\n"
        f"{many_fields}\n"
    )
    f = tmp_path / "settings.py"
    f.write_text(long_source, encoding="utf-8")

    block = _inject(f, '    redis_url: str = "redis://localhost"\n')

    rec_start = int(block.lines.split("-")[0]) - 1  # 0-based
    assert rec_start > FUZZY_WINDOW_LINES, (
        f"Injection must land past line {FUZZY_WINDOW_LINES + 1} for "
        f"Stage D to be reachable; got rec_start={rec_start}"
    )

    # Shrink the file to fewer lines than rec_start - FUZZY_WINDOW_LINES.
    # This empties the Stage C window and guarantees Stage D.
    f.write_text(
        "# Module completely rewritten.\nfrom pydantic_settings import BaseSettings\n",
        encoding="utf-8",
    )

    with pytest.raises(RemovalError) as exc_info:
        remove(f, block)

    message = str(exc_info.value)
    assert str(f) in message, f"RemovalError must contain the file path {str(f)!r}"
    assert block.lines in message, (
        f"RemovalError must contain the expected line range {block.lines!r}"
    )
    assert "Manual" in message or "manual" in message, (
        "RemovalError must include manual resolution instructions"
    )


# ── Multi-block disambiguation ────────────────────────────────────────────────


def test_fuzzy_removal_correct_block_selected(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """When two similar blocks exist in the same file, the fuzzy matcher must
    remove the block whose recorded position is closest, leaving the other
    block intact."""
    f = tmp_path / "settings.py"
    _write(
        f,
        """\
        from pydantic_settings import BaseSettings


        class Settings(BaseSettings):
            database_url: str = "postgresql://localhost"
            debug: bool = False
        """,
    )

    # Inject two similar but distinct blocks.
    block_redis = _inject(
        f,
        '    redis_url: str = "redis://localhost"\n',
        addon="redis",
        point="settings_fields_redis",
    )
    block_celery = _inject(
        f,
        '    celery_url: str = "redis://localhost/1"\n',
        addon="celery",
        point="settings_fields_celery",
    )
    assert block_celery.addon == "celery"

    # Mildly edit both so Stage A and B both fail — forcing Stage C.
    text = f.read_text(encoding="utf-8")
    text = text.replace(
        '    redis_url: str = "redis://localhost"',
        '    redis_cache: str = "redis://localhost"',
    )
    text = text.replace(
        '    celery_url: str = "redis://localhost/1"',
        '    celery_broker: str = "redis://localhost/1"',
    )
    f.write_text(text, encoding="utf-8")

    # Remove only the redis block.
    capsys.readouterr()  # clear any prior output
    remove(f, block_redis)

    remaining = f.read_text(encoding="utf-8")

    # Redis block is gone; celery block survives.
    assert "redis_cache" not in remaining, (
        "The redis block (fuzzy-matched to redis_cache) must have been removed"
    )
    assert "celery_broker" in remaining, "The celery block must not have been touched"
