# zenit migrate

Create a new project from a Copier template, bootstrapped with zenit's manifest
and lifecycle metadata.

```
zenit migrate <source> [--name <name>] [--data key=value ...]
```

`migrate` accepts a Copier template (local directory path or GitHub URL),
prompts for the same questions you would answer with Copier, renders the
template, and writes the result as a zenit-managed project. The project
directory is created in the current working directory and named after the
`project_name` answer.

After migration, `zenit doctor` reports which content is presence-tracked
(visible to zenit but not under full lifecycle management).

---

## Arguments

**`<source>`** — The Copier template source. One of:

| Format | Example |
|---|---|
| Local directory | `./path/to/template` |
| GitHub URL | `https://github.com/user/repo` |
| Shorthand | `gh:user/repo` |
| Shorthand (user=repo) | `gh:user` |

GitHub URLs are `git clone --depth=1` into a temporary directory, cleaned up
after migration. Local paths are used directly.

---

## Options

**`--name`, `-n`** — Project name. When provided, all questions are answered with
their defaults (or overridden via `--data`). The project directory is created in
the current directory with this name.

**`--data`, `-D`** — Override a template question value. Repeatable:

```
zenit migrate gh:user/template -D use_redis=yes -D project_name=myapp
```

**`--task-timeout`** — Per-task timeout in seconds for Copier `_tasks` execution.
Default is 300.

---

## Interactive mode

Without `--name` or `--data`, the migrator prompts for every question defined
in `copier.yml`:

```
  Project name [myproject]: myapp
  Add Redis? [y/N]: y
```

Answers are type-coerced (strings, integers, booleans). An empty answer uses
the default. Boolean questions accept `y`, `yes`, `n`, `no` (case-insensitive).

---

## Non-interactive mode

Passing `--name` or any `--data` flag enables non-interactive mode. Every
question takes its default value, overridden by any `--data` flags. Questions
without a default that are not covered by `--data` cause an error.

Templated defaults (e.g. <code v-pre>package_name: "{{ project_name | replace('-', '_') }}"</code>)
are resolved in question order at render time, matching Copier's behavior.

---

## What gets written

| Artifact | Description |
|---|---|
| **Template files** | Rendered using Copier's Jinja2 environment and written as static content |
| **`.zenit.toml`** | `[project]` section with `template`, `template_source = "copier"`, `template_uri`, `template_file_paths`, and `template_has_tasks` |
| **Manifest** | `source = "template"` entries for all detected env vars, compose services, dependencies, and compose volumes |
| **`.zenit-tasks.md`** | Written when `_tasks` fail or are blocked and cannot be automatically applied |

Safe tasks (`mv` and `rm -f` / `rm -rf`) are applied automatically during
migration and do not appear as manual steps. `mkdir -p` tasks are also
applied automatically.

The `[project]` section contains:

```
[project]
template = "https://github.com/user/repo"
template_source = "copier"
template_uri = "https://github.com/user/repo"
template_has_tasks = false
template_file_paths = [
    "README.md",
    "main.py",
]
```

---

## Migration report

After a successful migration:

```
Migration complete.

  Template:   https://github.com/user/fastapi-template
  Project:    myproject/

  Presence-tracked only:
    ~ 12 files tracked via template_file_paths
    ~ 3 env var(s) with source=template
    ~ 1 compose service(s) with source=template
    ~ 5 dependencies with source=template

  ! Manual steps required: Copier _tasks were not executed.
      See .zenit-tasks.md for the list of commands to run manually.

  Most post-creation lifecycle features (zenit add, zenit remove,
  zenit doctor integrity checks) work fully only for components
  zenit owns outright. Run 'zenit doctor' to see
  the current health report.
```

---

## Post-migration lifecycle

After migration, the project has a valid `.zenit.toml` with presence-tracked
entries. The following commands work with caveats:

| Command | Behavior |
|---|---|
| `zenit add <addon>` | Upgrades presence-tracked (template-sourced) entries to ADDON ownership. Warns before overriding files from the Copier template. |
| `zenit remove <addon>` | Removes ADDON-owned entries only. Never touches template-sourced entries. |
| `zenit doctor` | Reports template-sourced entries as warnings via the unmanaged-content check. Reports an ERROR if `template_has_tasks` is true, with a hint to check `.zenit-tasks.md`. |

---

## Exit codes

| Code | Meaning |
|---|---|
| `0` | Migration succeeded |
| `1` | Migration failed (missing source, template error, project dir already exists, etc.) |

---

## Limitations

- **`_tasks`** are not executed automatically. Safe `mv`/`rm`/`mkdir -p` operations
  are applied automatically; remaining tasks are written to `.zenit-tasks.md`.
- **Content is presence-tracked only, not fully managed.**
- **Choice questions** (e.g. `database: [postgres, mysql, sqlite]`) become render
  variables. They do not produce addon stubs.
