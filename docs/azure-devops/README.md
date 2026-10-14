# Azure DevOps Git Flow

Use Azure Repos for branches and pull requests, and Azure Pipelines for signed
version commits and tags. All four policies use the same git-tools versioning
engine; the two Azure adapters select its `classic` or `variant` strategy.

## How It Works at a Glance

```text
USER: push a branch / complete a PR in Azure Repos
                         |
                         v
AZURE: pipeline runs on the pushed target branch
                         |
                         v
Check out application repo + full history/tags
Clone git-tools from a supported branch/tag
                         |
                         v
SHARED ENGINE: inspect branch + commit subjects
               + .cz.toml + Git history/tags
                         |
                         v
                 Decide what to do
                  /      |       \
                 v       v        v
               SKIP    INVALID   BUMP
                |        |        |
                v        v        v
              Finish   Fail     Import GPG key
                                Update version files
                                Create signed commit/tag
                                      |
                                      v
                        Push back as project Build Service
                                      |
                                      v
USER: wait for CI, then pull the version commit
```

Completing a PR pushes its merge result to the target branch; that push triggers
versioning. The pipeline also evaluates included source-branch pushes, but the
engine can skip them. A version decision does not necessarily create a tag.
GitHub-hosted git-tools is only the engine source; your application stays in
Azure Repos. No LLM/API key is needed for the CI bump engine.

### What You Do vs What Automation Does

```text
ONE-TIME USER / ADMIN SETUP
Choose ONE flow adapter -> copy .example as .yml -> configure engine ref
        -> configure project-scoped authorization -> prepare signing key
        -> bootstrap and push master -> create pipeline -> upload/authorize key
        -> grant Build Service repo permissions -> run bootstrap CI
        -> create develop from bumped master

DAILY DEVELOPER WORK                 AUTOMATION
Checkout -> edit -> stage
        -> git-tools commit
        -> push / open Azure PR
        -> review and complete PR -----> inspect target-branch state
                                        -> skip / reject / bump
                                        -> publish version commit/tag
Wait for CI -> pull <------------------ successful publication
```

Local `git-tools pr` generates text; **you** paste it into Azure Repos and select
the source, target, reviewers, and completion method. It does not submit or merge
the PR. Use [setup](setup.md) for the exact configuration order and permissions.

**Activation checks:** decision text now travels through environment variables,
not Bash source, and diagnostic logs escape embedded newlines. Publication probes
atomic support and falls back only when unsupported; see
[publication and recovery](../publication.md). Validate both behaviors in a test
repo. This diagram describes the logical flow, not Secure File acquisition timing
or a production-security guarantee. Restrict who can edit/execute credentialed YAML.

## Choose a flow

| Flow | Release-line decision | Stabilization changes | Engine flow | Guide |
| --- | --- | --- | --- | --- |
| Classic | `develop` chooses; after a release cut, the next cycle starts with `Start A.B.C` | Direct commits on release/hotfix branches | `classic` | [Classic](classic.md) |
| Classic — Reviewed | Same as classic | Inner PRs into release/hotfix branches | `classic` | [Classic — Reviewed](classic-reviewed.md) |
| Release-led | `release/X.Y.Z` chooses; no mandatory Start PR after the cut | Direct commits on release/hotfix branches | `variant` | [Release-led](release-led.md) |
| Release-led — Reviewed | Same as release-led | Squash inner PRs into release/hotfix branches | `variant` | [Release-led — Reviewed](release-led-reviewed.md) |

Reviewed is a review-policy layer, not another engine strategy or adapter.
Use it when every stabilization fix needs a review trail. Classic reviewed
supports squash or merge commits; release-led reviewed uses a strict squash
profile. All profiles prohibit rebase completion for these automated flows.

## Start here

1. Follow [Azure DevOps setup](setup.md): configure a supported engine ref,
   project-scoped job authorization, a signing Secure File, and the repository's
   Build Service permissions.
2. Copy **one** adapter from git-tools into the target Azure repository,
   removing `.example`:

   | Flow (including reviewed) | Source template | Active destination |
   | --- | --- | --- |
   | Classic | [classic example](../../.azure/workflows/version-bump-git-flow-classic.yml.example) | `.azure/workflows/version-bump-git-flow-classic.yml` |
   | Release-led | [release-led example](../../.azure/workflows/version-bump-git-flow-variant-release-led.yml.example) | `.azure/workflows/version-bump-git-flow-variant-release-led.yml` |

3. Push the bootstrap `master`, create and authorize its Azure pipeline, and
   manually run it. Only create `develop` after the stable bootstrap bump.
   The first push does not retroactively trigger a newly created pipeline.
4. Follow the selected procedure above for feature PRs, release stabilization,
   promotion, hotfixes, and backmerges.

Never activate both adapters on the same repository and branches. A reviewed
flow uses its base adapter, not a second competing versioning pipeline.

## Local commands and interactive navigation

See [CLI usage](../usage.md) for installation, provider setup, direct commands,
actual interactive menus, and generation options. Run `git-tools` in a terminal
and choose `init`, `commit`, or `pr` from **Select command:** as the interactive
alternative to those direct subcommands. The flow guides specify the same
branches, fixed titles, and versions for either entry point.

PR generation is local: paste the generated title/description into Azure Repos
and choose the documented target. It does not create or complete a PR through
the Azure API. [Setup](setup.md#local-cli-and-pr-descriptions) explains Azure
remote detection, `--azure-limit` / `--no-azure-limit`, and the 4,000 UTF-16-unit
PR-description limit.

## Commit subjects are part of the protocol

Use the exact final target-branch subjects:

- `Start X.Y.Z` → `develop` opens tagged `X.Y.Z-alpha.0`.
- `Release X.Y.Z` → `master` promotes a release.
- `Hotfix X.Y.Z` → `master` promotes a patch.
- `Backmerge Release X.Y.Z` → `develop` carries release fixes back.
- `Backmerge Hotfix X.Y.Z` → `develop` carries patch fixes back.

Ordinary feature, bugfix, release-fix, and hotfix-fix PRs use Conventional Commit
subjects. The supported engine normalizes Azure's optional `Merged PR <id>:`
prefix; the remaining subject must still match the protocol. Configure
[Azure merge settings](setup.md#merge-settings) and inspect completion messages.
