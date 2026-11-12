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
    """
    The domain model's own calls to GitHub.
    """

    GIT = "git: a notes branch on the repository"
    """
    Git reaching the repository, on a notes branch of the probe's own.
    """

    ISSUE_BOARD = "issues: the finding boards"
    """
    Filing, labelling and closing issues.
    """

    PULL_REQUEST = "pull requests: draft, review threads, base"
    """
    Opening, rewriting and closing pull requests.
    """

    STACKS = "stacks: retargeting and native stacks, through the stacks command"
    """
    Retargeting pull requests and GitHub's native stacks, through ``stack on``.
    """

    SETTINGS = "settings: issues, merged-branch deletion, Actions"
    """
    Reading and writing the repository settings the workflow relies on.
    """

    ACTIONS = "Actions: deleting branches from a workflow"
    """
    An Actions workflow deleting branches, as the notes branch's workflows do.
    """

    SIGNALS = "signals beside the repository"
    """
    What the session can read beside the repository itself.
    """


class EnvironmentFact(StrEnum):
    """
    What a probe records about the session it runs in, each valued as the report names
    it.
    """

    PYTHON = "python"
    """
    The interpreter's version.
    """

    CLOUD_SESSION = "cloud session"
    """
    Whether the session runs in the cloud.
    """

    TOKEN_VARIABLE_SET = "token variable set"
    """
    Whether a variable holds a GitHub token.
    """

    CHECKED_OUT_BRANCH = "checked-out branch"
    """
    The branch the checkout has checked out.
    """

    GIT_AUTHOR = "git author"
    """
    Who git records as a commit's author.
    """

    GIT = "git"
    """
    Git's version.
    """

    GITHUB_CLI = "gh"
    """
    The GitHub CLI's version.
    """

    REPOSITORY = "repository"
    """
    The repository the session works in.
    """

    DEFAULT_BRANCH = "default branch"
    """
    Its default branch.
    """


@dataclass(frozen=True)
class ProbeCheckOutcome:
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

    outcomes: list[ProbeCheckOutcome] = field(default_factory=list)
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
        self.outcomes.append(
            ProbeCheckOutcome(group, check, succeeded, detail, seconds)
        )
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
