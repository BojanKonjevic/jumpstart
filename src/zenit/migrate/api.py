"""Main migration pipeline - ``zenit migrate`` entry point."""

from __future__ import annotations

import shutil
from dataclasses import dataclass, field
from pathlib import Path

from zenit.cli.ui import BOLD, CYAN, DIM, RESET, YELLOW, step, success, warn
from zenit.core.git import init as git_init
from zenit.core.lockfile import write_zenit_toml
from zenit.core.manifest import (
    add_compose_service,
    add_compose_volume,
    add_dependency,
    add_env_entry,
    read_manifest,
)
from zenit.core.rollback import scaffold_or_rollback
from zenit.schema.exceptions import ZenitError
from zenit.schema.models import EntrySource

from .answers import (
    _prompt_questions,
    _resolve_answers_noninteractive,
    _stabilise_render_vars,
)
from .copier import classify_questions, parse_copier_yml
from .env import build_extended_env
from .fetch import (
    _cleanup_temp,
    _fetch_source,
    _normalise_source,
    _pick_project_name,
)
from .files import (
    _apply_safe_task_file_ops,
    _apply_skip_if_exists,
    _find_copier_file,
    _render_destination_path,
    _render_template,
    _resolve_content_dir,
    _uses_copier_internal_path_vars,
)
from .inventory import _inventory_compose, _inventory_deps, _inventory_env
from .render import _render_file_content, _scan_for_unresolved_markers
from .tasks import _execute_tasks, _write_task_stub


@dataclass
class MigrationResult:
    project_dir: Path
    template_source: str
    file_paths: list[str] = field(default_factory=list)
    addon_ids: list[str] = field(default_factory=list)
    has_tasks: bool = False
    env_count: int = 0
    compose_service_count: int = 0
    compose_volume_count: int = 0
    dep_count: int = 0


def _print_migration_report(result: MigrationResult) -> None:
    print()
    success("Migration complete.")
    print()
    print(f"  {BOLD}Template:{RESET}   {CYAN}{result.template_source}{RESET}")
    print(f"  {BOLD}Project:{RESET}    {result.project_dir.name}/")
    print()

    print(f"  {BOLD}Presence-tracked only:{RESET}")
    print(f"    ~ {len(result.file_paths)} files tracked via template_file_paths")
    if result.env_count > 0:
        print(f"    ~ {result.env_count} env var(s) with source=template")
    if result.compose_service_count > 0:
        print(
            f"    ~ {result.compose_service_count} compose service(s) with source=template"
        )
    if result.compose_volume_count > 0:
        print(
            f"    ~ {result.compose_volume_count} compose volume(s) with source=template"
        )
    if result.dep_count > 0:
        print(f"    ~ {result.dep_count} dependencies with source=template")
    print()

    if result.has_tasks:
        print(
            f"  {YELLOW}!{RESET}  {BOLD}Manual steps required:{RESET} "
            f"Copier _tasks were not executed."
        )
        print(
            f"      See {CYAN}.zenit-tasks.md{RESET} for the list of commands "
            f"to run manually."
        )
        print()

    print(
        f"  {DIM}Most post-creation lifecycle features (zenit add, zenit remove,{RESET}"
    )
    print(
        f"  {DIM}zenit doctor integrity checks) work fully only for components{RESET}"
    )
    print(f"  {DIM}zenit owns outright. Run 'zenit doctor' to see{RESET}")
    print(f"  {DIM}the current health report.{RESET}")
    print()


