"""Task execution for Copier _tasks during migration."""

from __future__ import annotations

import fnmatch
import re
import shlex
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from zenit.cli.ui import warn

from .copier import CopierTask
from .env import COPIER_ENV

DESTRUCTIVE_PATTERNS: list[str] = [
    "rm *",
    "rm -rf *",
    "rm -rf /*",
    "rm -fr /*",
    "dd *",
    "> /dev/*",
    "> /dev/sd*",
    "mkfs*",
    "fdisk*",
    "format *",
    ":(){ :|:& };:",
    "mv /*",
    "chmod -R 0",
    "chown -R",
    "sudo",
    "pkexec",
]


@dataclass
class TaskResult:
    command: str
    rendered_command: str
    exit_code: int
    stdout: str
    stderr: str
    timed_out: bool = False

    @property
    def succeeded(self) -> bool:
        return self.exit_code == 0 and not self.timed_out


def _task_command(task: CopierTask) -> str | None:
    if isinstance(task, str):
        return task
    command = task.get("command")
    if isinstance(command, str):
        return command
    return None


def _task_enabled(task: CopierTask, render_vars: dict[str, Any]) -> bool:
    if isinstance(task, str):
        return True
    when = task.get("when")
    if not isinstance(when, str) or not when.strip():
        return True
    rendered = COPIER_ENV.from_string(when).render(**render_vars).strip().lower()
    return rendered in ("1", "true", "yes", "y", "on")


def _check_destructive_command(command: str) -> str | None:
    command_lower = command.lower().strip()
    for pattern in DESTRUCTIVE_PATTERNS:
        if fnmatch.fnmatch(command_lower, pattern) or fnmatch.fnmatch(
            command_lower, f"* {pattern}"
        ):
            return pattern
    return None


def _task_first_executable(command: str) -> str | None:
    first = re.split(r"\s*(?:&&|\|\||;|\||>)\s*", command.strip())[0]
    parts = shlex.split(first)
    return parts[0] if parts else None


def _execute_task(
    task: CopierTask,
    project_dir: Path,
    render_vars: dict[str, Any],
    timeout: float = 300.0,
) -> TaskResult | None:
    if not _task_enabled(task, render_vars):
        return None

    command = _task_command(task)
    if command is None:
        return None

    rendered = COPIER_ENV.from_string(command).render(**render_vars)

    executable = _task_first_executable(rendered)
    if executable is not None and shutil.which(executable) is None:
        warn(
            f"Skipping task: '{rendered!r}' — "
            f"'{executable}' is not installed. "
            f"Run it manually after installing {executable}."
        )
        return TaskResult(
            command,
            rendered,
            -1,
            "",
            f"'{executable}' not found on PATH",
            timed_out=False,
        )

    destructive = _check_destructive_command(rendered)
    if destructive:
        warn(
            f"Skipping destructive-looking task: {rendered!r} "
            f"(matched pattern: {destructive}). "
            f"Run it manually after review."
        )
        return TaskResult(
            command,
            rendered,
            -1,
            "",
            "blocked by destructive pattern check",
            timed_out=False,
        )

    try:
        proc = subprocess.run(
            rendered,
            shell=True,
            capture_output=True,
            text=True,
            cwd=str(project_dir),
            timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        warn(f"Task timed out after {timeout}s: {rendered!r}")
        return TaskResult(
            command, rendered, -1, "", f"timed out after {timeout}s", timed_out=True
        )

    if proc.returncode != 0:
        warn(f"Task failed (exit {proc.returncode}): {rendered!r}")

    return TaskResult(
        command,
        rendered,
        proc.returncode,
        proc.stdout,
        proc.stderr,
        timed_out=False,
    )


def _execute_tasks(
    tasks: list[CopierTask],
    project_dir: Path,
    render_vars: dict[str, Any],
    timeout: float = 300.0,
) -> list[TaskResult]:
    failed: list[TaskResult] = []
    for task in tasks:
        result = _execute_task(task, project_dir, render_vars, timeout)
        if result is not None and not result.succeeded:
            failed.append(result)
    return failed


def _write_task_stub(project_dir: Path, failed: list[TaskResult]) -> None:
    if not failed:
        return
    stub_path = project_dir / ".zenit-tasks.md"
    lines = [
        "# Manual Tasks (from Copier _tasks)",
        "",
        "The following tasks failed or were blocked during migration.",
        "Review and run them manually if needed.",
        "",
    ]
    for i, task in enumerate(failed, 1):
        lines.append(f"## {i}. {task.rendered_command}")
        if task.exit_code != -1:
            lines.append(f"- **Status:** Failed (exit {task.exit_code})")
        elif task.timed_out:
            lines.append("- **Status:** Timed out")
        else:
            lines.append("- **Status:** Blocked")
        if task.stderr:
            lines.append(f"- **Stderr:** {task.stderr.strip()}")
        if task.stdout:
            lines.append(f"- **Stdout:** {task.stdout.strip()}")
        lines.append("")
    stub_path.write_text("\n".join(lines), encoding="utf-8")
