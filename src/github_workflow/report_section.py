"""
One section of what a session starts with, computed from the owner's repository on
GitHub.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, replace

from github_workflow.hooks import Emphasis, Highlight, ReportLine, Speaker, Tone

# %% one section


class ReportSection(ABC):
    """
    One part of the session start that reads, and may set up, the repository on GitHub.
    """

    @abstractmethod
    def lines(self) -> list[ReportLine]:
        """
        :return: What the session should know, empty when there is nothing to say.
        """


# %% a group of lines


@dataclass(frozen=True)
class ReportGroup:
    """
    Lines about things of one kind, under a heading that says what they are.
    """

    heading: str
    """
    What the things are, such as ``draft pull requests``.
    """

    items: list[ReportLine]
    """
    One line per thing, without the workflow's prefix.
    """

    def lines(self) -> list[ReportLine]:
        """
        :return: The heading, in the heading's style and the tone of the most pressing
            item, followed by the items indented; nothing when there are no items.
        """
        if not self.items:
            return []
        pressing = any(item.tone is Tone.ACTION for item in self.items)
        text = Speaker.WORKFLOW.says(f"{self.heading}:")
        heading = ReportLine(
            text,
            Tone.ACTION if pressing else Tone.NEWS,
            emphases=(Emphasis(text, Highlight.HEADING),),
        )
        return [heading] + [replace(item, text=f"  {item.text}") for item in self.items]
