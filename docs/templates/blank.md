# blank

The `blank` template produces a minimal Python package — a working entry point, a passing test, and a full set of dev tooling. It has no framework, no database, and no service dependencies. Everything Zenit adds is removable.

---

## When to use it

Choose `blank` when you are building a CLI tool, a script, a library, or any project that does not need a web framework. If you later decide you need FastAPI, re-scaffold with the `fastapi` template — `blank` is not upgradeable in place.

---

## What gets generated

```
my-project/
├── .zenit.toml                  # Zenit's manifest — tracks what was generated
├── pyproject.toml               # Project metadata and dependencies
├── justfile                     # Task runner recipes
├── .env                         # Local environment variables (not committed)
├── .envrc                       # direnv hook — auto-activates the virtualenv on cd
├── .gitignore
├── .gitattributes
├── .pre-commit-config.yaml      # Ruff lint, ruff format, mypy on every commit
├── shell.nix                    # NixOS only — provides libstdc++
├── my_project/
│   ├── __init__.py              # Package version string
│   ├── __main__.py              # Allows python -m my_project
│   └── main.py                  # Entry point: main() function
└── tests/
    └── test_main.py             # Smoke test for main()
```

---

## Entry point

`main.py` exports a single `main()` function and no global side effects:

```python
def main() -> None:
    print("Hello from my-project!")

if __name__ == "__main__":
    main()
```

`__main__.py` imports and calls `main()` so the package is runnable as:

```bash
python -m my_project
# or via justfile:
just run
```

---

## Injection points

The `blank` template is intentionally minimal. It exposes two injection points:

| Point | File | Locator | What goes here |
|---|---|---|---|
| `settings_fields` | `src/{{pkg_name}}/settings.py` | `after_last_class_attribute` (`Settings`) | Pydantic settings fields |
| `main_startup` | `src/{{pkg_name}}/main.py` | `before_return_in_function` (`main`) | Startup calls — e.g. `init_sentry()` |
| `env_vars` | `.env` | `at_file_end` | Key=value pairs appended to the env file |

If you need richer hooks (lifespan, router registration, test fixtures), use the `fastapi` template — it exposes ten distinct injection points. If you want a new hook added to `blank`, open an issue or see [Contributing](../contributing.md).

---

## Dependencies

The `blank` template has no runtime dependencies. Dev tooling (`pytest`, `mypy`, `ruff`, `pytest-cov`) is added under `[dependency-groups] dev` and is the same across all templates.

---

## Justfile recipes

| Recipe | Command |
|---|---|
| `just run` | `uv run python -m <pkg_name>` |
| `just test` | `uv run pytest -v` |
| `just cov` | `uv run pytest --cov=src --cov-report=term-missing` |
| `just lint` | `uv run ruff check .` |
| `just fmt` | `uv run ruff format .` |
| `just fix` | `ruff check --fix` + `ruff format` |
| `just check` | `uv run mypy src/` |

---

## Compatibility and constraints

> [!NOTE]
> Two addons do not work with `blank`: `auth-manual` (requires `fastapi` template) and `sqlmodel` (requires `fastapi` template). All other addons are optional and compatible.


**NixOS:** `shell.nix` is written alongside `.envrc` to provide `libstdc++.so.6`. The `.envrc` is prefixed with `use nix shell.nix`. On non-NixOS systems `shell.nix` is not written.

**Windows:** `.envrc` and `shell.nix` are not written. The environment is managed entirely by `uv` and every recipe runs through `uv run`.
