# GitHub Setup

## Set Up GitHub First

- Set up GitHub before you run any local bootstrap commands.
- This project uses `master`.
- Before you run `git-tools init`, the default branch must already be `master`.

## What GitHub Must Have

### Workflow file

Activate exactly one workflow by copying or renaming one example to a real
`.yml` file in `.github/workflows/`:

- `.github/workflows/version-bump-git-flow-variant-release-led.yml.example` -> `.github/workflows/version-bump-git-flow-variant-release-led.yml`
- `.github/workflows/version-bump-git-flow-classic.yml.example` -> `.github/workflows/version-bump-git-flow-classic.yml`

### Required secrets

- `BOT_SSH_SECRETKEY`
- `BOT_GPG_SECRETKEY`

### Merge settings

This flow supports two GitHub merge styles:

- squash merge
- merge commit

Do not use `Rebase merge` for this automated flow.

The rule that matters is the final commit subject on the target branch. GitHub
may append a trailing `(#123)` to merged workflow PR subjects; the workflow
matcher ignores that suffix.

#### Subjects into `develop`

- most feature and bugfix PRs into `develop` land with a Conventional Commit
  subject
- the first PR on a fresh develop line may land with `Start X.Y.Z`
- release backmerge PRs into `develop` must land with `Backmerge Release X.Y.Z`
- hotfix backmerge PRs into `develop` must land with `Backmerge Hotfix X.Y.Z`

#### Subjects into `master`

- release promotion PRs into `master` must land with `Release X.Y.Z`
- hotfix promotion PRs into `master` must land with `Hotfix X.Y.Z`

#### Squash merge profile

- enable `Squash merge`
- set the default squash commit message to use the PR title, ideally `Pull
  request title and description`
- disable `Rebase merge`
- you may disable `Merge commit` if you want a strict squash-only repository

#### Merge commit profile

- enable `Merge commit`
- set the default merge commit message to `Pull request title` or `Pull request
  title and description`
- disable `Rebase merge`
- for the closest classic Git Flow feel, use merge commits for `feature/*`,
  `bugfix/*`, `release/*`, and `hotfix/*` PRs

GitHub's default merge-commit subject `Merge pull request #...` is not suitable
for this flow because the version workflow reads the latest commit subject.

Why:

- `develop` bump decisions depend on the final merged subject
- `master` release finalization depends on the merged prerelease state
- backmerges into `develop` must be distinguishable from release promotion
- squash and merge-commit styles both work when that final subject is the PR
  title

## Automation Note

Current CLI support covers the documented fixed-title workflow:

- `git-tools commit --workflow-kind open-release`
- `git-tools pr --start-pr`, `--release-pr`, `--hotfix-pr`, `--backmerge-release-pr`, and `--backmerge-hotfix-pr`
- pass `--workflow-version X.Y.Z` when Start or Backmerge PR helpers cannot infer the exact tuple safely

## After GitHub Is Ready

Continue with one of these standalone guides:

- [Git Flow Classic](git-flow-classic.md)
- [Git Flow Classic — Reviewed](git-flow-classic-reviewed.md) (classic + inner PR layer for compliance)
- [Git Flow Variant — Release-led](git-flow-variant-release-led.md)
- [Git Flow Variant — Reviewed](git-flow-variant-reviewed.md) (release-led + inner PR layer, squash)
