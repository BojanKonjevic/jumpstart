# Architecture Overview

Zenit generates projects and then tracks everything it touched in `.zenit.toml`. There is no runtime, no framework to stay compatible with, no lock-in. Once a project is generated, it works independently of Zenit.

This page gives you the mental model. The sub-pages go deeper on each mechanism.

---

## The three layers

**Templates** set the foundation. You pick one when you run `zenit create`. It determines overall structure - a FastAPI app with SQLAlchemy and Alembic, or a minimal blank package. Templates also declare the named injection points that addons are allowed to target.

**Addons** are optional capabilities layered on top. Each is self-contained and declarative: it knows exactly what files it creates, what code it injects, what packages it requires. Addons can be applied at creation time or added later with `zenit add`. They can also be removed cleanly.

**Your project** has no connection to Zenit except `.zenit.toml`. Delete that file and the project runs exactly the same - Zenit just can't manage it anymore.

---

## The removability constraint

Every design decision in Zenit is shaped by one hard rule: **everything Zenit adds must be removable.**

At any point you can run `zenit remove <addon>` and the project returns to its exact previous state - files deleted, injections excised, packages removed from `pyproject.toml`. You can also stop using Zenit entirely by deleting `.zenit.toml`.

This constraint drives the two most consequential design choices:

**Code injection uses a CST pipeline, not string replacement.** Removal has to be surgical - it must find exactly what was injected and remove only that, even after the file has been formatted or edited. Regex-based approaches break when the file changes. libcst finds code structurally.

**Addons are declarative, not imperative.** An addon describes what it adds; it doesn't run arbitrary code. Declarative manifests are fully enumerable and fully reversible. An addon that runs a script during install cannot be cleanly uninstalled.

---

## Three mechanisms, tracked separately

**File writes** - template and addon files are rendered from Jinja2 and written to disk. The manifest records the path and a content hash. On removal, the file is deleted - but only if the hash still matches. If you modified the file, Zenit warns you before touching it.

**Dependency edits** - `pyproject.toml` is edited with tomlkit, which preserves formatting and comments. Each addon declares its packages; Zenit adds them to the right section and records which packages came from which addon. On removal, those packages are deleted. `uv sync` is left to you.

**Code injection** - the most complex mechanism. When an addon needs to register a router, add a lifespan hook, or configure middleware in a file that already exists, Zenit parses the file with libcst, locates the correct insertion point structurally, splices in the new code, and validates the result is still valid Python. The manifest records a fingerprint of the injected block. On removal, that fingerprint is used to find and excise exactly that block.

---

## The role of `.zenit.toml`

`.zenit.toml` is the only artifact that connects a project to Zenit. It records everything: which template was used, which addons are installed, every file created (with content hash), every injection (with fingerprint and location), every dependency added.

This is what makes `zenit remove`, `zenit doctor`, and safe re-management possible. Without it, Zenit has no way to know what it wrote versus what you wrote.

**Commit it. Don't edit it manually.**

---

## Sub-pages

- [Code Injection](./injection.md) - how the libcst pipeline works, the locator system, how removal uses fingerprints
- [Addons & Templates](./addons-and-templates.md) - the internal structure of a template and addon, model reference, and how to write your own
- [The Manifest](./manifest.md) - every field in `.zenit.toml`, annotated
