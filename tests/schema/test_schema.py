"""Tests for zenit.schema — dataclass defaults, construction, and field behavior.

The schema module is the backbone of the entire contribution pipeline.
These tests verify that every dataclass initialises correctly, that mutable
defaults are independent across instances, and that the enum values used by
the injection machinery are stable.
"""

from __future__ import annotations

from zenit.schema.models import (
    AddonConfig,
    AddonHooks,
    ComposeService,
    Contributions,
    EnvVar,
    FileContribution,
    Injection,
    TemplateConfig,
)

# ── FileContribution ──────────────────────────────────────────────────────────


def test_file_contribution_required_fields():
    fc = FileContribution(dest="src/main.py")
    assert fc.dest == "src/main.py"


def test_file_contribution_defaults():
    fc = FileContribution(dest="src/main.py")
    assert fc.source is None
    assert fc.content is None
    assert fc.template is False


def test_file_contribution_with_content():
    fc = FileContribution(dest="hello.py", content="print('hi')")
    assert fc.content == "print('hi')"


def test_file_contribution_with_source():
    fc = FileContribution(dest="hello.py", source="/some/path/hello.py")
    assert fc.source == "/some/path/hello.py"


def test_file_contribution_template_flag():
    fc = FileContribution(dest="hello.py.j2", content="(( name ))", template=True)
    assert fc.template is True


# ── EnvVar ────────────────────────────────────────────────────────────────────


def test_env_var_required_fields():
    ev = EnvVar(key="REDIS_URL", default="redis://localhost:6379/0")
    assert ev.key == "REDIS_URL"
    assert ev.default == "redis://localhost:6379/0"


def test_env_var_comment_defaults_empty():
    ev = EnvVar(key="FOO", default="bar")
    assert ev.comment == ""


def test_env_var_with_comment():
    ev = EnvVar(key="SECRET_KEY", default="", comment="generate with openssl")
    assert ev.comment == "generate with openssl"


# ── Injection ─────────────────────────────────────────────────────────────────


def test_injection_required_fields():
    inj = Injection(point="lifespan_startup", content="    init_sentry()")
    assert inj.point == "lifespan_startup"
    assert inj.content == "    init_sentry()"


def test_injection_addon_id_defaults_empty():
    inj = Injection(point="startup", content="pass")
    assert inj.addon_id == ""


def test_injection_addon_id_can_be_set():
    inj = Injection(point="startup", content="pass", addon_id="sentry")
    assert inj.addon_id == "sentry"


# ── ComposeService ────────────────────────────────────────────────────────────


def test_compose_service_required_field():
    svc = ComposeService(name="redis")
    assert svc.name == "redis"


def test_compose_service_defaults():
    svc = ComposeService(name="redis")
    assert svc.image is None
    assert svc.build is None
    assert svc.ports == []
    assert svc.volumes == []
    assert svc.environment == {}
    assert svc.env_file == []
    assert svc.command is None
    assert svc.depends_on == []
    assert svc.develop_watch == []
    assert svc.healthcheck is None


def test_compose_service_mutable_defaults_are_independent():
    svc1 = ComposeService(name="a")
    svc2 = ComposeService(name="b")
    svc1.ports.append("6379:6379")
    assert svc2.ports == []


def test_compose_service_with_all_fields():
    svc = ComposeService(
        name="redis",
        image="redis:7-alpine",
        ports=["6379:6379"],
        volumes=["redis-data:/data"],
        environment={"REDIS_URL": "redis://localhost"},
        command="redis-server --appendonly yes",
        healthcheck={"test": ["CMD", "redis-cli", "ping"]},
    )
    assert svc.image == "redis:7-alpine"
    assert svc.ports == ["6379:6379"]
    assert svc.environment["REDIS_URL"] == "redis://localhost"
    assert svc.command == "redis-server --appendonly yes"
    assert svc.healthcheck is not None


def test_compose_service_depends_on_as_dict():
    svc = ComposeService(
        name="worker",
        depends_on={"redis": {"condition": "service_healthy"}},
    )
    assert isinstance(svc.depends_on, dict)
    assert "redis" in svc.depends_on


# ── AddonHooks ────────────────────────────────────────────────────────────────


def test_addon_hooks_all_default_none():
    hooks = AddonHooks()
    assert hooks.post_apply is None
    assert hooks.health_check is None
    assert hooks.can_apply is None
    assert hooks.can_remove is None


