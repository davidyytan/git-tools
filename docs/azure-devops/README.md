# Azure DevOps Git Flow

Use Azure Repos for branches and pull requests, and Azure Pipelines for signed
version commits and tags. All four policies use the same git-tools versioning
engine; the two Azure adapters select its `classic` or `variant` strategy.

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
