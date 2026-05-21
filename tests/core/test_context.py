"""Tests for zenit.context — Context and its filesystem abstraction.

Covers the real Context (which performs I/O) and the DryRunContext subclass
(which records operations without touching disk).  The DryRunContext rendering
tests live in test_dryrun.py; this file focuses on the Context API itself.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest
from conftest import ZENIT_ROOT

from zenit.core.context import Context
from zenit.core.dryrun import DryRunContext

# ── helpers ───────────────────────────────────────────────────────────────────


def _ctx(tmp_path: Path, name: str = "myapp") -> Context:
    return Context(
        name=name,
        pkg_name=name.replace("-", "_"),
        template="blank",
        addons=[],
        zenit_root=ZENIT_ROOT,
        project_dir=tmp_path / name,
    )


def _dry(tmp_path: Path, name: str = "myapp") -> DryRunContext:
    return DryRunContext(
        name=name,
        pkg_name=name.replace("-", "_"),
        template="blank",
        addons=[],
        zenit_root=ZENIT_ROOT,
        project_dir=tmp_path / name,
    )


# ── Context.dry_run ───────────────────────────────────────────────────────────


def test_context_dry_run_is_false(tmp_path):
    ctx = _ctx(tmp_path)
    assert ctx.dry_run is False


def test_dryrun_context_dry_run_is_true(tmp_path):
    ctx = _dry(tmp_path)
    assert ctx.dry_run is True


# ── Context.has ───────────────────────────────────────────────────────────────


def test_has_returns_true_for_installed_addon(tmp_path):
    ctx = Context(
        name="myapp",
        pkg_name="myapp",
        template="blank",
        addons=["docker", "redis"],
        zenit_root=ZENIT_ROOT,
        project_dir=tmp_path / "myapp",
    )
    assert ctx.has("docker") is True
    assert ctx.has("redis") is True


def test_has_returns_false_for_missing_addon(tmp_path):
    ctx = Context(
        name="myapp",
        pkg_name="myapp",
        template="blank",
        addons=["docker"],
        zenit_root=ZENIT_ROOT,
        project_dir=tmp_path / "myapp",
    )
    assert ctx.has("redis") is False


def test_has_returns_false_when_addons_empty(tmp_path):
    ctx = _ctx(tmp_path)
    assert ctx.has("docker") is False


# ── Context.write_file ────────────────────────────────────────────────────────


def test_write_file_creates_file(tmp_path):
    ctx = _ctx(tmp_path)
    ctx.project_dir.mkdir()
    ctx.write_file("hello.txt", "hello world\n")
    assert (ctx.project_dir / "hello.txt").read_text() == "hello world\n"


def test_write_file_creates_parent_dirs(tmp_path):
    ctx = _ctx(tmp_path)
    ctx.project_dir.mkdir()
    ctx.write_file("src/myapp/main.py", "# main\n")
    assert (ctx.project_dir / "src" / "myapp" / "main.py").exists()


def test_write_file_overwrites_existing(tmp_path):
    ctx = _ctx(tmp_path)
    ctx.project_dir.mkdir()
    ctx.write_file("file.txt", "original")
    ctx.write_file("file.txt", "updated")
    assert (ctx.project_dir / "file.txt").read_text() == "updated"


def test_write_file_empty_content(tmp_path):
    ctx = _ctx(tmp_path)
    ctx.project_dir.mkdir()
    ctx.write_file("empty.py", "")
    assert (ctx.project_dir / "empty.py").read_text() == ""


# ── Context.create_dir ────────────────────────────────────────────────────────


def test_create_dir_creates_directory(tmp_path):
    ctx = _ctx(tmp_path)
    ctx.project_dir.mkdir()
    ctx.create_dir("src/myapp")
    assert (ctx.project_dir / "src" / "myapp").is_dir()


def test_create_dir_idempotent(tmp_path):
    ctx = _ctx(tmp_path)
    ctx.project_dir.mkdir()
    ctx.create_dir("src/myapp")
    ctx.create_dir("src/myapp")
    assert (ctx.project_dir / "src" / "myapp").is_dir()


def test_create_dir_nested(tmp_path):
    ctx = _ctx(tmp_path)
    ctx.project_dir.mkdir()
    ctx.create_dir("a/b/c/d")
    assert (ctx.project_dir / "a" / "b" / "c" / "d").is_dir()


# ── Context.copy_file ─────────────────────────────────────────────────────────


def test_copy_file_copies_content(tmp_path):
    ctx = _ctx(tmp_path)
    ctx.project_dir.mkdir()
    src = tmp_path / "source.txt"
    src.write_text("source content")
    ctx.copy_file(src, "dest.txt")
    assert (ctx.project_dir / "dest.txt").read_text() == "source content"


def test_copy_file_creates_parent_dirs(tmp_path):
    ctx = _ctx(tmp_path)
    ctx.project_dir.mkdir()
    src = tmp_path / "template.yaml"
    src.write_text("key: value\n")
    ctx.copy_file(src, "config/template.yaml")
    assert (ctx.project_dir / "config" / "template.yaml").exists()


def test_copy_file_does_not_modify_source(tmp_path):
    ctx = _ctx(tmp_path)
    ctx.project_dir.mkdir()
    src = tmp_path / "source.txt"
    src.write_text("original")
    ctx.copy_file(src, "dest.txt")
    assert src.read_text() == "original"


# ── Context.append_to_file ────────────────────────────────────────────────────


def test_append_to_file_appends_content(tmp_path):
    ctx = _ctx(tmp_path)
    ctx.project_dir.mkdir()
    f = ctx.project_dir / "file.txt"
    f.write_text("line1\n")
    ctx.append_to_file("file.txt", "line2\n")
    assert f.read_text() == "line1\nline2\n"


def test_append_to_file_multiple_times(tmp_path):
    ctx = _ctx(tmp_path)
    ctx.project_dir.mkdir()
    f = ctx.project_dir / "file.txt"
    f.write_text("a\n")
    ctx.append_to_file("file.txt", "b\n")
    ctx.append_to_file("file.txt", "c\n")
    assert f.read_text() == "a\nb\nc\n"


# ── Context.record_modification ───────────────────────────────────────────────


def test_record_modification_noop_on_real_context(tmp_path):
    # On a real Context, record_modification is only meaningful in dry_run mode
    ctx = _ctx(tmp_path)
    ctx.project_dir.mkdir()
    # Should not raise and should not create any files
    ctx.record_modification("settings.py", "injected redis_url")
    assert list(ctx.project_dir.iterdir()) == []


# ── Context.execute_command ───────────────────────────────────────────────────


def test_execute_command_runs_command(tmp_path):
    ctx = _ctx(tmp_path)
    ctx.project_dir.mkdir()
    # Use a benign command that always succeeds
    ctx.execute_command(["true"])


def test_execute_command_raises_on_failure(tmp_path):
    ctx = _ctx(tmp_path)
    ctx.project_dir.mkdir()
    with pytest.raises(subprocess.CalledProcessError):
        ctx.execute_command(["false"], check=True)


def test_execute_command_no_raise_when_check_false(tmp_path):
    ctx = _ctx(tmp_path)
    ctx.project_dir.mkdir()
    # Should not raise even though command fails
    ctx.execute_command(["false"], check=False)


# ── DryRunContext — no I/O ────────────────────────────────────────────────────


def test_dry_write_file_does_not_create_file(tmp_path):
    ctx = _dry(tmp_path)
    ctx.write_file("hello.txt", "hello")
    assert not (ctx.project_dir / "hello.txt").exists()


def test_dry_create_dir_does_not_create_dir(tmp_path):
    ctx = _dry(tmp_path)
    ctx.create_dir("src/myapp")
    assert not (ctx.project_dir / "src").exists()


def test_dry_copy_file_does_not_create_file(tmp_path):
    ctx = _dry(tmp_path)
    src = tmp_path / "source.txt"
    src.write_text("data")
    ctx.copy_file(src, "dest.txt")
    assert not (ctx.project_dir / "dest.txt").exists()


def test_dry_append_to_file_does_not_write(tmp_path):
    ctx = _dry(tmp_path)
    # project_dir doesn't exist — should not raise
    ctx.append_to_file("file.txt", "content")
    assert not ctx.project_dir.exists()


def test_dry_execute_command_does_nothing(tmp_path):
    ctx = _dry(tmp_path)
    # Would fail if actually run — should be silently skipped
    ctx.execute_command(["false"], check=True)


# ── DryRunContext — recording ─────────────────────────────────────────────────


def test_dry_write_file_recorded_as_create(tmp_path):
    ctx = _dry(tmp_path)
    ctx.write_file("src/main.py", "# code")
    actions = [a for a, _, _ in ctx.recorded_files]
    assert "create" in actions


def test_dry_write_file_records_path(tmp_path):
    ctx = _dry(tmp_path)
    ctx.write_file("src/main.py", "# code")
    paths = [p for _, p, _ in ctx.recorded_files]
    assert "src/main.py" in paths


def test_dry_create_dir_recorded_as_mkdir(tmp_path):
    ctx = _dry(tmp_path)
    ctx.create_dir("src/myapp")
    actions = [a for a, _, _ in ctx.recorded_files]
    assert "mkdir" in actions


def test_dry_copy_file_recorded_as_copy(tmp_path):
    ctx = _dry(tmp_path)
    src = tmp_path / "source.txt"
    src.write_text("data")
    ctx.copy_file(src, "dest.txt")
    actions = [a for a, _, _ in ctx.recorded_files]
    assert "copy" in actions


def test_dry_append_recorded_as_append(tmp_path):
    ctx = _dry(tmp_path)
    ctx.append_to_file("file.txt", "content")
    actions = [a for a, _, _ in ctx.recorded_files]
    assert "append" in actions


def test_dry_record_modification_recorded_as_modify(tmp_path):
    ctx = _dry(tmp_path)
    ctx.record_modification("settings.py", "injected redis_url field")
    actions = [a for a, _, _ in ctx.recorded_files]
    assert "modify" in actions


def test_dry_record_modification_records_description(tmp_path):
    ctx = _dry(tmp_path)
    ctx.record_modification("settings.py", "injected redis_url field")
    descriptions = [d for _, _, d in ctx.recorded_files]
    assert "injected redis_url field" in descriptions


def test_dry_multiple_operations_all_recorded(tmp_path):
    ctx = _dry(tmp_path)
    src = tmp_path / "s.txt"
    src.write_text("x")
    ctx.create_dir("mydir")
    ctx.write_file("a.py", "")
    ctx.copy_file(src, "b.txt")
    ctx.append_to_file("c.txt", "line")
    ctx.record_modification("d.py", "changed")
    assert len(ctx.recorded_files) == 5


def test_dry_recorded_files_is_list_of_three_tuples(tmp_path):
    ctx = _dry(tmp_path)
    ctx.write_file("a.py", "x")
    ctx.create_dir("mydir")
    for entry in ctx.recorded_files:
        assert isinstance(entry, tuple)
        assert len(entry) == 3
        action, path, details = entry
        assert isinstance(action, str)
        assert isinstance(path, str)
        assert isinstance(details, str)


def test_dry_recorded_files_starts_empty(tmp_path):
    ctx = _dry(tmp_path)
    assert ctx.recorded_files == []


# ── Context fields ────────────────────────────────────────────────────────────


def test_context_stores_name(tmp_path):
    ctx = _ctx(tmp_path, name="cool-project")
    assert ctx.name == "cool-project"


def test_context_stores_pkg_name(tmp_path):
    ctx = Context(
        name="cool-project",
        pkg_name="cool_project",
        template="blank",
        addons=[],
        zenit_root=ZENIT_ROOT,
        project_dir=tmp_path / "cool-project",
    )
    assert ctx.pkg_name == "cool_project"


def test_context_stores_template(tmp_path):
    ctx = _ctx(tmp_path)
    assert ctx.template == "blank"


def test_context_stores_addons(tmp_path):
    ctx = Context(
        name="myapp",
        pkg_name="myapp",
        template="fastapi",
        addons=["docker", "redis"],
        zenit_root=ZENIT_ROOT,
        project_dir=tmp_path / "myapp",
    )
    assert ctx.addons == ["docker", "redis"]


def test_context_stores_zenit_root(tmp_path):
    ctx = _ctx(tmp_path)
    assert ctx.zenit_root == ZENIT_ROOT


def test_context_stores_project_dir(tmp_path):
    ctx = _ctx(tmp_path)
    assert ctx.project_dir == tmp_path / "myapp"
