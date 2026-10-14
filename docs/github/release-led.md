# Git Flow Variant — Release-led

[GitHub guides](README.md) · [Setup](setup.md) · [CLI and interactive usage](../usage.md)

Use this flow if you want the release branch to choose the final release line.

Use this workflow example and activate it as
`.github/workflows/version-bump-git-flow-variant-release-led.yml`:

```text
.github/workflows/version-bump-git-flow-variant-release-led.yml.example
```

This is the direct-push variant: commits land directly on `release/*` and
`hotfix/*`. If you want the same release-led model but with every change reviewed
through inner PRs and squash merges, use
[Variant — Reviewed](release-led-reviewed.md) instead.

## Subjects and Commands

Use the [shared subject protocol](../git-flow-guide.md#shared-naming-policy)
and [platform setup](setup.md) before following these recipes.
Replace placeholders with actual paths and versions; these are separate steps,
not a single script. Direct `git-tools commit` commits by default; use
`--no-commit` to review text only. `git-tools pr` generates text, not a hosted PR.
Review staged files before committing. Wait for CI, pull bot commits, and
fetch tags before dependent operations.
Keep promotion branches until backmerge completes.

## Merge Strategy

Squash or merge commits are supported when the final subject is the PR title.
Configure the [platform merge settings](setup.md#merge-settings); do not use
rebase completion. This direct-change mode does not require inner PRs.

## Synchronization Policy

Not required in this mode. Synchronization changes may be pushed directly;
use the reviewed sister guide if all human stabilization changes require PRs.

## Command Recipes

### Bootstrap on `master`

Follow [platform bootstrap](setup.md#bootstrap-master-and-develop).
Do this once in a fresh repository, not on every release.

### Feature or bugfix PR into `develop`

```bash
git checkout develop
git pull origin develop
git checkout -b feature/<name>
git add -A
git-tools commit
git push -u origin feature/<name>
git-tools pr --base develop
```

If this is the first PR after creating a fresh `develop` line, keep the branch commit Conventional Commit based and open the PR with `Start X.Y.Z`. That first Start-titled PR opens the new `alpha` line and may still describe the actual feature or bugfix changes normally.

### Release branch work and release PR into `master`

```bash
git checkout develop
git pull origin develop
git checkout -b release/X.Y.Z
git add -A
git-tools commit

# ALTERNATIVE to a real stabilization commit: open rc.0
git commit --allow-empty -m "chore: open release"

# if master has moved since the release was cut (e.g. a hotfix landed)
git fetch origin master
git merge origin/master -m "chore: merge master for release"

git push -u origin release/X.Y.Z
git-tools pr --release-pr
```

### Release backmerge into `develop`

```bash
git checkout release/X.Y.Z
git pull origin release/X.Y.Z
git fetch origin develop
git merge origin/develop -m "chore: merge develop for backmerge"
# resolve conflicts — keep the intended target version consistent in version files
git push origin release/X.Y.Z
git-tools pr --backmerge-release-pr
```

### Hotfix PR into `master`

```bash
git checkout master
git pull origin master
git checkout -b hotfix/<name>
git add -A
git-tools commit

# if master has moved since the hotfix was created (e.g. another hotfix landed)
git fetch origin master
git merge origin/master -m "chore: merge master for hotfix"

git push -u origin hotfix/<name>
git-tools pr --hotfix-pr
```

### Hotfix backmerge into `develop`

```bash
git checkout hotfix/<name>
git pull origin hotfix/<name>
git fetch origin develop
git merge origin/develop -m "chore: merge develop for backmerge"
# resolve conflicts — keep the intended target version consistent in version files
git push origin hotfix/<name>
git-tools pr --backmerge-hotfix-pr
```

## Feature and Bugfix Policy

Most feature and bugfix work lands on `develop` with a normal Conventional
Commit title. `develop` creates or continues tagged `alpha` prereleases.

On a freshly created `develop` branch that still matches the latest stable
release, the first develop PR may use the fixed title `Start X.Y.Z` while the
branch commit itself stays Conventional Commit based.

## Release-Line Policy

The release branch selects the target; cutting it does not itself open `rc.0`.
An optional `Start` PR opens a new develop line independently of this cut.

## Release Stabilization and Promotion

Variant flow lets the release branch choose the final release line.

Rules:

- `release/X.Y.Z` chooses the target release tuple
- creating the branch alone does not start `rc.0`
- the first meaningful Conventional Commit on the branch starts `X.Y.Z-rc.0`
- later meaningful Conventional Commits continue `X.Y.Z-rc.N`
- if there is no real stabilization change, an empty `chore: open release` commit is acceptable

Promotion PR title into `master`:

```text
Release X.Y.Z
```

If `master` has moved since the release was cut (for example a hotfix landed),
pre-merge `master` into the release branch before opening the promotion PR:

```bash
git fetch origin master
git merge origin/master -m "chore: merge master for release"
```

## Release Backmerge

Release merge-back is backmerge-only.

Rules:

- the PR title must be `Backmerge Release X.Y.Z`
- if `develop` is already ahead on an alpha line, preserve that current line
- if meaningful unique release fixes land on an ahead `develop`, advance alpha by one on that current line
- if `develop` is not ahead yet, the backmerge may catch `develop` up to stable `X.Y.Z` without tagging
- after that stable catch-up, open a new `develop` cycle later with `Start A.B.C` when you are ready

Before creating the backmerge PR, pre-merge `develop` into the release branch
to resolve version-file divergence (develop's alpha line vs the release's stable
line):

See the [command recipe](#release-backmerge-into-develop) for the synchronization commands.

When version files conflict, preserve the intended develop line (the ahead alpha
when present, otherwise the promoted stable target) consistently in `.cz.toml`
and any project version field. Do not resolve by lexical string order.

If you need to explicitly open a new `develop` cycle after a release, use the
fixed title on the first PR for that cycle:

See the [command recipe](#release-backmerge-into-develop) for the synchronization commands.

Landing `Start A.B.C` on `develop` must produce tagged `A.B.C-alpha.0`.

## Hotfix Stabilization and Promotion

Hotfix branch work also stays Conventional Commit based.

Rules:

- creating `hotfix/*` alone does not start `rc.0`
- the first meaningful Conventional Commit starts the next patch `rc` line
- later meaningful Conventional Commits continue that same patch `rc` line
- if there is no real stabilization change, an empty `chore: open release` commit is acceptable

Promotion PR title into `master`:

```text
Hotfix X.Y.Z
```

If `master` has moved since the hotfix was created (for example another hotfix
landed), pre-merge `master` into the hotfix branch before opening the promotion
PR:

```bash
git fetch origin master
git merge origin/master -m "chore: merge master for hotfix"
```

## Hotfix Backmerge

Hotfix merge-back follows the same model as release merge-back.

Rules:

- the PR title must be `Backmerge Hotfix X.Y.Z`
- if `develop` is already ahead on an alpha line, preserve that current line
- if meaningful unique hotfix fixes land on an ahead `develop`, advance alpha by one on that current line
- if `develop` is not ahead yet, the backmerge may catch `develop` up to stable patch `X.Y.Z` without tagging
- after that stable catch-up, open a new `develop` cycle later with `Start A.B.C` when you are ready

Before creating the backmerge PR, pre-merge `develop` into the hotfix branch
to resolve version-file divergence (develop's alpha line vs the hotfix's patch
line):

See the [command recipe](#hotfix-backmerge-into-develop) for the synchronization commands.

When version files conflict, preserve the intended develop line (the ahead alpha
when present, otherwise the promoted stable target) consistently in `.cz.toml`
and any project version field. Do not resolve by lexical string order.

## Summary

```text
feature/* or bugfix/* -> develop -> tagged alpha
release/X.Y.Z         -> master  -> stable
release/X.Y.Z         -> develop -> backmerge only
hotfix/*              -> master  -> next patch stable
hotfix/*              -> develop -> backmerge only
Start X.Y.Z           -> develop -> open tagged X.Y.Z-alpha.0 when needed
```
