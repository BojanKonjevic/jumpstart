"""Tests for the migration pipeline."""

import sys
from pathlib import Path

import pytest
import yaml

from zenit.core.lockfile import read_lockfile
from zenit.core.manifest import read_manifest
from zenit.migrate.copier import (
    CopierConfig,
    CopierQuestion,
    QuestionClass,
    QuestionType,
    parse_copier_yml,
)
from zenit.migrate.migrate import (
    MigrationAnswers,
    _inventory_compose,
    _inventory_deps,
    _inventory_env,
    _normalise_source,
    _prompt_questions,
    _resolve_answers_noninteractive,
    _stabilise_render_vars,
    run_migration,
)
from zenit.schema.exceptions import ZenitError

# ── _normalise_source ──────────────────────────────────────────────────────────


def test_normalise_github_url() -> None:
    assert (
        _normalise_source("https://github.com/user/repo")
        == "https://github.com/user/repo"
    )


def test_normalise_gh_shorthand() -> None:
    assert _normalise_source("gh:user/repo") == "https://github.com/user/repo"


def test_normalise_gh_shorthand_no_slash() -> None:
    """If no slash, assume repo name matches user name."""
    assert _normalise_source("gh:user") == "https://github.com/user/user"


def test_normalise_local_path() -> None:
    assert _normalise_source("./local-template") == str(
        Path("./local-template").resolve()
    )


# ── _prompt_questions (non-interactive) ────────────────────────────────────────


def test_prompt_render_var_str(monkeypatch: pytest.MonkeyPatch) -> None:
    config = CopierConfig(
        questions=[
            CopierQuestion(
                name="name", type=QuestionType.STR, default="myapp", help="Name"
            )
        ]
    )
    classes = {"name": QuestionClass.RENDER_VAR}
    monkeypatch.setattr("builtins.input", lambda prompt="": "testproj")
    answers = _prompt_questions(config, classes)
    assert answers.render_vars["name"] == "testproj"


