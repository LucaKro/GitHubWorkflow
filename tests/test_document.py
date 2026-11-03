"""
Tests for :mod:`github_workflow.notes.document`: the notes block in ``CLAUDE.local.md``.
"""

from __future__ import annotations

from github_workflow.command_line import FindingSubcommand, WorkflowCommand
from github_workflow.notes.document import NotesBlock, NotesSection
from github_workflow.policy import Attribution

# %% helpers


def block(branch: str = "feature") -> NotesBlock:
    """
    :param branch: The checked-out branch, empty for a detached ``HEAD``.
    :return: A block with text in every section.
    """
    return NotesBlock(
        source="an-owner/a-repository, branch notes",
        save_command="save",
        workflow_command="workflow",
        finding_guide="guide",
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


# %% the rules the header states


def test_the_header_names_every_command_a_finding_is_proven_and_worked_on_with():
    rendered = block().render()

    finding = f"workflow {WorkflowCommand.FINDING}"
    named = [
        f"`{finding} {FindingSubcommand.FILE}`",
        f"`{finding} {FindingSubcommand.PROVE}`",
        f"`{finding} {FindingSubcommand.MARK_UNPROVEN}`",
        f"`{finding} {FindingSubcommand.RECHECK}`",
        f"`workflow {WorkflowCommand.DRAFT} --finding`",
    ]
    assert [command for command in named if command not in rendered] == []


def test_the_header_names_the_credit_a_commit_refuses_and_the_line_it_carries():
    """
    A session that does not know the commit command refuses an assistant's co-author
    trailer adds one, is refused, and tries again.
    """
    rendered = block().render()

    assert f"`{Attribution.CO_AUTHOR_TRAILER}`" in rendered
    assert f'"{Attribution.ACKNOWLEDGEMENT}"' in rendered
