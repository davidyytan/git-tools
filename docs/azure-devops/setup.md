# Azure DevOps Setup

[Azure DevOps guides](README.md) · [Documentation index](../README.md) · [CLI usage](../usage.md)

This guide sets up a classic or release-led (variant) Git Flow versioning
pipeline in an Azure Repos repository.

The Azure pipeline and GitHub Actions workflow use different CI YAML, but both
run the same `git_tools.generators.bumpgen` versioning engine.

See the [Azure flow index](README.md) for all four flow policies and
[CLI usage](../usage.md) for direct commands and interactive navigation.

## Before You Start

- This project uses `master`.
- Choose classic or release-led (variant). Reviewed workflows use the same
  adapter as their corresponding base flow; the extra review layer is a PR process.
- You need permission to create an Azure pipeline and configure repository
  security, or an administrator who can grant the required permissions.
- In **Organization settings → Pipelines → Settings** or **Project settings →
  Pipelines → Settings**, enable **Limit job authorization scope to current
  project for non-release pipelines**. The YAML pipeline is a non-release
  pipeline even when managing Git release branches. This runbook requires a
  project-scoped job token; otherwise the collection-scoped identity may run
  the job and grants to the project identity will not apply. Organization-level
  enforcement cannot be relaxed at project level.
- Install `git-tools` locally as described in [CLI usage](../usage.md), and
  configure a provider/model for AI-generated commit and PR text. Fixed-title
  helpers and the CI versioning engine do not require an Azure API token.
- You do not need an Azure DevOps bot user, SSH key, or personal access token.
  The pipeline pushes through Azure DevOps' automatic Build Service identity.

## Naming Convention

Use a short lowercase slug for the Azure DevOps project, such as `myproject`.
The examples below assume one signing key shared by repositories in that
project:

| Resource | Recommended name | Scope |
| --- | --- | --- |
| Pipeline YAML file | `.azure/workflows/version-bump-git-flow-classic.yml` | Per repo |
| Azure pipeline definition | `<repo-slug>-version-bump-classic` | Per repo |
| GPG key identity | `MyProject Versioning Automation` | Per project |
| GPG key email | `myproject-versioning@automation.invalid` | Per project |
| Secure File | `myproject-versioning-gpg-private.asc` | Per project |
| Build Service identity | `<Project> Build Service (<Organization>)` | Automatic per project |

Keep variable keys such as `GIT_BOT_NAME`, `GIT_BOT_EMAIL`, and
`GPG_SECURE_FILE` unchanged. Only their values vary. If security policy
requires one key per repository, replace `myproject` with the repository slug
in the key email and Secure File name.

## 1. Copy and Configure the Pipeline File

From the target repository root, initialize Git on `master` if needed:

```bash
git init -b master
```

Choose **one** Azure Pipelines example from this repository and copy it into
the target repository, removing the `.example` suffix:

| Flow | Source example in git-tools | Destination in your repository |
| --- | --- | --- |
| Classic / Classic — Reviewed | `.azure/workflows/version-bump-git-flow-classic.yml.example` | `.azure/workflows/version-bump-git-flow-classic.yml` |
| Release-led / Release-led — Reviewed | `.azure/workflows/version-bump-git-flow-variant-release-led.yml.example` | `.azure/workflows/version-bump-git-flow-variant-release-led.yml` |

Do not activate both adapters for the same repository and branches. The steps
below use classic filenames; substitute the variant filename and use a
`<repo-slug>-version-bump-variant` pipeline name when choosing release-led.

Azure DevOps does not require a particular YAML folder, but this project uses
`.azure/workflows/` by convention. `git-tools init` writes `.cz.toml` only: it
does not install a pipeline, create branches, upload signing keys, grant
permissions, or create/complete PRs. Copying YAML is not enough; create and
authorize the pipeline definition using the steps below.

- [Classic adapter source](../../.azure/workflows/version-bump-git-flow-classic.yml.example)
- [Release-led adapter source](../../.azure/workflows/version-bump-git-flow-variant-release-led.yml.example)

Set the workflow to use the git-tools public repository. The selected ref must
contain Azure DevOps merge-subject normalization and the chosen strategy.
Verify that `develop` contains that support before using the default below,
or select a supported branch/tag. The adapter uses `git clone --branch`, so
`GIT_TOOLS_REF` must be a branch or tag, not a bare commit SHA; use an immutable
tag for a pinned engine revision. The ref must include
`normalize_workflow_subject` handling `Merged PR <id>:` and
`decide_version_strategy(..., flow="classic"/"variant")`. Do not assume an
older published ref supports Azure merely because it can be cloned.

