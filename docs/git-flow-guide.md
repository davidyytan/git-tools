# Git Flow Guide

This repository ships two workflow examples:

- `.github/workflows/version-bump-git-flow-variant.example.yml`
- `.github/workflows/version-bump-git-flow-classic.example.yml`

Use `variant` if you want the release branch to choose the final release version.

Use `classic` if you want `develop` to already represent the upcoming release line before you cut `release/<x.y.z>`.

## Shared Rules

`git-tools.bump` stays generic. The workflow decides branch policy.

By default, `.cz.toml` is the authoritative version source. `pyproject.toml`, `uv.lock`, and other managed version files are auxiliary sync targets and should not block a bump just because they drifted behind `.cz.toml`.

Shared branch roles:

| Branch | Purpose | Bump behavior |
| --- | --- | --- |
| `feature/**` | normal feature work from `develop` | no bump |
| `bugfix/**` | normal bugfix work from `develop` | no bump |
| `develop` | integration branch | `alpha` only |
| `release/**` | release branch | `rc` only |
| `hotfix/**` | production patch branch | patch `rc` only |
| `sync/**` | sync `master` back into `develop` | no bump |
| `master` | stable branch | finalize prerelease to stable |

Shared Conventional Commit mapping in the example workflows:

| Commit shape | Increment |
| --- | --- |
| `type!:` or `BREAKING CHANGE:` | `MAJOR` |
| `feat:` | `MINOR` |
| any other Conventional Commit header | `PATCH` |
| non-Conventional Commit message | no bump |

The examples intentionally pass `--default-increment PATCH` so normal merged PRs still produce referenceable builds on versioned branches.

Shared PR title policy:

| PR shape | Tool mode | Fixed title |
| --- | --- | --- |
| `feature/*` or `bugfix/* -> develop` | `git-tools pr` | no fixed title; use a Conventional Commit title |
| `release/* -> master` | `git-tools pr --release-pr` | `Release x.y.z` |
| `hotfix/* -> master` | `git-tools pr --hotfix-pr` | `Hotfix x.y.z` |
| `sync/* -> develop` | `git-tools pr --sync-pr` | `Sync x.y.z` |

Pull Request output should not include `## Related Issue` or `Issue: #...`.

## Repository Bootstrap

Start a new repository locally like this:

```bash
git init
git branch -M master
git-tools init
git add -A
git commit -m "Release 0.0.1"
```

That first commit establishes the untagged bootstrap baseline at `0.0.1`.

Then create the GitHub repository, add `origin`, and push `master` first:

```bash
git remote add origin git@github.com:<owner>/<repo>.git
git push -u origin master
```

Rename the initial branch to `master` before running `git-tools init`, so the first managed version is bootstrapped on the stable branch. Direct `git-tools init` seeds `.cz.toml` with `0.0.1` by default. You do not need to create a `0.0.1` tag manually. The first workflow run on `master` promotes that baseline to `0.1.0`.

Once the bootstrap bump lands on `master`, update local `master`, create `develop` from that bumped stable branch, and push it:

```bash
git checkout master
git pull origin master
git checkout -b develop
git push -u origin develop
```

From there, normal feature and bugfix work should start from `develop`.

## GitHub Setup

The workflow examples expect these repository secrets:

| Secret | Purpose |
| --- | --- |
| `BOT_SSH_SECRETKEY` | SSH private key used by Actions checkout and push steps |
| `BOT_GPG_SECRETKEY` | GPG private key used for signed bump commits and tags |

If you copy an example workflow into another repository, use the same secret names there so the workflow and docs stay aligned.

## Pull Request Merge Settings

For this flow, GitHub repository settings should prefer squash merges.

Recommended settings:

- enable `Squash merge`
- disable normal `Merge commit`
- disable `Rebase merge`
- in squash settings, use the Pull Request title and description as the default squash commit message

Why:

- feature and bugfix PRs into `develop` should squash to one Conventional Commit merge commit
- release, hotfix, and sync PRs should squash to one fixed-title merge commit
- this keeps target branch history clean and makes the PR title the visible branch-level event

## Variant Workflow

This is the recommended workflow if you want:

- `develop` to stay as the integration branch
- `release/<target>` to decide the final release version
- `master` to only finalize what the release branch already chose

### Version Authority

In the variant flow:

- `develop` creates integration builds like `0.1.1-alpha.0`
- `release/<target>` decides whether the next release is patch, minor, or major
- `master` finalizes that prerelease to stable

Example:

```text
master:         0.1.0
develop:        0.1.1-alpha.0
release/1.0.0:  1.0.0-rc.0
master:         1.0.0
```

Valid release targets are exactly the next legal semver step from `master`.

If `master = 0.1.0`, allowed release branches are:

- `release/0.1.1`
- `release/0.2.0`
- `release/1.0.0`

Rejected examples:

- `release/0.1.2`
- `release/1.0.1`
- `release/2.0.0`

### Day-to-Day Flow

#### 1. Feature or bugfix work into `develop`

Start from `develop`:

```bash
git checkout develop
git pull origin develop
git checkout -b feature/commitizen-title
```

or:

```bash
git checkout -b bugfix/empty-state
```

Make changes, then commit with `git-tools commit`:

```bash
git add -A
git-tools commit
git push origin feature/commitizen-title
git-tools pr --base develop
```

Keep the PR title in Conventional Commit form because these PRs are normally squash-merged into `develop`.

Good examples:

- `feat(cli): support release-pr mode`
- `fix(ui): handle empty state`
- `style: tighten prompt wording`

When the PR is merged into `develop`, the workflow creates or continues `alpha`.

Examples:

- `0.1.0` + `feat:` on `develop` -> `0.2.0-alpha.0`
- `0.1.0` + `fix:` on `develop` -> `0.1.1-alpha.0`
- `1.0.0-alpha.2` + `docs:` on `develop` -> `1.0.0-alpha.3`

#### 2. Normal release to `master`

When product or release QA decides the target version, cut `release/<target>` from `develop`.

Example:

```bash
git checkout develop
git pull origin develop
git checkout -b release/1.0.0
git push origin release/1.0.0
git-tools pr --base master --release-pr
```

What happens:

1. The workflow validates that `release/1.0.0` is a legal next step from `master`.
2. The first eligible bump on `release/1.0.0` moves the branch to `1.0.0-rc.0`.
3. Later commits on that release branch keep the same line and only advance `rc.N`.
4. Merging the PR to `master` finalizes `1.0.0-rc.N -> 1.0.0`.

Release PR title:

```text
Release 1.0.0
```

#### 3. Hotfix to `master`

Hotfixes start from `master`, not from `develop`.

```bash
git checkout master
git pull origin master
git checkout -b hotfix/session-timeout
```

Make the fix, then:

```bash
git add -A
git-tools commit
git push origin hotfix/session-timeout
git-tools pr --base master --hotfix-pr
```

What happens:

1. The first eligible hotfix bump creates the next patch `rc` line.
2. Later hotfix commits continue that patch `rc` line.
3. Merging the hotfix PR to `master` finalizes to stable.

Example:

```text
master:           1.0.0
hotfix/* branch:  1.0.1-rc.0
master after PR:  1.0.1
```

Hotfix PR title:

```text
Hotfix 1.0.1
```

#### 4. Sync `master` back into `develop`

After every release or hotfix, sync `master` back into `develop`.

Always use a dedicated sync branch:

```bash
git checkout develop
git pull origin develop
git checkout -b sync/back-to-develop
git merge origin/master
```

If there are conflicts, resolve them on `sync/back-to-develop`, not directly on `develop`.

Then finish the merge and open the PR:

```bash
git add -A
git commit -m "Sync 1.0.1"
git push origin sync/back-to-develop
git-tools pr --base develop --sync-pr
```

Sync PR title:

```text
Sync 1.0.1
```

`sync/**` never bumps a version. It only brings released history back into `develop`.

After the sync PR is merged, do not manually bump `develop`. The next normal PR merged into `develop` starts the next alpha line.

### Variant Workflow Summary

```text
feature/* or bugfix/* -> develop -> alpha
release/<target>      -> master  -> stable
hotfix/*              -> master  -> next patch stable
sync/*                -> develop -> no bump
```

ASCII example:

```text
master -------------------------------> 0.1.0
feature/* --squash--> develop -------> 0.1.1-alpha.0
more work ----------- develop -------> 0.1.1-alpha.1

cut release/1.0.0 from develop
release/1.0.0 -----------------------> 1.0.0-rc.0
release fixes -----------------------> 1.0.0-rc.1
release/1.0.0 ----PR-----------------> master --> 1.0.0

hotfix/session-timeout --------------> 1.0.1-rc.0
more hotfix work --------------------> 1.0.1-rc.1
hotfix/session-timeout ----PR--------> master --> 1.0.1

sync/back-to-develop --> merge origin/master
sync/back-to-develop ----PR----------> develop --> sync only, no bump
```

Use this workflow file:

```text
.github/workflows/version-bump-git-flow-variant.example.yml
```

## Classic Workflow

Use the classic workflow if you want textbook Git Flow behavior.

In the classic workflow:

- `develop` already represents the upcoming release line
- `release/<x.y.z>` must match that same line
- `master` only finalizes it

Example:

```text
develop:        1.0.0-alpha.2
release/1.0.0:  1.0.0-rc.0
master:         1.0.0
```

The important difference from the variant flow is the release decision point:

- classic: the release line is already decided on `develop`
- variant: the release line is decided by `release/<target>`

Classic release steps:

1. Merge work into `develop` until `develop` is already on the target alpha line.
2. Cut `release/<same-version>` from `develop`.
3. Let the workflow convert `alpha -> rc`.
4. Merge `release/<same-version> -> master`.
5. Sync `master` back into `develop` with `sync/* -> develop`.

Classic example:

```text
1.5.0 -> 1.6.0-alpha.0 on develop
release/1.6.0 -> 1.6.0-rc.0
release fixes -> 1.6.0-rc.1
master -> 1.6.0
sync/* -> develop
```

Use this workflow file:

```text
.github/workflows/version-bump-git-flow-classic.example.yml
```

## What To Remember

Variant workflow, which is the recommended one here:

- open feature work from `develop`
- open bugfix work from `develop`
- open release work from `release/<target>`
- open hotfix work from `master`
- open sync work from `develop` on `sync/*`
- use `git-tools commit` for normal feature and bugfix commits
- use fixed PR modes for release, hotfix, and sync PRs
- initial bootstrap commit should be `Release 0.0.1`
- the first workflow run on `master` turns that baseline into `0.1.0`

The most important branch names are:

- `feature/<name>`
- `bugfix/<name>`
- `release/<x.y.z>`
- `hotfix/<name>`
- `sync/back-to-develop`
