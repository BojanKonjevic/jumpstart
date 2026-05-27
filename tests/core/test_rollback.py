"""Tests for zenit.rollback — cleanup context managers.

Covers scaffold_or_rollback (removes the whole project dir on failure) and
addon_or_rollback (removes only files added during the failed addon apply).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from zenit.core.rollback import addon_or_rollback, batch_snapshot, scaffold_or_rollback

# ── scaffold_or_rollback — success ────────────────────────────────────────────


def test_scaffold_success_leaves_directory(tmp_path):
    project_dir = tmp_path / "myapp"
    project_dir.mkdir()
    with scaffold_or_rollback(project_dir):
        (project_dir / "main.py").write_text("# main")
    assert project_dir.exists()
    assert (project_dir / "main.py").exists()


def test_scaffold_success_no_cleanup(tmp_path):
    project_dir = tmp_path / "myapp"
    project_dir.mkdir()
    sentinel = project_dir / "sentinel.txt"
    sentinel.write_text("keep me")
    with scaffold_or_rollback(project_dir):
        pass
    assert sentinel.exists()


# ── scaffold_or_rollback — exception ─────────────────────────────────────────


def test_scaffold_failure_removes_directory(tmp_path):
    project_dir = tmp_path / "myapp"
    project_dir.mkdir()
    (project_dir / "partial.py").write_text("incomplete")
    with pytest.raises(SystemExit), scaffold_or_rollback(project_dir):
        raise RuntimeError("scaffold exploded")
    assert not project_dir.exists()


def test_scaffold_failure_removes_nested_files(tmp_path):
    project_dir = tmp_path / "myapp"
    project_dir.mkdir()
    nested = project_dir / "src" / "myapp"
    nested.mkdir(parents=True)
    (nested / "main.py").write_text("# main")
    with pytest.raises(SystemExit), scaffold_or_rollback(project_dir):
        raise RuntimeError("boom")
    assert not project_dir.exists()


def test_scaffold_failure_raises_system_exit(tmp_path):
    project_dir = tmp_path / "myapp"
    project_dir.mkdir()
    with pytest.raises(SystemExit) as exc_info, scaffold_or_rollback(project_dir):
        raise RuntimeError("boom")
    assert exc_info.value.code == 1


def test_scaffold_system_exit_propagates_and_cleans_up(tmp_path):
    project_dir = tmp_path / "myapp"
    project_dir.mkdir()
    (project_dir / "file.py").write_text("x")
    with pytest.raises(SystemExit), scaffold_or_rollback(project_dir):
        raise SystemExit(1)
    assert not project_dir.exists()


def test_scaffold_keyboard_interrupt_removes_directory(tmp_path):
    project_dir = tmp_path / "myapp"
    project_dir.mkdir()
    (project_dir / "partial.py").write_text("x")
    with pytest.raises(KeyboardInterrupt), scaffold_or_rollback(project_dir):
        raise KeyboardInterrupt
    assert not project_dir.exists()


def test_scaffold_keyboard_interrupt_re_raises(tmp_path):
    project_dir = tmp_path / "myapp"
    project_dir.mkdir()
    with pytest.raises(KeyboardInterrupt), scaffold_or_rollback(project_dir):
        raise KeyboardInterrupt


def test_cleanup_warns_when_rmtree_fails(tmp_path, monkeypatch):
    project_dir = tmp_path / "myapp"
    project_dir.mkdir()
    (project_dir / "main.py").write_text("x")

    warns = []
    monkeypatch.setattr("zenit.core.rollback.warn", lambda msg: warns.append(msg))

    def fake_rmtree(*args: object, **kwargs: object) -> None:
        onerror = kwargs.get("onerror")
        if onerror:
            onerror(None, str(project_dir / "main.py"), None)

    monkeypatch.setattr("shutil.rmtree", fake_rmtree)

    from zenit.core.rollback import _cleanup

    _cleanup(project_dir)

    assert len(warns) > 0
    assert any("manually" in w for w in warns)


def test_scaffold_cleanup_when_directory_already_gone(tmp_path):
    # If the directory was already removed inside the block, cleanup should not raise
    project_dir = tmp_path / "myapp"
    project_dir.mkdir()
    with pytest.raises(SystemExit), scaffold_or_rollback(project_dir):
        project_dir.rmdir()
        raise RuntimeError("boom")


# ── addon_or_rollback — success ───────────────────────────────────────────────


def test_addon_success_leaves_new_files(tmp_path):
    project_dir = tmp_path / "myapp"
    project_dir.mkdir()
    (project_dir / "existing.py").write_text("# existing")
    with addon_or_rollback(project_dir, "redis"):
        (project_dir / "redis.py").write_text("# redis")
    assert (project_dir / "redis.py").exists()
    assert (project_dir / "existing.py").exists()


def test_addon_success_leaves_existing_files(tmp_path):
    project_dir = tmp_path / "myapp"
    project_dir.mkdir()
    existing = project_dir / "main.py"
    existing.write_text("# main")
    with addon_or_rollback(project_dir, "sentry"):
        pass
    assert existing.exists()


# ── addon_or_rollback — exception ─────────────────────────────────────────────


def test_addon_failure_removes_new_files(tmp_path):
    project_dir = tmp_path / "myapp"
    project_dir.mkdir()
    (project_dir / "existing.py").write_text("# existing")
    with pytest.raises(SystemExit), addon_or_rollback(project_dir, "redis"):
        (project_dir / "redis.py").write_text("# redis")
        raise RuntimeError("addon failed")
    assert not (project_dir / "redis.py").exists()


def test_addon_failure_preserves_existing_files(tmp_path):
    project_dir = tmp_path / "myapp"
    project_dir.mkdir()
    existing = project_dir / "main.py"
    existing.write_text("# main")
    with pytest.raises(SystemExit), addon_or_rollback(project_dir, "redis"):
        (project_dir / "redis.py").write_text("# redis")
        raise RuntimeError("boom")
    assert existing.exists()


def test_addon_failure_raises_system_exit(tmp_path):
    project_dir = tmp_path / "myapp"
    project_dir.mkdir()
    with pytest.raises(SystemExit) as exc_info, addon_or_rollback(project_dir, "redis"):
        raise RuntimeError("boom")
    assert exc_info.value.code == 1


def test_addon_failure_removes_nested_new_files(tmp_path):
    project_dir = tmp_path / "myapp"
    project_dir.mkdir()
    with pytest.raises(SystemExit), addon_or_rollback(project_dir, "redis"):
        nested = project_dir / "src" / "integrations"
        nested.mkdir(parents=True)
        (nested / "redis.py").write_text("# redis")
        raise RuntimeError("boom")
    assert not (project_dir / "src" / "integrations" / "redis.py").exists()


def test_addon_failure_removes_new_empty_dirs(tmp_path):
    project_dir = tmp_path / "myapp"
    project_dir.mkdir()
    with pytest.raises(SystemExit), addon_or_rollback(project_dir, "redis"):
        new_dir = project_dir / "src" / "integrations"
        new_dir.mkdir(parents=True)
        raise RuntimeError("boom")
    assert not (project_dir / "src" / "integrations").exists()


def test_addon_failure_does_not_remove_pre_existing_dirs(tmp_path):
    project_dir = tmp_path / "myapp"
    project_dir.mkdir()
    existing_dir = project_dir / "src"
    existing_dir.mkdir()
    (existing_dir / "main.py").write_text("# main")
    with pytest.raises(SystemExit), addon_or_rollback(project_dir, "redis"):
        (existing_dir / "redis.py").write_text("# redis")
        raise RuntimeError("boom")
    # The pre-existing src/ dir must still be there
    assert existing_dir.exists()
    assert (existing_dir / "main.py").exists()
    # Only the new file is gone
    assert not (existing_dir / "redis.py").exists()


def test_addon_keyboard_interrupt_removes_new_files(tmp_path):
    project_dir = tmp_path / "myapp"
    project_dir.mkdir()
    with pytest.raises(KeyboardInterrupt), addon_or_rollback(project_dir, "redis"):
        (project_dir / "redis.py").write_text("# redis")
        raise KeyboardInterrupt
    assert not (project_dir / "redis.py").exists()


def test_addon_keyboard_interrupt_re_raises(tmp_path):
    project_dir = tmp_path / "myapp"
    project_dir.mkdir()
    with pytest.raises(KeyboardInterrupt), addon_or_rollback(project_dir, "redis"):
        raise KeyboardInterrupt


def test_addon_failure_multiple_new_files_all_removed(tmp_path):
    project_dir = tmp_path / "myapp"
    project_dir.mkdir()
    with pytest.raises(SystemExit), addon_or_rollback(project_dir, "celery"):
        (project_dir / "celery_app.py").write_text("# celery")
        (project_dir / "tasks.py").write_text("# tasks")
        (project_dir / "beat.py").write_text("# beat")
        raise RuntimeError("boom")
    assert not (project_dir / "celery_app.py").exists()
    assert not (project_dir / "tasks.py").exists()
    assert not (project_dir / "beat.py").exists()


def test_addon_system_exit_propagates_and_cleans_up(tmp_path):
    project_dir = tmp_path / "myapp"
    project_dir.mkdir()
    with pytest.raises(SystemExit), addon_or_rollback(project_dir, "redis"):
        (project_dir / "redis.py").write_text("x")
        raise SystemExit(1)
    assert not (project_dir / "redis.py").exists()


def test_addon_no_new_files_on_failure_leaves_project_intact(tmp_path):
    project_dir = tmp_path / "myapp"
    project_dir.mkdir()
    (project_dir / "main.py").write_text("# main")
    with pytest.raises(SystemExit), addon_or_rollback(project_dir, "redis"):
        # No new files written before the error
        raise RuntimeError("boom")
    assert (project_dir / "main.py").exists()
    assert project_dir.exists()


# ── addon_or_rollback — content restoration ──────────────────────────────────


def test_addon_failure_restores_modified_existing_file(tmp_path):
    project_dir = tmp_path / "myapp"
    project_dir.mkdir()
    existing = project_dir / "pyproject.toml"
    existing.write_text('[project]\nname = "myapp"\n')
    with pytest.raises(SystemExit), addon_or_rollback(project_dir, "redis"):
        existing.write_text('[project]\nname = "myapp"\ndependencies = ["redis"]\n')
        raise RuntimeError("boom")
    assert existing.read_text() == '[project]\nname = "myapp"\n'


def test_addon_failure_restores_multiple_modified_files(tmp_path):
    project_dir = tmp_path / "myapp"
    project_dir.mkdir()
    f1 = project_dir / "main.py"
    f2 = project_dir / "settings.py"
    f1.write_text("# original main")
    f2.write_text("# original settings")
    with pytest.raises(SystemExit), addon_or_rollback(project_dir, "redis"):
        f1.write_text("# modified main")
        f2.write_text("# modified settings")
        raise RuntimeError("boom")
    assert f1.read_text() == "# original main"
    assert f2.read_text() == "# original settings"


def test_addon_mixed_new_and_modified(tmp_path):
    project_dir = tmp_path / "myapp"
    project_dir.mkdir()
    existing = project_dir / "main.py"
    existing.write_text("# original")
    with pytest.raises(SystemExit), addon_or_rollback(project_dir, "redis"):
        existing.write_text("# modified")
        (project_dir / "new_file.py").write_text("# new")
        raise RuntimeError("boom")
    assert existing.read_text() == "# original"
    assert not (project_dir / "new_file.py").exists()


def test_addon_success_preserves_modifications(tmp_path):
    project_dir = tmp_path / "myapp"
    project_dir.mkdir()
    existing = project_dir / "main.py"
    existing.write_text("# original")
    with addon_or_rollback(project_dir, "redis"):
        existing.write_text("# modified and kept")
    assert existing.read_text() == "# modified and kept"


def test_addon_content_restored_when_file_deleted(tmp_path):
    project_dir = tmp_path / "myapp"
    project_dir.mkdir()
    existing = project_dir / "main.py"
    existing.write_text("# content to restore")
    with pytest.raises(SystemExit), addon_or_rollback(project_dir, "redis"):
        existing.unlink()
        raise RuntimeError("boom")
    assert existing.exists()
    assert existing.read_text() == "# content to restore"


def test_addon_failure_restores_valid_cwd(tmp_path, monkeypatch):
    project_dir = tmp_path / "myapp"
    project_dir.mkdir()
    monkeypatch.chdir(project_dir)

    with pytest.raises(SystemExit), addon_or_rollback(project_dir, "redis"):
        (project_dir / "redis.py").write_text("# redis")
        raise RuntimeError("boom")

    assert Path.cwd() == project_dir


# ── batch_snapshot ────────────────────────────────────────────────────────────


def test_batch_snapshot_success_leaves_changes(tmp_path):
    project_dir = tmp_path / "myapp"
    project_dir.mkdir()
    (project_dir / "existing.py").write_text("# existing")
    with batch_snapshot(project_dir, "batch"):
        (project_dir / "new.py").write_text("# new")
    assert (project_dir / "new.py").exists()
    assert (project_dir / "existing.py").exists()


def test_batch_snapshot_failure_restores_everything(tmp_path):
    project_dir = tmp_path / "myapp"
    project_dir.mkdir()
    (project_dir / "existing.py").write_text("# existing")
    with pytest.raises(SystemExit), batch_snapshot(project_dir, "batch"):
        (project_dir / "new.py").write_text("# new")
        raise RuntimeError("batch failed")
    assert not (project_dir / "new.py").exists()
    assert (project_dir / "existing.py").read_text() == "# existing"


def test_batch_snapshot_restores_modified_files(tmp_path):
    project_dir = tmp_path / "myapp"
    project_dir.mkdir()
    existing = project_dir / "config.toml"
    existing.write_text("key = 'original'")
    with pytest.raises(SystemExit), batch_snapshot(project_dir, "batch"):
        existing.write_text("key = 'modified'")
        raise RuntimeError("boom")
    assert existing.read_text() == "key = 'original'"


def test_batch_snapshot_restores_deleted_files(tmp_path):
    project_dir = tmp_path / "myapp"
    project_dir.mkdir()
    existing = project_dir / "main.py"
    existing.write_text("# content to restore")
    with pytest.raises(SystemExit), batch_snapshot(project_dir, "batch"):
        existing.unlink()
        raise RuntimeError("boom")
    assert existing.exists()
    assert existing.read_text() == "# content to restore"


def test_batch_snapshot_keyboard_interrupt_restores(tmp_path):
    project_dir = tmp_path / "myapp"
    project_dir.mkdir()
    with pytest.raises(KeyboardInterrupt), batch_snapshot(project_dir, "batch"):
        (project_dir / "new.py").write_text("# new")
        raise KeyboardInterrupt
    assert not (project_dir / "new.py").exists()


def test_batch_snapshot_system_exit_restores(tmp_path):
    project_dir = tmp_path / "myapp"
    project_dir.mkdir()
    with pytest.raises(SystemExit), batch_snapshot(project_dir, "batch"):
        (project_dir / "new.py").write_text("# new")
        raise SystemExit(1)
    assert not (project_dir / "new.py").exists()


def test_batch_snapshot_multiple_new_files_all_removed(tmp_path):
    project_dir = tmp_path / "myapp"
    project_dir.mkdir()
    with pytest.raises(SystemExit), batch_snapshot(project_dir, "batch"):
        (project_dir / "a.py").write_text("# a")
        (project_dir / "b.py").write_text("# b")
        (project_dir / "c.py").write_text("# c")
        raise RuntimeError("boom")
    assert not (project_dir / "a.py").exists()
    assert not (project_dir / "b.py").exists()
    assert not (project_dir / "c.py").exists()
