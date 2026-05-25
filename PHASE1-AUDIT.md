# Phase 1 + Section 7 Code Audit

**Codebase:** Zenit (Python project scaffolder)
**Focus:** `zenit migrate` create-only pipeline, manifest/lockfile MIGRATED source support, doctor integration, add/remove safety.
**Standard:** Is the code shippable for Phase 1? Issues that would matter to a senior engineer using this in production.

---

## Dimensional Scores

| Dimension | Score | Justification |
|---|---|---|
| **Correctness & Robustness** | 7/10 | Solid core with two confirmed correctness bugs (compose volumes untracked, `_skip_if_exists` ignored) and several silent-failure paths that should produce errors. |
| **Performance & Efficiency** | 8/10 | No unnecessary I/O, lazy imports in doctor thorough path. Migration clones with `--depth=1`. Acceptable. |
| **Readability & Maintainability** | 7/10 | Well-structured modules, clear naming, good docstrings. Some private-API leaks across module boundaries, and the `_prompt_questions` / `_resolve_answers_noninteractive` split is fragile. |
| **Security & Privacy** | 9/10 | Path traversal validation, atomic writes, no eval/exec on user input. The `_remove_contribution_targets` task handler needs bounds validation (currently trusts Copier tasks). |
| **Architecture & Design** | 8/10 | Clean separation of concerns. The `record_addon_manifest_entries` → `upgrade_migrated_entry` pipeline is well-conceived. Delimiter translator is correctly isolated as dead code for Phase 1. |
| **Testability** | 6/10 | Good test coverage for manifest round-trips and migration end-to-end. **Critical gap**: `upgrade_migrated_entry` and `_check_migration_health` have zero tests. |
| **Adherence to Python Idioms** | 8/10 | Modern Python (3.12+), `match`/`case`, `StrEnum`, dataclasses. Some unnecessary private-import chaining. |

---

## Issues Ranked by Severity

### CRITICAL

#### C01 — Compose volumes from Copier templates are silently discarded

**File:** `src/zenit/migrate/migrate.py:843-857`

**Description:** `run_migration` calls `_inventory_compose()` which returns both services and volumes, but only services are recorded in the manifest. Volumes are fetched and then discarded.

```python
# Line 843-844 — both services and volumes are returned
compose_services, compose_volumes = _inventory_compose(project_dir)

# Lines 852-853 — only services are recorded
for svc in compose_services:
    add_compose_service(manifest, svc, source=EntrySource.MIGRATED, addon="")

# compose_volumes is NEVER used
```

**Why it matters:** After migration, `zenit doctor` will not know that compose volumes exist. If a Copier template defines named volumes (e.g., `redis-data`), they are invisible to zenit. Later `zenit add redis` may try to add a volume the manifest already should know about, or `zenit remove` on a migrated addon would leave orphaned volume entries in `compose.yml`.

**Fix:** Add the missing loop:

```python
for vol in compose_volumes:
    add_compose_volume(manifest, vol, source=EntrySource.MIGRATED, addon="")
```

Update `MigrationResult` to include `compose_volume_count` and track it through the pipeline. Add `compose_volume_count` to the migration report in `_print_migration_report`.

---

#### C02 — `upgrade_migrated_entry` has zero test coverage

**File:** `src/zenit/core/manifest.py:117-155` (implementation), `tests/core/test_manifest.py` (missing)

**Description:** The `upgrade_migrated_entry` function — a core safety mechanism that prevents duplicate MIGRATED entries when `zenit add` is run on a migrated project — has no tests at all. This is the function that gates the entire Phase 1 safety model.

**Why it matters:** This function runs silently on every `zenit add` in a migrated project. If it has a bug — wrong key attribute, wrong source comparison, missing entry types — users will silently get duplicate entries, or worse, MIGRATED entries will be overwritten instead of upgraded, breaking the ownership chain.

**Fix:** Add a comprehensive test class:

```python
class TestUpgradeMigratedEntry:
    def test_upgrades_env_entry(self) -> None:
        m = Manifest()
        m.env.append(EnvEntry(key="REDIS_URL", source=EntrySource.MIGRATED, addon=""))
        assert upgrade_migrated_entry(m, "REDIS_URL", "redis", "env")
        assert m.env[0].source == EntrySource.ADDON
        assert m.env[0].addon == "redis"

    def test_returns_false_when_not_migrated(self) -> None:
        m = Manifest()
        m.env.append(EnvEntry(key="REDIS_URL", source=EntrySource.ADDON, addon="redis"))
        assert not upgrade_migrated_entry(m, "REDIS_URL", "redis", "env")

    def test_returns_false_when_missing(self) -> None:
        assert not upgrade_migrated_entry(Manifest(), "NONEXISTENT", "redis", "env")

    def test_unknown_entry_type_returns_false(self) -> None:
        assert not upgrade_migrated_entry(Manifest(), "x", "redis", "unknown_type")

    def test_upgrades_compose_service(self) -> None:
        m = Manifest()
        m.compose_services.append(OwnedEntry(name="redis", source=EntrySource.MIGRATED, addon=""))
        assert upgrade_migrated_entry(m, "redis", "redis", "compose_service")
        assert m.compose_services[0].source == EntrySource.ADDON
        assert m.compose_services[0].addon == "redis"

    def test_upgrades_just_recipe(self) -> None:
        m = Manifest()
        m.just_recipes.append(OwnedEntry(name="redis-up", source=EntrySource.MIGRATED, addon=""))
        assert upgrade_migrated_entry(m, "redis-up", "redis", "just_recipe")
        assert m.just_recipes[0].source == EntrySource.ADDON
        assert m.just_recipes[0].addon == "redis"

    def test_upgrades_dependency(self) -> None:
        m = Manifest()
        m.dependencies.append(
            DependencyEntry(package="redis", spec="redis>=5", source=EntrySource.MIGRATED, addon="", dev=False)
        )
        assert upgrade_migrated_entry(m, "redis", "redis", "dependency")
        assert m.dependencies[0].source == EntrySource.ADDON
        assert m.dependencies[0].addon == "redis"
```

---

### HIGH

#### H01 — `_check_migration_health` has zero test coverage

**File:** `src/zenit/doctor/doctor.py:510-580` (implementation), `tests/doctor/test_doctor.py` (missing)

**Description:** The `_check_migration_health` function — which produces persistent warnings on every `zenit doctor` run for migrated projects — has no tests. This function drives the user's perception of project health. If it produces false positives (scaring users) or false negatives (making unhealthy projects look fine), user trust is damaged.

**Why it matters:** This check runs on every `zenit doctor` invocation for migrated projects. It's noisy by design. Bugs here are high-impact because they're visible every single time the user runs the command.

**Fix:** Add tests covering at least:
1. Non-migrated project → returns OK, no warnings
2. Migrated project with MIGRATED env entries → produces WARN per entry
3. Migrated project with MIGRATED compose services → produces WARN per service
4. Migrated project with MIGRATED dependencies → produces WARN per dependency
5. Migrated project with `has_tasks=True` → produces ERROR
6. Migrated project with no MIGRATED entries but `migrated is not None` → produces general migration warning

---

#### H02 — `remove_blocks_for_addon` lacks explicit MIGRATED guard on `python_blocks`

**File:** `src/zenit/core/manifest.py:165`

**Description:** The `remove_blocks_for_addon` function has explicit `e.source != EntrySource.MIGRATED` guards on all structured entry collections (env, compose, deps, recipes), but NOT on `python_blocks`:

```python
manifest.python_blocks = [b for b in manifest.python_blocks if b.addon != addon_id]
# vs.
manifest.env = [e for e in manifest.env if e.addon != addon_id and e.source != EntrySource.MIGRATED]
```

**Why it matters:** `ManifestBlock` doesn't have a `source` field (only `addon`). Currently, MIGRATED Python blocks would have `addon=""`, which means `b.addon != addon_id` is True for any non-empty `addon_id` — so they're safe by accident. But if anyone ever sets `addon="migrated"` on a Python block, it would be incorrectly removed. The design paper explicitly recommends making this invariant readable and structurally enforced.

**Fix:** `ManifestBlock` needs a `source` field, OR the filter needs to be made explicit with a comment explaining why it's safe (and a structural assertion that MIGRATED blocks have empty `addon`). Adding `source` to `ManifestBlock` would be the clean fix:

```python
@dataclass
class ManifestBlock:
    addon: str
    point: str
    file: str
    lines: str
    fingerprint: str
    fingerprint_normalised: str
    locator: LocatorSpec
    source: EntrySource = EntrySource.ADDON  # new
```

