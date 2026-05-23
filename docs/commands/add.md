# zenit add

Add one or more addons to an existing Zenit project.

```
zenit add <addon_name>
```

Must be run from a directory that contains `.zenit.toml`. Zenit walks up the directory tree to find it, so you can run the command from a subdirectory of the project root.

---

## What it does

In order:

1. Loads `.zenit.toml` and validates the project state.
2. Resolves addon dependencies — if a selected addon requires another that is not installed, it is added to the install list automatically.
3. Validates compatibility — checks each addon against the current template and against already-installed addons.
4. For each addon in install order: writes files, injects code, updates `pyproject.toml`, updates `compose.yml`, updates `.env.example`, updates `justfile`.
5. Updates `.zenit.toml` with all new manifest entries.

Step 5 is always last. If anything before it fails, the rollback restores all modified files to their previous state and `.zenit.toml` is left unchanged. The manifest always reflects the actual state of the project.

After a successful `add`, run `uv sync` to install the new packages.

---

## Arguments

| Argument | Description |
|---|---|
| `addon...` | One or more addon names to install. Optional — if omitted, an interactive picker is shown. |

---

## Options

| Flag | Description |
|---|---|
| `--dry-run` | Print all files that would be created, all injections that would be made, and all packages that would be added, without writing anything. |
| `--yes` | Skip the confirmation prompt shown when addon dependencies are auto-resolved. |

---

## Interactive mode

Running `zenit add` with no arguments opens the addon picker, pre-filtered to addons that are compatible with the current template and not already installed:

```
Addons (space to select, enter to confirm):
  ❯ ◯ redis
    ◯ celery
    ◯ sentry
    ◯ github-actions
    ◯ sqlalchemy
    ◯ postgres
    ◯ sqlmodel
```

**Multi-select:** Space toggles each addon; Enter confirms the selection.

**Type-to-search:** Start typing to filter the list by name. Matches are highlighted as you type.

**Unavailable addons** are shown greyed out with the reason (e.g. "requires: fastapi template" or "depends on: redis"). A tooltip explains why each unavailable addon cannot be selected.

Already-installed addons are not shown. Addons incompatible with the current template are not shown.

---

## Addon dependency resolution

If you select an addon that requires another addon that is not yet installed, Zenit resolves the dependency and installs both:

```
$ zenit add celery

celery requires redis, which is not installed.
The following addons will be installed: redis, celery
Continue? [Y/n]
```

Pass `--yes` to skip this prompt.

---

## Output

A successful `add` prints one line per action taken:

```
$ zenit add redis

  ✔ wrote     my_project/redis.py
  ✔ injected  my_project/settings.py  (settings_fields)
  ✔ injected  my_project/lifecycle.py  (lifespan_startup)
  ✔ injected  my_project/lifecycle.py  (lifespan_shutdown)
  ✔ added     redis>=5  →  pyproject.toml
  ✔ merged    redis service  →  compose.yml
  ✔ appended  REDIS_URL, REDIS_POOL_SIZE  →  .env.example
  ✔ appended  redis-up  →  justfile
  ✔ updated   .zenit.toml

Run `uv sync` to install new packages.
```

---

## Dry run

`--dry-run` shows exactly what would happen without writing anything:

```
$ zenit add redis --dry-run

  ~ write     my_project/redis.py
  ~ inject    my_project/settings.py  (settings_fields, line 14)
  ~ inject    my_project/lifecycle.py  (lifespan_startup, line 8)
  ~ inject    my_project/lifecycle.py  (lifespan_shutdown, line 22)
  ~ add       redis>=5  →  pyproject.toml
  ~ merge     redis service  →  compose.yml
  ~ append    REDIS_URL, REDIS_POOL_SIZE  →  .env.example
  ~ append    redis-up  →  justfile

Dry run — nothing was written.
```

---

## Rollback

If any step fails — a file write error, a failed injection validation, a malformed `pyproject.toml` — Zenit rolls back all changes made during that `add` invocation before reporting the error. The rollback operates at the file level: modified files are restored from backup, and newly created files are deleted:

```
  ✔ wrote     my_project/redis.py
  ✔ injected  my_project/settings.py  (settings_fields)
  ✗ injection failed: my_project/lifecycle.py — result is not valid Python

Rolling back...
  ✔ restored  my_project/redis.py  →  deleted
  ✔ restored  my_project/settings.py  →  original content restored

Error: add failed. No changes were made to the project.
```

The rollback is complete — no partial state is left behind. Every file touched during the operation is either reverted to its original content (if it existed before) or deleted (if it was created).

---

## Error conditions

| Situation | Behaviour |
|---|---|
| Not in a Zenit project (no `.zenit.toml` found) | Exits with an error identifying the nearest parent directory checked. |
| Addon already installed | Exits with an error. Use `zenit doctor` to verify current state. |
| Addon incompatible with current template | Exits with an error naming the addon, the required template, and the current template. |
| Unknown addon name | Exits with an error and lists available addons. |
| File to be created already exists | Exits with an error naming the conflicting file. Nothing is written. |
| Injection produces invalid Python | Rolls back all changes. Reports the target file and the proposed output. |
| `uv` not found | Packages are added to `pyproject.toml` but `uv sync` cannot be run. Zenit prints a warning and exits cleanly — the manifest is still updated. |

---

## Examples

Add a single addon interactively:

```bash
zenit add
```

Add a specific addon directly:

```bash
zenit add redis
```

Add multiple addons in one invocation:

```bash
zenit add redis sentry
```

Preview what would change:

```bash
zenit add celery --dry-run
```

Add with auto-resolved dependencies, skipping confirmation:

```bash
zenit add celery --yes
```
