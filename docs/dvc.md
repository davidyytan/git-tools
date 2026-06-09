# DVC Workflow Guide

This guide describes a neutral DVC workflow for repos that use Git, PRs, and optional DVC experiments.

## Mental Model

Git stores small, reviewable project state:

```text
source code
configs
dependency files
dvc.yaml
params.yaml
*.dvc pointer files
docs
```

DVC manages large or generated state:

```text
data contents
cache objects
pipeline dependency hashes
experiment refs
metrics from runs
```

Typical split:

```text
Git                 = code + config + DVC pointers
DVC                 = large data/cache + experiment metadata
<data-path>/        = actual data, usually not committed to Git
<artifact-path>/    = generated outputs, usually not committed to Git
<metrics-file>.json = compact metrics for comparison
dvc.lock            = resolved pipeline state
```

## Initialize DVC

```bash
uv add dvc
uv run dvc init
```

Commit DVC repo setup:

```bash
git add .dvc/config .dvcignore
git-tools commit
```

Use a Conventional Commit subject such as `chore: initialize DVC`.

## Add Data

Track data with DVC:

```bash
uv run dvc add <data-path>
```

Commit the DVC pointer file and Git ignore file created by DVC:

```bash
git add <data-path>.dvc
git add <data-parent>/.gitignore
git-tools commit
```

Use a Conventional Commit subject such as `chore: track data with DVC`.

The real data is not committed to Git. The `.dvc` file records the expected data version.

## Without A DVC Remote

A DVC remote is not required at the start.

Without a remote:

```text
dvc status works locally
dvc repro works locally
dvc exp run works locally
dvc push/pull do not share data
```

To share manually, copy the real data directory by thumb drive or other storage into the same path:

```text
<data-path>/
```

Then verify:

```bash
uv run dvc status
uv run dvc repro --dry
```

## Add A Remote Later

When shared storage is needed:

```bash
uv run dvc remote add -d storage <remote-url>
git add .dvc/config
git-tools commit
```

Use a Conventional Commit subject such as `chore: configure DVC remote`.

Commit the remote name and URL.

Do not commit credentials. Put credentials in local config or CI secrets:

```bash
uv run dvc remote modify --local storage <key> <value>
```

After a remote exists:

```bash
uv run dvc push
uv run dvc pull
```

`dvc push` uploads DVC cache/data. It does not create Git commits.

## Update Data

When tracked data changes:

```bash
uv run dvc status
uv run dvc add <data-path>
```

Commit updated pointer files:

```bash
git add <data-path>.dvc
git-tools commit
```

Use a Conventional Commit subject such as `chore: update DVC data pointer`.

If a remote exists:

```bash
uv run dvc push
```

## Pipeline Setup

Use `dvc.yaml` for reproducible commands.

Generic example:

```yaml
stages:
  <stage-name>:
    cmd: <command>
    deps:
      - <dependency-path>
    params:
      - <param-key>
    metrics:
      - <metrics-file>:
          cache: false
```

Use `params.yaml` for values you want to sweep or review:

```yaml
<group>:
  <param-key>: <value>
```

Commit pipeline config:

```bash
git add dvc.yaml params.yaml <source-files>
git-tools commit
```

Use a Conventional Commit subject such as `feat: add DVC pipeline`.

## Metrics Policy

Use metrics for small comparison values:

```text
loss
accuracy
score
duration
count
quality metric
best iteration
```

Do not use metrics for bulky artifacts:

```text
large reports
images
plots
model files
prediction dumps
debug output
```

A metrics file should be compact and stable:

```text
<metrics-file>.json
```

During normal experiment work, leave generated metrics uncommitted unless creating an official baseline.

## dvc.lock Policy

Do not add `dvc.lock` to `.gitignore`.

Two valid policies exist:

```text
baseline workflow     commit dvc.lock intentionally
experiment workflow   leave dvc.lock uncommitted after runs
```

For experiment-heavy work, use:

```text
dvc.lock              leave uncommitted
<metrics-file>.json   leave uncommitted
```

Commit them only when the repo intentionally wants a baseline run recorded in Git.

## Run Experiments

Run a named experiment:

```bash
uv run dvc exp run -f --name "<name>-$(date +%Y%m%d-%H%M%S)"
```

Override params:

```bash
uv run dvc exp run -f \
  --name "<name>-$(date +%Y%m%d-%H%M%S)" \
  -S <param-key>=<value>
```

Compare:

```bash
uv run dvc exp show
uv run dvc exp diff
```

