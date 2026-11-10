# GitHub branch rulesets for version publication

[Browser policy index and screenshots](README.md) · [Optional independent review](03-independent-review.md)

**Scope:** this CLI recipe configures only policies 1 and 2: PR-only changes and history protection. It does not install optional independent review or the merger allowlist. The solo-developer preset uses policies 1, 2, and 4 with zero required approvals; teams can add policy 3 when another eligible reviewer is available.

[GitHub guides](../actions/README.md) · [Setup and merge settings](../actions/setup.md#merge-settings) · [Publication and recovery](../../publication.md)

Use this recipe to require PRs for human changes to `develop` and `master` while allowing the trusted git-tools publisher to push its version commits directly. Keep history protection in a separate ruleset so the publisher cannot bypass force-push or branch-deletion protection.

This is manual GitHub repository configuration, not a new git-tools command. `git-tools init` does not create rulesets, and `git-tools pr` does not create or merge hosted PRs.

**Concrete preset: Classic with merge commits.** The payloads below allow only merge commits. The serialized walkthroughs use squash, and release-led reviewed requires squash for its ordinary PRs and promotions: adapt `allowed_merge_methods` and repository merge settings to your chosen [flow](../actions/README.md#choose-a-flow) before using this recipe. Do not apply the merge-only preset unchanged to a squash-based process. Reviewed current-master synchronization still needs its ancestry-preserving merge-commit route.

## The two layers

Both rulesets target exactly `refs/heads/develop` and `refs/heads/master`, with no exclusions. Extend the target list only after reviewing your flow: this preset does not protect `release/*`, `hotfix/*`, feature branches, or tags.

| Name | Rules | Bypass |
| --- | --- | --- |
| **PR-only develop and master** | Require a PR; merge commits only in this preset | Only the dedicated publishing account, `User` / its numeric account ID / `always` |
| **Protect develop and master history** | Block deletion and non-fast-forward updates | None, including the publisher |

The bot bypass applies only to the PR layer. Putting history rules in that same bypassed ruleset would also exempt the bot from those safeguards. Bypass is not global: an exception in one ruleset does not waive another ruleset or classic protection.

The solo-maintainer preset requires **zero approving reviews**, with code-owner, last-push, additional-reviewer, extra-approval, and conversation-resolution requirements off. This permits the author to merge their own PR without a self-review deadlock. It enforces the PR path, not independent review or passing tests. A team can choose one or more approvals and other review requirements when an independent reviewer can actually satisfy them.

## Before changing settings

- Complete [bootstrap](../actions/setup.md#bootstrap-master-and-develop) first if this is a fresh repository. This recipe assumes both target branches already exist; do not repeat bootstrap or rewrite existing history to apply it.
- Use a GitHub plan that supports branch rulesets for the repository's visibility. Private personal repositories need an eligible plan such as GitHub Pro; see [GitHub's availability rules](https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/managing-rulesets/about-rulesets). A successful metadata GET alone does not prove enforcement entitlement.
- Use a human owner/admin account, or another account with rule-edit permission, to configure the rules. Keep the publisher's credentials separate. Bypass does not grant repository access: the publishing account still needs ordinary write access, not admin access.
- Confirm signing and publication in an approved test repository before enforcing a production policy. Keep existing working credentials; this procedure does not require rotating keys, creating an App, or changing the workflow's authentication.
- For the concrete merge-only Classic preset, enable merge commits, disable squash/rebase merge, and use the PR title as the default merge commit subject (`PR_TITLE`), with PR body as its default body (`PR_BODY`). Preserve the final control title or Conventional Commit subject expected by [the protocol](../../git-flow-guide.md#pr-titles-drive-versioning).

GitHub.com added individual-user bypass on **repository-level rulesets**, explicitly including service accounts, on [7 May 2026](https://github.blog/changelog/2026-05-07-repository-rulesets-user-bypass-and-branch-renaming/). Use `actor_type: User` with the numeric account database ID, not an App ID, GraphQL node ID, SSH-key ID, or GPG fingerprint. Older general lists of roles/teams/apps are not exhaustive. Classic branch-protection bypass lists have organization-specific restrictions; this recipe uses repository rulesets instead. Check feature/version availability separately on GitHub Enterprise Server.

## 1. Identify the real push account and existing policies

Run these commands in your own local Bash terminal with GitHub CLI (`gh`) and Python 3.12 available. The heredocs use `python`: activate your Python 3.12 environment or substitute its `python3.12`/`python3` executable. Commands can run from any directory because every API call names the application repository explicitly. Replace both placeholders; `REPO` is your application repository, not the git-tools source repository. Keep the variables and helper functions in the same shell across steps; after a shell restart, restore the recorded variables and IDs rather than repeating creation POSTs.

```bash
export REPO="YOUR_OWNER/YOUR_REPOSITORY"
export BOT_LOGIN="YOUR_AUTOMATION_LOGIN"
gh api user --jq .login
gh api "repos/$REPO" --jq '{repository: .full_name, private: .private, admin: .permissions.admin}'
gh api "users/$BOT_LOGIN" --jq '{login, id, type}'
gh api "repos/$REPO/collaborators/$BOT_LOGIN/permission" --jq '{permission, login: .user.login}'
BOT_ID="$(gh api "users/$BOT_LOGIN" --jq .id)"
export BOT_ID
```

Check that the configuring account is the intended human administrator, the bot is a regular `User`, and the bot has write access. The supplied workflow authenticates its final push with `BOT_SSH_SECRETKEY`. `GIT_BOT_NAME` / `GIT_BOT_EMAIL` control commit identity; GPG signing identity and the Actions run's triggering actor do not establish the push credential's account. `GITHUB_TOKEN` write permission does not give that SSH account a ruleset bypass.

Use an actual publication push record to corroborate the account, not just a commit byline. For recent repository activity:

```bash
gh api "repos/$REPO/events?per_page=100" --jq '.[] | select(.type == "PushEvent") | {actor: .actor.login, ref: .payload.ref, head: .payload.head}'
```

Match the event's head to the published version commit. Activity retention is limited; absent events are not proof of a different identity. Historical events establish the actor of that push, not the contents of a subsequently changed secret. If current authentication is uncertain, validate it through your approved test process rather than reading or exposing private keys or secret values.

This recipe is for a user-account publisher. If checkout authenticates as a GitHub App or deploy key, use the supported bypass type for that actual principal; do not disguise its identifier as a `User`, silently broaden the bypass to a repository role, or change credentials without an approved migration.

Inspect existing repository and inherited rulesets before creating anything:

```bash
gh api "repos/$REPO/rulesets?includes_parents=true&per_page=100" --paginate --jq '.[] | {id, name, target, enforcement, source}'
```

Also inspect classic branch protection for each target in GitHub settings or with `GET /repos/OWNER/REPO/branches/BRANCH/protection`. A `404` from that endpoint can mean no classic protection; it does not establish that repository rulesets are absent. Stop on permission or plan errors. Save relevant existing definitions and resolve overlapping gates with their owners; do not delete or weaken unrelated policies. If the two intended rulesets already exist, inspect their recorded IDs and update deliberately instead of repeating the creation POSTs.

## 2. Prepare disabled payloads

The following creates only local, non-secret JSON files in a temporary directory. Keep that directory and the returned ruleset IDs as an audit/rollback record. No hosted settings change in this step.

```bash
RULES_DIR="$(mktemp -d)"
export RULES_DIR
python - <<'PY'
import json
import os
from pathlib import Path

bot_id = int(os.environ["BOT_ID"])
if bot_id <= 0:
    raise SystemExit("BOT_ID must be a positive numeric account ID")
root = Path(os.environ["RULES_DIR"])
if not root.is_absolute() or not root.is_dir():
    raise SystemExit("RULES_DIR must be an existing absolute temporary directory")
conditions = {"ref_name": {"include": ["refs/heads/develop", "refs/heads/master"], "exclude": []}}
common = {"target": "branch", "enforcement": "disabled", "conditions": conditions}
payloads = {
    "pr": {
        **common,
        "name": "PR-only develop and master",
        "bypass_actors": [{"actor_type": "User", "actor_id": bot_id, "bypass_mode": "always"}],
        "rules": [{"type": "pull_request", "parameters": {
            "required_approving_review_count": 0,
            "dismiss_stale_reviews_on_push": False,
            "required_reviewers": [],
            "require_code_owner_review": False,
            "require_last_push_approval": False,
            "required_review_thread_resolution": False,
            "require_extra_approval_for_unattributed_changes": False,
            "allowed_merge_methods": ["merge"],
        }}],
    },
    "history": {
        **common,
        "name": "Protect develop and master history",
        "bypass_actors": [],
        "rules": [{"type": "deletion"}, {"type": "non_fast_forward"}],
    },
}
for kind, payload in payloads.items():
    (root / f"{kind}.json").write_text(json.dumps(payload, indent=2) + "\n")
print(root)
PY
```

Review both files. In particular, confirm the selected bot ID and branch names. The `always` bypass is necessary for direct publication; `pull_request` bypass mode would still require the bot to use a PR. Use `always`, not `exempt`, for this PR-layer automation exception; `exempt` omits pass/fail results. Do not add an owner/admin/write-role exception here. The named-human exemptions in the separate [policy 4 eligibility layer](04-allowed-mergers.md) do not waive this PR layer. The extra-approval flag is explicitly false rather than relying on a server default.

The exception authorizes otherwise-permitted fast-forward updates authenticated as that account. It is **not** a workflow-name allowlist or a restriction to version files. Protect the credential and workflow from untrusted code. This recipe does not add update restrictions, status checks, linear history, a signing gate, or tag rules.

## 3. Create disabled candidates and verify the round-trip

**These POSTs create new GitHub settings.** Run one step at a time, stop on any error, and do not repeat successful POSTs. The helper returns on a failed API call or invalid numeric ID rather than calling `exit`; stop after its nonzero result. If it stops after creating one candidate, retain that ID and inspect or remove only that disabled candidate. Do not rerun the whole creation helper and duplicate the successful POST.

```bash
create_disabled_rulesets() {
    test -n "${REPO:-}" && test -d "${RULES_DIR:-}" || return 1
    PR_RULE_ID="$(gh api --method POST "repos/$REPO/rulesets" --input "$RULES_DIR/pr.json" --jq .id)" || return 1
    case "$PR_RULE_ID" in ''|0|*[!0-9]*) return 1 ;; esac
    HISTORY_RULE_ID="$(gh api --method POST "repos/$REPO/rulesets" --input "$RULES_DIR/history.json" --jq .id)" || return 1
    case "$HISTORY_RULE_ID" in ''|0|*[!0-9]*) return 1 ;; esac
    gh api "repos/$REPO/rulesets/$PR_RULE_ID?includes_parents=true" > "$RULES_DIR/pr-staged.json" || return 1
    gh api "repos/$REPO/rulesets/$HISTORY_RULE_ID?includes_parents=true" > "$RULES_DIR/history-staged.json" || return 1
}
create_disabled_rulesets
```

Inspect the full single-ruleset GET responses with rule-edit authority. GitHub omits `bypass_actors` when the reader lacks write access to the ruleset: a missing field is **not** evidence of an empty bypass list. Do not activate if either response is rejected, unexpectedly altered, or incomplete.

Compare the stored definitions against the payloads:

- Correct repository source and actual returned IDs; `target: branch`; `enforcement: disabled`.
- Exactly the two intended full branch refs, no exclusions or broader wildcards.
- PR layer: only `pull_request`, all eight parameters as supplied, and exactly the selected `User` ID with `always` bypass.
- History layer: exactly `deletion` and `non_fast_forward`, with a present, empty `bypass_actors` list.
- No broad role exception or unexpected additional gate. The human configuring account should have no ordinary push bypass.

Disabled staging validates acceptance and persistence without enforcing the candidates. It is not Enterprise-only `evaluate` mode and does not execute a publisher or prove a future push succeeds. Recheck for conflicting classic/inherited rules before activation.

## 4. Activate the verified candidates

Only after both disabled definitions pass review, generate active payloads without changing their other settings:

```bash
activate_verified_rulesets() {
    test -n "${REPO:-}" && test -d "${RULES_DIR:-}" || return 1
    for RULE_ID in "${PR_RULE_ID:-}" "${HISTORY_RULE_ID:-}"; do
        case "$RULE_ID" in ''|0|*[!0-9]*) return 1 ;; esac
    done
    python - <<'PY' || return 1
import json
import os
from pathlib import Path

root = Path(os.environ["RULES_DIR"])
for kind in ["pr", "history"]:
    payload = json.loads((root / f"{kind}.json").read_text())
    payload["enforcement"] = "active"
    (root / f"{kind}-active.json").write_text(json.dumps(payload, indent=2) + "\n")
PY
    gh api --method PUT "repos/$REPO/rulesets/$HISTORY_RULE_ID" --input "$RULES_DIR/history-active.json" --jq '{id, name, enforcement}' || return 1
    gh api --method PUT "repos/$REPO/rulesets/$PR_RULE_ID" --input "$RULES_DIR/pr-active.json" --jq '{id, name, enforcement}' || return 1
}
activate_verified_rulesets
```

Activate history protection first, then the PR rule. Stop if either update fails; inspect the actual applied state rather than assuming an all-or-nothing transaction. Never widen the publisher exception merely to make activation succeed.

Read both definitions again and check effective rules on each branch:

```bash
gh api "repos/$REPO/rulesets/$PR_RULE_ID?includes_parents=true" > "$RULES_DIR/pr-final.json"
gh api "repos/$REPO/rulesets/$HISTORY_RULE_ID?includes_parents=true" > "$RULES_DIR/history-final.json"
for BRANCH in develop master; do
    gh api "repos/$REPO/branches/$BRANCH" --jq '{name, protected}'
    gh api "repos/$REPO/rules/branches/$BRANCH?per_page=100" --paginate --jq '.[] | {type, ruleset_id, ruleset_source_type, ruleset_source}'
done
```

The full definitions must retain every approved parameter and bypass actor and now show `enforcement: active`. Where exposed, `current_user_can_bypass: never` corroborates that the human configuring account has no normal push exception. With only this recipe and no overlapping classic protection, both branches should report `protected: true` and exactly `pull_request`, `deletion`, and `non_fast_forward` from the two recorded IDs. Account for every extra rule if existing policies remain.

Record the actual names, IDs, branch scope, enforcement, full review parameters, bypass lists, and GitHub rule URLs. Configuration verification is not application validation or end-to-end publication proof.

## 5. Let the owner perform the publication test

The owner should perform an approved PR merge following the selected walkthrough and final-subject protocol. Do not automatically merge a real PR, dispatch a mutating workflow, or push a test commit just to validate settings. Zero required approvals is not a substitute for the tests/review your project needs.

Observe the resulting publishing run, its signed version commit, actual push principal, and the exact tag's peeled commit target when tagging is expected. A successful merge or a later bot-triggered skip run does not prove the preceding publication succeeded. Wait for publication before the next version-producing operation in that repository.

## Additional gates and recovery

- **Required checks:** use a separate read-only `pull_request` test workflow. The version-bump publisher is push-triggered and does not run for every PR source. A check gate on a new, unpublished bot SHA can block its direct push even when the original PR's checks passed. Every applicable PR/check gate must permit the trusted publisher; the PR-layer bypass does not waive another ruleset. Keep such gates out of the no-bypass history layer unless the publisher can satisfy them before pushing.
- **Merge methods and ancestry:** preserve the final PR title as the merge subject and the chosen walkthrough's merge method. Do not add linear history to this merge-commit preset or block the reviewed current-master synchronization route. Rebase merge is not supported by the documented flows.
- **Signing and tags:** the examples already sign publication commits/tags. An additional verified-signature gate needs validation for both human merges and the publisher. Any separate tag rules must permit creation of the exact version tag; an independently rejected tag can reject an atomic branch/tag publication too.
- **Update restrictions:** this baseline uses `pull_request` to enforce the human PR path. Do not add an unplanned `update` restriction that also denies ordinary PR merges to non-bypassed humans. If you deliberately want a named-merger restriction, follow the separate [policy 4 guide](04-allowed-mergers.md), with exact named-human `exempt` entries only in that eligibility layer. Keep the separate PR path, optional review gate, and no-bypass history protection in force.
- **Rollback:** if creation/verification fails, disable or remove only the newly created candidate IDs. To disable one, PUT its original disabled payload back to its recorded ID; do not replay the creation POST. Keep unrelated policies intact and explicitly decide whether history protection should remain active. Disabling a ruleset does not undo a merge or repair publication.
- **Publication failure:** inspect the run and both remote branch/tag refs before any retry. Non-atomic fallback can leave a bump commit without its tag, and the original unpublished signed tag may be lost with a disposed runner. Do not blindly rerun, reset branches, force-push, or replace tags; use [publication and missing-tag recovery](../../publication.md).

For API permission requirements, current parameters and actor types, see the [REST repository ruleset API](https://docs.github.com/en/rest/repos/rules). Reassess the policy when changing the publisher credential, target branches, merge strategy, required checks, or review capacity.
