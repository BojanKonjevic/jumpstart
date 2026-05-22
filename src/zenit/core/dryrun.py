"""Dry-run mode — faithful preview by running the scaffold pipeline with a
recording context that captures every file operation without touching disk."""

from __future__ import annotations

from zenit.addons._registry import get_available_addons
from zenit.cli.ui import (
    BOLD,
    DIM,
    GREEN,
    MAGENTA,
    RESET,
    dry_cmd,
    dry_dep,
    dry_header,
    dry_section,
)
from zenit.core._apply_loader import load_apply
from zenit.core.apply import apply_contributions
from zenit.core.collect import collect_all
from zenit.core.context import Context
from zenit.core.filesystem import RecordingFileSystem
from zenit.core.generate import generate_all
from zenit.core.render import build_render_vars
from zenit.templates._load_config import load_template_config


def run_dry(ctx: Context) -> None:
    """Run the scaffold pipeline with a ``RecordingFileSystem`` and print the manifest."""
    fs = RecordingFileSystem(ctx.project_dir)
    dry_ctx = Context(
        name=ctx.name,
        pkg_name=ctx.pkg_name,
        template=ctx.template,
        addons=ctx.addons,
        zenit_root=ctx.zenit_root,
        project_dir=ctx.project_dir,
        _fs=fs,
    )

    sr = dry_ctx.zenit_root
    load_apply(sr / "templates" / "_common" / "apply.py")(dry_ctx)

    available = get_available_addons()
    template_config = load_template_config(sr, dry_ctx.template)
    selected_addon_configs = [cfg for cfg in available if cfg.id in dry_ctx.addons]

    contributions = collect_all(template_config, selected_addon_configs)

    render_vars = build_render_vars(
        name=ctx.name,
        pkg_name=ctx.pkg_name,
        template=ctx.template,
        addons=dry_ctx.addons,
    )

    apply_contributions(
        dry_ctx,
        contributions,
        template_config.injection_points,
        render_vars,
    )

    generate_all(dry_ctx, contributions)

    label = dry_ctx.template
    if dry_ctx.addons:
        label += " + " + ", ".join(dry_ctx.addons)

    print(f"\n  {BOLD}{MAGENTA}Dry run:{RESET} {dry_ctx.name}  {DIM}({label}){RESET}")
    print(f"  {DIM}Nothing will be written to disk.{RESET}\n")

    dry_header("Files that would be created or modified")

    for action, path, details in fs.recorded_files:
        if action == "mkdir":
            print(f"  {MAGENTA}►{RESET} {path}/")
        elif action in ("create", "copy"):
            suffix = f"  {DIM}{details}{RESET}" if details else ""
            print(f"  {GREEN}+{RESET} {path}{suffix}")
        elif action == "append":
            print(f"  {GREEN}+{RESET} {path}  {DIM}(appended){RESET}")
        elif action == "modify":
            print(f"  {GREEN}△{RESET} {path}  {DIM}{details}{RESET}")

    print()
    dry_section("Dependencies (pyproject.toml)")
    dry_section("  runtime")
    for dep in template_config.deps:
        dry_dep(dep)
    for dep in contributions.deps:
        dry_dep(dep, "addon")
    dry_section("  dev")
    for dep in template_config.dev_deps:
        dry_dep(dep, "template")
    for dep in contributions.dev_deps:
        dry_dep(dep, "addon")

    dry_header("Generated config files")
    for file_name in ["pyproject.toml", "justfile"]:
        dry_dep(file_name)

    dry_header("Commands that would run")
    for cmd in [
        "direnv allow",
        "git init",
        "git add .",
    ]:
        dry_cmd(cmd)

    print()
    print(f"  {DIM}Run without --dry-run to create the project.{RESET}\n")
