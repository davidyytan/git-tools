# GitHub Git Flow Guides

These guides use GitHub pull requests and Actions to manage signed version
commits and release tags. Start with [GitHub Setup](setup.md), then choose one
flow. Use [CLI and interactive usage](../usage.md) for installation-independent
command/navigation guidance, and [Azure DevOps guides](../azure-devops/README.md)
if your repository is hosted there instead.

## Choose a Flow

| Guide | Release-line decision | Stabilization changes | Merge style |
| --- | --- | --- | --- |
| [Classic](classic.md) | `develop` selects the line; `Start A.B.C` opens the next cycle after a release cut | Direct pushes to release/hotfix branches | Squash or merge commit |
| [Classic — Reviewed](classic-reviewed.md) | Same as classic | Inner PRs into release/hotfix branches | Squash or merge commit |
| [Release-led](release-led.md) | `release/X.Y.Z` chooses the final line | Direct pushes to release/hotfix branches | Squash or merge commit |
| [Release-led — Reviewed](release-led-reviewed.md) | Same as release-led | Inner PRs into release/hotfix branches | Squash |

Classic and classic-reviewed share the classic workflow. Release-led and
release-led-reviewed share the release-led workflow. Activate **exactly one**
workflow, not one per guide. Reviewed flows add a review layer, not a different
versioning implementation. See [setup](setup.md) for merge settings, secrets,
bot permissions, and the CI tool-source ref caveat.

## Shared Subject Policy

The final commit subject on the target branch must match the intended PR title:

- `Start X.Y.Z`: opens tagged `X.Y.Z-alpha.0` on `develop`.
- `Release X.Y.Z`: release promotion into `master` only.
- `Hotfix X.Y.Z`: hotfix promotion into `master` only.
- `Backmerge Release X.Y.Z`: release backmerge into `develop` only.
- `Backmerge Hotfix X.Y.Z`: hotfix backmerge into `develop` only.

Ordinary feature/bugfix and stabilization subjects are Conventional Commits.
GitHub's trailing `(#123)` suffix is accepted by the fixed-title matcher.
Do not use the default `Merge pull request #...` subject or rebase merging for
this documented automation. With merge commits, configure the subject to use
the PR title; with squash, use the PR title as the squash subject.

## Version Lifecycle

- Bootstrap explicitly with `git init -b master`, then wait for the stable CI
  bump before creating `develop`.
- `develop` creates or continues tagged alpha prereleases.
- The first meaningful release/hotfix branch change opens `rc.0`; later ones
  advance that RC line. Branch creation alone is not a version bump.
- Promotion into `master` finalizes the prerelease to stable.
- Backmerges preserve an ahead alpha line and may advance it for meaningful
  unique fixes; otherwise they can catch `develop` up to stable without tagging.
- Open a new develop line with `Start X.Y.Z` when appropriate. Classic requires
  a next-cycle Start after cutting a release; release-led does not require one
  merely because a release branch was cut.

Each detailed guide includes bootstrap, feature work, stabilization, promotion,
conflict resolution, and release/hotfix backmerges. Wait for CI and pull the
bot's version commits at each boundary.

## Direct Commands or Interactive Navigation

Use the direct command blocks in the selected guide for reproducible flags and
branch targets. Alternatively, run `git-tools` with no subcommand in an
interactive terminal and navigate to the corresponding operation. Keep the
same base branch, workflow kind, fixed title, and workflow version; use a direct
command when a required option is not available interactively. See
[CLI and interactive usage](../usage.md) for details. Checkout, staging, merges,
and pushes remain ordinary shell Git commands.
