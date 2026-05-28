"""Tests for zenit.dryrun — preview mode that records operations without writing.

Verifies that RecordingFileSystem captures all file operations and that run_dry
produces the expected output without touching the filesystem.
"""

from __future__ import annotations

from pathlib import Path

from helpers import ZENIT_ROOT

from zenit.core.context import Context
from zenit.core.dryrun import run_dry
from zenit.core.filesystem import RecordingFileSystem


def _real_ctx(
    tmp_path: Path,
    name: str = "myapp",
    template: str = "blank",
    addons: list | None = None,
) -> Context:
    return Context(
        name=name,
        pkg_name=name.replace("-", "_"),
        template=template,
        addons=addons or [],
        zenit_root=ZENIT_ROOT,
        project_dir=tmp_path / name,
    )


def _dry_ctx(
    tmp_path: Path,
    name: str = "myapp",
) -> tuple[Context, RecordingFileSystem]:
    fs = RecordingFileSystem(tmp_path / name)
    ctx = Context(
        name=name,
        pkg_name=name.replace("-", "_"),
        template="blank",
        addons=[],
        zenit_root=ZENIT_ROOT,
        project_dir=tmp_path / name,
        dry_run=True,
    )
    return ctx, fs


# ── dry_run property ─────────────────────────────────────────────────────────


def test_dry_run_context_dry_run_is_true(tmp_path):
    ctx, _ = _dry_ctx(tmp_path)
    assert ctx.dry_run is True


def test_real_context_dry_run_is_false(tmp_path):
    ctx = _real_ctx(tmp_path)
    assert ctx.dry_run is False


# ── RecordingFileSystem recording ──────────────────────────────────────────────


def test_write_file_is_recorded_not_written(tmp_path):
    ctx, fs = _dry_ctx(tmp_path)
    fs.write_file("src/myapp/main.py", "# content")
    assert not (tmp_path / "myapp" / "src" / "myapp" / "main.py").exists()
    assert any(path == "src/myapp/main.py" for (action, path, _) in fs.recorded_files)


def test_create_dir_is_recorded_not_created(tmp_path):
    ctx, fs = _dry_ctx(tmp_path)
    fs.create_dir("src/myapp")
    assert not (tmp_path / "myapp" / "src" / "myapp").exists()
    assert any(action == "mkdir" for (action, _, __) in fs.recorded_files)


def test_copy_file_is_recorded_not_copied(tmp_path):
    src = tmp_path / "source.txt"
    src.write_text("data")
    ctx, fs = _dry_ctx(tmp_path)
    fs.copy_file(src, "dest.txt")
    assert not (tmp_path / "myapp" / "dest.txt").exists()
    assert any(action == "copy" for (action, _, __) in fs.recorded_files)


def test_append_to_file_is_recorded(tmp_path):
    ctx, fs = _dry_ctx(tmp_path)
    fs.append_to_file("somefile.py", "# appended")
    assert any(action == "append" for (action, _, __) in fs.recorded_files)


# ── run_dry — no filesystem side-effects ─────────────────────────────────────


def test_run_dry_blank_does_not_create_project_dir(tmp_path):
    ctx = _real_ctx(tmp_path, template="blank")
    run_dry(ctx)
    assert not (tmp_path / "myapp").exists()


def test_run_dry_blank_docker_does_not_create_project_dir(tmp_path):
    ctx = _real_ctx(tmp_path, template="blank", addons=["docker"])
    run_dry(ctx)
    assert not (tmp_path / "myapp").exists()


def test_run_dry_fastapi_does_not_create_project_dir(tmp_path):
    ctx = _real_ctx(tmp_path, template="fastapi", addons=["docker"])
    run_dry(ctx)
    assert not (tmp_path / "myapp").exists()


# ── run_dry — output content ──────────────────────────────────────────────────


def test_run_dry_blank_output_mentions_project_name(tmp_path, capsys):
    ctx = _real_ctx(tmp_path, name="coolproject", template="blank")
    run_dry(ctx)
    captured = capsys.readouterr()
    assert "coolproject" in captured.out


