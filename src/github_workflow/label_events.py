"""
Finding labels picked on GitHub completed, by an Actions workflow or by a session where
the workflow is not installed: a stage, priority or evidence label replaces the others of
its kind.

Usage: ``python -m github_workflow.label_events <event file>``, with the ``issues``
event GitHub hands the workflow.
"""

from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Any

from basstler_domain_model.github.issue_models import Issue, LabelEvent
from basstler_domain_model.github.repository_client import (
    GitHubRepository,
    IssueBoard,
    IssueLabelHistory,
    RepositoryLabels,
)
from basstler_domain_model.github.vocabulary import (
    IssueState,
    IssueStateReason,
    JSONModel,
    RestJSONKey,
)
from basstler_domain_model.repository import Repository

from github_workflow.findings import (
    Evidence,
    FindingLabelling,
    FindingPrioritization,
    FindingStage,
    Priority,
)
from github_workflow.hooks import ReportLine, Speaker, Tone
from github_workflow.locations import ProjectFile, WorkflowTemplate
from github_workflow.report_section import ReportSection
from github_workflow.work import WorkflowStep
from github_workflow.workflow_templates import ActionRequirement, TemplatePlaceholder

# %% the event


class IssueEventKey(StrEnum):
    """
    The keys of an ``issues`` event that the REST answers do not share.
    """

    ISSUE = "issue"
    """
    The issue the event is about.
    """

    LABEL = "label"
    """
    The label just added.
    """

    REPOSITORY = "repository"
    """
    The repository the issue is in.
    """

    FULL_NAME = "full_name"
    """
    A repository's ``owner/name``.
    """


@dataclass(frozen=True)
class IssueLabelled(JSONModel):
    """
    A label added to an issue, as the ``issues`` event of type ``labeled`` reports it.
    """

    repository: Repository
    """
    The repository the issue is in.
    """

    number: int
    """
    The issue's number.
    """

    label: str
    """
    The name of the label added.
    """

    @classmethod
    def from_json(cls, data: dict[str, Any]) -> IssueLabelled:
        return cls(
            Repository.parse(data[IssueEventKey.REPOSITORY][IssueEventKey.FULL_NAME]),
            data[IssueEventKey.ISSUE][RestJSONKey.NUMBER],
            data[IssueEventKey.LABEL][RestJSONKey.NAME],
        )


# %% completing the label


@dataclass(frozen=True)
class FindingLabelCompletion(FindingLabelling):
    """
    A label just added to an issue, completed: a priority as :class:`FindingPrioritization`
    gives it, a stage or evidence replacing the others of its kind, and an incorrect
    finding closed as not planned. A label removed again since, or one outside the
    findings, changes nothing.
    """

    number: int
    """
    The issue.
    """

    label: str
    """
    The name of the label added.
    """

    def run(self) -> str:
        issue = self.board.issue(self.number)
        if self.label not in issue.labels:
            return f"#{self.number} no longer carries {self.label}"
        if self.label in Priority:
            return FindingPrioritization(
                self.board, self.labels, self.number, Priority(self.label)
            ).run()
        if self.label in Evidence:
            self.relabel(issue, [Evidence(self.label)])
            return f"marked #{self.number} {self.label}"
        if self.label not in FindingStage:
            return f"{self.label} is no finding label"
        stage = FindingStage(self.label)
        self.relabel(issue, [stage])
        if stage is FindingStage.INCORRECT and issue.state is IssueState.OPEN:
            self.board.close_issue(self.number, IssueStateReason.NOT_PLANNED)
        return f"moved #{self.number} to {stage}"


# %% completing them from a session


