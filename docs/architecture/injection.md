# Code Injection

Some addons need to modify files that already exist — files the template created that may already contain your code. The `redis` addon adds a settings field. The `auth-manual` addon registers its router. The `sentry` addon calls `init_sentry()` in the lifespan.

Naively appending or using sentinel comments breaks the moment the file is formatted, refactored, or edited. Zenit parses the target file into a concrete syntax tree, locates the insertion point structurally, splices in the code, and validates the result is still valid Python before writing anything.

---

## Why libcst

**Regex is positional.** It finds text at a known location. If the file is reformatted, the location changes. If the user adds an import above the target, everything shifts. Regex requires the file to be in a stable, known state — which source files never are.

**libcst is structural.** It understands "the body of function `lifespan`" or "after the last attribute in class `Settings`". The location doesn't change when the file is formatted, because the locator doesn't care about line numbers — it navigates the syntax tree.

---

## The injection pipeline

When `zenit add` applies an injection, the pipeline runs in this order:

1. Parse the target file into a libcst module.
2. Call the named locator to get an integer insertion index.
3. Splice the content at that index.
4. Parse the result to validate it's still valid Python. If not, abort — the file is not written.
5. Write the file and record a fingerprint of the injected block in `.zenit.toml`.

Steps 4 and 5 are atomic — either both happen or neither does.

---

## Handlers

Different file types use different strategies:

| Handler | File types | Strategy |
|---|---|---|
| `PythonHandler` | `*.py` | libcst structural injection |
| `TomlHandler` | `*.toml` | tomlkit append; skips if top-level key already exists |
| `YamlHandler` | `*.yml`, `*.yaml` | append block; skips if first content key is already present |
| `JustfileHandler` | `justfile` | append recipe; skips if recipe name already exists |
| `EnvHandler` | `.env*` | append `key=value`; skips keys already defined |

All handlers are idempotent: safe to call twice, they never overwrite existing content without confirmation, and they record what they wrote in the manifest.

---

## Locators

Locators are pure functions that take a parsed libcst module and keyword arguments, and return an integer body index at which to insert new code. All locators raise `LocatorError` with an actionable message on failure.

### Available locators

**`after_last_class_attribute`** — inserts after the last field in a class.

```python
# args: {class_name: "Settings"}
# Use for: adding settings fields, model fields
locator=LocatorSpec(
    name="after_last_class_attribute",
    args={"class_name": "Settings"},
)
```

```python
class Settings(BaseSettings):
    database_url: str = "..."
    redis_url: str = "..."     # ← injected here
```

---

**`before_yield_in_function`** — inserts before the `yield` in an async generator (lifespan startup).

```python
# args: {function: "lifespan"}
# Use for: startup hooks — code runs before the app starts serving
locator=LocatorSpec(
    name="before_yield_in_function",
    args={"function": "lifespan"},
)
```

```python
async def lifespan(app: FastAPI) -> AsyncGenerator[None]:
    redis_pool = await create_redis_pool(...)  # ← injected here
    yield
    await redis_pool.aclose()
```

---

**`in_function_body`** — inserts before or after a specific statement inside a function.

```python
# args: {function: "lifespan", anchor_pattern: "yield", position: "after"}
# Use for: shutdown hooks — position="after" means after the yield
locator=LocatorSpec(
    name="in_function_body",
    args={"function": "lifespan", "anchor_pattern": "yield", "position": "after"},
)
```

```python
async def lifespan(app: FastAPI) -> AsyncGenerator[None]:
    yield
    await redis_pool.aclose()  # ← injected here
```

---

**`after_statement_matching`** — inserts after the first top-level statement matching a regex.

```python
# args: {pattern: "api_router = APIRouter()"}
# Use for: inserting router includes after the router is instantiated
locator=LocatorSpec(
    name="after_statement_matching",
    args={"pattern": r"router\.include_router\("},
)
```

---

**`before_return_in_function`** — inserts before the first `return` in a named function.

