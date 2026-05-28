
# Zenit Code Audit

## 1. Priority Assessment

The single most dangerous failure mode is **removal without rollback**: unlike `add_addon` which wraps its pipeline in `addon_or_rollback` (pre-snapshot with full restore on failure), `remove_addon` operates destructively — deleting files, removing injection lines, and mutating pyproject.toml — without any snapshot or recovery mechanism. A crash or exception mid-removal (e.g., a `RemovalError` from a corrupted Python file during `_undo_injections_physical`) leaves the project in an unrecoverable state: files already deleted, lockfile and manifest out of sync, and no automatic way back. The remaining errors are significant but lower-stakes, mostly in the gap between a well-designed architecture and its incomplete safety-guard implementation for the removal path.

## 2. Dimensional Scores

| Dimension | Score | Rationale |
|-----------|-------|-----------|
| Correctness & Robustness | **5** | Removal pipeline is dangerously unguarded (no rollback). Python injection removal has strong safety (4-stage cascade + `_assert_valid_python`), but non-Python handler removal is bare line-range deletion with zero verification. Fingerprint fallback for fragments silently degrades to fuzzy matching. |
| Performance & Efficiency | **8** | Snapshot ignores `.venv`, `.git`, etc. — the dominant bottleneck addressed. `RecordingFileSystem` for dry-run is virtually free. Lazy-loaded addon configs via `functools.cache`. No obvious N² or redundant I/O paths. |
| Readability & Maintainability | **8** | Clean module boundaries, good docstrings on non-obvious design decisions, consistent typing, explicit `__future__` imports. The `locator` / `handler` / `dispatcher` separation is particularly clear. A few methods push 30 lines (e.g., `_backfill_just_recipes`, `add_addon`). |
| Security & Privacy | **7** | Path traversal protection in `_validate_no_path_traversal` covers all user-facing dest paths. `atomic_write_text` prevents partial-write corruption. Plugin loading via `importlib` is necessary for the addon architecture — no obvious injection surfaces. The `RecordingFileSystem` doesn't log content (good for privacy). |
| Architecture & Design | **8** | Composition over inheritance is well-executed. `HandlerDispatcher` / `FileHandler` / `Locator` separation is clean. Snapshot-based rollback is the right approach. `RecipeCollection.resolve()` is a good explicit dedup. `Context` as a simple dataclass avoids framework coupling. |
| Testability | **7** | Tests exist at unit, integration, and functional levels. `RecordingFileSystem` protocol enables sealed testing. However, the removal path is undertested relative to the add path, and `_assert_valid_python` is the only fence between fuzzy-removal correctness and corruption — tests for wrong-but-valid-Python extractions are absent. |
| Adherence to Python Idioms / Best Practices | **8** | Strong typing throughout, no star imports, proper use of Protocols, `from __future__ import annotations`, singled-out constants, clean dataclass patterns. A few `# type: ignore` without justification (acceptable given the dynamic loading requirement). |

## 3. Issues Ranked by Severity

### Critical

- **ISSUE-1**: **Severity**: Critical — **Location**: `src/zenit/addons/remove.py`, lines 120–317  
  **Description**: `remove_addon()` performs destructive operations (file deletion, injection removal, dependency removal, compose mutation) without any rollback context. If any step fails after a previous step has already committed — e.g., `_undo_injections_physical` raises `RemovalError` after `_remove_files` has already deleted addon files — the project is permanently corrupted: files are gone, the manifest/lockfile still reference the addon, and there is no automatic recovery path. Contrast with `add_addon` which wraps its entire pipeline in `addon_or_rollback`.  
  **Effort**: Medium  
  **Fix**: Wrap the removal body in `addon_or_rollback` (or `batch_snapshot`) at roughly the same scope as `add_addon` does. The snapshot will be slightly heavier (project may be larger post-scaffold), but that is acceptable for correctness:

  ```python
  with addon_or_rollback(project_dir, addon_id):
      removed_files = _remove_files(...)
      _restore_overridden_template_files(...)
      _undo_injections_physical(...)
      # ... all other removal steps ...
      remove_blocks_for_addon(manifest, addon_id)
      write_manifest(project_dir, manifest)
      write_lockfile(...)
  ```

