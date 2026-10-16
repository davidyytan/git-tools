# GitHub Setup

[GitHub guides](README.md) · [Documentation index](../README.md) · [CLI usage](../usage.md)

## Before You Start

- Read this setup before running local bootstrap commands.
- The checked-in adapters assume branches named `master` and `develop`.
- Initialize the local repository on `master`. For an empty GitHub repository,
  set its default branch to `master` after the first push, when that branch
  exists. For an existing repository, plan migration separately; do not rerun
  the fresh-repository bootstrap or overwrite its version configuration.

## Copy and Configure the Workflow

### Workflow file

`git-tools init` writes `.cz.toml`; it does **not** install Actions workflows, create branches, configure repository settings/secrets, or push to GitHub. The active classic workflow in this source repository versions **git-tools itself**. It is not installed into your application by the CLI.

Activate exactly one workflow by copying or renaming one example to a real `.yml` file in `.github/workflows/`:

- `.github/workflows/version-bump-git-flow-variant-release-led.yml.example` -> `.github/workflows/version-bump-git-flow-variant-release-led.yml`
- `.github/workflows/version-bump-git-flow-classic.yml.example` -> `.github/workflows/version-bump-git-flow-classic.yml`

### Tool-source ref and bot identity

The workflow clones `GIT_TOOLS_REPO` separately from the repository being versioned. Its `GIT_TOOLS_REF` selects the implementation of the version strategy, not your application's default branch. The supplied classic example currently uses `develop`; the release-led example uses `master`. Inspect and set this value explicitly before activation: the selected ref must contain `decide_version_strategy`, the bump runner, and the fixed-title/backmerge behavior described by these guides. Local edits or installing a newer CLI do not update that remote CI clone.

For reproducible CI, use a maintained release tag that contains the required behavior rather than a moving development branch. The examples use `git clone --branch "$GIT_TOOLS_REF"`, which accepts a branch or tag, **not an arbitrary commit SHA**; checking out a SHA requires adapting the clone/fetch step. Keep exactly one version workflow active to avoid competing version commits and tags.

Set `GIT_BOT_NAME` and `GIT_BOT_EMAIL` to your automation identity. Copy the chosen example from this repository:

- [Classic workflow example](../../.github/workflows/version-bump-git-flow-classic.yml.example)
- [Release-led workflow example](../../.github/workflows/version-bump-git-flow-variant-release-led.yml.example)

### Prepare keys and set the exact secrets

Use a dedicated automation identity, not your personal signing/private key. The commands below are instructions for **your local terminal**, not workflow steps. Never paste private keys into issues, chat, logs, or source files.

#### 1. Choose your values

Replace these descriptive placeholders before running commands; do not use the example text literally:

| Placeholder | Replace with |
| --- | --- |
| `YOUR_GPG_KEY_FINGERPRINT` | Full fingerprint of the bot's secret signing key from the listing below (preferred over a short key ID) |
| `YOUR_SSH_PRIVATE_KEY_PATH` | Path to the bot's existing private SSH key, e.g. `$HOME/.ssh/git_tools_bot_ed25519`; **not** its `.pub` file |
| `YOUR_BOT_NAME` | Git author name for generated commits |
| `YOUR_BOT_EMAIL` | Bot email matching the GPG identity; use a verified email on the bot's GitHub account for verification |
| `YOUR_SUPPORTED_ENGINE_BRANCH_OR_TAG` | An actual git-tools branch/tag containing the required strategy; not your application branch and not a bare SHA |

#### 2. Find and export the GPG private key

```bash
gpg --list-secret-keys --keyid-format=long
```

Select the bot's signing key by its identity/email. The `sec` line contains its long key ID; the fingerprint line below it identifies the full key. Do not copy the example ID from someone else's instructions. If you have no automation key, create a dedicated signing key with `gpg --full-generate-key`, then list it again. The supplied adapter has no passphrase input: use an approved unattended automation key or adapt the workflow securely for passphrase handling.

Export outside the checkout into a private directory:

```bash
GPG_KEY_FINGERPRINT='YOUR_GPG_KEY_FINGERPRINT'
KEY_EXPORT_DIR="$HOME/.git-tools-key-exports"
mkdir -p "$KEY_EXPORT_DIR"
chmod 700 "$KEY_EXPORT_DIR"
# Keep restrictive permissions for exports in this shell.
umask 077
gpg --output "$KEY_EXPORT_DIR/privatekey.pgp" --armor --export-secret-keys "$GPG_KEY_FINGERPRINT"
cat "$KEY_EXPORT_DIR/privatekey.pgp"
```

Copy the **entire** output, including `-----BEGIN PGP PRIVATE KEY BLOCK-----` and its matching end marker. In the target repository open **Settings → Secrets and variables → Actions → Secrets → New repository secret**:

- **Name:** `BOT_GPG_SECRETKEY`
- **Secret:** the complete armored private-key contents, **not** the filename, fingerprint, or public key.

