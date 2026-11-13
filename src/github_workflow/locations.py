"""
Every file and directory this package names, each written once.
"""

from __future__ import annotations

from enum import StrEnum
from pathlib import Path

from domain_model.git.revisions import BranchName
from domain_model.locations import GitHubRepositoryFile, PathEnumeration

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

    DELETION_WORKFLOW = (
        GitHubRepositoryFile.WORKFLOWS_DIRECTORY / "delete-ready-branches.yml"
    )
    """
    The Actions workflow deleting those branches whenever the notes branch is pushed.
    """

    SCRIPTS_DIRECTORY = Path(".github/scripts")
    """
    The scripts the notes branch's workflows run.
    """

    DELETION_SCRIPT = SCRIPTS_DIRECTORY / "delete-ready-branches.sh"
    """
    The script the deletion workflow runs.
    """

    DISCUSSION_POSTS = Path("discussion-posts")
    """
    The discussions waiting to be posted, one file each, removed once posted.
    """

    POSTING_WORKFLOW = GitHubRepositoryFile.WORKFLOWS_DIRECTORY / "post-discussions.yml"
    """
    The Actions workflow posting those discussions whenever they change.
    """

    POSTING_SCRIPT = SCRIPTS_DIRECTORY / "post-discussions.sh"
    """
    The script the posting workflow runs.
    """

    CATEGORIES_QUERY = SCRIPTS_DIRECTORY / "discussion-categories.graphql"
    """
    The query the posting script reads the repository's discussion categories with.
    """

    CREATE_QUERY = SCRIPTS_DIRECTORY / "create-discussion.graphql"
    """
    The mutation the posting script creates a discussion with.
    """

    FIND_QUERY = SCRIPTS_DIRECTORY / "find-discussions.graphql"
    """
    The query the posting script finds the discussion a comment goes on with.
    """

    COMMENT_QUERY = SCRIPTS_DIRECTORY / "add-discussion-comment.graphql"
    """
    The mutation the posting script comments on a discussion with.
    """

    UPSTREAM_REVIEW_REQUESTS = Path("upstream-review-requests")
    """
    The directory holding a session's requests for the reviews of a pull request opened
    upstream, one file each.
    """

    UPSTREAM_REVIEW_ANSWERS = Path("upstream-reviews")
    """
    The directory holding each answered request: GitHub's answers to the reads, as
    recorded by the Actions workflow.
    """

    UPSTREAM_REVIEW_WORKFLOW = (
        GitHubRepositoryFile.WORKFLOWS_DIRECTORY / "read-upstream-reviews.yml"
    )
    """
    The Actions workflow answering the requests.
    """

    COMMIT_SCRIPT = SCRIPTS_DIRECTORY / "commit-notes-branch.sh"
    """
    The script every workflow on the notes branch commits and pushes its changes with.
    """

    @classmethod
    def progress_file(cls, branch: BranchName) -> Path:
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

    LABEL_COMPLETION_WORKFLOW = (
        GitHubRepositoryFile.WORKFLOWS_DIRECTORY / "complete-finding-labels.yml"
    )
    """
    The Actions workflow completing finding labels picked on GitHub.
    """


# %% what the workflow pushes


