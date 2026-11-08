"""
Tests for :mod:`github_workflow.report`: each section of the session start is built by
its own class.
"""

from __future__ import annotations

import pytest

from github_workflow.report import SectionBuilder, SectionName

# %% finding a section's builder


@pytest.mark.parametrize("name", list(SectionName))
def test_every_section_has_the_class_building_it(name: SectionName) -> None:
    assert SectionBuilder.building(name).section_name is name
