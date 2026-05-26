# Addons & Templates

Reference for the `AddonConfig` and `TemplateConfig` APIs. For step-by-step walkthroughs, see [Writing an addon](../addons/writing-addons.md) and [Writing a template](../templates/writing-templates.md).

> **Note:** Addons and templates must live inside the Zenit repository. There is no plugin system for external addons or templates.

---

## Directory layout

```
src/zenit/
├── templates/
│   ├── _common/          # copied to every project regardless of template
│   ├── blank/
│   │   ├── template.py   # TemplateConfig instance
│   │   └── files/        # Jinja2 templates and static files
│   └── fastapi/
│       ├── template.py
│       └── files/
└── addons/
    ├── _registry.py      # auto-discovers addon.py files
    ├── redis/
    │   ├── addon.py      # AddonConfig instance + optional hooks
    │   └── files/        # files this addon writes
    └── your-addon/
        ├── addon.py
        └── files/
```

Addons are discovered automatically — no registration step. Templates require one additional manual step; see [Writing a template](../templates/writing-templates.md).

---

## How addons are discovered

`_registry.py` scans `addons/` for subdirectories, imports `addon.py` from each one, reads the `config` attribute, and attaches any optional hook functions (`can_apply`, `can_remove`, `health_check`, `post_apply`).

---

## `AddonConfig` reference

```python
@dataclass
class AddonConfig:
    id: str                              # CLI name: "zenit add <id>"
    description: str                     # one sentence, shown in zenit list
    requires: list[str]                  # addon dependencies, e.g. ["redis"]
    conflicts_with: list[str]            # mutually exclusive addons
    templates: list[str]                 # allowed templates; empty = all
    dirs: list[str]                      # directories to create
    files: list[FileContribution]        # files to write
    compose_services: list[ComposeService]
    compose_volumes: list[str]           # named volume names
    env_vars: list[EnvVar]
    deps: list[str]                      # runtime deps, e.g. ["redis>=5"]
    dev_deps: list[str]
    just_recipes: list[str]
    injections: list[Injection]
    tool_overrides: dict[str, list[dict[str, object]]]  # tool config overrides
    _module: AddonHooks | None           # populated by registry; not set manually
```

### `FileContribution`

```python
@dataclass
class FileContribution:
    dest: str           # path relative to project root; {{pkg_name}} is expanded
    source: str | None  # path to a source file (static copy or Jinja2 template)
    content: str | None # inline content (use for empty __init__.py stubs)
    template: bool      # True = render source as Jinja2; False = copy verbatim
```

Provide either `source` or `content`, not both. For an empty `__init__.py`:

```python
FileContribution(dest="src/{{pkg_name}}/mymodule/__init__.py", content="")
```

For a Jinja2 template:

```python
FileContribution(
    dest="src/{{pkg_name}}/integrations/redis.py",
    source=str(_HERE / "files" / "redis.py.j2"),
    template=True,
)
```

For a static file copied verbatim:

```python
FileContribution(
    dest=".dockerignore",
    source=str(_HERE / "files" / ".dockerignore"),
)
```

### `Injection`

```python
@dataclass
class Injection:
    point: str          # named injection point declared by the template
    content: str        # the code to inject (a string, including indentation)
    addon_id: str       # set automatically by the pipeline; leave as default ""
    templates: list[str]  # restrict to these templates; empty = all
```

The `point` must be one of the injection points declared by the target template. The `content` string is inserted verbatim — include the correct indentation for the target scope.

The `templates` field restricts which templates this injection applies to. When empty (the default), the injection applies to all compatible templates. Set it to `["fastapi"]` to limit the injection to fastapi projects only.

See [Code Injection](./injection.md) for the full locator reference and cookbook.

### `ComposeService`

```python
@dataclass
class ComposeService:
    name: str
    image: str | None
    build: str | None
    ports: list[str]
    volumes: list[str]
    environment: dict[str, str]
    env_file: list[str]
    command: str | None
    depends_on: list[str] | dict[str, dict[str, str]]
    develop_watch: list[dict[str, object]]
    healthcheck: dict[str, object] | None
```

### `tool_overrides`

Tool-specific configuration overrides that get merged into the project's `pyproject.toml`. The key is the tool name (e.g. `"mypy"`) and the value is a list of configuration table entries:

```python
tool_overrides = {
    "mypy": [
        {"module": ["jose.*"], "ignore_missing_imports": True, "ignore_errors": True},
    ],
}
```

This generates the following in `pyproject.toml`:

```toml
[[tool.mypy.overrides]]
module = ["jose.*"]
ignore_missing_imports = true
ignore_errors = true
```

