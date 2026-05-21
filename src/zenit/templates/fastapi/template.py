from pathlib import Path

from zenit.schema.models import (
    EnvVar,
    FileContribution,
    InjectionPoint,
    LocatorSpec,
    TemplateConfig,
)

_HERE = Path(__file__).parent.absolute()

config = TemplateConfig(
    id="fastapi",
    description="FastAPI web framework skeleton",
    requires_addons=[],
    injection_points={
        "settings_fields": InjectionPoint(
            file="src/{{pkg_name}}/settings.py",
            locator=LocatorSpec(
                name="after_last_class_attribute",
                args={"class_name": "Settings"},
            ),
        ),
        "lifespan_startup": InjectionPoint(
            file="src/{{pkg_name}}/lifecycle.py",
            locator=LocatorSpec(
                name="before_yield_in_function",
                args={"function": "lifespan"},
            ),
        ),
        "lifespan_shutdown": InjectionPoint(
            file="src/{{pkg_name}}/lifecycle.py",
            locator=LocatorSpec(
                name="in_function_body",
                args={
                    "function": "lifespan",
                    "anchor_pattern": r"yield",
                    "position": "after",
                },
            ),
        ),
        "lifespan_imports": InjectionPoint(
            file="src/{{pkg_name}}/lifecycle.py",
            locator=LocatorSpec(
                name="after_last_import",
                args={},
            ),
        ),
        "env_vars": InjectionPoint(
            file=".env",
            locator=LocatorSpec(name="at_file_end", args={}),
        ),
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
        "test_imports": InjectionPoint(
            file="tests/conftest.py",
            locator=LocatorSpec(name="after_last_import", args={}),
        ),
        "test_fixtures": InjectionPoint(
            file="tests/conftest.py",
            locator=LocatorSpec(name="at_module_end", args={}),
        ),
        "exceptions": InjectionPoint(
            file="src/{{pkg_name}}/exceptions.py",
            locator=LocatorSpec(name="at_module_end", args={}),
        ),
    },
    dirs=[
        "src/{{pkg_name}}/api/routes",
        "src/{{pkg_name}}/core",
        "src/{{pkg_name}}/models",
        "src/{{pkg_name}}/schemas",
        "tests/fixtures",
        "tests/unit",
        "tests/integration",
    ],
    files=[
        FileContribution(
            dest="src/{{pkg_name}}/__init__.py",
            content='"""(( name ))"""\n\n__version__ = "0.1.0"\n',
            template=True,
        ),
        FileContribution(dest="src/{{pkg_name}}/api/__init__.py", content=""),
        FileContribution(dest="src/{{pkg_name}}/api/routes/__init__.py", content=""),
        FileContribution(dest="src/{{pkg_name}}/core/__init__.py", content=""),
        FileContribution(dest="src/{{pkg_name}}/schemas/__init__.py", content=""),
        FileContribution(
            dest="src/{{pkg_name}}/models/__init__.py",
            content="# Import all models here so Alembic can discover them.\n",
        ),
        FileContribution(
            dest="src/{{pkg_name}}/main.py",
            source=str(_HERE / "files" / "main.py.j2"),
            template=True,
        ),
        FileContribution(
            dest="src/{{pkg_name}}/lifecycle.py",
            source=str(_HERE / "files" / "lifecycle.py"),
        ),
        FileContribution(
            dest="src/{{pkg_name}}/exceptions.py",
            source=str(_HERE / "files" / "exceptions.py"),
        ),
        FileContribution(
            dest="src/{{pkg_name}}/api/router.py",
            source=str(_HERE / "files" / "api" / "router.py.j2"),
            template=True,
        ),
        FileContribution(
            dest="src/{{pkg_name}}/api/routes/health.py",
            source=str(_HERE / "files" / "api" / "routes" / "health.py"),
        ),
        FileContribution(
            dest="src/{{pkg_name}}/schemas/common.py",
            source=str(_HERE / "files" / "schemas" / "common.py"),
        ),
        FileContribution(
            dest="src/{{pkg_name}}/settings.py",
            source=str(_HERE / "files" / "settings.py.j2"),
            template=True,
        ),
        FileContribution(
            dest=".env",
            source=str(_HERE / "files" / ".env.j2"),
            template=True,
        ),
        FileContribution(
            dest=".env.example",
            source=str(_HERE / "files" / ".env.example"),
        ),
        FileContribution(
            dest="tests/conftest.py",
            source=str(_HERE / "files" / "tests" / "conftest.py.j2"),
            template=True,
        ),
        FileContribution(
            dest="tests/integration/test_health.py",
            source=str(_HERE / "files" / "tests" / "test_health.py"),
        ),
    ],
    deps=[
        "fastapi",
        "uvicorn[standard]",
        "pydantic-settings",
        "email-validator",
        "python-multipart",
    ],
    dev_deps=[],
    just_recipes=[
        "# start dev server with auto-reload\nrun:\n    uv run uvicorn (( pkg_name )).main:app --reload",
    ],
    env_vars=[
        EnvVar(key="DEBUG", default="false"),
    ],
)
