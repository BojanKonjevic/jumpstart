"""Migration pipeline — convert Copier templates to zenit-managed projects."""

from .answers import MigrationAnswers
from .api import MigrationResult, _print_migration_report, run_migration
from .tasks import TaskResult

__all__ = [
    "MigrationAnswers",
    "MigrationResult",
    "TaskResult",
    "_print_migration_report",
    "run_migration",
]
