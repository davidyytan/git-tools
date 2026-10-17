# GitHub quickstart

**Fresh repository → first Classic release.** Requires [git-tools installed](../../README.md#install), Git author configured, and an empty GitHub repository. Existing release history needs a migration plan, not this bootstrap. No LLM account is needed.

## 1. Prepare the repository and Actions

Replace the checkout path and remote:

```bash
GIT_TOOLS_DIR=/path/to/git-tools
mkdir my-app && cd my-app
git init -b master
git remote add origin git@github.com:OWNER/REPO.git
git-tools init --version 0.0.1 --tag-format '$version'
mkdir -p .github/workflows
cp "$GIT_TOOLS_DIR/.github/workflows/version-bump-git-flow-classic.yml.example" \
  .github/workflows/version-bump-git-flow-classic.yml
```

Before pushing, complete [GitHub setup](setup.md):

- In the YAML, set `GIT_TOOLS_REPO`, a **supported engine branch/tag** in `GIT_TOOLS_REF`, and `GIT_BOT_NAME` / `GIT_BOT_EMAIL`. A bare SHA is not supported by the example clone.
- Store the bot's private keys in Actions secrets **`BOT_SSH_SECRETKEY`** and **`BOT_GPG_SECRETKEY`**; register their public keys. Keep private keys outside the checkout.
- Allow that SSH identity to push signed version commits/tags; scope protection exceptions to automation. Enable squash with **PR title as final subject**, disable rebase, and use separate PR validation checks.

Activate **one** version workflow. Protect `master`/`develop`; this Classic path permits human stabilization commits on `release/*` and `hotfix/*`. `init` does not install Actions.

## 2. Bootstrap once

Ensure credentials/private keys are ignored, then choose **one** staging command:

```bash
git add -A  # If application files are already present.
# Otherwise, stage only the bootstrap files instead:
# git add .cz.toml .github/workflows/version-bump-git-flow-classic.yml
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
git add -- <reviewed-paths>
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
