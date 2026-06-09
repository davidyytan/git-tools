# Git Flow Classic

Use this flow if `develop` chooses the release line first and the first PR for
the next cycle should land as `Start X.Y.Z` after cutting `release/X.Y.Z`.

Use this workflow example and activate it as
`.github/workflows/version-bump-git-flow-classic.yml`:

```text
.github/workflows/version-bump-git-flow-classic.yml.example
```

This guide supports either squash merge or merge commits. For the closest
classic Git Flow feel, use merge commits for feature, release, and hotfix PRs.
In both styles, the final commit subject on the target branch must be the PR
title.

## Naming

- `Start X.Y.Z` opens `X.Y.Z-alpha.0` on `develop`
- `Release X.Y.Z` is only for `release/* -> master`
- `Hotfix X.Y.Z` is only for `hotfix/* -> master`
- `Backmerge Release X.Y.Z` is only for `release/* -> develop`
- `Backmerge Hotfix X.Y.Z` is only for `hotfix/* -> develop`

Release and hotfix branch work stays normal Conventional Commits. If a release
branch needs to open `rc.0` without a real stabilization change, use:

```text
chore: open release
```

## Automation Note

Current CLI helper coverage matches this flow:

- `git-tools commit --workflow-kind open-release`
- `git-tools pr --start-pr`, `--release-pr`, `--hotfix-pr`, `--backmerge-release-pr`, and `--backmerge-hotfix-pr`
- pass `--workflow-version X.Y.Z` when Start or Backmerge inference is ambiguous

## TL;DR

### Bootstrap on `master`

```bash
git init
git remote add origin git@github.com:<owner>/<repo>.git
git-tools init
git add -A
git commit -m "Release 0.1.0"
git push -u origin master
```

Wait for the CI workflow on `master` to turn the bootstrap baseline into `0.1.0`, then update local `master` and create `develop` from that bumped stable branch:

```bash
git checkout master
git pull origin master
git checkout -b develop
git push -u origin develop
```

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

# if you need to open rc.0 without a real stabilization change
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
# resolve conflicts — for version files, keep the higher version
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
# resolve conflicts — for version files, keep the higher version
git push origin hotfix/<name>
git-tools pr --backmerge-hotfix-pr
```

## 0. Set Up GitHub First

Read [GitHub Setup](github-setup.md) first.

This project uses `master`. Set the GitHub default branch to `master` before
you run the local bootstrap commands below.

## 1. Bootstrap on `master`

```bash
git init
git remote add origin git@github.com:<owner>/<repo>.git
git-tools init
git add -A
git commit -m "Release 0.1.0"
git push -u origin master
```

Notes:

- `Release 0.0.1` is also accepted for the first commit.
- Direct `git-tools init` seeds `.cz.toml` with `0.0.1`.
- The first workflow run on `master` turns that baseline into `0.1.0`.

After that bump lands, update local `master`, create `develop` from the bumped stable branch, and push it:

```bash
git checkout master
git pull origin master
git checkout -b develop
git push -u origin develop
```

## 2. Feature or bugfix PR into `develop`

Most feature and bugfix work lands on `develop` with a normal Conventional
Commit title. `develop` creates or continues tagged `alpha` prereleases.

On a freshly created `develop` branch that still matches the latest stable
release, the first develop PR may use the fixed title `Start X.Y.Z` while the
branch commit itself stays Conventional Commit based.

## 3. Release Cut and Next Develop Cycle

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

## 4. Release Branch

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

## 5. Release Backmerge into `develop`

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

```bash
git fetch origin develop
git merge origin/develop -m "chore: merge develop for backmerge"
# resolve conflicts — for version files, keep the higher version
git push origin release/X.Y.Z
```

When version files conflict, keep the higher version and still merge the
branch code changes.

## 6. Hotfix Branch and Promotion

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

## 7. Hotfix Backmerge into `develop`

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

```bash
git fetch origin develop
git merge origin/develop -m "chore: merge develop for backmerge"
# resolve conflicts — for version files, keep the higher version
git push origin hotfix/<name>
```

When version files conflict, keep the higher version and still merge the
branch code changes.

## 8. Summary

```text
feature/* or bugfix/* -> develop -> tagged alpha
Start X.Y.Z           -> develop -> open tagged X.Y.Z-alpha.0
release/X.Y.Z         -> master  -> stable
release/X.Y.Z         -> develop -> backmerge only
hotfix/*              -> master  -> next patch stable
hotfix/*              -> develop -> backmerge only
```