Used when an addon introduces a dependency whose type stubs are incomplete or missing, preventing mypy errors from leaking into the user's project without requiring manual configuration.

---

### `EnvVar`

```python
@dataclass
class EnvVar:
    key: str      # e.g. "REDIS_URL"
    default: str  # e.g. "redis://localhost:6379/0"
    comment: str  # optional inline comment in .env.example
```

### `AddonHooks`

```python
@dataclass
class AddonHooks:
    post_apply:   Callable[[Context, FileSystem], None] | None
    health_check: Callable[[Path, ZenitLockfile], list[HealthIssue]] | None
    can_apply:    Callable[[Path, ZenitLockfile], str | None] | None
    can_remove:   Callable[[Path, ZenitLockfile], str | None] | None
```

Optional module-level functions in `addon.py`. The registry attaches them automatically.

---

## `EntrySource` enum

Every manifest entry records its origin. The `source` field is always one of:

```python
class EntrySource(StrEnum):
    TEMPLATE = "template"
    ADDON = "addon"
```

Used by `[[manifest.env]]`, `[[manifest.dependencies]]`, `[[manifest.compose_services]]`, `[[manifest.just_recipes]]`, and all other manifest entries to track ownership. The `zenit doctor` command uses this to attribute each check to the correct addon or template.

---

## `FileSystem` protocol

The pipeline writes files through a `FileSystem` abstraction, enabling dry-run previews without touching disk:

```python
class FileSystem(Protocol):
    def write_file(self, path: str, content: str) -> None: ...
    def create_dir(self, path: str) -> None: ...
    def copy_file(self, src: Path, dest_relative: str) -> None: ...
    def append_to_file(self, path: str, content: str) -> None: ...
    def record_modification(self, path: str, description: str) -> None: ...
    def execute_command(self, cmd: list[str], check: bool = True) -> None: ...
```

Two implementations:

| Implementation | Behaviour |
|---|---|
| `RealFileSystem` | Performs real I/O — writes files, creates directories, runs commands. Used during actual scaffold/add/remove operations. |
| `RecordingFileSystem` | Records every operation in a list without touching disk. Used for `--dry-run` previews. `execute_command` is a no-op. |

---

## `RecipeCollection`

Recipes from templates and addons are kept separate to give template recipes priority during deduplication:

```python
@dataclass
class RecipeCollection:
    template: list[str]    # template recipes, always kept
    addon: list[str]       # addon recipes, deduplicated against template

    def resolve(self) -> list[str]:
        """Return deduplicated list: template first, then unique addon recipes."""
```

An addon recipe is silently dropped if its name matches a template recipe.

---

## `Contributions`

Merged contributions from the template and all selected addons, used by the pipeline to apply everything in order:

```python
@dataclass
class Contributions:
    files: list[FileContribution]
    dirs: list[str]
    compose_services: list[ComposeService]
    compose_volumes: list[str]
    env_vars: list[EnvVar]
    deps: list[str]
    dev_deps: list[str]
    template_dev_deps: list[str]   # dev deps from the template
    recipes: RecipeCollection
    injections: list[Injection]
    tool_overrides: dict[str, list[dict[str, object]]]
```

The `template_dev_deps` field holds dev dependencies declared by the template, kept separate from addon dev deps for clean removal.

`tool_overrides` collects tool configuration overrides from all active addons, keyed by tool name (e.g. `"mypy"`). The pipeline merges these into `pyproject.toml`'s `[tool.*]` sections during scaffold and add operations, and removes them on remove.

---

## Jinja2 template variables

Files rendered with `template=True` have access to these variables:

| Variable | Type | Example |
|---|---|---|---|
| `pkg_name` | `str` | `"my_project"` |
| `name` | `str` | `"my-project"` |
| `template` | `str` | `"fastapi"` or `"blank"` |
| `addons` | `list[str]` | `["docker", "redis"]` |
| `has_redis` | `bool` | `True` if `redis` addon is in the project |
| `has_docker` | `bool` | `True` if `docker` addon is in the project |

Zenit uses non-standard Jinja2 delimiters to avoid conflicts with Python source and YAML:

```
(( pkg_name ))     →  variable substitution  (instead of {{ }})
[% if has_redis %] →  control flow           (instead of {% %})
[% endif %]
```

`dest` paths in `FileContribution` support `{{pkg_name}}` expansion (double braces — resolved before Jinja2 rendering).

---

## Injection points

Injection points are named locations in template files where addons can insert code. Declared by each template's `TemplateConfig`, backed by a specific locator.

### `fastapi` template injection points

