"""
The workflow's commands, the only way its agent writes to git and GitHub; each checks
the owner's rules before it writes and prints one line saying what it did.

Usage: ``python -m github_workflow <command> ...``; ``--help`` lists the commands.
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass
from functools import cached_property
from pathlib import Path
from types import TracebackType

from basstler_domain_model.environment import ClaudeCodeVariable
from basstler_domain_model.exceptions import DataclassException
from basstler_domain_model.github.readers import PullRequestSource, ReadSource
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
    ReviewSubcommand,
    StackSubcommand,
    ToolRepository,
    WorkflowCommand,
)
from github_workflow.exceptions import ForeignRepositoryError
from github_workflow.notes.branch import NotesBranch
from github_workflow.own_pull_request import (
    PullRequestLabelling,
    ReviewReply,
    ReviewResolution,
    ReviewThreadListing,
    WorkBranchPullRequest,
)
from github_workflow.notes.saving import NotesSave
from github_workflow.policy import WritePolicy
from github_workflow.proofs import DefaultBranchProofRunner, FindingTest
from github_workflow.cleanup import BranchCleanup, BranchDiscard, KeptBranches
from github_workflow.findings import (
    FindingAcceptance,
    FindingClosing,
    FindingComment,
    FindingEdit,
    FindingDraftOpening,
    FindingFiling,
    FindingListing,
    FindingPrioritization,
    FindingProving,
    FindingRecheck,
    FindingRejection,
    FindingShelving,
    FindingUnproving,
    Priority,
    ProvenFindingFiling,
)
from github_workflow.label_events import FindingAutomation
from github_workflow.pull_request_overview import (
    PullRequestDetails,
    PullRequestSignalReader,
)
from github_workflow.remotes import OwnedRemote, OwnedRemotes
from github_workflow.settings import WorkflowSettings
from github_workflow.stacks import StackPlacement
from github_workflow.upstream import (
    ForkMainSync,
    UpstreamProposal,
    UpstreamSuggestion,
)
from github_workflow.work import (
    BaseMerge,
    BranchStart,
    BranchSwitch,
    BranchSync,
    GitHubPullRequestBranches,
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
        """
        :return: The branch pull requests target unless told otherwise, as git reads it
            from the owner's remote, and from GitHub's API only when git cannot tell.
        """
        return (
            self.checkout.git.remote_default_branch(self.remote.name)
            or self.github.default_branch()
        )

    @property
    def policy(self) -> WritePolicy:
        """:return: The rules the command's writes pass first."""
        return WritePolicy(self.checkout, self.remote, self)

    @property
    def placement(self) -> StackPlacement:
        """:return: Places pull requests in the repository's native stacks."""
        return StackPlacement(self.github, self.github, self.github, self.github)

    def proof_runner(self, python: str) -> DefaultBranchProofRunner:
        """
        :param python: The interpreter the project's tests run with.
        :return: Runs a finding's test on the owner's default branch.
        """
        return DefaultBranchProofRunner(
            self.checkout.git, self.remote.name, self.default_branch(), python
        )

    def recheck(self, number: int, python: str) -> FindingRecheck:
        """
        :param number: A finding.
        :param python: The interpreter the project's tests run with.
        :return: Runs its proof again, trusting proofs the owner or the account the
            workflow writes as posted.
        """
        authors = {self.settings.owner, self.github.authenticated_login()}
        return FindingRecheck(self.github, self.proof_runner(python), authors, number)

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
                draft = DraftOpening(
                    self.policy,
                    self.github,
                    self.placement,
                    arguments.title,
                    arguments.body_file.read_text(),
                    arguments.on,
                    UpstreamSuggestion(self.github, self.remote.repository),
                )
                if arguments.finding is None:
                    return draft
                return FindingDraftOpening(
                    self.recheck(arguments.finding, arguments.python), draft
                )
            case WorkflowCommand.SYNC, _ if arguments.upstream:
                return ForkMainSync(self.policy, self.github)
            case WorkflowCommand.SYNC, _ if arguments.base:
                return BaseMerge(self.policy, self.github, self.github)
            case WorkflowCommand.SYNC, _:
                return BranchSync(
                    self.policy,
                    GitHubPullRequestBranches(
                        self.github, self.remote.repository.full_name
                    ),
                )
            case WorkflowCommand.STACK, StackSubcommand.ON:
                return StackPlacing(self.placement, arguments.below, arguments.above)
            case WorkflowCommand.NOTES, NotesSubcommand.SAVE:
                notes = NotesBranch.on(self.checkout.git, self.remote, self.settings)
                return NotesSaving(NotesSave(self.checkout, notes))
            case WorkflowCommand.FINDING, FindingSubcommand.FILE:
                body = arguments.body_file.read_text()
                priority = Priority[arguments.priority.upper()]
                if arguments.test is None:
                    board = self.findings_board(arguments.repository)
                    return FindingFiling(board, board, arguments.title, body, priority)
                return ProvenFindingFiling(
                    self.github,
                    self.github,
                    arguments.title,
                    body,
                    priority,
                    FindingTest.read(self.checkout, arguments.test),
                    self.proof_runner(arguments.python),
                )
            case WorkflowCommand.FINDING, FindingSubcommand.PRIORITIZE:
                return FindingPrioritization(
                    self.github,
                    self.github,
                    arguments.number,
                    Priority[arguments.priority.upper()],
                )
            case WorkflowCommand.FINDING, FindingSubcommand.LIST:
                return FindingListing(self.findings_board(arguments.repository))
            case WorkflowCommand.FINDING, FindingSubcommand.ACCEPT:
                return FindingAcceptance(self.github, self.github, arguments.number)
            case WorkflowCommand.FINDING, FindingSubcommand.SHELVE:
                return FindingShelving(self.github, self.github, arguments.number)
            case WorkflowCommand.FINDING, FindingSubcommand.REJECT:
                return FindingRejection(
                    self.github, self.github, arguments.number, arguments.reason
                )
            case WorkflowCommand.FINDING, FindingSubcommand.COMMENT:
                return FindingComment(
                    self.github,
                    self.github,
                    arguments.number,
                    arguments.body_file.read_text(),
                )
            case WorkflowCommand.FINDING, FindingSubcommand.EDIT:
                body = arguments.body_file.read_text() if arguments.body_file else None
                return FindingEdit(
                    self.github, self.github, arguments.number, arguments.title, body
                )
            case WorkflowCommand.FINDING, FindingSubcommand.PROVE:
                return FindingProving(
                    self.github,
                    self.github,
                    arguments.number,
                    FindingTest.read(self.checkout, arguments.test),
                    self.proof_runner(arguments.python),
                )
            case WorkflowCommand.FINDING, FindingSubcommand.MARK_UNPROVEN:
                return FindingUnproving(
                    self.github, self.github, arguments.number, arguments.reason
                )
            case WorkflowCommand.FINDING, FindingSubcommand.RECHECK:
                return self.recheck(arguments.number, arguments.python)
            case WorkflowCommand.FINDING, FindingSubcommand.CLOSE:
                return FindingClosing(
                    self.github,
                    self.github,
                    arguments.number,
                    self.github,
                    self.proof_runner(arguments.python),
                    {self.settings.owner, self.github.authenticated_login()},
                    self.default_branch(),
                    arguments.fixed_by,
                )
            case WorkflowCommand.FINDING, FindingSubcommand.AUTOMATE:
                return FindingAutomation(self.checkout.root)
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
                    self.github,
                    self.github,
                    arguments.number,
                    arguments.body_file.read_text() if arguments.body_file else None,
                    arguments.title,
                    UpstreamSuggestion(self.github, self.remote.repository),
                )
            case WorkflowCommand.CLONE, _:
                around = ProjectCheckout.around(self.directory)
                directory = self.directory if around is None else around.root.parent
                return RepositoryCloning(
                    Repository.parse(arguments.repository), directory, self.settings
                )
            case WorkflowCommand.LABEL, _:
                return PullRequestLabelling(
                    WorkBranchPullRequest(self.policy, self.github),
                    self.github,
                    self.github,
                    tuple(arguments.add or ()),
                    tuple(arguments.remove or ()),
                )
            case WorkflowCommand.REVIEW, ReviewSubcommand.LIST:
                return ReviewThreadListing(
                    WorkBranchPullRequest(self.policy, self.github), self.thread_source
                )
            case WorkflowCommand.REVIEW, ReviewSubcommand.REPLY:
                return ReviewReply(
                    WorkBranchPullRequest(self.policy, self.github),
                    self.thread_source,
                    ReadSource.detect().writer(self.github.api, self.remote.repository),
                    arguments.comment,
                    arguments.body_file.read_text(),
                )
            case WorkflowCommand.REVIEW, ReviewSubcommand.RESOLVE:
                return ReviewResolution(
                    WorkBranchPullRequest(self.policy, self.github),
                    self.thread_source,
                    ReadSource.detect().writer(self.github.api, self.remote.repository),
                    arguments.comment,
                )
            case WorkflowCommand.UPSTREAM, _:
                fork = Repository.parse(arguments.repository)
                github = GitHubRepository.from_environment(fork)
                return UpstreamProposal(
                    fork,
                    arguments.branch,
                    github,
                    github,
                    github,
                    github,
                    GitHubRepository.from_environment,
                    GitHubRepository.from_environment,
                    self.settings,
                    ClaudeCodeVariable.COMMAND_MARKER.read() is not None,
                )

    @property
    def thread_source(self) -> PullRequestSource:
        """
        Reads the review threads of the owner's repository's pull requests, through
        whichever API the place this runs in reaches.
        """
        repository = self.remote.repository
        return ReadSource.detect().reader(self.github.api, repository, repository.owner)

    @staticmethod
    def report(
        kind: type[BaseException],
        raised: BaseException,
        traceback: TracebackType | None,
    ) -> None:
        """
        Print a refusal of the workflow's as its reason and what to do instead, and any
        other error as Python would.

        :param kind: The error's type.
        :param raised: The error.
        :param traceback: Where it was raised.
        """
        if not isinstance(raised, DataclassException):
            sys.__excepthook__(kind, raised, traceback)
            return
        print(
            f"github-workflow: {raised}\n{ToolRepository.refusal_hint()}",
            file=sys.stderr,
        )

    def findings_board(self, repository: str | None) -> GitHubRepository:
        """
        :param repository: Another of the owner's repositories, as ``owner/name``;
            ``None`` for the checkout's.
        :return: The repository whose findings a command files or lists.
        :raises ForeignRepositoryError: If it belongs to somebody else.
        """
        if repository is None:
            return self.github
        named = Repository.parse(repository)
        if not self.settings.owns(named):
            raise ForeignRepositoryError(named, self.settings.owner)
        return GitHubRepository.from_environment(named)

    @staticmethod
    def parser() -> argparse.ArgumentParser:
        """:return: The parser of every command's line."""
        parser = argparse.ArgumentParser(
            prog=WorkflowCommand.command_line(),
            description=__doc__.strip().splitlines()[0],
        )
        parser.set_defaults(action=None)
        commands = parser.add_subparsers(dest="command", required=True)
        python_argument = argparse.ArgumentParser(add_help=False)
        python_argument.add_argument(
            "--python",
            default="python",
            help="the interpreter the project's tests run with (default: %(default)s)",
        )
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
        draft = commands.add_parser(
            WorkflowCommand.DRAFT, help="open a draft", parents=[python_argument]
        )
        draft.add_argument("--title", required=True)
        draft.add_argument("--body-file", required=True, type=Path)
        draft.add_argument("--on", type=int, help="the pull request to stack it on")
        draft.add_argument(
            "--finding",
            type=int,
            help="the accepted, proven finding it works on, rechecked first",
        )
        sync = commands.add_parser(
            WorkflowCommand.SYNC, help="bring the branch up to date"
        )
        instead = sync.add_mutually_exclusive_group()
        instead.add_argument(
            "--upstream",
            action="store_true",
            help="instead, fast-forward a fork's default branch to its upstream's",
        )
        instead.add_argument(
            "--base",
            action="store_true",
            help="instead, merge GitHub's default branch into the work branch",
        )
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
            help="file, prioritize, list, accept, shelve, reject, prove or recheck "
            "findings",
        )
        finding_actions = finding.add_subparsers(dest="action", required=True)
        priority_argument = argparse.ArgumentParser(add_help=False)
        priority_argument.add_argument(
            "--priority",
            required=True,
            choices=[priority.level for priority in Priority],
        )
        repository_help = (
            "another of the owner's repositories, as owner/name, no checkout needed; "
            "the checkout's when left out"
        )
        filing = finding_actions.add_parser(
            FindingSubcommand.FILE,
            help="file something noticed outside the current work",
            description=Priority.guide(),
            parents=[priority_argument, python_argument],
        )
        filing.add_argument("--title", required=True)
        filing.add_argument("--body-file", required=True, type=Path)
        filed_where = filing.add_mutually_exclusive_group()
        filed_where.add_argument(
            "--test",
            type=Path,
            help="an uncommitted test file failing on the default branch, proving it",
        )
        filed_where.add_argument("--repository", help=repository_help)
        prioritizing = finding_actions.add_parser(
            FindingSubcommand.PRIORITIZE,
            help="give an existing issue a priority, as a finding",
            description=Priority.guide(),
            parents=[priority_argument],
        )
        prioritizing.add_argument("number", type=int, help="the issue")
        listing = finding_actions.add_parser(
            FindingSubcommand.LIST, help="list open findings"
        )
        listing.add_argument("--repository", help=repository_help)
        accept = finding_actions.add_parser(
            FindingSubcommand.ACCEPT, help="accept a finding, on the person's word"
        )
        accept.add_argument("number", type=int)
        shelve = finding_actions.add_parser(
            FindingSubcommand.SHELVE, help="set a finding aside, on the person's word"
        )
        shelve.add_argument("number", type=int)
        reject = finding_actions.add_parser(
            FindingSubcommand.REJECT,
            help="reject a finding as incorrect, on the person's word",
        )
        reject.add_argument("number", type=int)
        reject.add_argument("--reason", required=True)
        comment = finding_actions.add_parser(
            FindingSubcommand.COMMENT,
            help="comment on an open finding, on the person's go-ahead",
        )
        comment.add_argument("number", type=int)
        comment.add_argument("--body-file", type=Path, required=True)
        rewrite = finding_actions.add_parser(
            FindingSubcommand.EDIT,
            help="rewrite an open finding's title or text, on the person's go-ahead",
        )
        rewrite.add_argument("number", type=int)
        rewrite.add_argument("--title")
        rewrite.add_argument("--body-file", type=Path)
        prove = finding_actions.add_parser(
            FindingSubcommand.PROVE,
            help="prove an open finding with a test failing on the default branch",
            parents=[python_argument],
        )
        prove.add_argument("number", type=int)
        prove.add_argument(
            "--test", required=True, type=Path, help="the uncommitted test file"
        )
        unproven = finding_actions.add_parser(
            FindingSubcommand.MARK_UNPROVEN,
            help="mark an open finding no failing test could be written for",
        )
        unproven.add_argument("number", type=int)
        unproven.add_argument("--reason", required=True)
        recheck = finding_actions.add_parser(
            FindingSubcommand.RECHECK,
            help="run a finding's proof again on the default branch",
            parents=[python_argument],
        )
        recheck.add_argument("number", type=int)
        close = finding_actions.add_parser(
            FindingSubcommand.CLOSE,
            help="close an accepted, proven finding once its fix is merged and its "
            "proof passes on the default branch",
            parents=[python_argument],
        )
        close.add_argument("number", type=int)
        close.add_argument(
            "--fixed-by", type=int, required=True, help="the merged pull request"
        )
        finding_actions.add_parser(
            FindingSubcommand.AUTOMATE,
            help="write the Actions workflow completing finding labels picked on GitHub",
        )
        commands.add_parser(
            WorkflowCommand.CLEANUP, help="delete branches of closed pull requests"
        )
        details = commands.add_parser(
            WorkflowCommand.DETAILS, help="what a pull request's signals are about"
        )
        details.add_argument("number", type=int, help="the pull request")
        describe = commands.add_parser(
            WorkflowCommand.DESCRIBE,
            help="rewrite an open pull request's description or title",
        )
        describe.add_argument("number", type=int, help="the open pull request")
        describe.add_argument("--body-file", type=Path, help="the new description")
        describe.add_argument("--title", help="the new title")
        clone = commands.add_parser(
            WorkflowCommand.CLONE,
            help="clone a repository: the owner's to work in, anyone's to read",
        )
        clone.add_argument("repository", help="the repository, as owner/name")
        label = commands.add_parser(
            WorkflowCommand.LABEL,
            help="label the work branch's own pull request, without asking",
        )
        label.add_argument(
            "--add", action="append", metavar="LABEL", help="a label to add, repeatable"
        )
        label.add_argument(
            "--remove",
            action="append",
            metavar="LABEL",
            help="a label to remove, repeatable",
        )
        review = commands.add_parser(
            WorkflowCommand.REVIEW,
            help="the review threads of the work branch's own pull request",
        )
        review_actions = review.add_subparsers(dest="action", required=True)
        review_actions.add_parser(
            ReviewSubcommand.LIST, help="list the threads, each with its identifier"
        )
        reply = review_actions.add_parser(
            ReviewSubcommand.REPLY, help="reply in a thread, without asking"
        )
        reply.add_argument("comment", type=int, help="the thread's identifier")
        reply.add_argument("--body-file", required=True, type=Path)
        resolve = review_actions.add_parser(
            ReviewSubcommand.RESOLVE,
            help="resolve a thread once its fix is pushed, without asking",
        )
        resolve.add_argument("comment", type=int, help="the thread's identifier")
        upstream = commands.add_parser(
            WorkflowCommand.UPSTREAM,
            help="open a fork's pull request on its upstream; the person's alone",
        )
        upstream.add_argument("repository", help="the owner's fork, as owner/name")
        upstream.add_argument("branch", help="the fork's branch with the pull request")
        return parser


# %% entry point


def main() -> None:
    """
    Run the command the command line names, and print what it did, or why it refused.
    """
    sys.excepthook = WorkflowSession.report
    arguments = WorkflowSession.parser().parse_args()
    session = WorkflowSession(Path.cwd(), WorkflowSettings())
    print(f"github-workflow: {session.step(arguments).run()}")


if __name__ == "__main__":
    main()
