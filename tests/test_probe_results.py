"""
Tests for :mod:`github_workflow.probe.results`: what a probe run records and writes.
"""

from __future__ import annotations

import json

from github_workflow.probe.results import CheckGroup, ProbeReport

# %% recording


def test_recording_hands_back_whether_the_check_succeeded():
    report = ProbeReport({})

    assert report.record(CheckGroup.GIT, "push", False, "refused", 0.1) is False


# %% writing


def test_the_report_has_a_section_only_for_groups_that_ran():
    report = ProbeReport({})
    report.record(CheckGroup.GIT, "push", True, "pushed", 0.1)

    markdown = report.markdown()

    assert f"## {CheckGroup.GIT}" in markdown
    assert f"## {CheckGroup.SIGNALS}" not in markdown


def test_the_results_hold_every_outcome():
    report = ProbeReport({})
    report.record(CheckGroup.GIT, "push", True, "pushed", 0.1)

    assert len(json.loads(report.to_json())["outcomes"]) == len(report.outcomes)
