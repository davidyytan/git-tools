# Git Flow Classic — Reviewed

Use this flow if every change must go through a PR for review, including
stabilization fixes that target an open `release/*` or `hotfix/*` branch.

This is [Git Flow Classic](git-flow-classic.md) plus an inner PR layer:

- `release-fix/<name>` → `release/X.Y.Z` (PR)
- `hotfix-fix/<name>`  → `hotfix/<name>` (PR)

The promotion and backmerge PRs are unchanged from classic. Pick this flow
when compliance, regulated industries, or org policy require a review trail
for every commit. Otherwise use classic — reviewed adds friction.

## How this differs from the other flows

| Aspect                          | [Classic](git-flow-classic.md)              | Reviewed (this doc)                            | [Variant — Release-led](git-flow-variant-release-led.md)          |
| ------------------------------- | ------------------------------------------- | ---------------------------------------------- | ----------------------------------------------------------------- |
| Who chooses the release line    | `develop` (via `Start X.Y.Z` PR)            | `develop` (via `Start X.Y.Z` PR)               | `release/X.Y.Z` itself (first real commit opens `rc.0`)           |
| Commits on `release/*`          | direct push allowed                         | **inner PR only** (`release-fix/*` → release)  | direct push allowed                                               |
| Commits on `hotfix/*`           | direct push allowed                         | **inner PR only** (`hotfix-fix/*` → hotfix)    | direct push allowed                                               |
| `Start X.Y.Z` PR required       | yes — opens next `alpha` cycle              | yes — opens next `alpha` cycle                 | no — release branch decides the line                              |
| Promotion / backmerge PRs       | `Release` / `Hotfix` / `Backmerge ...`      | same as classic                                | same as classic                                                   |
| Workflow file                   | `version-bump-git-flow-classic.yml`         | `version-bump-git-flow-classic.yml` (shared)   | `version-bump-git-flow-variant-release-led.yml`                   |
| Pick this when                  | small team, light process                   | compliance / regulated industries              | release-line decision lives with the release manager, not develop |

Use the classic workflow example and activate it as
`.github/workflows/version-bump-git-flow-classic.yml`:

```text
.github/workflows/version-bump-git-flow-classic.yml.example
```

This guide supports either squash merge or merge commits. In both styles, the
final commit subject on the target branch must be the PR title.

## Naming

- `Start X.Y.Z` opens `X.Y.Z-alpha.0` on `develop`
- `Release X.Y.Z` is only for `release/* -> master`
- `Hotfix X.Y.Z` is only for `hotfix/* -> master`
- `Backmerge Release X.Y.Z` is only for `release/* -> develop`
- `Backmerge Hotfix X.Y.Z` is only for `hotfix/* -> develop`

Inner PR titles (`release-fix/* -> release/X.Y.Z` and
`hotfix-fix/* -> hotfix/<name>`) stay normal Conventional Commits. If a release
branch needs to open `rc.0` without a real stabilization change, the inner PR
title may be:

```text
chore: open release
```

## Merge Strategy

The merge commit subject on `release/X.Y.Z` or `hotfix/<name>` is the input to
the rc-bump logic. That subject must be a Conventional Commit.

Compatible GitHub merge settings for inner PRs:

- **Squash and merge** — squash commit subject is the PR title.
- **Create a merge commit** with the repo setting "Default to PR title and
  description" — merge commit subject is the PR title.

Do not use the factory-default merge-commit subject
(`Merge pull request #N from ...`). That is not a Conventional Commit and the
rc bump will not advance.

## Automation Note

Current CLI helper coverage matches this flow:

- `git-tools commit --workflow-kind open-release`
- `git-tools pr --start-pr`, `--release-pr`, `--hotfix-pr`, `--backmerge-release-pr`, and `--backmerge-hotfix-pr`
- pass `--workflow-version X.Y.Z` when Start or Backmerge inference is ambiguous
- inner PRs use ordinary `git-tools pr --base <release-or-hotfix-branch>` with no fixed-title flag

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

If this is the first PR after creating a fresh `develop` line, keep the branch
commit Conventional Commit based and open the PR with `Start X.Y.Z`.

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
git add -A
git-tools commit
git push -u origin feature/<name>
git-tools pr --start-pr --workflow-version A.B.C
```

Landing `Start A.B.C` on `develop` must produce `A.B.C-alpha.0`. If you instead
land an ordinary feature next, `develop` keeps producing `X.Y.Z-alpha.N` and
collides with the line `release/X.Y.Z` is stabilizing.

### Release branch fix via inner PR

```bash
git checkout release/X.Y.Z
git pull origin release/X.Y.Z
git checkout -b release-fix/<name>
git add -A
git-tools commit

# if you need to open rc.0 without a real stabilization change,
# use an empty commit and a CC-style PR title `chore: open release`
git commit --allow-empty -m "chore: open release"

git push -u origin release-fix/<name>
git-tools pr --base release/X.Y.Z
```

When the inner PR merges, the push to `release/X.Y.Z` triggers the bump
workflow and advances `X.Y.Z-rc.N`.

### Release PR into `master`

```bash
git checkout release/X.Y.Z
git pull origin release/X.Y.Z

