"""
The notes block in ``CLAUDE.local.md``: written at session start, read back on save, and
never touching anything outside its markers.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

# %% markers


class BlockMarker(StrEnum):
    """
    The lines that open and close the whole block.
    """

    START = "<!-- github-workflow:start -->"
    END = "<!-- github-workflow:end -->"


class NotesSection(StrEnum):
    """
    The sections of the block, each saved to a file of its own, each titled by its
    value.
    """

    STANDING_NOTES = "Standing notes"
    """
    The notes every session on the repository starts with.
    """

    BRANCH_PROGRESS = "Progress on this branch"
    """
    Plan, progress and next steps for the checked-out branch.
    """

    @property
    def start_marker(self) -> str:
        """:return: The line the section's editable text starts after."""
        return f"<!-- github-workflow:{self._name_.lower()}:start -->"

    @property
    def end_marker(self) -> str:
        """:return: The line the section's editable text ends before."""
        return f"<!-- github-workflow:{self._name_.lower()}:end -->"


# %% the block


@dataclass(frozen=True)
class NotesBlock:
    """
    What a session starts with, as one block of ``CLAUDE.local.md``.
    """

    source: str
    """
    Where the notes were read from, as the header names it.
    """

    save_command: str
    """
    The command that saves edits to the block, as the header gives it.
    """

    branch: str
    """
    The checked-out branch, empty on a detached ``HEAD``, which has no progress section.
    """

    sections: dict[NotesSection, str]
    """
    The text of each section.
    """

    def render(self) -> str:
        """:return: The block, markers included."""
        lines = [
            BlockMarker.START,
            "# GitHub workflow notes",
            "",
            f"Read from {self.source}. Edit only between a section's markers, then save "
            f"with `{self.save_command}`.",
        ]
        for section in NotesSection:
            if section is NotesSection.BRANCH_PROGRESS and not self.branch:
                continue
            title = (
                f"{section} ({self.branch})"
                if section is NotesSection.BRANCH_PROGRESS
                else section
            )
            lines += [
                "",
                f"## {title}",
                section.start_marker,
                self.sections.get(section, ""),
                section.end_marker,
            ]
        lines.append(BlockMarker.END)
        return "\n".join(lines) + "\n"

    def written_into(self, document: str) -> str:
        """
        :param document: ``CLAUDE.local.md`` as it is now, empty when it does not exist.
        :return: It with this block in place of the old one, or appended when it holds
            none; everything outside the block unchanged.
        """
        start = document.find(BlockMarker.START)
        end = document.find(BlockMarker.END)
        if start == -1 or end == -1:
            separator = "\n" if document.strip() else ""
            return (
                document.rstrip("\n")
                + separator
                + ("\n" if separator else "")
                + self.render()
            )
        after = document[end + len(BlockMarker.END) :].removeprefix("\n")
        return document[:start] + self.render() + after

    @staticmethod
    def holds_block(document: str) -> bool:
        """
        :param document: ``CLAUDE.local.md``'s text.
        :return: Whether it holds a notes block.
        """
        return BlockMarker.START in document and BlockMarker.END in document

    @staticmethod
    def read_sections(document: str) -> dict[NotesSection, str]:
        """
        :param document: ``CLAUDE.local.md``'s text.
        :return: The text between each section's markers, for every section it holds.
        """
        sections = {}
        for section in NotesSection:
            start = document.find(section.start_marker)
            end = document.find(section.end_marker)
            if start == -1 or end == -1:
                continue
            sections[section] = document[
                start + len(section.start_marker) : end
            ].strip()
        return sections