class WorkflowTemplate(PathEnumeration):
    """
    The files the workflow fills in and writes to git or GitHub, as shipped in the
    package.
    """

    DIRECTORY = Path(__file__).parent / "templates"
    """
    Where they are shipped.
    """

    DELETION_WORKFLOW = DIRECTORY / "delete_ready_branches.yml"
    """
    The Actions workflow deleting the branches listed on the notes branch.
    """

    DELETION_SCRIPT = DIRECTORY / "delete_ready_branches.sh"
    """
    The script the deletion workflow runs.
    """

    POSTING_WORKFLOW = DIRECTORY / "post_discussions.yml"
    """
    The Actions workflow posting the discussions queued on the notes branch.
    """

    POSTING_SCRIPT = DIRECTORY / "post_discussions.sh"
    """
    The script the posting workflow runs.
    """

    CATEGORIES_QUERY = DIRECTORY / "discussion_categories.graphql"
    """
    The query reading a repository's discussion categories.
    """

    CREATE_QUERY = DIRECTORY / "create_discussion.graphql"
    """
    The mutation creating a discussion.
    """

    FIND_QUERY = DIRECTORY / "find_discussions.graphql"
    """
    The query listing a category's discussions, the oldest first.
    """

    COMMENT_QUERY = DIRECTORY / "add_discussion_comment.graphql"
    """
    The mutation commenting on a discussion.
    """

    UPSTREAM_REVIEW_WORKFLOW = DIRECTORY / "read_upstream_reviews.yml"
    """
    The Actions workflow reading the reviews of pull requests opened upstream for the
    requests queued on the notes branch.
    """

    COMMIT_SCRIPT = DIRECTORY / "commit_notes_branch.sh"
    """
    The script the notes branch's workflows commit and push their changes with.
    """

    SESSION_LOG_INTRODUCTION = DIRECTORY / "session_log_introduction.md"
    """
    The text the session log discussion is started with.
    """

    LABEL_COMPLETION_WORKFLOW = DIRECTORY / "complete_finding_labels.yml"
    """
    The Actions workflow completing finding labels picked on GitHub.
    """

    PROOF_COMMENT = DIRECTORY / "proof_comment.md"
    """
    The comment posting a finding's proof on its issue.
    """

    PRE_PUSH_HOOK = DIRECTORY / "pre_push.sh"
    """
    The ``pre-push`` hook checking every push from a Claude Code session.
    """

    NOTES_HEADER = DIRECTORY / "notes_header.md"
    """
    The instructions the notes block opens with.
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

    BRANCH_DELETION_WORKFLOW = (
        GitHubRepositoryFile.WORKFLOWS_DIRECTORY / "probe-branch-deletion.yml"
    )
    """
    The branch deletion workflow, where GitHub Actions finds it.
    """


# %% the plugin's data


class PluginDataDirectory(PathEnumeration):
    """
    The directories the workflow keeps in the plugin's data directory.
    """

    CLONES = Path("clones")
    """
    The clones of somebody else's repositories, as ``<owner>/<name>``.
    """


# %% the package's own files


class PackageLocation(PathEnumeration):
    """
    The workflow package's own directory and the files around it in its source, as
    absolute paths.
    """

    DIRECTORY = Path(__file__).parent
    """
    The package's own directory.
    """

    README = DIRECTORY.parent.parent / "README.md"
    """
    The workflow's README, there only when the package runs from its source.
    """


# %% the plugin and its runtime


class PluginDirectory(PathEnumeration):
    """
    The directories of the plugin a runtime is built from, relative to the plugin's.
    """

    WORKFLOW_SOURCE = Path("src")
    """
    The workflow's source.
    """

    DOMAIN_MODEL_SOURCE = Path("domain_model/src")
    """
    The domain model's source, shipped with the plugin.
    """


class UnstampedDirectory(StrEnum):
    """
    The directories in a plugin whose content is not part of what a runtime is built
    from, by name.
    """

    GIT = ".git"
    """
    The plugin's history, when it is a checkout.
    """

    BYTECODE = "__pycache__"
    """
    Compiled modules, written as the plugin's code runs.
    """


class RuntimeLocation(PathEnumeration):
    """
    The files and directories inside a runtime the installer writes, relative to it.
    """

    PLUGIN_STAMP = Path("github-workflow-plugin")
    """
    Holds the directory of the plugin the runtime was built from, and a digest of its
    content.
    """

    INTERPRETER = Path("bin/python")
    """
    The runtime's interpreter.
    """

    SOURCES = Path("sources")
    """
    Holds the copy of every source directory of the plugin.
    """


class SitePackagesFile(PathEnumeration):
    """
    The files the installer writes into a runtime's site-packages, relative to it.
    """

    SOURCE_PATHS = Path("github-workflow.pth")
    """
    Lists the source directories the runtime's interpreter imports from.
    """


class HomeDirectory(PathEnumeration):
    """
    The directories under the person's home directory the workflow writes to.
    """

    LAUNCHERS = Path(".local/bin")
    """
    Where the launcher is written: the usual place for one's own commands.
    """