# if master has moved since the release was cut (e.g. a hotfix landed)
git fetch origin master
git merge origin/master -m "chore: merge master for release"

git push origin release/X.Y.Z
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

### Hotfix branch fix via inner PR

```bash
git checkout master
git pull origin master
git checkout -b hotfix/<name>
git push -u origin hotfix/<name>

# for each fix on the hotfix line:
git checkout hotfix/<name>
git pull origin hotfix/<name>
git checkout -b hotfix-fix/<sub-name>
git add -A
git-tools commit
git push -u origin hotfix-fix/<sub-name>
git-tools pr --base hotfix/<name>
```

When the inner PR merges, the push to `hotfix/<name>` triggers the bump
workflow and advances the patch `rc` line.

### Hotfix PR into `master`

```bash
git checkout hotfix/<name>
git pull origin hotfix/<name>

# if master has moved since the hotfix was created (e.g. another hotfix landed)
git fetch origin master
git merge origin/master -m "chore: merge master for hotfix"

git push origin hotfix/<name>
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

Configure the inner-PR merge strategy in repo settings before opening the first
`release-fix/*` or `hotfix-fix/*` PR. See [Merge Strategy](#merge-strategy)
above.

## 1. Bootstrap on `master`

Same as [Git Flow Classic](git-flow-classic.md#1-bootstrap-on-master).

## 2. Feature or bugfix PR into `develop`

Same as [Git Flow Classic](git-flow-classic.md#2-feature-or-bugfix-pr-into-develop).

Feature work into `develop` is unchanged. Reviewed flow only adds inner PRs to
the release and hotfix branches, not to develop.

## 3. Release Cut and Next Develop Cycle

Same as [Git Flow Classic](git-flow-classic.md#3-release-cut-and-next-develop-cycle).

After cutting `release/X.Y.Z`, the first PR for the next `develop` cycle must
land as `Start A.B.C`.

## 4. Release Branch (Inner PRs)

The release branch does not reopen semver selection. It stabilizes the
selected release line. In reviewed flow, no direct commits land on
`release/X.Y.Z` — every change arrives via an inner PR from a
`release-fix/<name>` branch.

Rules:

- creating `release/X.Y.Z` alone does not start `rc.0`
- the first inner PR with a meaningful Conventional Commit title starts `X.Y.Z-rc.0`
- later inner PRs with meaningful Conventional Commit titles continue `X.Y.Z-rc.N`
- if there is no real stabilization change, an inner PR titled `chore: open release` is acceptable

Branch naming:

- `release-fix/<name>` for any change targeting an open `release/X.Y.Z`
- one inner PR per logical fix; small focused PRs are easier to review

Inner PR title: a normal Conventional Commit (e.g. `fix: tighten input validation`).
Do **not** use any of the reserved fixed titles (`Release X.Y.Z`,
`Backmerge Release X.Y.Z`, etc.) for inner PRs — those are reserved for the
boundary-crossing PRs only.

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

Same as [Git Flow Classic](git-flow-classic.md#5-release-backmerge-into-develop).

The backmerge PR is the only `release/* -> develop` boundary crossing. It is
not affected by the inner-PR rule.

## 6. Hotfix Branch (Inner PRs)

Hotfix branch work also goes through inner PRs in reviewed flow. Hotfixes are
often a single fix, in which case the hotfix branch holds exactly one inner PR.
Multi-fix hotfix lines work the same way as release lines.

Rules:

- creating `hotfix/<name>` alone does not start `rc.0`
- the first inner PR with a meaningful Conventional Commit title starts the next patch `rc` line
- later inner PRs with meaningful Conventional Commit titles continue that same patch `rc` line
- if there is no real stabilization change, an inner PR titled `chore: open release` is acceptable

Branch naming:

- `hotfix/<name>` is the long-lived patch line off `master`
- `hotfix-fix/<sub-name>` is the short-lived branch for each inner PR
- if a hotfix is truly one commit, you can still use one `hotfix-fix/*` PR — the policy is uniform

Inner PR title: a normal Conventional Commit. Reserved fixed titles
(`Hotfix X.Y.Z`, `Backmerge Hotfix X.Y.Z`) are not allowed as inner PR titles.

Promotion PR title into `master`:

```text
Hotfix X.Y.Z
```

If `master` has moved since the hotfix was created, pre-merge `master` into the
hotfix branch before opening the promotion PR:

```bash
git fetch origin master
git merge origin/master -m "chore: merge master for hotfix"
```

## 7. Hotfix Backmerge into `develop`

Same as [Git Flow Classic](git-flow-classic.md#7-hotfix-backmerge-into-develop).

The backmerge PR is the only `hotfix/* -> develop` boundary crossing. It is
not affected by the inner-PR rule.

## 8. Summary

```text
feature/* or bugfix/* -> develop          -> tagged alpha
Start X.Y.Z           -> develop          -> open tagged X.Y.Z-alpha.0
release-fix/*         -> release/X.Y.Z    -> inner PR, advances rc
release/X.Y.Z         -> master           -> stable
release/X.Y.Z         -> develop          -> backmerge only
hotfix-fix/*          -> hotfix/<name>    -> inner PR, advances patch rc
hotfix/<name>         -> master           -> next patch stable
hotfix/<name>         -> develop          -> backmerge only
```
