# git-tools

CLI for AI-assisted Conventional Commits, issue/PR text, and Git Flow versioning. Supports GitHub and Azure DevOps, with classic and release-led workflows and reviewed variants. LLM providers: OpenRouter, Kimi Code, CLIProxyAPI, ACRC, Copilot proxy, Qwen, OpenAI, and Anthropic. Model pickers use endpoint discovery where supported; the main model handles all generation.

## Install

Requires **Python 3.12**, Git, and [uv](https://docs.astral.sh/uv/getting-started/installation/). From this checkout:

```bash
./install.sh
# Refresh dependencies/tool environment when needed:
./install.sh --reinstall
```

The installer creates an editable tool installation, then enables shell completion if `git-tools` is on PATH. Restart your shell afterward. If the command is not on PATH, completion setup is skipped and the installer exits with an error: run `uv tool update-shell`, restart your shell, then run `git-tools --install-completion` and restart again (or rerun the installer after fixing PATH). Source changes are picked up without reinstalling; dependency changes or changes to project-version metadata may require `./install.sh --reinstall`.

## Quick Start

After installing, run from your new project directory. Replace `YOUR_GPG_KEY_ID` and the SSH key path:

```bash
# Optional: retrieve existing bot keys for your CI secret store.
gpg --list-secret-keys --keyid-format=long
gpg --export-secret-key -a YOUR_GPG_KEY_ID
cat ~/.ssh/key

git init
git-tools init
git add -A
git commit -m "Release 0.1.0"
```

**The key commands print private keys. Copy them only into your CI secret store, never into the repository; review staged files before committing.**

CI setup: [GitHub](docs/github/setup.md) · [Azure DevOps](docs/azure-devops/setup.md). `init` does not install automation. Full release flows: [walkthroughs](docs/walkthroughs.md). Tool version: `git-tools --version` (or `-V`).

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

`.cz.toml` is the **sole version and Git-tag authority**. During bump, other version files are best-effort sync targets: sync failures warn and skip rather than block the core bump. By default, every supported eligible location at the root and one immediate child level syncs to the computed release version, even when multiple locations use the same ecosystem. This includes child tools such as `smoke_runs`; limit targets with the optional replacement allowlist `auxiliary_directories` (for example, `["."]` for root only). Structured Python/uv, npm, and standalone Cargo handlers target each project's own version fields, not dependency versions; no package-manager commands run. This structured-handler scope is **not a safety guarantee for arbitrary custom `version_files` regexes** outside the selected directories; the current selector gap can rewrite dependency versions. See [versioning](docs/versioning.md) for exact targets and [current versioning limitations](docs/versioning.md#current-limitations) for that unresolved gap and the planning FIFO/file-mode defects.

Known configuration defects can also route a cleared endpoint to an unintended host, revive a reset endpoint after switching providers, or change Kimi's effective effort when accepting a picker default. Read [current configuration limitations](docs/configuration.md#current-limitations) before using provider generation. These are implementation gaps, not supported policy.

Workflow adapters are examples to copy and configure in the target repository; `init` does not install CI automation. Activate one adapter for your selected mode.

## Contribute

See [contributing](docs/contributing.md), [code layout](docs/architecture.md), [style conventions](docs/style.md), and [code of conduct](docs/code-of-conduct.md). Licensed under [MIT](LICENSE).
