# Classic: a fresh-repository walkthrough

[GitHub guides](README.md) · [Platform setup](setup.md) · [Mode reference](classic.md) · [CLI reference](../usage.md)

This is one continuous journey for a new `greeting-demo` repository, not a script to paste wholesale. Stop at each editing, GitHub, and CI checkpoint. Replace `<owner>` and local checkout paths. We build a tiny Python module without a package manifest, so `.cz.toml` is the only version file. In a packaged application, also reconcile the managed version fields in manifests and lockfiles; do not discard unrelated dependency changes.

The expected versions assume the exact subjects, serialized merges, default `semver2` configuration, and no extra version-producing pushes. Tags below are bare versions (`0.2.0-rc.0`, not `v0.2.0-rc.0`). This walkthrough is derived from the engine and local tests; it does not claim a live GitHub deployment was exercised.

Features, promotions, and backmerges use hosted PRs; release/hotfix stabilization and source synchronization use permitted direct human pushes. Use **Squash and merge** for the hosted PRs here, with final subjects equal to their stated titles. The mode also permits PR-title merge commits, but do not switch styles mid-example or use rebase completion.

## 1. Install the CLI and prepare GitHub before the first push

Install Git, Python **3.12**, and [uv](https://docs.astral.sh/uv/getting-started/installation/). Configure your Git author identity and authenticate Git/SSH to GitHub. Clone the tool into a separate directory, not inside the application:

```bash
git clone https://github.com/davidyytan/git-tools.git ../git-tools
cd ../git-tools
./install.sh
```
Restart your shell; if necessary run `uv tool update-shell` and restart again. Run `git-tools --help`, then `git-tools settings` and choose a provider, credentials, and model for local text generation. Prefer the masked credential prompt. CI versioning needs no LLM key. See [configuration](../configuration.md) for provider details.

In GitHub create an **empty** repository named `greeting-demo`: no generated README, license, or `.gitignore`. Before pushing the seed, follow [platform setup](setup.md) in this order:

1. Follow [Prepare keys and set the exact secrets](setup.md#prepare-keys-and-set-the-exact-secrets): list/select the GPG key, export `privatekey.pgp`, read the SSH private key, register public keys, and copy private contents to the named Actions secrets. The runbook supplies commands, descriptive placeholders, and the exact variable-to-settings mapping.
2. Store `BOT_SSH_SECRETKEY` and `BOT_GPG_SECRETKEY` as Actions secrets. Never place private keys in the application checkout.
3. Check bot identity, SSH write permissions, signed-commit/tag policy, and narrowly scoped ruleset exceptions. `GITHUB_TOKEN` permission alone does not authorize the workflow's SSH push.
4. Copy **only** `version-bump-git-flow-classic.yml.example` from the tool's `.github/workflows/` into the application's `.github/workflows/version-bump-git-flow-classic.yml`. Configure `GIT_TOOLS_REPO`, `GIT_TOOLS_REF`, `GIT_BOT_NAME`, and `GIT_BOT_EMAIL`. Pick an engine branch/tag known to contain the documented behavior; prefer a maintained pinned tag. The example clone accepts a branch/tag, not an arbitrary SHA. Installing a newer local CLI does not change the engine clone used by CI.
5. Configure squash messages to use PR titles, disable rebase merging, and configure a separate test workflow/check for PR validation. The version workflow is a mutating push workflow, not a PR test. Require the intended reviews/checks, with a planned one-time seed exception before final branch protection is enabled.

Keep exactly one version adapter active. Use full history and tags, serialize version-producing operations, and wait for successful publication after **every** push/merge below. A bot-generated bump can trigger another run that skips; wait until publication is complete. On failure, stop and inspect [publication/recovery](../publication.md), not force-push or repeat bootstrap.

## 2. Seed master at the required baseline and publish 0.1.0

From the tool checkout run `cd ..` to return to its parent, then create the separate application directory:

```bash
mkdir greeting-demo
cd greeting-demo
git init -b master
git remote add origin git@github.com:<owner>/greeting-demo.git
git-tools init --version 0.0.1 --tag-format '$version'
mkdir -p .github/workflows
```
Now copy/configure the adapter from step 1 into `.github/workflows/version-bump-git-flow-classic.yml`. Create `README.md` containing `# Greeting demo` and `.gitignore` containing `__pycache__/`. Inspect `.cz.toml`: its version must be `0.0.1`, not `0.1.0`. Do not manually create a bootstrap tag. If adding a package manifest, its starting version must also be `0.0.1`.

```bash
git add README.md .gitignore .cz.toml .github/workflows
git diff --cached
git commit -m "Release 0.1.0"
git push -u origin master
```
**Transition:** local seed → remote `master`, subject `Release 0.1.0`; no PR for this explicitly authorized fresh-repository seed. Set GitHub's default branch to `master` once it exists. Wait for Actions: it must commit stable **`0.1.0`** and publish tag **`0.1.0`**. Then bring that bot commit and tags home:

```bash
git switch master
git pull --ff-only origin master
git fetch origin --tags
git show HEAD:.cz.toml
git tag --list '0.1.0'
git switch -c develop
git push -u origin develop
```
**Transition:** `master` → new `develop`, no PR/title and no new content. Wait for its workflow; the generated bump subject should skip. Both branches remain **`0.1.0`**, with **no new tag**. Enable the planned steady-state protections now, retaining only the bot exception and approved ref-creation procedure.

For every subsequent local branch start, pull with `--ff-only` and fetch tags as shown. A failed fast-forward is a stop-and-inspect signal, not a reason to reset away work. Do not edit version fields on ordinary feature branches or run local mutating bumps alongside CI.

## 3. Deliver the first real feature through a hosted PR

```bash
git switch develop
git pull --ff-only origin develop
git fetch origin --tags
git switch -c feature/greeting
```
Create `greeting.py` with this actual implementation:

```python
def greet(name):
    return f"Hello, {name}!"
```

Create `tests/test_greeting.py` (create `tests/` first):

```python
import unittest
from greeting import greet


class GreetingTests(unittest.TestCase):
    def test_named_greeting(self):
        self.assertEqual(greet("Ada"), "Hello, Ada!")
```

```bash
python -m unittest discover -s tests
git add greeting.py tests/test_greeting.py
git diff --cached
git commit -m "feat: add named greeting"
git push -u origin feature/greeting
```
Wait for the feature-branch workflow: version stays **`0.1.0`**, **no tag** (feature branches skip publication). Refresh refs before generating PR text:

```bash
git fetch origin --tags
git-tools pr --base develop --start-pr --workflow-version 0.2.0
```
In GitHub, create **`feature/greeting` → `develop`**, title **`Start 0.2.0`**. The body describes the real greeting feature; the fixed title opens the selected classic line. Request review, wait for PR checks, then squash-merge with final subject `Start 0.2.0`.

The CLI only generates text: it neither creates nor merges the hosted PR. Inspect/paste its body and enforce the exact title/final subject in GitHub. Wait for develop's post-merge Actions run: expect **`0.2.0-alpha.0`**, tag **`0.2.0-alpha.0`**.

```bash
git switch develop
git pull --ff-only origin develop
git fetch origin --tags
```
You may use `git-tools commit` instead of the deterministic `git commit -m` examples, but it creates a commit by default. For a preview use `git-tools commit --no-commit`; inspect the result and preserve the stated Conventional Commit subject and hosted PR title if reproducing this version timeline.

## 4. Land another real change on the same alpha line

```bash
git switch -c bugfix/trim-name
```
Edit `greet` to return `f"Hello, {name.strip()}!"`. Add a test asserting that `greet(" Ada ")` equals `"Hello, Ada!"`; retain the original test. Then:

```bash
python -m unittest discover -s tests
git add greeting.py tests/test_greeting.py
git diff --cached
git commit -m "fix: trim greeting names"
git push -u origin bugfix/trim-name
git fetch origin --tags
git-tools pr --base develop
```
Wait for the source workflow: still **`0.2.0-alpha.0`**, **no tag**. In GitHub create **`bugfix/trim-name` → `develop`**, title **`fix: trim greeting names`**. Review, pass checks, squash-merge with that subject, then wait for develop CI: **`0.2.0-alpha.1`**, tag **`0.2.0-alpha.1`**.

```bash
git switch develop
git pull --ff-only origin develop
git fetch origin --tags
```
## 5. Cut 0.2.0, then move develop to 0.3.0

```bash
git switch -c release/0.2.0
git push -u origin release/0.2.0
```
**Transition:** `develop` at `0.2.0-alpha.1` → new `release/0.2.0`; no PR/title and no new human commit. Wait for the workflow: it should skip (there is no unique human stabilization commit), leaving **`0.2.0-alpha.1`**, **no new tag**. Merely naming/creating the branch does not open RC.

Classic has already selected `0.2.0` on develop, so the release branch must match that prerelease line. The next develop PR must open a forward cycle, rather than continue producing `0.2.0-alpha.N` while release stabilizes it.

```bash
git switch develop
git pull --ff-only origin develop
git fetch origin --tags
git switch -c feature/farewell
```
Add a real new function to `greeting.py`:

```python
def farewell(name):
    return f"Goodbye, {name}!"
```

Import `farewell` in the test file and add a test asserting `farewell("Ada") == "Goodbye, Ada!"`. This work belongs to the next cycle, not release 0.2.0.

```bash
python -m unittest discover -s tests
git add greeting.py tests/test_greeting.py
git diff --cached
git commit -m "feat: add farewell greeting"
git push -u origin feature/farewell
git fetch origin --tags
git-tools pr --base develop --start-pr --workflow-version 0.3.0
```
Wait for the source workflow: **`0.2.0-alpha.1`**, **no new tag**. In GitHub create **`feature/farewell` → `develop`**, title **`Start 0.3.0`**, with a body describing farewell. Review, pass checks, and squash-merge with final subject `Start 0.3.0`. Wait for CI: develop becomes **`0.3.0-alpha.0`**, tag **`0.3.0-alpha.0`**. Release is still on `0.2.0-alpha.1`.

```bash
git switch develop
git pull --ff-only origin develop
git fetch origin --tags
```
## 6. Open RC with a real stabilization fix

```bash
git switch release/0.2.0
git pull --ff-only origin release/0.2.0
git fetch origin --tags
```
On this release line, change `greet` to:

```python
def greet(name):
    cleaned = name.strip()
    return f"Hello, {cleaned or 'friend'}!"
```

Add a test asserting `greet("   ") == "Hello, friend!"`; keep the previous tests. The farewell function/test should **not** yet be on this release branch.

```bash
python -m unittest discover -s tests
git add greeting.py tests/test_greeting.py
git diff --cached
git commit -m "fix: greet blank names as friend"
```

```bash
git push origin release/0.2.0
```
**Transition:** direct stabilization commit on `release/0.2.0`, subject `fix: greet blank names as friend`; no hosted inner PR in this mode. Wait for the release-branch workflow. Expect **`0.2.0-rc.0`**, tag **`0.2.0-rc.0`**. This is alpha → RC on the same release line, not a patch release.

```bash
git switch release/0.2.0
git pull --ff-only origin release/0.2.0
git fetch origin --tags
```
## 7. Make a second stabilization change and verify the promotion boundary
Create `RELEASE_NOTES.md` with a `# 0.2.0` heading and accurate bullets for named greetings, trimming, and the blank-name fallback. Do not list farewell; it is next-cycle work. This real reviewable documentation diff gives a second RC checkpoint.

```bash
git add RELEASE_NOTES.md
git diff --cached
git commit -m "docs: describe greeting release"
```

```bash
git push origin release/0.2.0
```
**Transition:** direct `release/0.2.0` commit, subject `docs: describe greeting release`. Wait for release CI. Expect **`0.2.0-rc.1`**, tag **`0.2.0-rc.1`**. A Conventional Commit such as `docs:` is bump-eligible for RC continuation even though it does not normally select a semantic increment by itself.

```bash
git switch release/0.2.0
git pull --ff-only origin release/0.2.0
git fetch origin --tags
git fetch origin master
git merge-base --is-ancestor origin/master HEAD
python -m unittest discover -s tests
```
The ancestry command must succeed in this serialized story: master is still stable `0.1.0`, already contained in the release's history. Do **not** merge develop/farewell into the release before promotion. A promotion must include current stable master state as well as the RC, not just have an attractive PR title.

If the ancestry check fails because master advanced, stop this timeline and synchronize master into the candidate, keeping the candidate's intended RC version fields and all stable fixes. Resolve code/test conflicts and re-test before promotion. In this direct mode, use a synchronization merge subject `chore: merge master for release`, push the release branch, wait for CI, and pull/fetch the resulting RC. An extra eligible synchronization commit normally advances RC; re-check its actual version rather than insisting on `rc.1`.

## 8. Promote the release through GitHub, then wait for stable publication

```bash
git fetch origin --tags
git-tools pr --base master --release-pr
```
In GitHub create **`release/0.2.0` → `master`**, title **`Release 0.2.0`**. Inspect the diff: it contains the greeting and stabilization work, not farewell; `.cz.toml` carries **`0.2.0-rc.1`** in this uninterrupted example. Obtain review and green PR checks, squash-merge with final subject `Release 0.2.0`, and **retain the source branch** (disable automatic deletion or explicitly keep it).

Wait for master's post-merge version job: stable **`0.2.0`**, tag **`0.2.0`**. Creating or approving the PR alone does not publish stable.

```bash
git switch master
git pull --ff-only origin master
git fetch origin --tags
git show HEAD:.cz.toml
git tag --list '0.2.0'
```
## 9. Synchronize the retained release source for backmerge

Only after stable `0.2.0` is published, integrate current develop into the retained release source. This direction is **backmerge preparation**, not another promotion. It carries farewell into the source only after release publication. Keep develop's version state `0.3.0-alpha.0` when resolving `.cz.toml`; preserve the blank-name fix, notes, and all tests when resolving code. This produces a real diff, not an empty "open release" PR.

```bash
git switch release/0.2.0
git pull --ff-only origin release/0.2.0
git fetch origin --tags
git fetch origin develop
```

```bash
git merge --no-ff --no-commit origin/develop
```
If Git reports conflicts, resolve them before continuing. For this manifest-free example, take the known develop version config while retaining all actual application changes:

```bash
git restore --source=origin/develop -- .cz.toml
# Resolve greeting.py/tests manually if needed: retain greet fixes AND farewell.
git add .cz.toml greeting.py tests/test_greeting.py RELEASE_NOTES.md
python -m unittest discover -s tests
git diff --cached
git commit -m "chore: merge develop for backmerge"
```

```bash
git push origin release/0.2.0
```
**Transition:** direct synchronization commit on `release/0.2.0`, exact subject `chore: merge develop for backmerge`. Wait for its CI. The engine recognizes this exact preparation subject **before** ordinary release-line validation. It continues the copied alpha to **`0.3.0-alpha.1`**, **without a tag**. An arbitrary `chore:` title here is not interchangeable: classic would reject an alpha on the wrong release line. The source is now an integration carrier, not a candidate to promote to master again.

```bash
git switch release/0.2.0
git pull --ff-only origin release/0.2.0
git fetch origin --tags
```
## 10. Backmerge through a develop-based integration PR

Squash completion does not preserve source ancestry. A naive later PR from the retained source can show already-delivered changes, and squashing a bot's untagged prep version can also lose its history anchor. Use a temporary branch **based on current develop**, merge the retained release source locally, and preserve develop's current version fields. This keeps the final target diff and version decision deterministic without rewriting either protected branch. The essential safeguard is the proposed version, not the temporary branch name: before squash completion it must still match current develop (`0.3.0-alpha.0` here), whose tag remains available. After completion, develop's own CI creates a fresh untagged bump commit that subsequent runs retain in target history. Copying the source's untagged prep `alpha.1` into the squash commit instead loses that anchor and can fail even with `--yes`.

```bash
git switch develop
git pull --ff-only origin develop
git fetch origin --tags
git switch -c integration/backmerge-release-0.2.0
git fetch origin release/0.2.0
git merge --no-ff --no-commit origin/release/0.2.0
git restore --source=origin/develop -- .cz.toml
```
Resolve any remaining application/test conflicts: the final tree must include farewell, trimming, the blank-name fallback, and release notes. Stage every resolved path; do not replace an entire manifest merely to change its version in a packaged application.

```bash
git add .cz.toml greeting.py tests/test_greeting.py RELEASE_NOTES.md
python -m unittest discover -s tests
git diff --cached
git commit -m "chore: integrate released greeting fixes"
git push -u origin integration/backmerge-release-0.2.0
git fetch origin --tags
git diff origin/develop...HEAD
git-tools pr --base develop --backmerge-release-pr --workflow-version 0.2.0
```
**Source:** `integration/backmerge-release-0.2.0` (carrying retained `release/0.2.0`) → **target:** `develop`; **title:** `Backmerge Release 0.2.0`. The integration branch is outside the example adapter's push triggers: **no version/tag** there; it still runs applicable PR checks. `.cz.toml` in its proposed target tree remains `0.3.0-alpha.0` before completion.

Create that PR in GitHub, review the actual unique stabilization diff and passing tests, then squash-merge with final subject **`Backmerge Release 0.2.0`**. Wait for develop CI. The blank-name fix and notes are meaningful new content relative to develop's first-parent state, so expect **`0.3.0-alpha.1`**, **no tag**. This happens independently of the prep branch's untagged `alpha.1`.

```bash
git switch develop
git pull --ff-only origin develop
git fetch origin --tags
git show HEAD:.cz.toml
git tag --list '0.3.0-alpha.*'
```
At this point only `0.3.0-alpha.0` is tagged on that line. Version-only/no-op backmerges do **not** advance alpha; a develop line not yet ahead can instead catch up/finalize to the promoted stable version without a tag. Do not expect a new tag from either backmerge kind. Once the real fixes are confirmed on develop, the release source and temporary branches can be deleted; retain `hotfix/*` similarly until its own backmerge finishes. Do not repeatedly reuse a squash-promoted branch for later releases.


Before beginning the hotfix, publish a normal next-cycle checkpoint. This matters particularly for squash-only reviewed synchronization: copying an **untagged** develop version into a squash commit can drop the original bot history anchor. A tagged checkpoint avoids that problem without direct pushes or fabricated tags.

```bash
git switch -c feature/farewell-docs
```

Create `NEXT_CYCLE.md` documenting the actual farewell API and its planned 0.3.0 delivery. This is next-cycle documentation, not a modification to the published 0.2.0 release notes.

```bash
git add NEXT_CYCLE.md
git diff --cached
git commit -m "docs: document next-cycle farewell"
git push -u origin feature/farewell-docs
git fetch origin --tags
git-tools pr --base develop
```

The source workflow skips: still **`0.3.0-alpha.1`**, **no tag**. In GitHub create **`feature/farewell-docs` → `develop`**, title **`docs: document next-cycle farewell`**. Review the real documentation diff, pass checks, and squash-merge with that subject. Wait for develop CI: normal develop commits use a default patch increment, so this continues to **`0.3.0-alpha.2`**, tag **`0.3.0-alpha.2`**.

```bash
git switch develop
git pull --ff-only origin develop
git fetch origin --tags
```

Now the next synchronization can resolve its copied version against the published `0.3.0-alpha.2` tag even if a squash does not retain develop's bump commit. Do not manually tag the earlier no-tag backmerge state.

## 11. Start a hotfix from the published stable master

```bash
git switch master
git pull --ff-only origin master
git fetch origin --tags
git switch -c hotfix/missing-name
git push -u origin hotfix/missing-name
```
**Transition:** stable master `0.2.0` → new `hotfix/missing-name`, no PR/title and no new human content. Wait for the workflow: no unique hotfix commit yet, so **`0.2.0`**, **no new tag**. Fix the production error for `None` input. On this hotfix branch `greet` should become:

```python
def greet(name):
    cleaned = (name or "").strip()
    return f"Hello, {cleaned or 'friend'}!"
```

Add a regression test asserting `greet(None) == "Hello, friend!"`. Farewell is **not** on stable master yet and must not be introduced by this hotfix.

```bash
python -m unittest discover -s tests
git add greeting.py tests/test_greeting.py
git diff --cached
git commit -m "fix: handle missing greeting names"
```

```bash
git push origin hotfix/missing-name
```
**Transition:** direct commit on `hotfix/missing-name`, subject `fix: handle missing greeting names`. Wait for hotfix CI. Expect **`0.2.1-rc.0`**, tag **`0.2.1-rc.0`**. The hotfix selects the next patch from stable master, not from develop's `0.3.0` line.

```bash
git switch hotfix/missing-name
git pull --ff-only origin hotfix/missing-name
git fetch origin --tags
git fetch origin master
git merge-base --is-ancestor origin/master HEAD
python -m unittest discover -s tests
git-tools pr --base master --hotfix-pr
```
The master ancestry check succeeds in this serialized story: hotfix contains stable `0.2.0`. If master has advanced, stop and synchronize the new stable changes before promotion, keeping the intended patch RC and re-testing. Use a direct synchronization merge on the hotfix with subject `chore: merge master for hotfix`, push, wait CI, and pull/fetch. If master's next-patch target changed, reassess the target rather than forcing a stale version.

## 12. Promote the hotfix and wait for stable 0.2.1

In GitHub create **`hotfix/missing-name` → `master`**, title **`Hotfix 0.2.1`**. The proposed tree must carry `0.2.1-rc.0`, the missing-name fix and regression test, and current stable master state, but not farewell. Review, pass checks, and squash-merge with final subject `Hotfix 0.2.1`. **Keep the hotfix source branch.**

Wait for master CI: stable **`0.2.1`**, tag **`0.2.1`**.

```bash
git switch master
git pull --ff-only origin master
git fetch origin --tags
git show HEAD:.cz.toml
git tag --list '0.2.1'
```
## 13. Synchronize the retained hotfix source through the proper lane

Only after stable publication, integrate develop into the retained hotfix source. Develop is now the tagged `0.3.0-alpha.2` checkpoint. Keep that version config, retain the missing-name fix and all develop work, and never promote this combined source to master again.

```bash
git switch hotfix/missing-name
git pull --ff-only origin hotfix/missing-name
git fetch origin --tags
git fetch origin develop
```

```bash
git merge --no-ff --no-commit origin/develop
git restore --source=origin/develop -- .cz.toml
```
Resolve conflicts in code/tests by retaining both the `None` fallback and farewell. Stage all resolutions, then:

```bash
git add .cz.toml greeting.py tests/test_greeting.py RELEASE_NOTES.md
python -m unittest discover -s tests
git diff --cached
git commit -m "chore: merge develop for backmerge"
```

```bash
git push origin hotfix/missing-name
```
**Transition:** direct synchronization on `hotfix/missing-name`, exact subject `chore: merge develop for backmerge`. Wait for its version job. Expect the copied alpha to continue to **`0.3.0-alpha.3`**, **no tag**, via the special prep rule. This rule is important: normal hotfix validation would reject a `0.3.0` version against stable `0.2.1`.

```bash
git switch hotfix/missing-name
git pull --ff-only origin hotfix/missing-name
git fetch origin --tags
```
## 14. Backmerge the hotfix without downgrading develop

Again prepare a squash-safe integration branch from develop, keeping develop's pre-merge version `0.3.0-alpha.2` rather than copying the source's untagged prep version:

```bash
git switch develop
git pull --ff-only origin develop
git fetch origin --tags
git switch -c integration/backmerge-hotfix-0.2.1
git fetch origin hotfix/missing-name
git merge --no-ff --no-commit origin/hotfix/missing-name
git restore --source=origin/develop -- .cz.toml
```
Resolve any application/test conflicts, preserving the `None` regression fix and all next-cycle work. Stage all resolutions:

```bash
git add .cz.toml greeting.py tests/test_greeting.py RELEASE_NOTES.md
python -m unittest discover -s tests
git diff --cached
git commit -m "chore: integrate published missing-name fix"
git push -u origin integration/backmerge-hotfix-0.2.1
git fetch origin --tags
git diff origin/develop...HEAD
git-tools pr --base develop --backmerge-hotfix-pr --workflow-version 0.2.1
```
The explicit `--workflow-version 0.2.1` means the **already-promoted** hotfix, not master's next patch and not the source's synchronized alpha. The helper intentionally does not infer it.

In GitHub create **`integration/backmerge-hotfix-0.2.1` → `develop`** (carrying retained `hotfix/missing-name`), title **`Backmerge Hotfix 0.2.1`**. The integration source produces **no version/tag**. Inspect the target diff: it must contain the new missing-name fix, retain farewell, and propose `0.3.0-alpha.2` before CI. Review, pass checks, squash-merge with that final subject, and wait for develop CI: meaningful unique fixes yield **`0.3.0-alpha.3`**, **no tag**.

```bash
git switch develop
git pull --ff-only origin develop
git fetch origin --tags
python -m unittest discover -s tests
git show HEAD:.cz.toml
```
Verify the fix is present before deleting the hotfix and temporary integration branches. Backmerge titles must never be `Release 0.2.0` or `Hotfix 0.2.1` on develop: those titles are promotion-only and are rejected there. As with the release backmerge, no-op/version-only changes would skip rather than advance alpha.

## 15. Continue the next cycle from the recovered bot state

Develop is now on `0.3.0-alpha.3`; master is stable `0.2.1`. Make one more real fix:

```bash
git switch -c bugfix/trim-farewell
```
Edit `farewell` to return `f"Goodbye, {name.strip()}!"`. Add a test asserting `farewell(" Ada ") == "Goodbye, Ada!"`, retaining all greeting regression tests.

```bash
python -m unittest discover -s tests
git add greeting.py tests/test_greeting.py
git diff --cached
git commit -m "fix: trim farewell names"
git push -u origin bugfix/trim-farewell
git fetch origin --tags
git-tools pr --base develop
```
Wait for the bugfix source job: **no bump/tag**, still `0.3.0-alpha.3`. In GitHub create **`bugfix/trim-farewell` → `develop`**, title **`fix: trim farewell names`**; review, pass checks, and squash-merge with that subject. Wait for develop CI: **`0.3.0-alpha.4`**, tag **`0.3.0-alpha.4`**. The absence of `alpha.1`/`alpha.3` tags is intentional: those were no-tag backmerge states, with generated bump commits as history anchors.

```bash
git switch develop
git pull --ff-only origin develop
git fetch origin --tags
git switch -c release/0.3.0
git push -u origin release/0.3.0
```
**Transition:** current develop → next `release/0.3.0`; no PR/title, no unique human change yet, **no new tag**, still `0.3.0-alpha.4`. Wait for the skip job. You are now at the next release cut. Classic must keep this release on its selected `0.3.0` line. Repeat the same actual-work pattern: a real feature PR titled `Start 0.4.0` opens `0.4.0-alpha.0` on develop, while a real stabilization change on release opens `0.3.0-rc.0`. Use permitted direct stabilization commits just as above. Then promote, wait for stable, and backmerge before deleting the source.

## Why the expected results are conditional

The engine's behavior is covered by `tests/test_git_flow_strategy.py`, `tests/test_backmerge_content.py`, and `tests/test_hotfix_backmerge.py`; implementation is in `git_tools/generators/bumpgen/{strategy,rules,repo}.py`. Backmerge content is compared against the target commit's **first parent**, ignoring only actual managed version-field changes, not whole manifests or lockfiles. Different diffs, subjects, merge styles, extra CI-producing pushes, stale refs, or a different remote engine ref can legitimately change the result. Check `.cz.toml`, bot commits, remote refs, and tags at each checkpoint rather than manufacturing a missing tag or asserting that opening a PR performed a release.
