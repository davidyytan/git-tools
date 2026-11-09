# GitHub documentation

[Documentation index](../README.md) · [All platforms and modes](../git-flow-guide.md) · [Azure DevOps](../azure-devops/README.md)

GitHub configuration is split into two folders:

| Folder | What belongs here |
| --- | --- |
| [Actions](actions/README.md) | CI keys and secrets, workflow setup, quickstart, and complete Git Flow walkthroughs |
| [Rulesets](rulesets/README.md) | Optional branch policies, browser steps, screenshots, and the CLI baseline recipe |

## GitHub Actions

- [Setup: keys, secrets, workflow configuration, and permissions](actions/setup.md)
- [Returning-user quickstart](actions/quickstart.md)
- [Choose a complete flow](actions/README.md#choose-a-flow)

The walkthroughs retain their mode-specific merge strategies. A merge-only repository policy does not replace squash-based examples or their ancestry-preserving synchronization exceptions.

## Repository rules

Start with the [policy index and browser walkthroughs](rulesets/README.md):

1. [PR-only changes](rulesets/01-pr-only.md).
2. [History protection](rulesets/02-history-protection.md).
3. [Independent review](rulesets/03-independent-review.md), optional when another eligible reviewer is available.
4. [Allowed mergers](rulesets/04-allowed-mergers.md).

**Solo-developer preset: 1, 2, and 4.** The maintainer uses PRs and is the only allowed human merger; no independent approval is required. For a team that requires independent approval, add policy 3. Policy 4 restricts who may merge; it does not itself require a review.

These are generic guides: use your own repository, branches, reviewers, and automation account. They are not a personal repository rollout log.

- [CLI recipe: stage, verify, and activate the two baseline rulesets](rulesets/branch-rulesets.md)
- [Merge commit title and description: settings and screenshots](rulesets/README.md#merge-commit-title-and-description)
- [Screenshot provenance: saved settings versus unsaved examples](rulesets/screenshots/README.md)

Neither these guides nor `git-tools init` create hosted settings, install review automation, or change collaborators.
