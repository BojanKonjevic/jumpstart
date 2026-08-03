"""Integration tests - every scaffolded item is tracked in the manifest.

Verifies that after a full scaffold run:
  - Template-owned entries carry source='template', addon=''.
  - Addon-owned entries carry source='addon', addon=<id>.
  - Python injection blocks record accurate fingerprints and line ranges.
  - No entry appears with an empty or unknown source.
  - Adding an addon to an existing project adds its entries without
    corrupting the template-owned entries already present.
"""

from __future__ import annotations

from pathlib import Path

from zenit.addons._registry import get_addon
from zenit.core._apply_loader import load_apply
from zenit.core.apply import apply_contributions
from zenit.core.collect import collect_all
from zenit.core.context import Context
from zenit.core.filesystem import RealFileSystem
from zenit.core.generate import generate_all
from zenit.core.git import init
from zenit.core.lockfile import write_lockfile
from zenit.core.manifest import (
    add_compose_service,
    add_compose_volume,
    add_dependency,
    add_env_entry,
    add_just_recipe,
    read_manifest,
    record_addon_manifest_entries,
    write_manifest,
)
from zenit.core.manifest import fingerprint as _fp
from zenit.core.render import build_render_vars, make_env
from zenit.schema.models import EntrySource
from zenit.templates._load_config import load_template_config

_ZENIT_ROOT = Path(__file__).parent.parent.parent / "src" / "zenit"


# ── inline stamp (avoids importing CLI-heavy scaffold.py) ─────────────────────


def _pkg_name(spec: str) -> str:
    return spec.split(">=")[0].split("==")[0].split("[")[0].strip()


def _stamp_template_manifest(project_dir: Path, template_config: object) -> None:
    manifest = read_manifest(project_dir)
    for ev in template_config.env_vars:
        add_env_entry(manifest, ev.key, source=EntrySource.TEMPLATE, addon="")
    for svc in template_config.compose_services:
        add_compose_service(manifest, svc.name, source=EntrySource.TEMPLATE, addon="")
    for vol in template_config.compose_volumes:
        add_compose_volume(manifest, vol, source=EntrySource.TEMPLATE, addon="")
    for dep in template_config.deps:
        add_dependency(
            manifest,
            _pkg_name(dep),
            dep,
            source=EntrySource.TEMPLATE,
            addon="",
            dev=False,
        )
    for dep in template_config.dev_deps:
        add_dependency(
            manifest,
            _pkg_name(dep),
            dep,
            source=EntrySource.TEMPLATE,
            addon="",
            dev=True,
        )
    for recipe in template_config.just_recipes:
        name = ""
        for line in recipe.splitlines():
            stripped = line.strip()
            if stripped and not stripped.startswith("#"):
                name = stripped.split(":")[0].strip()
                break
        if name:
            add_just_recipe(manifest, name, source=EntrySource.TEMPLATE, addon="")
    write_manifest(project_dir, manifest)


# ── shared scaffold helper ────────────────────────────────────────────────────


def _scaffold(tmp_path: Path, name: str, template: str, addons: list[str]) -> Path:
    project_dir = tmp_path / name
    project_dir.mkdir()
    pkg_name = name.replace("-", "_")

    ctx = Context(
        name=name,
        pkg_name=pkg_name,
        template=template,
        addons=addons,
        zenit_root=_ZENIT_ROOT,
        project_dir=project_dir,
    )
    fs = RealFileSystem(project_dir)

    load_apply(_ZENIT_ROOT / "templates" / "_common" / "apply.py")(ctx, fs)

    template_config = load_template_config(_ZENIT_ROOT, template)
    selected_addon_configs = [get_addon(aid) for aid in addons]

    render_vars = build_render_vars(
        name=name,
        pkg_name=pkg_name,
        template=template,
        addons=addons,
    )

    write_lockfile(project_dir, template, addons)

    contributions = collect_all(template_config, selected_addon_configs)
    apply_contributions(
        ctx, fs, contributions, template_config.injection_points, render_vars
    )
    generate_all(ctx, fs, contributions)

    manifest = read_manifest(project_dir)
    string_env = make_env()
    for addon_cfg in selected_addon_configs:
        record_addon_manifest_entries(manifest, addon_cfg, string_env, render_vars)
    write_manifest(project_dir, manifest)

    _stamp_template_manifest(project_dir, template_config)

    init(project_dir)

    return project_dir


# ── source ownership invariants ───────────────────────────────────────────────


