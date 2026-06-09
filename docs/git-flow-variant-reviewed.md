# Git Flow Variant — Reviewed

Use this flow if you want the **release branch to choose the final release line**
(like [Variant — Release-led](git-flow-variant-release-led.md)) **and** every
change to land through a PR for review, including stabilization fixes that
target an open `release/*` or `hotfix/*` branch.

This is [Variant — Release-led](git-flow-variant-release-led.md) plus an inner PR
layer, merged by squash:

- `release-fix/<name>` → `release/X.Y.Z` (squash PR)
- `hotfix-fix/<name>`  → `hotfix/<name>` (squash PR)

`develop`, promotion, and backmerge PRs are unchanged from the release-led
variant. Pick this flow when the release manager owns the version line **and**
compliance or org policy requires a review trail for every commit. Otherwise use
[Variant — Release-led](git-flow-variant-release-led.md) — the inner PR layer
adds friction.

## How this differs from the other flows

| Aspect                          | Variant — Reviewed (this doc)                             | [Variant — Release-led](git-flow-variant-release-led.md)  | [Classic — Reviewed](git-flow-classic-reviewed.md)         |
| ------------------------------- | --------------------------------------------------------- | --------------------------------------------------------- | ---------------------------------------------------------- |
| Who chooses the release line    | `release/X.Y.Z` itself (first inner PR opens `rc.0`)      | `release/X.Y.Z` itself (first commit opens `rc.0`)        | `develop` (via `Start X.Y.Z` PR)                           |
| `Start X.Y.Z` PR required       | **no** — cutting `release/X.Y.Z` is the decision          | **no** — same                                             | yes — opens next `alpha` cycle                             |
| `develop` after the cut         | continues current `alpha`; next line opens on next cut    | same                                                      | must stop the old `alpha`; next `Start` PR opens new line  |
| Commits on `release/*`          | **inner PR only** (`release-fix/*` → release)             | direct push allowed                                       | **inner PR only** (`release-fix/*` → release)              |
| Commits on `hotfix/*`           | **inner PR only** (`hotfix-fix/*` → hotfix)               | direct push allowed                                       | **inner PR only** (`hotfix-fix/*` → hotfix)                |
| Merge style                     | **squash** (inner PR title becomes the subject)           | squash or merge commit                                    | squash or merge commit                                     |
| Promotion / backmerge PR titles | `Release` / `Hotfix` / `Backmerge ...` (same as classic)  | same                                                      | same                                                       |
| Workflow file                   | `version-bump-git-flow-variant-release-led.yml` (shared)  | `version-bump-git-flow-variant-release-led.yml`           | `version-bump-git-flow-classic.yml`                        |
| Pick this when                  | release manager owns the version **and** every commit needs review | release manager owns the version, light process  | develop owns the version, compliance                       |

This flow uses the **same workflow** as the release-led variant
(`flow="variant"`). The review trail is enforced by branch protection that
requires PRs into `release/*` and `hotfix/*`; the bump logic is identical and
only reads the latest commit subject on the branch.

## Naming

- `Start X.Y.Z` opens `X.Y.Z-alpha.0` on `develop` (optional here — only to explicitly open a fresh `develop` line)
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

This flow uses **squash merges**. The squashed commit subject on `release/X.Y.Z`
or `hotfix/<name>` is the input to the rc-bump logic, so it must be the inner PR
title and a Conventional Commit.

- enable **Squash and merge**; set the default squash commit message to the PR
  title (`Pull request title` or `Pull request title and description`)
- disable `Rebase merge`
- you may disable `Merge commit` for a strict squash-only repository

Do not use the factory-default merge-commit subject
(`Merge pull request #N from ...`). That is not a Conventional Commit and the rc
bump will not advance. GitHub may append a trailing `(#123)` to the squashed
subject; the workflow matcher ignores that suffix.

## Automation Note

Current CLI helper coverage matches this flow:

- `git-tools commit --workflow-kind open-release`
- `git-tools pr --release-pr`, `--hotfix-pr`, `--backmerge-release-pr`, and `--backmerge-hotfix-pr`
- `git-tools pr --start-pr` only when you explicitly open a fresh `develop` line; pass `--workflow-version X.Y.Z` when inference is ambiguous
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

