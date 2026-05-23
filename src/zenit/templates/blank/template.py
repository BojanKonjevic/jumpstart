from pathlib import Path

from zenit.core.handlers.locators import (
    LOCATOR_AFTER_LAST_CLASS_ATTR,
    LOCATOR_AT_FILE_END,
    LOCATOR_BEFORE_RETURN,
)
from zenit.schema.models import (
    FileContribution,
    InjectionPoint,
    LocatorSpec,
    TemplateConfig,
)

_HERE = Path(__file__).parent.absolute()

config = TemplateConfig(
    id="blank",
    description="dev tools only (pytest, ruff, mypy)",
    requires_addons=[],
    injection_points={
        "main_startup": InjectionPoint(
            file="src/{{pkg_name}}/main.py",
            locator=LocatorSpec(
                name=LOCATOR_BEFORE_RETURN,
                args={"function": "main"},
            ),
        ),
        "env_vars": InjectionPoint(
            file=".env",
            locator=LocatorSpec(name=LOCATOR_AT_FILE_END, args={}),
        ),
        "settings_fields": InjectionPoint(
            file="src/{{pkg_name}}/settings.py",
            locator=LocatorSpec(
                name=LOCATOR_AFTER_LAST_CLASS_ATTR,
                args={"class_name": "Settings"},
            ),
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
            dest="src/{{pkg_name}}/main.py",
            source=str(_HERE / "files" / "main.py.j2"),
            template=True,
        ),
        FileContribution(
            dest="src/{{pkg_name}}/__main__.py",
            source=str(_HERE / "files" / "__main__.py"),
        ),
        FileContribution(
            dest="tests/test_main.py",
            source=str(_HERE / "files" / "tests" / "test_main.py.j2"),
            template=True,
        ),
        FileContribution(
            dest=".env",
            content="",
        ),
    ],
    deps=[],
    dev_deps=[],
    just_recipes=[
        "# run the app\nrun:\n    uv run python -m (( pkg_name ))",
    ],
)
