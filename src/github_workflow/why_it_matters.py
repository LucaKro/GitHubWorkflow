"""
Why a finding or a pull request matters, in a few sentences, kept where the workflow can
copy it word for word.
"""

from __future__ import annotations

from dataclasses import dataclass

from domain_model.class_property import classproperty

from github_workflow.exceptions import EmptyWhyError, WhyTooLongError
from github_workflow.markers import WorkflowSection

# %% the why


@dataclass(frozen=True)
class WhyItMattersSection:
    """
    The section of a finding's or a pull request's text saying why it matters: who runs
    into the problem and what it costs them, under a heading of its own, so that a pull
    request working on the finding can copy it word for word.
    """

    explanation: str
    """
    Why it matters, as Markdown.
    """

    @classproperty
    def maximum_explanation_length(cls) -> int:
        """
        How many characters an explanation given to the workflow may hold.
        """
        return 600

    @classproperty
    def workflow_section(cls) -> WorkflowSection:
        """
        The comments the section stands between.
        """
        return WorkflowSection("why")

    @classproperty
    def heading(cls) -> str:
        """
        The heading the explanation stands under.
        """
        return "## Why"

    @classmethod
    def from_text(cls, text: str) -> WhyItMattersSection:
        """
        :param text: An explanation given to the workflow.
        :return: The section holding it.
        :raises EmptyWhyError: If it holds no text.
        :raises WhyTooLongError: If it is longer than
            :attr:`maximum_explanation_length`.
        """
        stripped = text.strip()
        if not stripped:
            raise EmptyWhyError()
        if len(stripped) > cls.maximum_explanation_length:
            raise WhyTooLongError(len(stripped), cls.maximum_explanation_length)
        return cls(stripped)

    @classmethod
    def from_issue_text(cls, body: str) -> WhyItMattersSection | None:
        """
        :param body: An issue's text.
        :return: The section it holds, ``None`` when it holds none.
        """
        content = cls.workflow_section.find_content(body)
        if content is None:
            return None
        return cls(content.removeprefix(cls.heading).strip())

    def place_into_issue_text(self, body: str) -> str:
        """
        :param body: An issue's text, which may hold such a section already.
        :return: The text with this section after it, in place of the one it held.
        """
        rest = self.workflow_section.cut_out(body).rstrip()
        section = self.workflow_section.enclose(f"{self.heading}\n\n{self.explanation}")
        return f"{rest}\n\n{section}\n" if rest else f"{section}\n"