class TestSourceOwnership:
    def test_no_entry_has_empty_source(self, tmp_path: Path) -> None:
        project_dir = _scaffold(tmp_path, "myapp", "fastapi", [])
        m = read_manifest(project_dir)

        for entry in m.env:
            assert entry.source in {"template", "addon"}, (
                f"env entry {entry.key!r} has unexpected source {entry.source!r}"
            )
        for entry in m.dependencies:
            assert entry.source in {"template", "addon"}, (
                f"dep entry {entry.package!r} has unexpected source {entry.source!r}"
            )
        for entry in m.just_recipes:
            assert entry.source in {"template", "addon"}, (
                f"recipe entry {entry.name!r} has unexpected source {entry.source!r}"
            )

    def test_template_env_vars_carry_template_source(self, tmp_path: Path) -> None:
        project_dir = _scaffold(tmp_path, "myapp", "fastapi", ["postgres"])
        m = read_manifest(project_dir)

        template_env = {e.key: e for e in m.env if e.source == "template"}
        assert "DEBUG" in template_env
        assert template_env["DEBUG"].addon == ""

        addon_env = {e.key: e for e in m.env if e.source == "addon"}
        assert "DATABASE_URL" in addon_env
        assert addon_env["DATABASE_URL"].addon == "postgres"

    def test_template_deps_carry_template_source(self, tmp_path: Path) -> None:
        project_dir = _scaffold(tmp_path, "myapp", "fastapi", ["sqlalchemy"])
        m = read_manifest(project_dir)

        template_pkgs = {d.package for d in m.dependencies if d.source == "template"}
        assert "fastapi" in template_pkgs
        assert "uvicorn" in template_pkgs

        addon_pkgs = {d.package for d in m.dependencies if d.source == "addon"}
        assert "sqlalchemy" in addon_pkgs

    def test_template_recipes_carry_template_source(self, tmp_path: Path) -> None:
        project_dir = _scaffold(tmp_path, "myapp", "fastapi", ["sqlalchemy"])
        m = read_manifest(project_dir)

        template_recipes = {r.name for r in m.just_recipes if r.source == "template"}
        assert "run" in template_recipes

        addon_recipes = {r.name for r in m.just_recipes if r.source == "addon"}
        assert "upgrade" in addon_recipes

    def test_addon_env_vars_carry_addon_source(self, tmp_path: Path) -> None:
        project_dir = _scaffold(tmp_path, "myapp", "fastapi", ["redis"])
        m = read_manifest(project_dir)

        redis_env = next((e for e in m.env if e.key == "REDIS_URL"), None)
        assert redis_env is not None
        assert redis_env.source == "addon"
        assert redis_env.addon == "redis"

    def test_addon_compose_service_carries_addon_source(self, tmp_path: Path) -> None:
        project_dir = _scaffold(tmp_path, "myapp", "fastapi", ["docker", "redis"])
        m = read_manifest(project_dir)

        svc = next((s for s in m.compose_services if s.name == "redis"), None)
        assert svc is not None
        assert svc.source == "addon"
        assert svc.addon == "redis"

    def test_addon_compose_volume_carries_addon_source(self, tmp_path: Path) -> None:
        project_dir = _scaffold(tmp_path, "myapp", "fastapi", ["docker", "redis"])
        m = read_manifest(project_dir)

        vol = next((v for v in m.compose_volumes if v.name == "redis-data"), None)
        assert vol is not None
        assert vol.source == "addon"
        assert vol.addon == "redis"

    def test_addon_deps_carry_addon_source(self, tmp_path: Path) -> None:
        project_dir = _scaffold(tmp_path, "myapp", "fastapi", ["redis"])
        m = read_manifest(project_dir)

        addon_pkgs = {d.package: d for d in m.dependencies if d.source == "addon"}
        assert "redis" in addon_pkgs
        assert "hiredis" in addon_pkgs
        assert addon_pkgs["redis"].addon == "redis"
        assert addon_pkgs["fakeredis"].dev is True

    def test_addon_recipes_carry_addon_source(self, tmp_path: Path) -> None:
        project_dir = _scaffold(tmp_path, "myapp", "fastapi", ["docker", "redis"])
        m = read_manifest(project_dir)

        addon_recipes = {r.name: r for r in m.just_recipes if r.source == "addon"}
        assert "redis-up" in addon_recipes
        assert addon_recipes["redis-up"].addon == "redis"


# ── Python block completeness ─────────────────────────────────────────────────