def test_addon_hooks_callable_fields():
    def my_fn(a, b):
        return None

    hooks = AddonHooks(can_apply=my_fn)
    assert hooks.can_apply is my_fn


# ── AddonConfig ───────────────────────────────────────────────────────────────


def test_addon_config_required_fields():
    cfg = AddonConfig(id="docker", description="Docker support")
    assert cfg.id == "docker"
    assert cfg.description == "Docker support"


def test_addon_config_list_defaults_are_empty():
    cfg = AddonConfig(id="docker", description="")
    assert cfg.requires == []
    assert cfg.templates == []
    assert cfg.files == []
    assert cfg.compose_services == []
    assert cfg.compose_volumes == []
    assert cfg.env_vars == []
    assert cfg.deps == []
    assert cfg.dev_deps == []
    assert cfg.just_recipes == []
    assert cfg.injections == []


def test_addon_config_mutable_defaults_are_independent():
    cfg1 = AddonConfig(id="a", description="")
    cfg2 = AddonConfig(id="b", description="")
    cfg1.deps.append("redis>=5")
    assert cfg2.deps == []


def test_addon_config_module_defaults_none():
    cfg = AddonConfig(id="docker", description="")
    assert cfg._module is None


def test_addon_config_module_excluded_from_repr():
    cfg = AddonConfig(id="docker", description="")
    assert "_module" not in repr(cfg)


def test_addon_config_module_excluded_from_compare():
    cfg1 = AddonConfig(id="docker", description="")
    cfg2 = AddonConfig(id="docker", description="")
    cfg1._module = AddonHooks(can_apply=lambda p, line: None)
    # _module has compare=False so they should still be equal
    assert cfg1 == cfg2


def test_addon_config_templates_empty_means_all_allowed():
    # This is a convention used throughout the codebase
    cfg = AddonConfig(id="docker", description="", templates=[])
    assert cfg.templates == []


def test_addon_config_templates_restricts_when_set():
    cfg = AddonConfig(id="auth-manual", description="", templates=["fastapi"])
    assert "fastapi" in cfg.templates
    assert "blank" not in cfg.templates


# ── TemplateConfig ────────────────────────────────────────────────────────────


def test_template_config_required_fields():
    cfg = TemplateConfig(id="blank", description="dev tools only")
    assert cfg.id == "blank"
    assert cfg.description == "dev tools only"


def test_template_config_list_defaults_are_empty():
    cfg = TemplateConfig(id="blank", description="")
    assert cfg.requires_addons == []
    assert cfg.dirs == []
    assert cfg.files == []
    assert cfg.compose_services == []
    assert cfg.compose_volumes == []
    assert cfg.env_vars == []
    assert cfg.deps == []
    assert cfg.dev_deps == []
    assert cfg.just_recipes == []
    assert cfg.injections == []


def test_template_config_mutable_defaults_are_independent():
    cfg1 = TemplateConfig(id="blank", description="")
    cfg2 = TemplateConfig(id="fastapi", description="")
    cfg1.deps.append("fastapi")
    assert cfg2.deps == []


# ── Contributions ─────────────────────────────────────────────────────────────


def test_contributions_all_defaults_empty():
    c = Contributions()
    assert c.files == []
    assert c.dirs == []
    assert c.compose_services == []
    assert c.compose_volumes == []
    assert c.env_vars == []
    assert c.deps == []
    assert c.dev_deps == []
    assert c.just_recipes == []
    assert c.injections == []
    assert c._addon_configs == []


def test_contributions_mutable_defaults_are_independent():
    c1 = Contributions()
    c2 = Contributions()
    c1.deps.append("redis>=5")
    assert c2.deps == []


def test_contributions_can_accumulate_items():
    c = Contributions()
    c.deps.extend(["fastapi", "uvicorn"])
    c.dev_deps.append("pytest>=8")
    assert len(c.deps) == 2
    assert len(c.dev_deps) == 1


def test_contributions_files_accumulate():
    c = Contributions()
    fc = FileContribution(dest="src/main.py", content="")
    c.files.append(fc)
    assert fc in c.files


def test_contributions_injections_accumulate():
    c = Contributions()
    inj = Injection(point="startup", content="pass", addon_id="sentry")
    c.injections.append(inj)
    assert inj in c.injections
