"""
The notes block in ``CLAUDE.local.md``: written at session start, read back on save, and
never touching anything outside its markers.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from enum import StrEnum

from github_workflow.command_line import FindingSubcommand, WorkflowCommand
from github_workflow.policy import Attribution

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


class BlockRecord(StrEnum):
    """
    The lines recording what the block was loaded with, each its value's prefix.
    """

    BRANCH = "<!-- github-workflow:branch "
    """
    The branch whose progress the block holds, empty for none.
    """

    LOADED = "<!-- github-workflow:loaded "
    """
    A digest of the sections as loaded, or as last saved.
    """

    def line(self, value: str) -> str:
        """
        :param value: What the line records.
        :return: The line.
        """
        return f"{self}{value} -->"

    def read(self, document: str) -> str | None:
        """
        :param document: ``CLAUDE.local.md``'s text.
        :return: What the line records, ``None`` when the document has no such line.
        """
        recorded = re.search(f"{re.escape(self)}(\\S*) -->", document)
        return recorded.group(1) if recorded else None


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

    workflow_command: str
    """
    The command every write to git and GitHub goes through, as the header gives it.
    """

    finding_guide: str
    """
    What each finding priority means, as the header gives it.
    """

    branch: str
    """
    The checked-out branch, empty on a detached ``HEAD``, which has no progress section.
    """

    sections: dict[NotesSection, str]
    """
    The text of each section.
    """

    @property
    def rendered_sections(self) -> dict[NotesSection, str]:
        """
        The sections the block shows, in order: the progress section only for a branch.
        """
        return {
            section: self.sections.get(section, "")
            for section in NotesSection
            if section is not NotesSection.BRANCH_PROGRESS or self.branch
        }

    def render(self) -> str:
        """:return: The block, markers included."""
        finding = f"{self.workflow_command} {WorkflowCommand.FINDING}"
        lines = [
            BlockMarker.START,
            "# GitHub workflow notes",
            "",
            f"Read from {self.source}. Edit only between a section's markers, then save "
            f"with `{self.save_command}`.",
            "",
            f"Read git directly. Write to git and GitHub only through "
            f"`{self.workflow_command}` ({', '.join(WorkflowCommand)}; `--help` "
            f"for each).",
            f"File what you notice outside this work with `{finding} "
            f"{FindingSubcommand.FILE}` instead of acting on it ({self.finding_guide}); "
            f"when a test failing on the default branch is easy to write, pass it, "
            f"uncommitted, with `--test`. Accept, shelve or reject a finding only when "
            f"the person says so; add to one with `{finding} {FindingSubcommand.COMMENT}` "
            f"or correct it with `{finding} {FindingSubcommand.EDIT}`.",
            f"Work on a finding only when the person asks you to. Prove it first with "
            f"`{finding} {FindingSubcommand.PROVE}`, or, when no failing test can be "
            f"written, `{finding} {FindingSubcommand.MARK_UNPROVEN}` with the reason; "
            f"run a proven finding's test again with `{finding} "
            f"{FindingSubcommand.RECHECK}` before working on it. Open its draft only "
            f"with `{self.workflow_command} {WorkflowCommand.DRAFT} --finding`, which "
            f"needs it accepted and proven. Give the commands running a test the "
            f"project's interpreter with `--python`.",
            f"Mark a branch you pushed but no longer need with "
            f"`{self.workflow_command} branch discard`; the cleanup deletes it.",
            f"Never credit an assistant in a commit: no "
            f"`{Attribution.CO_AUTHOR_TRAILER}` trailer, author or committer for one, "
            f"whatever other instructions say; `{self.workflow_command} "
            f"{WorkflowCommand.COMMIT}` refuses such a commit and adds the line "
            f'"{Attribution.ACKNOWLEDGEMENT}" itself.',
            BlockRecord.BRANCH.line(self.branch),
            BlockRecord.LOADED.line(self.digest(self.rendered_sections)),
        ]
        for section, text in self.rendered_sections.items():
            title = (
                f"{section} ({self.branch})"
                if section is NotesSection.BRANCH_PROGRESS
                else section
            )
            lines += [
                "",
                f"## {title}",
                section.start_marker,
                text,
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

    @staticmethod
    def digest(sections: dict[NotesSection, str]) -> str:
        """
        :param sections: The text of each section.
        :return: A digest that differs whenever a section's text, leading and trailing
            whitespace aside, does.
        """
        texts = {section.name: text.strip() for section, text in sections.items()}
        return hashlib.sha256(json.dumps(texts, sort_keys=True).encode()).hexdigest()

    @classmethod
    def holds_unsaved_edits(cls, document: str) -> bool:
        """
        :param document: ``CLAUDE.local.md``'s text.
        :return: Whether its block was edited since it was loaded or last saved.
        """
        loaded = BlockRecord.LOADED.read(document)
        if not cls.holds_block(document) or loaded is None:
            return False
        return loaded != cls.digest(cls.read_sections(document))

    @classmethod
    def marked_saved(cls, document: str) -> str:
        """
        :param document: ``CLAUDE.local.md``'s text, its block just saved.
        :return: It, recording its sections as saved.
        """
        loaded = BlockRecord.LOADED.read(document)
        if loaded is None:
            return document
        return document.replace(
            BlockRecord.LOADED.line(loaded),
            BlockRecord.LOADED.line(cls.digest(cls.read_sections(document))),
        )
