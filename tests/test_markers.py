"""
Tests for :mod:`github_workflow.markers`: the comments the workflow hides in Markdown
read back what they record.
"""

from __future__ import annotations

from github_workflow.markers import CommentDelimiter, WorkflowSection, WorkflowMarker

# %% reading a marker back


def test_a_marker_reads_back_the_value_it_records() -> None:
    marker = WorkflowMarker("proof")

    assert marker.read(f"before {marker.line('{"a": 1}')} after") == '{"a": 1}'


def test_a_marker_recording_nothing_is_one_comment_without_a_value() -> None:
    marker = WorkflowMarker("start")

    assert marker.line() == (
        f"{CommentDelimiter.OPEN}{marker.namespace}:{marker.subject}"
        f"{CommentDelimiter.CLOSE}"
    )


def test_text_without_the_marker_records_nothing() -> None:
    assert WorkflowMarker("proof").read(WorkflowMarker("branch").line("x")) is None


# %% a section between two markers


def test_a_workflow_section_finds_the_content_it_encloses() -> None:
    section = WorkflowSection("why")

    text = f"before\n\n{section.enclose('The reason.')}\n\nafter"

    assert section.find_content(text) == "The reason."


def test_text_without_the_section_holds_no_content() -> None:
    other = WorkflowSection("changes").enclose("x")

    assert WorkflowSection("why").find_content(other) is None


def test_cutting_out_a_section_keeps_the_text_around_it() -> None:
    section = WorkflowSection("why")

    text = f"before\n\n{section.enclose('The reason.')}\n\nafter"

    assert section.cut_out(text) == "before\n\nafter"


def test_cutting_out_a_section_from_text_without_it_changes_nothing() -> None:
    assert WorkflowSection("why").cut_out("text") == "text"
