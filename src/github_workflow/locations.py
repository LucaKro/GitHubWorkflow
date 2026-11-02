"""
Every file and directory this package names, each written once.
"""

from __future__ import annotations

from pathlib import Path

from basstler_domain_model.locations import PathEnumeration

# %% the notes branch


class NotesFile(PathEnumeration):
    """
    The files on the notes branch.
    """

    STANDING_NOTES = Path("notes.md")
    """
    The notes every session on the repository starts with.
    """

    PROGRESS_DIRECTORY = Path("progress")
    """
    One file per work branch, named after it.
    """

    READY_FOR_DELETION = Path("ready-for-deletion.md")
    """
    The branches a cloud session could not delete, one per line, for the deletion
    workflow.
    """

    DISCARDED_BRANCHES = Path("discarded-branches.md")
    """
    The branches thrown away, one per line with the commit each was at when discarded.
    """

    DELETION_WORKFLOW = Path(".github/workflows/delete-ready-branches.yml")
    """
    The Actions workflow deleting those branches whenever the notes branch is pushed.
    """

    @classmethod
    def progress_of(cls, branch: str) -> Path:
        """
        :param branch: A work branch.
        :return: Where its progress is kept.
        """
        return cls.PROGRESS_DIRECTORY / f"{branch}.md"


# %% the project


class ProjectFile(PathEnumeration):
    """
    The files the workflow writes into a checkout, relative to its root.
    """

    CLAUDE_LOCAL = Path("CLAUDE.local.md")
    """
    The personal memory file Claude Code loads, which the notes are written into.
    """


class GitFile(PathEnumeration):
    """
    The files inside a repository's git directory the workflow writes, relative to it.
    """

    EXCLUDE = Path("info/exclude")
    """
    The repository's own ignore list, which is never committed.
    """


# %% what the workflow pushes


class WorkflowTemplate(PathEnumeration):
    """
    The files the workflow fills in and pushes, as shipped in the package.
    """

    DELETION_WORKFLOW = (
        Path(__file__).parent / "templates" / "delete_ready_branches.yml"
    )
    """
    The Actions workflow deleting the branches listed on the notes branch.
    """


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
