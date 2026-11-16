"""
A pull request's description as the workflow writes it: why the pull request matters,
from the findings it works on, first; what it changes, folded away, after; and the lines
naming the issues it addresses last, which only the workflow writes.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass, field, replace

from domain_model.class_property import classproperty
from domain_model.github.closing_lines import ClosingLines
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
from github_workflow.markers import MarkedPart
from github_workflow.why_it_matters import WhyItMatters

# %% the issues a pull request addresses


@dataclass(frozen=True)
class AddressedIssues:
    """
    The issues of its repository a pull request addresses: those it fixes, closed when
    it is merged, and those it fixes only in part.
    """

    fixed: tuple[int, ...] = ()
    """
    The issues it fixes.
    """

    partly: tuple[int, ...] = ()
    """
    The issues it fixes in part.
    """

    @classproperty
    def partial_fix_words(cls) -> str:
        """
        The words a description writes before an issue the pull request fixes in part.
        """
        return "Part of"

    @classmethod
    def from_description(cls, description: str) -> AddressedIssues:
        """
        :param description: A pull request's description.
        :return: The issues its lines name.
        """
        partial = re.compile(rf"{re.escape(cls.partial_fix_words)} #(\d+)")
        stripped = (line.strip() for line in description.splitlines())
        partly = [
            int(found.group(1))
            for found in map(partial.fullmatch, stripped)
            if found is not None
        ]
        return cls(tuple(ClosingLines(description).issues()), tuple(partly))

    @property
    def numbers(self) -> tuple[int, ...]:
        """:return: Every issue addressed, the fixed ones first."""
        return self.fixed + self.partly

    def lines(self) -> list[str]:
        """:return: The lines naming the issues, as a description ends with them."""
        return [ClosingKeyword.FIXES.reference(number) for number in self.fixed] + [
            f"{self.partial_fix_words} #{number}" for number in self.partly
        ]

    def remove_lines(self, description: str) -> str:
        """
        :param description: A pull request's description.
        :return: It without the lines naming these issues.
        """
        named = set(self.lines())
        kept = [line for line in description.splitlines() if line.strip() not in named]
        return "\n".join(kept)

    def changed(
        self,
        fixed: Sequence[int],
        partly: Sequence[int],
        dropped: Sequence[int],
    ) -> AddressedIssues:
        """
        :param fixed: Issues it now fixes, moved there when it fixed them in part.
        :param partly: Issues it now fixes in part, moved there when it fixed them.
        :param dropped: Issues it no longer addresses.
        :return: The issues it addresses then.
        :raises IssueNamedTwiceError: If an issue is named in more than one of them.
        """
        named = [*fixed, *partly, *dropped]
        twice = sorted({number for number in named if named.count(number) > 1})
        if twice:
            raise IssueNamedTwiceError(tuple(twice))
        kept_fixed = [n for n in self.fixed if n not in partly and n not in dropped]
        kept_partly = [n for n in self.partly if n not in fixed and n not in dropped]
        return AddressedIssues(
            tuple(kept_fixed + [n for n in fixed if n not in kept_fixed]),
            tuple(kept_partly + [n for n in partly if n not in kept_partly]),
        )

    @classmethod
    def refuse_lines(cls, text: str | None, argument: CommandOption) -> str | None:
        """
        :param text: Text a session gives for a pull request's description.
        :param argument: The argument giving it.
        :return: The text.
        :raises AddressedIssueLineError: If it holds a line naming an issue the pull
            request addresses, which only the workflow writes.
        """
        if text is not None and cls.from_description(text).numbers:
            raise AddressedIssueLineError(argument)
        return text


# %% the description


@dataclass(frozen=True)
class PullRequestDescription:
    """
    A pull request's description: why it matters, the session's own words and each
    addressed finding's why; what it changes, as the session describes it; and the
    issues it addresses.
    """

    changes: str
    """
    What the pull request changes, as Markdown: the changes, the tests and what breaks.
    """

    why: str = ""
    """
    Why it matters in the session's own words, empty when only its findings say so.
    """

    addressed: AddressedIssues = field(default_factory=AddressedIssues)
    """
    The issues it addresses.
    """

    @classproperty
    def content(cls) -> MarkedPart:
        """
        The part holding everything but the lines naming the addressed issues.
        """
        return MarkedPart("description")

    @classproperty
    def own_why(cls) -> MarkedPart:
        """
        The part holding the session's own why.
        """
        return MarkedPart("pull-request-why")

    @classproperty
    def changes_part(cls) -> MarkedPart:
        """
        The part holding what the pull request changes.
        """
        return MarkedPart("changes")

    @classproperty
    def changes_summary(cls) -> str:
        """
        The line a reader opens to see what the pull request changes.
        """
        return "What changes, how it is tested, and what breaks"

    @classmethod
    def from_text(cls, text: str) -> PullRequestDescription:
        """
        :param text: A pull request's description.
        :return: What it holds; one the workflow did not write is all changes, its
            lines naming issues aside.
        """
        addressed = AddressedIssues.from_description(text)
        changes = cls.changes_part.read(text)
        if changes is None:
            return cls(addressed.remove_lines(text).strip(), addressed=addressed)
        return cls(changes, cls.own_why.read(text) or "", addressed)

    def render(self, issues: IssueBoard, repository: Repository) -> str:
        """
        :param issues: The issues of the pull request's repository.
        :param repository: That repository, which bare issue numbers name.
        :return: The description, every issue number naming the repository.
        :raises MissingWhyError: If neither the session nor an addressed issue says why
            it matters.
        """
        whys = [] if not self.why else [self.own_why.wrap(self.why)]
        whys += [
            self.issue_section(issues, repository, number, in_part=False)
            for number in self.addressed.fixed
        ]
        whys += [
            self.issue_section(issues, repository, number, in_part=True)
            for number in self.addressed.partly
        ]
        if not whys:
            raise MissingWhyError()
        changes = (
            f"<details>\n<summary>{self.changes_summary}</summary>\n\n"
            f"{self.changes_part.wrap(self.changes)}\n\n</details>"
        )
        content = "\n\n".join([WhyItMatters.heading, *whys, changes])
        qualified = IssueReferences(self.content.wrap(content)).qualify(repository)
        lines = "\n".join(self.addressed.lines())
        return f"{qualified}\n\n{lines}\n" if lines else f"{qualified}\n"

    @staticmethod
    def issue_section(
        issues: IssueBoard, repository: Repository, number: int, in_part: bool
    ) -> str:
        """
        :param issues: The issues of the pull request's repository.
        :param repository: That repository.
        :param number: An issue the pull request addresses.
        :param in_part: Whether it fixes the issue only in part.
        :return: The issue's title, linking its page, over its why, when it has one.
        """
        issue = issues.issue(number)
        link = f"[{repository.full_name}#{number}]({repository.issue_url(number)})"
        partly = "Partly: " if in_part else ""
        heading = f"### {partly}{issue.title} ({link})"
        why = WhyItMatters.read(issue.body)
        return heading if why is None else f"{heading}\n\n{why.text}"

    def changed(self, change: DescriptionChange) -> PullRequestDescription:
        """
        :param change: What a session changes.
        :return: The description with it.
        :raises IssueNamedTwiceError: If an issue is named twice in the change.
        """
        return replace(
            self,
            changes=self.changes if change.changes is None else change.changes,
            why=self.why if change.why is None else change.why,
            addressed=self.addressed.changed(
                change.fixed, change.partly, change.dropped
            ),
        )


@dataclass(frozen=True)
class DescriptionChange:
    """
    What a session changes in a pull request's description; whatever it leaves out stays
    as it is.
    """

    changes: str | None = None
    """
    What the pull request now changes, ``None`` to keep it.
    """

    why: str | None = None
    """
    The session's own why, ``None`` to keep it.
    """

    fixed: tuple[int, ...] = ()
    """
    Issues the pull request now fixes.
    """

    partly: tuple[int, ...] = ()
    """
    Issues it now fixes in part.
    """

    dropped: tuple[int, ...] = ()
    """
    Issues it no longer addresses.
    """

    @property
    def changes_nothing(self) -> bool:
        """:return: Whether it leaves the whole description as it is."""
        return self == DescriptionChange()

    @property
    def added(self) -> AddressedIssues:
        """:return: The issues it names as newly addressed."""
        return AddressedIssues(self.fixed, self.partly)
