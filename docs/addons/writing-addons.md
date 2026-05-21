# Writing an addon

This walkthrough builds a `hello` addon from scratch — a file, an injection, a preflight check, and a health check. By the end you'll have a working addon installable with `zenit add hello`.

For the full `AddonConfig` API reference, see [Addons & Templates](../architecture/addons-and-templates.md).

---

## Step 1: create the directory

```bash
mkdir src/zenit/addons/hello
```

The registry scans `addons/` on every run. No registration step needed.

---

## Step 2: minimal `addon.py`

```python
# src/zenit/addons/hello/addon.py
from zenit.schema.models import AddonConfig, Injection

config = AddonConfig(
    id="hello",
    description="Injects a hello-world print into main().",
    templates=["blank"],
    injections=[
        Injection(
            point="main_startup",
            content='    print("hello from zenit")',
        ),
    ],
)
```

That's a complete addon — no files, no dependencies, just one injection.

---

## Step 3: test it

```bash
zenit create hello-test
cd hello-test

zenit add hello --dry-run   # preview without writing
zenit add hello             # install

cat src/hello_test/main.py  # verify injection landed
zenit doctor                # verify manifest is clean
zenit remove hello          # verify clean removal
cat src/hello_test/main.py  # verify it's gone
```

---

## Step 4: add a file

```python
from pathlib import Path
from zenit.schema.models import AddonConfig, FileContribution, Injection

_HERE = Path(__file__).parent.absolute()

config = AddonConfig(
    id="hello",
    description="Writes a greeter module and wires it into main().",
    templates=["blank"],
    files=[
        FileContribution(
            dest="src/{{pkg_name}}/greeter.py",
            source=str(_HERE / "files" / "greeter.py.j2"),
            template=True,
        ),
    ],
    injections=[
        Injection(
            point="main_startup",
            content="    from .greeter import greet\n    greet()",
        ),
    ],
)
```

```python
# src/zenit/addons/hello/files/greeter.py.j2
def greet() -> None:
    print("hello from (( name ))")
```

The `(( name ))` variable expands to the project name at render time. See [Jinja2 template variables](../architecture/addons-and-templates.md#jinja2-template-variables) for the full list.

---

## Step 5: add a preflight check

`can_apply` runs before any files are written. Return `None` to proceed, or a string to abort with a clear error.

```python
from pathlib import Path
from zenit.core.lockfile import ZenitLockfile

def can_apply(project_dir: Path, lockfile: ZenitLockfile) -> str | None:
    pkg_name = project_dir.name.replace("-", "_")
    target = project_dir / "src" / pkg_name / "greeter.py"
    if target.exists():
        return (
            f"{target.relative_to(project_dir)} already exists.\n"
            f"    Remove it first: rm {target.relative_to(project_dir)}"
        )
    return None
```

---

## Step 6: add a health check

`health_check` is called by `zenit doctor`. Return a list of `HealthIssue` objects describing what you expect to be true.

```python
from zenit.doctor.doctor import HealthIssue, Severity

def health_check(project_dir: Path, lockfile: ZenitLockfile) -> list[HealthIssue]:
    pkg_name = project_dir.name.replace("-", "_")
    greeter = project_dir / "src" / pkg_name / "greeter.py"
    if greeter.exists():
        return [HealthIssue(Severity.OK, "greeter.py is present.")]
    return [HealthIssue(
        Severity.ERROR,
        "greeter.py is missing.",
        hint="Re-add the hello addon: zenit add hello",
    )]
```

---

## Complete `addon.py`

```python
from pathlib import Path

from zenit.core.lockfile import ZenitLockfile
from zenit.doctor.doctor import HealthIssue, Severity
from zenit.schema.models import AddonConfig, FileContribution, Injection

_HERE = Path(__file__).parent.absolute()

config = AddonConfig(
    id="hello",
    description="Writes a greeter module and wires it into main().",
    templates=["blank"],
    files=[
        FileContribution(
            dest="src/{{pkg_name}}/greeter.py",
            source=str(_HERE / "files" / "greeter.py.j2"),
            template=True,
        ),
    ],
    injections=[
        Injection(
            point="main_startup",
            content="    from .greeter import greet\n    greet()",
        ),
    ],
)


def can_apply(project_dir: Path, lockfile: ZenitLockfile) -> str | None:
    pkg_name = project_dir.name.replace("-", "_")
    target = project_dir / "src" / pkg_name / "greeter.py"
    if target.exists():
        return (
            f"{target.relative_to(project_dir)} already exists.\n"
            f"    Remove it first: rm {target.relative_to(project_dir)}"
        )
    return None


def health_check(project_dir: Path, lockfile: ZenitLockfile) -> list[HealthIssue]:
    pkg_name = project_dir.name.replace("-", "_")
    greeter = project_dir / "src" / pkg_name / "greeter.py"
    if greeter.exists():
        return [HealthIssue(Severity.OK, "greeter.py is present.")]
    return [HealthIssue(
        Severity.ERROR,
        "greeter.py is missing.",
        hint="Re-add the hello addon: zenit add hello",
    )]
```