- **ISSUE-2**: **Severity**: Critical — **Location**: `src/zenit/core/handlers/base.py`, lines 33–44  
  **Description**: The base `FileHandler.remove()` method performs blind line-range deletion with zero content verification. It reads the file, splits by lines, deletes `[start, end]` by recorded line numbers, and writes. No fingerprint check, no content comparison, no structural validation. This is inherited by `EnvHandler`, `YamlHandler`, `TomlHandler`, and `JustfileHandler` — the latter two of which handle structured formats (TOML/YAML) where removing the wrong lines can break the file entirely. Only `PythonHandler` overrides this with the 4-stage cascade.  
  **Effort**: Large  
  **Fix**: Either (a) extend fingerprint tracking to all manifest entry types (not just Python blocks), or (b) at minimum add a content-hash check before removal for non-Python handlers, or (c) re-derive the target line range by re-running the insertion logic in reverse (locate → find added content → remove). Option (b) is the smallest viable improvement:

  ```python
  def remove(self, file: Path, block: ManifestBlock) -> None:
      if not file.exists():
          return
      source = file.read_text(encoding="utf-8")
      lines = source.splitlines(keepends=True)
      start_str, end_str = block.lines.split("-")
      s = int(start_str) - 1
      e = int(end_str) - 1
      if e >= len(lines):
          return
      # Verify the recorded block still matches before deleting
      if block.content_hash:  # hypothetical new field
          actual_hash = hashlib.sha256("".join(lines[s:e+1]).encode()).hexdigest()
          if actual_hash != block.content_hash:
              logger.warning("Block content has changed since injection — skipping removal")
              return
      new_lines = lines[:s] + lines[e + 1 :]
      atomic_write_text(file, "".join(new_lines))
  ```

### High

- **ISSUE-3**: **Severity**: High — **Location**: `src/zenit/core/handlers/python_handler.py`, lines 258–286 (Stage C3)  
  **Description**: The text-level fuzzy match (Stage C3) uses `SequenceMatcher` on the entire block text and a fixed `block_len` to define the candidate window. It slides a window of exactly `block_len` lines across the search space. If the user added or removed lines within the block (not just modified existing lines), `block_len` will be wrong, and the correct content will never be matched at any offset — the window is the wrong size. The function will silently fall through to Stage D (`RemovalError`) even though the block may be present but at a different line count.  
  **Effort**: Medium  
  **Fix**: In Stage C3, try multiple candidate lengths around `block_len` (e.g., `range(block_len - 2, block_len + 3)`), similar to how Stage C2 already tries `range(max_c2_len, 0, -1)`:

  ```python
  for block_delta in range(-2, 3):
      candidate_len = block_len + block_delta
      if candidate_len < 1:
          continue
      for s in range(window_start, min(window_end, len(lines) - candidate_len) + 1):
          candidate = _normalise_for_fuzzy(_extract(s, s + candidate_len - 1))
          ratio = SequenceMatcher(None, norm_ref, candidate).ratio()
          if ratio > best_ratio:
              best_ratio = ratio
              best_start = s
  ```

- **ISSUE-4**: **Severity**: High — **Location**: `src/zenit/addons/remove.py`, lines 331–363 (`_remove_files`)  
  **Description**: `_remove_files` unconditionally deletes all files contributed by the removed addon, regardless of whether the user has modified them since installation. The manifest does not track file-content fingerprints (only Python injection blocks have fingerprints), so there is no way to detect or warn about user modifications before deletion. Unlike Python injections which have the 4-stage safety cascade, file deletion is irrevocable. If another addon (or the user) depends on a file that the removed addon contributed, that file is simply gone.  
  **Effort**: Medium  
  **Fix**: At minimum, emit a warning per file that has been modified since scaffold time. This requires adding a file-content fingerprint to the manifest at scaffold/add time (e.g., stored alongside each `FileContribution`), or checking git status / mtime as a heuristic. A full solution would be:

  ```python
  for fc in addon_cfg.files:
      dest = resolve_dest_placeholder(fc.dest, pkg_name)
      full = project_dir / dest
      if full.exists():
          if _file_was_modified_since_addon_install(full, fc, manifest):
              warn(f"'{dest}' was modified since addon installation — deleting anyway")
          full.unlink()
          removed.append(dest)
  ```

