# Classic — Reviewed: complete GitHub guide

[GitHub guides](README.md) · [Platform setup](setup.md) · [CLI reference](../usage.md)

## Already have keys? Copy these into CI

**Destination: your application repository → Settings → Secrets and variables → Actions → New repository secret.** Select your own dedicated automation key, not a personal key. Run one command at a time; replace `YOUR_GPG_KEY_ID` with its full fingerprint (preferred) or long key ID after listing, and replace the SSH filename before reading it:

```bash
gpg --list-secret-keys --keyid-format=long
# Actions secret BOT_GPG_SECRETKEY: paste the complete private-key block printed next.
gpg --export-secret-key -a YOUR_GPG_KEY_ID
# Actions secret BOT_SSH_SECRETKEY: paste the complete SSH private key printed next.
cat "$HOME/.ssh/YOUR_AUTOMATION_SSH_KEY"
```

Paste each complete BEGIN/END block into its named secret from a private, unrecorded local terminal. Do not save an extra export file or expose output in chat/logs/source. Keep existing public-key registration/write access if already correct; [register public keys only if needed](setup.md#register-public-keys-only-if-needed). Missing a key? Follow the [optional creation steps](setup.md#prepare-keys-and-set-the-exact-secrets), then return to this block. These workflows have no GPG/SSH passphrase configured; protected keys need an approved adaptation.

**Entering an existing project?** Configure [the workflow](setup.md#copy-and-configure-the-workflow), preserve its version/history, and resume at the applicable release checkpoint below. **Do not repeat fresh-repository bootstrap.**

## Fresh-repository journey

Follow this journey in a new **`greeting-demo` repository under your own GitHub account or organization**. Stop at each editing, GitHub, and CI checkpoint; this is not a paste-all script.

- **Local layout:** `$HOME/projects/git-tools` holds the retained tool checkout; `$HOME/projects/greeting-demo` holds your application. If you choose another parent, use that location consistently.
- **Example application:** a tiny Python module without a package manifest, so `.cz.toml` is its only version file. In a packaged application, reconcile managed manifest/lockfile versions without discarding unrelated changes.
- **Expected results:** exact subjects, serialized merges, default `semver2`, and bare-version tags (`0.2.0-rc.0`, not `v0.2.0-rc.0`). Extra version-producing pushes change the timeline. Results are derived from the engine/local tests, not a live GitHub deployment.

All human changes after the one-time repository seed go through hosted PRs, including release/hotfix stabilization and synchronization. Protect `master`, `develop`, `release/*`, and `hotfix/*`; narrowly authorize the version bot's signed pushes. New protected release/hotfix refs may need an approved branch-creation process: creating a ref at an already-reviewed commit is not permission to push new human commits. Use **Squash and merge** for every PR in this walkthrough, with the final subject equal to its stated title. Never create an empty inner PR.

## 1. Install the CLI and prepare GitHub before the first push

Install Git, Python **3.12**, [uv](https://docs.astral.sh/uv/getting-started/installation/), and GnuPG. Authenticate your local Git/SSH connection to GitHub. From outside any existing repository:

```bash
mkdir -p "$HOME/projects"
cd "$HOME/projects"
git clone https://github.com/davidyytan/git-tools.git
cd git-tools
./install.sh
```

Already have the tool checkout? Go to it and rerun `./install.sh` instead of cloning again. **Keep the checkout:** installation is editable. The upstream URL above is the tool source, not your application origin.

Restart your shell, then run `git-tools --help`. If it is not on PATH, run `uv tool update-shell` and restart again; see [installation](../../README.md#install) for completion setup.

In **your own** GitHub account or organization, create an **empty** `greeting-demo` repository: no generated README, license, or `.gitignore`. The next section creates its local checkout and configures Actions before the first push.

**Optional generated prose:** the fixed `git commit -m` commands and CI need no LLM. If you use `git-tools commit` or `git-tools pr`, configure a provider/model with `git-tools settings` before the first use; prefer its masked credential prompt. See [configuration](../configuration.md).

**Working rule:** keep one version adapter, full history, and current tags. After each version-producing push/merge, wait for publication, pull the bot commit, and fetch tags. A follow-up bot run may skip. On failure, stop and use [recovery](../publication.md), not force-push or another bootstrap.

## 2. Seed master at the required baseline and publish 0.1.0

Return explicitly to your chosen parent after the shell restart. Replace `YOUR_NAME` / `YOUR_EMAIL` with **your human Git identity**, and `YOUR_USERNAME_OR_ORG` with the owner of your new GitHub repository. Keep the SSH user `git@` unchanged:

```bash
cd "$HOME/projects"
mkdir greeting-demo
cd greeting-demo
git init -b master
git config user.name 'YOUR_NAME'
git config user.email 'YOUR_EMAIL'
git remote add origin git@github.com:YOUR_USERNAME_OR_ORG/greeting-demo.git
git-tools init --version 0.0.1 --tag-format '$version'
mkdir -p .github/workflows
cp "$HOME/projects/git-tools/.github/workflows/version-bump-git-flow-classic.yml.example" .github/workflows/version-bump-git-flow-classic.yml
```

**Before the first push, complete [GitHub setup](setup.md):**

1. In the copied YAML `env:`, set `GIT_BOT_NAME` / `GIT_BOT_EMAIL` to **your dedicated automation identity**, not your human identity or David's. Keep the upstream `GIT_TOOLS_REPO`; choose a supported engine branch/tag in `GIT_TOOLS_REF` (not a bare SHA). Local installation does not change CI's engine clone.
2. Follow [key setup](setup.md#prepare-keys-and-set-the-exact-secrets): use an existing dedicated automation GPG key **or create one first**, print its private block and paste it into Actions secret **`BOT_GPG_SECRETKEY`**, and read the dedicated SSH private key into **`BOT_SSH_SECRETKEY`** using the copy block above. Register matching public keys separately **only if not already configured**. Do not save a private-key export file.
3. Use PR-title squash messages, disable rebase, and add separate read-only PR tests. Grant the SSH identity write access and narrow bot protection exceptions; `GITHUB_TOKEN` permission alone is insufficient. Plan the one-time seed exception before final protections.

Create `README.md` containing `# Greeting demo` and `.gitignore` containing `__pycache__/`. Confirm `.cz.toml` is **`0.0.1`**, not `0.1.0`; any managed package version must match. Do not create a bootstrap tag manually.

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

```bash
git switch -c release-fix/blank-name
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
git push -u origin release-fix/blank-name
git fetch origin --tags
git-tools pr --base release/0.2.0
```
The example version adapter does not run on `release-fix/*`; no version/tag is produced on this source (separate PR tests still run). In GitHub create **`release-fix/blank-name` → `release/0.2.0`**, title **`fix: greet blank names as friend`**. Review the implementation and regression test, wait for checks, and squash-merge with that Conventional Commit subject. Wait for the release-branch version job. Expect **`0.2.0-rc.0`**, tag **`0.2.0-rc.0`**. This is alpha → RC on the same release line, not a patch release.

```bash
git switch release/0.2.0
git pull --ff-only origin release/0.2.0
git fetch origin --tags
```
## 7. Make a second stabilization change and verify the promotion boundary

```bash
git switch -c release-fix/release-notes
```
Create `RELEASE_NOTES.md` with a `# 0.2.0` heading and accurate bullets for named greetings, trimming, and the blank-name fallback. Do not list farewell; it is next-cycle work. This real reviewable documentation diff gives a second RC checkpoint.

```bash
git add RELEASE_NOTES.md
git diff --cached
git commit -m "docs: describe greeting release"
```

```bash
git push -u origin release-fix/release-notes
git fetch origin --tags
git-tools pr --base release/0.2.0
```
In GitHub create **`release-fix/release-notes` → `release/0.2.0`**, title **`docs: describe greeting release`**. The source is outside the version adapter triggers: **no tag**. Review the notes, wait for checks, and squash-merge with that subject; wait for release CI. Expect **`0.2.0-rc.1`**, tag **`0.2.0-rc.1`**. A Conventional Commit such as `docs:` is bump-eligible for RC continuation even though it does not normally select a semantic increment by itself.

```bash
git switch release/0.2.0
git pull --ff-only origin release/0.2.0
git fetch origin --tags
git fetch origin master
git merge-base --is-ancestor origin/master HEAD
python -m unittest discover -s tests
```
The ancestry command must succeed in this serialized story: master is still stable `0.1.0`, already contained in the release's history. Do **not** merge develop/farewell into the release before promotion. A promotion must include current stable master state as well as the RC, not just have an attractive PR title.

If the ancestry check fails because master advanced, stop this timeline and synchronize master into the candidate, keeping the candidate's intended RC version fields and all stable fixes. Resolve code/test conflicts and re-test before promotion. In this reviewed mode, do that on a new `release-fix/sync-master` branch based on the release branch and open a real inner PR into `release/0.2.0`, titled `chore: merge master for release`; review and squash it, then wait for CI and pull/fetch the resulting RC. Never use a direct human push to the protected release branch or an empty PR. An extra eligible synchronization merge normally advances RC, so re-check the actual version instead of insisting on `rc.1`.

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
git switch -c release-fix/sync-develop
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
git push -u origin release-fix/sync-develop
git fetch origin --tags
git-tools pr --base release/0.2.0
```
In GitHub create **`release-fix/sync-develop` → `release/0.2.0`**, title **`chore: merge develop for backmerge`**. The source produces **no tag**. Review the actual farewell integration, version resolution, and retained stabilization fixes; pass checks and squash-merge with that exact subject. Wait for source-line CI. The engine recognizes this exact preparation subject **before** ordinary release-line validation. It continues the copied alpha to **`0.3.0-alpha.1`**, **without a tag**. An arbitrary `chore:` title here is not interchangeable: classic would reject an alpha on the wrong release line. The source is now an integration carrier, not a candidate to promote to master again.

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
**Transition:** stable master `0.2.0` → new `hotfix/missing-name`, no PR/title and no new human content. Wait for the workflow: no unique hotfix commit yet, so **`0.2.0`**, **no new tag**.

```bash
git switch -c hotfix-fix/missing-name
```
Fix the production error for `None` input. On this hotfix branch `greet` should become:

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
git push -u origin hotfix-fix/missing-name
git fetch origin --tags
git-tools pr --base hotfix/missing-name
```
In GitHub create **`hotfix-fix/missing-name` → `hotfix/missing-name`**, title **`fix: handle missing greeting names`**. No source version/tag is produced (`hotfix-fix/*` is outside adapter triggers). Review the implementation/test, pass checks, and squash-merge with that subject; wait for hotfix CI. Expect **`0.2.1-rc.0`**, tag **`0.2.1-rc.0`**. The hotfix selects the next patch from stable master, not from develop's `0.3.0` line.

```bash
git switch hotfix/missing-name
git pull --ff-only origin hotfix/missing-name
git fetch origin --tags
git fetch origin master
git merge-base --is-ancestor origin/master HEAD
python -m unittest discover -s tests
git-tools pr --base master --hotfix-pr
```
The master ancestry check succeeds in this serialized story: hotfix contains stable `0.2.0`. If master has advanced, stop and synchronize the new stable changes before promotion, keeping the intended patch RC and re-testing. Use a temporary `hotfix-fix/sync-master` branch based on hotfix, merge master there, and submit an actual inner PR into `hotfix/missing-name` titled `chore: merge master for hotfix`; review, squash-merge, wait CI, and pull/fetch. Never directly push human synchronization work to the protected hotfix branch. If master has changed the next-patch target, reassess the hotfix target rather than forcing a stale version.

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
git switch -c hotfix-fix/sync-develop
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
git push -u origin hotfix-fix/sync-develop
git fetch origin --tags
git-tools pr --base hotfix/missing-name
```
In GitHub create **`hotfix-fix/sync-develop` → `hotfix/missing-name`**, title **`chore: merge develop for backmerge`**. This is a real synchronization diff (including farewell), not an empty PR. No version/tag on the source. Review, pass checks, and squash-merge with that exact subject; wait for the hotfix-branch version job. Expect the copied alpha to continue to **`0.3.0-alpha.3`**, **no tag**, via the special prep rule. This rule is important: normal hotfix validation would reject a `0.3.0` version against stable `0.2.1`.

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
**Transition:** current develop → next `release/0.3.0`; no PR/title, no unique human change yet, **no new tag**, still `0.3.0-alpha.4`. Wait for the skip job. You are now at the next release cut. Classic must keep this release on its selected `0.3.0` line. Repeat the same actual-work pattern: a real feature PR titled `Start 0.4.0` opens `0.4.0-alpha.0` on develop, while a real stabilization change on release opens `0.3.0-rc.0`. Use reviewed `release-fix/*` inner PRs, including any synchronization, just as above. Then promote, wait for stable, and backmerge before deleting the source.

## Why the expected results are conditional

The engine's behavior is covered by `tests/test_git_flow_strategy.py`, `tests/test_backmerge_content.py`, and `tests/test_hotfix_backmerge.py`; implementation is in `git_tools/generators/bumpgen/{strategy,rules,repo}.py`. Backmerge content is compared against the target commit's **first parent**, ignoring only actual managed version-field changes, not whole manifests or lockfiles. Different diffs, subjects, merge styles, extra CI-producing pushes, stale refs, or a different remote engine ref can legitimately change the result. Check `.cz.toml`, bot commits, remote refs, and tags at each checkpoint rather than manufacturing a missing tag or asserting that opening a PR performed a release.

## Flow policy and edge cases

Use these rules outside the worked timeline. This is Classic plus a review trail for **every human stabilization/synchronization change**, not a compliance certification. Commands run in your application checkout.

### Feature and Bugfix Policy

Feature/bugfix PRs into develop work as in direct Classic: Conventional Commit titles create/continue tagged alpha versions. A fresh develop line may use `Start X.Y.Z` on its first real PR; branch commits remain Conventional Commits. Reviewed mode adds inner PRs to release/hotfix lines, not an extra layer on develop.

### Release-Line Policy

Develop selects the Classic release line. After cutting `release/X.Y.Z`, the next develop PR must use `Start A.B.C` for a valid forward cycle, producing tagged `A.B.C-alpha.0`; it may contain actual next-cycle work. Otherwise develop continues the same alpha line being stabilized and collides with it.

### Merge Strategy

This journey uses **squash** for every PR. Classic reviewed also permits PR-title merge commits when configured in [merge settings](setup.md#merge-settings). On release/hotfix targets, the final inner-PR subject must be a Conventional Commit. The factory-default `Merge pull request #...` subject does not advance RC; do not use rebase or change merge style midway through this example.

### Synchronization Policy

Protect master, develop, release, and hotfix targets. Grant only the bot its approved narrow signed-version push exception. Human synchronization belongs on a temporary `release-fix/*` or `hotfix-fix/*` branch based on the target source line, followed by an inner PR back into it—not a direct protected-branch push. Resolve version conflicts, review/test, merge, and wait for CI before promotion/backmerge.

An empty commit alone is **not a mergeable GitHub inner PR**. Use a real reviewable diff, or an approved auditable initialization procedure. Never bypass review just to initialize RC.

### Release Stabilization and Promotion

Creating the branch does not open RC. The first real inner PR with an eligible Conventional Commit title opens `X.Y.Z-rc.0`; later ones continue the same RC line. Use `release-fix/<name>` and one focused logical change per PR. An inner `chore: open release` title is acceptable only with a real reviewable diff; do not use fixed promotion/backmerge titles for ordinary inner fixes.

The release branch stabilizes the line already selected on develop. Include current master and the expected RC, re-test, then promote into master with `Release X.Y.Z`. Synchronize a changed master through a reviewed inner PR first, and wait for stable publication before backmerge.

### Release Backmerge

The develop PR is titled `Backmerge Release X.Y.Z`; its review is the release-to-develop boundary crossing, separate from source-line inner PRs. Keep an ahead develop alpha line; meaningful unique fixes advance it once **without tagging**. No-op/version-only changes do not advance it. Develop not yet ahead may catch up to the promoted stable version without a tag; a later real PR titled `Start A.B.C` opens the next cycle.

Follow [reviewed source synchronization](#9-synchronize-the-retained-release-source-for-backmerge), then the [develop-based integration PR](#10-backmerge-through-a-develop-based-integration-pr). Squash does not preserve source ancestry: keep develop's current version in the integration diff **only when its alpha release tuple is ahead of the promoted target**, not the source's untagged prep version. Otherwise use the [stable-catch-up procedure](#stable-catch-up-when-develop-is-not-ahead). Resolve `.cz.toml` and any managed manifest version consistently; do not choose by lexical string order.

### Stable catch-up when develop is not ahead

The numbered `0.3.0-alpha.*` backmerge is the **ahead-alpha case only**. Compare numeric release tuples, not prerelease counters or lexical strings: `0.2.0-alpha.N` is not ahead of promoted stable `0.2.0`. This procedure also applies to hotfix backmerges when develop is not ahead of the promoted patch.

1. Finish promotion and fetch its existing stable tag. Complete the retained source's synchronization through the permitted direct or reviewed lane. Wait for any no-tag preparation job and pull its result. That source version is intermediate: setting stable before the exact `chore: merge develop for backmerge` subject is not sufficient, because its special rule can open another RC.
2. Update develop, fetch tags, and create a fresh `integration/*` branch **from develop**, as in the numbered integration recipe. Merge the retained prepared source with `git merge --no-ff --no-commit <source-ref>`, replacing `<source-ref>` with the fetched release/hotfix ref. Retain all published fixes and continued develop work.
3. Before committing this integration, resolve **only the managed version fields** in `.cz.toml` and synchronized manifests/lockfiles to the **already-published stable target `X.Y.Z`**, not develop's same-line alpha or the source's preparation version. Preserve all other settings, dependencies, and application changes; do not restore whole manifests from master. For example, backmerging `Release 0.2.0` into `0.2.0-alpha.N` must propose stable `0.2.0` at the develop boundary.
4. Test and commit the integration, push it, and open its reviewed PR into develop with final title `Backmerge Release X.Y.Z` or `Backmerge Hotfix X.Y.Z`. Generate the title using the matching `git-tools pr --base develop --backmerge-release-pr --workflow-version X.Y.Z` or `--backmerge-hotfix-pr --workflow-version X.Y.Z`. Replace `X.Y.Z` with the historical promoted target. Squash-merge as in the numbered GitHub recipe; never promote this integration to master.
5. Verify develop contains the fixes and stable `X.Y.Z`. Its version job **skips because the boundary already matches stable**, including version-only backmerges; it must not advance the old alpha or create another stable tag. Open the next cycle later with a real `Start A.B.C` PR. The alternate histories are covered by `tests/test_backmerge_catchup.py`.

### Hotfix Stabilization and Promotion

Start `hotfix/<name>` from published stable master. Each human change uses `hotfix-fix/<sub-name>` → `hotfix/<name>` with a Conventional Commit title; even a single-fix hotfix needs that inner PR. Branch creation alone does not open RC. The first eligible inner PR opens the next patch `rc.0`, and later ones continue it. An empty commit alone is not an initialization PR; use a real diff or approved procedure. Reserve `Hotfix X.Y.Z` and `Backmerge Hotfix X.Y.Z` for the boundary PRs, not ordinary inner fixes.

Synchronize current master through an inner PR and re-test if it advances; reassess the target if the next-patch boundary changes. Promote with `Hotfix X.Y.Z`, then wait for stable publication.

### Hotfix Backmerge

Use `Backmerge Hotfix X.Y.Z` into develop. The helper requires `--workflow-version` for the **already-promoted patch**, not the source's synchronized alpha or master's next patch. The release-backmerge rules for ahead alpha, stable catch-up, no-op, no tag, and version resolution also apply. Follow the [reviewed hotfix synchronization](#13-synchronize-the-retained-hotfix-source-through-the-proper-lane) and [develop integration PR](#14-backmerge-the-hotfix-without-downgrading-develop); do not promote that combined source again.
