<h1 align="center">
  <a href="https://bojankonjevic.github.io/zenit/" target="_blank" rel="noopener noreferrer">
    zenit
  </a>
</h1>

<p align="center">
  Scaffold Python projects without lock-in. Add what you need. Remove cleanly.
</p>

<p align="center">
  <a href="https://github.com/BojanKonjevic/zenit/actions/workflows/ci.yml">
    <img src="https://github.com/BojanKonjevic/zenit/actions/workflows/ci.yml/badge.svg" alt="CI">
  </a>
  <a href="https://github.com/BojanKonjevic/zenit/blob/main/LICENSE">
    <img src="https://img.shields.io/github/license/BojanKonjevic/zenit" alt="License">
  </a>
  <a href="https://pypi.org/project/zenit/">
    <img src="https://img.shields.io/pypi/v/zenit" alt="PyPI">
  </a>
  <a href="https://pypi.org/project/zenit/">
    <img src="https://img.shields.io/pypi/pyversions/zenit" alt="Python">
  </a>
</p>

---

**Zenit** is a CLI tool that scaffolds Python projects from declarative templates and addons. It generates production-ready code - FastAPI apps, database layers, Docker configs, CI pipelines - then gets out of the way. Everything it adds can be removed cleanly. Delete `.zenit.toml` and the project keeps working exactly the same.

## Quick Start

```bash
# Install
uv tool install zenit

# Create a project
zenit create my-api

# Add capabilities later
zenit add redis
zenit add auth-manual
```

## Documentation

Full documentation is available at **[bojankonjevic.github.io/zenit/docs](https://bojankonjevic.github.io/zenit/docs/)**.

- [Getting Started](https://bojankonjevic.github.io/zenit/docs/getting-started) - install, create, and run in under five minutes
- [Architecture](https://bojankonjevic.github.io/zenit/docs/architecture/) - how the manifest, libcst injection, and declarative addons work
- [Commands](https://bojankonjevic.github.io/zenit/docs/commands/) - `create`, `add`, `remove`, `doctor`, `list`, `config`, `graph`, `migrate`
- [Templates](https://bojankonjevic.github.io/zenit/docs/templates/) - `blank` and `fastapi`
- [Addons](https://bojankonjevic.github.io/zenit/docs/addons/) - Docker, Redis, Celery, auth, Sentry, GitHub Actions, SQLAlchemy, PostgreSQL, SQLModel
- [Contributing](https://bojankonjevic.github.io/zenit/docs/contributing) - coding standards, tests, and how to submit changes

## Studio

Explore templates, browse addons, inspect their files and dependencies, and build commands visually - all in your browser.

**[bojankonjevic.github.io/zenit/studio/](https://bojankonjevic.github.io/zenit/studio/)**

## Why Zenit?

- **No lock-in** - generated projects have zero runtime dependency on Zenit
- **Clean removal** - `zenit remove <addon>` undoes every file, injection, and dependency
- **Declarative addons** - addons describe what they add, not arbitrary scripts
- **Structural injection** - libcst-based code injection that survives formatting
- **Fingerprint tracking** - every injected block is hashed so removal is exact
- **Copier migration** - `zenit migrate` imports any Copier template into a Zenit-managed project
- **Dependency graph** - `zenit graph` renders addon dependencies in the terminal or as DOT/JSON

## License

[MIT](LICENSE)