- **ISSUE-5**: **Severity**: High — **Location**: `src/zenit/core/handlers/python_handler.py`, lines 28–95 (`_locate_line`)  
  **Description**: `_locate_line` uses `MetadataWrapper(module, unsafe_skip_copy=True)`. The `unsafe_skip_copy` flag disables libcst's internal deep-copy safeguard for performance. If the metadata wrapper modifies the CST tree during resolution (a known risk documented in libcst), the parsed module may become corrupted, affecting subsequent injections in the same file or subsequent remove operations that re-read the file. This is a documented libcst sharp edge.  
  **Effort**: Small  
  **Fix**: Either (a) do not use `unsafe_skip_copy` and accept the minor performance cost, or (b) add a comment with the exact libcst version rationale and isolate each metadata resolution to its own parse:

  ```python
  # Re-parse for metadata resolution to avoid unsafe_skip_copy corruption
  fresh_module = cst.parse_module(source)
  wrapper = MetadataWrapper(fresh_module)
  positions = wrapper.resolve(PositionProvider)
  ```

### Medium

- **ISSUE-6**: **Severity**: Medium — **Location**: `src/zenit/core/handlers/base.py`, lines 11–15 (`_ensure_trailing_newline`)  
  **Description**: This function is used by multiple handlers to ensure injected content ends with a newline. It operates on `content_lines` (the list of lines to be injected). If `content` is an empty string, `content_lines` is `['']` (one empty line from `''.splitlines(keepends=True)`), and `_ensure_trailing_newline` will not add a newline if the last element is empty but does not end with `\n`. This means an empty-string injection adds a blank line. This matters for the `justfile_handler` where a blank-line-only injection could create a spurious blank block.  
  **Effort**: Small  
  **Fix**: Guard against empty content at the caller level, or handle it in `_ensure_trailing_newline`:

  ```python
  def _ensure_trailing_newline(content_lines: list[str]) -> list[str]:
      if not content_lines or (len(content_lines) == 1 and content_lines[0] == ''):
          return content_lines
      if not content_lines[-1].endswith("\n"):
          content_lines[-1] += "\n"
      return content_lines
  ```

- **ISSUE-7**: **Severity**: Medium — **Location**: `src/zenit/core/manifest.py`, lines 356–368 (`fingerprint`)  
  **Description**: When `libcst.parse_module(code)` fails on a code fragment (e.g., a single class attribute annotated line), `fingerprint()` falls back to raw-text hashing with no canonicalisation. The docstring correctly notes this means "Stage A and B removal will not match, and removal will fall through to Stage C (fuzzy match)." However, the fallback means that ANY syntactically incomplete fragment (which is common for class-body or function-body injections) always degrades to fuzzy matching on removal, even when the file has not been modified at all. This silently bypasses the exact-match guarantee for a large class of real injections.  
  **Effort**: Medium  
  **Fix**: Wrap the fragment in a valid Python module before parsing (e.g., `"class _Stub:\n    " + code` for class-body fragments, or `"def _stub():\n    " + code` for function-body fragments), then extract the relevant node's canonical output. This would require the injection to be annotated with its target scope (which the locator already knows). Alternatively, store both the raw fingerprint AND a "fragment-wrapped" normalised fingerprint.

- **ISSUE-8**: **Severity**: Medium — **Location**: `src/zenit/core/handlers/python_handler.py`, lines 397–403 (`_remove_lines`)  
  **Description**: `_collapse_blank_lines` is always applied after removal, even when the user may have intentionally placed large blank sections. The collapsing follows the manifest normalisation contract, but this is a side effect on the user's file. If a removal happens at a region where the user had 3+ consecutive blank lines (e.g., separating logical sections of code), those lines will be collapsed to 2 regardless of the user's intent.  
  **Effort**: Small  
  **Fix**: Only collapse blank lines that were created by the removal itself (i.e., blank lines at the boundary between `lines[:start]` and `lines[end+1:]`), not throughout the entire file:

  ```python
  def _collapse_boundary_blank_lines(new_lines: list[str], start: int, end: int) -> list[str]:
      # Only collapse blank lines at the removal boundary
      ...
  ```

