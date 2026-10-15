"""Conventional Commit bump rules and Git Flow subject/branch conventions."""

from __future__ import annotations

import re
from string import Template

from .version import Increment, Version

DEFAULT_BUMP_MESSAGE = "bump: version $current_version → $new_version"
DEFAULT_BUMP_PATTERN = re.compile(r"^((BREAKING[\-\ ]CHANGE|\w+)(\(.+\))?!?):")
BOOTSTRAP_RELEASE_SUBJECTS = frozenset({"Release 0.0.1", "Release 0.1.0"})
RELEASE_BRANCH_PATTERN = re.compile(r"^release/(?P<target>\d+\.\d+\.\d+)$")
RELEASE_MERGE_SUBJECT_PATTERN = re.compile(r"^Release (?P<target>\d+\.\d+\.\d+)$")
HOTFIX_MERGE_SUBJECT_PATTERN = re.compile(r"^Hotfix (?P<target>\d+\.\d+\.\d+)$")
START_SUBJECT_PATTERN = re.compile(r"^Start (?P<target>\d+\.\d+\.\d+)$")
BACKMERGE_RELEASE_SUBJECT_PATTERN = re.compile(
    r"^Backmerge Release (?P<target>\d+\.\d+\.\d+)$"
)
BACKMERGE_HOTFIX_SUBJECT_PATTERN = re.compile(
    r"^Backmerge Hotfix (?P<target>\d+\.\d+\.\d+)$"
)
GITHUB_PR_SUFFIX_PATTERN = re.compile(r"^(?P<subject>.+?)\s+\(#\d+\)$")
AZURE_DEVOPS_PR_PREFIX_PATTERN = re.compile(r"^Merged PR \d+:\s*(?P<subject>.+)$")
_VERSION_TOKEN = (
    r"\d+\.\d+\.\d+(?:-(?:(?:alpha|beta|rc)\.\d+|(?:a|b|rc)\d+))?"
)
BUMP_SUBJECT_TARGET_PATTERN = re.compile(
    r"^bump:\s+version\s+"
    rf"(?P<previous>{_VERSION_TOKEN})\s+"
    r"(?:→|->)\s+"
    rf"(?P<current>{_VERSION_TOKEN})$"
)
GENERATED_BUMP_PREFIX = "bump:"
DVC_EXPERIMENT_COMMIT_PATTERN = re.compile(r"^dvc:\s+commit experiment\b")
RELEASE_MANAGEMENT_PREFIX = "chore(release):"
BACKMERGE_PREP_SUBJECT = "chore: merge develop for backmerge"
BUMP_RULES: tuple[tuple[re.Pattern[str], Increment], ...] = (
    (re.compile(r"^.+!$"), "MAJOR"),
    (re.compile(r"^BREAKING[\-\ ]CHANGE"), "MAJOR"),
    (re.compile(r"^feat"), "MINOR"),
    (re.compile(r"^fix"), "PATCH"),
    (re.compile(r"^refactor"), "PATCH"),
    (re.compile(r"^perf"), "PATCH"),
)


def detect_increment(
    commit_messages: list[str],
    *,
    major_version_zero: bool,
    default_increment: Increment | None = None,
) -> Increment | None:
    current: Increment | None = None
    priority = {None: -1, "PATCH": 0, "MINOR": 1, "MAJOR": 2}

    for message in commit_messages:
        if is_dvc_experiment_commit(message):
            continue

        for line in message.splitlines():
            match = DEFAULT_BUMP_PATTERN.search(line)
            if not match:
                continue

            found_keyword = match.group(1)
            detected: Increment | None = None
            for pattern, increment in BUMP_RULES:
                if pattern.match(found_keyword):
                    detected = increment
                    break

            if detected is None:
                detected = default_increment

            if detected == "MAJOR" and major_version_zero:
                detected = "MINOR"

            if detected is None:
                continue

            if priority[detected] > priority[current]:
                current = detected

            if current == "MAJOR":
                return current

    return current


def normalize_workflow_subject(subject: str) -> str:
    stripped = subject.strip()
    match = GITHUB_PR_SUFFIX_PATTERN.fullmatch(stripped)
    if match is not None:
        stripped = match.group("subject")
    prefix_match = AZURE_DEVOPS_PR_PREFIX_PATTERN.fullmatch(stripped)
    if prefix_match is not None:
        stripped = prefix_match.group("subject")
    return stripped


def is_bootstrap_release_subject(subject: str) -> bool:
    return normalize_workflow_subject(subject) in BOOTSTRAP_RELEASE_SUBJECTS


def parse_bump_subject_target_version(subject: str) -> str | None:
    match = BUMP_SUBJECT_TARGET_PATTERN.fullmatch(subject.strip())
    if match is None:
        return None
    return match.group("current")


def is_dvc_experiment_commit(message: str) -> bool:
    subject = message.splitlines()[0].strip() if message.strip() else ""
    return bool(DVC_EXPERIMENT_COMMIT_PATTERN.match(subject))


def is_bump_eligible(message: str) -> bool:
    if is_dvc_experiment_commit(message):
        return False

    lines = message.splitlines()
    for index, line in enumerate(lines):
        if index == 0:
            line = normalize_workflow_subject(line)
        if DEFAULT_BUMP_PATTERN.search(line):
            return True
    return False


def create_bump_message(
    current_version: Version,
    new_version: Version,
    template: str = DEFAULT_BUMP_MESSAGE,
) -> str:
    return Template(template).safe_substitute(
        current_version=current_version,
        new_version=new_version,
    )