def test_prompt_questions_uses_default_when_empty(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = CopierConfig(
        questions=[
            CopierQuestion(
                name="name", type=QuestionType.STR, default="myapp", help="Name"
            )
        ]
    )
    classes = {"name": QuestionClass.RENDER_VAR}
    monkeypatch.setattr("builtins.input", lambda prompt="": "")
    answers = _prompt_questions(config, classes)
    assert answers.render_vars["name"] == "myapp"


# ── Non-interactive answer resolution ─────────────────────────────────────────


def test_resolve_noninteractive_uses_defaults() -> None:
    config = CopierConfig(
        questions=[
            CopierQuestion(name="name", type=QuestionType.STR, default="myapp"),
            CopierQuestion(name="port", type=QuestionType.INT, default=8080),
            CopierQuestion(name="debug", type=QuestionType.BOOL, default=False),
        ]
    )
    answers = _resolve_answers_noninteractive(config, {})
    assert answers.render_vars["name"] == "myapp"
    assert answers.render_vars["port"] == 8080
    assert answers.render_vars["debug"] is False


def test_resolve_noninteractive_renders_jinja_defaults_in_order() -> None:
    config = CopierConfig(
        questions=[
            CopierQuestion(
                name="project_name",
                type=QuestionType.STR,
                default="my-proj",
            ),
            CopierQuestion(
                name="package_name",
                type=QuestionType.STR,
                default="{{ project_name | replace('-', '_') }}",
            ),
        ]
    )
    answers = _resolve_answers_noninteractive(config, {})
    assert answers.render_vars["project_name"] == "my-proj"
    assert answers.render_vars["package_name"] == "my_proj"


def test_resolve_noninteractive_applies_overrides() -> None:
    config = CopierConfig(
        questions=[
            CopierQuestion(name="name", type=QuestionType.STR, default="myapp"),
            CopierQuestion(name="port", type=QuestionType.INT, default=8080),
            CopierQuestion(name="debug", type=QuestionType.BOOL, default=False),
        ]
    )
    answers = _resolve_answers_noninteractive(
        config, {"name": "custom", "port": "3000", "debug": "yes"}
    )
    assert answers.render_vars["name"] == "custom"
    assert answers.render_vars["port"] == 3000
    assert answers.render_vars["debug"] is True


def test_resolve_noninteractive_missing_default() -> None:
    config = CopierConfig(
        questions=[
            CopierQuestion(
                name="db_url",
                type=QuestionType.STR,
                default=None,  # no default
            ),
        ]
    )
    with pytest.raises(ZenitError, match="has no default"):
        _resolve_answers_noninteractive(config, {})


def test_resolve_noninteractive_override_handles_missing_default() -> None:
    """An override should satisfy a question that has no default."""
    config = CopierConfig(
        questions=[
            CopierQuestion(name="db_url", type=QuestionType.STR, default=None),
        ]
    )
    answers = _resolve_answers_noninteractive(
        config, {"db_url": "postgres://localhost"}
    )
    assert answers.render_vars["db_url"] == "postgres://localhost"


def test_resolve_noninteractive_renders_templated_default_values() -> None:
    config = CopierConfig(
        questions=[
            CopierQuestion(
                name="project_name", type=QuestionType.STR, default="my-proj"
            ),
            CopierQuestion(
                name="package_name",
                type=QuestionType.STR,
                default="{{ project_name | replace('-', '_') }}",
            ),
        ]
    )
    answers = _resolve_answers_noninteractive(config, {})
    assert answers.render_vars["project_name"] == "my-proj"
    assert answers.render_vars["package_name"] == "my_proj"


# ── _stabilise_render_vars ─────────────────────────────────────────────────────


def test_stabilise_simple_chain() -> None:
    """project_name → package_name converges in 1 iteration."""
    config = CopierConfig(
        questions=[
            CopierQuestion(
                name="project_name", type=QuestionType.STR, default="my-app"
            ),
            CopierQuestion(
                name="package_name",
                type=QuestionType.STR,
                default="{{ project_name | replace('-', '_') }}",
            ),
        ]
    )
    answers = MigrationAnswers()
    answers.render_vars["project_name"] = "my-app"
    answers.render_vars["package_name"] = ""

    _stabilise_render_vars(config, answers, set())

    assert answers.render_vars["package_name"] == "my_app"


def test_stabilise_3level_chain() -> None:
    """a → b → c converges in multiple iterations."""
    config = CopierConfig(
        questions=[
            CopierQuestion(name="a", type=QuestionType.STR, default="hello"),
            CopierQuestion(name="b", type=QuestionType.STR, default="{{ a }}_b"),
            CopierQuestion(name="c", type=QuestionType.STR, default="{{ b }}_c"),
        ]
    )
    answers = MigrationAnswers()
    answers.render_vars["a"] = "hello"
    answers.render_vars["b"] = ""
    answers.render_vars["c"] = ""

    _stabilise_render_vars(config, answers, set())

    assert answers.render_vars["b"] == "hello_b"
    assert answers.render_vars["c"] == "hello_b_c"


def test_stabilise_when_false_computed() -> None:
    """when: false var gets re-resolved against current context."""
    config = CopierConfig(
        questions=[
            CopierQuestion(name="flag_a", type=QuestionType.BOOL, default=True),
            CopierQuestion(
                name="flag_b",
                type=QuestionType.BOOL,
                default="{{ flag_a }}",
                when=False,
            ),
        ]
    )
    answers = MigrationAnswers()
    answers.render_vars["flag_a"] = True
    answers.render_vars["flag_b"] = False  # Initial resolution got this wrong

    _stabilise_render_vars(config, answers, set())

    assert answers.render_vars["flag_b"] is True


def test_stabilise_self_referential() -> None:
    """Self-referential default does not loop."""
    config = CopierConfig(
        questions=[
            CopierQuestion(
                name="a",
                type=QuestionType.STR,
                default="{{ a | default('val') }}",
            ),
        ]
    )
    answers = MigrationAnswers()
    answers.render_vars["a"] = "val"

    _stabilise_render_vars(config, answers, set())

    assert answers.render_vars["a"] == "val"


def test_stabilise_no_jinja_defaults() -> None:
    """No Jinja2 defaults — no changes to answers."""
    config = CopierConfig(
        questions=[
            CopierQuestion(name="name", type=QuestionType.STR, default="myapp"),
            CopierQuestion(name="port", type=QuestionType.INT, default=8080),
        ]
    )
    answers = MigrationAnswers()
    answers.render_vars["name"] = "myapp"
    answers.render_vars["port"] = 8080

    _stabilise_render_vars(config, answers, set())

    assert answers.render_vars["name"] == "myapp"
    assert answers.render_vars["port"] == 8080


def test_stabilise_override_skipped() -> None:
    """Overridden names are never re-resolved."""
    config = CopierConfig(
        questions=[
            CopierQuestion(name="name", type=QuestionType.STR, default="default"),
            CopierQuestion(
                name="derived",
                type=QuestionType.STR,
                default="{{ name }}_suffix",
            ),
        ]
    )
    answers = MigrationAnswers()
    answers.render_vars["name"] = "custom"

    _stabilise_render_vars(config, answers, {"name"})

    assert answers.render_vars["derived"] == "custom_suffix"
    assert answers.render_vars["name"] == "custom"


def test_stabilise_circular_dependency_warns(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Circular dependency emits warning after max iterations."""
    # Each pass appends a character — never converges.
    config = CopierConfig(
        questions=[
            CopierQuestion(name="a", type=QuestionType.STR, default="{{ b }}x"),
            CopierQuestion(name="b", type=QuestionType.STR, default="{{ a }}x"),
        ]
    )
    answers = MigrationAnswers()
    answers.render_vars["a"] = ""
    answers.render_vars["b"] = ""

    warnings: list[str] = []
    monkeypatch.setattr(
        "zenit.migrate.migrate.warn",
        lambda msg: warnings.append(msg),
    )

    _stabilise_render_vars(config, answers, set())

    assert len(warnings) == 1
    assert "not stabilize" in warnings[0]


def test_stabilise_preserves_user_explicit_values(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Questions where user typed a value are not overwritten."""
    config = CopierConfig(
        questions=[
            CopierQuestion(name="a", type=QuestionType.STR, default="default_a"),
            CopierQuestion(
                name="b",
                type=QuestionType.STR,
                default="{{ a }}_from_b",
            ),
        ]
    )
    answers = MigrationAnswers()
    answers.render_vars["a"] = "user_value"  # User explicitly typed this
    answers.render_vars["b"] = "user_b_value"  # User explicitly typed this

    # "a" and "b" are both explicit — neither should be re-resolved
    _stabilise_render_vars(config, answers, {"a", "b"})

    assert answers.render_vars["b"] == "user_b_value"


# ── run_migration (end-to-end) ─────────────────────────────────────────────────


def test_run_migration_noninteractive_with_name(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    template_dir = _create_copier_template(tmp_path)
    monkeypatch.chdir(tmp_path)

    result = run_migration(str(template_dir), name="myproj")

    assert result.project_dir == (tmp_path / "myproj").resolve()
    assert result.project_dir.exists()
    main_py = (result.project_dir / "main.py").read_text(encoding="utf-8")
    assert "import redis" not in main_py  # use_redis default is False
    assert '"""myproj main module."""' in main_py


def test_run_migration_noninteractive_with_name_and_data(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    template_dir = _create_copier_template(tmp_path)
    monkeypatch.chdir(tmp_path)

    result = run_migration(str(template_dir), name="myproj", data={"use_redis": "yes"})

    assert result.project_dir == (tmp_path / "myproj").resolve()
    assert result.project_dir.exists()
    main_py = (result.project_dir / "main.py").read_text(encoding="utf-8")
    assert "import redis" in main_py  # overridden to yes
    assert '"""myproj main module."""' in main_py


def test_run_migration_noninteractive_with_data_only(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    template_dir = _create_copier_template(tmp_path)
    monkeypatch.chdir(tmp_path)

    # project_name has no explicit default; -D provides it
    result = run_migration(
        str(template_dir), data={"project_name": "myproj", "use_redis": "no"}
    )

    assert result.project_dir == (tmp_path / "myproj").resolve()
    assert result.project_dir.exists()
    main_py = (result.project_dir / "main.py").read_text(encoding="utf-8")
    assert "import redis" not in main_py


# ── Inventory ──────────────────────────────────────────────────────────────────


def test_inventory_env(tmp_path: Path) -> None:
    (tmp_path / ".env").write_text(
        "# comment\nKEY1=val1\nKEY2=val2\n", encoding="utf-8"
    )
    keys = _inventory_env(tmp_path)
    assert "KEY1" in keys
    assert "KEY2" in keys


def test_inventory_env_example(tmp_path: Path) -> None:
    (tmp_path / ".env.example").write_text(
        "DB_URL=postgres://localhost\n", encoding="utf-8"
    )
    keys = _inventory_env(tmp_path)
    assert "DB_URL" in keys


def test_inventory_compose(tmp_path: Path) -> None:
    compose = {
        "services": {"web": {"image": "nginx"}, "db": {"image": "postgres"}},
        "volumes": {"data": None},
    }
    (tmp_path / "compose.yml").write_text(yaml.dump(compose), encoding="utf-8")
    services, volumes = _inventory_compose(tmp_path)
    assert sorted(services) == ["db", "web"]
    assert volumes == ["data"]


def test_inventory_compose_missing(tmp_path: Path) -> None:
    services, volumes = _inventory_compose(tmp_path)
    assert services == []
    assert volumes == []


def test_inventory_deps(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text(
        '[project]\ndependencies = ["fastapi>=0.100", "redis>=5"]\n'
        '[dependency-groups]\ndev = ["pytest>=8"]\n',
        encoding="utf-8",
    )
    deps = _inventory_deps(tmp_path)
    dep_names = [d[0] for d in deps]
    assert "fastapi" in dep_names
    assert "redis" in dep_names
    assert "pytest" in dep_names


# ── run_migration (end-to-end with local template) ────────────────────────────


def _create_copier_template(tmp_path: Path, name: str = "test-template") -> Path:
    """Create a minimal Copier template directory for testing."""
    template_dir = tmp_path / name
    template_dir.mkdir()

    copier_yml = {
        "project_name": {"type": "str", "help": "Project name"},
        "use_redis": {"type": "bool", "default": False, "help": "Add Redis?"},
    }
    (template_dir / "copier.yml").write_text(yaml.dump(copier_yml), encoding="utf-8")

    (template_dir / "README.md.jinja").write_text(
        "# {{ project_name }}\n\nWelcome to {{ project_name }}.\n",
        encoding="utf-8",
    )
    (template_dir / "main.py.jinja").write_text(
        '"""{{ project_name }} main module."""\n\n'
        "{% if use_redis %}\nimport redis\n{% endif %}\n\n"
        'def main() -> None:\n    print("hello")\n',
        encoding="utf-8",
    )
    (template_dir / "static.txt").write_text("static content\n", encoding="utf-8")

    return template_dir


def test_run_migration_local_template(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    template_dir = _create_copier_template(tmp_path)

    # Mock user input: project_name="myproject", use_redis=yes
    inputs = iter(["myproject", "y"])
    monkeypatch.setattr("builtins.input", lambda prompt="": next(inputs))
    monkeypatch.chdir(tmp_path)

    result = run_migration(str(template_dir))

    assert result.project_dir.exists()
    assert (result.project_dir / "README.md").exists()
    assert (result.project_dir / "main.py").exists()
    assert (result.project_dir / "static.txt").exists()
    assert "README.md" in result.file_paths or "README.md.jinja" in result.file_paths

    # Check lockfile
    lockfile = read_lockfile(result.project_dir)
    assert lockfile is not None
    assert lockfile.template_source == "copier"
    assert lockfile.template_uri != ""

    # Check manifest has TEMPLATE entries
    manifest = read_manifest(result.project_dir)
    assert manifest is not None

    # Verify template was rendered with user answers
    main_py = (result.project_dir / "main.py").read_text(encoding="utf-8")
    assert "import redis" in main_py  # use_redis was yes
    assert '"""myproject main module."""' in main_py  # project_name rendered


def test_run_migration_without_addon(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    template_dir = _create_copier_template(tmp_path)

    # Mock user input: project_name="myproject", use_redis=no
    inputs = iter(["myproject", "n"])
    monkeypatch.setattr("builtins.input", lambda prompt="": next(inputs))
    monkeypatch.chdir(tmp_path)

    result = run_migration(str(template_dir))

    assert result.project_dir.exists()
    main_py = (result.project_dir / "main.py").read_text(encoding="utf-8")
    assert "import redis" not in main_py  # use_redis was no

    lockfile = read_lockfile(result.project_dir)
    assert lockfile is not None
    assert lockfile.template_source == "copier"


def test_run_migration_creates_lockfile_with_copier_section(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    template_dir = _create_copier_template(tmp_path)

    inputs = iter(["myproject", "n"])
    monkeypatch.setattr("builtins.input", lambda prompt="": next(inputs))
    monkeypatch.chdir(tmp_path)

    result = run_migration(str(template_dir))

    lockfile = read_lockfile(result.project_dir)
    assert lockfile is not None
    assert lockfile.template_source == "copier"
    assert lockfile.template_uri != ""
    assert isinstance(lockfile.template_file_paths, list)
    assert len(lockfile.template_file_paths) > 0


def test_run_migration_fails_when_dir_exists(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    template_dir = _create_copier_template(tmp_path)

    inputs = iter(["myproject", "n"])
    monkeypatch.setattr("builtins.input", lambda prompt="": next(inputs))
    monkeypatch.chdir(tmp_path)

    # Create the project directory first so run_migration will fail
    project_dir = tmp_path / "myproject"
    project_dir.mkdir()

    with pytest.raises(ZenitError):
        run_migration(str(template_dir))


@pytest.mark.skipif(
    sys.platform == "win32",
    reason="Template path contains | which is illegal on Windows",
)
def test_run_migration_renders_unsuffixed_pyproject_and_templated_paths(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    template_dir = tmp_path / "copier-template"
    template_dir.mkdir()
    (template_dir / "copier.yml").write_text(
        yaml.dump(
            {
                "project_name": {"type": "str", "help": "Project name"},
            }
        ),
        encoding="utf-8",
    )
    (template_dir / "pyproject.toml").write_text(
        "[project]\n"
        'name = "{{ project_name }}"\n'
        'version = "0.1.0"\n'
        "[project.scripts]\n"
        '"{{ project_name }}" = '
        "\"{{ project_name | replace('-', '_') }}.main:main\"\n"
        "[tool.hatch.build.targets.wheel]\n"
        "packages = [\"src/{{ project_name | replace('-', '_') }}\"]\n",
        encoding="utf-8",
    )
    package_dir = template_dir / "src" / "{{ project_name | replace('-', '_') }}"
    package_dir.mkdir(parents=True)
    (package_dir / "main.py.jinja").write_text(
        'def main() -> None:\n    print("hello from {{ project_name }}")\n',
        encoding="utf-8",
    )

    monkeypatch.chdir(tmp_path)

    result = run_migration(str(template_dir), name="my-proj")

    pyproject_text = (result.project_dir / "pyproject.toml").read_text(encoding="utf-8")
    assert "{{" not in pyproject_text
    assert '"my-proj" = "my_proj.main:main"' in pyproject_text
    assert 'packages = ["src/my_proj"]' in pyproject_text

    package_main = result.project_dir / "src" / "my_proj" / "main.py"
    assert package_main.exists()
    assert 'print("hello from my-proj")' in package_main.read_text(encoding="utf-8")


def test_run_migration_renders_jinja_backed_package_name_default(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    template_dir = tmp_path / "copier-template"
    template_dir.mkdir()
    (template_dir / "copier.yml").write_text(
        "project_name:\n"
        "  type: str\n"
        "  help: Project name\n"
        "package_name:\n"
        "  type: str\n"
        "  default: \"{{ project_name | replace('-', '_') }}\"\n",
        encoding="utf-8",
    )
    (template_dir / "pyproject.toml.jinja").write_text(
        "[project]\n"
        'name = "{{ project_name }}"\n'
        'version = "0.1.0"\n'
        "[project.scripts]\n"
        '"{{ project_name }}" = "{{ package_name }}.main:main"\n',
        encoding="utf-8",
    )
    package_dir = template_dir / "src" / "{{ package_name }}"
    package_dir.mkdir(parents=True)
    (package_dir / "main.py.jinja").write_text(
        'def main() -> None:\n    print("hello")\n',
        encoding="utf-8",
    )

    monkeypatch.chdir(tmp_path)

    result = run_migration(str(template_dir), name="my-proj")

    pyproject_text = (result.project_dir / "pyproject.toml").read_text(encoding="utf-8")
    assert "{{" not in pyproject_text
    assert '"my-proj" = "my_proj.main:main"' in pyproject_text
    assert (result.project_dir / "src" / "my_proj" / "main.py").exists()


def test_run_migration_derives_package_name_when_project_name_empty(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """When project_name is empty (interactive mode, user pressed Enter),
    _pick_project_name derives it from the source path.  package_name
    (which defaults to ``{{ project_name | replace('-', '_') }}``) must
    be re-derived from the new project_name so that template rendering
    and mv-task rewrites use the correct value.
    """
    src_dir = tmp_path / "source"
    src_dir.mkdir()
    (src_dir / "copier.yml").write_text(
        "project_name:\n"
        "  type: str\n"
        "  help: Project name\n"
        "package_name:\n"
        "  type: str\n"
        "  default: \"{{ project_name | replace('-', '_') }}\"\n",
        encoding="utf-8",
    )
    (src_dir / "main.py.jinja").write_text(
        '"""{{ package_name }} main module."""\nVERSION = "0.1.0"\n',
        encoding="utf-8",
    )

    # All prompts return empty — project_name is empty, so dependent
    # defaults (package_name) are also empty at prompt-time.
    monkeypatch.setattr("builtins.input", lambda prompt="": "")
    out_dir = tmp_path / "out"
    out_dir.mkdir()
    monkeypatch.chdir(out_dir)

    result = run_migration(str(src_dir))

    # Project name derived from src_dir.name ("source").
    # package_name must be re-derived as "source".
    assert result.project_dir.name == "source"
    main_py = (result.project_dir / "main.py").read_text(encoding="utf-8")
    assert '"""source main module."""' in main_py


def test_run_migration_applies_safe_mv_and_rm_tasks(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    template_dir = tmp_path / "copier-template"
    template_dir.mkdir()
    (template_dir / "copier.yml").write_text(
        "project_name:\n"
        "  type: str\n"
        "package_name:\n"
        "  type: str\n"
        "  default: \"{{ project_name | replace('-', '_') }}\"\n"
        "_tasks:\n"
        '  - command: mv src/project_name "src/{{ package_name }}"\n'
        "    when: \"{{ package_name != 'project_name' }}\"\n"
        '  - command: rm -rf "src/{{ package_name }}/api/" docs/\n'
        '    when: "{{ not use_api }}"\n'
        "  - echo keep-manual\n"
        "use_api:\n"
        "  type: bool\n"
        "  default: false\n",
        encoding="utf-8",
    )
    src_dir = template_dir / "src" / "project_name"
    (src_dir / "api").mkdir(parents=True)
    (src_dir / "main.py.jinja").write_text("VALUE = 1\n", encoding="utf-8")
    (src_dir / "api" / "routes.py.jinja").write_text("VALUE = 2\n", encoding="utf-8")
    (template_dir / "docs" / "index.md").parent.mkdir(parents=True)
    (template_dir / "docs" / "index.md").write_text("# docs\n", encoding="utf-8")

    monkeypatch.chdir(tmp_path)

    result = run_migration(str(template_dir), name="my-proj")

    assert (result.project_dir / "src" / "my_proj" / "main.py").exists()
    assert not (result.project_dir / "src" / "project_name").exists()
    assert not (result.project_dir / "src" / "my_proj" / "api").exists()
    assert not (result.project_dir / "docs").exists()

    task_stub = (result.project_dir / ".zenit-tasks.md").read_text(encoding="utf-8")
    assert "echo keep-manual" in task_stub
    assert "mv src/project_name" not in task_stub
    assert "rm -rf" not in task_stub


# ── _apply_skip_if_exists ───────────────────────────────────────────────────────


def test_apply_skip_if_exists_file_exists_pattern_matches(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """File exists and pattern matches → skipped with warning."""
    warnings: list[str] = []
    monkeypatch.setattr(
        "zenit.migrate.migrate.warn",
        lambda msg: warnings.append(msg),
    )
    (tmp_path / "CHANGELOG.md").write_text("existing")

    from zenit.migrate.migrate import _apply_skip_if_exists
    from zenit.schema.models import FileContribution

    contributions = [
        FileContribution(dest="CHANGELOG.md"),
        FileContribution(dest="README.md"),
    ]
    result = _apply_skip_if_exists(contributions, ["CHANGELOG.md"], tmp_path, {})
    assert len(result) == 1
    assert result[0].dest == "README.md"
    assert len(warnings) == 1
    assert "CHANGELOG.md" in warnings[0]


def test_apply_skip_if_exists_file_absent(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """File absent even though pattern matches → written normally, no warning."""
    warnings: list[str] = []
    monkeypatch.setattr(
        "zenit.migrate.migrate.warn",
        lambda msg: warnings.append(msg),
    )
    from zenit.migrate.migrate import _apply_skip_if_exists
    from zenit.schema.models import FileContribution

    contributions = [FileContribution(dest="NEW_FILE.md")]
    result = _apply_skip_if_exists(contributions, ["NEW_FILE.md"], tmp_path, {})
    assert len(result) == 1
    assert result[0].dest == "NEW_FILE.md"
    assert len(warnings) == 0


def test_apply_skip_if_exists_pattern_no_match(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """File exists but pattern doesn't match → written normally."""
    warnings: list[str] = []
    monkeypatch.setattr(
        "zenit.migrate.migrate.warn",
        lambda msg: warnings.append(msg),
    )
    (tmp_path / "CHANGELOG.md").write_text("existing")

    from zenit.migrate.migrate import _apply_skip_if_exists
    from zenit.schema.models import FileContribution

    contributions = [FileContribution(dest="CHANGELOG.md")]
    result = _apply_skip_if_exists(contributions, ["README.md"], tmp_path, {})
    assert len(result) == 1
    assert result[0].dest == "CHANGELOG.md"
    assert len(warnings) == 0


def test_apply_skip_if_exists_glob_pattern(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Glob pattern matches existing file → skipped."""
    warnings: list[str] = []
    monkeypatch.setattr(
        "zenit.migrate.migrate.warn",
        lambda msg: warnings.append(msg),
    )
    sub = tmp_path / "odoo" / "custom" / "dependencies"
    sub.mkdir(parents=True)
    (sub / "external.txt").write_text("existing")

    from zenit.migrate.migrate import _apply_skip_if_exists
    from zenit.schema.models import FileContribution

    contributions = [FileContribution(dest="odoo/custom/dependencies/external.txt")]
    result = _apply_skip_if_exists(
        contributions, ["odoo/custom/dependencies/*.txt"], tmp_path, {}
    )
    assert len(result) == 0
    assert len(warnings) == 1


def test_apply_skip_if_exists_no_patterns(
    tmp_path: Path,
) -> None:
    """No skip_if_exists patterns → all files written normally."""
    from zenit.migrate.migrate import _apply_skip_if_exists
    from zenit.schema.models import FileContribution

    contributions = [
        FileContribution(dest="a.txt"),
        FileContribution(dest="b.txt"),
    ]
    result = _apply_skip_if_exists(contributions, [], tmp_path, {})
    assert len(result) == 2


def test_apply_skip_if_exists_renders_jinja_dest(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Jinja in destination path is rendered before skip check."""
    warnings: list[str] = []
    monkeypatch.setattr(
        "zenit.migrate.migrate.warn",
        lambda msg: warnings.append(msg),
    )
    (tmp_path / "myproj.conf").write_text("existing")

    from zenit.migrate.migrate import _apply_skip_if_exists
    from zenit.schema.models import FileContribution

    contributions = [FileContribution(dest="{{ name }}.conf")]
    result = _apply_skip_if_exists(
        contributions, ["*.conf"], tmp_path, {"name": "myproj"}
    )
    assert len(result) == 0
    assert len(warnings) == 1


# ── _messages display ──────────────────────────────────────────────────────────


def test_run_migration_message_before_copy(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    template_dir = tmp_path / "copier-template"
    template_dir.mkdir()
    (template_dir / "copier.yml").write_text(
        yaml.dump(
            {
                "project_name": {"type": "str", "help": "Project name"},
                "_message_before_copy": "Setting up {{ project_name }}...",
            }
        ),
        encoding="utf-8",
    )
    (template_dir / "README.md.jinja").write_text(
        "# {{ project_name }}\n", encoding="utf-8"
    )

    monkeypatch.chdir(tmp_path)
    run_migration(str(template_dir), name="myproj")

    captured = capsys.readouterr()
    assert "Setting up myproj..." in captured.out


def test_run_migration_message_after_copy(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    template_dir = tmp_path / "copier-template"
    template_dir.mkdir()
    (template_dir / "copier.yml").write_text(
        yaml.dump(
            {
                "project_name": {"type": "str", "help": "Project name"},
                "_message_after_copy": "Done! cd {{ project_name }} && make install",
            }
        ),
        encoding="utf-8",
    )
    (template_dir / "README.md.jinja").write_text(
        "# {{ project_name }}\n", encoding="utf-8"
    )

    monkeypatch.chdir(tmp_path)
    run_migration(str(template_dir), name="myproj")

    captured = capsys.readouterr()
    assert "Done! cd myproj && make install" in captured.out


def test_run_migration_no_messages(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    template_dir = tmp_path / "copier-template"
    template_dir.mkdir()
    (template_dir / "copier.yml").write_text(
        yaml.dump({"project_name": {"type": "str", "help": "Project name"}}),
        encoding="utf-8",
    )
    (template_dir / "README.md.jinja").write_text(
        "# {{ project_name }}\n", encoding="utf-8"
    )

    monkeypatch.chdir(tmp_path)
    run_migration(str(template_dir), name="myproj")

    captured = capsys.readouterr()
    assert "Template message" not in captured.out


def test_run_migration_message_with_jinja(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    template_dir = tmp_path / "copier-template"
    template_dir.mkdir()
    (template_dir / "copier.yml").write_text(
        yaml.dump(
            {
                "project_name": {"type": "str", "help": "Project name"},
                "version": {"type": "str", "default": "1.0"},
                "_message_before_copy": "Version: {{ version }}",
            }
        ),
        encoding="utf-8",
    )
    (template_dir / "README.md.jinja").write_text(
        "# {{ project_name }}\n", encoding="utf-8"
    )

    monkeypatch.chdir(tmp_path)
    run_migration(str(template_dir), name="myproj")

    captured = capsys.readouterr()
    assert "Version: 1.0" in captured.out


def test_parse_copier_yml_messages(tmp_path: Path) -> None:
    """_message_before_copy and _message_after_copy are parsed correctly."""
    path = tmp_path / "copier.yml"
    path.write_text(
        yaml.dump(
            {
                "name": {"type": "str", "help": "Name"},
                "_message_before_copy": "Before",
                "_message_after_copy": "After",
            }
        ),
        encoding="utf-8",
    )
    config = parse_copier_yml(path)
    assert config.message_before_copy == "Before"
    assert config.message_after_copy == "After"


def test_run_migration_skips_copier_internal_answers_file(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    template_dir = tmp_path / "copier-template"
    template_dir.mkdir()
    (template_dir / "copier.yml").write_text(
        yaml.dump(
            {
                "project_name": {"type": "str", "help": "Project name"},
            }
        ),
        encoding="utf-8",
    )
    (template_dir / "{{ _copier_conf.answers_file }}.jinja").write_text(
        "{{ _copier_answers | to_nice_yaml }}\n",
        encoding="utf-8",
    )
    (template_dir / "README.md.jinja").write_text(
        "# {{ project_name }}\n",
        encoding="utf-8",
    )

    monkeypatch.chdir(tmp_path)

    result = run_migration(str(template_dir), name="myproj")

    assert (result.project_dir / "README.md").exists()
    assert not (result.project_dir / ".copier-answers.yml").exists()


# ── Secret and YAML question types (Step 5) ─────────────────────────────────────


def test_mask_secrets_replaces_value() -> None:
    """_mask_secrets replaces secret values with ******."""
    from zenit.migrate.migrate import _mask_secrets

    result = _mask_secrets(
        "api_key=sk-1234, other=foo",
        {"db_password": "sk-1234"},
        {"db_password"},
    )
    assert "sk-1234" not in result
    assert "******" in result
    assert "other=foo" in result


def test_mask_secrets_multiple() -> None:
    """Multiple secret values are all masked."""
    from zenit.migrate.migrate import _mask_secrets

    result = _mask_secrets(
        "a=secret1, b=secret2",
        {"pw1": "secret1", "pw2": "secret2"},
        {"pw1", "pw2"},
    )
    assert "secret1" not in result
    assert "secret2" not in result
    assert result.count("******") == 2


def test_mask_secrets_no_match() -> None:
    """Text with no secret values is returned unchanged."""
    from zenit.migrate.migrate import _mask_secrets

    result = _mask_secrets(
        "hello world",
        {"pw": "secret"},
        {"pw"},
    )
    assert result == "hello world"


def test_mask_secrets_empty_value() -> None:
    """Empty string value is not masked."""
    from zenit.migrate.migrate import _mask_secrets

    result = _mask_secrets(
        "pw=",
        {"pw": ""},
        {"pw"},
    )
    assert result == "pw="


def test_mask_secrets_non_string_value() -> None:
    """Non-string value in render_vars is skipped."""
    from zenit.migrate.migrate import _mask_secrets

    result = _mask_secrets(
        "port=5432",
        {"port": 5432},
        {"port"},
    )
    assert result == "port=5432"


def test_resolve_secret_noninteractive() -> None:
    """Secret value is resolved from -D override."""
    config = CopierConfig(
        questions=[CopierQuestion(name="api_key", type=QuestionType.SECRET)],
    )
    from zenit.migrate.migrate import _resolve_answers_noninteractive

    answers = _resolve_answers_noninteractive(config, {"api_key": "sk-abc"})
    assert answers.render_vars["api_key"] == "sk-abc"


def test_resolve_yaml_noninteractive() -> None:
    """YAML default is coerced to a Python object."""
    config = CopierConfig(
        questions=[
            CopierQuestion(
                name="config",
                type=QuestionType.YAML,
                default="key: value",
            )
        ],
    )
    from zenit.migrate.migrate import _resolve_answers_noninteractive

    answers = _resolve_answers_noninteractive(config, {})
    assert isinstance(answers.render_vars["config"], dict)
    assert answers.render_vars["config"]["key"] == "value"


def test_resolve_secret_default_coerces_as_string() -> None:
    """Secret default is treated as plain string."""
    config = CopierConfig(
        questions=[
            CopierQuestion(
                name="api_key", type=QuestionType.SECRET, default="default_key"
            ),
        ],
    )
    from zenit.migrate.migrate import _resolve_answers_noninteractive

    answers = _resolve_answers_noninteractive(config, {})
    assert answers.render_vars["api_key"] == "default_key"


# ── Rendered-file tracking for marker scan (Step 6) ────────────────────────────


def test_scan_unresolved_markers_flags_rendered_file(tmp_path: Path) -> None:
    """File with unresolved var is flagged."""
    from zenit.migrate.migrate import _scan_for_unresolved_markers

    d = tmp_path / "proj"
    d.mkdir()
    (d / "config.py").write_text("NAME = {{ unknown_var }}\n")
    flagged = _scan_for_unresolved_markers(d, {"config.py"})
    assert "config.py" in flagged


def test_scan_unresolved_markers_skips_static_copy(tmp_path: Path) -> None:
    """Static-copied GHA file is not scanned, so not flagged."""
    from zenit.migrate.migrate import _scan_for_unresolved_markers

    d = tmp_path / "proj"
    d.mkdir()
    (d / "ci.yml").write_text("on: push\n  ${{ github.ref }}")
    flagged = _scan_for_unresolved_markers(d, set())  # not in rendered set
    assert "ci.yml" not in flagged


def test_scan_unresolved_markers_rendered_and_resolved(tmp_path: Path) -> None:
    """Rendered file with all vars resolved is not flagged."""
    from zenit.migrate.migrate import _scan_for_unresolved_markers

    d = tmp_path / "proj"
    d.mkdir()
    (d / "app.py").write_text("NAME = myproj\n")
    flagged = _scan_for_unresolved_markers(d, {"app.py"})
    assert "app.py" not in flagged


def test_scan_unresolved_markers_block_tag(tmp_path: Path) -> None:
    """Unresolved block tag is flagged."""
    from zenit.migrate.migrate import _scan_for_unresolved_markers

    d = tmp_path / "proj"
    d.mkdir()
    (d / "template.txt").write_text("{% if x %}hello{% endif %}")
    flagged = _scan_for_unresolved_markers(d, {"template.txt"})
    assert "template.txt" in flagged


def test_run_migration_tracks_rendered_files(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Rendered file with unresolved marker is warned at migration end."""
    template_dir = tmp_path / "copier-template"
    template_dir.mkdir()
    (template_dir / "copier.yml").write_text(
        yaml.dump({"name": {"type": "str", "help": "Name"}}),
        encoding="utf-8",
    )
    (template_dir / "README.md.jinja").write_text(
        "Hello {{ name }}\n", encoding="utf-8"
    )
    (template_dir / "LICENSE").write_text("{{ unknown_var }}\n", encoding="utf-8")

    monkeypatch.chdir(tmp_path)

    warnings: list[str] = []
    monkeypatch.setattr(
        "zenit.migrate.migrate.warn",
        lambda msg: warnings.append(msg),
    )

    from zenit.migrate.migrate import run_migration

    run_migration(str(template_dir), name="myproj")

    # README.md was rendered (no .jinja → stripped), LICENSE was static copy
    # Only rendered files are scanned, so LICENSE should not be flagged
    unresolved_warnings = [
        w for w in warnings if "unresolved" in w.lower() or "marker" in w.lower()
    ]
    # README.md has no unresolved markers (name is provided)
    assert len(unresolved_warnings) == 0


def test_run_migration_warns_unresolved_markers(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Rendered file with residual Jinja2 markers triggers warning."""
    template_dir = tmp_path / "copier-template"
    template_dir.mkdir()
    (template_dir / "copier.yml").write_text(
        yaml.dump({"name": {"type": "str", "help": "Name"}}),
        encoding="utf-8",
    )
    (template_dir / "README.md.jinja").write_text(
        "Hello {{ name }} {% unknown_tag %}\n", encoding="utf-8"
    )

    monkeypatch.chdir(tmp_path)

    warnings: list[str] = []
    monkeypatch.setattr(
        "zenit.migrate.migrate.warn",
        lambda msg: warnings.append(msg),
    )

    from zenit.migrate.migrate import run_migration

    run_migration(str(template_dir), name="myproj")

    unresolved_warnings = [
        w for w in warnings if "unresolved" in w.lower() or "marker" in w.lower()
    ]
    assert len(unresolved_warnings) > 0