Then the guard becomes:
```python
manifest.python_blocks = [
    b for b in manifest.python_blocks
    if b.addon != addon_id and b.source != EntrySource.MIGRATED
]
```

This requires schema bump and TOML encode/decode changes for `ManifestBlock`.

---

#### H03 — `record_addon_manifest_entries` does not log upgrades

**File:** `src/zenit/core/manifest.py:246-294`

**Description:** The design paper explicitly states: "Log the upgrade to the command output: 'Transferred ownership of {key} from migrated to addon '{addon_id}'." The implementation silently returns `True`/`False` from `upgrade_migrated_entry` but never messages the user.

**Why it matters:** A user running `zenit add redis` on a migrated project will see the addon succeed but won't understand that existing Copier-written env vars just got transferred to zenit's ownership. Silent state changes erode trust — the user can't distinguish "nothing happened" from "something important happened."

**Fix:** Either:
a) Thread a logging callback through `record_addon_manifest_entries`, or
b) Return upgrade statistics from `_run_add_pipeline` and display them, or
c) Use `print()` / `warn()` directly in `upgrade_migrated_entry`.

Option (b) is cleanest:

```python
def record_addon_manifest_entries(
    manifest: Manifest,
    addon_cfg: AddonConfig,
    string_env: Environment,
    render_vars: dict[str, object],
) -> list[str]:  # returns list of upgraded key descriptions
    upgraded: list[str] = []
    for ev in addon_cfg.env_vars:
        if upgrade_migrated_entry(manifest, ev.key, addon_cfg.id, "env"):
            upgraded.append(f"env:{ev.key}")
        else:
            add_env_entry(...)
    return upgraded
```

Then in `add.py`:
```python
upgraded = record_addon_manifest_entries(...)
for u in upgraded:
    info(f"Transferred ownership of {u} to addon '{addon_id}'.")
```

---

#### H04 — `run_migration` does not handle `_skip_if_exists`

**File:** `src/zenit/migrate/migrate.py` (missing logic)

**Description:** The `copier.yml` `_skip_if_exists` field is parsed by `parse_copier_yml` and stored in `CopierConfig.skip_if_exists`, but it is never consulted during `_render_template()` or `run_migration()`. Files listed in `_skip_if_exists` are written unconditionally.

**Why it matters:** If a Copier template lists `pyproject.toml` in `_skip_if_exists`, the template expects to merge into an existing file. The current behavior unconditionally overwrites it. This is a documented limitation in the design paper, but the code should at minimum emit a warning listing the affected files.

**Fix:** In `_render_template()` or `run_migration()`, check `config.skip_if_exists` and emit a warning:

```python
if config.skip_if_exists:
    for pattern in config.skip_if_exists:
        warn(f"'_skip_if_exists' pattern '{pattern}' is not supported in migration. "
             f"Any matching files were written unconditionally.")
```

---

### MEDIUM

#### M01 — `translate_delimiters` is dead code

**File:** `src/zenit/migrate/copier.py:317-387`

**Description:** `translate_delimiters()` is a fully implemented, exported function that is never called from anywhere in the codebase. It's available as a public symbol but has no callers.

**Why it matters:** Dead code must be maintained but provides no value. It signals incomplete implementation to future readers. Either wire it in or gate it behind a feature flag with a clear docstring explaining Phase 3 intent.

**Fix:** Add a docstring:
```python
def translate_delimiters(content: str) -> str:
    """Translate Copier-style Jinja2 delimiters to zenit-style.
    
    NOTE: Currently unused in Phase 1. In Phase 3, this translates
    migrated template content so it can be re-rendered by zenit's
    Jinja2 environment (which uses (( )) / [% %] delimiters).
    """
```

---

#### M02 — `_prompt_questions` imports and uses `_COPIER_ENV` as private symbol

**File:** `src/zenit/migrate/migrate.py:53`

```python
from .copier import (
    _COPIER_ENV,  # private import
    ...
)
```

**Why it matters:** `_COPIER_ENV` is a private module-level variable in `copier.py`. Importing it into another module breaks encapsulation. A future refactor of `copier.py` might rename or remove it without considering external callers.

**Fix:** Export `COPIER_ENV` as a public constant from `copier.py`, or expose it via a getter function.

---

#### M03 — `_dep_package_name` imported as private across modules

**File:** `src/zenit/addons/remove.py:40`

```python
from zenit.core.manifest import (
    _dep_package_name,  # private import
    ...
)
```

