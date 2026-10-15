# Azure DevOps Git Flow Guides

[Documentation index](../README.md) · [All platforms and modes](../git-flow-guide.md) · [GitHub](../github/README.md)

## Choose a Flow

| Mode | Release line selected by | Stabilization changes | Merge style |
| --- | --- | --- | --- |
| [Classic](classic.md) | `develop`; next-cycle `Start` after release cut | Direct human commits | Squash or merge commit |
| [Classic — Reviewed](classic-reviewed.md) | Same as classic | Inner PRs | Squash or merge commit |
| [Release-led](release-led.md) | `release/X.Y.Z` | Direct human commits | Squash or merge commit |
| [Release-led — Reviewed](release-led-reviewed.md) | Same as release-led | Inner PRs | Squash |

Reviewed modes share their base adapter. Activate **one** versioning pipeline, not one per mode. Review requirements are enforced by repository policies; generated bot version commits need a narrowly approved direct-push exception.

## How It Works

```text
Push branch / complete PR with the intended final subject
  → Pipelines checks out application history and tags
  → clones the selected git-tools engine branch/tag
  → decides skip / invalid / bump
  → signs version commit and, when applicable, tag
  → publishes using the project Build Service identity
  → user waits for CI, pulls bot commit, and fetches tags
```

The CLI generates PR text locally; it does not create or merge hosted PRs. `git-tools init` writes `.cz.toml`, not a pipeline. Versioning CI needs no LLM key; ordinary local commit/PR generation uses your configured provider.

## Start Here

1. Follow [Azure DevOps setup](setup.md): choose one adapter, configure the
   engine ref, signing Secure File, bot identity, project-scoped Build Service
   permissions, and merge settings.
2. Follow [bootstrap](setup.md#bootstrap-master-and-develop) once for a fresh
   repository. Push `master`, create and authorize the pipeline, then run it
   manually; the earlier push does not trigger a newly created pipeline
   retroactively. Create `develop` only after stable publication on `master`.
3. Follow the selected mode's command recipes and policy sections.
4. If publication fails, inspect remote refs and follow
   [publication and recovery](../publication.md), not another bootstrap.

## Shared References

- [Subject protocol and version policy](../git-flow-guide.md)
- [CLI commands, interactive navigation, and PR length preferences](../usage.md)
- [Configuration and provider settings](../configuration.md)
- [Optional manual DVC workflow](../dvc.md)

Azure descriptions have a 4,000 UTF-16-unit limit; origin detection enables the CLI length target by default. The CLI usage page is the authoritative home for limit preferences and overrides. Platform setup is the authoritative home for credential and merge configuration.
