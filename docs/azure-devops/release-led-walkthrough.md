# Azure DevOps: Release-led end-to-end walkthrough

The numbered journey below assumes an **empty Azure Repo**, not the git-tools source checkout. If you enter mid-flow, use the existing-key block and mode policy instead of repeating bootstrap. The full example runs from the first commit through a release, hotfix, and next development cycle. Commands assume Bash (or Git Bash), an authenticated Git connection to Azure Repos, and one person coordinating these operations without concurrent merges. Replace the organization/project/repository URL and your Git identity; keep the example branch names, titles, and versions unchanged.

These are expected results derived from the engine and local Git checks, **not a claim that these instructions were executed against hosted Azure DevOps**. Stop on errors or unexpected versions instead of running later steps blindly.

## Already Have a Signing Key or Pipeline?

**Destination: Azure DevOps → Pipelines → your pipeline → Edit → Variables → New variable → `BOT_GPG_SECRETKEY` → enable “Keep this value secret”.** Select your existing **dedicated automation signing key**, not your personal key. Replace `YOUR_GPG_KEY_ID` with its long ID or full fingerprint from the first command before running the second:

```bash
gpg --list-secret-keys --keyid-format=long
gpg --export-secret-key -a YOUR_GPG_KEY_ID  # → BOT_GPG_SECRETKEY (secret pipeline variable)
```