Also used in `doctor.py:29`, `migrate.py:37`, `scaffold.py:27`.

**Why it matters:** Same encapsulation concern. `_dep_package_name` is used by 4 different modules outside `manifest.py`. It should be a public function.

**Fix:** Rename to `dep_package_name` (public) and update all usages.

---

#### M04 — `_check_manifest_schema` orphan detection relies on falsy `addon=""`

**File:** `src/zenit/doctor/doctor.py:160-167`

```python
def _orphan_addons_in(entries, attr="addon"):
    return {
        getattr(e, attr)
        for e in entries
        if getattr(e, attr) and getattr(e, attr) not in addon_ids
    }
```

**Why it matters:** MIGRATED entries with `addon=""` are excluded from orphan detection because `""` is falsy. This is correct behavior (migrated entries should not trigger orphan warnings), but it's implicit and fragile. If anyone changes the default addon value for MIGRATED entries, orphan detection silently breaks.

**Fix:** Make the filter explicit:

```python
def _orphan_addons_in(entries, attr="addon"):
    return {
        getattr(e, attr)
        for e in entries
        if getattr(e, attr) and getattr(e, attr) not in addon_ids
        and getattr(e, "source", EntrySource.ADDON) != EntrySource.MIGRATED
    }
```

---

#### M05 — `_remove_compose_services` and `_remove_compose_volumes` filter only by addon, not source

**File:** `src/zenit/addons/remove.py:355-360, 400-405`

```python
# _remove_compose_services
for entry in manifest.compose_services:
    if entry.addon != addon_id:
        continue
    if entry.name in services:
        del services[entry.name]
```

**Why it matters:** MIGRATED entries have `addon=""`, so they're safe by accident. But if a future change sets `addon` to something non-empty on migrated entries, compose entries from migrated projects would be removed by `zenit remove`. The design paper recommends making this explicit.

**Fix:** Add explicit MIGRATED filter:

```python
for entry in manifest.compose_services:
    if entry.addon != addon_id or entry.source == EntrySource.MIGRATED:
        continue
```

---

### LOW

#### L01 — `has_tasks` ERROR hint references `.zenit-tasks.md` but design paper says `_common/apply.py` stub

**File:** `src/zenit/doctor/doctor.py:565-567`

The hint says `"Check .zenit-tasks.md in the project root"`. The design paper section 8.1.10 says to write a `post_apply` stub to `templates/_common/apply.py`. The code uses `.zenit-tasks.md` (in `_write_task_stub`). Either is fine, but the hint and actual behavior should match. The doctor's hint is slightly misleading — pointing at a file the user may not have.

---

#### L02 — `_uses_copier_internal_path_vars` silently skips files

**File:** `src/zenit/migrate/migrate.py:818-820`

```python
for fc in file_contributions:
    if _uses_copier_internal_path_vars(fc.dest):
        continue  # silently skipped
```

**Why it matters:** Files using `_copier_conf.answers_file` are silently skipped. The migration report doesn't mention that some files were intentionally omitted. A user familiar with the Copier template might expect `_copier_answers.yml` and not see it.

**Fix:** Track skipped files and include them in the migration report, or at minimum emit a warning during processing.

---

#### L03 — `_migrated_overrides` in dry-run path duplicates the real-path logic

**File:** `src/zenit/addons/add.py:224-232` and `258-267`

The same `_migrated_overrides` check appears in both the dry-run path and the real path. This duplication should be unified (call once before branching).

---

#### L04 — `_fetch_source` during error when git not found, the error message could be more actionable

**File:** `src/zenit/migrate/migrate.py:168-173`

```python
raise ZenitError(
    "git is required to clone remote templates. "
    "Install git and try again, or use a local path."
)
```

The error message doesn't include the failed URL, making debugging harder when a user has multiple failed attempts.

---

### NIT

#### N01 — `_cleanup_temp` uses string-based `/tmp/` detection

**File:** `src/zenit/migrate/migrate.py:889-893`

```python
def _cleanup_temp(template_dir: Path) -> None:
    tmp_str = str(template_dir)
    if "/tmp/" in tmp_str or tmp_str.startswith("/var/tmp/"):
        shutil.rmtree(template_dir, ignore_errors=True)
```

This can false-positive on paths containing `/tmp/` as a substring (e.g., `/home/user/tmp/`). Use `tempfile.gettempdir()` for proper detection.

---

