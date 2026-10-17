# Git Flow Guide

## Start with a Full Walkthrough

For a fresh repository, use the **[numbered end-to-end walkthroughs](walkthroughs.md)**. They cover setup and `Release 0.1.0`, feature work, release stabilization/promotion, backmerges, hotfixes, and the next cycle with concrete versions and CI checkpoints. This page is the shared policy/reference, not the complete procedural guide.

## Choose Your Platform First

1. Open [GitHub guides](github/README.md) or [Azure DevOps guides](azure-devops/README.md).
2. Complete that platform's setup and choose a flow below.
3. Use [Direct CLI and Interactive Usage](usage.md) for command examples and
   step-by-step terminal menu navigation.

| Flow | Version policy | GitHub guide | Azure DevOps guide |
| --- | --- | --- | --- |
| Classic | `develop` chooses the release line | [Classic](github/classic.md) | [Classic](azure-devops/classic.md) |
| Classic — Reviewed | Classic with inner stabilization PRs | [Reviewed](github/classic-reviewed.md) | [Reviewed](azure-devops/classic-reviewed.md) |
| Release-led | `release/X.Y.Z` chooses the release line | [Release-led](github/release-led.md) | [Release-led](azure-devops/release-led.md) |
| Release-led — Reviewed | Release-led with squash inner PRs | [Reviewed](github/release-led-reviewed.md) | [Reviewed](azure-devops/release-led-reviewed.md) |

Both platforms supply classic and release-led example adapters. Reviewed flows share their base adapter: enable **one** versioning workflow/pipeline per repo, not both adapters. Templates are examples to copy/configure in the target repo; their presence does not certify a live run in your organization. See each setup guide for supported engine refs, signing, permissions, and merge settings. `git-tools init` creates `.cz.toml` only; it does not install either adapter or configure hosting. These recipes assume `master` and `develop`, full history and tags, and fresh-repository bootstrap. Existing projects need a separate migration plan. Versioning CI does not require an LLM key; normal local commit and PR generation does. Before provider use or configuring custom sync targets, read the current [configuration](configuration.md#current-limitations) and [versioning](versioning.md#current-limitations) limitations.

## Shared Naming Policy

- `Start X.Y.Z` opens `X.Y.Z-alpha.0` on `develop`
- `Release X.Y.Z` is reserved for `release/* -> master`
- `Hotfix X.Y.Z` is reserved for `hotfix/* -> master`
- `Backmerge Release X.Y.Z` is reserved for `release/* -> develop`
- `Backmerge Hotfix X.Y.Z` is reserved for `hotfix/* -> develop`

GitHub may append a trailing `(#123)` to merged workflow subjects. The runtime matcher ignores that suffix and still recognizes the underlying fixed title. Azure DevOps may prefix subjects with `Merged PR <id>:`; a supported engine ref normalizes that prefix too. In either case, the underlying subject must still match the intended title.

Release and hotfix branch work stays normal Conventional Commits. If a release branch needs to open `rc.0` without a real stabilization change, use an empty commit such as:

```bash
git commit --allow-empty -m "chore: open release"
```

This opener is an alternative to a real stabilization change, not a required extra commit. In reviewed flows, an empty commit alone is not a reviewable PR: use a meaningful inner PR or an approved initialization procedure instead.

## Shared Bump Policy

These guides assume the bump strategy follows these rules:

- `develop` creates or continues tagged `alpha`
- `master` finalizes prerelease to stable
- backmerges into `develop` preserve an ahead alpha line when one is already open
- meaningful unique backmerged fixes may advance that ahead alpha by one
- if `develop` is not ahead yet, a backmerge may catch `develop` up to the promoted stable target without tagging
- after that stable catch-up, open the next cycle later with `Start X.Y.Z` when needed

## CLI Coverage

Current helpers match the documented workflow:

- `git-tools commit --workflow-kind open-release`
- `git-tools pr --start-pr`, `--release-pr`, `--hotfix-pr`, `--backmerge-release-pr`, and `--backmerge-hotfix-pr`
- for direct `--backmerge-hotfix-pr`, always pass `--workflow-version X.Y.Z` naming the **already-promoted** hotfix; interactive mode asks without an inferred default
- Start and release-backmerge can infer their tuple where context permits; pass an explicit exact `X.Y.Z` when needed. Explicit Start input requires readable current/base version context and a valid next-cycle transition

These guides are GitHub and Azure DevOps PR-based adaptations of Git Flow. Ordinary feature/stabilization PRs in classic, classic-reviewed, and release-led support either squash merge or merge commits, provided the final commit subject on the target branch is the PR title. Synchronization and boundary backmerge steps must still use the completion method required by the selected platform walkthrough. Release-led-reviewed uses squash for ordinary feature/stabilization PRs. GitHub's strict squash recipe and Azure's ancestry-preserving synchronization/backmerge recipe differ: the Azure walkthrough requires Merge (no fast-forward) for those specified steps, so it is not squash-only end to end. Follow the selected platform's completion instructions.

If you want the closest thing to classic Git Flow, use [Git Flow Classic](github/classic.md) on GitHub or [Classic](azure-devops/classic.md) on Azure DevOps with merge commits for feature, release, and hotfix PRs.

`Rebase merge` is not part of this documented flow.

Use **Variant — Release-led** if you want `release/X.Y.Z` to choose the release line.

Use **Classic** if you want `develop` to choose the release line first and then open the next cycle with a `Start X.Y.Z` first PR.

Use **Classic — Reviewed** if you want classic semantics but every human change on `release/*` and `hotfix/*` must arrive via an inner PR for review trail.

Use **Variant — Reviewed** if you want the release-led model but every human change on `release/*` and `hotfix/*` must arrive via an inner PR for a review trail. Stabilization PRs squash-merge; the Azure walkthrough's specified synchronization and boundary-backmerge steps retain merge ancestry. Generated version commits still arrive from the bot directly, with a narrowly approved policy exception. Keep source branches until promotion and backmerge both finish. For failed publication, see [publication and recovery](publication.md).