```python
# args: {function: "main"}
# Use for: blank template startup — main() returns instead of yielding
locator=LocatorSpec(
    name="before_return_in_function",
    args={"function": "main"},
)
```

---

**`after_last_import`** — inserts after the last import statement at module level.

```python
locator=LocatorSpec(name="after_last_import", args={})
```

---

**`at_module_end`** — appends at the end of the module body.

```python
locator=LocatorSpec(name="at_module_end", args={})
```

---

### Choosing a locator

| What you want to inject | Locator | Args |
|---|---|---|
| A field into a settings or model class | `after_last_class_attribute` | `{class_name: "ClassName"}` |
| Startup code (before app serves) | `before_yield_in_function` | `{function: "lifespan"}` |
| Shutdown code (after yield) | `in_function_body` | `{function: "lifespan", anchor_pattern: "yield", position: "after"}` |
| An import statement | `after_last_import` | _(none)_ |
| A router `include_router(...)` call | `after_statement_matching` | `{pattern: r"include_router\("}` |
| A top-level definition or class | `at_module_end` | _(none)_ |
| Code inside `main()` (blank template) | `before_return_in_function` | `{function: "main"}` |
| Code before/after an anchor in any function | `in_function_body` | `{function: "...", anchor_pattern: "...", position: "before"\|"after"}` |

---

### Locator cookbook

Real patterns from the built-in addons, showing the full `Injection` + `InjectionPoint` pair:

#### Inject a settings field (redis addon)

```python
# In addon.py:
Injection(
    point="settings_fields",
    content='    redis_url: str = "redis://localhost:6379/0"',
)

# In template.py:
"settings_fields": InjectionPoint(
    file="src/{{pkg_name}}/settings.py",
    locator=LocatorSpec(
        name="after_last_class_attribute",
        args={"class_name": "Settings"},
    ),
),
```

#### Register a router (auth-manual addon)

```python
# Two injections: the import, then the include_router call.
Injection(
    point="router_imports",
    content="from .routes.auth import router as auth_router",
),
Injection(
    point="router_includes",
    content='api_router.include_router(auth_router, prefix="/auth", tags=["auth"])',
),

# In template.py:
"router_imports": InjectionPoint(
    file="src/{{pkg_name}}/api/router.py",
    locator=LocatorSpec(name="after_last_import", args={}),
),
"router_includes": InjectionPoint(
    file="src/{{pkg_name}}/api/router.py",
    locator=LocatorSpec(
        name="after_statement_matching",
        args={"pattern": r"router\.include_router\("},
    ),
),
```

#### Inject a lifespan startup hook (sentry addon)

```python
# In addon.py:
Injection(
    point="lifespan_startup",
    content="    from .integrations.sentry import init_sentry\n    init_sentry()",
),

# In template.py:
"lifespan_startup": InjectionPoint(
    file="src/{{pkg_name}}/lifecycle.py",
    locator=LocatorSpec(
        name="before_yield_in_function",
        args={"function": "lifespan"},
    ),
),
```

#### Add a pytest fixture (auth-manual addon)

```python
# In addon.py:
Injection(
    point="test_fixtures",
    content="""
@pytest.fixture
async def test_user(session: AsyncSession) -> User:
    user = User(email="test@example.com", hashed_password=hash_password("testpassword123"))
    session.add(user)
    await session.commit()
    await session.refresh(user)
    return user""",
),

# In template.py:
"test_fixtures": InjectionPoint(
    file="tests/conftest.py",
    locator=LocatorSpec(name="at_module_end", args={}),
),
```

#### Inject startup code on the blank template (sentry addon)

```python
# In addon.py:
Injection(
    point="main_startup",
    content="    from .integrations.sentry import init_sentry\n    init_sentry()",
),

# In template.py:
"main_startup": InjectionPoint(
    file="src/{{pkg_name}}/main.py",
    locator=LocatorSpec(
        name="before_return_in_function",
        args={"function": "main"},
    ),
),
```

---

## What Zenit injects

Zenit injects infrastructure wiring only. It never injects into business logic, data models, or test files.