`privatekey.pgp` is just an export filename; `--armor` makes its contents text regardless of extension. If it already exists, inspect it before choosing a new export filename; do not overwrite a key blindly. Remove the temporary export after securely storing the secret and any approved backup; this does not delete the key from your GPG keyring.

Export the matching **public** key separately:

```bash
gpg --armor --export "$GPG_KEY_FINGERPRINT"
```

Register that public block on the bot account under **Settings → SSH and GPG keys → New GPG key**. Never upload the private block there.

#### 3. Read the SSH private key and register its public key

Use your existing dedicated automation SSH key. If one is needed, create it with `ssh-keygen -t ed25519 -C 'YOUR_BOT_EMAIL' -f "$HOME/.ssh/git_tools_bot_ed25519"`; do not overwrite an existing key. The supplied checkout step has no SSH passphrase input, so plan unattended authentication accordingly.

```bash
# Replace the filename with YOUR_SSH_PRIVATE_KEY_PATH; keep $HOME expandable.
SSH_PRIVATE_KEY_PATH="$HOME/.ssh/git_tools_bot_ed25519"
cat "$SSH_PRIVATE_KEY_PATH"
```

This is the explicit-path form of `cat ~/.ssh/key`. Copy the **whole private key**, including its BEGIN/END markers. Create another repository Actions **secret**:

- **Name:** `BOT_SSH_SECRETKEY`
- **Secret:** the complete SSH private-key contents, **not** its path and **not** the `.pub` contents.

Now read the **public** key:

```bash
cat "${SSH_PRIVATE_KEY_PATH}.pub"
```

Register the public key either as a repository **Settings → Deploy keys → Add deploy key**, with **Allow write access**, or on a dedicated bot account with repository write access. Choose one identity model and ensure its permissions/ruleset exceptions permit the required pushes. Public keys go in key-registration screens; private keys go only in the Actions secrets above.

#### 4. Set workflow variables (not secrets)

Edit the top-level `env:` block in the copied workflow:

```yaml
env:
  GIT_TOOLS_REPO: https://github.com/davidyytan/git-tools.git
  GIT_TOOLS_REF: YOUR_SUPPORTED_ENGINE_BRANCH_OR_TAG
  GIT_BOT_NAME: 'YOUR_BOT_NAME'
  GIT_BOT_EMAIL: 'YOUR_BOT_EMAIL'
  GIT_TOOLS_BUMP_SYNC_AUXILIARY: 'true'
```

| Exact name | Location | Value |
| --- | --- | --- |
| `BOT_GPG_SECRETKEY` | Repository Actions **secret** | Armored GPG **private** key text |
| `BOT_SSH_SECRETKEY` | Repository Actions **secret** | SSH **private** key text |
| `GIT_TOOLS_REPO` | Workflow `env:` | Clone URL of the git-tools engine |
| `GIT_TOOLS_REF` | Workflow `env:` | Supported engine branch/tag |
| `GIT_BOT_NAME` | Workflow `env:` | Bot Git author name |
| `GIT_BOT_EMAIL` | Workflow `env:` | Bot Git author email matching its signing identity |
| `GIT_TOOLS_BUMP_SYNC_AUXILIARY` | Workflow `env:` | `'true'` to sync supported auxiliary version files; `'false'` for `.cz.toml` only |

**Keep these exact names.** The supplied workflow reads `${{ secrets.BOT_SSH_SECRETKEY }}` and `${{ secrets.BOT_GPG_SECRETKEY }}`. It reads the other settings from YAML `env:`; merely creating same-named values in GitHub's **Variables** tab does not override them. To use repository Variables instead, explicitly wire them with `${{ vars.NAME }}` in the workflow. No LLM/API key is required for versioning CI.

### Credential permissions and signing limitations

`BOT_SSH_SECRETKEY` is the private SSH key for an identity allowed to write to the target repository (for example, a write-enabled deploy key or bot account). `BOT_GPG_SECRETKEY` is the private signing key used for version commits and tags. Register the matching public keys as appropriate, store private keys only in Actions secrets, and do not commit them to the repository.

The supplied workflow does not configure a GPG passphrase input. Use a dedicated key suitable for unattended signing, or adapt the import step to supply a passphrase securely. Plan expiry, rotation, revocation, and backup; never use an unattended automation key as a personal signing key.

Branch protections/rulesets must permit this bot to push signed version commits and tags on the workflow's target branches. In reviewed flows, require human changes to arrive through PRs while narrowly granting the automation identity the required bypass. The workflow's final `git push` uses the SSH checkout credentials; merely granting `GITHUB_TOKEN` write permissions does not make an SSH identity writable. Validate bootstrap in a test repository before enforcing the final protections.

## Merge Settings

This flow supports two GitHub merge styles:

- squash merge
- merge commit

Do not use `Rebase merge` for this automated flow.

