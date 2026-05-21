# Writing a template

This walkthrough builds a `cli` template that scaffolds a [Click](https://click.palletsprojects.com) CLI application, with one injection point that addons can target.

For the full `TemplateConfig` API reference, see [Addons & Templates](../architecture/addons-and-templates.md).

---

## What we're building

```
my-cli/
├── .zenit.toml
├── pyproject.toml
├── justfile
├── .env
├── my_cli/
│   ├── __init__.py
│   ├── __main__.py
│   └── main.py          # Click group entry point
└── tests/
    └── test_cli.py
```

The `cli_commands` injection point at the end of `main.py` lets addons register new Click subcommands.

---

## Step 1: create the directories

```bash
mkdir -p src/scaffolder/templates/cli/files/tests
```

---

## Step 2: register in `_render.py`

Unlike addons, **templates are not auto-discovered for the interactive picker**. The filesystem loader finds `template.py` automatically, but you must add the template to `TEMPLATES` in `src/scaffolder/cli/prompt/_render.py`:

```python
TEMPLATES: list[tuple[str, str]] = [
    ("blank", "dev tools only  (pytest, ruff, mypy)"),
    ("fastapi", "FastAPI + SQLAlchemy + Alembic + asyncpg"),
    ("cli", "Click CLI application"),   # ← add this line
]
```

This is the only manual registration step.

---

## Step 3: write the template files

**`files/main.py.j2`** — rendered with Jinja2:

```python
import click
from dotenv import load_dotenv

load_dotenv()


@click.group()
def cli() -> None:
    """(( name ))."""


if __name__ == "__main__":
    cli()
```

**`files/__main__.py`** — static, copied verbatim:

```python
from .main import cli

cli()
```

**`files/tests/test_cli.py.j2`** — rendered with Jinja2:

```python
from click.testing import CliRunner

from (( pkg_name )).main import cli


def test_cli_invokes() -> None:
    runner = CliRunner()
    result = runner.invoke(cli, ["--help"])
    assert result.exit_code == 0
    assert "(( name ))" in result.output
```

---

## Step 4: write `template.py`

```python
# src/scaffolder/templates/cli/template.py
from pathlib import Path

from scaffolder.schema.models import (
    FileContribution,
    InjectionPoint,
    LocatorSpec,
    TemplateConfig,
)

_HERE = Path(__file__).parent.absolute()

config = TemplateConfig(
    id="cli",
    description="Click CLI application",
    requires_addons=[],
    injection_points={
        "cli_commands": InjectionPoint(
            file="src/{{pkg_name}}/main.py",
            locator=LocatorSpec(name="at_module_end", args={}),
        ),
        "env_vars": InjectionPoint(
            file=".env",
            locator=LocatorSpec(name="at_file_end", args={}),
        ),
    },
    dirs=[
        "src/{{pkg_name}}",
        "tests",
    ],
    files=[
        FileContribution(
            dest="src/{{pkg_name}}/__init__.py",
            content='"""(( name ))"""\n\n__version__ = "0.1.0"\n',
            template=True,
        ),
        FileContribution(
            dest="src/{{pkg_name}}/__main__.py",
            source=str(_HERE / "files" / "__main__.py"),
        ),
        FileContribution(
            dest="src/{{pkg_name}}/main.py",
            source=str(_HERE / "files" / "main.py.j2"),
            template=True,
        ),
        FileContribution(
            dest="tests/test_cli.py",
            source=str(_HERE / "files" / "tests" / "test_cli.py.j2"),
            template=True,
        ),
        FileContribution(dest=".env", content=""),
    ],
    deps=["click", "python-dotenv"],
    dev_deps=[],
    just_recipes=[
        "# run the CLI\nrun *ARGS:\n    uv run python -m (( pkg_name )) {{ARGS}}",
    ],
)
```

> [!NOTE]
> The `_common/apply.py` script always runs before your template files. `.gitignore`, `.gitattributes`, `.pre-commit-config.yaml`, `.envrc`, and `shell.nix` are written to every project automatically — you do not need to declare them.

---

## Step 5: test it

```bash
zenit create my-cli
# select cli when prompted
cd my-cli

just run --help   # should print "my-cli." and exit 0
just test         # should pass
zenit doctor      # should be clean
```

---

## Step 6: verify the injection point works

Write a minimal addon that targets `cli_commands`:

```python
# src/scaffolder/addons/hello-cmd/addon.py
from scaffolder.schema.models import AddonConfig, Injection

config = AddonConfig(
    id="hello-cmd",
    description="Adds a 'hello' subcommand.",
    templates=["cli"],
    injections=[
        Injection(
            point="cli_commands",
            content=(
                "\n\n@cli.command()\n"
                "def hello() -> None:\n"
                '    """Say hello."""\n'
                '    click.echo("Hello from zenit")\n'
            ),
        ),
    ],
)
```

```bash
zenit add hello-cmd
just run hello        # Hello from zenit
zenit remove hello-cmd
```

---

## Step 7: force an addon with `requires_addons`

If your template needs an addon at scaffold time — the way `fastapi` forces `docker` — list it in `requires_addons`:

```python
config = TemplateConfig(
    id="cli",
    requires_addons=["github-actions"],  # auto-selected and locked for all cli projects
    ...
)
```

Addons in `requires_addons` appear with a lock indicator in the TUI and cannot be deselected.

---

## Addon vs template: key differences

| | Addon | Template |
|---|---|---|
| Discovery | Automatic — scans `addons/` | Requires entry in `_render.py` |
| Lifecycle | Add / remove after creation | Selected once at `zenit create` |
| Injection points | Consumes them | Declares them |
| Forced dependencies | `requires: list[str]` | `requires_addons: list[str]` |
| `_common` files | N/A | Always applied first |
