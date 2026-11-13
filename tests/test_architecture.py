"""
The workflow's README holds the diagrams of its architecture its current source draws.
"""

from __future__ import annotations

from github_workflow.architecture import WorkflowReadme

# %% the README


def test_workflow_readme_diagrams_match_the_source():
    """
    The workflow's README holds the diagrams its current source draws; the pre-commit
    hook draws them anew.
    """
    readme = WorkflowReadme()

    assert readme.path.read_text() == readme.current_text()
