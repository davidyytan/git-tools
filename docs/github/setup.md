# GitHub Setup

[GitHub guides](README.md) · [Setup](setup.md) · [CLI and interactive usage](../usage.md)

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

### Tool-source ref and bot identity

The workflow clones `GIT_TOOLS_REPO` separately from the repository being
versioned. Its `GIT_TOOLS_REF` selects the implementation of the version
strategy, not your application's default branch. The supplied classic example
currently uses `develop`; the release-led example uses `master`. Inspect and
set this value explicitly before activation: the selected ref must contain
`decide_version_strategy`, the bump runner, and the fixed-title/backmerge
behavior described by these guides. Local edits or installing a newer CLI do
not update that remote CI clone.

For reproducible CI, use a maintained release tag that contains the required
behavior rather than a moving development branch. The examples use
`git clone --branch "$GIT_TOOLS_REF"`, which accepts a branch or tag, **not an
arbitrary commit SHA**; checking out a SHA requires adapting the clone/fetch
step. Keep exactly one version workflow active to avoid competing version
commits and tags.

Set `GIT_BOT_NAME` and `GIT_BOT_EMAIL` to your automation identity. Copy the
chosen example from this repository:

- [Classic workflow example](../../.github/workflows/version-bump-git-flow-classic.yml.example)
- [Release-led workflow example](../../.github/workflows/version-bump-git-flow-variant-release-led.yml.example)

### Required secrets

- `BOT_SSH_SECRETKEY`
- `BOT_GPG_SECRETKEY`

`BOT_SSH_SECRETKEY` is the private SSH key for an identity allowed to write to
the target repository (for example, a write-enabled deploy key or bot account).
`BOT_GPG_SECRETKEY` is the private signing key used for version commits and
tags. Register the matching public keys as appropriate, store private keys
only in Actions secrets, and do not commit them to the repository.

Branch protections/rulesets must permit this bot to push signed version
commits and tags on the workflow's target branches. In reviewed flows, require
human changes to arrive through PRs while narrowly granting the automation
identity the required bypass. The workflow's final `git push` uses the SSH
checkout credentials; merely granting `GITHUB_TOKEN` write permissions does
not make an SSH identity writable. Validate bootstrap in a test repository
before enforcing the final protections.

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

## Direct CLI and Interactive Navigation

The flow guides show direct commands, including `git-tools init`,
`git-tools commit`, and `git-tools pr`. As an alternative, run `git-tools`
without a subcommand in an interactive terminal and navigate to the operation
you need. Use the same workflow kind, base branch, fixed title, and explicit
version as the direct examples; use the direct command if an interactive path
does not expose a required option. See [CLI and interactive usage](../usage.md)
for navigation details. GitHub settings and ordinary Git commands are still
performed separately.

## After GitHub Is Ready

Continue with one of these standalone guides:

- [Git Flow Classic](classic.md)
- [Git Flow Classic — Reviewed](classic-reviewed.md) (classic + inner PR layer for compliance)
- [Git Flow Variant — Release-led](release-led.md)
- [Git Flow Variant — Reviewed](release-led-reviewed.md) (release-led + inner PR layer, squash)

## Publication and Recovery

The selected engine ref must also contain `git_tools.generators.publish`.
Publishing dry-runs an atomic push, logs its choice, and falls back only when the
server explicitly lacks atomic support. Other failures stop. See
[publication and missing-tag recovery](../publication.md).
