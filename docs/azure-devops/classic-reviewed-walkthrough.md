# Azure DevOps: Classic — Reviewed end-to-end walkthrough

Start with an **empty Azure Repo**, not the git-tools source checkout. This is one
continuous example, from the first commit through a release, hotfix, and next
development cycle. Commands assume Bash (or Git Bash), an authenticated Git
connection to Azure Repos, and one person coordinating these operations without
concurrent merges. Replace the organization/project/repository URL and your Git
identity; keep the example branch names, titles, and versions unchanged.

These are expected results derived from the engine and local Git checks, **not a
claim that these instructions were executed against hosted Azure DevOps**.
Stop on errors or unexpected versions instead of running later steps blindly.

## 1. Install the CLI and prepare the Azure project

Install Git, **Python 3.12**, uv, and GnuPG. See the [installation instructions](../../README.md#install)
and [provider configuration](../configuration.md). Clone the tool into a separate
directory, not into the application repository:

```bash
git clone https://github.com/davidyytan/git-tools.git git-tools-cli
cd git-tools-cli
./install.sh
```

Restart the shell after installation (`uv tool update-shell` if needed), then run:

```bash
git-tools --help
git-tools settings
```

Choose a provider, credentials, and model if you want generated commit/PR prose.
`init` and the CI engine do not need an LLM. Fixed workflow titles are
deterministic, but `git-tools pr` still uses your configured provider to generate
the description. The fixed Git messages below are deliberate: use them to
reproduce the version sequence.
As an alternative after staging a real change, preview with
`git-tools commit --no-commit --no-copy`, then `git-tools commit` to generate and
**create** a commit. Do not run both that command and the example `git commit`
for the same change. Review the generated Conventional Commit subject.

In Azure DevOps create a project/repository with **no initial README**. Ensure you
can push branches, create/complete PRs, create a YAML pipeline, and administer
its permissions (or enlist an administrator). Configure Git authentication using
your organization's approved Azure Repos method. The pipeline itself needs no
bot account, PAT, or SSH key: it uses the automatic Build Service identity.
Read [platform setup](setup.md) for credential/key-generation details.
In organization/project **Pipelines → Settings**, enable **Limit job authorization
scope to current project for non-release pipelines** before granting service permissions.

## 2. Create the local repository and copy exactly one adapter

From the `git-tools-cli` checkout, return to its parent so the two repositories are siblings:

```bash
cd ..
mkdir azure-flow-demo
cd azure-flow-demo
git init -b master
git config user.name "Your Name"
git config user.email "you@example.com"
git remote add origin https://dev.azure.com/ORG/PROJECT/_git/REPOSITORY
git-tools init --version 0.0.1 --tag-format '$version'
mkdir -p .azure/workflows
```

Copy `.azure/workflows/version-bump-git-flow-classic.yml.example` from the separate git-tools
checkout to `.azure/workflows/version-bump-git-flow-classic.yml` here (remove `.example`).
Use your actual source-checkout path, for example:

```bash
cp ../git-tools-cli/.azure/workflows/version-bump-git-flow-classic.yml.example .azure/workflows/version-bump-git-flow-classic.yml
```

In that YAML set `GIT_TOOLS_REPO` to the public git-tools repository and
`GIT_TOOLS_REF` to a supported branch or tag containing Azure subject normalization
and the selected flow. The example uses `develop`; verify its support, or use an
immutable supported tag for reproducible engine code. The adapter uses
`git clone --branch`, so a bare commit SHA is not accepted. Do not activate a second adapter.

Keep full history, tag fetching, and `persistCredentials: true`. Set:

```yaml
GIT_BOT_NAME: MyProject Versioning Automation
GIT_BOT_EMAIL: myproject-versioning@automation.invalid
GPG_SECURE_FILE: myproject-versioning-gpg-private.asc
```

Create `README.md` containing `# Azure flow demo` and `.gitignore` containing
`*-gpg-private.asc` on its own line. This deliberately minimal repository has
no package manifests: `.cz.toml` is the only managed version file. `git-tools init`
writes that file; it does not install pipelines, create branches, push, or tag.
Confirm `.cz.toml` contains `version = "0.0.1"` and `tag_format = "$version"`.

## 3. Generate the signing key, bootstrap, and push before pipeline creation

Follow [Generate the GPG Secure File](setup.md#2-generate-the-gpg-secure-file):
generate a dedicated non-interactive signing key with the matching bot email,
and export its armored private key to `myproject-versioning-gpg-private.asc`.
Keep the key out of source control; verify the ignore rule before staging:

```bash
git check-ignore myproject-versioning-gpg-private.asc
git status --short
git add README.md .gitignore .cz.toml .azure/workflows
git diff --cached
git commit -m "Release 0.1.0"
git push -u origin master
```

The check-ignore command must print the private filename. The staged diff must
contain no key or credentials. **Do not add another commit after `Release 0.1.0`
before bootstrap runs.** At this point `master` still contains version `0.0.1`,
and there is **no tag**. Push now: an empty Azure Repo cannot supply the branch/YAML
needed by the pipeline picker. No PR is involved in this one-time bootstrap.

## 4. Create and authorize the Azure pipeline, then manually bootstrap

Perform these Azure actions in order; detailed permission/key screens are in
[platform setup](setup.md#4-add-the-azure-pipeline):

1. Open **Pipelines → New pipeline → Azure Repos Git**, select this repository,
   then **Existing Azure Pipelines YAML file**. Choose `master` and
   `.azure/workflows/version-bump-git-flow-classic.yml`. Save the definition
   (do not use a generated starter YAML or create a competing pipeline).
2. Open **Pipelines → Library → Secure files → + Secure file** and upload
   `myproject-versioning-gpg-private.asc`. Its name must exactly match the YAML.
   Open its **Pipeline permissions** and authorize this pipeline specifically.
3. Under **Project settings → Repositories → this repository → Security**, grant
   `<Project> Build Service (<Organization>)` **Read**, **Contribute**,
   **Create branch**, and **Create tag**. This is the project identity, not the
   collection-wide Build Service Accounts group. Resolve any inherited denies.
4. If repository access protection is enabled, approve this pipeline's access
   to this repository when prompted. Do not replace the job token with a PAT.
5. Open the saved pipeline, choose **Run pipeline**, select **master**, and **Run**.
   If approvals pause it, authorize the Secure File/repository resources and
   resume. Wait for the complete run, including publication, to succeed.

The first push is not retroactively triggered by creating a pipeline. A manual
run of the latest bootstrap commit is required. Expected result: a signed bot
bump commit changes `.cz.toml` from `0.0.1` to stable **`0.1.0`**, and signed tag
**`0.1.0`** is published. Pull and fetch before doing anything else:

```bash
git checkout master
git pull --ff-only origin master
git fetch origin --tags
git tag -v 0.1.0
git log -2 --oneline
```

If the run fails, inspect its decision and publication output and the remote
state before retrying. Do not manually create a competing tag or locally bump
to compensate for a permission failure.

## 5. Set PR policy and create develop from the stable bot commit

Configure **Project settings → Repositories → this repository → Settings** to
disable the PR-ID prefix in completion messages if available. The engine also
recognizes `Merged PR 42:` on older installations. In branch policies protect
`master` and `develop` with required reviews; use a separate read-only validation
pipeline, not this mutating version pipeline, as a PR build policy.

Protect `release/*` and `hotfix/*` as reviewed stabilization branches too.
Humans must not directly push changes to those branches after creation.
Permit both squash and basic merge completion: inner synchronization and
backmerge PRs below require **Merge (no fast-forward)** to preserve ancestry.

Only the automation may receive a minimal administrator-approved branch-scoped
exception needed for its direct version commits under required-PR policies.
Do not grant humans blanket bypass. Restrict authorized YAML/signing-key access.

**For every PR below:** push the source, then in **Repos → Pull requests → New
pull request** select the stated source and target, enter the exact title, and
create it. Review the diff, obtain required approvals/checks, choose **Complete**,
choose the stated merge type, and ensure the final commit subject is the title
(the recognized Azure prefix is okay). Never use rebase completion. Wait for the
target's push-triggered version pipeline to finish, then run the specified
pull/fetch commands. Keep release/hotfix source branches until backmerge finishes.

`git-tools pr` only generates text: it does **not** create or complete Azure PRs.
Its descriptions must fit Azure's **4,000 UTF-16 code-unit** limit, not 4,000
bytes or necessarily 4,000 displayed characters. Azure origins enable the limit
automatically; use `--azure-limit` for custom hosts. Inspect/shorten the final
text even after regeneration. Fixed titles below override ordinary generated title suggestions.

```bash
git checkout master
git pull --ff-only origin master
git checkout -b develop
git push -u origin develop
git fetch origin --tags
```

There is no PR for this branch creation. Wait for the branch-push run: it should
skip the generated bump subject. `develop` starts at stable **`0.1.0`**, with
**no new tag**. Do not create it from the pre-bump bootstrap commit.

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
git-tools pr --base develop --start-pr --workflow-version 0.2.0
```

Source **`feature/greeting` → target `develop`**, title **`Start 0.2.0`**.
In the Azure UI create, review, and complete this PR using **Squash**, with that
completion subject. The feature-branch run skips versioning: no branch tag.
Wait for the post-completion `develop` pipeline: expected `.cz.toml` and tag
**`0.2.0-alpha.0`**. The fixed Start title explicitly opens the minor line; the source commit remains Conventional Commit based.

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

Create Azure PR **`feature/output-format` → `develop`**, title
**`feat: add output format`**; review and **Complete → Squash** with that subject.
The source branch publishes no tag. Wait for the target pipeline: `develop`
becomes **`0.2.0-alpha.1`**, with tag **`0.2.0-alpha.1`** (not `0.3.0`).

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

This is branch creation, not a PR or promotion. Wait for its push pipeline:
cutting alone leaves **`0.2.0-alpha.1`**, with **no new tag and no RC**.
The release needs a unique human stabilization change below to open `rc.0`.

Classic now requires the first PR of the next develop cycle to be `Start 0.3.0`;
do not keep landing ordinary features on the 0.2.0 line being released.

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

Create Azure PR **`feature/next-cycle` → `develop`**, title **`Start 0.3.0`**;
review and **Complete → Squash** with that exact subject. Wait for the target
pipeline: **`0.3.0-alpha.0`**, tag **`0.3.0-alpha.0`**. No source-branch tag.

```bash
git checkout develop
git pull --ff-only origin develop
git fetch origin --tags
```

## 9. Stabilize the release with a real change and open RC

```bash
git checkout release/0.2.0
git pull --ff-only origin release/0.2.0
git checkout -b release-fix/checks
```

Create `release-check.txt` with the line `0.2.0 check: greeting and plain output verified`.

```bash
git add release-check.txt
git commit -m "fix: record verified release behavior"
git push -u origin release-fix/checks
git fetch origin --tags
git-tools pr --base release/0.2.0
```

Create Azure inner PR **`release-fix/checks` → `release/0.2.0`**, title
**`fix: record verified release behavior`**. Review the actual file diff and
**Complete → Squash** with that subject. The helper branch has no version run
under the supplied trigger. Do not create an empty opener PR or push directly
to the protected release branch. Wait for the target's post-completion pipeline.

Expected release version and signed tag: **`0.2.0-rc.0`**. A later meaningful
stabilization change on this branch would produce `0.2.0-rc.1`; we use one RC
here so the rest of the sequence stays deterministic.

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

Master is still `0.1.0`, the base from which this cycle began: no pre-promotion
master sync is needed in this serial example. Create Azure PR
**`release/0.2.0` → `master`**, title **`Release 0.2.0`**. Review and
**Complete → Squash**, final subject `Release 0.2.0`, **without deleting the source**.
Wait for the master push pipeline to finalize the merged RC: stable **`0.2.0`**
and signed tag **`0.2.0`**. Develop is still `0.3.0-alpha.0`.

```bash
git checkout master
git pull --ff-only origin master
git fetch origin --tags
git tag -v 0.2.0
```

Squash promotion did not make the release branch an ancestor of master.
Before backmerging, synchronize both master and develop into the retained
source as below. Do not cherry-pick the fixes and call that a backmerge.

## 11. Synchronize the promoted release source for backmerge through an inner PR

```bash
git checkout release/0.2.0
git pull --ff-only origin release/0.2.0
git fetch origin --tags
git checkout -b release-fix/backmerge-sync
git merge --no-ff --no-commit origin/master
```

This folds in the post-promotion master history, including its stable bot commit.
If Git reports conflicts, resolve all of them: retain all real feature/fix files,
and for this **intermediate** master merge keep `.cz.toml` at **`0.2.0-rc.0`**
(preserve its other settings). This is not the final develop version. Stage the
resolved files and make the merge commit:

```bash
git add .cz.toml
git add -u
git commit -m "chore(release): synchronize promoted master"
git merge --no-ff --no-commit origin/develop
```

Resolve this second merge before committing. Retain all real files from both
sides, including the stabilization fix; set `.cz.toml`'s version to the current
develop version **`0.3.0-alpha.0`** and keep its other settings unchanged.
This intentional version choice is by release policy, not lexical string order.
If there are no conflicts, still inspect `.cz.toml` and set that same value.
Stage any additional resolved files explicitly. Then:

```bash
git add .cz.toml
git add -u
git diff --cached
git commit -m "chore: merge develop for backmerge"
git push -u origin release-fix/backmerge-sync
git-tools pr --base release/0.2.0
```

Create Azure inner PR **`release-fix/backmerge-sync` → `release/0.2.0`**, title
**`chore: merge develop for backmerge`**. Review the actual synchronization diff,
including version resolution; it is not an empty PR. **Complete → Merge
(no fast-forward)**, not squash, with this exact completion subject. A merge
commit retains the master/develop parents of the helper's merge commits.
All human sync changes have now reached the protected source via review;
there was no direct protected-branch push. Wait for the target push pipeline.

The exact prep subject selects the special no-tag strategy before normal
release/hotfix line checks. Expected source version: **`0.3.0-alpha.1`**, **no tag**.
This is a disposable backmerge-prepared source, no longer a candidate to promote
to master. It has incorporated develop's ahead alpha and advanced it once.

```bash
git checkout release/0.2.0
git pull --ff-only origin release/0.2.0
git fetch origin --tags
```

Do not squash away this untagged preparation bump: its commit is the version
history baseline the engine needs. The boundary backmerge in the next step
must also retain ancestry. If policies allow only squash, stop and have an
administrator allow the required merge type before continuing.

## 12. Backmerge the release into develop without a tag

```bash
git checkout release/0.2.0
git pull --ff-only origin release/0.2.0
git fetch origin --tags
git-tools pr --base develop --backmerge-release-pr
```

Create Azure PR **`release/0.2.0` → `develop`**, title **`Backmerge Release 0.2.0`**.
Review and **Complete → Merge (no fast-forward)**, with that final subject, not
squash and not `Release 0.2.0`. Wait for the develop push pipeline.
The source brings `0.3.0-alpha.1` and its untagged bump history; the unique
`release-check.txt` is meaningful content, so the engine advances to
**`0.3.0-alpha.2`**, **without creating a tag**. It does not reopen 0.2.0 or
tag another stable release. Fetching tags does not create the missing alpha tags.

```bash
git checkout develop
git pull --ff-only origin develop
git fetch origin --tags
git log -4 --oneline
```

Verify the release check file is present and `.cz.toml` reads `0.3.0-alpha.2`.
Only now may you delete the release source and its completed helper branches
in Azure. Backmerges advance an ahead alpha only for meaningful unique changes;
version-only/no-op backmerges can leave the version unchanged. If develop is
not ahead, the rules can instead catch up to the promoted stable line, still
without tagging. Those alternate histories are not the one followed here.

## 13. Create a hotfix from stable master and open its patch RC

```bash
git checkout master
git pull --ff-only origin master
git fetch origin --tags
git checkout -b hotfix/timeout
git push -u origin hotfix/timeout
```

No PR for branch creation. Wait for the branch-push pipeline: with no unique
fix yet it skips; version remains stable **`0.2.0`**, **no new tag**.

```bash
git checkout -b hotfix-fix/timeout-setting
```

Create `timeout.txt` with exactly the line `timeout_seconds=30`.

```bash
git add timeout.txt
git commit -m "fix: set safe timeout"
git push -u origin hotfix-fix/timeout-setting
git fetch origin --tags
git-tools pr --base hotfix/timeout
```

Create Azure inner PR **`hotfix-fix/timeout-setting` → `hotfix/timeout`**, title
**`fix: set safe timeout`**; review the real file diff and **Complete → Squash**
with that subject. No direct protected push and no empty opener. The helper
branch has no version run under the supplied trigger. Wait for the target pipeline.

Expected version and signed tag: **`0.2.1-rc.0`**. Hotfix selects the next patch
from current stable master, not from develop's 0.3.0 alpha.

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

Master has not moved since this hotfix was cut, so no pre-promotion sync is
needed. Create Azure PR **`hotfix/timeout` → `master`**, title **`Hotfix 0.2.1`**.
Review and **Complete → Squash**, final subject `Hotfix 0.2.1`, keeping the
source branch. Wait for the master push pipeline: stable **`0.2.1`** and
signed tag **`0.2.1`**. Develop remains `0.3.0-alpha.2` for now.

```bash
git checkout master
git pull --ff-only origin master
git fetch origin --tags
git tag -v 0.2.1
```

## 15. Synchronize the promoted hotfix source for backmerge through an inner PR

```bash
git checkout hotfix/timeout
git pull --ff-only origin hotfix/timeout
git fetch origin --tags
git checkout -b hotfix-fix/backmerge-sync
git merge --no-ff --no-commit origin/master
```

This folds in the post-promotion master history, including its stable bot commit.
If Git reports conflicts, resolve all of them: retain all real feature/fix files,
and for this **intermediate** master merge keep `.cz.toml` at **`0.2.1-rc.0`**
(preserve its other settings). This is not the final develop version. Stage the
resolved files and make the merge commit:

```bash
git add .cz.toml
git add -u
git commit -m "chore(release): synchronize promoted master"
git merge --no-ff --no-commit origin/develop
```

Resolve this second merge before committing. Retain all real files from both
sides, including the stabilization fix; set `.cz.toml`'s version to the current
develop version **`0.3.0-alpha.2`** and keep its other settings unchanged.
This intentional version choice is by release policy, not lexical string order.
If there are no conflicts, still inspect `.cz.toml` and set that same value.
Stage any additional resolved files explicitly. Then:

```bash
git add .cz.toml
git add -u
git diff --cached
git commit -m "chore: merge develop for backmerge"
git push -u origin hotfix-fix/backmerge-sync
git-tools pr --base hotfix/timeout
```

Create Azure inner PR **`hotfix-fix/backmerge-sync` → `hotfix/timeout`**, title
**`chore: merge develop for backmerge`**. Review the actual synchronization diff,
including version resolution; it is not an empty PR. **Complete → Merge
(no fast-forward)**, not squash, with this exact completion subject. A merge
commit retains the master/develop parents of the helper's merge commits.
All human sync changes have now reached the protected source via review;
there was no direct protected-branch push. Wait for the target push pipeline.

The exact prep subject selects the special no-tag strategy before normal
release/hotfix line checks. Expected source version: **`0.3.0-alpha.3`**, **no tag**.
This is a disposable backmerge-prepared source, no longer a candidate to promote
to master. It has incorporated develop's ahead alpha and advanced it once.

```bash
git checkout hotfix/timeout
git pull --ff-only origin hotfix/timeout
git fetch origin --tags
```

Do not squash away this untagged preparation bump: its commit is the version
history baseline the engine needs. The boundary backmerge in the next step
must also retain ancestry. If policies allow only squash, stop and have an
administrator allow the required merge type before continuing.

## 16. Backmerge the hotfix and resume the next cycle

```bash
git checkout hotfix/timeout
git pull --ff-only origin hotfix/timeout
git fetch origin --tags
git-tools pr --base develop --backmerge-hotfix-pr --workflow-version 0.2.1
```

The explicit workflow version is required for this helper after synchronization:
the source now carries an alpha, which is not the historical promoted hotfix
identity. Create Azure PR **`hotfix/timeout` → `develop`**, title
**`Backmerge Hotfix 0.2.1`**. Review and **Complete → Merge (no fast-forward)**,
with that exact subject. Do not squash or use `Hotfix 0.2.1` on develop.
Wait for the develop push pipeline: the unique timeout file is meaningful, so
`.cz.toml` becomes **`0.3.0-alpha.4`**, **no tag**. This preserves the ahead line,
rather than resetting develop to 0.2.1. Pull the bot commit and fetch:

```bash
git checkout develop
git pull --ff-only origin develop
git fetch origin --tags
```

Verify `timeout.txt` and `release-check.txt` are present, then delete the retained
hotfix/helper branches in Azure if desired. Continue with actual next-cycle work:

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

Create Azure PR **`feature/configuration` → `develop`**, title
**`feat: add greeting configuration`**; review and **Complete → Squash** with
that subject. Source run: skip, no tag. Wait for the target pipeline: expected
version and tag **`0.3.0-alpha.5`**. The untagged backmerge bump history lets
normal tagged development resume without inventing alpha.1–alpha.4 tags.

```bash
git checkout develop
git pull --ff-only origin develop
git fetch origin --tags
git show 0.3.0-alpha.5:.cz.toml
```

You are now developing 0.3.0 while master is stable 0.2.1. For the next release,
cut `release/0.3.0` from the latest pulled develop commit, stabilize it with real
changes, and repeat promotion/sync/backmerge. In classic, the first develop PR
after that cut must be `Start 0.4.0`; in release-led that Start is optional.

## 17. Handle divergence safely and check the completed sequence

The concrete run deliberately had no concurrent master updates before either
promotion. In real work, re-fetch master before each promotion. If it moved,
merge its actual changes into the candidate and resolve version files to the
intended candidate line before promoting; never discard a production fix.

In this reviewed mode, do that on a fresh `release-fix/*` or `hotfix-fix/*`
branch based on the candidate. Push only the helper, create an Azure PR to the
candidate with a Conventional Commit title such as `fix: integrate current master`,
review the real diff, and **Complete → Merge (no fast-forward)** with that title.
Wait for the candidate pipeline, then pull/fetch it before generating the
promotion PR. A meaningful integration can advance RC, so inspect the result
rather than assuming the `rc.0` values above. If master has already shipped the
candidate's target, stop and recut/retarget appropriately; do not force stale
hotfix or release versions. The same inner-PR requirement applies to all human
synchronization and conflict-resolution changes, not just code fixes.

After a squash promotion, the paired master/develop preparation merges above
deliberately stay local until their final prep subject is ready. In reviewed
mode they stay on the helper until its inner PR is completed. This avoids
publishing an intermediate source with stable or mismatched version state.
Backmerge-prepared sources must never be promoted again.

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

All tags in this example use the bare version, with no `v` prefix. If using a
real application with auxiliary version files, preserve the intended version
consistently in those files during conflict resolution too. `.cz.toml` remains
the authority; see [versioning](../versioning.md) and
[publication/recovery](../publication.md) before repairing partial failures.
