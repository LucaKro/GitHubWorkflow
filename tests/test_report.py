"""
Tests for :mod:`github_workflow.report`: each section of the session start is built by
its own class.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from github_workflow.report import SectionBuilder, SectionName
from github_workflow.session import WorkflowSession
from github_workflow.settings import WorkflowSettings

# %% finding a section's builder


@pytest.mark.parametrize("name", list(SectionName))
def test_every_section_has_the_class_building_it(
    name: SectionName, tmp_path: Path, settings: WorkflowSettings
) -> None:
    builder = SectionBuilder.from_section_name(
        WorkflowSession(tmp_path, settings), name
    )

    assert builder.section_name is name
