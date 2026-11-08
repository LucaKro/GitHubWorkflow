"""
The checkout a command or a section of the session start runs in, and every object it
works through, each built once.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from functools import cached_property
from pathlib import Path

from basstler_domain_model.github.readers import PullRequestSource, ReadSource
from basstler_domain_model.github.repository_client import (
    GitHubRepository,
    RepositoryDetails,
)
from basstler_domain_model.github.review_writers import ReviewThreadWriter
from basstler_domain_model.github.stack_placement import StackPlacement
from basstler_domain_model.repository import Repository

from github_workflow.checkout import ProjectCheckout
from github_workflow.cleanup import KeptBranches
from github_workflow.command_steps import CommandStep
from github_workflow.discussions import DiscussionSessionLog
from github_workflow.environment import WorkflowVariable
from github_workflow.exceptions import ForeignRepositoryError, UnknownPluginDataError
from github_workflow.findings import SessionPullRequestClosing
from github_workflow.freshness import BranchFreshening
from github_workflow.label_events import PickedLabelCompletion
from github_workflow.locations import PluginDataDirectory
from github_workflow.notes.branch import NotesBranch
from github_workflow.own_pull_request import WorkBranchPullRequest
from github_workflow.policy import WritePolicy
from github_workflow.proofs import BranchProofRunner
from github_workflow.remotes import OwnedRemote, OwnedRemotes
from github_workflow.settings import WorkflowSettings
from github_workflow.upstream_reviews import (
    DirectUpstreamReviews,
    ForwardedUpstreamReviews,
    UpstreamReviews,
)
from github_workflow.work import (
    OpenPullRequestBranch,
    PullRequestOpenedLabelling,
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

    @cached_property
    def notes(self) -> NotesBranch:
        """
        The notes branch on the owner's remote.
        """
        return NotesBranch.from_settings(self.checkout.git, self.remote, self.settings)

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
        return StackPlacement(self.github)

    @property
    def freshening(self) -> BranchFreshening:
        """:return: Brings the fork's default branch and the work branch up to date."""
        return BranchFreshening(self.policy, self.github)

    @property
    def session_log(self) -> DiscussionSessionLog:
        """:return: Where what the session does without asking is entered."""
        return DiscussionSessionLog.from_checkout(
            self.github, self.checkout.git, self.notes
        )

    @property
    def session_closing(self) -> SessionPullRequestClosing:
        """:return: Closes a pull request a session no longer needs, marked so."""
        return SessionPullRequestClosing(self.github, self.session_log)

    @property
    def issue_labels(self) -> PullRequestOpenedLabelling:
        """
        :return: Labels the issues an opened pull request's description closes, and
            takes the label off again.
        """
        return PullRequestOpenedLabelling(self.github)

    @property
    def work_branch_pull_request(self) -> WorkBranchPullRequest:
        """:return: Finds the work branch's own pull request."""
        return WorkBranchPullRequest(self.policy, self.github)

    @property
    def label_completion(self) -> PickedLabelCompletion:
        """:return: Completes the finding labels picked on GitHub."""
        return PickedLabelCompletion(self.github)

    @property
    def kept_branches(self) -> KeptBranches:
        """
        :return: The repository's branches and pull requests, the notes branch's list of
            discarded branches as last fetched.
        """
        return KeptBranches.read(
            self.checkout.git, self.remote, self.github, self.notes
        )

    @property
    def trusted_authors(self) -> set[str]:
        """
        :return: The logins whose proofs count: the owner's and the account the workflow
            writes as.
        """
        return {self.settings.owner, self.github.authenticated_login()}

    @property
    def foreign_clones(self) -> Path | None:
        """
        :return: Where somebody else's repositories are cloned, as ``<owner>/<name>``;
            ``None`` when the plugin's data directory is not known.
        """
        data = WorkflowVariable.PLUGIN_DATA.read()
        return Path(data) / PluginDataDirectory.CLONES if data else None

    def clone_directory(self, repository: Repository) -> Path:
        """
        :param repository: The repository to clone.
        :return: The directory it is cloned in, under its name: next to the checkout,
            or the current directory outside one, for the owner's; the plugin's data
            for somebody else's.
        :raises UnknownPluginDataError: When it is somebody else's and the plugin's
            data directory is not known.
        """
        if not self.settings.owns(repository):
            clones = self.foreign_clones
            if clones is None:
                raise UnknownPluginDataError(repository)
            return clones / repository.owner
        around = ProjectCheckout.around(self.directory)
        return self.directory if around is None else around.root.parent

    def named_branch(self, name: str | None) -> str:
        """
        :param name: An open pull request's number, or a branch, of the owner's
            repository; ``None`` for the default branch.
        :return: The branch it names.
        :raises UnbuildablePullRequestError: If the pull request is not open, or its
            branch is on another repository.
        """
        if name is None:
            return self.default_branch()
        if not name.isdigit():
            return name
        return OpenPullRequestBranch(self.github, self.remote.repository).branch(
            int(name)
        )

    def proof_runner(self, python: str, branch: str) -> BranchProofRunner:
        """
        :param python: The interpreter the project's tests run with.
        :param branch: The owner's branch to run it on.
        :return: Runs a finding's test on the branch.
        """
        return BranchProofRunner(self.checkout.git, self.remote.name, branch, python)

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

    @property
    def upstream_reviews(self) -> UpstreamReviews:
        """
        Reads the pull requests opened upstream from the owner's fork: directly where
        GitHub's GraphQL is reached, else through the fork's Actions.
        """
        if ReadSource.detect() is ReadSource.GRAPHQL:
            return DirectUpstreamReviews(self.github.api)
        return ForwardedUpstreamReviews(self.notes, self.remote.repository, self.github)

    @property
    def thread_source(self) -> PullRequestSource:
        """
        Reads the review threads of the owner's repository's pull requests, through
        whichever API the place this runs in reaches.
        """
        repository = self.remote.repository
        return ReadSource.detect().reader(self.github.api, repository, repository.owner)

    @property
    def review_writer(self) -> ReviewThreadWriter:
        """
        Writes the review threads of the owner's repository's pull requests, through
        whichever API the place this runs in reaches.
        """
        return ReadSource.detect().writer(self.github.api, self.remote.repository)

    def step(self, arguments: argparse.Namespace) -> WorkflowStep:
        """
        :param arguments: The parsed command line.
        :return: The step it asks for.
        """
        return CommandStep.handling(arguments)(self, arguments).step()

    def command(self, arguments: argparse.Namespace) -> WorkflowStep:
        """
        :param arguments: The parsed command line.
        :return: The step it asks for, run once what it relies on is up to date.
        """
        return CommandStep.handling(arguments)(self, arguments).prepared()
