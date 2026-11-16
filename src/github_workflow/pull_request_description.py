"""
A pull request's description as the workflow writes it: why the pull request matters,
from the findings it works on, first; what it changes, folded away, after; and the lines
naming the issues it addresses last, which only the workflow writes.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, replace
from enum import StrEnum

from domain_model.class_property import classproperty
from domain_model.github.issue_models import Issue
from domain_model.github.issue_references import IssueReferences
from domain_model.github.repository_client import IssueBoard
from domain_model.github.vocabulary import ClosingKeyword
from domain_model.repository import Repository

from github_workflow.command_line import CommandOption
from github_workflow.exceptions import (
    AddressedIssueLineError,
    IssueNamedTwiceError,
    MissingWhyError,
)
from github_workflow.markers import WorkflowSection
from github_workflow.why_it_matters import WhyItMattersSection

# %% the issues a pull request addresses


class IssueRelation(StrEnum):
    """
    How a pull request addresses an issue, each member's value the words its line in the
    description starts with.
    """

    FIXES = ClosingKeyword.FIXES.value
    """
    It fixes the issue, which GitHub closes when the pull request is merged.
    """

    FIXES_IN_PART = "Part of"
    """
    It fixes the issue only in part, so the issue stays open.
    """

    def write_reference_line(self, number: int) -> str:
        """
        :param number: An issue of the pull request's repository.
        :return: The line of the description naming it.
        """
        return f"{self} #{number}"


@dataclass(frozen=True)
class AddressedIssueNumber:
    """
    An issue a pull request addresses, by its number, as a description's lines and the
    command line name it.
    """

    number: int
    """
    The issue's number in the pull request's repository.
    """

    relation: IssueRelation
    """
    How the pull request addresses it.
    """

    @classmethod
    def from_description(cls, description: str) -> tuple[AddressedIssueNumber, ...]:
        """
        :param description: A pull request's description.
        :return: The issues its lines name, in their order.
        """
        relations = "|".join(re.escape(relation) for relation in IssueRelation)
        line = re.compile(rf"({relations}) #(\d+)")
        found = (line.fullmatch(text.strip()) for text in description.splitlines())
        return tuple(
            cls(int(match.group(2)), IssueRelation(match.group(1)))
            for match in found
            if match is not None
        )

    @classmethod
    def read_issue_numbers(cls, description: str) -> list[int]:
        """
        :param description: A pull request's description.
        :return: The numbers of the issues its lines name, in their order.
        """
        return [issue.number for issue in cls.from_description(description)]

    @classmethod
    def remove_reference_lines(cls, description: str) -> str:
        """
        :param description: A pull request's description.
        :return: It without the lines naming the issues it addresses.
        """
        named = {issue.reference_line for issue in cls.from_description(description)}
        kept = [text for text in description.splitlines() if text.strip() not in named]
        return "\n".join(kept)

    @classmethod
    def refuse_reference_lines(
        cls, text: str | None, argument: CommandOption
    ) -> str | None:
        """
        :param text: Text a session gives for a pull request's description.
        :param argument: The argument giving it.
        :return: The text.
        :raises AddressedIssueLineError: If it holds a line naming an issue the pull
            request addresses, which only the workflow writes.
        """
        if text is not None and cls.from_description(text):
            raise AddressedIssueLineError(argument)
        return text

    @property
    def reference_line(self) -> str:
        """:return: The line of the description naming the issue."""
        return self.relation.write_reference_line(self.number)

    def read_issue(self, issues: IssueBoard) -> AddressedIssue:
        """
        :param issues: The issues of the pull request's repository.
        :return: The issue, as GitHub has it now.
        """
        return AddressedIssue(issues.issue(self.number), self.relation)


@dataclass(frozen=True)
class AddressedIssue:
    """
    An issue a pull request addresses, as GitHub has it.
    """

    issue: Issue
    """
    The issue.
    """

    relation: IssueRelation
    """
    How the pull request addresses it.
    """

    @property
    def reference_line(self) -> str:
        """:return: The line of the description naming the issue."""
        return self.relation.write_reference_line(self.issue.number)

    def to_markdown(self, repository: Repository) -> str:
        """
        :param repository: The pull request's repository, which holds the issue.
        :return: The issue's title, linking its page, over why it matters, when the
            issue says so.
        """
        number = self.issue.number
        link = f"[{repository.full_name}#{number}]({repository.issue_url(number)})"
        partly = "Partly: " if self.relation is IssueRelation.FIXES_IN_PART else ""
        heading = f"### {partly}{self.issue.title} ({link})"
        why = WhyItMattersSection.from_issue_text(self.issue.body)
        return heading if why is None else f"{heading}\n\n{why.explanation}"


# %% the command line ending a description


@dataclass(frozen=True)
class PersonCommandEnding:
    """
    The end of a pull request's or issue's description giving the person a command line
    only they may run, for them to copy.
    """

    purpose: str
    """
    What the command does, as the sentence introducing it finishes ``To ...``.
    """

    command: str
    """
    The command line.
    """

    @property
    def markdown(self) -> str:
        """
        The ending itself.
        """
        return (
            f"---\n\n"
            f"To {self.purpose}, run this yourself (a Claude Code session may not):\n\n"
            f"```bash\n{self.command}\n```"
        )

    def remove_from_description(self, body: str) -> str:
        """
        :param body: A description, which may hold the ending.
        :return: The description without it.
        """
        return body.replace(self.markdown, "").rstrip()

    @classmethod
    def remove_command_endings(cls, body: str) -> str:
        """
        :param body: A description, which may hold such an ending.
        :return: The description without any ending of this form, whatever command it
            gives.
        """
        template = re.escape(cls("PURPOSE", "COMMAND").markdown)
        pattern = template.replace("PURPOSE", ".+?").replace("COMMAND", ".+?")
        return re.sub(pattern, "", body, flags=re.DOTALL).rstrip()

    def append_once(self, body: str) -> str:
        """
        :param body: A description, which may hold the ending already.
        :return: The description, ending with it once.
        """
        return f"{self.remove_from_description(body)}\n\n{self.markdown}\n"


# %% the description


@dataclass(frozen=True)
class PullRequestDescription:
    """
    A pull request's description: why it matters, the session's own words and each
    addressed finding's why; what it changes, as the session describes it; and the
    issues it addresses.
    """

    change_details: str
    """
    What the pull request changes, as Markdown: the changes, the tests and what breaks.
    """

    why_it_matters: str = ""
    """
    Why it matters in the session's own words, empty when only its findings say so.
    """

    addressed_issues: tuple[AddressedIssue, ...] = ()
    """
    The issues it addresses, in the order their lines are written.
    """

    @classproperty
    def copied_section(cls) -> WorkflowSection:
        """
        The section holding everything but the lines naming the addressed issues, which
        is what a copy elsewhere carries.
        """
        return WorkflowSection("description")

    @classproperty
    def why_it_matters_section(cls) -> WorkflowSection:
        """
        The section holding the session's own why.
        """
        return WorkflowSection("pull-request-why")

    @classproperty
    def change_details_section(cls) -> WorkflowSection:
        """
        The section holding what the pull request changes.
        """
        return WorkflowSection("changes")

    @classproperty
    def change_details_summary(cls) -> str:
        """
        The line a reader opens to see what the pull request changes.
        """
        return "What changes, how it is tested, and what breaks"

    @classmethod
    def read_change_details(cls, text: str) -> str:
        """
        :param text: A pull request's description.
        :return: What it says the pull request changes; of one the workflow did not
            write, its whole text but the lines naming issues and the command line for
            the person.
        """
        details = cls.change_details_section.find_content(text)
        if details is not None:
            return details
        without_lines = AddressedIssueNumber.remove_reference_lines(text)
        return PersonCommandEnding.remove_command_endings(without_lines).strip()

    @classmethod
    def from_text(cls, text: str, issues: IssueBoard) -> PullRequestDescription:
        """
        :param text: A pull request's description.
        :param issues: The issues of the pull request's repository.
        :return: What it holds, its addressed issues read as GitHub has them now.
        """
        return cls(
            cls.read_change_details(text),
            cls.why_it_matters_section.find_content(text) or "",
            tuple(
                number.read_issue(issues)
                for number in AddressedIssueNumber.from_description(text)
            ),
        )

    def to_markdown(self, repository: Repository) -> str:
        """
        :param repository: The pull request's repository, which bare issue numbers
            name.
        :return: The description, every issue number naming the repository.
        :raises MissingWhyError: If neither the session nor an addressed issue says why
            it matters.
        """
        whys = (
            [self.why_it_matters_section.enclose(self.why_it_matters)]
            if self.why_it_matters
            else []
        )
        whys += [issue.to_markdown(repository) for issue in self.addressed_issues]
        if not whys:
            raise MissingWhyError()
        details = (
            f"<details>\n<summary>{self.change_details_summary}</summary>\n\n"
            f"{self.change_details_section.enclose(self.change_details)}\n\n"
            "</details>"
        )
        content = "\n\n".join([WhyItMattersSection.heading, *whys, details])
        copied = self.copied_section.enclose(content)
        qualified = IssueReferences(copied).qualify(repository)
        lines = "\n".join(issue.reference_line for issue in self.addressed_issues)
        return f"{qualified}\n\n{lines}\n" if lines else f"{qualified}\n"

    def apply_change(
        self, change: DescriptionChange, issues: IssueBoard
    ) -> PullRequestDescription:
        """
        :param change: What a session changes.
        :param issues: The issues of the pull request's repository.
        :return: The description with the change, each issue it newly addresses read
            as GitHub has it now; an issue named again moves to its new relation.
        :raises IssueNamedTwiceError: If the change names an issue twice.
        """
        named = [issue.number for issue in change.added_issues]
        named += change.dropped_issues
        twice = sorted({number for number in named if named.count(number) > 1})
        if twice:
            raise IssueNamedTwiceError(tuple(twice))
        kept = tuple(
            issue for issue in self.addressed_issues if issue.issue.number not in named
        )
        added = tuple(number.read_issue(issues) for number in change.added_issues)
        return replace(
            self,
            change_details=(
                self.change_details
                if change.change_details is None
                else change.change_details
            ),
            why_it_matters=(
                self.why_it_matters
                if change.why_it_matters is None
                else change.why_it_matters
            ),
            addressed_issues=kept + added,
        )


@dataclass(frozen=True)
class DescriptionChange:
    """
    What a session changes in a pull request's description; whatever it leaves out stays
    as it is.
    """

    change_details: str | None = None
    """
    What the pull request now changes, ``None`` to keep it.
    """

    why_it_matters: str | None = None
    """
    The session's own why, ``None`` to keep it.
    """

    added_issues: tuple[AddressedIssueNumber, ...] = ()
    """
    Issues the pull request now addresses, or addresses in another way than before.
    """

    dropped_issues: tuple[int, ...] = ()
    """
    The numbers of the issues it no longer addresses.
    """

    @property
    def is_empty(self) -> bool:
        """:return: Whether it leaves the whole description as it is."""
        return self == DescriptionChange()