def test_run_dry_blank_output_mentions_template(tmp_path, capsys):
    ctx = _real_ctx(tmp_path, template="blank")
    run_dry(ctx)
    captured = capsys.readouterr()
    assert "blank" in captured.out


def test_run_dry_blank_output_contains_dry_run_header(tmp_path, capsys):
    ctx = _real_ctx(tmp_path, template="blank")
    run_dry(ctx)
    captured = capsys.readouterr()
    assert "Dry run" in captured.out


def test_run_dry_blank_output_contains_files_section(tmp_path, capsys):
    ctx = _real_ctx(tmp_path, template="blank")
    run_dry(ctx)
    captured = capsys.readouterr()
    assert "Files" in captured.out or "files" in captured.out


def test_run_dry_blank_output_contains_git_command(tmp_path, capsys):
    ctx = _real_ctx(tmp_path, template="blank")
    run_dry(ctx)
    captured = capsys.readouterr()
    assert "git init" in captured.out


def test_run_dry_blank_output_contains_main_py(tmp_path, capsys):
    ctx = _real_ctx(tmp_path, template="blank")
    run_dry(ctx)
    captured = capsys.readouterr()
    assert "main.py" in captured.out


def test_run_dry_with_docker_addon_output_mentions_dockerfile(tmp_path, capsys):
    ctx = _real_ctx(tmp_path, template="blank", addons=["docker"])
    run_dry(ctx)
    captured = capsys.readouterr()
    assert "Dockerfile" in captured.out


def test_run_dry_with_addons_output_mentions_addon(tmp_path, capsys):
    ctx = _real_ctx(tmp_path, template="blank", addons=["docker"])
    run_dry(ctx)
    captured = capsys.readouterr()
    assert "docker" in captured.out


def test_run_dry_output_says_nothing_will_be_written(tmp_path, capsys):
    ctx = _real_ctx(tmp_path, template="blank")
    run_dry(ctx)
    captured = capsys.readouterr()
    assert "Nothing will be written" in captured.out


def test_run_dry_output_contains_dependencies(tmp_path, capsys):
    ctx = _real_ctx(tmp_path, template="blank")
    run_dry(ctx)
    captured = capsys.readouterr()
    assert "Dependencies" in captured.out


def test_run_dry_fastapi_output_mentions_fastapi_dep(tmp_path, capsys):
    ctx = _real_ctx(tmp_path, template="fastapi", addons=["docker"])
    run_dry(ctx)
    captured = capsys.readouterr()
    assert "fastapi" in captured.out


def test_run_dry_fastapi_output_mentions_pydantic_settings(tmp_path, capsys):
    ctx = _real_ctx(tmp_path, template="fastapi", addons=["docker"])
    run_dry(ctx)
    captured = capsys.readouterr()
    assert "pydantic-settings" in captured.out


def test_run_dry_all_fastapi_addons(tmp_path, capsys):
    ctx = _real_ctx(
        tmp_path,
        template="fastapi",
        addons=[
            "docker",
            "postgres",
            "sqlalchemy",
            "redis",
            "celery",
            "sentry",
            "github-actions",
        ],
    )
    run_dry(ctx)
    captured = capsys.readouterr()
    for addon in ["docker", "redis", "celery", "sentry"]:
        assert addon in captured.out


# ── recorded_files structure ──────────────────────────────────────────────────


def test_recorded_files_is_list_of_tuples(tmp_path):
    ctx, fs = _dry_ctx(tmp_path)
    fs.write_file("a.py", "x")
    fs.create_dir("mydir")
    for entry in fs.recorded_files:
        assert isinstance(entry, tuple)
        assert len(entry) == 3
        action, path, details = entry
        assert isinstance(action, str)
        assert isinstance(path, str)
        assert isinstance(details, str)


def test_run_dry_blank_recorded_files_are_non_empty(tmp_path):
    ctx = _real_ctx(tmp_path, template="blank")
    run_dry(ctx)
