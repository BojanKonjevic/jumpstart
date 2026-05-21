"""Tests for zenit.assembler — collecting and merging contributions."""

from zenit.core.collect import collect_all
from zenit.schema.models import (
    AddonConfig,
    ComposeService,
    Contributions,
    EnvVar,
    FileContribution,
    Injection,
    TemplateConfig,
)

# ── Helpers ───────────────────────────────────────────────────────────────────


def _template(
    deps: list[str] | None = None,
    dev_deps: list[str] | None = None,
    files: list[FileContribution] | None = None,
    just_recipes: list[str] | None = None,
    injections: list[Injection] | None = None,
    compose_services: list[ComposeService] | None = None,
    compose_volumes: list[str] | None = None,
    env_vars: list[EnvVar] | None = None,
    dirs: list[str] | None = None,
) -> TemplateConfig:
    return TemplateConfig(
        id="blank",
        description="test",
        deps=deps or [],
        dev_deps=dev_deps or [],
        files=files or [],
        just_recipes=just_recipes or [],
        injections=injections or [],
        compose_services=compose_services or [],
        compose_volumes=compose_volumes or [],
        env_vars=env_vars or [],
        dirs=dirs or [],
    )


def _addon(
    id: str = "myaddon",
    deps: list[str] | None = None,
    dev_deps: list[str] | None = None,
    files: list[FileContribution] | None = None,
    just_recipes: list[str] | None = None,
    injections: list[Injection] | None = None,
    compose_services: list[ComposeService] | None = None,
    compose_volumes: list[str] | None = None,
    env_vars: list[EnvVar] | None = None,
    dirs: list[str] | None = None,
) -> AddonConfig:
    return AddonConfig(
        id=id,
        description="test addon",
        deps=deps or [],
        dev_deps=dev_deps or [],
        files=files or [],
        just_recipes=just_recipes or [],
        injections=injections or [],
        compose_services=compose_services or [],
        compose_volumes=compose_volumes or [],
        env_vars=env_vars or [],
        dirs=dirs or [],
    )


# ── deps ──────────────────────────────────────────────────────────────────────


def test_collect_all_empty():
    result = collect_all(_template(), [])
    assert isinstance(result, Contributions)
    assert result.deps == []
    assert result.dev_deps == []
    assert result.files == []
    assert result.just_recipes == []
    assert result.injections == []


def test_collect_all_template_deps_in_contributions():
    result = collect_all(_template(deps=["fastapi", "uvicorn"]), [])
    assert "fastapi" in result.deps
    assert "uvicorn" in result.deps


def test_collect_all_addon_deps_in_contributions():
    result = collect_all(_template(), [_addon(deps=["redis>=5", "hiredis"])])
    assert "redis>=5" in result.deps
    assert "hiredis" in result.deps


def test_collect_all_multiple_addon_deps_merged():
    addons = [
        _addon(id="redis", deps=["redis>=5"]),
        _addon(id="celery", deps=["celery[redis]>=5"]),
    ]
    result = collect_all(_template(), addons)
    assert "redis>=5" in result.deps
    assert "celery[redis]>=5" in result.deps


def test_collect_all_dev_deps_from_addon():
    result = collect_all(_template(), [_addon(dev_deps=["fakeredis"])])
    assert "fakeredis" in result.dev_deps


# ── files ─────────────────────────────────────────────────────────────────────


def test_collect_all_template_files_in_contributions():
    fc = FileContribution(dest="src/{{pkg_name}}/main.py", content="")
    result = collect_all(_template(files=[fc]), [])
    assert fc in result.files


def test_collect_all_addon_files_in_contributions():
    fc = FileContribution(dest="src/{{pkg_name}}/integrations/redis.py", content="")
    result = collect_all(_template(), [_addon(files=[fc])])
    assert fc in result.files


def test_collect_all_files_from_multiple_addons():
    fc1 = FileContribution(dest="redis.py", content="")
    fc2 = FileContribution(dest="sentry.py", content="")
    result = collect_all(
        _template(),
        [
            _addon(id="redis", files=[fc1]),
            _addon(id="sentry", files=[fc2]),
        ],
    )
    assert fc1 in result.files
    assert fc2 in result.files


