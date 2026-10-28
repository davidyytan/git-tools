# GitHub quickstart — returning-user checklist

Use this page to reconnect existing automation keys or repeat a familiar Classic flow. **First time?** Use the [complete Classic guide](classic-walkthrough.md), which includes installation, key-creation checkpoints, and the end-to-end release journey. The fixed commands and CI need no LLM account.

## Already have keys? Copy these into CI

**Destination: your application repository → Settings → Secrets and variables → Actions → New repository secret.** Use your own dedicated automation keys, not personal private keys. Run one command at a time: replace `YOUR_GPG_KEY_ID` with the selected bot key's full fingerprint (preferred) or long key ID after listing, and replace the SSH filename before reading it:

```bash
gpg --list-secret-keys --keyid-format=long
# Actions secret BOT_GPG_SECRETKEY: paste the complete private-key block printed next.
gpg --export-secret-key -a YOUR_GPG_KEY_ID
# Actions secret BOT_SSH_SECRETKEY: paste the complete SSH private key printed next.
cat "$HOME/.ssh/YOUR_AUTOMATION_SSH_KEY"
```

Paste each complete BEGIN/END block into its named secret in a private, unrecorded local terminal. Do not save an extra export file or expose output in chat/logs/source. Keep correct existing public-key registration; [register only if needed](setup.md#register-public-keys-only-if-needed). Missing a key? Use the [optional creation steps](setup.md#prepare-keys-and-set-the-exact-secrets), then return here. The supplied workflows have no GPG/SSH passphrase configured; protected keys need an approved adaptation.

For an **existing application**, [configure the workflow](setup.md#copy-and-configure-the-workflow) and resume from its actual branch/version. Do not rerun initialization or bootstrap. The checklist below is only for a **fresh repository** under your own GitHub account/org, with [git-tools installed](../../README.md#install) and GnuPG available.

## 1. Prepare the repository and Actions

This example keeps the tool checkout at `$HOME/projects/git-tools` and creates your application at `$HOME/projects/my-app`. Use your actual chosen paths if different; keep the tool checkout because installation is editable.

Replace `YOUR_NAME` / `YOUR_EMAIL` with **your human Git identity** and `YOUR_USERNAME_OR_ORG` / `YOUR_REPOSITORY` with your application's GitHub owner/name. Keep the SSH user `git@` unchanged:

```bash
mkdir -p "$HOME/projects"
cd "$HOME/projects"
mkdir my-app
cd my-app
git init -b master
git config user.name 'YOUR_NAME'
git config user.email 'YOUR_EMAIL'
git remote add origin git@github.com:YOUR_USERNAME_OR_ORG/YOUR_REPOSITORY.git
git-tools init --version 0.0.1 --tag-format '$version'
mkdir -p .github/workflows
cp "$HOME/projects/git-tools/.github/workflows/version-bump-git-flow-classic.yml.example" .github/workflows/version-bump-git-flow-classic.yml
```

Before pushing, complete [GitHub setup](setup.md):

- **Copied YAML `env:`:** keep the upstream `GIT_TOOLS_REPO`; choose a supported branch/tag in `GIT_TOOLS_REF` (not a bare SHA). Set `GIT_BOT_NAME` / `GIT_BOT_EMAIL` to **your dedicated automation identity**, not your human identity or David's.
- **Actions secrets:** follow [key setup](setup.md#prepare-keys-and-set-the-exact-secrets). Print the dedicated GPG private key and paste it into **`BOT_GPG_SECRETKEY`**; read the dedicated SSH private key into **`BOT_SSH_SECRETKEY`**. Use existing automation keys or create only the missing key first; no extra private-key export file is needed. Register matching public keys separately only if not already configured.
- **Repository settings:** allow that SSH identity to push signed version commits/tags with narrowly scoped protection exceptions. Enable PR-title squash messages, disable rebase, and use separate read-only PR tests.

Activate **one** version workflow. Protect `master`/`develop`; this Classic path permits human stabilization commits on `release/*` and `hotfix/*`. `init` does not install Actions.

## 2. Bootstrap once

Keep credentials/private keys outside the checkout. Stage the bootstrap files; add other application files only after reviewing them:

```bash
git add .cz.toml .github/workflows/version-bump-git-flow-classic.yml
git diff --cached
git commit -m "Release 0.1.0"
git push -u origin master
```

Set GitHub's default branch to `master`. **Wait for Actions to publish the bot commit and tag `0.1.0`**; do not manually bump/tag or add another bootstrap commit. Then:

```bash
git pull --ff-only origin master
git fetch origin --tags
git switch -c develop
git push -u origin develop
```

The branch-creation run skips; `develop` starts at `0.1.0`.

## 3. Land the first feature

```bash
git switch -c feature/first
# Make and test a real application change; replace the path placeholder.
git add -- path/to/changed-file
git commit -m "feat: add first feature"
git push -u origin feature/first
```

In GitHub, open **`feature/first` → `develop`**, title **`Start 0.2.0`**. Review, pass checks, and squash with that final subject. Wait for Actions: **`0.2.0-alpha.0`** and its tag.

After **every** version-producing push/merge, wait for publication, switch to the affected branch, run `git pull --ff-only origin <branch>`, and `git fetch origin --tags`. Stop on failures; do not run competing local bumps.

## 4. Release, backmerge, hotfix

| Step | Action | Expected result |
| --- | --- | --- |
| Cut release | From updated `develop`, create/push `release/0.2.0` | Branch creation alone does not open RC |
| Open next cycle | Next real PR into `develop`: **`Start 0.3.0`** | `0.3.0-alpha.0` |
| Stabilize | Commit/push a tested `fix: …` on `release/0.2.0` | `0.2.0-rc.0` |
| Promote | PR `release/0.2.0` → `master`: **`Release 0.2.0`** | Stable `0.2.0` + tag |
| Backmerge | Follow the [synchronization and integration-PR recipe](classic-walkthrough.md#9-synchronize-the-retained-release-source-for-backmerge); PR into `develop`: **`Backmerge Release 0.2.0`** | Preserve fixes; no new tag |
| Hotfix | From updated `master`, create `hotfix/name`, commit/push a tested fix; PR to `master`: **`Hotfix 0.2.1`** | `0.2.1-rc.0`, then stable `0.2.1` + tag |
| Backmerge hotfix | Follow the [hotfix synchronization recipe](classic-walkthrough.md#13-synchronize-the-retained-hotfix-source-through-the-proper-lane); PR into `develop`: **`Backmerge Hotfix 0.2.1`** | Preserve fixes; no new tag |

Keep release/hotfix sources until backmerge finishes. **Do not squash a source's untagged preparation version directly into develop**; use the linked integration-PR recipe. If master advances before promotion, synchronize/revalidate first.

**Other modes:** [Classic reviewed](classic-reviewed-walkthrough.md) uses inner stabilization PRs with the same adapter. [Release-led](release-led-walkthrough.md) and [release-led reviewed](release-led-reviewed-walkthrough.md) use the release-led adapter **instead**, with different release-line selection; do not mix their sequence with Classic.

Before production use: [current versioning limitations](../versioning.md#current-limitations). Failed publication: [recovery](../publication.md), not another bootstrap. Full worked example: [Classic walkthrough](classic-walkthrough.md).
