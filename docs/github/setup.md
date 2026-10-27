# GitHub Setup

[GitHub guides](README.md) · [Documentation index](../README.md) · [CLI usage](../usage.md)

Use this page to configure Actions for **your application repository**, whether it already exists or is new. For a complete fresh-repository journey, choose a [walkthrough](README.md#full-walkthroughs).

## Already have keys? Copy these into CI

**Destination: your application repository → Settings → Secrets and variables → Actions → New repository secret.** Use your own **dedicated automation** keys, not personal private keys. Run one command at a time: after listing, replace `YOUR_GPG_KEY_ID` with the selected bot key's full fingerprint (preferred) or long key ID; replace the SSH filename with your own automation key's filename before reading it.

```bash
gpg --list-secret-keys --keyid-format=long
# Actions secret BOT_GPG_SECRETKEY: copy the complete private-key block printed next.
gpg --export-secret-key -a YOUR_GPG_KEY_ID
# Actions secret BOT_SSH_SECRETKEY: copy the complete SSH private key printed next.
cat "$HOME/.ssh/YOUR_AUTOMATION_SSH_KEY"
```

Paste each complete private key, including BEGIN/END markers, into its named secret. Run only in a private, unrecorded local terminal; never paste keys into chat, logs, or source files, and do not save an extra export file. Clipboard/terminal history may retain copied text. The supplied workflows have no GPG/SSH passphrase configured; protected keys need an [approved adaptation](#credential-permissions-and-signing-limitations).

**Already registered the matching public keys and write access?** Keep that setup; no need to create or register keys again. Otherwise follow [public-key registration](#register-public-keys-only-if-needed). Need a new key? Use the [optional creation steps](#prepare-keys-and-set-the-exact-secrets), then return to this same copy block.

Next, [configure the workflow](#copy-and-configure-the-workflow). Skip the fresh-repository bootstrap if your repository already has version history.

## Before You Start

- Install [git-tools](../../README.md#install), Git, Python **3.12**, and GnuPG. Keep the git-tools checkout: the installation is editable.
- Use your own GitHub account or organization and repository. Configure local Git with **your own** author name and email. The dedicated automation identity below is separate from your human identity.
- The adapters use `master` and `develop`. These bootstrap instructions are for a **fresh** repository. Existing history needs a migration plan; do not overwrite its version configuration or repeat bootstrap.
- Commands run in your local terminal unless marked as GitHub settings or YAML. No LLM/API key is needed for versioning CI.

## Copy and Configure the Workflow

In your application's `.github/workflows/`, activate **exactly one** example by removing its `.example` suffix:

| Flow | Example in the git-tools checkout | Destination filename |
| --- | --- | --- |
| Classic / Classic reviewed | [Classic example](../../.github/workflows/version-bump-git-flow-classic.yml.example) | `version-bump-git-flow-classic.yml` |
| Release-led / Release-led reviewed | [Release-led example](../../.github/workflows/version-bump-git-flow-variant-release-led.yml.example) | `version-bump-git-flow-variant-release-led.yml` |

Copy from your retained tool checkout; the walkthroughs use `$HOME/projects/git-tools`. `git-tools init` creates `.cz.toml`, **not** a workflow or hosted repository settings. The active `.yml` in the tool checkout versions git-tools itself; copy an **example** into your application instead.

**Destination: the copied workflow's top-level `env:` block.** Replace the identity and ref placeholders before pushing:

```yaml
env:
  GIT_TOOLS_REPO: https://github.com/davidyytan/git-tools.git # Upstream tool source; keep this URL.
  GIT_TOOLS_REF: YOUR_SUPPORTED_ENGINE_BRANCH_OR_TAG # A supported branch/tag, not a bare SHA.
  GIT_BOT_NAME: 'YOUR_AUTOMATION_NAME' # Your dedicated automation Git name, not David's.
  GIT_BOT_EMAIL: 'YOUR_AUTOMATION_EMAIL' # Match the GPG key and verified signing account email.
  GIT_TOOLS_BUMP_SYNC_AUXILIARY: 'true' # 'false' bumps only .cz.toml.
```

`GIT_TOOLS_REF` selects the **tool implementation**, not an application branch. Prefer a maintained release tag containing the documented strategy; the examples currently use `develop` for Classic and `master` for release-led. Check compatibility before activation; see [engine-ref details](#tool-source-ref-and-bot-identity).

## Prepare keys and set the exact secrets

**Optional: need new keys?** If you already have suitable dedicated automation keys, skip creation and use the [copy block above](#already-have-keys-copy-these-into-ci). Create only the key you are missing; do not export your everyday personal keys to CI.

### Create a GPG signing key only if needed

Run this locally:

```bash
gpg --full-generate-key
```

Choose a signing-capable key (for example RSA with signing), an expiry under your policy, and **your own automation name and email**. Use that same identity for `GIT_BOT_NAME` / `GIT_BOT_EMAIL`; verify the email on the GitHub account that will own the public key.

**Passphrase constraint:** the supplied workflows do not configure a GPG passphrase. Create a no-passphrase automation key **only if your policy allows it**; otherwise [adapt passphrase handling](#credential-permissions-and-signing-limitations) before using a protected key. Do not remove protection from a personal key to make CI work.

Return to the [same copy block](#already-have-keys-copy-these-into-ci), select the new key, and paste its complete private block into **Actions secret `BOT_GPG_SECRETKEY`**. No extra export file is needed.

### Create an SSH authentication key only if needed

Replace the comment's name/email with **your own automation identity**. The command creates the normal SSH key files at the stated path; choose another filename if either already exists, and **never overwrite an existing key**:

```bash
mkdir -p "$HOME/.ssh"
ssh-keygen -t ed25519 -C 'YOUR_AUTOMATION_NAME <YOUR_AUTOMATION_EMAIL>' -f "$HOME/.ssh/git_tools_bot_ed25519"
```

The supplied checkout has **no SSH passphrase input**. At the passphrase prompts, press Enter twice for an empty passphrase **only if your policy permits unattended keys**. Otherwise arrange an approved authentication adaptation before using this key; an encrypted key will not automatically work with the supplied checkout.

Return to the [same copy block](#already-have-keys-copy-these-into-ci), use `git_tools_bot_ed25519` as the SSH filename, and paste the complete private key into **Actions secret `BOT_SSH_SECRETKEY`**.

### Register public keys only if needed

If the matching public keys are already registered with the correct identities/access, leave them alone. Otherwise:

**GPG public-key destination: your dedicated signing account → Settings → SSH and GPG keys → New GPG key.** Replace `YOUR_GPG_KEY_ID` with the same selected key identifier:

```bash
# GitHub account GPG key registration: PUBLIC block only, not an Actions secret.
gpg --export -a YOUR_GPG_KEY_ID
```

Register only the public block. For GitHub verification, `GIT_BOT_EMAIL` must match an email in the key and a verified email on that account. A deploy key cannot own a GPG identity; signing registration and push authentication are separate.

**SSH public-key destination: a write-enabled repository Deploy key OR your dedicated bot account's authentication keys.** Replace the filename with the public half of your selected SSH key (use `git_tools_bot_ed25519.pub` if you created it above):

```bash
# SSH public-key registration only; do not paste this into BOT_SSH_SECRETKEY.
cat "$HOME/.ssh/YOUR_AUTOMATION_SSH_KEY.pub"
```

- **Deploy key:** application repository → Settings → Deploy keys → Add deploy key; enable **Allow write access**.
- **Bot account:** that account → Settings → SSH and GPG keys → New SSH key; choose an authentication key and grant the account repository write access.

Registering a GPG public key does not grant write access. Keep private keys out of the application checkout; only public keys belong in these registration screens.

## Merge Settings

For the walkthroughs, use **Squash and merge**, with the final commit subject equal to the stated PR title:

- Enable squash merge; choose **Pull request title** or **Pull request title and description** for its default message.
- Disable **Rebase merge**.
- Classic, Classic reviewed, and direct release-led also support merge commits when their final subject is the PR title. Configure the default merge message accordingly, not `Merge pull request #...`. Release-led reviewed uses squash.
- Use a separate read-only workflow for PR tests. The version workflow runs on pushes and **writes** commits/tags; it is not a PR validation check.

Protect the intended target branches and require human reviews/checks. Narrowly allow the automation identity to push signed version commits/tags; plan the one-time seed exception before applying final protections. See [credential permissions](#credential-permissions-and-signing-limitations) for the SSH/ruleset distinction.

## Bootstrap `master` and `develop`

Do this **once**, after copying/configuring the adapter and setting the secrets. In your **fresh application directory**, replace `YOUR_USERNAME_OR_ORG` and `YOUR_REPOSITORY` with the owner/name of your own GitHub repository. The SSH user `git@` stays unchanged.

```bash
# Use your application's actual directory, not the git-tools checkout.
cd "$HOME/projects/YOUR_REPOSITORY"
git init -b master
git remote add origin git@github.com:YOUR_USERNAME_OR_ORG/YOUR_REPOSITORY.git
git-tools init --version 0.0.1 --tag-format '$version'
git add -A
git diff --cached # Check that no credentials or private keys are staged.
git commit -m "Release 0.1.0"
git push -u origin master
```

If you already initialized the application or set its remote, do not repeat those commands. `.cz.toml` starts at **`0.0.1`**; any managed application manifest version must match. Do not create a bootstrap tag manually. Set GitHub's default branch to `master` after the first push.

**Wait for Actions:** expect the bot commit at stable **`0.1.0`** and tag **`0.1.0`**. Only after successful publication:

```bash
git switch master
git pull --ff-only origin master
git fetch origin --tags
git switch -c develop
git push -u origin develop
```

The branch-creation run skips. `develop` now starts from the published stable release. After every version-producing push/merge, wait for CI, pull the bot commit, and fetch tags before the next operation. Stop on failures; use [publication recovery](../publication.md), not another bootstrap or a force-push.

## After Setup

Continue with one complete journey:

- [Classic walkthrough](classic-walkthrough.md)
- [Classic reviewed walkthrough](classic-reviewed-walkthrough.md)
- [Release-led walkthrough](release-led-walkthrough.md)
- [Release-led reviewed walkthrough](release-led-reviewed-walkthrough.md)

Each [complete guide](README.md#choose-a-flow) includes its mode's policy and edge cases. The details below cover shared configuration choices and operational limits.

## Configuration and Safety Details

### Tool-source ref and bot identity

The selected engine ref must contain `decide_version_strategy`, the bump runner, fixed-title/backmerge behavior, and `git_tools.generators.publish`. A newer local CLI or local source edit does **not** update CI's separate remote clone.

The example's `git clone --branch "$GIT_TOOLS_REF"` accepts a branch or tag, **not an arbitrary commit SHA**. To pin a SHA, adapt the clone/fetch/checkout step. Keep exactly one version workflow active to avoid competing version commits/tags.

`GIT_BOT_NAME` is a commit identity label, not a GitHub username or authentication mechanism. Set your human Git author separately. Use your own account/org/repository for the application origin; keep the upstream git-tools URL for `GIT_TOOLS_REPO`.

### Exact settings and destinations

| Exact name | Set it here | Value |
| --- | --- | --- |
| `BOT_GPG_SECRETKEY` | Repository Actions **secret** | Complete armored GPG private key |
| `BOT_SSH_SECRETKEY` | Repository Actions **secret** | Complete dedicated SSH private key |
| `GIT_TOOLS_REPO` | Copied YAML `env:` | Upstream tool-source URL |
| `GIT_TOOLS_REF` | Copied YAML `env:` | Supported tool branch/tag |
| `GIT_BOT_NAME` / `GIT_BOT_EMAIL` | Copied YAML `env:` | Your automation identity, matching its GPG identity |
| `GIT_TOOLS_BUMP_SYNC_AUXILIARY` | Copied YAML `env:` | `'true'` to sync supported auxiliary versions; `'false'` for `.cz.toml` only |

Keep these names. The workflow reads `${{ secrets.BOT_SSH_SECRETKEY }}` and `${{ secrets.BOT_GPG_SECRETKEY }}`. Other settings come from YAML `env:`: creating same-named repository **Variables** does not override them. To use repository Variables, wire them explicitly with `${{ vars.NAME }}`.

### Credential permissions and signing limitations

- **GPG passphrase:** the import action supports one, but the supplied workflow does not configure it. For a protected key, create a separate Actions secret such as `BOT_GPG_PASSPHRASE` and add `passphrase: ${{ secrets.BOT_GPG_PASSPHRASE }}` to the import action's `with:` block. Do not hardcode it. Plan expiry, rotation, revocation, and approved backup; do not strip protection from a personal key to use it in CI.
- **SSH permissions:** final pushes use the checkout's SSH identity. `GITHUB_TOKEN` write permission alone does not grant that SSH identity write access or bypass rulesets. Check branch/tag protections for the selected deploy key or bot account, and validate in a test repository before enforcing final protections.
- **Reviewed modes:** require human changes through PRs while narrowly authorizing bot version pushes. Reviewed flow is a policy choice, not a compliance certification.
- **Key storage:** printing avoids an extra export file; GnuPG still stores keys in its keyring, and the runner imports private material to sign. Protect the local terminal, secret store, and runner.

### Final subjects

The workflow reads the latest commit subject on the target branch. GitHub may append `(#123)` to a workflow PR subject; the matcher ignores that suffix.

| Target | Final subject |
| --- | --- |
| `develop`, ordinary work | Conventional Commit |
| `develop`, explicitly open a new line | `Start X.Y.Z` |
| `develop`, release backmerge | `Backmerge Release X.Y.Z` |
| `develop`, hotfix backmerge | `Backmerge Hotfix X.Y.Z` |
| `master`, release promotion | `Release X.Y.Z` |
| `master`, hotfix promotion | `Hotfix X.Y.Z` |

The first master run also accepts `Release 0.0.1` for bootstrap. The documented sequence uses `Release 0.1.0` and the `0.0.1` starting configuration. Interactive initialization must retain that baseline.

### Operational Safety and Limitations

- Never expose this mutating workflow's write/signing credentials to untrusted code or allow arbitrary adapter edits. Its triggers include `master`, `develop`, `release/**`, `hotfix/**`, `feature/**`, and `bugfix/**`. Reviewed `release-fix/*` / `hotfix-fix/*` sources are intentionally excluded; their target merge triggers CI.
- Full history and current tags are required. Decisions also read remote branch history; shallow checkouts or stale refs can change results.
- The examples have no job concurrency setting. Serialize version-producing pushes per branch and wait for publication. A bot bump normally triggers a skip run, but that does not prevent races between competing workflows. Inspect remote refs on failures; do not force-push or repeat bootstrap.
- Before promotion, the release/hotfix source must contain the expected RC and current stable changes. Wait for stable publication on `master` before backmerge; keep the source until integration is confirmed. Branch creation or opening a PR alone does not bump.
- Read [current versioning limitations](../versioning.md#current-limitations), including metadata snapshot and custom-selector safety gaps, before production use.

### Local CLI and PR Descriptions

`git-tools commit` generates **and commits** by default; use `--no-commit` to preview. `git-tools pr` generates text, not a hosted PR: push the source, create the PR in GitHub, and use the documented base/title. Configure a provider only if using generated prose; see [CLI usage](../usage.md), [configuration](../configuration.md), and [current provider limitations](../configuration.md#current-limitations).

### Publication and Recovery

Publishing dry-runs an atomic push and falls back only when the server explicitly lacks atomic support. Other failures stop. Inspect remote commits/tags and follow [publication and missing-tag recovery](../publication.md) before retrying.