def run_migration(
    source: str,
    *,
    name: str | None = None,
    data: dict[str, str] | None = None,
    task_timeout: float = 300.0,
) -> MigrationResult:
    step("Fetching template source")
    template_dir = _fetch_source(source)
    normalised_source = _normalise_source(source)
    template_source = normalised_source

    copier_yml = _find_copier_file(template_dir)
    config = parse_copier_yml(copier_yml)

    step("Analyzing template questions")
    classes = classify_questions(config, template_dir)

    non_interactive = name is not None or data

    if non_interactive:
        step("Resolving template answers (non-interactive)")
        overrides: dict[str, str] = {}
        if name is not None:
            overrides["project_name"] = name
        if data is not None:
            overrides.update(data)
        answers = _resolve_answers_noninteractive(config, overrides)
        if "project_name" not in answers.render_vars and "project_name" in overrides:
            answers.render_vars["project_name"] = overrides["project_name"]
        overridden_names: set[str] = set(overrides.keys())
    else:
        step("Prompting for template answers")
        answers = _prompt_questions(config, classes)
        overridden_names = answers.explicit_names

    project_name = _pick_project_name(
        answers.render_vars.get("project_name"),
        answers.render_vars.get("name"),
        normalised_source,
        template_dir,
    )
    answers.render_vars["project_name"] = project_name
    overridden_names.add("project_name")

    _stabilise_render_vars(config, answers, overridden_names)

    project_dir = (Path.cwd() / project_name).resolve()

    if project_dir.exists():
        raise ZenitError(
            f"Directory '{project_dir}' already exists. "
            f"Choose a different project name or output directory."
        )

    step("Rendering template files")
    file_contributions = _render_template(template_dir)
    file_contributions, pending_tasks = _apply_safe_task_file_ops(
        file_contributions, config.tasks, answers.render_vars, project_dir
    )
    file_contributions = _apply_skip_if_exists(
        file_contributions, config.skip_if_exists, project_dir, answers.render_vars
    )

    content_dir = _resolve_content_dir(template_dir, config)
    render_env = build_extended_env(config, template_dir, content_dir)

    if config.message_before_copy:
        step("Template message")
        msg = render_env.from_string(config.message_before_copy).render(
            **answers.render_vars
        )
        print(f"\n{msg}\n")

    step("Writing project")
    file_paths: list[str] = []
    rendered_file_paths: set[str] = set()
    question_names: set[str] = {q.name for q in config.questions}
    with scaffold_or_rollback(project_dir):
        project_dir.mkdir(parents=True)

        for fc in file_contributions:
            if _uses_copier_internal_path_vars(fc.dest):
                warn(
                    f"Skipping '{fc.dest}' - destination depends on Copier-only "
                    f"variables (prefixed with _copier_)."
                )
                continue
            dest_rel = _render_destination_path(fc.dest, answers.render_vars)
            if dest_rel is None:
                warn(
                    f"Skipping '{fc.dest}' - rendered destination is empty or unsafe "
                    f"(likely a conditional path whose condition was false)."
                )
                continue
            dest_path = project_dir / dest_rel
            if dest_path.exists() and dest_path.is_dir():
                warn(
                    f"Skipping '{fc.dest}' - rendered path '{dest_rel}' already "
                    f"exists as a directory."
                )
                continue
            if any(
                p.exists() and p.is_file()
                for p in [dest_path] + list(dest_path.parents)
                if p != project_dir
            ):
                warn(
                    f"Skipping '{fc.dest}' - rendered path '{dest_rel}' "
                    f"collides with an existing file."
                )
                continue
            rel = str(dest_path.relative_to(project_dir))
            file_paths.append(rel)
            dest_path.parent.mkdir(parents=True, exist_ok=True)
            if fc.content is not None:
                if fc.template:
                    rendered_content, diagnostic = _render_file_content(
                        fc.content,
                        render_env,
                        answers.render_vars,
                        question_names,
                    )
                    if rendered_content is not None:
                        dest_path.write_text(rendered_content, encoding="utf-8")
                        rendered_file_paths.add(str(dest_rel))
                        if diagnostic:
                            warn(f"Partially rendered '{dest_rel}': {diagnostic}")
                    else:
                        dest_path.write_text(fc.content, encoding="utf-8")
                        warn(
                            f"Failed to render '{dest_rel}' - written verbatim. "
                            f"Reason: {diagnostic}"
                        )
                else:
                    dest_path.write_text(fc.content, encoding="utf-8")
            elif fc.source is not None:
                shutil.copy2(fc.source, dest_path)

    if config.message_after_copy:
        step("Template message (after copy)")
        msg = render_env.from_string(config.message_after_copy).render(
            **answers.render_vars
        )
        print(f"\n{msg}\n")

    unresolved = _scan_for_unresolved_markers(project_dir, rendered_file_paths)
    for path in unresolved:
        warn(
            f"Unresolved Copier marker(s) found in '{path}' - "
            f"the template variable may be misspelled or missing."
        )

    step("Scanning project inventory")
    env_keys = _inventory_env(project_dir)
    compose_services, compose_volumes = _inventory_compose(project_dir)
    deps = _inventory_deps(project_dir)

    step("Writing manifest and lockfile")
    manifest = read_manifest(project_dir)

    for key in env_keys:
        add_env_entry(manifest, key, source=EntrySource.TEMPLATE, addon="")
    for svc in compose_services:
        add_compose_service(manifest, svc, source=EntrySource.TEMPLATE, addon="")
    for vol in compose_volumes:
        add_compose_volume(manifest, vol, source=EntrySource.TEMPLATE, addon="")
    for pkg, spec, dev in deps:
        add_dependency(
            manifest, pkg, spec, source=EntrySource.TEMPLATE, addon="", dev=dev
        )

    write_zenit_toml(
        project_dir,
        template=template_source,
        addons=[],
        template_source="copier",
        template_uri=template_source,
        template_has_tasks=bool(pending_tasks),
        template_file_paths=sorted(set(file_paths)),
        manifest=manifest,
    )

    step("Processing tasks")
    failed_tasks = _execute_tasks(
        pending_tasks, project_dir, answers.render_vars, task_timeout
    )
    _write_task_stub(project_dir, failed_tasks)

    step("Initialising git repository")
    git_init(project_dir)

    result = MigrationResult(
        project_dir=project_dir,
        template_source=template_source,
        file_paths=sorted(set(file_paths)),
        addon_ids=[],
        has_tasks=bool(failed_tasks),
        env_count=len(env_keys),
        compose_service_count=len(compose_services),
        compose_volume_count=len(compose_volumes),
        dep_count=len(deps),
    )

    _cleanup_temp(template_dir)

    return result
