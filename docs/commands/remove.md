# zenit remove

Remove one or more addons from an existing Zenit project.

```
zenit remove <addon_name>
```

Must be run from a directory that contains `.zenit.toml`. Zenit walks up the directory tree to find it, so you can run the command from a subdirectory of the project root.

---

## What it does

In order:

1. Loads `.zenit.toml` and validates that each named addon is currently installed.
2. Checks for dependents — if another installed addon requires the one being removed, Zenit exits with an error before making any changes.
3. Shows a confirmation prompt listing everything that will be removed.
4. For each addon in reverse installation order: removes justfile recipes, removes env vars from `.env.example`, removes compose services from `compose.yml`, removes dependencies from `pyproject.toml`, excises injected code blocks, deletes created files.
5. Updates `.zenit.toml` — removes the addon from `[project].addons` and deletes all its manifest entries.

Step 5 is always last. If anything before it fails, all modified files are restored to their state before the command ran.

After a successful `remove`, run `uv sync` to uninstall the removed packages.

---

## Arguments

| Argument | Description |
|---|---|---|
| `addon...` | One or more addon names to remove. Optional — omit to open the interactive picker. |

---

## Options

| Flag | Description |
|---|---|
| `--dry-run` | Print everything that would be removed without writing anything. |
| `--yes` | Skip the confirmation prompt. |

---

## Interactive mode

Running `zenit remove` with no arguments opens the addon picker, pre-filtered to addons currently installed in the project:

```
Addons (space to select, enter to confirm):
  ❯ ◯ redis
    ◯ celery
```

**Multi-select:** Space toggles each addon; Enter confirms the selection.

**Type-to-search:** Start typing to filter the list by name. Matches are highlighted as you type.

**Unavailable addons** (e.g. addons that cannot be removed because another addon depends on them) are shown greyed out with the reason.

---

## Confirmation prompt

Before making any changes, Zenit prints the full list of what will be removed and asks for confirmation:

```
$ zenit remove redis

The following will be removed:

  Files
    my_project/redis.py

  Code injections
    my_project/settings.py  (settings_fields, lines 14–14)
    my_project/lifecycle.py  (lifespan_startup, lines 8–10)
    my_project/lifecycle.py  (lifespan_shutdown, lines 22–23)

  Dependencies
    redis>=5

  Compose services
    redis

  Env vars
    REDIS_URL
    REDIS_POOL_SIZE

  Justfile recipes
    redis-up

Continue? [y/N]
```

The default is **N**. Pass `--yes` to skip this prompt in scripts.

---

## Handling modified files

If a file Zenit created has been modified since it was written, `remove` warns before deleting it:

```
  ⚠ my_project/redis.py has been modified since it was created by Zenit.
    recorded: sha256:abc123...
    current:  sha256:def456...
    Delete anyway? [y/N]
```

The prompt is per-file. You can keep a modified file and still remove the rest of the addon — Zenit will skip deletion of that file but will still remove injections, dependencies, env vars, compose services, and justfile recipes associated with the addon.

---

## Handling modified injection blocks

If an injected code block has been edited since it was written, `remove` warns before excising it:

```
  ⚠ Injection in my_project/lifecycle.py (lifespan_startup) has been modified.
    The block will be located by fuzzy match and removed.
    Review the result carefully.
    Continue? [y/N]
```

If the fuzzy match fails entirely — the block has been changed enough that Zenit cannot locate it with confidence — removal exits with an error and manual recovery instructions:

```
  ✗ Could not locate injection in my_project/lifecycle.py (lifespan_startup).

  The following block was recorded at lines 8–10:

    redis_pool = await create_redis_pool(settings.redis_url)

  Remove it manually, then run `zenit doctor` to verify the project state.
```

---

## What "clean" means

After a successful `remove`, the project must be in the exact state it was in before `zenit add` was called for that addon. Zenit verifies this by running the equivalent of `zenit doctor` for the removed addon's entries immediately after removal. If any discrepancy is found, it is reported — Zenit does not silently leave partial state.

Concretely:
- No files created by the addon remain on disk.
- No injected lines remain in any target file.
- No packages added by the addon remain in `pyproject.toml`.
- No compose services added by the addon remain in `compose.yml`.
- No env vars added by the addon remain in `.env.example`.
- No recipes added by the addon remain in the `justfile`.
- No manifest entries for the addon remain in `.zenit.toml`.

---

## Dependency removal and `uv sync`

Zenit removes packages from `pyproject.toml` but does not run `uv sync` automatically. This is intentional — running `uv sync` modifies the active virtual environment, which may affect a running dev server or test process. You control when the environment changes.

After removing an addon:

```bash
uv sync
```

---

## Removing the last addon

Removing all addons leaves the project in the state of the bare template. `.zenit.toml` still exists and still records the template. The project is still Zenit-managed — you can run `zenit add` again at any time.

---

## Error conditions

| Situation | Behaviour |
|---|---|
| Not in a Zenit project (no `.zenit.toml` found) | Exits with an error. |
| Addon not installed | Exits with an error. Use `zenit list --installed` to see what is installed. |
| Another installed addon depends on the one being removed | Exits with an error naming the dependent addon. Remove the dependent first, or remove both in the same invocation. |
| Injection cannot be located (all three fingerprint strategies fail) | Exits with an error and manual recovery instructions. The rest of the removal is not attempted. |
| File deletion fails (permissions, etc.) | Rolls back all changes and reports the error. |

---

## Examples

Remove a single addon:

```bash
zenit remove redis
```

Remove multiple addons in one invocation:

```bash
zenit remove redis celery
```

Preview what would be removed:

```bash
zenit remove redis --dry-run
```

Remove without the confirmation prompt:

```bash
zenit remove sentry --yes
```
