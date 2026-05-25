# Commands

Zenit's CLI is intentionally narrow. Each command does one thing, accepts explicit flags rather than inferring intent, and exits with a non-zero code on any error. There are no hidden defaults that change behaviour based on context, no commands that silently succeed when they should have failed.

All commands that modify files support `--dry-run`, which prints exactly what would change without writing anything.

| Command | Description |
|---|---|---|
| [`zenit create`](./create.md) | Scaffold a new project from a template with optional addons |
| [`zenit migrate`](./migrate.md) | Create a new project from a Copier template with zenit lifecycle metadata |
| [`zenit add`](./add.md) | Add one or more addons to the current project |
| [`zenit remove`](./remove.md) | Remove one or more addons from the current project |
| [`zenit doctor`](./doctor.md) | Verify the project's state matches `.zenit.toml` |
| [`zenit list`](./list.md) | List available templates and addons, or what is installed |
| [`zenit config`](../configuration.md) | Show the config file path and current settings |