| Point | Target file | Locator | What goes here |
|---|---|---|---|---|
| `settings_fields` | `settings.py` | `after_last_class_attribute` on `Settings` | Pydantic settings fields |
| `lifespan_imports` | `lifecycle.py` | `after_last_import` | Imports needed by lifespan hooks |
| `lifespan_startup` | `lifecycle.py` | `before_yield_in_function` on `lifespan` | Startup hooks |
| `lifespan_shutdown` | `lifecycle.py` | `in_function_body` after `yield` in `lifespan` | Shutdown hooks |
| `router_imports` | `api/router.py` | `after_last_import` | Import statements for addon routers |
| `router_includes` | `api/router.py` | `after_statement_matching` on `include_router` | `include_router(...)` calls |
| `test_imports` | `tests/conftest.py` | `after_last_import` | Test fixture imports |
| `test_fixtures` | `tests/conftest.py` | `at_module_end` | Additional pytest fixtures |
| `exceptions` | `exceptions.py` | `at_module_end` | Custom exception classes |
| `env_vars` | `.env` | `at_file_end` | Environment variable definitions |

### `blank` template injection points

| Point | Target file | Locator | What goes here |
|---|---|---|---|---|
| `settings_fields` | `settings.py` | `after_last_class_attribute` on `Settings` | Pydantic settings fields |
| `main_startup` | `main.py` | `before_return_in_function` on `main` | Startup calls |
| `env_vars` | `.env` | `at_file_end` | Environment variable definitions |

---

## Optional hook functions

### `can_apply(project_dir, lockfile) -> str | None`

Called before the addon pipeline runs. Return `None` to allow installation, or a descriptive error string to abort.

```python
def can_apply(project_dir: Path, lockfile: ZenitLockfile) -> str | None:
    target = project_dir / "src" / project_dir.name.replace("-", "_") / "my_file.py"
    if target.exists():
        return (
            f"{target.relative_to(project_dir)} already exists.\n"
            f"    Remove it first: rm {target.relative_to(project_dir)}"
        )
    return None
```

### `can_remove(project_dir, lockfile) -> str | None`

Called before removal. Return `None` to allow it, or an error string to abort.

```python
def can_remove(project_dir: Path, lockfile: ZenitLockfile) -> str | None:
    if "celery" in lockfile.addons:
        return "Remove 'celery' first — it depends on this addon."
    return None
```

### `health_check(project_dir, lockfile) -> list[HealthIssue]`

Called by `zenit doctor`. Return a list of `HealthIssue` objects.

```python
def health_check(project_dir: Path, lockfile: ZenitLockfile) -> list[HealthIssue]:
    issues: list[HealthIssue] = []
    env_path = project_dir / ".env"
    if env_path.exists() and "MY_KEY=" not in env_path.read_text():
        issues.append(HealthIssue(
            Severity.WARN,
            "MY_KEY is not set in .env",
            hint="Add MY_KEY=<value> to .env.",
        ))
    return issues
```

### `post_apply(ctx, fs) -> None`

Called after the addon pipeline completes successfully. Receives the rendering `Context` and a `FileSystem` instance for any additional file operations. Use for post-install steps that can't be expressed declaratively.

---

## `TemplateConfig` reference

```python
@dataclass
class TemplateConfig:
    id: str
    description: str
    requires_addons: list[str]                   # addons forced at scaffold time
    injection_points: dict[str, InjectionPoint]  # name → InjectionPoint
    dirs: list[str]
    files: list[FileContribution]
    compose_services: list[ComposeService]
    compose_volumes: list[str]
    env_vars: list[EnvVar]
    deps: list[str]
    dev_deps: list[str]
    just_recipes: list[str]
    injections: list[Injection]
```

### `InjectionPoint`

```python
@dataclass
class InjectionPoint:
    file: str        # relative to project root; {{pkg_name}} is expanded
    locator: LocatorSpec

@dataclass
class LocatorSpec:
    name: str        # name of the locator function
    args: dict       # kwargs forwarded to the locator
```

### Example

```python
config = TemplateConfig(
    id="blank",
    injection_points={
        "main_startup": InjectionPoint(
            file="src/{{pkg_name}}/main.py",
            locator=LocatorSpec(
                name="before_return_in_function",
                args={"function": "main"},
            ),
        ),
    },
    files=[...],
    deps=[...],
)
```

---

## What makes a good addon

**Minimal wiring, maximal files.** Injections should only wire a new module into the existing structure. The substance goes in files, not in injection content.

**Declare conflicts eagerly in `can_apply`.** The user gets a clear error before anything is written.

**Write a `health_check`.** It makes `zenit doctor` useful and documents what the addon expects.

**Test with `--dry-run` first.** `zenit add <id> --dry-run` on a fresh project shows exactly what would happen.
