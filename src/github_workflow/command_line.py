"""
The commands ``python -m github_workflow`` takes: the only way the workflow's agent
writes to git and GitHub.
"""

from __future__ import annotations

import sys
from enum import StrEnum

import github_workflow

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
    Open a draft pull request for the work branch.
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
    File, prioritize, list, accept, shelve or reject findings.
    """

    CLEANUP = "cleanup"
    """
    Delete the branches GitHub kept although their pull request is closed, and the
    branches discarded.
    """

    DETAILS = "details"
    """
    Show what a pull request's signals are about.
    """

    DESCRIBE = "describe"
    """
    Rewrite the description of an open draft pull request.
    """

    CLONE = "clone"
    """
    Clone another of the owner's repositories, next to the checkout the command runs
    in.
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
    File something noticed outside the current work, as unreviewed.
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
