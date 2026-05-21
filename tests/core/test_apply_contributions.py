"""Integration tests for apply_contributions() → manifest recording.

Verifies that apply_contributions() correctly records every category of
injected item in the manifest — Python blocks with accurate fingerprints,
env entries, compose services/volumes, dependencies, and just recipes.

Tested invariants:
  - Every Python injection produces a ManifestBlock with all fields populated.
  - The stored fingerprint matches bytes on disk at the recorded line range.
  - Env, compose, dep, and recipe entries carry correct source/addon metadata.
  - Running apply_contributions twice produces no duplicate manifest entries.
  - Injections for a missing file are silently skipped (no block recorded).
"""

from __future__ import annotations

from pathlib import Path

from zenit.core.apply import apply_contributions
from zenit.core.context import Context
from zenit.core.manifest import fingerprint as _fp
from zenit.core.manifest import read_manifest
from zenit.core.render import build_render_vars
from zenit.schema.models import (
    AddonConfig,
    ComposeService,
    Contributions,
    EnvVar,
    Injection,
    InjectionPoint,
    LocatorSpec,
)

# ── helpers ───────────────────────────────────────────────────────────────────

_ZENIT_ROOT = Path(__file__).parent.parent.parent / "src" / "zenit"


def _ctx(tmp_path: Path, name: str = "myapp") -> Context:
    project_dir = tmp_path / name
    project_dir.mkdir()
    return Context(
        name=name,
        pkg_name=name.replace("-", "_"),
        template="blank",
        addons=[],
        zenit_root=_ZENIT_ROOT,
        project_dir=project_dir,
    )


def _render_vars(ctx: Context) -> dict[str, object]:
    return build_render_vars(
        name=ctx.name,
        pkg_name=ctx.pkg_name,
        template=ctx.template,
        secret_key="test-secret",
    )


def _injection_points(
    *items: tuple[str, str, str, dict[str, object]],
) -> dict[str, InjectionPoint]:
    """Build a minimal injection_points dict.

    Each item is (point_name, file_template, locator_name, locator_args).
    """
    return {
        name: InjectionPoint(
            file=file_tpl,
            locator=LocatorSpec(name=loc_name, args=loc_args),
        )
        for name, file_tpl, loc_name, loc_args in items
    }


def _addon(
    addon_id: str,
    *,
    injections: list[Injection] | None = None,
    env_vars: list[EnvVar] | None = None,
    compose_services: list[ComposeService] | None = None,
    compose_volumes: list[str] | None = None,
    deps: list[str] | None = None,
    dev_deps: list[str] | None = None,
    just_recipes: list[str] | None = None,
) -> AddonConfig:
    return AddonConfig(
        id=addon_id,
        description="",
        injections=injections or [],
        env_vars=env_vars or [],
        compose_services=compose_services or [],
        compose_volumes=compose_volumes or [],
        deps=deps or [],
        dev_deps=dev_deps or [],
        just_recipes=just_recipes or [],
    )


# ── Python block recording ────────────────────────────────────────────────────


def test_apply_records_python_block_with_all_fields(tmp_path: Path) -> None:
    ctx = _ctx(tmp_path)
    # Create a Python file for injection to land in
    target = ctx.project_dir / "src" / "myapp" / "settings.py"
    target.parent.mkdir(parents=True)
    target.write_text(
        'class Settings:\n    db_url: str = "postgresql://localhost"\n',
        encoding="utf-8",
    )

    addon = _addon(
        "redis",
        injections=[
            Injection(
                point="settings_fields",
                content='    redis_url: str = "redis://localhost"\n',
                addon_id="redis",
            )
        ],
    )
    contributions = Contributions(injections=addon.injections, _addon_configs=[addon])
    injection_points = _injection_points(
        (
            "settings_fields",
            "src/{{pkg_name}}/settings.py",
            "after_last_class_attribute",
            {"class_name": "Settings"},
        ),
    )

    apply_contributions(ctx, contributions, injection_points, _render_vars(ctx))

    manifest = read_manifest(ctx.project_dir)
    assert len(manifest.python_blocks) == 1
    block = manifest.python_blocks[0]

    assert block.addon == "redis"
    assert block.point == "settings_fields"
    assert block.file == "src/myapp/settings.py"
    assert "-" in block.lines  # e.g. "3-3"
    assert block.fingerprint.startswith("sha256:")
    assert block.fingerprint_normalised.startswith("sha256:")
    assert block.locator["name"] == "after_last_class_attribute"
    assert block.locator["args"] == {"class_name": "Settings"}


def test_apply_fingerprint_matches_written_content(tmp_path: Path) -> None:
    ctx = _ctx(tmp_path)
    target = ctx.project_dir / "src" / "myapp" / "settings.py"
    target.parent.mkdir(parents=True)
    target.write_text(
        'class Settings:\n    db_url: str = "postgresql://localhost"\n',
        encoding="utf-8",
    )

    injection_text = '    redis_url: str = "redis://localhost"\n'
    addon = _addon(
        "redis",
        injections=[
            Injection(point="settings_fields", content=injection_text, addon_id="redis")
        ],
    )
    contributions = Contributions(injections=addon.injections, _addon_configs=[addon])
    injection_points = _injection_points(
        (
            "settings_fields",
            "src/{{pkg_name}}/settings.py",
            "after_last_class_attribute",
            {"class_name": "Settings"},
        ),
    )

    apply_contributions(ctx, contributions, injection_points, _render_vars(ctx))

    manifest = read_manifest(ctx.project_dir)
    block = manifest.python_blocks[0]

    # Re-extract the exact bytes on disk at the recorded line range
    start, end = (int(x) for x in block.lines.split("-"))
    disk_lines = target.read_text(encoding="utf-8").splitlines(keepends=True)
    on_disk_text = "".join(disk_lines[start - 1 : end])

    expected_fp, _ = _fp(on_disk_text)
    assert block.fingerprint == expected_fp


