"""
What a probe run found, and how it is written down.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from enum import StrEnum

# %% one finding


class CheckGroup(StrEnum):
    """
    What part of the workflow a check answers for.
    """

    LIBRARY = "domain model, used live"
    GIT = "git: a notes branch on the repository"
    ISSUE_BOARD = "issues: the finding boards"
    PULL_REQUEST = "pull requests: draft, review threads, base"
    SIGNALS = "signals beside the repository"


@dataclass(frozen=True)
class CheckOutcome:
    """
    One check and what it found.
    """

    group: CheckGroup
    """
    What part of the workflow it answers for.
    """

    check: str
    """
    What was tried.
    """

    succeeded: bool
    """
    Whether it worked.
    """

    detail: str
    """
    What came back, in one line.
    """

    seconds: float
    """
    How long it took.
    """


# %% the whole run


@dataclass
class ProbeReport:
    """
    Everything one probe run found.
    """

    environment: dict[str, str]
    """
    What the session runs on, by what was looked at.
    """

    outcomes: list[CheckOutcome] = field(default_factory=list)
    """
    Every check, in the order it ran.
    """

    def record(
        self,
        group: CheckGroup,
        check: str,
        succeeded: bool,
        detail: str,
        seconds: float,
    ) -> bool:
        """
        :param group: What part of the workflow the check answers for.
        :param check: What was tried.
        :param succeeded: Whether it worked.
        :param detail: What came back, in one line.
        :param seconds: How long it took.
        :return: *succeeded*, so a scenario can stop at a failed step.
        """
        self.outcomes.append(CheckOutcome(group, check, succeeded, detail, seconds))
        return succeeded

    def markdown(self) -> str:
        """:return: The report, for a person to read."""
        lines = ["# Probe report", "", "## Environment", ""]
        lines += [f"- **{key}**: {value}" for key, value in self.environment.items()]
        for group in CheckGroup:
            outcomes = [outcome for outcome in self.outcomes if outcome.group is group]
            if not outcomes:
                continue
            lines += [
                "",
                f"## {group}",
                "",
                "| check | ok | detail | s |",
                "|---|---|---|---|",
            ]
            lines += [
                f"| {self._cell(outcome.check)} | {'yes' if outcome.succeeded else 'NO'} "
                f"| {self._cell(outcome.detail)} | {outcome.seconds} |"
                for outcome in outcomes
            ]
        return "\n".join(lines) + "\n"

    @staticmethod
    def _cell(text: str) -> str:
        """:param text: A table cell's content.
        :return: It, safe inside a Markdown table row."""
        return text.replace("|", "\\|").replace("\n", " ")

    def to_json(self) -> str:
        """:return: The report, for a program to read."""
        return json.dumps(asdict(self), indent=2) + "\n"