```yaml
GIT_TOOLS_REPO: https://github.com/davidyytan/git-tools.git
GIT_TOOLS_REF: develop
```

Configure the Git author and Secure File name:

```yaml
GIT_BOT_NAME: MyProject Versioning Automation
GIT_BOT_EMAIL: myproject-versioning@automation.invalid
GPG_SECURE_FILE: myproject-versioning-gpg-private.asc
```

`GIT_BOT_NAME` and `GIT_BOT_EMAIL` control the author shown on generated
commits. They do not need to represent an Azure DevOps account. The email
should match the GPG key identity generated in the next step.

**Reuse scope:** the same name and email can be reused across repositories and
projects when they use the same signing identity. Use different values if a
project or repository has its own GPG key or compliance identity.

## 2. Generate the GPG Secure File

Generate a dedicated signing key locally:

```bash
gpg --batch \
  --passphrase '' \
  --quick-generate-key \
  "MyProject Versioning Automation <myproject-versioning@automation.invalid>" \
  rsa3072 sign 2y
```

The empty passphrase allows the pipeline agent to sign non-interactively.
Adjust the two-year expiration to match the organization's key-rotation policy.

**Reuse scope:** a GPG signing key can be reused by multiple repositories and
across Azure DevOps projects. For stronger isolation, use one key per project
or one per repository. One key per project is a practical default: repositories
in that project share the signing identity, while different projects can
rotate or revoke their keys independently.

Confirm that the private key exists:

```bash
gpg --list-secret-keys "myproject-versioning@automation.invalid"
```

From the target repository root, ignore private-key exports before creating
the file:

```bash
printf '\n*-gpg-private.asc\n' >> .gitignore
```

Export the key into the repository directory:

```bash
gpg --armor \
  --export-secret-keys \
  "myproject-versioning@automation.invalid" \
  > myproject-versioning-gpg-private.asc
```

Confirm that Git ignores the private key:

```bash
git check-ignore myproject-versioning-gpg-private.asc
```

The command should print `myproject-versioning-gpg-private.asc`. Do not continue to
`git add -A` unless the file is ignored. You will upload it to Azure DevOps
after creating the pipeline.

## Local CLI and PR Descriptions

Direct `git-tools commit` generates and commits by default; use `--no-commit`
to review output first. See [configuration](../configuration.md) for provider
settings and [CLI usage](../usage.md) for direct and interactive options.

`git-tools pr` generates title/description text; it does not create or complete
an Azure Repos PR. Push the source branch, then open **Repos → Pull requests →
New pull request**, select the documented target, and paste the output.

Azure descriptions are limited to **4,000 UTF-16 code units**. The CLI detects
Azure HTTPS/SSH origins, including legacy `visualstudio.com` URLs. Force the
limit for custom hosts with `--azure-limit`; `--no-azure-limit` disables it for
output not intended for Azure. Oversized output is regenerated once from the
original inputs, then retained with a warning if still too long. Verify and
shorten the final pasted text. See [CLI usage](../usage.md) for options,
interactive navigation, and saved preferences.

## Bootstrap `master` and `develop`

The bootstrap sequence spans steps 3–8 below: push once, create and authorize
the pipeline, run it manually, then create `develop` from the stable bump.
Do not repeat this sequence in an already initialized repository.

## 3. Bootstrap and Push `master`

An empty Azure Repo has no branch for the pipeline picker to discover. Push the
bootstrap commit before creating the Azure pipeline:

```bash
git remote add origin \
  "https://dev.azure.com/<organization>/<project>/_git/<repository>"
git-tools init
git add -A
git commit -m "Release 0.1.0"
git push -u origin master
```

`git-tools init` creates `.cz.toml` with bootstrap version `0.0.1`. If
`pyproject.toml` contains `[project].version`, initialize it to `0.0.1` too.

After pushing, set the Azure Repos default branch to `master` in repository
settings. Direct `git-tools init` seeds `0.0.1`; interactive initialization
must retain that bootstrap baseline for the same result.

The recommended first commit subject is:

```text
Release 0.1.0
```

`Release 0.0.1` is also accepted by the engine for the first bootstrap commit;
use `Release 0.1.0` for the documented `0.1.0` result.

## 4. Add the Azure Pipeline

After the first push:

1. Open **Pipelines → New pipeline**.
2. Select **Azure Repos Git**.
3. Select the target repository.
4. Select **Existing Azure Pipelines YAML file**.
5. Select the `master` branch.
6. Select `/.azure/workflows/version-bump-git-flow-classic.yml`.
7. Select **Save**. Do not run the pipeline yet.
8. Rename the pipeline to `<repo-slug>-version-bump-classic` so it is easy to
   distinguish from pipelines for other repositories in the project.

