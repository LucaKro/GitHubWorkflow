"""
Tests for :mod:`github_workflow.report_section`: lines about things of one kind are
shown under a heading.
"""

from __future__ import annotations

from github_workflow.report_lines import Emphasis, Highlight, ReportLine, Speaker, Tone
from github_workflow.report_section import ReportGroup

# %% a group of lines


def test_a_group_is_its_heading_followed_by_its_items_indented() -> None:
    group = ReportGroup("drafts", [ReportLine("#1 One", Tone.NEWS)])

    assert group.lines() == [
        ReportLine(
            Speaker.WORKFLOW.says("drafts:"),
            Tone.NEWS,
            emphases=(Emphasis(Speaker.WORKFLOW.says("drafts:"), Highlight.HEADING),),
        ),
        ReportLine("  #1 One", Tone.NEWS),
    ]


def test_a_group_with_an_item_asking_for_attention_has_its_heading_ask_too() -> None:
    items = [ReportLine("#1 One", Tone.NEWS), ReportLine("#2 Two", Tone.ACTION)]

    [heading, *_] = ReportGroup("drafts", items).lines()

    assert heading.tone is Tone.ACTION


def test_an_empty_group_says_nothing() -> None:
    assert ReportGroup("drafts", []).lines() == []


def test_a_heading_is_shown_in_the_heading_s_style() -> None:
    [heading, _] = ReportGroup("drafts", [ReportLine("#1 One", Tone.NEWS)]).lines()

    assert f"\033[0;{Highlight.HEADING}m{heading.text}" in heading.shown
