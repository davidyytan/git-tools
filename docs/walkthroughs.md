# Full workflow walkthroughs

[Project README](../README.md) · [Documentation index](README.md) · [Flow comparison](git-flow-guide.md)

**Start here to take a fresh repository through a complete release lifecycle.** These are numbered journeys with concrete changes and versions, not collections of independent command recipes.

Choose your hosting platform and **one** mode:

| Mode | When to choose it | GitHub walkthrough | Azure DevOps walkthrough |
| --- | --- | --- | --- |
| Classic | Develop selects the release line; explicitly open the next develop cycle after cutting a release | [Start to finish](github/classic-walkthrough.md) | [Start to finish](azure-devops/classic-walkthrough.md) |
| Classic — Reviewed | Classic, with human stabilization and synchronization changes reviewed through inner PRs | [Start to finish](github/classic-reviewed-walkthrough.md) | [Start to finish](azure-devops/classic-reviewed-walkthrough.md) |
| Release-led | The release branch selects its target; no mandatory next-cycle Start PR after the cut | [Start to finish](github/release-led-walkthrough.md) | [Start to finish](azure-devops/release-led-walkthrough.md) |
| Release-led — Reviewed | Release-led, with human stabilization and synchronization changes reviewed through inner PRs | [Start to finish](github/release-led-reviewed-walkthrough.md) | [Start to finish](azure-devops/release-led-reviewed-walkthrough.md) |

## What each walkthrough covers

1. Install the CLI and configure the platform's automation identity, signing, permissions, and single versioning adapter.
2. Initialize `.cz.toml` at `0.0.1`, commit **`Release 0.1.0`** on `master`, and wait for CI to publish stable `0.1.0` and its tag. Azure includes pipeline creation, authorization, and the manual first run.
3. Pull the published commit and fetch tags, then create `develop`.
4. Deliver real feature and bugfix changes through hosted PRs and verify alpha versions.
5. Cut `release/0.2.0`, manage the next develop cycle according to the selected mode, and stabilize an RC.
6. Promote the release to `master`, verify stable publication, and backmerge without resetting the ahead develop line.
7. Ship a production hotfix, promote it, and backmerge it.
8. Resume ordinary tagged development and begin the next cycle.

Every transition states the branch, PR target and exact title where required, hosting action, expected CI version/tag behavior, and local synchronization commands. Local `git-tools pr` generates text; **you still create and complete the hosted PR**.

## Read before following the commands

- These walkthroughs are for **fresh repositories**, not migration or repair of an existing release history. Do not repeat bootstrap in an initialized project.
- Follow one walkthrough in order. Do not mix its merge settings or version-resolution steps with another platform's example: the GitHub walkthroughs demonstrate develop-based integration PRs, while Azure's examples retain source ancestry with merge-commit backmerges.
- Stop at every editing, review, CI, and verification checkpoint. The pages are not scripts to paste wholesale.
- Keep release/hotfix branches until promotion **and** backmerge finish. Squash merges and untagged preparation bumps need the specific history safeguards documented in the chosen walkthrough.
- The version sequences have been checked against the local engine. Hosted permissions, signing, branch protections, and publication still need validation in a test repository.

For policy and individual recipes after completing a walkthrough, use the [flow references](git-flow-guide.md). For failed publication, stop and consult [recovery](publication.md); do not force-push or bootstrap again.
