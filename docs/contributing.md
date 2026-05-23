# Contributing

Zenit is currently a solo project. These guidelines exist so that if you want to contribute, the process is clear — and so the author doesn't forget his own conventions.

---

## Quick start

```bash
git clone https://github.com/BojanKonjevic/zenit.git
cd zenit

# Install uv if you haven't already
curl -LsSf https://astral.sh/uv/install.sh | sh

uv sync
just test    # full test suite (986+ tests)
just lint    # ruff check
just fmt     # ruff format
just check   # mypy strict
```

---

## What to contribute

**Definitely welcome:** bug fixes, documentation improvements, new addons, template improvements, more test coverage.

**Discuss first** (open an issue before writing code): core pipeline changes (manifest schema, injection engine, rollback logic), new CLI commands, and anything that would alter `.zenit.toml` schema or existing addon behaviour.

---

## How to contribute

1. Fork and branch — `git checkout -b fix-something`
2. Write the change, following the standards below
3. Add tests — every behaviour change ships with tests, no exceptions
4. Run `just test`, `just lint`, `just check` — all must be clean
5. Open a PR — describe what changed and why

Small, focused changes move faster than large refactors.

---

## Coding standards

**Types.** Strict MyPy. No `Any` without `# type: ignore[...]` justification. Use `from __future__ import annotations` when forward references are needed. No bare `except:` or `except Exception:` unless re-raising immediately.

**Style.** Ruff handles formatting and import sorting — run `just fmt`. Functions should be small and single-purpose; over 30 lines is a smell. Explicit type annotations on all signatures. No star imports.

**Comments.** Don't add file-header path comments. Don't explain what the code already says. Comment non-obvious intent or domain quirks only.

**Errors.** Use the `ZenitError` hierarchy — no raw `ValueError` or `RuntimeError` in user-facing paths. Error messages must say what failed, why it failed, and how to fix it.

---

## Testing

Zenit has 985+ tests covering injection, removal, round-trip integrity, and edge cases. Every PR-level change includes tests.

Test layers: unit (single function, mocked dependencies), integration (multiple modules, real filesystem), functional (end-to-end CLI), and slow (I/O-heavy). Cover edge cases — empty input, malformed input, missing files, permission errors — and every `raise` and `except` branch.

---

## Architecture principles

If you're modifying core code, keep these in mind:

1. **User trust & independence** — Zenit must never trap users. Removal must be trivial.
2. **Declarative over imperative** — addons describe what they add, they don't run arbitrary code.
3. **Everything must be removable** — the design constraint that shapes every other decision.
4. **Composition over inheritance** — extend via handlers and hooks, not subclassing.
5. **Public API minimal and stable** — templates and core logic stay strictly separated.

---

## Reporting bugs

Use [GitHub Issues](https://github.com/BojanKonjevic/zenit/issues). Include the Zenit version (`zenit --version`), Python version and OS, minimal reproduction steps, expected vs. actual behaviour, and — if relevant — the contents of `.zenit.toml` and the output of `zenit doctor`.

---

## License

By contributing, you agree that your contributions will be licensed under the [MIT License](https://github.com/BojanKonjevic/zenit/blob/main/LICENSE).
