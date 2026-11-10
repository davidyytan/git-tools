# Documentation

[Project README](../README.md)

## Pick up where you are

| What you want to do | GitHub | Azure DevOps |
| --- | --- | --- |
| Copy existing keys into CI or configure automation | [Setup and key commands](github/actions/setup.md) | [Setup and key commands](azure-devops/setup.md) |
| Choose branch protections and allowed mergers | [Rulesets: solo/team presets](github/rulesets/README.md) | — |
| Configure merge-commit title and description | [Settings and screenshots](github/rulesets/README.md#merge-commit-title-and-description) | — |
| Apply the PR-only/history baseline with the CLI | [Two-ruleset recipe](github/rulesets/branch-rulesets.md) | — |
| Use a compact returning-user checklist | [Quickstart](github/actions/quickstart.md) | [Quickstart](azure-devops/quickstart.md) |
| Follow a complete release and hotfix process | [Choose your guide](github/actions/README.md) | [Choose your guide](azure-devops/README.md) |

**Already have keys?** The setup pages, quickstarts, and complete guides each include the commands and exact secret names. You do not need to start from scratch or create new keys.

**First time?** [Install the CLI](../README.md#install), choose a [complete guide](walkthroughs.md), and follow its numbered steps. Missing SSH/GPG keys have optional creation steps in platform setup. Configure an [LLM provider](configuration.md) only if you want AI-generated commit or PR text; versioning CI needs no LLM key.

Each complete guide now contains both the worked lifecycle and its mode policy. There is no separate mode-reference page to assemble. Reviewed modes use their base flow's adapter: enable **one** versioning workflow/pipeline per application.

## Local commands and reference

| Guide | Use it for |
| --- | --- |
| [CLI usage](usage.md) | Commands, options, defaults, and interactive operation |
| [Configuration](configuration.md) | Providers, credentials, models, and saved settings |
| [Versioning](versioning.md) | `.cz.toml`, best-effort Python/Node/Rust sync, and custom targets |
| [Flow comparison](git-flow-guide.md) | Choosing classic or release-led, reviewed modes, and shared title rules |
| [Publication](publication.md) | Failed CI publication and missing-tag recovery |
| [DVC](dvc.md) | Optional manual data and experiment workflow |

Before sending repository content to a provider, read the [configuration limitations](configuration.md#current-limitations). Before custom version selectors or bump planning, read the [versioning limitations](versioning.md#current-limitations).

## Project maintenance

- [Contributing](contributing.md)
- [Code layout](architecture.md)
- [Style conventions](style.md)
- [Code of conduct](code-of-conduct.md)
- [MIT license](../LICENSE)