@dataclass(frozen=True)
class PickedLabelCompletion:
    """
    The finding labels the person picked on GitHub, completed from a session as
    :class:`FindingLabelCompletion` completes one: on each open finding carrying several
    labels of one kind, the one added last stays, and an open finding labelled incorrect
    is closed.
    """

    board: IssueBoard
    """
    Lists and labels the issues.
    """

    labels: RepositoryLabels
    """
    Creates the finding labels the repository lacks.
    """

    history: IssueLabelHistory
    """
    Reads in which order an issue's labels were added.
    """

    def complete(self) -> list[str]:
        """
        :return: What was completed, one entry per label.
        """
        found = {
            issue.number: issue
            for stage in FindingStage
            for issue in self.board.issues([stage], IssueState.OPEN)
        }
        return [
            FindingLabelCompletion(self.board, self.labels, number, label).run()
            for number, issue in found.items()
            for label in self.picks(issue)
        ]

    def picks(self, issue: Issue) -> list[str]:
        """
        :param issue: An open finding.
        :return: The labels picked on it that are not completed yet: the one added
            last of each kind it carries several of, or the incorrect stage it still
            carries open.
        """
        kinds = (FindingStage, Priority, Evidence)
        contested = [
            kind for kind in kinds if sum(label in kind for label in issue.labels) > 1
        ]
        if not contested:
            incorrect = FindingStage.from_issue(issue) is FindingStage.INCORRECT
            return [FindingStage.INCORRECT] if incorrect else []
        events = self.history.label_events(issue.number)
        return [
            picked
            for kind in contested
            if (picked := self.added_last(kind, issue, events)) is not None
        ]

    @staticmethod
    def added_last(
        kind: type[FindingStage | Priority | Evidence],
        issue: Issue,
        events: list[LabelEvent],
    ) -> str | None:
        """
        :param kind: A kind of finding label.
        :param issue: The finding.
        :param events: Its labels added and removed, oldest first.
        :return: The label of that kind it carries that was added last, ``None`` when
            its events name none.
        """
        return next(
            (
                event.label
                for event in reversed(events)
                if event.added and event.label in kind and event.label in issue.labels
            ),
            None,
        )


@dataclass(frozen=True)
class LabelsCompletedStep(WorkflowStep):
    """
    A step run once the finding labels picked on GitHub are completed, saying first
    what that did.
    """

    completion: PickedLabelCompletion
    """
    Completes the labels.
    """

    step: WorkflowStep
    """
    The step asked for.
    """

    def run(self) -> str:
        done = [f"completed: {entry}" for entry in self.completion.complete()]
        return "\n".join([*done, self.step.run()])


@dataclass(frozen=True)
class LabelsCompletedReport(ReportSection):
    """
    A section of the session start computed once the finding labels picked on GitHub
    are completed, with a line saying what that did.
    """

    completion: PickedLabelCompletion
    """
    Completes the labels.
    """

    section: ReportSection
    """
    The section asked for.
    """

    def lines(self) -> list[ReportLine]:
        done = self.completion.complete()
        completed = [
            ReportLine(Speaker.WORKFLOW.says(f"completed {'; '.join(done)}"), Tone.NEWS)
        ]
        return [*(completed if done else []), *self.section.lines()]


# %% the Actions workflow


@dataclass(frozen=True)
class FindingAutomation(WorkflowStep):
    """
    The Actions workflow completing finding labels picked on GitHub, written into a
    checkout, to reach its default branch through a pull request.
    """

    root: Path
    """
    The checkout's root.
    """

    def run(self) -> str:
        workflow = TemplatePlaceholder.fill(
            WorkflowTemplate.LABEL_COMPLETION_WORKFLOW.read_text(),
            ActionRequirement.placeholder_values(__name__),
        )
        path = self.root / ProjectFile.LABEL_COMPLETION_WORKFLOW.value
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(workflow)
        return (
            f"wrote {ProjectFile.LABEL_COMPLETION_WORKFLOW.value}; commit it on a work "
            f"branch and open a draft, GitHub runs it once it is on the default branch"
        )


# %% entry point


def main() -> None:
    """
    Complete the label the event file on the command line reports added.
    """
    parser = argparse.ArgumentParser(description=__doc__.strip().splitlines()[0])
    parser.add_argument("event", type=Path, help="the issues event GitHub handed over")
    event = IssueLabelled.from_json(json.loads(parser.parse_args().event.read_text()))
    github = GitHubRepository.from_environment(event.repository)
    print(FindingLabelCompletion(github, github, event.number, event.label).run())


if __name__ == "__main__":
    main()
