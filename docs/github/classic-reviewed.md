# Git Flow Classic — Reviewed

[GitHub guides](README.md) · [Setup](setup.md) · [CLI and interactive usage](../usage.md)

Use this flow if every human change must go through a PR for review, including stabilization fixes that target an open `release/*` or `hotfix/*` branch.

This is [Git Flow Classic](classic.md) plus an inner PR layer:

- `release-fix/<name>` → `release/X.Y.Z` (PR)
- `hotfix-fix/<name>`  → `hotfix/<name>` (PR)

The promotion and backmerge PRs are unchanged from classic. Pick this flow when compliance, regulated industries, or org policy require a review trail for human changes. Otherwise use classic — reviewed adds friction.

## Full Walkthrough

Follow **[Classic — Reviewed: start to finish](classic-reviewed-walkthrough.md)** for a numbered journey from `Release 0.1.0` through release, reviewed synchronization, backmerge, hotfix, and the next cycle. This page remains the policy and recipe reference.

## Subjects and Commands

Use the [shared subject protocol](../git-flow-guide.md#shared-naming-policy) and [platform setup](setup.md) before following these recipes. Replace placeholders with actual paths and versions; these are separate steps, not a single script. Direct `git-tools commit` commits by default; use `--no-commit` to review text only. `git-tools pr` generates text, not a hosted PR. Review staged files before committing. Wait for CI, pull bot commits, and fetch tags before dependent operations. Keep promotion branches until backmerge completes.

## Merge Strategy

The merge commit subject on `release/X.Y.Z` or `hotfix/<name>` is the input to the rc-bump logic. That subject must be a Conventional Commit.

Compatible GitHub merge settings for inner PRs:

- **Squash and merge** — squash commit subject is the PR title.
- **Create a merge commit** with the repo setting "Default to PR title and
  description" — merge commit subject is the PR title.

Do not use the factory-default merge-commit subject (`Merge pull request #N from ...`). That is not a Conventional Commit and the rc bump will not advance.

## Synchronization Policy

Require PRs into `release/*` and `hotfix/*` as well as the protected target branches. The CI bot must still be allowed to push its signed version commits; limit any ruleset bypass to the automation identity and review that exception. The synchronization merges shown below (`master` or `develop` into a release or hotfix branch) are direct-push examples. Under a strict no-human-direct-push policy, prepare that merge on a temporary integration branch based on the release/hotfix branch and submit an inner PR back into it instead. Resolve version-file conflicts there and wait for CI before the boundary-crossing PR. Do not bypass review merely to run the synchronization commands verbatim.

An empty `chore: open release` commit can trigger CI when direct pushes are allowed, but an empty commit alone does not provide a mergeable GitHub PR diff. For an inner PR, use a real, reviewable change with a Conventional Commit title (or an approved, auditable initialization procedure); do not rely on an empty inner PR to open `rc.0`.

## Command Recipes

### Bootstrap on `master`

Follow [platform bootstrap](setup.md#bootstrap-master-and-develop). Do this once in a fresh repository, not on every release.

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

If this is the first PR after creating a fresh `develop` line, keep the branch commit Conventional Commit based and open the PR with `Start X.Y.Z`.

### Cut `release/X.Y.Z`, then open the next `develop` cycle

```bash
git checkout develop
git pull origin develop
git checkout -b release/X.Y.Z
git push -u origin release/X.Y.Z
```

Cutting the branch does not change `develop` on its own — `develop` stays on `X.Y.Z-alpha.N`. To stop `develop` advancing the line you are now releasing, the next `develop` PR must land with the fixed `Start A.B.C` title (`A.B.C` a forward step above `X.Y.Z`):

```bash
git checkout develop
git pull origin develop
git checkout -b feature/<name>
git add -A
git-tools commit
git push -u origin feature/<name>
git-tools pr --start-pr --workflow-version A.B.C
```

Landing `Start A.B.C` on `develop` must produce `A.B.C-alpha.0`. If you instead land an ordinary feature next, `develop` keeps producing `X.Y.Z-alpha.N` and collides with the line `release/X.Y.Z` is stabilizing.

### Release branch fix via inner PR

```bash
git checkout release/X.Y.Z
git pull origin release/X.Y.Z
git checkout -b release-fix/<name>
git add -A
git-tools commit

# An inner PR must contain a real reviewable diff; an empty commit alone
# is not a mergeable GitHub PR. Use a Conventional Commit PR title.

git push -u origin release-fix/<name>
git-tools pr --base release/X.Y.Z
```

When the inner PR merges, the push to `release/X.Y.Z` triggers the bump workflow and advances `X.Y.Z-rc.N`.

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
# resolve conflicts — keep the intended target version consistent in version files
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

When the inner PR merges, the push to `hotfix/<name>` triggers the bump workflow and advances the patch `rc` line.

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
# resolve conflicts — keep the intended target version consistent in version files
git push origin hotfix/<name>
# Replace 1.6.1 with the hotfix version already promoted to master.
git-tools pr --backmerge-hotfix-pr --workflow-version 1.6.1
```

## Feature and Bugfix Policy

Same as [Git Flow Classic](classic.md#feature-and-bugfix-policy).

Feature work into `develop` is unchanged. Reviewed flow only adds inner PRs to the release and hotfix branches, not to develop.

## Release-Line Policy

Same as [Git Flow Classic](classic.md#release-line-policy).

After cutting `release/X.Y.Z`, the first PR for the next `develop` cycle must land as `Start A.B.C`.

## Release Stabilization and Promotion

The release branch does not reopen semver selection. It stabilizes the selected release line. In reviewed flow, human changes arrive via inner PRs from `release-fix/<name>`, not direct protected-branch pushes; automation still creates its authorized version commits.

Rules:

- creating `release/X.Y.Z` alone does not start `rc.0`
- the first inner PR with a meaningful Conventional Commit title starts `X.Y.Z-rc.0`
- later inner PRs with meaningful Conventional Commit titles continue `X.Y.Z-rc.N`
- an inner PR titled `chore: open release` is acceptable only when it has a real, reviewable diff; an empty commit alone does not make a mergeable GitHub PR

Branch naming:

- `release-fix/<name>` for any change targeting an open `release/X.Y.Z`
- one inner PR per logical fix; small focused PRs are easier to review

Inner PR title: a normal Conventional Commit (e.g. `fix: tighten input validation`). Do **not** use any of the reserved fixed titles (`Release X.Y.Z`, `Backmerge Release X.Y.Z`, etc.) for inner PRs — those are reserved for the boundary-crossing PRs only.

Promotion PR title into `master`:

```text
Release X.Y.Z
```

If `master` has moved since the release was cut (for example a hotfix landed), pre-merge `master` into the release branch before opening the promotion PR:

```bash
git fetch origin master
git merge origin/master -m "chore: merge master for release"
```

## Release Backmerge

Same as [Git Flow Classic](classic.md#release-backmerge).

The backmerge PR is the only `release/* -> develop` boundary crossing. It is not affected by the inner-PR rule.

## Hotfix Stabilization and Promotion

Hotfix branch work also goes through inner PRs in reviewed flow. Hotfixes are often a single fix, in which case the hotfix branch holds exactly one inner PR. Multi-fix hotfix lines work the same way as release lines.

Rules:

- creating `hotfix/<name>` alone does not start `rc.0`
- the first inner PR with a meaningful Conventional Commit title starts the next patch `rc` line
- later inner PRs with meaningful Conventional Commit titles continue that same patch `rc` line
- an inner PR titled `chore: open release` is acceptable only when it has a real, reviewable diff; an empty commit alone does not make a mergeable GitHub PR

Branch naming:

- `hotfix/<name>` is the long-lived patch line off `master`
- `hotfix-fix/<sub-name>` is the short-lived branch for each inner PR
- if a hotfix is truly one commit, you can still use one `hotfix-fix/*` PR — the policy is uniform

Inner PR title: a normal Conventional Commit. Reserved fixed titles (`Hotfix X.Y.Z`, `Backmerge Hotfix X.Y.Z`) are not allowed as inner PR titles.

Promotion PR title into `master`:

```text
Hotfix X.Y.Z
```

If `master` has moved since the hotfix was created, pre-merge `master` into the hotfix branch before opening the promotion PR:

```bash
git fetch origin master
git merge origin/master -m "chore: merge master for hotfix"
```

## Hotfix Backmerge

Same as [Git Flow Classic](classic.md#hotfix-backmerge).

The backmerge PR is the only `hotfix/* -> develop` boundary crossing. It is not affected by the inner-PR rule.

## Summary

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
