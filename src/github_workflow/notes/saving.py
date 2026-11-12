"""
Saving the notes block of ``CLAUDE.local.md`` back to the notes branch.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from domain_model.git.revisions import BranchName, TextFiles

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
    def progress_branch(self) -> BranchName | None:
        """
        The branch the block's progress belongs to: the one it was loaded for, or the
        checked-out one for a block that does not record it; ``None`` for none.
        """
        recorded = BlockRecord.BRANCH.read(self.checkout.claude_local_text)
        if recorded is not None:
            return BranchName(recorded) if recorded else None
        checked_out = self.checkout.working_tree.checked_out_branch()
        return None if checked_out is None else checked_out.name

    def files(self) -> TextFiles:
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
        return TextFiles(files)

    def run(self) -> list[Path]:
        """
        Push every file whose text differs from the branch's, and record the block as
        saved.

        :return: The files saved, empty when nothing changed.
        """
        files = self.files()
        checked_out = self.checkout.working_tree.checked_out_branch()
        self.notes.fetch()
        changed = TextFiles(
            {
                path: f"{text}\n"
                for path, text in files.texts.items()
                if (self.notes.read(path) or "").strip() != text
            }
        )
        if changed.texts:
            source = "a detached HEAD" if checked_out is None else checked_out.name
            self.notes.write(changed, f"Save notes from {source}")
        self.checkout.claude_local.write_text(
            NotesBlock.marked_saved(self.checkout.claude_local_text)
        )
        return changed.paths
