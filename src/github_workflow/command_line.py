"""
The commands ``python -m github_workflow`` takes: the only way the workflow's agent
writes to git and GitHub.
"""

from __future__ import annotations

import sys
from enum import StrEnum

import github_workflow
from github_workflow.install import DomainModelSource

# %% the commands


class WorkflowCommand(StrEnum):
    """
    The commands ``python -m github_workflow`` takes.
    """

    BRANCH = "branch"
    """
    Start a work branch, or switch to one.
    """

    COMMIT = "commit"
    """
    Commit named files on the work branch.
    """

    PUSH = "push"
    """
    Push the work branch to the owner's remote.
    """

    DRAFT = "draft"
    """
    Open a draft pull request for the work branch, working on an accepted, proven
    finding when one is named.
    """

    SYNC = "sync"
    """
    Bring the checked-out branch up to date with GitHub.
    """

    STACK = "stack"
    """
    Put one pull request on top of another in a native stack.
    """

    NOTES = "notes"
    """
    Save the notes block to the notes branch.
    """

    FINDING = "finding"
    """
    File, prioritize, list, accept, shelve, reject, prove or recheck findings, or have
    GitHub complete the finding labels picked there.
    """

    IDEA = "idea"
    """
    Post an idea, not a finding, to the repository's Discussions.
    """

    CLEANUP = "cleanup"
    """
    Delete the branches GitHub kept although their pull request is closed, and the
    branches discarded; remove the clones of somebody else's repositories no session
    uses.
    """

    DETAILS = "details"
    """
    Show what a pull request's signals are about.
    """

    DESCRIBE = "describe"
    """
    Rewrite the description, the title or both of an open pull request, a draft or
    ready for review.
    """

    CLONE = "clone"
    """
    Clone a repository, next to the checkout the command runs in: the owner's to work
    in, anyone else's to read.
    """

    UPSTREAM = "upstream"
    """
    Open a pull request of the owner's fork on the repository it was forked from; the
    person's alone, never a session's.
    """

    LABEL = "label"
    """
    Add labels of the repository's to the work branch's pull request, or remove them.
    """

    REVIEW = "review"
    """
    List, reply to or resolve the review threads of the work branch's pull request.
    """

    @classmethod
    def command_line(cls, *arguments: str) -> str:
        """
        :param arguments: A command and its arguments, none for the bare entry point.
        :return: The command line running it with the interpreter the package runs in.
        """
        return " ".join([sys.executable, "-m", github_workflow.__name__, *arguments])


class BranchSubcommand(StrEnum):
    """
    What ``branch`` does.
    """

    START = "start"
    """
    Create a work branch from the default branch, or from another branch, and switch to
    it.
    """

    SWITCH = "switch"
    """
    Switch to an existing branch.
    """

    DISCARD = "discard"
    """
    Mark a pushed branch as thrown away, so the cleanup deletes it.
    """


class FindingSubcommand(StrEnum):
    """
    What ``finding`` does.
    """

    FILE = "file"
    """
    File something noticed outside the current work, as unreviewed, and proven when a
    test failing on the default branch is given.
    """

    PRIORITIZE = "prioritize"
    """
    Give an existing issue a priority, replacing any other, making it an unreviewed
    finding when it is none yet.
    """

    LIST = "list"
    """
    List the open findings.
    """

    CLOSE = "close"
    """
    Close an accepted, proven finding whose fix is merged and whose proof now passes.
    """

    ACCEPT = "accept"
    """
    Accept an unreviewed or shelved finding, on the person's word.
    """

    SHELVE = "shelve"
    """
    Set an unreviewed or accepted finding aside, on the person's word.
    """

    REJECT = "reject"
    """
    Reject a finding as incorrect, with a reason, on the person's word.
    """

    COMMENT = "comment"
    """
    Comment on an open finding, on the person's go-ahead.
    """

    EDIT = "edit"
    """
    Rewrite an open finding's title or text, on the person's go-ahead.
    """

    PROVE = "prove"
    """
    Prove an open finding with a test failing on the default branch.
    """

    MARK_UNPROVEN = "mark-unproven"
    """
    Mark an open finding unproven, with the reason no failing test could be written.
    """

    RECHECK = "recheck"
    """
    Run the test proving a finding again on the default branch, writing nothing.
    """

    AUTOMATE = "automate"
    """
    Write the Actions workflow completing finding labels picked on GitHub into the
    checkout.
    """


class ReviewSubcommand(StrEnum):
    """
    What ``review`` does.
    """

    LIST = "list"
    """
    List the threads, each with the identifier the others take.
    """

    REPLY = "reply"
    """
    Reply in a thread.
    """

    RESOLVE = "resolve"
    """
    Resolve a thread, once its fix is pushed.
    """


class IdeaSubcommand(StrEnum):
    """
    What ``idea`` does.
    """

    FILE = "file"
    """
    Queue an idea to be posted to the repository's Discussions.
    """


class StackSubcommand(StrEnum):
    """
    What ``stack`` does.
    """

    ON = "on"
    """
    Put the second pull request on top of the first.
    """


class NotesSubcommand(StrEnum):
    """
    What ``notes`` does.
    """

    SAVE = "save"
    """
    Push the edited notes block to the notes branch.
    """


# %% where to report the workflow itself


class ToolRepository(StrEnum):
    """
    The repositories the workflow is built from, where a session files what the
    workflow refused unnecessarily or lacks.
    """

    WORKFLOW = "LucaKro/GitHubWorkflow"
    """
    The workflow itself: the guard, the hooks and the commands.
    """

    DOMAIN_MODEL = DomainModelSource.REPOSITORY.value.removeprefix(
        "https://github.com/"
    )
    """
    The model of git and GitHub the workflow is built on.
    """

    @classmethod
    def refusal_hint(cls) -> str:
        """
        :return: What a session does about a refusal it thinks unnecessary, ending every
            refusal and the notes header.
        """
        listing = WorkflowCommand.command_line(
            WorkflowCommand.FINDING,
            FindingSubcommand.LIST,
            "--repository",
            cls.WORKFLOW,
        )
        filing = WorkflowCommand.command_line(
            WorkflowCommand.FINDING,
            FindingSubcommand.FILE,
            "--repository",
            cls.WORKFLOW,
        )
        attachable = " and ".join(cls)
        return (
            f"When the workflow refuses something unnecessarily or lacks it, check "
            f"`{listing}` and file it there without asking first: `{filing} "
            f"--priority <level> --title "
            f"<title> --body-file <file>`, with what you ran, what happened and what "
            f"should have; for git and GitHub themselves, --repository "
            f"{cls.DOMAIN_MODEL}. A cloud session reaches only the repositories "
            f"attached to it: attach {attachable} with push access without asking, "
            f"never another account's copy of either."
        )
