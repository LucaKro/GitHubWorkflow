"""
Opening a pull request of the owner's fork on the repository it was forked from: a
command only the person runs, which a draft's description suggests to them.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from basstler_domain_model.github.repository_client import (
    Commenter,
    ForkDetails,
    PullRequestsFromForks,
    RepositoryDetails,
)
from basstler_domain_model.github.rest_models import RestPullRequest
from basstler_domain_model.github.vocabulary import PullRequestState
from basstler_domain_model.repository import Repository

import github_workflow
from github_workflow.command_line import WorkflowCommand
from github_workflow.exceptions import (
    NotOwnersForkError,
    PersonOnlyCommandError,
    PullRequestNotProposableError,
)
from github_workflow.locations import PersonRuntime
from github_workflow.settings import WorkflowSettings
from github_workflow.work import DescriptionEnding, WorkflowStep

# %% proposing


@dataclass(frozen=True)
class UpstreamProposal(WorkflowStep):
    """
    The open pull request of a branch of the owner's fork opened on the repository the
    fork was forked from, ready for review, with the same title and a description
    linking back to it; the fork's pull request then links to the new one.

    :raises PersonOnlyCommandError: If a Claude Code session runs it.
    :raises NotOwnersForkError: If the repository is no fork of the owner's.
    :raises PullRequestNotProposableError: If the branch has no open pull request onto
        the fork's default branch, or one is open upstream already.
    """

    repository: Repository
    """
    The owner's fork.
    """

    branch: str
    """
    The fork's branch whose pull request is proposed.
    """

    fork_pull_requests: PullRequestsFromForks
    """
    Finds the fork's pull request from the branch.
    """

    fork_details: ForkDetails
    """
    Reads which repository the fork was forked from.
    """

    fork_repository_details: RepositoryDetails
    """
    Reads the fork's default branch.
    """

    commenter: Commenter
    """
    Writes the link to the new pull request on the fork's.
    """

    upstream_pull_requests: Callable[[Repository], PullRequestsFromForks]
    """
    Reaches the pull requests of the repository the fork was forked from.
    """

    upstream_details: Callable[[Repository], RepositoryDetails]
    """
    Reads the default branch of the repository the fork was forked from.
    """

    settings: WorkflowSettings
    """
    Whose forks are proposed from.
    """

    run_by_a_session: bool
    """
    Whether a Claude Code session runs the command.
    """

    def run(self) -> str:
        if self.run_by_a_session:
            raise PersonOnlyCommandError(WorkflowCommand.UPSTREAM)
        upstream = (
            self.fork_details.upstream()
            if self.settings.owns(self.repository)
            else None
        )
        if upstream is None:
            raise NotOwnersForkError(self.repository, self.settings.owner)
        local = self.local_pull_request()
        proposals = self.upstream_pull_requests(upstream)
        already = [
            pull_request
            for pull_request in proposals.pull_requests_from(
                self.repository.owner, self.branch
            )
            if pull_request.state is PullRequestState.OPEN
        ]
        if already:
            raise PullRequestNotProposableError(
                self.branch, f"it is open upstream already, at {already[0].url}"
            )
        opened = proposals.open_pull_request_from(
            self.repository.owner,
            self.branch,
            self.upstream_details(upstream).default_branch(),
            local.title,
            self.body_linking(local.url),
        )
        self.commenter.add_comment(local.number, self.comment_linking(opened.url))
        return f"opened {upstream}#{opened.number}: {opened.url}"

    def local_pull_request(self) -> RestPullRequest:
        """
        :return: The fork's open pull request from the branch, onto its default branch.
        :raises PullRequestNotProposableError: If there is none.
        """
        open_ones = [
            pull_request
            for pull_request in self.fork_pull_requests.pull_requests_from(
                self.repository.owner, self.branch
            )
            if pull_request.state is PullRequestState.OPEN
        ]
        if not open_ones:
            raise PullRequestNotProposableError(
                self.branch, f"{self.repository} has no open pull request from it"
            )
        [local] = open_ones
        default_branch = self.fork_repository_details.default_branch()
        if local.base != default_branch:
            raise PullRequestNotProposableError(
                self.branch,
                f"its pull request is stacked on {local.base}, not onto "
                f"{default_branch}; open the one below upstream first",
            )
        return local

    @staticmethod
    def body_linking(url: str) -> str:
        """
        :param url: The fork's pull request.
        :return: The new pull request's description.
        """
        return f"Proposed from {url}"

    @staticmethod
    def comment_linking(url: str) -> str:
        """
        :param url: The new pull request upstream.
        :return: The comment on the fork's pull request.
        """
        return f"Opened upstream: {url}"


# %% the suggestion


@dataclass(frozen=True)
class UpstreamSuggestion(DescriptionEnding):
    """
    The command line opening a fork's pull request upstream, ending its description for
    the person to copy; nothing on a repository that is no fork.
    """

    fork_details: ForkDetails
    """
    Reads whether the repository is a fork.
    """

    repository: Repository
    """
    The repository the pull request is opened on.
    """

    def appended_to(self, body: str, branch: str) -> str:
        upstream = self.fork_details.upstream()
        if upstream is None:
            return body
        return (
            f"{body.rstrip()}\n\n---\n\n"
            f"To open this pull request on {upstream}, run this yourself (a Claude "
            f"Code session may not):\n\n"
            f"```bash\n{self.command_for(self.repository, branch)}\n```\n"
        )

    @staticmethod
    def command_for(repository: Repository, branch: str) -> str:
        """
        :param repository: The owner's fork.
        :param branch: Its branch.
        :return: The command line opening the branch's pull request upstream, as the
            person runs it on their own machine.
        """
        return " ".join(
            [
                PersonRuntime.INTERPRETER,
                "-m",
                github_workflow.__name__,
                WorkflowCommand.UPSTREAM,
                repository.full_name,
                branch,
            ]
        )
