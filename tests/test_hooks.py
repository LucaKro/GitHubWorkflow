"""
Tests for :mod:`github_workflow.report_lines`: the session start's lines stand out to
the person in their tone's colour and reach the model plain.
"""

from __future__ import annotations

import json

import pytest

from basstler_domain_model.claude_code.hooks import HookKey
from github_workflow.report_lines import ReportLine, SessionStartReport, Tone

# %% one line


@pytest.mark.parametrize("tone", list(Tone))
def test_a_line_is_shown_in_its_tone_s_colour(tone: Tone):
    line = ReportLine("github-workflow: something", tone)

    assert line.shown == f"\033[1;{tone}m{line.text}\033[0m"


@pytest.mark.parametrize("tone", list(Tone))
def test_a_line_handed_between_processes_arrives_unchanged(tone: Tone):
    line = ReportLine("github-workflow: something", tone)

    assert ReportLine.from_json(line.to_json()) == line


# %% the whole report


def test_the_model_gets_the_lines_without_colour():
    lines = [ReportLine("first", Tone.NEWS), ReportLine("second", Tone.ACTION)]

    answer = json.loads(SessionStartReport(lines).to_json())

    assert answer[HookKey.SYSTEM_MESSAGE] == "\n".join(line.shown for line in lines)
    context = answer[HookKey.HOOK_SPECIFIC_OUTPUT][HookKey.ADDITIONAL_CONTEXT]
    assert context == "\n".join(line.text for line in lines)
