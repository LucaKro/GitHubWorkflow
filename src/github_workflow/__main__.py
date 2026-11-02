"""
The workflow's commands, the only way its agent writes to git and GitHub; each checks
the owner's rules before it writes and prints one line saying what it did.

Usage: ``python -m github_workflow <command> ...``; ``--help`` lists the commands.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from functools import cached_property
from pathlib import Path

from basstler_domain_model.github.repository_client import (
    GitHubRepository,
    RepositoryDetails,
)
from basstler_domain_model.repository import Repository

from github_workflow.checkout import ProjectCheckout
from github_workflow.command_line import (
    BranchSubcommand,
    FindingSubcommand,
    NotesSubcommand,
    StackSubcommand,
    WorkflowCommand,
)
from github_workflow.notes.branch import NotesBranch
from github_workflow.notes.saving import NotesSave
from github_workflow.policy import WritePolicy
from github_workflow.cleanup import BranchCleanup, BranchDiscard, KeptBranches
from github_workflow.findings import (
    FindingAcceptance,
    FindingFiling,
    FindingListing,
    FindingPrioritization,
    FindingRejection,
    Priority,
)
from github_workflow.pull_request_overview import (
    PullRequestDetails,
    PullRequestSignalReader,
)
from github_workflow.remotes import OwnedRemote, OwnedRemotes
from github_workflow.settings import WorkflowSettings
from github_workflow.stacks import StackPlacement
from github_workflow.work import (
    BranchStart,
    BranchSwitch,
    BranchSync,
    CommitWork,
    DescriptionRewrite,
    DraftOpening,
    NotesSaving,
    PushWork,
    RepositoryCloning,
    StackPlacing,
    WorkflowStep,
)

# %% the session


@dataclass(frozen=True)
class WorkflowSession(RepositoryDetails):
    """
    The checkout a command runs in, and GitHub reached only when the command needs it.
    """

    directory: Path
    """
    Where the command runs, inside the checkout it works on.
    """

    settings: WorkflowSettings
    """
    Whose repositories are written to.
    """

    @cached_property
    def checkout(self) -> ProjectCheckout:
        """
        The checkout the command works on.
        """
        return ProjectCheckout.containing(self.directory)

    @cached_property
    def remote(self) -> OwnedRemote:
        """
        The owner's remote, the only one written to.
        """
        return OwnedRemotes.read(self.checkout.git, self.settings).chosen

    @cached_property
    def github(self) -> GitHubRepository:
        """
        The owner's repository on GitHub.
        """
        return GitHubRepository.from_environment(self.remote.repository)

    def default_branch(self) -> str:
        return self.github.default_branch()

    @property
    def policy(self) -> WritePolicy:
        """:return: The rules the command's writes pass first."""
        return WritePolicy(self.checkout, self.remote, self)

    @property
    def placement(self) -> StackPlacement:
        """:return: Places pull requests in the repository's native stacks."""
        return StackPlacement(self.github, self.github, self.github, self.github)

    def step(self, arguments: argparse.Namespace) -> WorkflowStep:
        """
        :param arguments: The parsed command line.
        :return: The step it asks for.
        """
        match WorkflowCommand(arguments.command), arguments.action:
            case WorkflowCommand.BRANCH, BranchSubcommand.START:
                return BranchStart(self.policy, arguments.name, arguments.on)
            case WorkflowCommand.BRANCH, BranchSubcommand.SWITCH:
                return BranchSwitch(self.policy, arguments.name)
            case WorkflowCommand.BRANCH, BranchSubcommand.DISCARD:
                notes = NotesBranch.on(self.checkout.git, self.remote, self.settings)
                return BranchDiscard(self.policy, notes, arguments.name)
            case WorkflowCommand.COMMIT, _:
                return CommitWork(self.policy, arguments.message, arguments.paths)
            case WorkflowCommand.PUSH, _:
                return PushWork(self.policy)
            case WorkflowCommand.DRAFT, _:
                return DraftOpening(
                    self.policy,
                    self.github,
                    self.placement,
                    arguments.title,
                    arguments.body_file.read_text(),
                    arguments.on,
                )
            case WorkflowCommand.SYNC, _:
                return BranchSync(self.policy)
            case WorkflowCommand.STACK, StackSubcommand.ON:
                return StackPlacing(self.placement, arguments.below, arguments.above)
            case WorkflowCommand.NOTES, NotesSubcommand.SAVE:
                notes = NotesBranch.on(self.checkout.git, self.remote, self.settings)
                return NotesSaving(NotesSave(self.checkout, notes))
            case WorkflowCommand.FINDING, FindingSubcommand.FILE:
                return FindingFiling(
                    self.github,
                    self.github,
                    arguments.title,
                    arguments.body_file.read_text(),
                    Priority[arguments.priority.upper()],
                )
            case WorkflowCommand.FINDING, FindingSubcommand.PRIORITIZE:
                return FindingPrioritization(
                    self.github,
                    self.github,
                    arguments.number,
                    Priority[arguments.priority.upper()],
                )
            case WorkflowCommand.FINDING, FindingSubcommand.LIST:
                return FindingListing(self.github)
            case WorkflowCommand.FINDING, FindingSubcommand.ACCEPT:
                return FindingAcceptance(self.github, arguments.number)
            case WorkflowCommand.FINDING, FindingSubcommand.REJECT:
                return FindingRejection(self.github, arguments.number, arguments.reason)
            case WorkflowCommand.CLEANUP, _:
                git = self.checkout.git
                notes = NotesBranch.on(git, self.remote, self.settings)
                notes.fetch()
                return BranchCleanup(
                    git,
                    self.remote,
                    KeptBranches.read(git, self.remote, self.github, notes),
                    notes,
                )
            case WorkflowCommand.DETAILS, _:
                return PullRequestDetails(
                    PullRequestSignalReader.of(self.github), arguments.number
                )
            case WorkflowCommand.DESCRIBE, _:
                return DescriptionRewrite(
                    self.github,
                    self.github,
                    arguments.number,
                    arguments.body_file.read_text(),
                )
            case WorkflowCommand.CLONE, _:
                around = ProjectCheckout.around(self.directory)
                directory = self.directory if around is None else around.root.parent
                return RepositoryCloning(
                    Repository.parse(arguments.repository), directory, self.settings
                )

    @staticmethod
    def parser() -> argparse.ArgumentParser:
        """:return: The parser of every command's line."""
        parser = argparse.ArgumentParser(
            prog=WorkflowCommand.command_line(),
            description=__doc__.strip().splitlines()[0],
        )
        parser.set_defaults(action=None)
        commands = parser.add_subparsers(dest="command", required=True)
        branch = commands.add_parser(WorkflowCommand.BRANCH, help="start or switch")
        actions = branch.add_subparsers(dest="action", required=True)
        start = actions.add_parser(BranchSubcommand.START, help="start a work branch")
        start.add_argument("name")
        start.add_argument("--on", help="the branch to start from")
        switch = actions.add_parser(BranchSubcommand.SWITCH, help="switch to a branch")
        switch.add_argument("name")
        discard = actions.add_parser(
            BranchSubcommand.DISCARD,
            help="mark a pushed branch as thrown away, for the cleanup to delete",
        )
        discard.add_argument(
            "name", nargs="?", help="the branch, the checked-out one when left out"
        )
        commit = commands.add_parser(WorkflowCommand.COMMIT, help="commit files")
        commit.add_argument("-m", "--message", required=True)
        commit.add_argument("paths", nargs="+", type=Path)
        commands.add_parser(WorkflowCommand.PUSH, help="push the work branch")
        draft = commands.add_parser(WorkflowCommand.DRAFT, help="open a draft")
        draft.add_argument("--title", required=True)
        draft.add_argument("--body-file", required=True, type=Path)
        draft.add_argument("--on", type=int, help="the pull request to stack it on")
        commands.add_parser(WorkflowCommand.SYNC, help="bring the branch up to date")
        stack = commands.add_parser(WorkflowCommand.STACK, help="stack pull requests")
        stack_actions = stack.add_subparsers(dest="action", required=True)
        on = stack_actions.add_parser(StackSubcommand.ON, help="put above on below")
        on.add_argument("below", type=int)
        on.add_argument("above", type=int)
        notes = commands.add_parser(WorkflowCommand.NOTES, help="save the notes")
        notes_actions = notes.add_subparsers(dest="action", required=True)
        notes_actions.add_parser(NotesSubcommand.SAVE, help="save the notes block")
        finding = commands.add_parser(
            WorkflowCommand.FINDING,
            help="file, prioritize, list, accept or reject findings",
        )
        finding_actions = finding.add_subparsers(dest="action", required=True)
        priority_argument = argparse.ArgumentParser(add_help=False)
        priority_argument.add_argument(
            "--priority",
            required=True,
            choices=[priority.level for priority in Priority],
        )
        filing = finding_actions.add_parser(
            FindingSubcommand.FILE,
            help="file something noticed outside the current work",
            description=Priority.guide(),
            parents=[priority_argument],
        )
        filing.add_argument("--title", required=True)
        filing.add_argument("--body-file", required=True, type=Path)
        prioritizing = finding_actions.add_parser(
            FindingSubcommand.PRIORITIZE,
            help="give an existing issue a priority, as a finding",
            description=Priority.guide(),
            parents=[priority_argument],
        )
        prioritizing.add_argument("number", type=int, help="the issue")
        finding_actions.add_parser(FindingSubcommand.LIST, help="list open findings")
        accept = finding_actions.add_parser(
            FindingSubcommand.ACCEPT, help="accept a finding, on the person's word"
        )
        accept.add_argument("number", type=int)
        reject = finding_actions.add_parser(
            FindingSubcommand.REJECT, help="reject a finding, on the person's word"
        )
        reject.add_argument("number", type=int)
        reject.add_argument("--reason", required=True)
        commands.add_parser(
            WorkflowCommand.CLEANUP, help="delete branches of closed pull requests"
        )
        details = commands.add_parser(
            WorkflowCommand.DETAILS, help="what a pull request's signals are about"
        )
        details.add_argument("number", type=int, help="the pull request")
        describe = commands.add_parser(
            WorkflowCommand.DESCRIBE, help="rewrite a draft's description"
        )
        describe.add_argument("number", type=int, help="the draft pull request")
        describe.add_argument("--body-file", required=True, type=Path)
        clone = commands.add_parser(
            WorkflowCommand.CLONE, help="clone another of the owner's repositories"
        )
        clone.add_argument("repository", help="the repository, as owner/name")
        return parser


# %% entry point


def main() -> None:
    """
    Run the command the command line names, and print what it did.
    """
    arguments = WorkflowSession.parser().parse_args()
    session = WorkflowSession(Path.cwd(), WorkflowSettings())
    print(f"github-workflow: {session.step(arguments).run()}")


if __name__ == "__main__":
    main()