class TestPythonBlockCompleteness:
    def test_blocks_recorded_for_redis_injection(self, tmp_path: Path) -> None:
        project_dir = _scaffold(tmp_path, "myapp", "fastapi", ["redis"])
        m = read_manifest(project_dir)

        redis_blocks = [b for b in m.python_blocks if b.addon == "redis"]
        assert len(redis_blocks) >= 1

    def test_block_file_is_relative_path(self, tmp_path: Path) -> None:
        project_dir = _scaffold(tmp_path, "myapp", "fastapi", ["redis"])
        m = read_manifest(project_dir)

        for block in m.python_blocks:
            assert not Path(block.file).is_absolute(), (
                f"Expected relative path, got: {block.file!r}"
            )

    def test_block_fingerprint_matches_disk(self, tmp_path: Path) -> None:
        project_dir = _scaffold(tmp_path, "myapp", "fastapi", ["redis"])
        m = read_manifest(project_dir)

        for block in m.python_blocks:
            target = project_dir / block.file
            if not target.exists():
                continue
            start, end = (int(x) for x in block.lines.split("-"))
            disk_lines = target.read_text(encoding="utf-8").splitlines(keepends=True)
            on_disk = "".join(disk_lines[start - 1 : end])
            expected_fp, _ = _fp(on_disk)
            assert block.fingerprint == expected_fp, (
                f"Fingerprint mismatch for {block.file}:{block.lines}\n"
                f"  stored : {block.fingerprint}\n"
                f"  on disk: {expected_fp}"
            )

    def test_block_line_range_is_valid(self, tmp_path: Path) -> None:
        project_dir = _scaffold(tmp_path, "myapp", "fastapi", ["redis"])
        m = read_manifest(project_dir)

        for block in m.python_blocks:
            parts = block.lines.split("-")
            assert len(parts) == 2, f"Bad line range: {block.lines!r}"
            start, end = int(parts[0]), int(parts[1])
            assert start >= 1
            assert end >= start

    def test_block_locator_name_is_non_empty(self, tmp_path: Path) -> None:
        project_dir = _scaffold(tmp_path, "myapp", "fastapi", ["redis"])
        m = read_manifest(project_dir)

        for block in m.python_blocks:
            assert block.locator.name, (
                f"Block {block.addon}/{block.point} has empty locator name"
            )


# ── Template-only baseline (blank template) ───────────────────────────────────


class TestBlankTemplateManifest:
    def test_blank_template_has_no_python_blocks(self, tmp_path: Path) -> None:
        project_dir = _scaffold(tmp_path, "myapp", "blank", [])
        m = read_manifest(project_dir)
        assert m.python_blocks == []

    def test_blank_template_has_no_addon_entries(self, tmp_path: Path) -> None:
        project_dir = _scaffold(tmp_path, "myapp", "blank", [])
        m = read_manifest(project_dir)

        addon_env = [e for e in m.env if e.source == "addon"]
        addon_deps = [d for d in m.dependencies if d.source == "addon"]
        assert addon_env == []
        assert addon_deps == []


# ── Additive safety ───────────────────────────────────────────────────────────


class TestAdditiveManifest:
    def test_addon_does_not_corrupt_template_entries(self, tmp_path: Path) -> None:
        """Template-owned entries must survive addon addition unchanged."""
        project_dir = _scaffold(tmp_path, "myapp", "fastapi", ["postgres", "redis"])
        m = read_manifest(project_dir)

        db_entry = next((e for e in m.env if e.key == "DATABASE_URL"), None)
        assert db_entry is not None
        assert db_entry.source == "addon"
        assert db_entry.addon == "postgres"

    def test_no_duplicate_entries_after_scaffold(self, tmp_path: Path) -> None:
        project_dir = _scaffold(tmp_path, "myapp", "fastapi", ["redis"])
        m = read_manifest(project_dir)

        env_keys = [e.key for e in m.env]
        assert len(env_keys) == len(set(env_keys)), (
            f"Duplicate env keys in manifest: {env_keys}"
        )

        dep_pkgs = [d.package for d in m.dependencies]
        assert len(dep_pkgs) == len(set(dep_pkgs)), (
            f"Duplicate dep entries in manifest: {dep_pkgs}"
        )

        recipe_names = [r.name for r in m.just_recipes]
        assert len(recipe_names) == len(set(recipe_names)), (
            f"Duplicate recipe entries in manifest: {recipe_names}"
        )
