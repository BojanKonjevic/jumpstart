"""Unit tests for the fingerprinting contract in zenit.core.manifest.

The fingerprint contract is frozen: changing _normalise requires bumping
MANIFEST_SCHEMA_VERSION. These tests document the contract boundaries and
the guarantees made to removal Stages A and B.
"""

from __future__ import annotations

from zenit.core.manifest import _normalise, fingerprint

# ── fingerprint() - top-level contract ───────────────────────────────────────


def test_fingerprint_returns_sha256_prefix() -> None:
    raw, normalised = fingerprint("x = 1\n")
    assert raw.startswith("sha256:")
    assert normalised.startswith("sha256:")


def test_fingerprint_raw_and_normalised_differ() -> None:
    # Any valid Python module ends with \n; _normalise strips the trailing
    # newline (via splitlines → join without final \n), so the two hashes
    # are computed over different strings and will always differ.
    raw, normalised = fingerprint("x = 1   \ny = 2   \n")
    assert raw != normalised


def test_normalised_stable_after_trailing_whitespace() -> None:
    # libcst preserves trailing spaces in canonical output; _normalise strips them.
    # Both inputs must therefore produce the same fingerprint_normalised.
    _, fp_with_spaces = fingerprint("x = 1   \ny = 2   \n")
    _, fp_clean = fingerprint("x = 1\ny = 2\n")
    assert fp_with_spaces == fp_clean


def test_normalised_stable_after_extra_blank_lines() -> None:
    # libcst preserves extra blank lines; _normalise collapses 3+ → 2.
    # Three blank lines and one blank line both normalise to one blank line.
    _, fp_extra = fingerprint("x = 1\n\n\n\ny = 2\n")
    _, fp_single = fingerprint("x = 1\n\ny = 2\n")
    assert fp_extra == fp_single


def test_normalised_differs_on_semantic_change() -> None:
    # Renaming a variable is a semantic change; both fingerprints must change.
    raw_a, norm_a = fingerprint("redis_url: str = ''\n")
    raw_b, norm_b = fingerprint("database_url: str = ''\n")
    assert raw_a != raw_b
    assert norm_a != norm_b


def test_invalid_python_falls_back_gracefully() -> None:
    """An indented fragment is not a valid Python module.

    fingerprint() must not raise - it falls back to raw-text hashing
    with no libcst round-trip.  The hashes are still valid sha256
    values, but because no canonical round-trip occurred, Stage A/B
    removal will not match and removal falls through to Stage C fuzzy.
    This is a known contract, not a bug.
    """
    fragment = '    redis_url: str = ""\n'
    raw, normalised = fingerprint(fragment)
    assert raw.startswith("sha256:")
    assert normalised.startswith("sha256:")
    # Raw and normalised differ because _normalise strips trailing
    # whitespace/newlines even without a libcst round-trip.
    assert raw != normalised


# ── _normalise() - internal contract ─────────────────────────────────────────


def test_normalise_collapses_three_plus_blank_lines_to_two() -> None:
    code = "line1\n\n\nline2\n\n\n\nline3"
    result = _normalise(code)
    assert "\n\n\n" not in result
    assert result == "line1\n\nline2\n\nline3"


def test_normalise_strips_trailing_whitespace_per_line() -> None:
    code = "line1   \nline2\t\nline3"
    result = _normalise(code)
    assert result == "line1\nline2\nline3"


def test_normalise_idempotent() -> None:
    # Applying _normalise twice must produce the same result as once.
    for code in [
        "line1   \n\n\n\nline2   ",
        "x = 1\n\n\ny = 2\n",
        "    a: int\n    b: str   \n",
    ]:
        once = _normalise(code)
        twice = _normalise(once)
        assert once == twice, f"_normalise not idempotent for {code!r}"
