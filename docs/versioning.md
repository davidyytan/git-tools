# Versioning and Best-Effort Sync

[Documentation index](README.md) · [CLI reference](usage.md#bump) · [Workflow modes](git-flow-guide.md)

## Authority

**`.cz.toml` is the sole authority for the current version, next version, and Git tag format.**
Other files never determine or override these values.

```toml
[tool.commitizen]
name = "cz_conventional_commits"
version = "1.2.3"
version_scheme = "semver2"
tag_format = "$version"
```

Only `.cz.toml` is supported as the Commitizen source: not `cz.toml`, embedded
Commitizen configuration in `pyproject.toml`, or external version providers.
`semver2` uses versions such as `1.3.0-alpha.0`; `semver` uses `1.3.0-a0`.
An explicitly configured scheme is honored even when the current version is stable.

## What Happens During Bump

1. Read `.cz.toml` and repository history; compute the next version and tag.
2. Plan the authoritative update and **try** each optional sync target.
3. Write `.cz.toml` and successfully handled auxiliary targets.
4. Stage successful changed files, create the bump commit, and create the tag unless `--no-tag` is used.

Auxiliary loading, pattern resolution, reading, updating, and writing failures
produce warnings and are skipped. They do **not** block the authoritative bump,
commit, or tagging. Missing optional automatic files do not need to be created.
Stale auxiliary versions can be brought into line with the newly computed version.

Core `.cz.toml` errors, invalid core history/configuration, and failed Git operations
still stop the operation. `--check-consistency` applies to the authoritative field;
it does not turn auxiliary mismatches into hard requirements.

Use `--dry-run` or `--get-next` to compute without writes, commits, or tags.
Previews return before write-time target validation and are not a complete sync audit.

## Automatic Targets

Automatic targets are at the repository root, plus the conventional `src-tauri/` Cargo pair. No workspace/package-tree scan is performed.

| File | Fields attempted |
| --- | --- |
| `pyproject.toml` | `[project].version`, if present |
| `uv.lock` | Own package version selected by `[project].name` from `pyproject.toml` |
| `package.json` | Top-level `version` |
| `package-lock.json` | Top-level `version` and `packages[""].version`, independently where valid |
| `npm-shrinkwrap.json` | Top-level `version` and `packages[""].version`, independently where valid |
| `Cargo.toml`, `src-tauri/Cargo.toml` | Literal `[package].version` |
| `Cargo.lock`, `src-tauri/Cargo.lock` | Unique local crate entry selected by the sibling manifest's exact package name and old version; no `source` field |

Python lock prereleases use the package form: for example `.cz.toml` version
`0.2.0-alpha.16` becomes `0.2.0a16` in `uv.lock`. Dependency versions are not bumped;
no `uv lock`, `npm install`, `cargo update`, or other package-manager command is run.

### Node.js, TypeScript, Express, and Electron

These use the same generic `package.json` support; there is no framework-specific
bump path. JSON-aware selection changes only the app's own version. Dependency
versions, including `express` and `electron`, and nested workspace/package entries
in npm lockfiles remain untouched. Missing or non-string version fields warn and
are not invented. JSON formatting may be normalized; common indentation and final
newline conventions are preserved.

### Rust and Cargo

Cargo sync is another **best-effort try during the normal bump**, not a separate
release authority. It updates a standalone app crate's literal `[package].version`
and attempts its matching local `Cargo.lock` entry. TOML is validated and comments,
quoting, and normal layout are retained. Rust prereleases use the computed version
text directly (for example `1.3.0-alpha.0`), not Python's compact prerelease form.

Registry/git package versions, dependency requirements, lockfile format versions,
and unrelated workspace crates are untouched. A stale, ambiguous, malformed, or
unsupported lockfile warns and skips independently of its manifest. Version-qualified
lockfile dependency references are not rewritten; that lockfile is skipped with a
warning so it can be regenerated with Cargo. A skipped lockfile may need repair
before `cargo build --locked` or packaging.

Virtual workspaces, `[workspace.package].version`, and `version.workspace = true`
are **not** automatically rewritten: changing a shared version can affect many
crates. They warn and skip rather than guessing. Other crate locations require
explicit extra targets; there is no automatic workspace recursion.

### Tauri

If Tauri's version already references `package.json`, **leave that reference intact**.
The bump attempts to update `package.json`, not replace the reference with a literal
version. The conventional `src-tauri/Cargo.toml` and `src-tauri/Cargo.lock` are
also attempted using the Cargo rules above. Tauri configuration itself is not
rewritten. Custom Rust backend paths require explicit extra targets.

### Monorepos and Other Lockfiles

There is no automatic recursion into workspaces: independent packages must not all
receive the root app's version accidentally. Select additional files explicitly
when they genuinely share a release version. Yarn and pnpm lockfiles are not
automatically rewritten or regenerated.

## Explicit Extra Targets

Add `version_files` to `[tool.commitizen]` for other files that share the version:

```toml
version_files = [
  'apps/desktop/package.json:^\s*"version"\s*:',
]
```

Entries support a path/glob and an optional colon-separated regular expression.
The matcher works **line by line**, not as a JSON/TOML parser: use narrowly selected
lines and inspect the diff. Without a pattern, it searches for the current version.
Invalid patterns, unmatched paths, unreadable files, and ambiguous matching content
warn and skip. Automatic npm/Cargo targets always use their ecosystem-aware handling, not a
configured replacement pattern. Explicit regex entries cannot override their safe field selection. `.cz.toml` remains the authoritative target.

## Safety and Recovery

Start with a clean index and working tree. Unrelated staged changes can enter the
bump commit. The write/commit/tag sequence is not transactional; a failed write can
leave partial file content, and a Git failure can leave changed files or a commit
without its tag. Failed auxiliary writes are not added to the bump's staging list,
but this does not unstage changes you already staged yourself.

Read warnings and inspect `git diff`/`git status` afterward. A skipped file can remain
out of sync and may need manual repair or regeneration before packaging/deployment.
Local bump does not push refs; see [publication and recovery](publication.md) for CI.
