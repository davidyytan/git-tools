# Git Flow Guide

Read these in order:

1. [GitHub Setup](github-setup.md)
2. Pick one standalone flow guide:
   - [Git Flow Classic](git-flow-classic.md) — develop chooses the release line; small team, light process
   - [Git Flow Classic — Reviewed](git-flow-classic-reviewed.md) — classic plus an inner PR layer on `release/*` and `hotfix/*`; for compliance / regulated industries
   - [Git Flow Variant — Release-led](git-flow-variant-release-led.md) — the release branch chooses the line; release manager owns the version
   - [Git Flow Variant — Reviewed](git-flow-variant-reviewed.md) — release-led plus an inner PR layer with squash merges; release manager owns the version and every commit is reviewed

## Shared Naming Policy

- `Start X.Y.Z` opens `X.Y.Z-alpha.0` on `develop`
- `Release X.Y.Z` is reserved for `release/* -> master`
- `Hotfix X.Y.Z` is reserved for `hotfix/* -> master`
- `Backmerge Release X.Y.Z` is reserved for `release/* -> develop`
- `Backmerge Hotfix X.Y.Z` is reserved for `hotfix/* -> develop`

GitHub may append a trailing `(#123)` to merged workflow subjects. The runtime
matcher ignores that suffix and still recognizes the underlying fixed title.

Release and hotfix branch work stays normal Conventional Commits. If a release
branch needs to open `rc.0` without a real stabilization change, use an empty
commit such as:

```text
chore: open release
```

## Shared Bump Policy

These guides assume the bump strategy follows these rules:

- `develop` creates or continues tagged `alpha`
- `master` finalizes prerelease to stable
- backmerges into `develop` preserve an ahead alpha line when one is already open
- meaningful unique backmerged fixes may advance that ahead alpha by one
- if `develop` is not ahead yet, a backmerge may catch `develop` up to the promoted stable target without tagging
- after that stable catch-up, open the next cycle later with `Start X.Y.Z` when needed

## CLI Coverage

Current helpers match the documented workflow:

- `git-tools commit --workflow-kind open-release`
- `git-tools pr --start-pr`, `--release-pr`, `--hotfix-pr`, `--backmerge-release-pr`, and `--backmerge-hotfix-pr`
- pass `--workflow-version X.Y.Z` when repo state cannot safely infer the tuple for a fixed-title Start or Backmerge flow

These guides are GitHub PR-based adaptations of Git Flow. They support either
squash merge or merge commits, as long as the final commit subject on the
target branch is the PR title.

If you want the closest thing to classic Git Flow, use [Git Flow
Classic](git-flow-classic.md) with merge commits for feature, release, and
hotfix PRs.

`Rebase merge` is not part of this documented flow.

Use **Variant — Release-led** if you want `release/X.Y.Z` to choose the release line.

Use **Classic** if you want `develop` to choose the release line first and then
open the next cycle with a `Start X.Y.Z` first PR.

Use **Classic — Reviewed** if you want classic semantics but every commit on
`release/*` and `hotfix/*` must arrive via an inner PR for review trail.

Use **Variant — Reviewed** if you want the release-led model but every commit on
`release/*` and `hotfix/*` must arrive via an inner PR (squash) for a review trail.
