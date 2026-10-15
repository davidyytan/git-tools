# Git Flow Classic

[Azure DevOps guides](README.md) · [Setup](setup.md) · [CLI usage](../usage.md)

Use this flow if `develop` chooses the release line first and the first PR for
the next cycle should land as `Start X.Y.Z` after cutting `release/X.Y.Z`.

Use this workflow example and activate it as
`.azure/workflows/version-bump-git-flow-classic.yml`:

```text
.azure/workflows/version-bump-git-flow-classic.yml.example
```

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

Follow [platform bootstrap](setup.md#bootstrap-master-and-develop). For Azure,
use the ordered setup runbook, including manual pipeline authorization/run.

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

### Cut `release/X.Y.Z`, then open the next `develop` cycle

```bash
git checkout develop
git pull origin develop
git checkout -b release/X.Y.Z
git push -u origin release/X.Y.Z
```

Cutting the branch does not change `develop` on its own — `develop` stays on
`X.Y.Z-alpha.N`. To stop `develop` advancing the line you are now releasing, the
next `develop` PR must land with the fixed `Start A.B.C` title (`A.B.C` a forward
step above `X.Y.Z`):

```bash
git checkout develop
git pull origin develop
git checkout -b feature/<name>

# make changes
git add -A
git-tools commit

git push -u origin feature/<name>
git-tools pr --start-pr --workflow-version A.B.C
```

Landing `Start A.B.C` on `develop` must produce `A.B.C-alpha.0`. If you instead
land an ordinary feature next, `develop` keeps producing `X.Y.Z-alpha.N` and
collides with the line `release/X.Y.Z` is stabilizing.

### Release branch work and release PR into `master`

```bash
git checkout release/X.Y.Z
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
# Replace 1.6.1 with the hotfix version already promoted to master.
git-tools pr --backmerge-hotfix-pr --workflow-version 1.6.1
```

## Feature and Bugfix Policy

Most feature and bugfix work lands on `develop` with a normal Conventional
Commit title. `develop` creates or continues tagged `alpha` prereleases.

On a freshly created `develop` branch that still matches the latest stable
release, the first develop PR may use the fixed title `Start X.Y.Z` while the
branch commit itself stays Conventional Commit based.

## Release-Line Policy

Classic flow has one key rule:

- after cutting `release/X.Y.Z`, the first PR for the next `develop` cycle
  must land as `Start A.B.C`

That means:

- once `release/X.Y.Z` exists, `develop` should stop producing `X.Y.Z-alpha.N`
- the first PR for the next line must land as `Start A.B.C`
- that fixed subject opens tagged `A.B.C-alpha.0`
- that Start-titled PR may also contain the first real changes on the new line

Example:

- before cut: `develop = 0.2.0-alpha.3`
- cut `release/0.2.0`
- land `Start 0.3.0` on `develop`
- result: `develop = 0.3.0-alpha.0`

## Release Stabilization and Promotion

The release branch does not reopen semver selection. It stabilizes the selected release line.

Rules:

- creating `release/X.Y.Z` alone does not start `rc.0`
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
- if `develop` is already ahead on an alpha line, keep that line
- if meaningful unique release fixes land on an ahead `develop`, advance alpha by one
- if `develop` is not ahead yet, the backmerge may catch `develop` up to stable `X.Y.Z` without tagging
- after that stable catch-up, open the next cycle later with `Start A.B.C` when you are ready
- if the backmerge is effectively version-only or otherwise no-op while `develop` already matches the target stable line, keeping the same version is acceptable

Before creating the backmerge PR, pre-merge `develop` into the release branch
to resolve version-file divergence (develop's alpha line vs the release's stable
line):

See the [command recipe](#release-backmerge-into-develop) for the synchronization commands.

When version files conflict, preserve the intended develop line (the ahead alpha
when present, otherwise the promoted stable target) consistently in `.cz.toml`
and any project version field. Do not resolve by lexical string order.

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
- if `develop` is already ahead on an alpha line, keep that line
- if meaningful unique hotfix fixes land on an ahead `develop`, advance alpha by one
- if `develop` is not ahead yet, the backmerge may catch `develop` up to stable patch `X.Y.Z` without tagging
- after that stable catch-up, open the next cycle later with `Start A.B.C` when you are ready

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
Start X.Y.Z           -> develop -> open tagged X.Y.Z-alpha.0
release/X.Y.Z         -> master  -> stable
release/X.Y.Z         -> develop -> backmerge only
hotfix/*              -> master  -> next patch stable
hotfix/*              -> develop -> backmerge only
```
