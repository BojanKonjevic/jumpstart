# The Manifest

`.zenit.toml` lives at the root of every Zenit-managed project. It is the complete record of everything Zenit has done: which template was used, which addons are installed, every file created (with a content hash), every code injection (with a fingerprint), and every dependency added.

`zenit add`, `zenit remove`, and `zenit doctor` all require this file. Without it, Zenit cannot manage the project. The project itself is unaffected — it runs identically with or without `.zenit.toml`.

**Commit it. Don't edit it manually.**

---

## Annotated example

A `fastapi` project with `docker` and `redis` installed:

```toml
[project]
template = "fastapi"
addons = ["docker", "redis"]
zenit_version = "1.0.8"
schema_version = 2

# One entry per injected Python block
[[manifest.python_blocks]]
addon = "redis"
point = "settings_fields"
file = "src/my_project/settings.py"
lines = "14-14"
fingerprint = "sha256:abc123..."
fingerprint_normalised = "sha256:def456..."

[manifest.python_blocks.locator]
name = "after_last_class_attribute"
args = {class_name = "Settings"}

[[manifest.env]]
key = "REDIS_URL"
source = "addon"
addon = "redis"

[[manifest.dependencies]]
package = "redis"
spec = "redis>=5"
source = "addon"
addon = "redis"
dev = false

[[manifest.just_recipes]]
name = "redis-up"
source = "addon"
addon = "redis"
```

---

## `[project]`

Written once at scaffold time and updated on every `add` or `remove`.

`template` — the template used to scaffold the project. Never changes after creation.

`addons` — currently installed addons in installation order.

`zenit_version` — the version of Zenit that last wrote this file.

`schema_version` — the manifest format version. Used for migrations if the schema changes.

---

## `[[manifest.python_blocks]]`

One entry per code block injected into a Python file. Contains everything needed to find the block again at removal time.

`addon` — the addon that produced this injection.

`point` — the named injection point, e.g. `settings_fields` or `lifespan_startup`.

`file` — path to the target file, relative to the project root.

`lines` — the line range where the block was written, e.g. `"14-14"`. Used as a hint for the fingerprint search; not relied upon as a hard position.

`fingerprint` — SHA-256 of the canonical libcst output of the injected block. Used for exact-match removal.

`fingerprint_normalised` — SHA-256 after normalising whitespace. Matches when the file has been formatted since injection.

`locator.name` and `locator.args` — the locator used to find the insertion point. Re-run at removal time against the current file, so removal works even if the block has moved.

### How fingerprints are used at removal

Zenit tries three strategies in order until one succeeds:

1. **Exact** — SHA-256 matches the recorded `fingerprint`. Clean removal.
2. **Normalised** — SHA-256 matches `fingerprint_normalised`. Used after a formatter run. Silent.
3. **Fuzzy** — SequenceMatcher similarity ≥ 85% within a 20-line window. Used when the block was lightly edited. Zenit warns and asks for confirmation.

If none succeed, Zenit prints the recorded block and instructs manual removal.

---

## `[[manifest.env]]`

One entry per environment variable added by an addon.

`key` — the variable name, e.g. `REDIS_URL`.

`source` — one of the `EntrySource` enum values: `"addon"` for addon-added entries, `"template"` for template-owned entries. See [EntrySource](./addons-and-templates.md#entrysource-enum).

`addon` — the addon that added this variable. Empty string for template-owned vars.

---

## `[[manifest.dependencies]]`

One entry per package added to `pyproject.toml`.

`package` — the package name, e.g. `redis`.

`spec` — the version specifier written to `pyproject.toml`, e.g. `redis>=5`.

`source` — one of the `EntrySource` enum values (`"template"` or `"addon"`).

`dev` — `true` if added to the dev dependency group, `false` for main dependencies.

---

## `[[manifest.compose_services]]` and `[[manifest.compose_volumes]]`

One entry per Docker Compose service or named volume added by an addon. Both have `name`, `source`, and `addon` fields. Used by `zenit doctor` to verify the service exists in `compose.yml`.

> [!NOTE]
> Compose entries are only recorded in the manifest when the `docker` addon is active. If `docker` is added later (via `zenit add docker`), the manifest is backfilled with compose entries from all installed addons that declare compose services.

---

## `[[manifest.just_recipes]]`

One entry per recipe appended to the `justfile`. Has `name`, `source` (one of the `EntrySource` enum values), and `addon`.

---

## What happens if `.zenit.toml` is deleted

The project continues to work. `main.py` still runs, tests still pass, `uv sync` still works. Zenit has no runtime presence.

What you lose is Zenit's ability to manage the project. `zenit add`, `zenit remove`, and `zenit doctor` all require `.zenit.toml` and will exit with an error. There is no `zenit init` that reconstructs the manifest from an existing project — doing so would require guessing what Zenit wrote versus what you wrote, which is exactly the ambiguity Zenit is designed to avoid.

---

## What happens if you edit a Zenit-managed file

`zenit doctor` will flag a content hash mismatch. This is not an error — it's expected that you edit generated files. It is information.

`zenit remove` will warn specifically before deleting any file whose hash no longer matches:

```
⚠ my_project/redis.py has been modified since Zenit created it.
  recorded: sha256:abc123...
  current:  sha256:def456...
  Delete anyway? [y/N]
```

It will never silently delete a file you have edited.
