# Git Flow Variant — Reviewed

[Azure DevOps guides](README.md) · [Setup](setup.md) · [CLI usage](../usage.md)

Use this flow if you want the **release branch to choose the final release line** (like [Variant — Release-led](release-led.md)) **and** every human change to land through a PR for review, including stabilization fixes that target an open `release/*` or `hotfix/*` branch.

This is [Variant — Release-led](release-led.md) plus an inner PR layer. Ordinary stabilization changes use squash:

- `release-fix/<name>` → `release/X.Y.Z` (squash stabilization PR)
- `hotfix-fix/<name>`  → `hotfix/<name>` (squash stabilization PR)

The Azure walkthrough's synchronization and boundary-backmerge steps instead use ancestry-preserving **Merge (no fast-forward)**; see [Merge Strategy](#merge-strategy).

`develop`, promotion, and backmerge PRs are unchanged from the release-led variant. Pick this flow when the release manager owns the version line **and** compliance or org policy requires a review trail for human changes. Otherwise use [Variant — Release-led](release-led.md) — the inner PR layer adds friction.

## Full Walkthrough

Follow **[Release-led — Reviewed: start to finish](release-led-reviewed-walkthrough.md)** for a numbered journey from Azure setup and `Release 0.1.0` through release, reviewed synchronization, backmerge, hotfix, and the next cycle. This page remains the policy and recipe reference.

## Subjects and Commands

