"""
The architecture diagrams of projects drawn into their READMEs or checked, and the
workflow's own README kept equal to what its source draws.
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from domain_model.architecture.readme import ArchitectureReadme

from github_workflow.architecture import ArchitectureDrawing, DrawingStatus
from github_workflow.locations import PackageLocation

# %% a project whose README is out of date


@pytest.fixture
def stale_project(tmp_path: Path) -> Path:
    """
    :return: A copy of a project whose README holds a diagram drawn from an older
        source.
    """
    source = Path(__file__).parent / "dataset" / "architecture" / "stale_project"
    project = tmp_path / source.name
    shutil.copytree(source, project)
    return project


# %% checking and drawing


def test_check_reports_an_outdated_readme_without_writing_it(stale_project: Path):
    """
    Checking reports a README that no longer matches its source, and leaves it as it is.
    """
    readme = ArchitectureReadme.from_project(stale_project)
    before = readme.path.read_text()

    status = ArchitectureDrawing(projects=[stale_project], check_only=True).run()

    assert (status, readme.path.read_text()) == (DrawingStatus.OUTDATED, before)


def test_drawing_brings_an_outdated_readme_up_to_date(stale_project: Path):
    """
    Drawing writes the diagrams the current source draws, after which a check passes.
    """
    ArchitectureDrawing(projects=[stale_project], check_only=False).run()

    status = ArchitectureDrawing(projects=[stale_project], check_only=True).run()

    assert status == DrawingStatus.CURRENT


# %% the workflow's own README


def test_workflow_readme_diagrams_match_the_source():
    """
    The workflow's README holds the diagrams its current source draws; the pre-commit
    hook draws them anew.
    """
    readme = ArchitectureReadme.from_project(PackageLocation.PROJECT)

    assert readme.path.read_text() == readme.current_text()
