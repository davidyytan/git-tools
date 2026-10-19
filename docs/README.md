# Documentation

[Project README](../README.md)

## Start Here

1. Install using the [root README](../README.md#install).
2. Configure an LLM provider using [configuration](configuration.md) if you want AI generation.
3. Use [CLI usage](usage.md) for local commands and interactive prompts.
4. For automated releases, follow a **[full start-to-finish walkthrough](walkthroughs.md)**. Choose one platform and mode; the numbered journey includes setup, the initial `Release 0.1.0`, features, release, backmerge, hotfix, and the next cycle.

## Full Workflow Walkthroughs

[Choose your complete walkthrough](walkthroughs.md). These are the guided learning path. The core and hosted flow references below explain individual commands and policies once you know the lifecycle.

## Core References

| Guide | Covers |
| --- | --- |
| [CLI usage](usage.md) | Commands, options, defaults, side effects, interactive operation |
| [Configuration](configuration.md) | Providers, credentials, model selection, saved settings |
| [Versioning](versioning.md) | `.cz.toml` authority, best-effort sync, Python, Node, and Rust targets |
| [Flow comparison](git-flow-guide.md) | Mode selection and shared workflow policy |
| [Publication](publication.md) | CI ref publication, fallback, and recovery |
| [DVC](dvc.md) | Optional manual data and experiment workflow |

## Hosted Workflows

The guides are parallel sister copies: choose a platform and a mode. Platform-specific setup and mode-specific policy are intentional differences.

| Mode | GitHub | Azure DevOps |
| --- | --- | --- |
| Setup | [Setup](github/setup.md) | [Setup](azure-devops/setup.md) |
| Classic | [Classic](github/classic.md) | [Classic](azure-devops/classic.md) |
| Classic reviewed | [Classic reviewed](github/classic-reviewed.md) | [Classic reviewed](azure-devops/classic-reviewed.md) |
| Release-led | [Release-led](github/release-led.md) | [Release-led](azure-devops/release-led.md) |
| Release-led reviewed | [Release-led reviewed](github/release-led-reviewed.md) | [Release-led reviewed](azure-devops/release-led-reviewed.md) |

Platform indexes: [GitHub](github/README.md) · [Azure DevOps](azure-devops/README.md). Reviewed modes share their base adapter; install one adapter, not four.

## Project Maintenance

- [Contributing](contributing.md)
- [Code layout](architecture.md)
- [Style conventions](style.md)
- [Code of conduct](code-of-conduct.md)
- [MIT license](../LICENSE)

Keep detailed documentation here; root and folder READMEs serve as entry points.
