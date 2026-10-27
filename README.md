# git-tools

CLI for AI-assisted Conventional Commits, issue/PR text, and Git Flow versioning on GitHub and Azure DevOps.

## Install

Requires **Python 3.12**, Git, and [uv](https://docs.astral.sh/uv/getting-started/installation/). Install GnuPG too if you need GPG signing.

Choose a directory **outside your application repository**. This example uses `$HOME/projects`:

```bash
mkdir -p "$HOME/projects"
cd "$HOME/projects"
git clone https://github.com/davidyytan/git-tools.git
cd git-tools
./install.sh
```

Already cloned the tool? Run `./install.sh` from that checkout instead. **Keep the checkout in place:** the installation is editable. David's URL above is the upstream **tool source**, not your application's repository.

Restart your shell, then check `git-tools --version`. If the command is not on PATH, run `uv tool update-shell`, restart, then run `git-tools --install-completion`. For dependency or package-metadata changes, rerun `./install.sh --reinstall` from the tool checkout.

## Already have keys? Copy them into CI

Use your own **dedicated automation keys**, not someone else's key ID or everyday personal private keys. Run the commands **one at a time** in a private local terminal. After listing keys, select your automation key and replace `YOUR_GPG_KEY_ID` with its long ID or full fingerprint. Replace the SSH filename with your own automation key's filename.

### GitHub Actions

In **your application repository → Settings → Secrets and variables → Actions → New repository secret**, create the two secrets named beside these commands:

```bash
gpg --list-secret-keys --keyid-format=long
gpg --export-secret-key -a YOUR_GPG_KEY_ID  # → BOT_GPG_SECRETKEY
cat "$HOME/.ssh/YOUR_AUTOMATION_SSH_KEY"   # → BOT_SSH_SECRETKEY (not the .pub file)
```

Paste each complete private-key block, including its BEGIN/END markers, into the corresponding **secret**. **No export file is needed.** Never paste the private output into chat, logs, or source files; terminal/clipboard history can retain it.

Already registered the matching public keys and write access? Keep that setup. Missing a key or public-key registration? The [GitHub setup guide](docs/github/setup.md#prepare-keys-and-set-the-exact-secrets) shows how to create only what you need. The supplied workflows have no GPG/SSH passphrase configured; protected keys need a secure workflow adaptation.

### Azure DevOps

In **Pipelines → your pipeline → Edit → Variables → New variable**, name the variable **`BOT_GPG_SECRETKEY`** and enable **Keep this value secret**:

```bash
gpg --list-secret-keys --keyid-format=long
gpg --export-secret-key -a YOUR_GPG_KEY_ID  # → BOT_GPG_SECRETKEY (secret pipeline variable)
```

Paste the complete armored private-key block with its original line breaks. Azure's examples need **no SSH secret or exported key file**; the Build Service identity authenticates pushes. They have no GPG passphrase input. See [Azure setup](docs/azure-devops/setup.md) for creating a missing key, permissions, and updating older Secure File-based templates.

**Use your own details:** your name/email for local commits, your GitHub owner/repository or Azure organization/project/repository for the application remote, and your chosen automation name/email in CI. Keep the upstream git-tools source URL unchanged unless you intentionally use a fork.

## Use the CLI in your application

Switch to the repository you want to work on, **not** the git-tools source checkout:

```bash
cd /path/to/your/application
git-tools --help
git-tools settings                       # Optional: configure a provider for AI generation.
git-tools commit --no-commit --no-copy    # Preview a message for changes you already staged.
```

Direct `git-tools commit` **creates a commit by default**. `git-tools pr` generates text; it does not open a hosted PR. `init`, `bump`, and versioning CI need no LLM key.

## Follow a workflow

| What you need | GitHub | Azure DevOps |
| --- | --- | --- |
| Keys, secrets, CI settings, and permissions | [Setup](docs/github/setup.md) | [Setup](docs/azure-devops/setup.md) |
| Returning-user command checklist | [Quickstart](docs/github/quickstart.md) | [Quickstart](docs/azure-devops/quickstart.md) |
| Complete release/hotfix process | [Choose a guide](docs/github/README.md) | [Choose a guide](docs/azure-devops/README.md) |

Each complete guide includes the key-copy commands and its flow policy. Fresh-project bootstrap is clearly marked: **do not rerun it in an existing repository**. `git-tools init` creates `.cz.toml`; it does not install workflows or configure hosting. Enable only one versioning adapter per application.

## Reference and safety

- [CLI reference](docs/usage.md): commands, options, interactive operation, and side effects.
- [Configuration](docs/configuration.md): providers, credentials, models, and settings. **Do not use blank endpoints:** known destination/profile defects can send generation requests to an unintended host. Read the [current limitations](docs/configuration.md#current-limitations) before provider use.
- [Versioning](docs/versioning.md): `.cz.toml` is the version/tag authority; supported Python, Node, and Rust files sync on a best-effort basis. Review the [current limitations](docs/versioning.md#current-limitations) before custom selectors or bump planning.
- [Publication and recovery](docs/publication.md): inspect failed publication rather than force-pushing or repeating bootstrap.
- [Documentation index](docs/README.md): all guides, including optional [DVC](docs/dvc.md).

## Contribute

See [contributing](docs/contributing.md), [code layout](docs/architecture.md), [style conventions](docs/style.md), and [code of conduct](docs/code-of-conduct.md). Licensed under [MIT](LICENSE).