### Nits

- **ISSUE-9**: **Severity**: Nit — **Location**: `src/zenit/core/handlers/python_handler.py`, lines 188–256 (Stages A, B, C1)  
  **Description**: `remove()` reads the file at line 188; `relocate_block` (called at line 215) re-reads it at line 317. The concern is that after relocation the original `lines` could be stale. In practice, the file is never mutated between these two reads (no write happens until `_remove_lines`), so the content is identical both times. `relocate_block`'s line numbers are computed from raw text (`source.splitlines()` at line 335), not from libcst's normalised output. There is no mechanism by which the offsets could diverge. The concern is purely theoretical.  
  **Effort**: None needed.

- **ISSUE-10**: **Severity**: Nit — **Location**: `src/zenit/addons/remove.py`, lines 637–653 (`_remove_deps`)  
  **Description**: The `dev_group` variable uses `or` for fallback from `dependency-groups` to `optional-dependencies`. If `dependency-groups.dev` exists but is an empty list (falsy), the fallback activates incorrectly. This is an extreme edge case — an empty `dependency-groups.dev` list is not a valid real-world state that uv or any tool would produce — but the logic conflates "absent" with "empty".  
  **Effort**: Small  
  **Fix**: Use explicit membership checks (`"dev" in _dev_doc`) instead of `or` fallback.

- **ISSUE-11**: **Severity**: Nit — **Location**: `src/zenit/core/dryrun.py`, lines 58–65  
  **Description**: `run_dry` calls `build_render_vars` without passing `deps`, `dev_deps`, or `python_version`, while the real scaffold path (`scaffold.py:155-163`) and add path (`add.py:126-134`) do pass them. If any template references `(( deps ))`, `(( dev_deps ))`, or `(( python_version ))`, dry-run output will differ from real output. The `dry_ctx` Context copy (one field changed) is a reasonable pattern, not an issue.  
  **Effort**: Small  
  **Fix**: Match the real scaffold path's parameter list:
  ```python
  render_vars = build_render_vars(
      name=ctx.name,
      pkg_name=ctx.pkg_name,
      template=ctx.template,
      addons=dry_ctx.addons,
      deps=contributions.deps,
      dev_deps=contributions.dev_deps,
      python_version=...,
  )
  ```

- **ISSUE-12**: **Severity**: Nit — **Location**: `src/zenit/core/collect.py`, lines 35–37 (`_merge_addon_contributions`)  
  **Description**: `_merge_addon_contributions` sets `inj.addon_id = addon.id` in-place on each `Injection` object from the addon config. Since `get_addon` is cached via `functools.cache`, this mutates the cached `AddonConfig`'s injection data. Subsequent calls see `addon_id` already set — which happens to work because the value is always the same for a given addon. This is a code smell (mutating a cached object's internals) rather than a practical bug, but it violates the expectation that cached reads are side-effect-free.  
  **Effort**: Small  
  **Fix**: Defensively copy injections in `_merge_addon_contributions`, or set `addon_id` at the caller level and keep `Injection` objects immutable.

## 4. What Is Done Particularly Well

1. **Rollback architecture for scaffold and add**: The `_snapshot_on_failure` → `_restore_snapshot` mechanism with `_SNAPSHOT_IGNORE` for `.venv`/`.git` is the correct design — it avoids the complexity of per-operation undo while remaining fast enough for interactive use. The `_move_cwd_out_of_tree` guard (`rollback.py:192–206`) shows attention to real-world failure modes (cwd disappearing after rmtree).

2. **Four-stage removal cascade with `_assert_valid_python`**: The progression from exact fingerprint → normalised fingerprint → locator-based relocation → fuzzy match → hard error is well-graded. The `_assert_valid_python` post-condition (`python_handler.py:406–423`) is the correct safety net: even if fuzzy matching selects wrong boundaries, the file won't be corrupted with invalid syntax.

3. **Clean separation of Jinja2 delimiters**: Using `(( ))` for variables and `[% %]` for blocks (vs. `{{ }}`) is a pragmatic choice that avoids conflicts with Python f-strings, Docker Compose YAML, and Alembic templates. The `make_env()` factory centralises this in one place. The distinction between `{{pkg_name}}` (plain-string substitution for paths) and `(( pkg_name ))` (Jinja2 rendering for content) is well-documented.