Delete:

```bash
uv run dvc exp list --all
uv run dvc exp remove <experiment-name-or-hash>
uv run dvc exp remove --all-commits
uv run dvc exp clean
```

## Reproduce Runs

Reproduction has three pieces:

```text
Git commit       = code, config, params, and DVC pointers
DVC data/cache   = actual data and cached artifacts
DVC experiment   = optional params/metrics/lock state for a trial
```

For a committed baseline run, start from the Git commit:

```bash
git checkout <commit-or-branch>
uv run dvc pull
uv run dvc repro
```

If no DVC remote exists, replace `dvc pull` by manually copying the real data into the expected path, then verify:

```bash
uv run dvc status
uv run dvc repro --dry
uv run dvc repro
```

For a DVC experiment, the runner should share the experiment ref:

```bash
uv run dvc exp show
uv run dvc exp push origin <experiment-name-or-hash>
```

If `origin` is GitHub, this pushes the DVC experiment Git ref to GitHub. It does not push raw data bytes.

If a DVC remote exists, also upload the data/cache needed to reproduce:

```bash
uv run dvc push
```

The reviewer or teammate can then fetch and apply the experiment:

```bash
git fetch origin --all --tags
git checkout develop
git pull origin develop
uv run dvc exp pull origin <experiment-name-or-hash>
uv run dvc exp apply <experiment-name-or-hash>
```

To pull every experiment ref from GitHub:

```bash
git fetch origin --all --tags
uv run dvc exp pull origin --all-commits
uv run dvc exp show -A
```

After applying, reproduce or inspect:

```bash
uv run dvc status
uv run dvc repro --dry
uv run dvc exp show
```

GitHub `origin` stores Git commits and DVC experiment refs. A DVC remote stores actual data/cache. If no DVC remote exists, the teammate also needs the real data copied manually.

To rerun an old experiment, apply it to the workspace, then run the pipeline again:

```bash
uv run dvc exp apply <experiment-name-or-hash>
uv run dvc repro -f
```

To keep the rerun as a new experiment instead of only refreshing workspace files:

```bash
uv run dvc exp apply <experiment-name-or-hash>
uv run dvc exp run -f --name "<new-name>-$(date +%Y%m%d-%H%M%S)"
```

If the old experiment is not available locally, pull it first:

```bash
uv run dvc exp pull origin <experiment-name-or-hash>
```

## Git Flow

Use Git branches for code, config, and data-pointer changes.

Use DVC experiments for runs.

Recommended pattern:

```bash
git checkout develop
git pull origin develop
git checkout -b feature/<name>
```

Commit reviewable changes:

```bash
git add dvc.yaml params.yaml *.dvc <source-files>
git-tools commit
```

Use a Conventional Commit subject that describes the reviewed change.

Open the PR into `develop`.

After merge, run important experiments from `develop`:

```bash
git checkout develop
git pull origin develop
uv run dvc exp run -f --name "<official-name>-$(date +%Y%m%d-%H%M%S)"
```

Feature branches are fine for smoke runs. Shared/official comparisons should usually be rerun from `develop`.

## Git-Tools Integration

Use normal PR generation:

```bash
git-tools pr --base develop
```

Keep DVC experiment refs out of normal branch history.

DVC experiment refs may appear as commits like:

```text
dvc: commit experiment ...
```

Treat those as experiment refs, not normal feature commits. Do not merge them into `develop`.

Only promote an experiment intentionally:

```bash
uv run dvc exp branch <experiment-name-or-hash>
```

## Commit Checklist

Commit:

```text
.dvc/config
.dvcignore
*.dvc
.gitignore files created by DVC
dvc.yaml
params.yaml
source files
dependency files
docs
```

Do not normally commit:

```text
real data directories
generated artifact directories
generated metrics files
dvc.lock
```

Exception: commit `dvc.lock` and metrics only for an intentional baseline.

## Quick Commands

```bash
git status --short --branch

uv run dvc doctor
uv run dvc status
uv run dvc repro --dry
uv run dvc dag

uv run dvc exp run -f --name "<name>-$(date +%Y%m%d-%H%M%S)"
uv run dvc exp show
uv run dvc exp diff
uv run dvc exp list --all
uv run dvc exp push origin <experiment-name-or-hash>
uv run dvc exp pull origin <experiment-name-or-hash>
uv run dvc exp apply <experiment-name-or-hash>

uv run dvc remote list
uv run dvc push
uv run dvc pull
```