`develop` keeps producing tagged `alpha` prereleases on its current line. Feature
work into `develop` is unchanged; the reviewed inner PRs only apply to the
release and hotfix branches.

### Cut `release/X.Y.Z` (release-led — no `Start` needed)

```bash
git checkout develop
git pull origin develop
git checkout -b release/X.Y.Z
git push -u origin release/X.Y.Z
```

The release branch chooses the line, so there is no `Start` PR. `develop` keeps
its current `alpha`. Cutting the branch alone does not start `rc.0` — the first
inner PR does.

### Release branch fix via inner PR

```bash
git checkout release/X.Y.Z
git pull origin release/X.Y.Z
git checkout -b release-fix/<name>
git add -A
git-tools commit

# to open rc.0 without a real stabilization change, open an empty inner PR and
# use the CC-style PR title `chore: open release`
git commit --allow-empty -m "chore: open release"

git push -u origin release-fix/<name>
git-tools pr --base release/X.Y.Z
```

Squash-merging the inner PR pushes its Conventional Commit title onto
`release/X.Y.Z`, which opens `X.Y.Z-rc.0` on the first PR and advances
`X.Y.Z-rc.N` on later ones.

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

When the inner PR squash-merges, the push to `hotfix/<name>` triggers the bump
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

This project uses `master`. Set the GitHub default branch to `master` before you
run the local bootstrap commands below.

Configure the **squash** inner-PR merge strategy in repo settings, and protect
`release/*` and `hotfix/*` to require PRs, before opening the first
`release-fix/*` or `hotfix-fix/*` PR. See [Merge Strategy](#merge-strategy) above.

Activate the variant workflow (shared with the release-led variant):

```text
.github/workflows/version-bump-git-flow-variant-release-led.yml.example
```

## 1. Bootstrap on `master`

Same as [Variant — Release-led](git-flow-variant-release-led.md#1-bootstrap-on-master).

## 2. Feature or bugfix PR into `develop`

Same as [Variant — Release-led](git-flow-variant-release-led.md#2-feature-or-bugfix-pr-into-develop).

Feature work into `develop` is unchanged. Reviewed flow only adds inner PRs to
the release and hotfix branches, not to develop.

## 3. Release Branch Chooses the Line (Inner PRs)

The release branch chooses the final release line. In reviewed flow, no direct
commits land on `release/X.Y.Z` — every change arrives via an inner PR from a
`release-fix/<name>` branch and squash-merges with a Conventional Commit subject.

Rules:

- `release/X.Y.Z` chooses the target release tuple
- creating the branch alone does not start `rc.0`
- the first inner PR with a meaningful Conventional Commit title starts `X.Y.Z-rc.0`
- later inner PRs with meaningful Conventional Commit titles continue `X.Y.Z-rc.N`
- if there is no real stabilization change, an inner PR titled `chore: open release` is acceptable
- cutting `release/X.Y.Z` does not require a `Start` PR; `develop` continues its current `alpha` and opens the next line on the next cut

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

## 4. Release Backmerge into `develop`

Same as [Variant — Release-led](git-flow-variant-release-led.md#4-release-backmerge-into-develop).

The backmerge PR is the only `release/* -> develop` boundary crossing. It is not
affected by the inner-PR rule.

## 5. Hotfix Branch (Inner PRs)

Hotfix branch work also goes through inner PRs. Hotfixes are often a single fix,
in which case the hotfix branch holds exactly one inner PR. Multi-fix hotfix
lines work the same way as release lines.

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

## 6. Hotfix Backmerge into `develop`

Same as [Variant — Release-led](git-flow-variant-release-led.md#6-hotfix-backmerge-into-develop).

The backmerge PR is the only `hotfix/* -> develop` boundary crossing. It is not
affected by the inner-PR rule.

## 7. Summary

```text
feature/* or bugfix/* -> develop          -> tagged alpha
Start X.Y.Z           -> develop          -> open tagged X.Y.Z-alpha.0 (optional)
release-fix/*         -> release/X.Y.Z    -> inner PR (squash), opens/advances rc
release/X.Y.Z         -> master           -> stable
release/X.Y.Z         -> develop          -> backmerge only
hotfix-fix/*          -> hotfix/<name>    -> inner PR (squash), advances patch rc
hotfix/<name>         -> master           -> next patch stable
hotfix/<name>         -> develop          -> backmerge only
```
