"""
Tests for :mod:`github_workflow.markers`: the comments the workflow hides in Markdown
read back what they record.
"""

from __future__ import annotations

from github_workflow.markers import CommentDelimiter, MarkedPart, WorkflowMarker

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


# %% a part between two markers


def test_a_marked_part_reads_back_what_it_wraps() -> None:
    part = MarkedPart("why")

    assert part.read(f"before\n\n{part.wrap('The reason.')}\n\nafter") == "The reason."


def test_text_without_the_part_holds_none() -> None:
    assert MarkedPart("why").read(MarkedPart("changes").wrap("x")) is None


def test_removing_a_part_keeps_the_text_around_it() -> None:
    part = MarkedPart("why")

    assert part.remove(f"before\n\n{part.wrap('The reason.')}\n\nafter") == (
        "before\n\nafter"
    )


def test_removing_a_part_from_text_without_it_changes_nothing() -> None:
    assert MarkedPart("why").remove("text") == "text"
