# Versioning and Best-Effort Sync

[Documentation index](README.md) · [CLI reference](usage.md#bump) · [Workflow modes](git-flow-guide.md)

## Common tasks

| What you need | Start here |
| --- | --- |
| Preview a bump without changing files | `git-tools bump --dry-run` in your application repository |
| Print only the next version | `git-tools bump --get-next` |
| Update only `.cz.toml` | [Disable auxiliary sync](#disabling-auxiliary-sync-local-and-ci) |
| Sync only the root app, not child tools | [Set the directory allowlist](#optional-directory-allowlist) to `["."]` |
| Check supported manifests/lockfiles | [Automatic targets](#automatic-targets) |
| Recover failed CI publication | [Publication and recovery](publication.md) |

Direct `git-tools bump` writes files, commits, and normally tags; it does not push. Keep the index empty before applying and review the full diff. Read the [current limitations](#current-limitations) before custom selectors or planning around unusual filesystem paths.

## Authority

**`.cz.toml` is the sole authority for the current version, next version, and Git tag format.** Other files never determine or override these values.

```toml
[tool.commitizen]
name = "cz_conventional_commits"
version = "1.2.3"
version_scheme = "semver2"
tag_format = "$version"
```

Only `.cz.toml` is supported as the Commitizen source: not `cz.toml`, embedded Commitizen configuration in `pyproject.toml`, or external version providers. `semver2` uses versions such as `1.3.0-alpha.0`; `semver` uses `1.3.0-a0`. An explicitly configured scheme is honored even when the current version is stable.

## What Happens During Bump

1. Read `.cz.toml` and repository history; compute the next version and tag.
2. Plan the authoritative update and **try** each optional sync target.
3. Write `.cz.toml` and successfully handled auxiliary targets.
4. Stage successful changed files, create the bump commit, and create the tag unless `--no-tag` is used.

Handled auxiliary loading, pattern resolution, reading, updating, and writing failures produce warnings and are skipped rather than blocking the authoritative bump, commit, or tagging. Missing optional automatic files do not need to be created. Stale auxiliary versions can be brought into line with the newly computed version. This best-effort policy is not a guarantee against every planning failure: the metadata snapshot has a confirmed [nonregular-file hang](#current-limitations).

Explicit custom targets resolving outside the physical repository root are configuration errors, not skippable auxiliary warnings (see [extra targets](#explicit-extra-targets)). Core `.cz.toml` errors, invalid core history/configuration, and failed Git operations still stop the operation. `--check-consistency` applies to the authoritative field; it does not turn auxiliary mismatches into hard requirements.

Use `--get-next` for a lightweight version-only calculation. `--dry-run` also runs the in-memory managed-file planner and shows paths/diffs, consistency errors and best-effort warnings without writes, commits, or tags. It cannot validate execution of hooks, signing, or Git writes. Interactive bump offers Preview / Apply / Cancel and applies the same reviewed plan. Snapshot checks cover branch/HEAD, tags, managed-file bytes, target-discovery metadata and selected Git settings. They do **not** currently detect a file's executable-bit change after preview; see [current limitations](#current-limitations).

## Disabling Auxiliary Sync (Local and CI)

Bumping typically runs in CI: configure auxiliary sync directly in the workflow YAML as shown below. For local runs (including `uv`), auxiliary sync defaults to enabled; to bump only the authoritative `.cz.toml`, set the repository default:

```toml
[tool.commitizen]
version = "1.2.3"
sync_auxiliary = false
```

Or optionally override it for one local `uv` execution:

```sh
GIT_TOOLS_BUMP_SYNC_AUXILIARY=false uv run git-tools bump --yes
```

The bump engine reads this override from the **process environment**, not automatically from `git-tools.env` or `~/.git-tools/settings.env`; export it or use the command prefix shown above.

Precedence is **environment variable > `.cz.toml` `sync_auxiliary` > `true`**. The TOML setting must be a boolean, not a quoted string; invalid TOML setting types fail even when an environment override is present. Environment values are case-insensitive and trimmed: `true`/`false`, `1`/`0`, `yes`/`no`, or `on`/`off`. An empty or unrecognized environment value raises `ConfigError` rather than silently enabling or disabling sync.

Disabled means **all auxiliary targets**: `pyproject.toml`, `uv.lock`, npm JSON files, Cargo files at the root and eligible immediate-child locations, and every custom `version_files` entry. Auxiliary files are not parsed or registered as sync targets, and auxiliary selectors are not validated or resolved; even unsafe custom selectors are inactive while sync is disabled. The reviewed-plan snapshot still inspects known metadata paths, independently of target selection. It currently attempts to read any existing non-symlink metadata path without first requiring a regular file: a FIFO can hang planning even with sync disabled. Concurrent metadata byte changes can also require a fresh plan. See [current limitations](#current-limitations). No auxiliary version updates are planned. `.cz.toml` remains the source of truth and is still bumped. Version calculation, branch/history rules, commits, tagging, and publication are not disabled by this switch.

### CI deployment configuration

All shipped workflows under `.github/workflows/` and `.azure/workflows/` define `GIT_TOOLS_BUMP_SYNC_AUXILIARY` directly in YAML, defaulting to `'true'`. **Edit the workflow YAML** to disable sync in CI; no GitHub repository variable or local `.env` setup is required. The workflow passes this setting through the process environment, so it overrides `.cz.toml` `sync_auxiliary`, including a TOML `false`.

For GitHub Actions, change the workflow-level setting to `'false'` for both push and manual runs (the shipped default is `'true'`):

```yaml
env:
  GIT_TOOLS_BUMP_SYNC_AUXILIARY: 'false'
```

For Azure Pipelines, edit the template's deployment variable:

```yaml
variables:
  GIT_TOOLS_BUMP_SYNC_AUXILIARY: 'false'
```

The Azure templates explicitly map this variable into the strategy and bump step environments. GitHub uses a workflow-wide environment. Embedded Python and its bump subprocess inherit the same setting; no package-manager invocation is added.

## Automatic Targets

Automatic discovery checks the repository root and its immediate child directories only, consistently for Python/uv, npm, and Cargo. It never descends into grandchildren or recursively walks workspace members. Hidden directories and `node_modules`, `target`, `build`, `dist`, `vendor`, `venv`, and `__pycache__` are excluded. Symlink directories and symlink target files are skipped.

By default, supported targets at **every eligible location** sync to the release version computed from `.cz.toml`, even when multiple locations contain the same ecosystem. A malformed or unsupported target warns and skips independently; other supported targets and locations can still sync. Each Python or Cargo lockfile is paired only with the manifest in the same directory; a manifest can be synced without a lockfile.

Immediate-child tools such as `smoke_runs` participate by default when they contain supported files; they are not implicitly excluded as development-only projects. To keep a child tool on an independent version, exclude it by listing only the desired directories in the allowlist below.

### Optional directory allowlist

To limit automatic sync, set `auxiliary_directories` as a **replacement allowlist**, not an addition to the default discovery. For root-only sync:

```toml
[tool.commitizen]
version = "1.2.3"
auxiliary_directories = ["."]
```

To include selected release-sharing children, use, for example, `auxiliary_directories = [".", "backend", "frontend", "src-tauri"]`. This applies across all supported ecosystems: only the listed directories participate, and every selected project's own version syncs to the computed release version on a best-effort basis. `"."` means the repository root; omit it to exclude root targets. Each other entry must name an existing, non-hidden immediate child directory that is not a symlink or an excluded tool directory. Absolute paths, parent traversal, deeper paths such as `services/api`, and invalid selector types raise `ConfigError` before updates. Explicit selection does not enable recursion or Cargo workspace inheritance.

Use `auxiliary_directories = []` to disable automatic targets while keeping explicit `version_files` targets active. **Do not use that combination to bypass structured npm/Cargo handling:** the current implementation can instead select a generic regex target and rewrite dependency versions. The same gap exists when the allowlist excludes a directory; see [current limitations](#current-limitations). By contrast, `sync_auxiliary = false` disables both automatic and custom auxiliary updates and bypasses directory-selector validation, but does not avoid the snapshot hang described above. Omit `auxiliary_directories` to sync all supported targets within the bounded discovery rules above.

### Supported files in each selected directory

The following filenames are checked at each selected location; no package-manager command or dependency-tree traversal is added.

| File | Fields attempted |
| --- | --- |
| `pyproject.toml` | `[project].version`, if present |
| `uv.lock` | Own package version selected by `[project].name` from `pyproject.toml` |
| `package.json` | Top-level `version` |
| `package-lock.json` | Top-level `version` and `packages[""].version`, independently where valid |
| `npm-shrinkwrap.json` | Top-level `version` and `packages[""].version`, independently where valid |
| `Cargo.toml` | Literal `[package].version` |
| `Cargo.lock` | Unique local crate entry selected by the sibling manifest's exact package name and old version; no `source` field |

Python lock prereleases use the package form: for example `.cz.toml` version `0.2.0-alpha.16` becomes `0.2.0a16` in `uv.lock`. These structured automatic handlers do not bump dependency versions; this does not extend to arbitrary custom regex selections. No `uv lock`, `npm install`, `cargo update`, or other package-manager command is run.

### Node.js, TypeScript, Express, and Electron

These use the same generic `package.json` support; there is no framework-specific bump path. JSON-aware selection targets only the app's own version fields, not dependency versions (including `express` and `electron`) or nested workspace/package versions in npm lockfiles. Missing or non-string version fields warn and are not invented. When a version changes, the entire JSON document is parsed and reserialized: formatting may be normalized and unrelated numeric values can lose precision through Python float conversion. Common indentation and final newline conventions are preserved. Inspect the full diff, not only the version fields.

### Rust and Cargo

Cargo sync is another **best-effort try during the normal bump**, not a separate release authority. It updates a standalone app crate's literal `[package].version` and attempts its matching local `Cargo.lock` entry. TOML is validated and comments, quoting, and normal layout are retained. Rust prereleases use the computed version text directly (for example `1.3.0-alpha.0`), not Python's compact prerelease form.

Registry/git package versions, dependency requirements, lockfile format versions, and unrelated workspace crates are untouched. A stale, ambiguous, malformed, or unsupported lockfile warns and skips independently of its manifest. Version-qualified lockfile dependency references are not rewritten; that lockfile is skipped with a warning so it can be regenerated with Cargo. A skipped lockfile may need repair before `cargo build --locked` or packaging.

Virtual workspaces, `[workspace.package].version`, and `version.workspace = true` are **not** automatically rewritten: changing a shared version can affect many crates. They warn and skip rather than guessing. Every eligible immediate-child standalone crate participates by default alongside root crates, unless excluded through `auxiliary_directories`. Deeper crate locations are outside automatic support; there is no automatic workspace recursion. Do not treat a custom regex as an equivalent safe Cargo manifest/lockfile handler.

### Tauri

If Tauri's version already references `package.json`, **leave that reference intact**. The bump attempts to update `package.json`, not replace the reference with a literal version. The conventional `src-tauri/Cargo.toml` and `src-tauri/Cargo.lock` are within the one-level discovery boundary and use the Cargo rules above. They participate by default alongside any other eligible Cargo locations; use `auxiliary_directories` only to limit that selection. Tauri configuration itself is not rewritten. Other immediate child backend directories work the same way. Deeper ecosystem manifests/lockfiles are outside automatic support; custom selectors are not a substitute for their structured safety checks.

### Monorepos and Other Lockfiles

There is no automatic recursion into workspaces. Supported files at the root and every eligible immediate-child location share the release version by default; use the replacement `auxiliary_directories` allowlist to exclude independently versioned projects. Nested workspace members and deeper package locations remain outside automatic support. Use `version_files` for deeper custom version files only when they genuinely share a release version and their content can be selected safely; see the ecosystem-selector limitation below. Yarn and pnpm lockfiles are not automatically rewritten or regenerated.

## Explicit Extra Targets

Add `version_files` to `[tool.commitizen]` for custom files that share the version. For example, this target can be a plain file containing only `1.2.3`:

```toml
version_files = [
  'apps/desktop/VERSION',
]
```

For npm/Cargo manifests and lockfiles, prefer supported structured automatic targets in selected root/immediate-child directories. A generic line regex cannot provide equivalent semantic protection.

With auxiliary sync enabled, every explicit path/glob and each match must resolve inside the resolved repository root. Paths (including internal `..` aliases), absolute paths, and symlinks are allowed only when their resolved physical path remains inside the repository, and aliases share physical file identity. A selector or glob match resolving outside that physical root raises a clear `ConfigError` before any updates are written; this is not downgraded to an auxiliary warning. Physical root identity also handles macOS `/var` versus `/private/var` aliases.

Entries support a path/glob and an optional colon-separated regular expression. The matcher works **line by line**, not as a JSON/TOML parser: a regex selects whole lines, not a capture group or field. Without a pattern, the current version text selects the lines; stale-only lines therefore need an explicit regex.

A selected version-bearing line must contain exactly **one complete supported version token**, and all selected version-bearing lines must carry the same source version. Multiple values on one line are rejected even when identical; differing versions across selected lines are also rejected. Repeated single versions on separate lines are allowed. Only the token span is replaced, never substrings of longer versions. Stable versions and the supported `alpha`/`beta`/`rc` formats (including the short `a`/`b`/`rc` scheme) are recognized; unsupported suffixes and build metadata warn and skip rather than receiving a partial replacement. Selected lines with no version token are left alone; a target with no version tokens is skipped. An unambiguous stale source version may sync to the new version.

Invalid patterns, unmatched paths, unreadable files, unsupported version tokens, and ambiguous content warn and skip that custom target without blocking the core bump or other safe targets. Use narrowly selected lines and inspect the diff: line selection cannot establish the semantic meaning of a version field. For npm/Cargo paths reserved in the automatic candidate directories, configured replacement patterns do not override ecosystem-aware handling. **That reservation is currently incomplete when `auxiliary_directories` is empty or excludes the path:** a custom selector can fall through to generic line matching and change dependency versions. This violates the intended structured safety policy; it is not a supported workaround. See [current limitations](#current-limitations). `.cz.toml` remains the authoritative target.

## Current limitations

These confirmed implementation gaps remain unresolved:

- **Nonregular metadata can hang planning.** The snapshot opens existing known metadata paths without first requiring a regular file. A FIFO named `package.json` can block `--dry-run` or interactive planning, even with `sync_auxiliary = false` or the path excluded from auxiliary selection. `--get-next` avoids this snapshot and remains a version-only calculation, not a file-plan validation. Until fixed, ensure known metadata paths at the root and immediate-child locations are ordinary regular files (or absent), not FIFOs/devices. Do not assume disabling sync avoids inspecting those paths.
- **Post-preview executable-bit changes are not detected.** File bytes/path identity are checked, but Git executable mode is not captured. With `core.filemode=true`, changing a tracked managed file from `0644` to `0755` after preview can be accepted and committed. Avoid concurrent edits, including mode changes; inspect modes with `git diff --summary` and restart the operation to obtain a fresh preview after any change. The current snapshot is not a complete stale-state guarantee.
- **Custom selectors can bypass ecosystem reservations.** For example, `auxiliary_directories = []` combined with `version_files = ["package.json:version"]` can select both the app's version line and a dependency named `lib-version`, updating both when their versions match. An allowlist excluding that directory can expose the same gap. Keep supported ecosystem manifests/lockfiles under their structured handlers; do not use broad generic selectors to re-enable them outside automatic selection. If structured handling cannot cover the layout, use a separately reviewed ecosystem-specific process rather than assuming a regex has safe field semantics.

These precautions are workarounds, not repairs. In particular, neither a green test suite nor a successful dry-run proves all later mode changes or custom selectors are safe. The intended policy remains to update only the app's own ecosystem version, not dependencies.

## Safety and Recovery

Apply requires an empty index: pre-staged changes, including managed files, are rejected before mutation with unstage guidance. Dry-run remains available with staged changes. Prefer a clean working tree too: existing unstaged edits in managed files are included in the reviewed file plan and can enter its commit; unrelated unstaged files are not added. The write/commit/tag sequence remains nontransactional; a failed write can leave partial file content, and a Git failure can leave changed files or a commit without its tag. Failed auxiliary writes are not added to the bump's staging list.

Read warnings and inspect `git diff`/`git status` afterward. A skipped file can remain out of sync and may need manual repair or regeneration before packaging/deployment. Local bump does not push refs; see [publication and recovery](publication.md) for CI.