The rule that matters is the final commit subject on the target branch. GitHub may append a trailing `(#123)` to merged workflow PR subjects; the workflow matcher ignores that suffix.

#### Subjects into `develop`

- most feature and bugfix PRs into `develop` land with a Conventional Commit
  subject
- the first PR on a fresh develop line may land with `Start X.Y.Z`
- release backmerge PRs into `develop` must land with `Backmerge Release X.Y.Z`
- hotfix backmerge PRs into `develop` must land with `Backmerge Hotfix X.Y.Z`

#### Subjects into `master`

- release promotion PRs into `master` must land with `Release X.Y.Z`
- hotfix promotion PRs into `master` must land with `Hotfix X.Y.Z`

#### Squash merge profile

- enable `Squash merge`
- set the default squash commit message to use the PR title, ideally `Pull
  request title and description`
- disable `Rebase merge`
- you may disable `Merge commit` if you want a strict squash-only repository

#### Merge commit profile

- enable `Merge commit`
- set the default merge commit message to `Pull request title` or `Pull request
  title and description`
- disable `Rebase merge`
- for the closest classic Git Flow feel, use merge commits for `feature/*`,
  `bugfix/*`, `release/*`, and `hotfix/*` PRs

GitHub's default merge-commit subject `Merge pull request #...` is not suitable for this flow because the version workflow reads the latest commit subject.

Why:

- `develop` bump decisions depend on the final merged subject
- `master` release finalization depends on the merged prerelease state
- backmerges into `develop` must be distinguishable from release promotion
- squash and merge-commit styles both work when that final subject is the PR
  title

## Operational Safety and Limitations

- This is a **mutating push workflow**, not a read-only PR check. Use a separate
  test workflow for PR validation. Never expose its write/signing credentials
  to untrusted code or permit arbitrary changes to the adapter.
- The examples trigger on `master`, `develop`, `release/**`, `hotfix/**`,
  `feature/**`, and `bugfix/**`. Reviewed `release-fix/*` and `hotfix-fix/*`
  branches are intentionally outside that list; merging their PRs triggers
  the stabilization branch instead.
- Full history and tags are required. The adapter evaluates remote branch
  history as well as `.cz.toml`; shallow checkouts and stale refs can change
  decisions. Pull bot commits and explicitly fetch tags between dependent steps.
- The examples do not configure job concurrency. Coordinate version-producing
  pushes on each branch and wait for publication before the next operation.
  Concurrent runs can race; rejected publication is not permission to force-push
  or repeat bootstrap. Inspect the remote refs and [recovery guide](../publication.md).
- The bot's bump subject makes the next triggered run skip, preventing an
  ordinary bump loop. This is not a general guarantee against competing
  versioning workflows or manually changed versions.
- Reviewed flow is a repository-policy choice, not a compliance certification.
  Human changes require PRs; generated bot version commits need the approved
  narrow exception described above.

## Bootstrap `master` and `develop`

For a **fresh** target repository, copy and configure the chosen adapter before staging the first commit. Do not use this recipe to migrate existing history.

```bash
git init -b master
git remote add origin git@github.com:<owner>/<repo>.git
git-tools init
git add -A
git commit -m "Release 0.1.0"
git push -u origin master
```

Review staged files before committing, and never stage signing-key exports. Set the remote default branch to `master` after it exists. Direct initialization seeds `.cz.toml` at `0.0.1`; initialize `[project].version` to the same baseline if present. The first master run should create stable `0.1.0`. The subject `Release 0.0.1` is also accepted for bootstrap. Interactive initialization must retain the same baseline to obtain this documented result.

Wait for CI to publish successfully, then:

```bash
git checkout master
git pull origin master
git fetch origin --tags
git checkout -b develop
git push -u origin develop
```

Before every dependent operation, pull the bot commit and fetch tags. Promote only after the release/hotfix branch contains the expected `rc` version; wait for stable publication on `master` before backmerge. Creating a branch or opening a PR alone does not bump it.

## Local CLI and PR Descriptions

Direct `git-tools commit` generates and commits by default; use `--no-commit` to review output first. `git-tools pr` generates text, not a GitHub PR. Push the source branch, create the PR in GitHub, and use the documented base and title. See [CLI usage](../usage.md) for direct/interactive options and PR length preferences, and [configuration](../configuration.md) for provider settings.

## After Setup

Continue with one of these standalone guides:

- [Git Flow Classic](classic.md)
- [Git Flow Classic — Reviewed](classic-reviewed.md) (classic + inner PR layer for compliance)
- [Git Flow Variant — Release-led](release-led.md)
- [Git Flow Variant — Reviewed](release-led-reviewed.md) (release-led + inner PR layer, squash)

## Publication and Recovery

The selected engine ref must also contain `git_tools.generators.publish`. Publishing dry-runs an atomic push, logs its choice, and falls back only when the server explicitly lacks atomic support. Other failures stop. See [publication and missing-tag recovery](../publication.md).
