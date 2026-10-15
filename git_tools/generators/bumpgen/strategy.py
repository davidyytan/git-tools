"""Decide how a CI run on a given branch should bump the version, if at all."""

from __future__ import annotations

from pathlib import Path

from .config import has_bootstrap_commitizen_version, load_bump_config
from .conventions import (
    BACKMERGE_PREP_SUBJECT,
    GENERATED_BUMP_PREFIX,
    RELEASE_BRANCH_PATTERN,
    is_bootstrap_release_subject,
    is_bump_eligible,
    is_dvc_experiment_commit,
    normalize_workflow_subject,
)
from .decision import Flow, StrategyDecision, replace_decision
from .git import branch_has_unique_commits_since, get_last_commit_message, get_tag_names
from .repo import load_version_from_refs
from .rules import (
    decide_classic_release_strategy,
    decide_develop_strategy,
    decide_hotfix_strategy,
    decide_master_strategy,
    decide_variant_release_strategy,
)
from .version import (
    Version,
    _format_release_tuple,
    _version_is_alpha,
    infer_release_increment,
    next_patch_release_line,
)


def decide_version_strategy(root: Path, branch: str, *, flow: Flow) -> StrategyDecision:
    last_commit = get_last_commit_message(root)
    subject = last_commit.splitlines()[0] if last_commit else ""
    current_config = load_bump_config(root)
    current_version = current_config.current_version_text
    current_version_parsed = current_config.current_version
    current_is_prerelease = current_version_parsed.is_prerelease
    current_release_line = _format_release_tuple(current_version_parsed.release)
    master_version = ""
    master_release_line = ""
    hotfix_target = ""
    release_increment = ""
    branch_gate_ref = ""
    branch_has_unique_commits = False
    bump_eligible = is_bump_eligible(last_commit)
    has_tags = bool(get_tag_names(root))
    release_match = RELEASE_BRANCH_PATTERN.fullmatch(branch)
    release_target = release_match.group("target") if release_match else ""
    release_branch_error = ""
    hotfix_branch_error = ""
    bootstrap_commitizen_version_ok = has_bootstrap_commitizen_version(root)
    bootstrap_subject_ok = is_bootstrap_release_subject(subject)

    if branch.startswith("release/"):
        branch_has_unique_commits, branch_gate_ref = branch_has_unique_commits_since(
            root,
            ("origin/develop", "develop"),
        )
        if flow == "variant":
            master_version = load_version_from_refs(root, ("origin/master", "master"))
            master_release_line = _format_release_tuple(
                Version.parse(master_version).release
            )
            if not release_match:
                release_branch_error = (
                    "release branches must be named release/<x.y.z>, "
                    f"got {branch}"
                )
            else:
                release_increment = infer_release_increment(master_version, release_target) or ""
            if not release_branch_error and not release_increment:
                release_branch_error = (
                    f"release branch target {release_target} is not a valid "
                    f"MAJOR/MINOR/PATCH step from master version {master_release_line}"
                )
        else:
            if not release_match:
                release_branch_error = (
                    "release branches must be named release/<x.y.z>, "
                    f"got {branch}"
                )
            elif not current_is_prerelease:
                release_branch_error = (
                    "classic release branches must carry a prerelease on the "
                    f"selected line, got {current_version}"
                )
            elif release_target != current_release_line:
                release_branch_error = (
                    f"classic release branch target {release_target} does not match "
                    f"the current prerelease line {current_release_line}"
                )

    if branch.startswith("hotfix/"):
        master_version = load_version_from_refs(root, ("origin/master", "master"))
        master_release_line = _format_release_tuple(
            Version.parse(master_version).release
        )
        hotfix_target = next_patch_release_line(master_version)
        branch_has_unique_commits, branch_gate_ref = branch_has_unique_commits_since(
            root,
            ("origin/master", "master"),
        )
        if current_release_line == master_release_line:
            if current_is_prerelease:
                hotfix_branch_error = (
                    f"hotfix branches should start from stable master state, got {current_version}"
                )
        elif current_release_line == hotfix_target:
            if not current_is_prerelease:
                hotfix_branch_error = (
                    "hotfix branches must carry a prerelease after selecting "
                    f"the patch target line, got {current_version}"
                )
        else:
            hotfix_branch_error = (
                f"hotfix branch version line {current_release_line} does not align "
                f"with master {master_release_line} or next patch target {hotfix_target}"
            )

    decision = StrategyDecision(
        skip=False,
        invalid=False,
        branch=branch,
        release_target=release_target,
        release_increment=release_increment,
        hotfix_target=hotfix_target,
        current_version=current_version,
        current_release_line=current_release_line,
        master_version=master_version,
        master_release_line=master_release_line,
        bootstrap_commitizen_version_ok=bootstrap_commitizen_version_ok,
        bootstrap_subject_ok=bootstrap_subject_ok,
        current_is_prerelease=current_is_prerelease,
        bump_eligible=bump_eligible,
        subject=subject,
        branch_gate_ref=branch_gate_ref,
        branch_has_unique_commits=branch_has_unique_commits,
    )

    if normalize_workflow_subject(subject) == BACKMERGE_PREP_SUBJECT and (
        branch.startswith("release/") or branch.startswith("hotfix/")
    ):
        if not bump_eligible:
            return replace_decision(
                decision,
                skip=True,
                reason="backmerge prep commit is not bump-eligible",
            )
        if _version_is_alpha(current_version):
            return replace_decision(
                decision,
                mode="backmerge-prep-alpha",
                args="--yes --prerelease alpha --default-increment PATCH --no-tag",
                create_tag=False,
                reason="backmerge prep continues the current alpha line",
            )
        if current_is_prerelease:
            return replace_decision(
                decision,
                mode="backmerge-prep-rc",
                args="--yes --increment PATCH --prerelease rc --no-tag",
                create_tag=False,
                reason="backmerge prep continues the current rc line",
            )
        return replace_decision(
            decision,
            mode="backmerge-prep-start-rc",
            args="--yes --increment PATCH --prerelease rc --no-tag",
            create_tag=False,
            reason="backmerge prep starts rc on the stable base",
        )

    if subject.startswith(GENERATED_BUMP_PREFIX) and (
        release_branch_error or hotfix_branch_error
    ):
        return replace_decision(
            decision,
            skip=True,
            reason="latest commit was generated by the version bump workflow",
        )

    if release_branch_error:
        return replace_decision(decision, invalid=True, error=release_branch_error)
    if hotfix_branch_error:
        return replace_decision(decision, invalid=True, error=hotfix_branch_error)
    if is_dvc_experiment_commit(last_commit):
        return replace_decision(
            decision,
            skip=True,
            reason="latest commit was generated by DVC experiment tracking",
        )
    if branch.startswith("feature/") or branch.startswith("bugfix/"):
        return replace_decision(
            decision,
            skip=True,
            reason="feature and bugfix branches do not publish versions",
        )
    if branch == "develop":
        return decide_develop_strategy(root, decision)
    if branch.startswith("release/"):
        if flow == "variant":
            return decide_variant_release_strategy(decision)
        return decide_classic_release_strategy(decision)
    if branch.startswith("hotfix/"):
        return decide_hotfix_strategy(decision)
    if branch == "master":
        return decide_master_strategy(decision, has_tags=has_tags, flow=flow)
    return replace_decision(
        decision,
        skip=True,
        reason=f"branch {branch} is not managed by this workflow",
    )
