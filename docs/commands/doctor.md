# zenit doctor

Verify that the project's current state matches what `.zenit.toml` records.

```
zenit doctor
```

`doctor` is read-only. It never modifies any file. It exits with code `0` if everything is consistent, and code `1` if any check fails.

---

## What it checks

Checks run in the following order. All checks always run — `doctor` does not stop at the first failure.

**1. Manifest files exist**

Every file listed in the manifest is checked for existence on disk. A missing file is an error.

**2. File content hashes match**

For each file in the manifest, the current content hash is compared against the recorded hash. A mismatch means the file has been modified since Zenit created it. This is reported as a warning, not an error — modifying generated files is expected and supported. It becomes relevant when you later run `zenit remove`, which will ask for confirmation before deleting a modified file.

**3. Injection markers are present and match**

For each injection in the manifest, the fingerprint pipeline is run against the current file. If the exact or normalised fingerprint matches, the check passes. If only the fuzzy match succeeds, it is reported as a warning. If none of the three strategies find the block, it is reported as an error.

**4. Dependencies are present in `pyproject.toml`**

Every package recorded in the manifest is checked against the current `[project.dependencies]` and `[project.optional-dependencies.dev]` sections. A missing package is an error.

**5. Compose services are present**

Only runs when the `docker` addon is installed. If any installed addon (or the template) declares compose services, `compose.yml` is checked for each service name. A missing service is an error. If docker is not installed or no addon has compose services, this check is skipped.

**6. Env vars are defined**

Every env var recorded in the manifest is checked against `.env.example`. A missing key is a warning — you may have intentionally removed it from `.env.example` after deciding not to use it.

---

## Output format

Each check prints one line. Passed checks use `✔`, warnings use `⚠`, errors use `✗`:

```
$ zenit doctor

  ✔ my_project/redis.py  exists
  ⚠ my_project/redis.py  content hash mismatch (file has been modified)
  ✔ my_project/settings.py  injection: settings_fields
  ✔ my_project/lifecycle.py  injection: lifespan_startup
  ✔ my_project/lifecycle.py  injection: lifespan_shutdown
  ✔ redis>=5  in pyproject.toml
  ✔ redis service  in compose.yml
  ✔ REDIS_URL  in .env.example
  ⚠ REDIS_POOL_SIZE  missing from .env.example

2 warnings, 0 errors.
```

When errors are present:

```
$ zenit doctor

  ✔ my_project/redis.py  exists
  ✔ my_project/redis.py  content hash matches
  ✗ my_project/lifecycle.py  injection: lifespan_startup — block not found
  ✔ redis>=5  in pyproject.toml
  ✔ redis service  in compose.yml
  ✔ REDIS_URL  in .env.example
  ✔ REDIS_POOL_SIZE  in .env.example

0 warnings, 1 error.
```

---

## `--thorough`

```
zenit doctor --thorough
```

Adds a full fingerprint integrity pass for every Python injection recorded in the manifest. In a standard `doctor` run, the fingerprint check stops as soon as one strategy succeeds (exact → normalised → fuzzy). With `--thorough`, all three strategies are always evaluated and their results are reported individually:

```
  ✔ my_project/lifecycle.py  injection: lifespan_startup
      exact fingerprint:       ✔ match
      normalised fingerprint:  — (not checked, exact matched)
      fuzzy match:             — (not checked, exact matched)

  ⚠ my_project/settings.py  injection: settings_fields
      exact fingerprint:       ✗ mismatch
      normalised fingerprint:  ✔ match (file was reformatted)
      fuzzy match:             — (not checked, normalised matched)
```

Use `--thorough` after running a formatter over the project, or when preparing to run `zenit remove` and you want confidence about what will be found.

---

## Exit codes

| Code | Meaning |
|---|---|
| `0` | All checks passed. Warnings do not affect the exit code. |
| `1` | One or more checks failed. |

---

## When to run it

**After pulling changes from collaborators.** If a teammate edited a file that Zenit manages, `doctor` will surface the mismatch before it causes a problem at `remove` time.

**Before running `zenit remove`.** Confirm that all injections are locatable so removal proceeds cleanly. Use `--thorough` if the project has been formatted recently.

**After running a formatter.** Formatters can change whitespace inside injected blocks enough to fail the exact fingerprint check. `doctor --thorough` tells you whether the normalised fingerprint still matches, and therefore whether `remove` will be silent or will warn.

**When something seems wrong.** If the app behaves unexpectedly after an `add`, `doctor` gives you a complete picture of the project's managed state.

---

## Using `doctor` in CI

`doctor` exits with code `1` on any error, making it suitable as a CI gate. Example GitHub Actions step:

```yaml
name: Verify Zenit project integrity
run: zenit doctor
```

Add this after your test step to catch cases where a generated file was accidentally edited and committed with a stale or missing injection.
