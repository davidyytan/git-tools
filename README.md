# git-tools

CLI for AI-assisted Conventional Commits, issue/PR text, and Git Flow versioning. Supports GitHub and Azure DevOps, with classic and release-led workflows and reviewed variants. LLM providers: OpenRouter, Kimi Code, CLIProxyAPI, ACRC, Copilot proxy, Qwen, OpenAI, and Anthropic. Model pickers use endpoint discovery where supported; main handles generation and support is reserved for future use.

## Install

Requires **Python 3.12**, Git, and [uv](https://docs.astral.sh/uv/getting-started/installation/). From this checkout:

```bash
./install.sh
# Refresh dependencies/tool environment when needed:
./install.sh --reinstall
```

The installer creates an editable tool installation, then enables shell completion if `git-tools` is on PATH. Restart your shell afterward. If the command is not on PATH, completion setup is skipped and the installer exits with an error: run `uv tool update-shell`, restart your shell, then run `git-tools --install-completion` and restart again (or rerun the installer after fixing PATH). Source changes are picked up without reinstalling; dependency changes may require `--reinstall`.

## Start a repository and ship a release

Follow a **[full workflow walkthrough](docs/walkthroughs.md)** for your platform and mode. Each numbered guide takes a fresh repository from the initial **`Release 0.1.0`** commit through features, alpha/RC versions, stable release, backmerge, hotfix, and the next development cycle—with exact PR titles and CI checkpoints.

Choose [GitHub](docs/github/README.md#full-walkthroughs) or [Azure DevOps](docs/azure-devops/README.md#full-walkthroughs). The walkthrough includes setup; `git-tools init` alone does not install automation. Existing release histories need a migration plan, not another bootstrap.

## Quick Start — individual commands

For an already configured repository, or text generation without release automation (the examples below still use the configured provider):

Run commands from the repository you want to work on:

```bash
git-tools settings           # Choose provider, credentials, and model
git-tools                    # Interactive command menu

# Generate a message for deliberately staged changes without committing/copying:
git-tools commit --no-commit --no-copy

# Generate PR text via the configured provider; inspect and paste the output:
git-tools pr --base develop --no-copy

# Preview a version bump without changing files or Git state:
git-tools bump --dry-run
```

**Direct `git-tools commit` creates a commit by default.** Stage only intended files first. PR/issue commands generate text; they do not submit or merge hosted requests. Actual bumps require an empty index and reject pre-staged content before writing. Use `bump --dry-run` to review planned files/diffs; interactive bump offers Preview / Apply / Cancel.

## Documentation

Start with the **[documentation index](docs/README.md)**.

| Topic | Guide |
| --- | --- |
| Commands, defaults, safety, and interactive usage | [CLI usage](docs/usage.md) |
| Providers, credentials, models, and settings | [Configuration](docs/configuration.md) |
| Version authority and optional Python/Node/Rust sync | [Versioning](docs/versioning.md) |
| Choosing classic/release-led and reviewed modes | [Flow comparison](docs/git-flow-guide.md) |
| GitHub setup and four workflow guides | [GitHub](docs/github/README.md) |
| Azure DevOps setup and four workflow guides | [Azure DevOps](docs/azure-devops/README.md) |
| CI publication and recovery | [Publication](docs/publication.md) |
| Optional data and experiment workflow | [DVC](docs/dvc.md) |

`.cz.toml` is the **sole version and Git-tag authority**. During bump, other version files are best-effort sync targets: sync failures warn and skip rather than block the core bump. Automatic discovery checks the root and one directory level down; its structured Python/uv, npm, and standalone Cargo handlers target the app's own version fields, not dependency versions. Multiple locations for the same ecosystem require an explicit `auxiliary_directories` selection. This structured-handler scope is **not a safety guarantee for arbitrary custom `version_files` regexes** outside the selected directories; the current selector gap can rewrite dependency versions. See [versioning](docs/versioning.md) for exact targets and [current versioning limitations](docs/versioning.md#current-limitations) for that unresolved gap and the planning FIFO/file-mode defects.

Known configuration defects can also route a cleared endpoint to an unintended host, revive a reset endpoint after switching providers, or change Kimi's effective effort when accepting a picker default. Read [current configuration limitations](docs/configuration.md#current-limitations) before using provider generation. These are implementation gaps, not supported policy.

Workflow adapters are examples to copy and configure in the target repository; `init` does not install CI automation. Activate one adapter for your selected mode.

## Contribute

See [contributing](docs/contributing.md), [code layout](docs/architecture.md), [style conventions](docs/style.md), and [code of conduct](docs/code-of-conduct.md). Licensed under [MIT](LICENSE).
