"""
Tests for :mod:`github_workflow.notes.document`: the notes block in ``CLAUDE.local.md``.
"""

from __future__ import annotations

from github_workflow.notes.document import NotesBlock, NotesSection

# %% helpers


def block(branch: str = "feature") -> NotesBlock:
    """
    :param branch: The checked-out branch, empty for a detached ``HEAD``.
    :return: A block with text in every section.
    """
    return NotesBlock(
        source="an-owner/a-repository, branch notes",
        save_command="save",
        branch=branch,
        sections={section: f"text of {section}" for section in NotesSection},
    )


# %% writing and reading back


def test_the_sections_read_back_as_they_were_written():
    written = block()

    assert NotesBlock.read_sections(written.render()) == written.sections


def test_text_outside_the_block_survives_rewriting_it():
    before, after = "my own line above\n", "\nmy own line below\n"
    document = before + block().render() + after

    rewritten = block().written_into(document)

    assert rewritten.startswith(before) and rewritten.endswith(after)


def test_a_detached_head_has_no_progress_section():
    assert NotesSection.BRANCH_PROGRESS not in NotesBlock.read_sections(
        block(branch="").render()
    )
