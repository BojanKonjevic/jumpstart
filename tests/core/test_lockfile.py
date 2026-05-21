"""Tests for zenit.lockfile — read/write round-trip."""

from zenit.core.lockfile import (
    LOCKFILE_NAME,
    ZenitLockfile,
    read_lockfile,
    write_lockfile,
)


def test_write_then_read_roundtrip(tmp_path):
    write_lockfile(tmp_path, "fastapi", ["docker", "redis"])
    result = read_lockfile(tmp_path)
    assert result is not None
    assert result.template == "fastapi"
    assert result.addons == ["docker", "redis"]


def test_write_creates_lockfile(tmp_path):
    write_lockfile(tmp_path, "blank", [])
    assert (tmp_path / LOCKFILE_NAME).exists()


def test_write_empty_addons(tmp_path):
    write_lockfile(tmp_path, "blank", [])
    result = read_lockfile(tmp_path)
    assert result is not None
    assert result.addons == []


def test_write_sets_zenit_version(tmp_path):
    write_lockfile(tmp_path, "blank", [])
    result = read_lockfile(tmp_path)
    assert result is not None
    assert isinstance(result.zenit_version, str)
    assert len(result.zenit_version) > 0


def test_read_returns_none_when_missing(tmp_path):
    assert read_lockfile(tmp_path) is None


def test_read_returns_none_on_corrupt_toml(tmp_path):
    (tmp_path / LOCKFILE_NAME).write_text("NOT VALID TOML ][[[")
    assert read_lockfile(tmp_path) is None


def test_read_handles_missing_project_key(tmp_path):
    (tmp_path / LOCKFILE_NAME).write_text("[other]\nkey = 1\n")
    result = read_lockfile(tmp_path)
    assert result is not None
    assert result.template == ""
    assert result.addons == []


def test_read_handles_non_string_template(tmp_path):
    (tmp_path / LOCKFILE_NAME).write_text("[project]\ntemplate = 42\naddons = []\n")
    result = read_lockfile(tmp_path)
    assert result is not None
    assert result.template == ""


def test_read_handles_non_list_addons(tmp_path):
    (tmp_path / LOCKFILE_NAME).write_text(
        '[project]\ntemplate = "blank"\naddons = "bad"\n'
    )
    result = read_lockfile(tmp_path)
    assert result is not None
    assert result.addons == []


def test_read_filters_non_string_addon_entries(tmp_path):
    (tmp_path / LOCKFILE_NAME).write_text(
        '[project]\ntemplate = "blank"\naddons = ["docker", 42, "redis"]\n'
    )
    result = read_lockfile(tmp_path)
    assert result is not None
    assert result.addons == ["docker", "redis"]


def test_write_is_idempotent(tmp_path):
    write_lockfile(tmp_path, "blank", ["docker"])
    write_lockfile(tmp_path, "blank", ["docker"])
    result = read_lockfile(tmp_path)
    assert result is not None
    assert result.addons == ["docker"]


def test_lockfile_dataclass_defaults():
    lf = ZenitLockfile()
    assert lf.template == ""
    assert lf.addons == []
    assert lf.zenit_version == ""


def test_write_lockfile_preserves_manifest_section(tmp_path):
    """Regression: write_lockfile must not destroy an existing [manifest] section.

    Previously used tomli_w.dumps which serialised a fresh dict containing only
    [project], silently discarding [manifest] and any other sections present.
    """
    import tomlkit

    path = tmp_path / ".zenit.toml"
    doc = tomlkit.document()
    manifest_table = tomlkit.table()
    manifest_table.add("python_blocks", tomlkit.array())
    manifest_table.add("env", tomlkit.array())
    doc.add("manifest", manifest_table)
    path.write_text(tomlkit.dumps(doc), encoding="utf-8")

    write_lockfile(tmp_path, "fastapi", ["redis"])

    raw = tomlkit.parse(path.read_text(encoding="utf-8"))
    assert "manifest" in raw, (
        "write_lockfile destroyed the [manifest] section. "
        "It must use tomlkit round-trip, not tomli_w.dumps."
    )
    assert "project" in raw
    assert raw["project"]["template"] == "fastapi"