def test_apply_skips_python_block_for_missing_file(tmp_path: Path) -> None:
    ctx = _ctx(tmp_path)
    # Target file deliberately not created
    addon = _addon(
        "redis",
        injections=[
            Injection(
                point="settings_fields",
                content='    redis_url: str = "redis://localhost"\n',
                addon_id="redis",
            )
        ],
    )
    contributions = Contributions(injections=addon.injections, _addon_configs=[addon])
    injection_points = _injection_points(
        (
            "settings_fields",
            "src/{{pkg_name}}/settings.py",
            "after_last_class_attribute",
            {"class_name": "Settings"},
        ),
    )

    apply_contributions(ctx, contributions, injection_points, _render_vars(ctx))

    manifest = read_manifest(ctx.project_dir)
    assert manifest.python_blocks == []


# ── Non-Python manifest recording ─────────────────────────────────────────────


def test_apply_records_env_entry(tmp_path: Path) -> None:
    ctx = _ctx(tmp_path)
    (ctx.project_dir / ".env").write_text("", encoding="utf-8")

    addon = _addon(
        "redis", env_vars=[EnvVar(key="REDIS_URL", default="redis://localhost")]
    )
    contributions = Contributions(_addon_configs=[addon], env_vars=addon.env_vars)

    apply_contributions(ctx, contributions, {}, _render_vars(ctx))

    manifest = read_manifest(ctx.project_dir)
    entry = next((e for e in manifest.env if e.key == "REDIS_URL"), None)
    assert entry is not None
    assert entry.source == "addon"
    assert entry.addon == "redis"


def test_apply_records_compose_service_and_volume(tmp_path: Path) -> None:
    ctx = _ctx(tmp_path)
    (ctx.project_dir / "compose.yml").write_text(
        "services:\n  app:\n    image: myapp\n", encoding="utf-8"
    )

    svc = ComposeService(name="redis", image="redis:7-alpine")
    addon = _addon("redis", compose_services=[svc], compose_volumes=["redis-data"])
    contributions = Contributions(
        _addon_configs=[addon],
        compose_services=addon.compose_services,
        compose_volumes=addon.compose_volumes,
    )

    apply_contributions(ctx, contributions, {}, _render_vars(ctx))

    manifest = read_manifest(ctx.project_dir)

    svc_entry = next((s for s in manifest.compose_services if s.name == "redis"), None)
    assert svc_entry is not None
    assert svc_entry.source == "addon"
    assert svc_entry.addon == "redis"

    vol_entry = next(
        (v for v in manifest.compose_volumes if v.name == "redis-data"), None
    )
    assert vol_entry is not None
    assert vol_entry.source == "addon"
    assert vol_entry.addon == "redis"


def test_apply_records_dependency_entry(tmp_path: Path) -> None:
    ctx = _ctx(tmp_path)
    addon = _addon("redis", deps=["redis>=5"], dev_deps=["fakeredis"])
    contributions = Contributions(_addon_configs=[addon])

    apply_contributions(ctx, contributions, {}, _render_vars(ctx))

    manifest = read_manifest(ctx.project_dir)

    runtime = next((d for d in manifest.dependencies if d.package == "redis"), None)
    assert runtime is not None
    assert runtime.source == "addon"
    assert runtime.addon == "redis"
    assert runtime.dev is False

    dev = next((d for d in manifest.dependencies if d.package == "fakeredis"), None)
    assert dev is not None
    assert dev.source == "addon"
    assert dev.addon == "redis"
    assert dev.dev is True


def test_apply_records_just_recipe(tmp_path: Path) -> None:
    ctx = _ctx(tmp_path)
    addon = _addon("docker", just_recipes=["docker-up:\n    docker compose up -d\n"])
    contributions = Contributions(_addon_configs=[addon])

    apply_contributions(ctx, contributions, {}, _render_vars(ctx))

    manifest = read_manifest(ctx.project_dir)
    recipe = next((r for r in manifest.just_recipes if r.name == "docker-up"), None)
    assert recipe is not None
    assert recipe.source == "addon"
    assert recipe.addon == "docker"


# ── Idempotency ───────────────────────────────────────────────────────────────


def test_apply_idempotent(tmp_path: Path) -> None:
    """Running apply_contributions twice with the same contributions produces
    no duplicate manifest entries — the add_* helpers deduplicate."""
    ctx = _ctx(tmp_path)
    (ctx.project_dir / ".env").write_text("", encoding="utf-8")

    addon = _addon(
        "redis",
        env_vars=[EnvVar(key="REDIS_URL", default="redis://localhost")],
        deps=["redis>=5"],
    )
    contributions = Contributions(
        _addon_configs=[addon],
        env_vars=addon.env_vars,
    )

    apply_contributions(ctx, contributions, {}, _render_vars(ctx))
    apply_contributions(ctx, contributions, {}, _render_vars(ctx))

    manifest = read_manifest(ctx.project_dir)
    redis_url_entries = [e for e in manifest.env if e.key == "REDIS_URL"]
    assert len(redis_url_entries) == 1

    redis_dep_entries = [d for d in manifest.dependencies if d.package == "redis"]
    assert len(redis_dep_entries) == 1
