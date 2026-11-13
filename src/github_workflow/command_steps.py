"""
The step each command line asks for, built by one class per command from the session it
runs in.
"""

from __future__ import annotations

import argparse
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import TYPE_CHECKING

from domain_model.class_family import ClassFamily
from domain_model.class_property import classproperty
from domain_model.environment import ClaudeCodeVariable
from domain_model.github.discussions import (
    DefaultDiscussionCategory,
    DiscussionCategory,
)
from domain_model.github.repository_client import GitHubRepository
from domain_model.repository import Repository

from github_workflow.cleanup import (
    BranchCleanup,
    BranchDiscard,
    Cleanup,
    UnusedCloneRemoval,
)
from github_workflow.command_line import CommandOption, PriorityLevel, RunnableCommand
from github_workflow.exceptions import WorkflowMarkerError
from github_workflow.discussions import DiscussionPost, DiscussionPosting, IdeaFiling
from github_workflow.findings import (
    FindingAcceptance,
    FindingClosing,
    FindingComment,
    FindingDraftOpening,
    FindingEdit,
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
from github_workflow.freshness import FreshenedStep
from github_workflow.label_events import (
    FindingAutomation,
    LabelsCompletedStep,
    PickedLabelCompletion,
)
from github_workflow.markers import WorkflowMarker
from github_workflow.notes.saving import NotesSave
from github_workflow.own_pull_request import (
    PullRequestLabelling,
    ReviewAddressing,
    ReviewReply,
    ReviewResolution,
    ReviewThreadListing,
)
from github_workflow.proofs import FindingTest
from github_workflow.pull_request_overview import (
    PullRequestDetails,
    PullRequestSignalReader,
)
from github_workflow.upstream import ForkMainSync, UpstreamProposal, UpstreamSuggestion
from github_workflow.work import (
    BaseMerge,
    BranchStart,
    BranchSwitch,
    BranchSync,
    CommitWork,
    DescriptionRewrite,
    DraftOpening,
    MergeAbort,
    MergeCompletion,
    NotesSaving,
    PullRequestComment,
    PullRequestMerge,
    PushWork,
    Replacement,
    RepositoryCloning,
    StackPlacing,
    WorkflowStep,
)

if TYPE_CHECKING:
    from github_workflow.session import WorkflowSession

# %% one command's step


@dataclass(frozen=True)
class CommandStep(ClassFamily, ABC):
    """
    Builds the step one command line asks for.
    """

    session: WorkflowSession
    """
    The checkout the command runs in.
    """

    arguments: argparse.Namespace
    """
    The parsed command line.
    """

    @classproperty
    @abstractmethod
    def command(cls) -> RunnableCommand:
        """
        The command whose step this builds.
        """

    @abstractmethod
    def step(self) -> WorkflowStep:
        """
        :return: The step the command line asks for.
        """

    def prepare_step(self) -> WorkflowStep:
        """
        :return: The step, run once what it relies on is up to date; the step itself
            unless the command relies on anything.
        """
        return self.step()

    @classmethod
    def from_arguments(
        cls, session: WorkflowSession, arguments: argparse.Namespace
    ) -> CommandStep:
        """
        :param session: The checkout the command runs in.
        :param arguments: A parsed command line.
        :return: What builds the step it asks for in that checkout.
        """
        words = [word for word in (arguments.command, arguments.action) if word]
        command = RunnableCommand.from_words(words)
        builder = next(
            builder
            for builder in cls.concrete_subclasses()
            if builder.command is command
        )
        return builder(session, arguments)

    @property
    def body(self) -> str | None:
        """
        :return: The text of the file ``--body-file`` names, ``None`` without one.
        :raises WorkflowMarkerError: If it carries a workflow marker.
        """
        file = self.arguments.body_file
        text = None if file is None else file.read_text()
        return self.refuse_markers(text, CommandOption.BODY_FILE)

    @property
    def title(self) -> str | None:
        """
        :return: The text ``--title`` gives, ``None`` without one.
        :raises WorkflowMarkerError: If it carries a workflow marker.
        """
        return self.refuse_markers(self.arguments.title, CommandOption.TITLE)

    @property
    def reason(self) -> str | None:
        """
        :return: The text ``--reason`` gives, ``None`` without one.
        :raises WorkflowMarkerError: If it carries a workflow marker.
        """
        return self.refuse_markers(self.arguments.reason, CommandOption.REASON)

    @property
    def message(self) -> str | None:
        """
        :return: The commit message ``--message`` gives, ``None`` without one.
        :raises WorkflowMarkerError: If it carries a workflow marker.
        """
        return self.refuse_markers(self.arguments.message, CommandOption.MESSAGE)

    @staticmethod
    def refuse_markers(text: str | None, argument: CommandOption) -> str | None:
        """
        :param text: Text a session gives for GitHub, ``None`` for none.
        :param argument: The argument giving it.
        :return: The text.
        :raises WorkflowMarkerError: If it carries a workflow marker, which would pass
            for one of the workflow's own records.
        """
        if text is not None and WorkflowMarker.appears_in(text):
            raise WorkflowMarkerError(argument)
        return text

    @property
    def priority(self) -> Priority:
        """:return: The priority ``--priority`` names."""
        return Priority.at_level(PriorityLevel(self.arguments.priority))


# %% steps run once the branches are up to date


@dataclass(frozen=True)
class FreshenedCommandStep(CommandStep, ABC):
    """
    Builds a step run once the branches are brought up to date.
    """

    def prepare_step(self) -> WorkflowStep:
        """
        Unlike :meth:`CommandStep.prepare_step`, runs once the branches are up to date.
        """
        return FreshenedStep(self.session.freshening, self.step())


# %% branches


@dataclass(frozen=True)
class BranchStartStep(CommandStep):
    """
    Builds the step ``branch start`` asks for.
    """

    @classproperty
    def command(cls) -> RunnableCommand:
        return RunnableCommand.BRANCH_START

    def step(self) -> WorkflowStep:
        return BranchStart(self.session.policy, self.arguments.name, self.arguments.on)


@dataclass(frozen=True)
class BranchSwitchStep(CommandStep):
    """
    Builds the step ``branch switch`` asks for.
    """

    @classproperty
    def command(cls) -> RunnableCommand:
        return RunnableCommand.BRANCH_SWITCH

    def step(self) -> WorkflowStep:
        return BranchSwitch(self.session.policy, self.arguments.name)


@dataclass(frozen=True)
class BranchDiscardStep(CommandStep):
    """
    Builds the step ``branch discard`` asks for.
    """

    @classproperty
    def command(cls) -> RunnableCommand:
        return RunnableCommand.BRANCH_DISCARD

    def step(self) -> WorkflowStep:
        session = self.session
        return BranchDiscard(
            session.policy,
            session.notes,
            session.github,
            session.session_closing,
            self.arguments.name,
        )


# %% committing, pushing and pull requests


@dataclass(frozen=True)
class CommitStep(CommandStep):
    """
    Builds the step ``commit`` asks for.
    """

    @classproperty
    def command(cls) -> RunnableCommand:
        return RunnableCommand.COMMIT

    def step(self) -> WorkflowStep:
        return CommitWork(self.session.policy, self.message, self.arguments.paths)


@dataclass(frozen=True)
class PushStep(FreshenedCommandStep):
    """
    Builds the step ``push`` asks for.
    """

    @classproperty
    def command(cls) -> RunnableCommand:
        return RunnableCommand.PUSH

    def step(self) -> WorkflowStep:
        return PushWork(self.session.policy)


@dataclass(frozen=True)
class DraftStep(FreshenedCommandStep):
    """
    Builds the step ``draft`` asks for.
    """

    @classproperty
    def command(cls) -> RunnableCommand:
        return RunnableCommand.DRAFT

    def step(self) -> WorkflowStep:
        session, arguments = self.session, self.arguments
        replacement = (
            None
            if arguments.replaces is None
            else Replacement(arguments.replaces, session.session_closing)
        )
        draft = DraftOpening(
            session.policy,
            session.github,
            session.placement,
            session.issue_labels,
            self.title,
            self.body,
            arguments.on,
            UpstreamSuggestion(session.github, session.remote.repository),
            replacement,
        )
        if arguments.finding is None:
            return draft
        built_on = session.named_branch(
            None if arguments.on is None else str(arguments.on)
        )
        recheck = FindingRecheck(
            session.github,
            session.proof_runner(arguments.python, built_on),
            session.trusted_authors,
            arguments.finding,
        )
        return FindingDraftOpening(recheck, draft)


@dataclass(frozen=True)
class SyncStep(CommandStep):
    """
    Builds the step ``sync`` asks for.
    """

    @classproperty
    def command(cls) -> RunnableCommand:
        return RunnableCommand.SYNC

    def step(self) -> WorkflowStep:
        session, arguments = self.session, self.arguments
        if arguments.upstream:
            return ForkMainSync(session.policy, session.github)
        if arguments.base:
            return BaseMerge(session.policy, session.github)
        if arguments.on is not None:
            return PullRequestMerge(session.policy, session.github, arguments.on)
        if arguments.resolved:
            return MergeCompletion(session.policy, arguments.resolved)
        if arguments.abort:
            return MergeAbort(session.policy)
        return BranchSync(session.policy, session.github)


@dataclass(frozen=True)
class StackOnStep(CommandStep):
    """
    Builds the step ``stack on`` asks for.
    """

    @classproperty
    def command(cls) -> RunnableCommand:
        return RunnableCommand.STACK_ON

    def step(self) -> WorkflowStep:
        return StackPlacing(
            self.session.placement, self.arguments.below, self.arguments.above
        )


@dataclass(frozen=True)
class NotesSaveStep(CommandStep):
    """
    Builds the step ``notes save`` asks for.
    """

    @classproperty
    def command(cls) -> RunnableCommand:
        return RunnableCommand.NOTES_SAVE

    def step(self) -> WorkflowStep:
        return NotesSaving(NotesSave(self.session.checkout, self.session.notes))


@dataclass(frozen=True)
class DescribeStep(FreshenedCommandStep):
    """
    Builds the step ``describe`` asks for.
    """

    @classproperty
    def command(cls) -> RunnableCommand:
        return RunnableCommand.DESCRIBE

    def step(self) -> WorkflowStep:
        session, number = self.session, self.arguments.number
        if number is None:
            number = session.work_branch_pull_request.find().number
        return DescriptionRewrite(
            session.github,
            number,
            self.body,
            self.title,
            UpstreamSuggestion(session.github, session.remote.repository),
            repository=session.remote.repository,
        )

    def prepare_step(self) -> WorkflowStep:
        """
        Unlike :meth:`FreshenedCommandStep.prepare_step`, freshens the branches only
        when it rewrites the work branch's own pull request.
        """
        if self.arguments.number is not None:
            return self.step()
        return super().prepare_step()


@dataclass(frozen=True)
class LabelStep(CommandStep):
    """
    Builds the step ``label`` asks for.
    """

    @classproperty
    def command(cls) -> RunnableCommand:
        return RunnableCommand.LABEL

    def step(self) -> WorkflowStep:
        return PullRequestLabelling(
            self.session.work_branch_pull_request,
            self.session.github,
            tuple(self.arguments.add or ()),
            tuple(self.arguments.remove or ()),
        )


@dataclass(frozen=True)
class DetailsStep(CommandStep):
    """
    Builds the step ``details`` asks for.
    """

    @classproperty
    def command(cls) -> RunnableCommand:
        return RunnableCommand.DETAILS

    def step(self) -> WorkflowStep:
        return PullRequestDetails(
            PullRequestSignalReader(self.session.github, self.session.thread_source),
            self.arguments.number,
        )


# %% findings


@dataclass(frozen=True)
class FindingFileStep(CommandStep):
    """
    Builds the step ``finding file`` asks for.
    """

    @classproperty
    def command(cls) -> RunnableCommand:
        return RunnableCommand.FINDING_FILE

    def step(self) -> WorkflowStep:
        session, arguments = self.session, self.arguments
        if arguments.test is None:
            board = session.findings_board(arguments.repository)
            return FindingFiling(board, self.title, self.body, self.priority)
        return ProvenFindingFiling(
            session.github,
            self.title,
            self.body,
            self.priority,
            FindingTest.read(session.checkout, arguments.test),
            session.proof_runner(arguments.python, session.default_branch()),
        )


@dataclass(frozen=True)
class FindingPrioritizeStep(CommandStep):
    """
    Builds the step ``finding prioritize`` asks for.
    """

    @classproperty
    def command(cls) -> RunnableCommand:
        return RunnableCommand.FINDING_PRIORITIZE

    def step(self) -> WorkflowStep:
        github = self.session.github
        return FindingPrioritization(github, self.arguments.number, self.priority)


@dataclass(frozen=True)
class FindingListStep(CommandStep):
    """
    Builds the step ``finding list`` asks for.
    """

    @classproperty
    def command(cls) -> RunnableCommand:
        return RunnableCommand.FINDING_LIST

    def step(self) -> WorkflowStep:
        board = self.session.findings_board(self.arguments.repository)
        return FindingListing(board, board.repository)

    def prepare_step(self) -> WorkflowStep:
        """
        Unlike :meth:`CommandStep.prepare_step`, runs once the labels picked on GitHub
        are completed.
        """
        board = self.session.findings_board(self.arguments.repository)
        return LabelsCompletedStep(PickedLabelCompletion(board), self.step())


@dataclass(frozen=True)
class FindingAcceptStep(CommandStep):
    """
    Builds the step ``finding accept`` asks for.
    """

    @classproperty
    def command(cls) -> RunnableCommand:
        return RunnableCommand.FINDING_ACCEPT

    def step(self) -> WorkflowStep:
        github = self.session.github
        return FindingAcceptance(github, self.arguments.number)


@dataclass(frozen=True)
class FindingShelveStep(CommandStep):
    """
    Builds the step ``finding shelve`` asks for.
    """

    @classproperty
    def command(cls) -> RunnableCommand:
        return RunnableCommand.FINDING_SHELVE

    def step(self) -> WorkflowStep:
        github = self.session.github
        return FindingShelving(github, self.arguments.number)


@dataclass(frozen=True)
class FindingRejectStep(CommandStep):
    """
    Builds the step ``finding reject`` asks for.
    """

    @classproperty
    def command(cls) -> RunnableCommand:
        return RunnableCommand.FINDING_REJECT

    def step(self) -> WorkflowStep:
        github = self.session.github
        return FindingRejection(github, self.arguments.number, self.reason)


@dataclass(frozen=True)
class CommentStep(CommandStep):
    """
    Builds the step ``comment`` asks for.
    """

    @classproperty
    def command(cls) -> RunnableCommand:
        return RunnableCommand.COMMENT

    def step(self) -> WorkflowStep:
        return PullRequestComment(self.session.github, self.arguments.number, self.body)


@dataclass(frozen=True)
class FindingCommentStep(CommandStep):
    """
    Builds the step ``finding comment`` asks for.
    """

    @classproperty
    def command(cls) -> RunnableCommand:
        return RunnableCommand.FINDING_COMMENT

    def step(self) -> WorkflowStep:
        board = self.session.findings_board(self.arguments.repository)
        return FindingComment(board, self.arguments.number, self.body)


@dataclass(frozen=True)
class FindingEditStep(CommandStep):
    """
    Builds the step ``finding edit`` asks for.
    """

    @classproperty
    def command(cls) -> RunnableCommand:
        return RunnableCommand.FINDING_EDIT

    def step(self) -> WorkflowStep:
        board = self.session.findings_board(self.arguments.repository)
        return FindingEdit(board, self.arguments.number, self.title, self.body)


@dataclass(frozen=True)
class FindingProveStep(CommandStep):
    """
    Builds the step ``finding prove`` asks for.
    """

    @classproperty
    def command(cls) -> RunnableCommand:
        return RunnableCommand.FINDING_PROVE

    def step(self) -> WorkflowStep:
        session, arguments = self.session, self.arguments
        return FindingProving(
            session.github,
            arguments.number,
            FindingTest.read(session.checkout, arguments.test),
            session.proof_runner(arguments.python, session.named_branch(arguments.on)),
        )


@dataclass(frozen=True)
class FindingMarkUnprovenStep(CommandStep):
    """
    Builds the step ``finding mark-unproven`` asks for.
    """

    @classproperty
    def command(cls) -> RunnableCommand:
        return RunnableCommand.FINDING_MARK_UNPROVEN

    def step(self) -> WorkflowStep:
        github = self.session.github
        return FindingUnproving(github, self.arguments.number, self.reason)


@dataclass(frozen=True)
class FindingRecheckStep(CommandStep):
    """
    Builds the step ``finding recheck`` asks for.
    """

    @classproperty
    def command(cls) -> RunnableCommand:
        return RunnableCommand.FINDING_RECHECK

    def step(self) -> WorkflowStep:
        session, arguments = self.session, self.arguments
        return FindingRecheck(
            session.github,
            session.proof_runner(arguments.python, session.named_branch(arguments.on)),
            session.trusted_authors,
            arguments.number,
        )


@dataclass(frozen=True)
class FindingCloseStep(CommandStep):
    """
    Builds the step ``finding close`` asks for.
    """

    @classproperty
    def command(cls) -> RunnableCommand:
        return RunnableCommand.FINDING_CLOSE

    def step(self) -> WorkflowStep:
        session, arguments = self.session, self.arguments
        default_branch = session.default_branch()
        return FindingClosing(
            session.github,
            arguments.number,
            session.proof_runner(arguments.python, default_branch),
            session.trusted_authors,
            default_branch,
            arguments.fixed_by,
            session.session_log,
        )


@dataclass(frozen=True)
class FindingAutomateStep(CommandStep):
    """
    Builds the step ``finding automate`` asks for.
    """

    @classproperty
    def command(cls) -> RunnableCommand:
        return RunnableCommand.FINDING_AUTOMATE

    def step(self) -> WorkflowStep:
        return FindingAutomation(self.session.checkout.root)


@dataclass(frozen=True)
class IdeaFileStep(CommandStep):
    """
    Builds the step ``idea file`` asks for.
    """

    @classproperty
    def command(cls) -> RunnableCommand:
        return RunnableCommand.IDEA_FILE

    def step(self) -> WorkflowStep:
        session, arguments = self.session, self.arguments
        category = arguments.category or DefaultDiscussionCategory.IDEAS
        return IdeaFiling(
            session.github,
            DiscussionPosting(session.notes),
            session.remote.repository,
            DiscussionPost(DiscussionCategory(category), self.title, self.body),
        )


# %% cleaning up and other repositories


@dataclass(frozen=True)
class CleanupStep(CommandStep):
    """
    Builds the step ``cleanup`` asks for.
    """

    @classproperty
    def command(cls) -> RunnableCommand:
        return RunnableCommand.CLEANUP

    def step(self) -> WorkflowStep:
        session = self.session
        session.notes.fetch()
        clones = session.foreign_clones
        return Cleanup(
            BranchCleanup(
                session.remote,
                session.kept_branches,
                session.notes,
                session.session_log,
            ),
            None if clones is None else UnusedCloneRemoval(clones),
        )


@dataclass(frozen=True)
class CloneStep(CommandStep):
    """
    Builds the step ``clone`` asks for.
    """

    @classproperty
    def command(cls) -> RunnableCommand:
        return RunnableCommand.CLONE

    def step(self) -> WorkflowStep:
        repository = Repository.parse(self.arguments.repository)
        return RepositoryCloning(
            repository,
            self.session.clone_directory(repository),
            self.session.settings,
        )


@dataclass(frozen=True)
class UpstreamStep(CommandStep):
    """
    Builds the step ``upstream`` asks for.
    """

    @classproperty
    def command(cls) -> RunnableCommand:
        return RunnableCommand.UPSTREAM

    def step(self) -> WorkflowStep:
        fork = Repository.parse(self.arguments.repository)
        github = GitHubRepository.from_environment(fork)
        return UpstreamProposal(
            fork,
            self.arguments.branch,
            github,
            GitHubRepository.from_environment,
            self.session.settings,
            ClaudeCodeVariable.COMMAND_MARKER.read() is not None,
        )


# %% review threads


@dataclass(frozen=True)
class ReviewListStep(CommandStep):
    """
    Builds the step ``review list`` asks for.
    """

    @classproperty
    def command(cls) -> RunnableCommand:
        return RunnableCommand.REVIEW_LIST

    def step(self) -> WorkflowStep:
        session = self.session
        return ReviewThreadListing(
            session.work_branch_pull_request,
            session.thread_source,
            session.github,
            session.upstream_reviews,
        )


@dataclass(frozen=True)
class ReviewAddressedStep(CommandStep):
    """
    Builds the step ``review addressed`` asks for.
    """

    @classproperty
    def command(cls) -> RunnableCommand:
        return RunnableCommand.REVIEW_ADDRESSED

    def step(self) -> WorkflowStep:
        session = self.session
        return ReviewAddressing(
            session.work_branch_pull_request,
            session.github,
            self.arguments.address,
            self.body,
            session.upstream_reviews,
        )


@dataclass(frozen=True)
class ReviewReplyStep(CommandStep):
    """
    Builds the step ``review reply`` asks for.
    """

    @classproperty
    def command(cls) -> RunnableCommand:
        return RunnableCommand.REVIEW_REPLY

    def step(self) -> WorkflowStep:
        session = self.session
        return ReviewReply(
            session.work_branch_pull_request,
            session.thread_source,
            session.review_writer,
            self.arguments.comment,
            self.body,
        )


@dataclass(frozen=True)
class ReviewResolveStep(CommandStep):
    """
    Builds the step ``review resolve`` asks for.
    """

    @classproperty
    def command(cls) -> RunnableCommand:
        return RunnableCommand.REVIEW_RESOLVE

    def step(self) -> WorkflowStep:
        session = self.session
        return ReviewResolution(
            session.work_branch_pull_request,
            session.thread_source,
            session.review_writer,
            self.arguments.comment,
        )