Paste the full armored block with original line breaks. Existing pipeline users can paste now; for this fresh example, run the block after creating the pipeline in step 4. No export file, SSH key, PAT, or bot user is needed. Already configured the key? Do not recreate/register it. [Need a new key? Follow the optional create-first path](setup.md#2-choose-an-automation-signing-key), then return to this block.

The template has **no passphrase input**: use only an approved unattended automation key. Never log/trace the key or paste it into YAML/chat; multiline masking does not protect its individual lines. Already have release history? Use the [mode policy](#mode-policy-and-edge-cases) and the relevant later step; do not repeat fresh-repository bootstrap.

## 1. Install the CLI and prepare the Azure project

Install Git, **Python 3.12**, uv, and GnuPG. This example keeps the tool and application under **`$HOME/projects`**; choose another location if preferred and adjust the later absolute copy path. This is the **upstream tool source**, not your application origin. If you already have the checkout, use it instead of cloning again:

```bash
mkdir -p "$HOME/projects"
cd "$HOME/projects"
git clone https://github.com/davidyytan/git-tools.git
cd git-tools
./install.sh
```

Keep the tool checkout in place: installation is editable. See [installation](../../README.md#install) for PATH/completion help.

Restart the shell after installation (`uv tool update-shell` if needed), then run:

```bash
git-tools --help
git-tools settings
```

Configure a [provider](../configuration.md) for local generated commit/PR prose; `init` and versioning CI need no LLM. `git-tools pr` uses the provider for descriptions even with a fixed title. The explicit Git messages below keep the version sequence reproducible. If using `git-tools commit` instead, remember it creates a commit by default: do not also run the example `git commit` for that change. See [CLI usage](../usage.md) for preview options.

In Azure DevOps create a project/repository with **no initial README**. Ensure you can push branches, create/complete PRs, create a YAML pipeline, and administer its permissions (or enlist an administrator). Configure Git authentication using your organization's approved Azure Repos method. The pipeline itself needs no bot account, PAT, or SSH key: it uses the automatic Build Service identity. Use [platform setup](setup.md) for the full credential and permission reference. In organization/project **Pipelines → Settings**, enable **Limit job authorization scope to current project for non-release pipelines** before granting service permissions.

## 2. Create the local repository and copy exactly one adapter

After restarting your shell, explicitly return to the chosen parent. Use **your own human name/email** for commits and **your own Azure organization/project/repository** for the origin below, not the upstream author's identity:

```bash
cd "$HOME/projects"
mkdir azure-flow-demo
cd azure-flow-demo
git init -b master
git config user.name "YOUR_NAME"
git config user.email "YOUR_EMAIL"
git remote add origin "https://dev.azure.com/YOUR_ORG/YOUR_PROJECT/_git/YOUR_REPOSITORY"
git-tools init --version 0.0.1 --tag-format '$version'
mkdir -p .azure/workflows
```

Copy the release-led adapter into this application. If you chose a different tool-checkout location, replace the absolute source path:

```bash
cp "$HOME/projects/git-tools/.azure/workflows/version-bump-git-flow-variant-release-led.yml.example" .azure/workflows/version-bump-git-flow-variant-release-led.yml
```

In that YAML set `GIT_TOOLS_REPO` to the public git-tools repository and `GIT_TOOLS_REF` to a supported branch or tag containing Azure subject normalization and the selected flow. The example uses `develop`; verify its support, or use an immutable supported tag for reproducible engine code. The adapter uses `git clone --branch`, so a bare commit SHA is not accepted. Do not activate a second adapter.

Keep full history, tag fetching, and `persistCredentials: true`. Replace these with **your own dedicated automation name/email**, matching the signing key used in step 4 (not your human author identity):

```yaml
GIT_BOT_NAME: YOUR_AUTOMATION_NAME
GIT_BOT_EMAIL: YOUR_AUTOMATION_EMAIL
```

Create `README.md` containing `# Azure flow demo`. This deliberately minimal repository has no package manifests: `.cz.toml` is the only managed version file. `git-tools init` writes that file; it does not install pipelines, create branches, push, or tag. Confirm `.cz.toml` contains `version = "0.0.1"` and `tag_format = "$version"`.

## 3. Bootstrap and push before pipeline creation

Review the files and staged diff; no credentials belong in this commit. Configure the signing secret in step 4, after the pipeline exists:

```bash
git status --short
git add README.md .cz.toml .azure/workflows
git diff --cached
git commit -m "Release 0.1.0"
git push -u origin master
```

**Do not add another commit after `Release 0.1.0` before bootstrap runs.** At this point `master` still contains version `0.0.1`, and there is **no tag**. Push now: an empty Azure Repo cannot supply the branch/YAML needed by the pipeline picker. No PR is involved in this one-time bootstrap.

## 4. Configure the Azure pipeline and run bootstrap

Perform these Azure actions in order; see [platform setup](setup.md#4-create-the-azure-pipeline) for details:

1. Open **Pipelines → New pipeline → Azure Repos Git**, select this repository, then **Existing Azure Pipelines YAML file**. Choose `master` and `.azure/workflows/version-bump-git-flow-variant-release-led.yml`. Save the definition (do not use a generated starter YAML or create a competing pipeline).
2. In this pipeline's **Edit → Variables**, create **`BOT_GPG_SECRETKEY`** and enable **Keep this value secret**. Use the [copy block above](#already-have-a-signing-key-or-pipeline) for an existing key, or its linked optional create-first path. Paste its complete printed armored private key here with original line breaks; save. Do not put the key in YAML or a local export file.
3. Under **Project settings → Repositories → this repository → Security**, grant `<Your Project> Build Service (<Your Organization>)` **Read**, **Contribute**, **Create branch**, and **Create tag**. Use the project identity, not the collection-wide group. If it is missing, follow the [initial-run identity caveat](setup.md#6-grant-build-service-permissions); inspect any partial publication before retrying.
4. If repository access protection is enabled, approve this pipeline's access to this repository when prompted. Do not replace the job token with a PAT.
5. Open the saved pipeline, choose **Run pipeline → master → Run**. Approve repository access if prompted and wait for the complete run, including publication, to succeed.

The adapter has **no passphrase input**: use only an approved unattended automation key, never your personal key. Use a fresh disposable hosted agent and restrict YAML/secret access. Never log the multiline key or enable tracing; masking does not reliably hide its individual lines. No export file is needed, but GPG stores the imported key in the agent keyring. See [operational safety](setup.md#operational-safety-and-limitations).

The first push is not retroactively triggered by creating a pipeline. A manual run of the latest bootstrap commit is required. Expected result: a signed bot bump commit changes `.cz.toml` from `0.0.1` to stable **`0.1.0`**, and signed tag **`0.1.0`** is published. Pull and fetch before doing anything else:

```bash
git checkout master
git pull --ff-only origin master
git fetch origin --tags
git tag -v 0.1.0
git log -2 --oneline
```

If the run fails, inspect its decision and publication output and the remote state before retrying. Do not manually create a competing tag or locally bump to compensate for a permission failure.

## 5. Set PR policy and create develop from the stable bot commit

Configure **Project settings → Repositories → this repository → Settings** to disable the PR-ID prefix in completion messages if available. The engine also recognizes `Merged PR 42:` on older installations. In branch policies protect `master` and `develop` with required reviews; use a separate read-only validation pipeline, not this mutating version pipeline, as a PR build policy.

This direct-change mode permits human stabilization/synchronization pushes on `release/*` and `hotfix/*`. Permit squash and basic merge completion; the backmerge PRs below require **Merge (no fast-forward)** to preserve ancestry.

Only the automation may receive a minimal administrator-approved branch-scoped exception needed for its direct version commits under required-PR policies. Do not grant humans blanket bypass. Restrict authorized YAML/signing-key access.

**For every PR below:** push the source, then in **Repos → Pull requests → New pull request** select the stated source and target, enter the exact title, and create it. Review the diff, obtain required approvals/checks, choose **Complete**, choose the stated merge type, and ensure the final commit subject is the title (the recognized Azure prefix is okay). Never use rebase completion. Wait for the target's push-triggered version pipeline to finish, then run the specified pull/fetch commands. Keep release/hotfix source branches until backmerge finishes.

`git-tools pr` only generates text: it does **not** create or complete Azure PRs. Its descriptions must fit Azure's **4,000 UTF-16 code-unit** limit, not 4,000 bytes or necessarily 4,000 displayed characters. Azure origins enable the limit automatically; use `--azure-limit` for custom hosts. Inspect/shorten the final text even after regeneration. Fixed titles below override ordinary generated title suggestions.

```bash
git checkout master
git pull --ff-only origin master
git checkout -b develop
git push -u origin develop
git fetch origin --tags
```

There is no PR for this branch creation. Wait for the branch-push run: it should skip the generated bump subject. `develop` starts at stable **`0.1.0`**, with **no new tag**. Do not create it from the pre-bump bootstrap commit.

## 6. Land the first real feature on develop

```bash
git checkout develop
git pull --ff-only origin develop
git checkout -b feature/greeting
```

Create `greeting.txt` with exactly one line: `Hello, Azure!` (and a final newline).

```bash
git add greeting.txt
git commit -m "feat: add greeting"
git push -u origin feature/greeting
git fetch origin --tags
git-tools pr --base develop
```

Source **`feature/greeting` → target `develop`**, title **`feat: add greeting`**. In the Azure UI create, review, and complete this PR using **Squash**, with that completion subject. The feature-branch run skips versioning: no branch tag. Wait for the post-completion `develop` pipeline: expected `.cz.toml` and tag **`0.2.0-alpha.0`**. An ordinary feat from stable 0.1.0 selects the next minor line, 0.2.0; it does not remain on a 0.1.x alpha line. No Start PR is required here.

```bash
git checkout develop
git pull --ff-only origin develop
git fetch origin --tags
git show 0.2.0-alpha.0:.cz.toml
```

## 7. Land more work before cutting the release

```bash
git checkout develop
git pull --ff-only origin develop
git checkout -b feature/output-format
```

Create `output-format.txt` with the line `format=plain`.

```bash
git add output-format.txt
git commit -m "feat: add output format"
git push -u origin feature/output-format
git fetch origin --tags
git-tools pr --base develop
```

Create Azure PR **`feature/output-format` → `develop`**, title **`feat: add output format`**; review and **Complete → Squash** with that subject. The source branch publishes no tag. Wait for the target pipeline: `develop` becomes **`0.2.0-alpha.1`**, with tag **`0.2.0-alpha.1`** (not `0.3.0`).

```bash
git checkout develop
git pull --ff-only origin develop
git fetch origin --tags
```

## 8. Cut release/0.2.0, then open the next develop line

```bash
git checkout develop
git pull --ff-only origin develop
git checkout -b release/0.2.0
git push -u origin release/0.2.0
git fetch origin --tags
```

This is branch creation, not a PR or promotion. Wait for its push pipeline: cutting alone leaves **`0.2.0-alpha.1`**, with **no new tag and no RC**. The release needs a unique human stabilization change below to open `rc.0`.

Release-led does not require a Start at the cut: the release branch selects the release target, and develop could continue 0.2.0 alphas independently. Here we deliberately use the optional `Start 0.3.0` to isolate new development and show how an already-ahead alpha survives backmerge. The release target remains 0.2.0, a valid minor step from stable master 0.1.0.

```bash
git checkout develop
git pull --ff-only origin develop
git checkout -b feature/next-cycle
```

Create `next-cycle.txt` with the line `Next cycle: configurable greeting`.

```bash
git add next-cycle.txt
git commit -m "feat: plan configurable greeting"
git push -u origin feature/next-cycle
git fetch origin --tags
git-tools pr --base develop --start-pr --workflow-version 0.3.0
```

Create Azure PR **`feature/next-cycle` → `develop`**, title **`Start 0.3.0`**; review and **Complete → Squash** with that exact subject. Wait for the target pipeline: **`0.3.0-alpha.0`**, tag **`0.3.0-alpha.0`**. No source-branch tag.

```bash
git checkout develop
git pull --ff-only origin develop
git fetch origin --tags
```

## 9. Stabilize the release with a real change and open RC

```bash
git checkout release/0.2.0
git pull --ff-only origin release/0.2.0
```

Create `release-check.txt` with the line `0.2.0 check: greeting and plain output verified`.

```bash
git add release-check.txt
git commit -m "fix: record verified release behavior"
git push origin release/0.2.0
```

This is a direct stabilization push to `release/0.2.0`, not a PR (source and target are that branch; subject `fix: record verified release behavior`). Wait for its push pipeline. No empty opener is needed because the file really changed.

Expected release version and signed tag: **`0.2.0-rc.0`**. A later meaningful stabilization change on this branch would produce `0.2.0-rc.1`; we use one RC here so the rest of the sequence stays deterministic.

```bash
git checkout release/0.2.0
git pull --ff-only origin release/0.2.0
git fetch origin --tags
git show 0.2.0-rc.0:.cz.toml
```

## 10. Promote release/0.2.0 to master

```bash
git checkout master
git pull --ff-only origin master
git checkout release/0.2.0
git pull --ff-only origin release/0.2.0
git fetch origin --tags
git-tools pr --base master --release-pr
```

Master is still `0.1.0`, the base from which this cycle began: no pre-promotion master sync is needed in this serial example. Create Azure PR **`release/0.2.0` → `master`**, title **`Release 0.2.0`**. Review and **Complete → Squash**, final subject `Release 0.2.0`, **without deleting the source**. Wait for the master push pipeline to finalize the merged RC: stable **`0.2.0`** and signed tag **`0.2.0`**. Develop is still `0.3.0-alpha.0`.

```bash
git checkout master
git pull --ff-only origin master
git fetch origin --tags
git tag -v 0.2.0
```

Squash promotion did not make the release branch an ancestor of master. Before backmerging, synchronize both master and develop into the retained source as below. Do not cherry-pick the fixes and call that a backmerge.

## 11. Synchronize the promoted release source for backmerge

```bash
git checkout release/0.2.0
git pull --ff-only origin release/0.2.0
git fetch origin --tags
git merge --no-ff --no-commit origin/master
```

This folds in the post-promotion master history, including its stable bot commit. If Git reports conflicts, resolve all of them: retain all real feature/fix files, and for this **intermediate** master merge keep `.cz.toml` at **`0.2.0-rc.0`** (preserve its other settings). This is not the final develop version. Stage the resolved files and make the merge commit:

```bash
git add .cz.toml
git add -u
git commit -m "chore(release): synchronize promoted master"
git merge --no-ff --no-commit origin/develop
```

Resolve this second merge before committing. Retain all real files from both sides, including the stabilization fix; set `.cz.toml`'s version to the current develop version **`0.3.0-alpha.0`** and keep its other settings unchanged. This intentional version choice is by release policy, not lexical string order. If there are no conflicts, still inspect `.cz.toml` and set that same value. Stage any additional resolved files explicitly. Then:

```bash
git add .cz.toml
git add -u
git diff --cached
git commit -m "chore: merge develop for backmerge"
git push origin release/0.2.0
```

This is one direct synchronization push to **`release/0.2.0`**, not a PR. The final subject is **`chore: merge develop for backmerge`**. Push only after both local merges are committed, not between them. Wait for its push pipeline.

The exact prep subject selects the special no-tag strategy before normal release/hotfix line checks. Expected source version: **`0.3.0-alpha.1`**, **no tag**. This is a disposable backmerge-prepared source, no longer a candidate to promote to master. It has incorporated develop's ahead alpha and advanced it once.

```bash
git checkout release/0.2.0
git pull --ff-only origin release/0.2.0
git fetch origin --tags
```

Do not squash away this untagged preparation bump: its commit is the version history baseline the engine needs. The boundary backmerge in the next step must also retain ancestry. If policies allow only squash, stop and have an administrator allow the required merge type before continuing.

## 12. Backmerge the release into develop without a tag

```bash
git checkout release/0.2.0
git pull --ff-only origin release/0.2.0
git fetch origin --tags
git-tools pr --base develop --backmerge-release-pr
```

Create Azure PR **`release/0.2.0` → `develop`**, title **`Backmerge Release 0.2.0`**. Review and **Complete → Merge (no fast-forward)**, with that final subject, not squash and not `Release 0.2.0`. Wait for the develop push pipeline. The source brings `0.3.0-alpha.1` and its untagged bump history; the unique `release-check.txt` is meaningful content, so the engine advances to **`0.3.0-alpha.2`**, **without creating a tag**. It does not reopen 0.2.0 or tag another stable release. Fetching tags does not create the missing alpha tags.

```bash
git checkout develop
git pull --ff-only origin develop
git fetch origin --tags
git log -4 --oneline
```

Verify the release check file is present and `.cz.toml` reads `0.3.0-alpha.2`. Only now may you delete the release source and its completed helper branches in Azure. Backmerges advance an ahead alpha only for meaningful unique changes; version-only/no-op backmerges can leave the version unchanged. If develop is not ahead, the rules can instead catch up to the promoted stable line, still without tagging. Those alternate histories are not the one followed here.

## 13. Create a hotfix from stable master and open its patch RC

```bash
git checkout master
git pull --ff-only origin master
git fetch origin --tags
git checkout -b hotfix/timeout
git push -u origin hotfix/timeout
```

No PR for branch creation. Wait for the branch-push pipeline: with no unique fix yet it skips; version remains stable **`0.2.0`**, **no new tag**.

Create `timeout.txt` with exactly the line `timeout_seconds=30`.

```bash
git add timeout.txt
git commit -m "fix: set safe timeout"
git push origin hotfix/timeout
```

This is a direct fix push to `hotfix/timeout`, not a PR; subject `fix: set safe timeout`. Wait for its push pipeline.

Expected version and signed tag: **`0.2.1-rc.0`**. Hotfix selects the next patch from current stable master, not from develop's 0.3.0 alpha.

```bash
git checkout hotfix/timeout
git pull --ff-only origin hotfix/timeout
git fetch origin --tags
```

## 14. Promote the hotfix to master

```bash
git checkout master
git pull --ff-only origin master
git checkout hotfix/timeout
git pull --ff-only origin hotfix/timeout
git fetch origin --tags
git-tools pr --base master --hotfix-pr
```

Master has not moved since this hotfix was cut, so no pre-promotion sync is needed. Create Azure PR **`hotfix/timeout` → `master`**, title **`Hotfix 0.2.1`**. Review and **Complete → Squash**, final subject `Hotfix 0.2.1`, keeping the source branch. Wait for the master push pipeline: stable **`0.2.1`** and signed tag **`0.2.1`**. Develop remains `0.3.0-alpha.2` for now.

```bash
git checkout master
git pull --ff-only origin master
git fetch origin --tags
git tag -v 0.2.1
```

## 15. Synchronize the promoted hotfix source for backmerge

```bash
git checkout hotfix/timeout
git pull --ff-only origin hotfix/timeout
git fetch origin --tags
git merge --no-ff --no-commit origin/master
```

This folds in the post-promotion master history, including its stable bot commit. If Git reports conflicts, resolve all of them: retain all real feature/fix files, and for this **intermediate** master merge keep `.cz.toml` at **`0.2.1-rc.0`** (preserve its other settings). This is not the final develop version. Stage the resolved files and make the merge commit:

```bash
git add .cz.toml
git add -u
git commit -m "chore(release): synchronize promoted master"
git merge --no-ff --no-commit origin/develop
```

Resolve this second merge before committing. Retain all real files from both sides, including the stabilization fix; set `.cz.toml`'s version to the current develop version **`0.3.0-alpha.2`** and keep its other settings unchanged. This intentional version choice is by release policy, not lexical string order. If there are no conflicts, still inspect `.cz.toml` and set that same value. Stage any additional resolved files explicitly. Then:

```bash
git add .cz.toml
git add -u
git diff --cached
git commit -m "chore: merge develop for backmerge"
git push origin hotfix/timeout
```

This is one direct synchronization push to **`hotfix/timeout`**, not a PR. The final subject is **`chore: merge develop for backmerge`**. Push only after both local merges are committed, not between them. Wait for its push pipeline.

The exact prep subject selects the special no-tag strategy before normal release/hotfix line checks. Expected source version: **`0.3.0-alpha.3`**, **no tag**. This is a disposable backmerge-prepared source, no longer a candidate to promote to master. It has incorporated develop's ahead alpha and advanced it once.

```bash
git checkout hotfix/timeout
git pull --ff-only origin hotfix/timeout
git fetch origin --tags
```

Do not squash away this untagged preparation bump: its commit is the version history baseline the engine needs. The boundary backmerge in the next step must also retain ancestry. If policies allow only squash, stop and have an administrator allow the required merge type before continuing.

## 16. Backmerge the hotfix and resume the next cycle

```bash
git checkout hotfix/timeout
git pull --ff-only origin hotfix/timeout
git fetch origin --tags
git-tools pr --base develop --backmerge-hotfix-pr --workflow-version 0.2.1
```

The explicit workflow version is required for this helper after synchronization: the source now carries an alpha, which is not the historical promoted hotfix identity. Create Azure PR **`hotfix/timeout` → `develop`**, title **`Backmerge Hotfix 0.2.1`**. Review and **Complete → Merge (no fast-forward)**, with that exact subject. Do not squash or use `Hotfix 0.2.1` on develop. Wait for the develop push pipeline: the unique timeout file is meaningful, so `.cz.toml` becomes **`0.3.0-alpha.4`**, **no tag**. This preserves the ahead line, rather than resetting develop to 0.2.1. Pull the bot commit and fetch:

```bash
git checkout develop
git pull --ff-only origin develop
git fetch origin --tags
```

Verify `timeout.txt` and `release-check.txt` are present, then delete the retained hotfix/helper branches in Azure if desired. Continue with actual next-cycle work:

```bash
git checkout -b feature/configuration
```

Create `configuration.txt` with the line `greeting_style=configurable`.

```bash
git add configuration.txt
git commit -m "feat: add greeting configuration"
git push -u origin feature/configuration
git fetch origin --tags
git-tools pr --base develop
```

Create Azure PR **`feature/configuration` → `develop`**, title **`feat: add greeting configuration`**; review and **Complete → Squash** with that subject. Source run: skip, no tag. Wait for the target pipeline: expected version and tag **`0.3.0-alpha.5`**. The untagged backmerge bump history lets normal tagged development resume without inventing alpha.1–alpha.4 tags.

```bash
git checkout develop
git pull --ff-only origin develop
git fetch origin --tags
git show 0.3.0-alpha.5:.cz.toml
```

You are now developing 0.3.0 while master is stable 0.2.1. For the next release, cut `release/0.3.0` from the latest pulled develop commit, stabilize it with real changes, and repeat promotion/sync/backmerge. In classic, the first develop PR after that cut must be `Start 0.4.0`; in release-led that Start is optional.

## 17. Handle divergence safely and check the completed sequence

The concrete run deliberately had no concurrent master updates before either promotion. In real work, re-fetch master before each promotion. If it moved, merge its actual changes into the candidate and resolve version files to the intended candidate line before promoting; never discard a production fix.

In this direct mode, merge master into the candidate locally with a suitable Conventional Commit subject, resolve conflicts, push the candidate, wait for its pipeline, then pull/fetch before promotion. A meaningful integration can advance RC. If master has already shipped the target, stop and recut/retarget appropriately instead of trying to force a stale release or hotfix line.

After a squash promotion, the paired master/develop preparation merges above deliberately stay local until their final prep subject is ready. In reviewed mode they stay on the helper until its inner PR is completed. This avoids publishing an intermediate source with stable or mismatched version state. Backmerge-prepared sources must never be promoted again.

Final expected checkpoints for this exact serial example:

| Event | Version after target pipeline | New tag? |
| --- | --- | --- |
| Manual master bootstrap | `0.1.0` | `0.1.0` |
| First feature on develop | `0.2.0-alpha.0` | yes |
| More develop work | `0.2.0-alpha.1` | yes |
| Cut release branch only | `0.2.0-alpha.1` on release | no |
| Start next develop cycle | `0.3.0-alpha.0` | yes |
| Release stabilization | `0.2.0-rc.0` | yes |
| Release promotion to master | `0.2.0` | yes |
| Release source backmerge preparation | `0.3.0-alpha.1` | **no** |
| Release backmerge to develop | `0.3.0-alpha.2` | **no** |
| Hotfix stabilization | `0.2.1-rc.0` | yes |
| Hotfix promotion to master | `0.2.1` | yes |
| Hotfix source backmerge preparation | `0.3.0-alpha.3` | **no** |
| Hotfix backmerge to develop | `0.3.0-alpha.4` | **no** |
| Ordinary next-cycle feature | `0.3.0-alpha.5` | yes |

All tags in this example use the bare version, with no `v` prefix. If using a real application with auxiliary version files, preserve the intended version consistently in those files during conflict resolution too. `.cz.toml` remains the authority; see [versioning](../versioning.md) and [publication/recovery](../publication.md) before repairing partial failures.

## Mode Policy and Edge Cases

Release-led lets `release/X.Y.Z` select the final release line; human stabilization changes are direct pushes. Use [Release-led — Reviewed](release-led-reviewed-walkthrough.md) for required inner PRs. These rules generalize the concrete journey; optional alternatives are not extra steps to run in that sequence.

### Feature and Bugfix Policy

Most feature/bugfix PRs into develop use Conventional Commit titles and create/continue tagged alphas. On a fresh develop branch matching stable, the first real PR may instead use `Start X.Y.Z` while its source commit remains Conventional Commit based. An ordinary `feat` from stable also selects the next minor alpha, as demonstrated above.

### Release-Line Policy

The **release branch name selects the target tuple**. Creation alone does not open RC. Unlike classic, cutting a release does **not require** a next-cycle Start on develop: develop can continue its current alpha line independently. To explicitly isolate the next cycle, use a real develop PR with `git-tools pr --base develop --start-pr --workflow-version A.B.C`, where `A.B.C` is an exact valid forward tuple. Complete it as `Start A.B.C` to obtain tagged `A.B.C-alpha.0`; a Backmerge title must not be used to open a cycle.

### Release Stabilization and Promotion

The first meaningful Conventional Commit on `release/X.Y.Z` opens `X.Y.Z-rc.0`; later meaningful commits continue RC on that locked line. With no real stabilization change, an **alternative** empty opener is `git commit --allow-empty -m "chore: open release"`; do not run it in addition to a real fix just to imitate the example.

Promote the expected RC with `Release X.Y.Z`. Integrate any newer master before promotion as described in step 17, retaining real fixes and the intended candidate version. Stop if the candidate target has already shipped rather than forcing a stale line.

### Release Backmerge

Use `Backmerge Release X.Y.Z`. If develop already has an ahead alpha, preserve that line; meaningful unique release fixes advance it once. Version-only/no-op integration can leave the version unchanged. If develop is not ahead, a backmerge may catch it up to stable `X.Y.Z` without tagging. A later `Start A.B.C` opens a new develop cycle when wanted.

For the ahead-alpha case, follow steps 11–12 to synchronize the retained source and preserve its untagged preparation bump/ancestry. Resolve `.cz.toml` and all managed project version fields consistently by intended develop policy, not lexical string order. If develop's release tuple is not ahead of the promoted target, use the [stable-catch-up procedure](#stable-catch-up-when-develop-is-not-ahead) instead of copying the numbered example's alpha. Do not promote a backmerge-prepared source to master again.

### Stable catch-up when develop is not ahead

The numbered `0.3.0-alpha.*` backmerge is the **ahead-alpha case only**. Compare numeric release tuples, not prerelease counters or lexical strings: `0.2.0-alpha.N` is not ahead of promoted stable `0.2.0`. This procedure also applies to hotfix backmerges when develop is not ahead of the promoted patch.

1. Finish promotion and fetch its existing stable tag. Synchronize the retained source with master and develop through the direct or reviewed lane in this guide. Wait for the source's no-tag preparation run and pull its result. Its resulting alpha/RC is intermediate; setting stable before the exact `chore: merge develop for backmerge` subject is not sufficient, because the prep rule can open another RC.
2. Instead of sending that intermediate version directly into develop, update develop and create a fresh `integration/*` branch **from develop**. Merge the fetched prepared release/hotfix source with `git merge --no-ff --no-commit <source-ref>`, replacing `<source-ref>` with its ref. Preserve the source's merge parents and preparation-bump history, all published fixes, and continued develop work.
3. Before committing the integration, resolve **only the managed version fields** in `.cz.toml` and synchronized manifests/lockfiles to the **already-published stable target `X.Y.Z`**, not develop's same-line alpha or the source's preparation version. Preserve all other settings and dependency/application changes; do not copy whole manifests from master. For example, a `Release 0.2.0` backmerge into `0.2.0-alpha.N` must propose stable `0.2.0` at the develop boundary.
4. Test, commit, and push the integration. Generate PR text with `git-tools pr --base develop --backmerge-release-pr --workflow-version X.Y.Z` or the matching `--backmerge-hotfix-pr --workflow-version X.Y.Z`, replacing `X.Y.Z` with the historical promoted target. Open the reviewed `integration/*` → `develop` boundary PR titled `Backmerge Release X.Y.Z` or `Backmerge Hotfix X.Y.Z`. **Complete → Merge (no fast-forward)** with that final subject, not squash; retain the prepared source's ancestry. Never promote this integration to master.
5. Verify develop contains the fixes and stable `X.Y.Z`. Its version job **skips because the boundary already matches stable**, including version-only backmerges; it must not advance the old alpha or create another stable tag. Open the next cycle later with a real `Start A.B.C` PR. The alternate histories are covered by `tests/test_backmerge_catchup.py`.

### Hotfix Stabilization and Promotion

Create `hotfix/<name>` from updated stable master. Branch creation alone opens no RC. The first meaningful Conventional Commit selects the next patch RC; later fixes advance that same line. If no real fix is needed, an empty `chore: open release` is accepted as an optional opener. Integrate newer master before promotion and use final subject `Hotfix X.Y.Z`.

### Hotfix Backmerge

Use `Backmerge Hotfix X.Y.Z`, where `X.Y.Z` is the historical promoted patch. After preparation use `git-tools pr --backmerge-hotfix-pr --workflow-version X.Y.Z` explicitly; its source may now carry an alpha instead. The same ahead-alpha, stable-catch-up, no-op, and no-tag rules as release backmerge apply. Keep the source until integration completes.

### Merge Strategy

Ordinary PRs support squash or merge commits with their final subject equal to the PR title. Prohibit rebase. The synchronization and boundary-backmerge steps here specifically require **Merge (no fast-forward)**; do not squash their parents or untagged version anchors. A supported engine normalizes Azure's optional `Merged PR <id>:` prefix.

### Synchronization Policy

Human synchronization/stabilization changes can be pushed directly in this mode. Preserve exact preparation subjects where specified, particularly `chore: merge develop for backmerge`, which selects special no-tag behavior before normal release/hotfix line checks. Wait for source CI and pull/fetch before generating promotion/backmerge text. Use the reviewed guide if those human changes must all pass through inner PRs.
