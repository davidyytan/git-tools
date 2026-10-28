# GitHub Git Flow Guides

[Documentation index](../README.md) · [All platforms and modes](../git-flow-guide.md) · [Azure DevOps](../azure-devops/README.md)

## Configure CI with existing keys

**Already have automation keys or entering an existing project?** Go straight to [Copy these into CI](setup.md#already-have-keys-copy-these-into-ci) for the grouped commands and exact Actions secret names, then configure one workflow. The [returning-user quickstart](quickstart.md) also keeps the commands on the page. Do not rerun fresh-repository bootstrap on existing version history.

Use your own GitHub account/org, application repository, and human author identity. Use your own **dedicated automation** keys/name/email for CI, not personal private keys or David's identity. Keep `https://github.com/davidyytan/git-tools.git` as the upstream tool source; it is not your application origin.

## Full Walkthroughs

**First time, or need the whole process?** Choose one complete guide below. Each includes installation → optional key creation via [shared setup](setup.md#prepare-keys-and-set-the-exact-secrets) → bootstrap → feature → RC/stable release → backmerge → hotfix → next cycle. The existing-key commands are also shown directly in every guide.

### Choose a Flow

| Complete guide | Release line selected by | Human stabilization changes | Merge style |
| --- | --- | --- | --- |
| [Classic](classic-walkthrough.md) | `develop`; next-cycle `Start` after release cut | Direct commits | Squash or PR-title merge commit |
| [Classic — Reviewed](classic-reviewed-walkthrough.md) | Same as Classic | Inner PRs | Squash or PR-title merge commit; current-master sync requires a merge commit |
| [Release-led](release-led-walkthrough.md) | `release/X.Y.Z` | Direct commits | Squash or PR-title merge commit |
| [Release-led — Reviewed](release-led-reviewed-walkthrough.md) | Same as release-led | Inner PRs | Squash; merge commit for current-master sync |

The guides use squash for their serialized worked examples. If master advances before promotion, reviewed modes require **Create a merge commit** for the current-master synchronization inner PR, with a customized Conventional Commit subject; repository and source-branch rules must allow that ancestry-preserving exception. Develop/backmerge preparation still follows its separate squash-safe recipe. Each guide keeps its policy/edge-case notes at the end; there is no separate mode-reference page to follow. Reviewed modes share their base adapter: activate **one** version workflow, not one per mode. Human review is enforced by repository policy; the bot needs a narrowly approved direct-push exception for version commits.

## How It Works

```text
Push branch / complete PR with the intended final subject
  → Actions checks out application history and tags
  → clones the selected git-tools engine branch/tag
  → decides skip / invalid / bump
  → signs version commit and, when applicable, tag
  → publishes using the bot SSH identity
  → user waits for CI, pulls bot commit, and fetches tags
```

`git-tools init` writes `.cz.toml`, not a workflow. The CLI generates PR text locally; it does not create or merge hosted PRs. Versioning CI needs no LLM key; optional generated commit/PR prose uses your configured provider.

## Shared References

- [GitHub setup: keys, exact secret names, workflow configuration, and permissions](setup.md)
- [Subject protocol and version policy](../git-flow-guide.md)
- [Publication and recovery](../publication.md) — use this on failure, not another bootstrap
- [CLI commands and interactive navigation](../usage.md)
- [Configuration and provider settings](../configuration.md)
- [Optional manual DVC workflow](../dvc.md)

GitHub has no automatic PR length target by default; Azure does. [CLI usage](../usage.md) covers opt-in targets and aliases.
