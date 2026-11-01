"""
Every file and directory this package names, each written once.
"""

from __future__ import annotations

from pathlib import Path

from basstler_domain_model.locations import PathEnumeration

# %% what a probe writes


class ProbeFile(PathEnumeration):
    """
    The files a probe run writes into the directory it is handed.
    """

    REPORT = Path("report.md")
    """
    What the probe found, for a person to read.
    """

    RESULTS = Path("results.json")
    """
    What the probe found, for a program to read.
    """


# %% what a probe pushes


class ProbeTemplate(PathEnumeration):
    """
    The files a probe fills in and pushes, as shipped in the package.
    """

    BRANCH_DELETION_WORKFLOW = (
        Path(__file__).parent / "probe" / "templates" / "branch_deletion.yml"
    )
    """
    A workflow deleting the probe's branches, run when its own branch is pushed.
    """


class RepositoryFile(PathEnumeration):
    """
    Where in a repository the probe puts the files it pushes.
    """

    BRANCH_DELETION_WORKFLOW = Path(".github/workflows/probe-branch-deletion.yml")
    """
    The branch deletion workflow, where GitHub Actions finds it.
    """
