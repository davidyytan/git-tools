"""Strategy decision record and its CI output encoding."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Literal

Flow = Literal["classic", "variant"]


@dataclass(frozen=True)
class StrategyDecision:
    skip: bool
    invalid: bool
    mode: str = ""
    args: str = ""
    reason: str = ""
    error: str = ""
    branch: str = ""
    release_target: str = ""
    release_increment: str = ""
    hotfix_target: str = ""
    current_version: str = ""
    current_release_line: str = ""
    master_version: str = ""
    master_release_line: str = ""
    bootstrap_commitizen_version_ok: bool = False
    bootstrap_subject_ok: bool = False
    current_is_prerelease: bool = False
    bump_eligible: bool = False
    subject: str = ""
    branch_gate_ref: str = ""
    branch_has_unique_commits: bool = False
    create_tag: bool = True

    def outputs(self) -> dict[str, str]:
        values: dict[str, str] = {}
        for key, value in asdict(self).items():
            if isinstance(value, bool):
                values[key] = "true" if value else "false"
            else:
                values[key] = value
        return values


def replace_decision(decision: StrategyDecision, **changes: object) -> StrategyDecision:
    values = asdict(decision)
    values.update(changes)
    return StrategyDecision(**values)


def write_github_output(path: Path, decision: StrategyDecision) -> None:
    with path.open("a", encoding="utf-8") as handle:
        for key, value in decision.outputs().items():
            # Single-line output records must not let data create new records.
            value = value.replace("\r", " ").replace("\n", " ")
            handle.write(f"{key}={value}\n")
