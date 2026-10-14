# git-tools

CLI for AI-assisted Conventional Commits, issue/PR text, and Git Flow versioning.
Supports GitHub and Azure DevOps, with classic and release-led workflows and reviewed variants.

## Install

Requires **Python 3.12**, Git, and [uv](https://docs.astral.sh/uv/getting-started/installation/).
From this checkout:

```bash
./install.sh
# Refresh dependencies/tool environment when needed:
./install.sh --reinstall
```

Installation is editable and enables shell completion. Restart your shell afterward.
If the command is not on PATH, run `uv tool update-shell` and restart your shell.
Source changes are picked up without reinstalling; dependency changes may require `--reinstall`.

## Quick Start

Run commands from the repository you want to work on:

```bash
git-tools settings           # Choose provider, credentials, and model
git-tools                    # Interactive command menu

# Preview a message for deliberately staged changes:
git-tools commit --no-commit --no-copy

# Generate PR text locally; inspect and paste it into your hosting UI:
git-tools pr --base develop

# Preview a version bump without changing files or Git state:
git-tools bump --dry-run
```

**Direct `git-tools commit` creates a commit by default.** Stage only intended files first.
PR/issue commands generate text; they do not submit or merge hosted requests.
Use a clean index before an actual bump: unrelated staged changes can enter its commit.

## Documentation

Start with the **[documentation index](docs/README.md)**.

| Topic | Guide |
| --- | --- |
| Commands, defaults, safety, and interactive usage | [CLI usage](docs/usage.md) |
| Providers, credentials, models, and settings | [Configuration](docs/configuration.md) |
| Version authority and optional Python/Node sync | [Versioning](docs/versioning.md) |
| Choosing classic/release-led and reviewed modes | [Flow comparison](docs/git-flow-guide.md) |
| GitHub setup and four workflow guides | [GitHub](docs/github/README.md) |
| Azure DevOps setup and four workflow guides | [Azure DevOps](docs/azure-devops/README.md) |
| CI publication and recovery | [Publication](docs/publication.md) |
| Optional data and experiment workflow | [DVC](docs/dvc.md) |

`.cz.toml` is the **sole version and Git-tag authority**. During bump, other version
files are best-effort sync targets: failures warn and skip rather than block the core bump.
Root `package.json` and npm lockfiles are supported without framework-specific logic.
See [versioning](docs/versioning.md) for exact targets and limitations.

Workflow adapters are examples to copy and configure in the target repository;
`init` does not install CI automation. Activate one adapter for your selected mode.

## Contribute

See [contributing](docs/contributing.md), [style conventions](docs/style.md), and
[code of conduct](docs/code-of-conduct.md). Licensed under [MIT](LICENSE).
