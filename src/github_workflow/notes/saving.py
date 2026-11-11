"""
Saving the notes block of ``CLAUDE.local.md`` back to the notes branch.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from github_workflow.checkout import ProjectCheckout
from github_workflow.locations import NotesFile
from github_workflow.notes.branch import NotesBranch
from github_workflow.notes.document import BlockRecord, NotesBlock, NotesSection
from github_workflow.notes.exceptions import NotesBlockMissingError

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

    @property
    def progress_branch(self) -> str:
        """
        The branch the block's progress belongs to: the one it was loaded for, or the
        checked-out one for a block that does not record it; empty for none.
        """
        recorded = BlockRecord.BRANCH.read(self.checkout.claude_local_text)
        if recorded is None:
            return self.checkout.checked_out_branch_name
        return recorded

    def files(self) -> dict[Path, str]:
        """
        :return: Each file the block's sections are saved to, with the section's text.
        :raises NotesBlockMissingError: If ``CLAUDE.local.md`` holds no block.
        """
        document = self.checkout.claude_local_text
        if not NotesBlock.holds_block(document):
            raise NotesBlockMissingError(str(self.checkout.claude_local))
        sections = NotesBlock.read_sections(document)
        files = {
            NotesFile.STANDING_NOTES: sections.get(NotesSection.STANDING_NOTES, "")
        }
        branch = self.progress_branch
        if branch and NotesSection.BRANCH_PROGRESS in sections:
            files[NotesFile.progress_file(branch)] = sections[
                NotesSection.BRANCH_PROGRESS
            ]
        return files

    def run(self) -> list[Path]:
        """
        Push every file whose text differs from the branch's, and record the block as
        saved.

        :return: The files saved, empty when nothing changed.
        """
        files = self.files()
        branch = self.checkout.checked_out_branch_name
        self.notes.fetch()
        changed = {
            path: f"{text}\n"
            for path, text in files.items()
            if (self.notes.read(path) or "").strip() != text
        }
        if changed:
            self.notes.write(changed, f"Save notes from {branch or 'a detached HEAD'}")
        self.checkout.claude_local.write_text(
            NotesBlock.marked_saved(self.checkout.claude_local_text)
        )
        return list(changed)
