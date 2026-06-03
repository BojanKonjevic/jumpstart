# zenit doctor

Verify that the project's current state matches what `.zenit.toml` records.

```
zenit doctor
```

Without `--fix`, `doctor` is read-only. It never modifies any file. It exits
with code `0` if everything is consistent, and code `1` if any check fails.

---

## What it checks

Checks run in the following order. All checks always run — `doctor` does not
stop at the first failure.

**1. Metadata**

- `.zenit.toml` is present and valid
- Template field is set
- All installed addons are known to the current zenit version
- Addon dependency requirements are satisfied
- Zenit version matches the current installation (warning on mismatch)

**2. Template health**

For native (zenit) templates, this check passes immediately.

For Copier-migrated projects (`template_source == "copier"`):

- **Error** if `template_has_tasks` is true — pending Copier `_tasks` were not
  executed. Check `.zenit-tasks.md` for the command list.
- **Warning** with the count of files tracked via `template_file_paths` — these
  files are presence-tracked but not under full lifecycle management.

**3. Manifest schema**

- Verifies `schema_version` matches the current version
- Detects orphan manifest blocks — entries whose addon is no longer in the
  lockfile's addon list

**4. Dependencies**

Loads the template and addon configurations, then checks every expected
dependency against the current `[project] dependencies` and
`[dependency-groups] dev` in `pyproject.toml`. Missing runtime dependencies
are errors; missing dev dependencies are warnings.

**5. Generated files**

Every file declared by the template and installed addons is checked for
existence on disk. A missing file is an error.

**6. Compose**

- Detects duplicate service definitions in `compose.yml`
- Checks every expected compose service (from template and addons) is present
  in `compose.yml`

**7. Env vars**

Every env var declared by the template and addons is checked against
`.env` and `.env.example`. A missing key is an error.

**8. Addon integrity**

Calls each installed addon's `health_check` hook if one is defined. Addon
authors use this to run custom validation (e.g. checking that a service
responds).

**9. Manifest env integrity**

Every key recorded in `[[manifest.env]]` is checked against `.env` and
`.env.example`. A missing key is an error.

**10. Manifest compose integrity**

Every service and volume recorded in the manifest is checked against
`compose.yml`. A missing entry is an error.

**11. Manifest dependency integrity**

Every dependency recorded in the manifest is checked against
`pyproject.toml`. A missing entry is an error.

**12. Manifest just-recipe integrity**

Every recipe name recorded in `[[manifest.just_recipes]]` is checked against
the `justfile`. A missing entry is an error.

**13. Python block line presence (fast)**

For every `[[manifest.python_blocks]]`, verifies that the recorded line range
does not exceed the file's current line count. This fast check runs first.

**14. Python block integrity (thorough)**

For every `[[manifest.python_blocks]]`, parses the target file, extracts the
recorded line range, and recomputes the fingerprint. Reports:

- **OK** if fingerprint matches exactly
- **Warning** if only the normalised fingerprint matches (file was
  reformatted)
- **Warning** if the block has drifted (found at different lines via the
  locator)
- **Error** if the block cannot be found by any strategy

**15. Unmanaged content (Copier-migrated projects only)**

Scans the manifest for entries still marked `source = "template"` with
`addon = ""` — env vars, dependencies, compose services, compose volumes, and
just recipes that the Copier template contributed but no zenit addon has
adopted. Suggests which native addon could take ownership.

Native projects report that no unmanaged content is expected.

---

## `--fix`

```
zenit doctor --fix
```

Re-syncs stale line numbers and fingerprints in the manifest from the current
file content. After editing files or running formatters, the line ranges
recorded in `.zenit.toml` may be outdated — `--fix` recalculates them without
changing any source file.

Use `--fix` after editing or reformatting a Zenit-managed file to keep the
manifest accurate for future `remove` operations.

---

## Exit codes

| Code | Meaning |
|---|---|
| `0` | All checks passed. Warnings do not affect the exit code. |
| `1` | One or more checks failed. |

---

## When to run it

**After pulling changes from collaborators.** If a teammate edited a file that
Zenit manages, `doctor` will surface the mismatch before it causes a problem
at `remove` time.

**Before running `zenit remove`.** Confirm that all injections are locatable
so removal proceeds cleanly. Use `--fix` if the project has been formatted
recently to re-sync fingerprints.

**After running a formatter.** Formatters can change whitespace inside injected
blocks enough to fail the exact fingerprint check. `doctor --fix` recalculates
the line ranges and fingerprints so `remove` will proceed cleanly.

**When something seems wrong.** If the app behaves unexpectedly after an `add`,
`doctor` gives you a complete picture of the project's managed state.

---

## Using `doctor` in CI

`doctor` exits with code `1` on any error, making it suitable as a CI gate.
Example GitHub Actions step:

```yaml
- name: Verify Zenit project integrity
  run: zenit doctor
```

Add this after your test step to catch cases where a generated file was
accidentally edited and committed with a stale or missing injection.