Use the [shared subject protocol](../git-flow-guide.md#shared-naming-policy) and [platform setup](setup.md) before following these recipes. Replace placeholders with actual paths and versions; these are separate steps, not a single script. Direct `git-tools commit` commits by default; use `--no-commit` to review text only. `git-tools pr` generates text, not a hosted PR. Review staged files before committing. Wait for CI, pull bot commits, and fetch tags before dependent operations. Keep promotion branches until backmerge completes.

## Merge Strategy

Ordinary feature and stabilization PRs use **squash merges**. The squashed commit subject on `release/X.Y.Z` or `hotfix/<name>` is the input to the rc-bump logic, so it must be the inner PR title and a Conventional Commit.

- Complete ordinary stabilization inner PRs using **Squash commit** and set the
  final subject to the PR title.
- The [numbered Azure walkthrough](release-led-reviewed-walkthrough.md) requires
  **Merge (no fast-forward)** for its synchronization inner PRs and boundary
  backmerges into `develop`. Retain the merge parents and untagged preparation
  bump anchors; do not squash those steps.
- Configure **Limit merge types** on the affected targets to permit both required
  styles, and choose the method specified for each step. This Azure recipe is
  **not a strict squash-only end-to-end flow**. Prohibit rebase completion.
- Preserve the exact specified PR/completion subject; do not leave an unrelated
  generated subject in the completion dialog.

Azure may prefix the subject with `Merged PR 42:`; the supported engine normalizes that prefix. The remaining subject must still be the Conventional Commit PR title. See [setup merge settings](setup.md#merge-settings).

## Synchronization Policy

Require reviewers and PRs into `release/*` and `hotfix/*` through Azure Repos branch policies. Apply policies to each new stabilization branch, or use an administrator-managed branch-prefix policy. Do not grant developers blanket policy bypass. The automation identity may need a narrowly approved push exception for generated version commits; see [setup](setup.md#7-grant-build-service-permissions).

The synchronization snippets below describe the Git merge subjects and conflict resolutions required by the engine. If the target stabilization branch requires PRs, perform those merges on a temporary `release-fix/*` or `hotfix-fix/*` source branch and submit an inner PR instead of directly pushing the protected branch. For preparation merges, preserve the exact subject `chore: merge master for release`, `chore: merge master for hotfix`, or `chore: merge develop for backmerge` as appropriate; this is synchronization, not a new stabilization fix. Use the ancestry-preserving merge method specified by the walkthrough for these synchronization PRs and their boundary backmerges. Pull the completed PR and automation result before generating the promotion or backmerge text. Keep the promotion branch until its backmerge is complete; do not select source-branch deletion early.

An empty commit may not yield a file diff that Azure Repos can use to create an inner PR. To use the engine's accepted opener subject `chore: open release`, include a small legitimate tracked stabilization/documentation change and use that inner PR title. Do not rely on an empty inner PR or bypass the review policy with a direct opener push.

## Command Recipes

### Bootstrap on `master`

Follow [platform bootstrap](setup.md#bootstrap-master-and-develop). For Azure, use the ordered setup runbook, including manual pipeline authorization/run.

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

`develop` keeps producing tagged `alpha` prereleases on its current line. Feature work into `develop` is unchanged; the reviewed inner PRs only apply to the release and hotfix branches.

### Cut `release/X.Y.Z` (release-led — no `Start` needed)

```bash
git checkout develop
git pull origin develop
git checkout -b release/X.Y.Z
git push -u origin release/X.Y.Z
```

The release branch chooses the line, so there is no `Start` PR. `develop` keeps its current `alpha`. Cutting the branch alone does not start `rc.0` — the first inner PR does.

### Release branch fix via inner PR

```bash
git checkout release/X.Y.Z
git pull origin release/X.Y.Z
git checkout -b release-fix/<name>
git add -A
git-tools commit

# An inner PR needs a real reviewable diff; an empty commit may not
# provide a PR Azure Repos can create. Use a Conventional Commit PR title.

git push -u origin release-fix/<name>
git-tools pr --base release/X.Y.Z
```

Squash-merging the inner PR pushes its Conventional Commit title onto `release/X.Y.Z`, which opens `X.Y.Z-rc.0` on the first PR and advances `X.Y.Z-rc.N` on later ones.

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

When the inner PR squash-merges, the push to `hotfix/<name>` triggers the bump workflow and advances the patch `rc` line.

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

Same as [Variant — Release-led](release-led.md#feature-and-bugfix-policy).

Feature work into `develop` is unchanged. Reviewed flow only adds inner PRs to the release and hotfix branches, not to develop.

## Release-Line Policy

The release branch selects the target; cutting it does not itself open `rc.0`. An optional `Start` PR opens a new develop line independently of this cut.

## Release Stabilization and Promotion

The release branch chooses the final release line. Human changes arrive via inner PRs from `release-fix/<name>`, not direct protected-branch pushes; automation still creates its authorized version commits. Stabilization PRs squash-merge with a Conventional Commit subject; synchronization PRs follow the ancestry-preserving exceptions above.

Rules:

- `release/X.Y.Z` chooses the target release tuple
- creating the branch alone does not start `rc.0`
- the first inner PR with a meaningful Conventional Commit title starts `X.Y.Z-rc.0`
- later inner PRs with meaningful Conventional Commit titles continue `X.Y.Z-rc.N`
- if there is no real stabilization change, an inner PR titled `chore: open release` is acceptable
- cutting `release/X.Y.Z` does not require a `Start` PR; `develop` continues its current `alpha`; use `Start` to explicitly open a new develop line

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

Same as [Variant — Release-led](release-led.md#release-backmerge).

The backmerge PR is the only `release/* -> develop` boundary crossing. It is not affected by the inner-PR rule.

## Hotfix Stabilization and Promotion

Hotfix branch work also goes through inner PRs. Hotfixes are often a single fix, in which case the hotfix branch holds exactly one inner PR. Multi-fix hotfix lines work the same way as release lines.

Rules:

- creating `hotfix/<name>` alone does not start `rc.0`
- the first inner PR with a meaningful Conventional Commit title starts the next patch `rc` line
- later inner PRs with meaningful Conventional Commit titles continue that same patch `rc` line
- if there is no real stabilization change, an inner PR titled `chore: open release` is acceptable

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

Same as [Variant — Release-led](release-led.md#hotfix-backmerge).

The backmerge PR is the only `hotfix/* -> develop` boundary crossing. It is not affected by the inner-PR rule.

## Summary

```text
feature/* or bugfix/* -> develop          -> tagged alpha
Start X.Y.Z           -> develop          -> open tagged X.Y.Z-alpha.0 (optional)
release-fix/*         -> release/X.Y.Z    -> stabilization PR (squash), opens/advances rc
release/X.Y.Z         -> master           -> stable
release/X.Y.Z         -> develop          -> backmerge only
hotfix-fix/*          -> hotfix/<name>    -> stabilization PR (squash), advances patch rc
hotfix/<name>         -> master           -> next patch stable
hotfix/<name>         -> develop          -> backmerge only
```
