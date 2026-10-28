# Choose a Git Flow

[Documentation index](README.md) · [Complete walkthroughs](walkthroughs.md) · [CLI reference](usage.md)

## Choose your mode

Choose your platform and **one** mode. Each link below is a complete guide with key-copy commands, CI setup checkpoints, a release/hotfix example, and mode-specific policy.

| Mode | Who chooses the release line? | Human stabilization changes | GitHub | Azure DevOps |
| --- | --- | --- | --- | --- |
| Classic | `develop` selects it first; explicitly open the next cycle after cutting a release | Direct commits allowed | [Complete guide](github/classic-walkthrough.md) | [Complete guide](azure-devops/classic-walkthrough.md) |
| Classic — Reviewed | Same as Classic | Inner PRs required | [Complete guide](github/classic-reviewed-walkthrough.md) | [Complete guide](azure-devops/classic-reviewed-walkthrough.md) |
| Release-led | `release/X.Y.Z` selects it | Direct commits allowed | [Complete guide](github/release-led-walkthrough.md) | [Complete guide](azure-devops/release-led-walkthrough.md) |
| Release-led — Reviewed | Same as release-led | Inner PRs required | [Complete guide](github/release-led-reviewed-walkthrough.md) | [Complete guide](azure-devops/release-led-reviewed-walkthrough.md) |

For the closest classic Git Flow experience, choose Classic with merge commits for feature, release, and hotfix PRs. The serialized GitHub examples use squash; reviewed current-master synchronization before promotion instead requires an ancestry-preserving merge commit. Follow the chosen guide's method at each checkpoint.

**Only configuring CI or copying existing keys?** Go straight to [GitHub setup](github/setup.md) or [Azure setup](azure-devops/setup.md). You do not need to repeat fresh-repository bootstrap.

## Before following a complete example

- The examples use `master` and `develop`, full history and tags, and a fresh-repository bootstrap. An existing project needs its own migration plan; do not reset its history or version configuration to match the example.
- Enable **one** versioning adapter. Reviewed modes share the Classic or release-led adapter; review is a repository-policy layer, not another pipeline.
- `git-tools init` writes `.cz.toml` only. It does not install CI, configure secrets, create branches, or push.
- CI clones its own git-tools engine branch/tag. Local CLI updates do not update that clone. Select a supported engine ref as explained in platform setup.
- Versioning needs no LLM key. AI-generated commit and PR text uses your configured provider. Check [configuration limitations](configuration.md#current-limitations) before generation and [versioning limitations](versioning.md#current-limitations) before custom sync targets.
- Validate signing, permissions, and publication in a test repository before production. The examples are not proof of a live run in your organization.

## PR titles drive versioning

The **final commit subject on the target branch** must match the intended title:

| Title | Use it for |
| --- | --- |
| `Start X.Y.Z` | Open `X.Y.Z-alpha.0` on `develop` |
| `Release X.Y.Z` | Promote `release/*` to `master` |
| `Hotfix X.Y.Z` | Promote `hotfix/*` to `master` |
| `Backmerge Release X.Y.Z` | Bring a promoted release back into `develop` |
| `Backmerge Hotfix X.Y.Z` | Bring a promoted hotfix back into `develop` |

Ordinary feature, bugfix, and stabilization work uses Conventional Commit subjects. A supported engine ignores GitHub's trailing `(#123)` and Azure's leading `Merged PR <id>:` when matching fixed titles.

If a **direct-push** release flow needs to open `rc.0` without a real stabilization change, this is an optional alternative—not an extra required commit:

```bash
git commit --allow-empty -m "chore: open release"
```

An empty commit alone is not a reviewable inner PR. Reviewed modes require a meaningful stabilization change or an approved initialization procedure.

## Version and backmerge rules

- `develop` creates or continues tagged `alpha` versions.
- `master` finalizes a prerelease to a stable version.
- A backmerge preserves an already-ahead alpha line; meaningful unique fixes may advance that alpha by one.
- If `develop` is not ahead, a backmerge may catch it up to the promoted stable target **without a tag**. Open the next cycle later with `Start X.Y.Z` when needed.
- Keep release/hotfix branches until promotion **and** backmerge finish. After each version-producing push or merge, wait for CI, pull its commit, and fetch tags.

## Merge methods are platform-specific

Classic, Classic reviewed, and direct release-led support squash or merge commits for ordinary feature/stabilization PRs, provided the final subject is the PR title. Release-led reviewed uses squash for those ordinary PRs. **Rebase merge is not supported by these flows.**

Follow the chosen guide for synchronization and backmerges. On GitHub, reviewed current-master synchronization into a release/hotfix candidate requires **Create a merge commit**, with the stated Conventional Commit subject; repository and source-branch rules must permit merge commits. Do not squash or rebase that inner PR, because master's ancestry must survive. This exception does not change GitHub's squash-safe develop synchronization and integration-PR backmerge recipes. Azure requires **Merge (no fast-forward)** at the synchronization and boundary-backmerge steps it marks, even in release-led reviewed mode. Generated bot version commits need a narrow, approved direct-push exception to review policies; in reviewed modes, humans still use PRs.

## Local title helpers

These commands generate commit or PR text; `pr` does **not** create or merge a hosted PR:

```bash
git-tools commit --workflow-kind open-release
git-tools pr --base develop --start-pr --workflow-version X.Y.Z
git fetch origin master
git-tools pr --base origin/master --release-pr
git fetch origin master
git-tools pr --base origin/master --hotfix-pr
git-tools pr --base develop --backmerge-release-pr --workflow-version X.Y.Z
git-tools pr --base develop --backmerge-hotfix-pr --workflow-version X.Y.Z
```

Replace `X.Y.Z` before running. Refresh `origin/master` immediately before either promotion helper; a fetch updates the remote-tracking ref but does **not** move local `master`, so these helpers explicitly use `--base origin/master`. If master changes, synchronize/revalidate the candidate first and reassess the hotfix's next-patch target. For hotfix backmerge, `X.Y.Z` must be the **already-promoted hotfix version**, not the next patch. Direct mode requires it; interactive mode asks without guessing. Start and release-backmerge can infer a tuple when repository context permits. Explicit Start input still needs readable current/base versions and a valid next-cycle transition.

Direct `commit` creates a commit by default; use `--no-commit --no-copy` to preview. See the [CLI reference](usage.md) for exact options. If publication fails, inspect the remote state and use [recovery](publication.md), not force-push or another bootstrap.