# ── just_recipes ──────────────────────────────────────────────────────────────


def test_collect_all_template_just_recipes_not_in_contributions():
    # Template just_recipes are NOT put into contributions.just_recipes —
    # generate_all reads them directly from template_cfg to avoid
    # double-rendering during deduplication.
    result = collect_all(_template(just_recipes=["run:\n    python -m app"]), [])
    assert result.just_recipes == []


def test_collect_all_addon_just_recipes_in_contributions():
    result = collect_all(
        _template(),
        [_addon(just_recipes=["redis-up:\n    docker compose up -d redis"])],
    )
    assert "redis-up:\n    docker compose up -d redis" in result.just_recipes


def test_collect_all_just_recipes_from_multiple_addons():
    result = collect_all(
        _template(),
        [
            _addon(
                id="redis", just_recipes=["redis-up:\n    docker compose up -d redis"]
            ),
            _addon(
                id="docker", just_recipes=["docker-up:\n    docker compose up --build"]
            ),
        ],
    )
    assert len(result.just_recipes) == 2


# ── injections ────────────────────────────────────────────────────────────────


def test_collect_all_template_injections_get_addon_id_template():
    inj = Injection(point="lifespan_startup", content="    init_sentry()")
    result = collect_all(_template(injections=[inj]), [])
    assert any(i.addon_id == "template" for i in result.injections)


def test_collect_all_addon_injections_get_addon_id():
    inj = Injection(point="settings_fields", content='    redis_url: str = ""')
    result = collect_all(_template(), [_addon(id="redis", injections=[inj])])
    assert any(i.addon_id == "redis" for i in result.injections)


def test_collect_all_injections_from_multiple_addons():
    inj1 = Injection(point="settings_fields", content='    redis_url: str = ""')
    inj2 = Injection(point="lifespan_startup", content="    init_sentry()")
    result = collect_all(
        _template(),
        [
            _addon(id="redis", injections=[inj1]),
            _addon(id="sentry", injections=[inj2]),
        ],
    )
    addon_ids = {i.addon_id for i in result.injections}
    assert "redis" in addon_ids
    assert "sentry" in addon_ids


# ── compose ───────────────────────────────────────────────────────────────────


def test_collect_all_compose_services_from_addon():
    svc = ComposeService(name="redis", image="redis:7-alpine")
    result = collect_all(_template(), [_addon(compose_services=[svc])])
    assert svc in result.compose_services


def test_collect_all_compose_volumes_from_addon():
    result = collect_all(_template(), [_addon(compose_volumes=["redis-data"])])
    assert "redis-data" in result.compose_volumes


def test_collect_all_compose_services_from_template():
    svc = ComposeService(name="db", image="postgres:16")
    result = collect_all(_template(compose_services=[svc]), [])
    assert svc in result.compose_services


# ── env_vars ──────────────────────────────────────────────────────────────────


def test_collect_all_env_vars_from_addon():
    ev = EnvVar(key="REDIS_URL", default="redis://localhost:6379/0")
    result = collect_all(_template(), [_addon(env_vars=[ev])])
    assert ev in result.env_vars


def test_collect_all_env_vars_from_template():
    ev = EnvVar(key="DATABASE_URL", default="postgresql://localhost/mydb")
    result = collect_all(_template(env_vars=[ev]), [])
    assert ev in result.env_vars


# ── dirs ──────────────────────────────────────────────────────────────────────


def test_collect_all_dirs_from_template():
    result = collect_all(_template(dirs=["src/{{pkg_name}}", "tests"]), [])
    assert "src/{{pkg_name}}" in result.dirs
    assert "tests" in result.dirs


def test_collect_all_dirs_from_addon():
    result = collect_all(
        _template(),
        [_addon(dirs=["src/{{pkg_name}}/db", "alembic/versions"])],
    )
    assert "src/{{pkg_name}}/db" in result.dirs
    assert "alembic/versions" in result.dirs


# ── addon_configs stored ──────────────────────────────────────────────────────


def test_collect_all_stores_addon_configs():
    addon = _addon(id="redis")
    result = collect_all(_template(), [addon])
    assert addon in result._addon_configs