**Reuse scope:** create a separate Azure pipeline definition for each
repository, even when every definition uses identical YAML contents. Do not
create two active versioning pipelines for the same repository and branches,
because both could try to create the same bump and tag.

The pipeline clones the public `git-tools` repository over HTTPS and runs the
same versioning engine used by GitHub Actions.

## 5. Upload the GPG Secure File

In Azure DevOps:

1. Open **Pipelines → Library → Secure files**.
2. Select **+ Secure file**.
3. Upload `myproject-versioning-gpg-private.asc` from the repository directory.
4. Confirm that Azure DevOps shows the filename as:

   ```text
   myproject-versioning-gpg-private.asc
   ```

The filename must exactly match the pipeline setting:

```yaml
GPG_SECURE_FILE: myproject-versioning-gpg-private.asc
```

Do not store the private key in an ordinary pipeline variable.

**Reuse scope:** Secure Files belong to an Azure DevOps project. Within the
same project, upload the key once and authorize each repository's pipeline to
use that Secure File. For a repository in a different project, upload the key
to that project's Library separately, even when reusing the same GPG key and
filename.

After upload:

- keep an approved backup in the organization's secret manager;
- remove the exported file from the repository directory after upload:

  ```bash
  rm myproject-versioning-gpg-private.asc
  ```

- never force-add or commit the `.asc` file.

## 6. Authorize the Pipeline to Use the Secure File

1. Open **Pipelines → Library → Secure files**.
2. Select `myproject-versioning-gpg-private.asc`.
3. Open the **Pipeline permissions** section.
4. Select **+** to add an authorized pipeline.
5. Select the versioning pipeline and confirm the authorization.

Alternatively, **Open access** allows every pipeline in the project to use the
Secure File. Prefer pipeline-specific authorization when possible.

## 7. Grant Build Service Permissions

Azure DevOps automatically creates a license-free pipeline identity:

```text
<Project name> Build Service (<Organization>)
```

**Initial-run identity caveat:** the project Build Service identity is created
when a pipeline in the project first runs, not necessarily when its definition
is saved. If it is absent from the identity picker, authorize the Secure File
and queue an initial run to materialize it. That first attempt may fail at
checkout or push because permissions have not yet been granted. Once the
identity appears, grant the permissions below and rerun on `master`. Do not
work around this by granting the collection-wide group. Check whether the
failed attempt created a bump commit or tag before rerunning; if it did, pull
and fetch tags and inspect the pipeline decision rather than repeating the
bootstrap commit.

**Reuse scope:** pipelines and repositories in the same Azure DevOps project
use this project Build Service identity. Each Azure DevOps project has its own
Build Service identity; it is not shared across projects.

Open:

```text
Project settings
→ Repositories
→ <repository>
→ Security
```

Select the project Build Service identity and set **Allow** for:

- `Read`
- `Contribute`
- `Create branch`
- `Create tag`

**Reuse scope:** permissions are evaluated for each repository. For least
privilege, grant them separately on every repository that uses the versioning
pipeline. If every repository in the project should use this automation, an
administrator may instead grant the permissions at **All repositories** so
repos inherit them. Permissions must be configured again in each Azure DevOps
project for that project's Build Service identity.

Do not select the general **Project Collection Build Service Accounts** group.
Do not grant **Bypass policies when pushing** unless an explicit repository
policy requires it and an administrator approves the exception.

If the project protects repository access from YAML pipelines, authorize the
pipeline to access the repository when Azure DevOps prompts for approval.

## 8. Run the Bootstrap Pipeline

After the pipeline, Secure File authorization, and Build Service permissions
are ready, manually run the pipeline against `master`:

1. Open **Pipelines** and select the versioning pipeline.
2. Select **Run pipeline**.
3. Choose the `master` branch.
4. Select **Run**.

The first push happened before the pipeline existed, so it does not trigger a
run retroactively.

With `.cz.toml` at `0.0.1` and latest commit subject `Release 0.1.0`, the run
should create:

```text
bump: version 0.0.1 → 0.1.0
```

and signed tag:

```text
0.1.0
```

After the run succeeds:

```bash
git pull origin master
git fetch origin --tags
git tag -v 0.1.0
```

A normal `git pull` might fetch the generated commit without displaying the
new tag locally, so fetch tags explicitly.

Create `develop` from the bumped `master`, not from the original bootstrap
commit:

```bash
git checkout master
git pull origin master
git checkout -b develop
git push -u origin develop
```

## Pull Request ID Setting

Azure DevOps can prefix PR-completion commit subjects like this:

```text
Merged PR 42: Release 1.2.3
```

The shared `git-tools` engine recognizes this prefix, but cleaner history is
produced by disabling it as well.

Under:

```text
Project settings
→ Repositories
→ <repository>
→ Settings
```

turn off the setting that includes the pull request ID in commit messages.
Configure this before completing PRs. It does not affect the direct bootstrap
commit.

This setting is available in Azure DevOps Services from the Sprint 270 update.
Older Azure DevOps Server versions might not expose it; the code normalizer
remains the fallback in that case.

## Merge Settings

This flow supports two Azure DevOps completion strategies:

- squash merge
- merge commit

Do not use rebase merge for this automated flow.

The final commit subject on the target branch must represent the PR title. The
runtime also ignores Azure DevOps' optional leading `Merged PR <id>:` prefix.

### Subjects into `develop`

- most feature and bugfix PRs into `develop` land with a Conventional Commit
  subject
- the first PR on a fresh develop line may land with `Start X.Y.Z`
- release backmerge PRs into `develop` must land with
  `Backmerge Release X.Y.Z`
- hotfix backmerge PRs into `develop` must land with
  `Backmerge Hotfix X.Y.Z`

### Subjects into `master`

- release promotion PRs into `master` must land with `Release X.Y.Z`
- hotfix promotion PRs into `master` must land with `Hotfix X.Y.Z`

### Squash merge profile

- complete the PR with **Squash commit**
- ensure the final squash commit subject is the PR title
- do not leave an unrelated generated subject in the completion dialog
- disable or prohibit rebase completion for this versioning flow

### Merge commit profile

- complete the PR with **Merge (no fast-forward)**
- customize the merge commit message when necessary so its subject is the PR
  title
- for the closest classic Git Flow feel, use merge commits for `feature/*`,
  `bugfix/*`, `release/*`, and `hotfix/*` PRs

Azure DevOps' generated PR-ID prefix is safe when the code normalizer is
present, but the remainder of the subject must still match the PR title.

Why:

- `develop` bump decisions depend on the final merged subject
- `master` release finalization depends on the merged prerelease state
- backmerges into `develop` must be distinguishable from release promotion
- squash and merge-commit styles both work when the final subject represents
  the PR title

## After Setup

Choose the corresponding Azure procedure (reviewed shares its base adapter):

- [Classic](classic.md)
- [Classic — Reviewed](classic-reviewed.md)
- [Release-led](release-led.md)
- [Release-led — Reviewed](release-led-reviewed.md)

Use branch policies for required reviewers and allowed merge types. Do not add
this mutating versioning pipeline as a PR build-validation policy: it reacts
to branch pushes (`pr: none` in the adapter). Use a separate read-only test
pipeline for validation. Protect `master` and `develop` and, for reviewed
flows, stabilization branches. An administrator must reconcile required-PR
policies with the automation's direct version commits; grant only the minimal
approved branch-scoped exception if necessary, not blanket bypass to humans.

## Local CLI Preferences

See [PR preferences](../usage.md) and
[configuration](../configuration.md) for persistent settings and overrides.

## Operational Safety and Limitations

The adapters are mutating push pipelines, not PR validation builds. Keep write
and signing credentials inaccessible to untrusted code and restrict who can
modify authorized YAML. Reviewed flow is a repository-policy choice, not a
compliance certification; generated bot commits still use an approved direct
push exception.

Full history, tags, and remote branch refs are required. The supplied triggers
include `master`, `develop`, `release/*`, `hotfix/*`, `feature/*`, and `bugfix/*`.
The reviewed inner branches (`release-fix/*`, `hotfix-fix/*`) do not trigger this
pipeline; their merge triggers the target stabilization branch instead.

The examples do not serialize concurrent runs. Coordinate version-producing
pushes on each branch and wait for publication before the next operation.
Racing or rejected publication must be investigated against remote refs;
never force-push a version commit or repeat bootstrap to repair it. The next
run normally skips a bot bump subject, but that does not protect against
multiple active versioning pipelines or manual version edits.

## Publication and Recovery

The selected engine ref must also contain `git_tools.generators.publish`.
Publishing dry-runs an atomic push, logs its choice, and falls back to separate
pushes only if the server explicitly lacks atomic support. Other failures stop.
See [publication and missing-tag recovery](../publication.md); a new pipeline run
is not guaranteed to recover a lost local signed tag automatically.