Injections are limited to: startup and shutdown hooks, router registration calls, middleware configuration, settings class fields, and module-level imports required by those. If an addon needs a file that contains logic — a Redis helper module, a Celery app definition, an auth router — it writes that as a new file, not as an injection.

---

## Removal and fingerprinting

When `zenit remove` processes an addon, it reverses each injection using a three-stage search:

**Stage A — exact fingerprint.** SHA-256 of the canonical libcst output. Matches when the block is untouched.

**Stage B — normalised fingerprint.** SHA-256 after stripping trailing whitespace and collapsing blank lines. Matches when a formatter has run over the file. Silent.

**Stage C — fuzzy match.** SequenceMatcher similarity ≥ 85% within a 20-line window around the recorded position. Used when the block has been lightly edited. Zenit warns before removing.

If none succeed, Zenit prints the recorded block content, the file path, and instructs manual removal. It never silently corrupts a file.

After excising, the result is parsed to confirm it's still valid Python. If not, the operation aborts without writing.

---

## Debugging injection failures

### Preview with `--dry-run`

Before adding an addon, always preview with `--dry-run`:

```bash
zenit add redis --dry-run
```

This runs the entire injection pipeline — locator resolution, content rendering, insertion — but writes nothing to disk. You see exactly which lines would be inserted and where. If the locator fails, the error is printed at dry-run time, not after half the files have been written.

### Reading injection error messages

When injection fails, Zenit prints:

```
Error: Cannot inject at 'settings_fields' in src/my_project/settings.py.
  Reason: Could not find class 'Settings' in the module.
  Has the class been removed or renamed?
```

The message names the injection point, the file, and the exact reason the locator failed. Common causes:

| Error | Likely cause | Fix |
|---|---|---|
| `Could not find class 'X'` | Class was renamed or removed | Restore the class or declare a new injection point targeting the new name |
| `Could not find function 'X'` | Function was renamed or removed | Same as above |
| `No statement matches pattern 'X'` | The anchor statement was edited | Update the `anchor_pattern` in the injection point declaration |
| `Result is not valid Python` | Injected content has a syntax error | Check indentation in your `Injection.content` string |

### Indentation is your responsibility

The `content` field in `Injection` is inserted verbatim. If the target scope is indented (inside a class or function body), your content must include the correct leading whitespace:

```python
# WRONG — missing indentation for class body
Injection(
    point="settings_fields",
    content='redis_url: str = "redis://localhost:6379/0"',
)

# RIGHT
Injection(
    point="settings_fields",
    content='    redis_url: str = "redis://localhost:6379/0"',
)
```

If the injected result fails to parse as valid Python, Zenit aborts before writing. The error message shows the injection point and file — open the file, look at the surrounding code, and match the indentation of adjacent statements.

### Debugging a locator that finds the wrong place

If your code is injected but in the wrong location:

1. Add a print to your locator call (temporarily) or use `--dry-run` to see the line number
2. Cross-check the line number against the actual file
3. Verify your locator args — e.g., `after_statement_matching` matches the *first* statement that satisfies the regex, not the last

### After running a formatter

Formatters can change whitespace inside injected blocks enough to invalidate the exact fingerprint. Run `zenit doctor --thorough` to check:

```bash
zenit doctor --thorough
```

If the normalised fingerprint matches, removal will still work silently. If only the fuzzy match succeeds, Zenit will warn before removing. Either way, `zenit remove` will not lose your code.

### When `zenit remove` cannot locate a block

If all three fingerprint strategies fail, Zenit exits with:

```
Error: Could not remove 'settings_fields' injection for addon 'redis'.
  File: src/my_project/settings.py
  Expected block at lines 14-14 (fingerprint sha256:abc123...)
  Manual steps:
    - Open src/my_project/settings.py
    - Find the code added by the 'redis' addon for point 'settings_fields'
    - Remove it, then run: zenit doctor
```

The message prints the recorded fingerprint so you can identify the original content in `.zenit.toml` if the file has changed significantly. After manual removal, `zenit doctor` verifies the project is clean.