#### N02 — `classify_file` uses `fnmatch.fnmatch` on filename only, not full path

**File:** `src/zenit/migrate/copier.py:277`

```python
for pattern in config.exclude:
    if fnmatch.fnmatch(file_path.name, pattern):
        return FileJinjaClass.STATIC
```

Copier's `_exclude` patterns are matched against relative paths, not filenames. `fnmatch` on the name alone will miss patterns like `**/__pycache__/*` or `*.pyc` (though `*.pyc` would match). This is subtle and only matters for templates relying on path-based exclusion.

---

## What Is Done Particularly Well

1. **The `upgrade_migrated_entry` function and its wiring in `record_addon_manifest_entries`.** This is the core safety mechanism, and it's clean, well-typed, and correctly placed. The `match`/`case` dispatch is idiomatic, the boolean return value communicates the upgrade signal cleanly, and the callers in `record_addon_manifest_entries` handle the skip-or-add logic correctly.

2. **`remove_blocks_for_addon` explicit MIGRATED guards.** The guards on env, compose_services, compose_volumes, dependencies, and just_recipes are all present and consistent (H02 notwithstanding). This was a specific ask from the design paper and it was done correctly.

3. **`_check_migration_health` severity gradient.** WARN for unmanaged content, ERROR for pending tasks. This is the right level of urgency: users can ignore warnings and still work, but errors block `zenit doctor` from passing and create visible friction until resolved.

4. **The `scaffold_or_rollback` / `addon_or_rollback` context managers.** The snapshot-based rollback for `addon_or_rollback` is production-grade — `shutil.copytree` for O(1) backup/restore is much more robust than per-file rollback. The `_move_cwd_out_of_tree` handler prevents broken `os.getcwd` after directory removal, which is a subtle bug that shows real operational experience.

5. **The `atomic_write_text` implementation.** Temp-file + fsync + os.replace is the correct pattern for atomic file writes. No partial writes, no corruption on crash.

6. **Delimiter translator token-stream approach.** The `_process_token_stream` function correctly operates on Jinja2's token stream rather than regex, avoiding the three failure modes (literal braces, `{% raw %}`, `_jinja_extensions`) described in the design paper. That it's currently dead code doesn't diminish its correctness — it's ready to wire in for Phase 3.

7. **Inventory scanning functions.** `_inventory_env`, `_inventory_compose`, and `_inventory_deps` are correct, handle missing/corrupt files, and return typed results. They each mirror the corresponding zenit pipeline helper (e.g., `_merge_env_vars`, `merge_compose`), which gives consistency.

---

## Points Where Reasonable Senior Engineers Might Disagree

1. **Should `translate_delimiters` be wired in during Phase 1?** I say no — Phase 1 renders files at migration time using Copier's Jinja2, so the output has no delimiters at all. Wiring it in now would add complexity for no observable benefit. A reasonable engineer could argue the opposite: wire it in now, test it, and have it ready for Phase 3. The current approach (dead code with a docstring) is a compromise that I find acceptable but not ideal.

2. **Should `_skip_if_exists` be a Phase 1 blocker?** The design paper explicitly lists it as a "translates with loss" item. I agree — warning would be nice, but blocking Phase 1 on this would be disproportionate. A reasonable engineer shipping a v1 might disagree and want every documented Copier feature handled, even with a warning.

3. **Is the `_prompt_questions` direct-`input()` approach acceptable?** It works for the CLI use case and replicates existing zenit patterns (`add_addon` also uses direct `input()`). A more testable approach would inject an IO abstraction. Given that the project already uses `monkeypatch` for testing, I consider this acceptable. A strict TDD practitioner would disagree.

4. **Should `ManifestBlock` get a `source` field now (H02)?** This is a schema change that touches TOML encode/decode, all existing manifest files, and multiple test assertions. It's the right fix architecturally, but it's a non-trivial change. Adding it now vs. deferring to Phase 2 is a legitimate tradeoff. I lean toward doing it now since it only gets harder to change later.

5. **Is the missing compose volume tracking (C01) critical?** It's a correctness bug: data is fetched and discarded. But in practice, most Copier templates don't define named volumes, and the volumes section of `compose.yml` is not managed by zenit's manifest in any actionable way (there's no `add_volume` command). A pragmatic engineer could argue it's Medium, not Critical. I rate it Critical because the data contract (`_inventory_compose` returns volumes → caller uses them) is clearly violated.
