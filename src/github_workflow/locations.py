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
    The branches a cloud session could not delete, one per line with the commit each
    may be deleted at, for the deletion workflow.
    """

    DISCARDED_BRANCHES = Path("discarded-branches.md")
    """
    The branches thrown away, one per line with the commit each was at when discarded.
    """

    DELETION_WORKFLOW = Path(".github/workflows/delete-ready-branches.yml")
    """
    The Actions workflow deleting those branches whenever the notes branch is pushed.
    """

    DELETION_SCRIPT = Path(".github/scripts/delete-ready-branches.sh")
    """
    The script the deletion workflow runs.
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

    LABEL_COMPLETION_WORKFLOW = Path(".github/workflows/complete-finding-labels.yml")
    """
    The Actions workflow completing finding labels picked on GitHub.
    """

    SOURCE_DIRECTORY = Path("src")
    """
    Where a Python project laid out with a source directory keeps its packages.
    """

    PYPROJECT = Path("pyproject.toml")
    """
    The Python project's settings, which may say how its proofs run.
    """


class GitFile(PathEnumeration):
    """
    The files inside a repository's git directory the workflow writes, relative to it.
    """

    EXCLUDE = Path("info/exclude")
    """
    The repository's own ignore list, which is never committed.
    """

    PRE_PUSH_HOOK = Path("hooks/pre-push")
    """
    The hook git runs before every push, which may refuse it.
    """


# %% what the workflow pushes


class WorkflowTemplate(PathEnumeration):
    """
    The files the workflow fills in and writes to git or GitHub, as shipped in the
    package.
    """

    DELETION_WORKFLOW = (
        Path(__file__).parent / "templates" / "delete_ready_branches.yml"
    )
    """
    The Actions workflow deleting the branches listed on the notes branch.
    """

    DELETION_SCRIPT = Path(__file__).parent / "templates" / "delete_ready_branches.sh"
    """
    The script the deletion workflow runs.
    """

    LABEL_COMPLETION_WORKFLOW = (
        Path(__file__).parent / "templates" / "complete_finding_labels.yml"
    )
    """
    The Actions workflow completing finding labels picked on GitHub.
    """

    PROOF_COMMENT = Path(__file__).parent / "templates" / "proof_comment.md"
    """
    The comment posting a finding's proof on its issue.
    """

    PRE_PUSH_HOOK = Path(__file__).parent / "templates" / "pre_push.sh"
    """
    The ``pre-push`` hook checking every push from a Claude Code session.
    """


# %% proving a finding


class ProofFile(PathEnumeration):
    """
    The files a proof run writes into the scratch directory it is handed.
    """

    DEFAULT_BRANCH = Path("default-branch")
    """
    The default branch's files, with the finding's test written among them.
    """

    REPORT = Path("report.xml")
    """
    pytest's JUnit XML report on the test.
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