4. **Lockfile + Manifest separation**: The lockfile (`.zenit.toml` `[project]`) tracks what was scaffolded; the manifest (`[manifest]`) tracks ownership of every injected artifact. This two-level design allows `zenit doctor` to detect drift between what zenit *thinks* is in the project and what's actually on disk, and enables safe re-attachment after manual repair.

## 5. Comparison to Similar Tools

Compared to **Cookiecutter** (which is a one-shot template copier with no post-generation mutation model) and **Copier** (which adds idempotent re-scaffolding and Jinja2 conditionals but has no plugin system), Zenit's addon architecture with libcst-powered structural injection is a fundamentally different approach — it mutates user files *after* generation rather than at generation time. This is closer to **Terraform providers** (which manage external resource state) or **Ansible modules** (which enforce desired state on files) than to traditional project generators. Zenit's fingerprint-based manifest gives it a state-tracking capability that neither Cookiecutter nor Copier has. The tradeoff is that Zenit is tied to its known addon library (you cannot easily write one-off mutations), whereas Copier's Jinja2 conditionals are more accessible. The removal pipeline is significantly more conservative than Copier's (which simply re-scaffolds and diffs), but Copier's approach risks overwriting user modifications unless `--overwrite` is handled carefully. In practice, **Cookiecutter/Copier are better for "generate and forget" workflows; Zenit is designed for ongoing project lifecycle management**, comparable to how `npm init` + `npm install` work together. The absence of rollback in Zenit's removal pipeline (ISSUE-1) would be unacceptable in Terraform (which has a full plan/apply lifecycle with rollback) and is the most significant gap relative to that standard.

## 6. Points Where Reasonable Senior Engineers Might Disagree

1. **Single `Typer` CLI vs. subcommand hierarchy**: The current `typer.Exit(1)` pattern in validation functions mixes control flow with business logic, making it impossible to test validation without catching `SystemExit`. A valid alternative is returning `Optional[str]` (error message) or using a `Result` type, with the CLI layer deciding how to exit. The current approach is simpler but less testable. **Tradeoff**: Simplicity and obvious control flow vs. testability and composability.

2. **Snapshot-based rollback vs. per-operation undo log**: The current approach snapshots the entire project directory before mutation and restores it on any failure. This is simple and robust but expensive (even with the `.venv`/`.git` ignore list, a project with 1000+ small files can take 100-200ms to snapshot). A per-operation undo log would be faster but far more complex to implement correctly for every mutation type. **Tradeoff**: Implementation simplicity and correctness guarantees vs. performance at scale.

3. **Lazy `functools.cache` on `get_addon` vs. eager loading at startup**: Cached addon loading means the first `zenit add` is slower (loading and exec-ing the addon module), but subsequent operations in the same process are fast. This trades first-call latency for steady-state performance. An eager approach would make `zenit --help` slower but consistent. **Tradeoff**: Startup latency vs. command latency. The current choice is correct for a tool where each command is a fresh process — no state is shared between invocations, so caching only helps within a single command's execution, which is minimal.

4. **Fingerprint-only manifest for Python vs. content-hash for all file types**: Currently, only Python injection blocks get fingerprint tracking. All other manifest entries (env vars, compose services, deps, etc.) are tracked by ownership only, with no content verification. Extending fingerprints to all entry types would make removal safer (ISSUE-2) but would increase manifest size and complexity. **Tradeoff**: Safety and verification depth vs. manifest complexity and IO overhead.

5. **The `RecordingFileSystem` protocol vs. abstract methods**: The `FileSystem` Protocol class has 5 methods with no implementation. Two classes implement it (`RealFileSystem`, `RecordingFileSystem`). Using `typing.Protocol` is Pythonic but means there's no shared validation (e.g., path traversal checking must be duplicated or added at each call site instead of in the protocol). An ABC with concrete base methods could centralise safety checks. **Tradeoff**: Pythonic duck-typing flexibility vs. enforced safety guarantees in a shared base class.
