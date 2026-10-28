# Azure DevOps Git Flow Guides

[Documentation index](../README.md) · [All platforms and modes](../git-flow-guide.md) · [GitHub](../github/README.md)

## Existing Keys or Pipeline? Start Here

- **[Copy your existing automation key into CI](setup.md#already-have-an-automation-key-copy-it-into-ci)** — two commands, exact secret pipeline variable **`BOT_GPG_SECRETKEY`**, no local export file or SSH key.
- **[Setup and pipeline permissions](setup.md)** — shared YAML, optional key creation, Build Service identity, and merge settings. For existing release history, do not repeat bootstrap.
- **[Returning-user quickstart](quickstart.md)** — compact key-copy and Classic checklist; includes a separately marked fresh-repository bootstrap.

Versioning CI uses Azure's Build Service token for pushes and your automation GPG key for signing. It needs no Azure bot user, SSH key, PAT, or LLM key. Local AI commit/PR prose separately uses your configured provider.

## Full Walkthroughs

For a new repository or a complete release example, choose **one** detailed guide. Each contains the existing-key copy commands, installation and fresh bootstrap, exact PR actions, expected versions/tags, local sync commands, and its mode policy/edge cases:

| Complete guide | Release line selected by | Human stabilization changes |
| --- | --- | --- |
| **[Classic](classic-walkthrough.md)** | `develop`; required next-cycle `Start` after release cut | Direct commits |
| **[Classic — Reviewed](classic-reviewed-walkthrough.md)** | Same as classic | Inner PRs |
| **[Release-led](release-led-walkthrough.md)** | `release/X.Y.Z`; optional next-cycle `Start` | Direct commits |
| **[Release-led — Reviewed](release-led-reviewed-walkthrough.md)** | Same as release-led | Inner PRs |

Reviewed modes share their base adapter: activate **one** versioning pipeline, not one per mode. Review requirements are repository policies; bot version commits need a narrowly approved direct-push exception.

Ordinary PRs use the guide's stated squash/merge style. The Azure guides require **Merge (no fast-forward)** for their synchronization and boundary-backmerge checkpoints to preserve ancestry and untagged version anchors. Prohibit rebase; do not apply a blanket squash-only policy to those steps.

## How It Works

```text
Push / complete PR with the intended final subject
  → check out application history and tags
  → clone the supported git-tools engine branch/tag
  → decide skip / invalid / bump
  → sign version commit and, when applicable, tag
  → publish using the project Build Service identity
  → wait for CI, pull bot commit, and fetch tags
```

`git-tools init` writes `.cz.toml`, not a pipeline. `git-tools pr` generates text; it does not create or complete hosted PRs. Azure's first bootstrap push precedes pipeline creation, so it needs a manual run. Create develop only after stable publication on master. On failure, inspect remote refs and follow [publication/recovery](../publication.md), not another bootstrap.

## Shared References

- [Subject protocol and version policy](../git-flow-guide.md)
- [CLI commands and PR length preferences](../usage.md)
- [Configuration and provider settings](../configuration.md)
- [Optional manual DVC workflow](../dvc.md)

Azure descriptions have a **4,000 UTF-16-unit** limit; Azure origin detection enables the CLI target. Inspect the final text before pasting. Credential details live in setup; mode policy and concrete journeys live together in the four complete guides.
