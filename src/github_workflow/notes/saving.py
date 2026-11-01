"""
Saving the notes block of ``CLAUDE.local.md`` back to the notes branch.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

import github_workflow.notes
from github_workflow.checkout import ProjectCheckout
from github_workflow.exceptions import NotesBlockMissingError
from github_workflow.locations import NotesFile
from github_workflow.notes.branch import NotesBranch
from github_workflow.notes.document import NotesBlock, NotesSection

# %% the commands


class NotesCommand(StrEnum):
    """
    What ``python -m github_workflow.notes`` does.
    """

    SAVE = "save"
    """
    Push the edited notes block to the notes branch.
    """

    @property
    def command_line(self) -> str:
        """:return: The command, with the interpreter the package runs in."""
        return f"{sys.executable} -m {github_workflow.notes.__name__} {self}"


# %% saving


@dataclass(frozen=True)
class NotesSave:
    """
    One save of the notes block.
    """

    checkout: ProjectCheckout
    """
    The checkout whose ``CLAUDE.local.md`` is saved.
    """

    notes: NotesBranch
    """
    The branch it is saved to.
    """

    def files(self) -> dict[Path, str]:
        """
        :return: Each file the block's sections are saved to, with the section's text.
        :raises NotesBlockMissingError: If ``CLAUDE.local.md`` holds no block.
        """
        document = (
            self.checkout.claude_local.read_text()
            if self.checkout.claude_local.exists()
            else ""
        )
        if not NotesBlock.holds_block(document):
            raise NotesBlockMissingError(str(self.checkout.claude_local))
        sections = NotesBlock.read_sections(document)
        files = {
            NotesFile.STANDING_NOTES.value: sections.get(
                NotesSection.STANDING_NOTES, ""
            )
        }
        branch = self.checkout.git.checked_out_branch()
        if branch and NotesSection.BRANCH_PROGRESS in sections:
            files[NotesFile.progress_of(branch)] = sections[
                NotesSection.BRANCH_PROGRESS
            ]
        return files

    def run(self) -> list[Path]:
        """
        Push every file whose text differs from the branch's.

        :return: The files saved, empty when nothing changed.
        """
        files = self.files()
        branch = self.checkout.git.checked_out_branch()
        self.notes.fetch()
        changed = {
            path: f"{text}\n"
            for path, text in files.items()
            if (self.notes.read(path) or "") != text
        }
        if changed:
            self.notes.write(changed, f"Save notes from {branch or 'a detached HEAD'}")
        return list(changed)
