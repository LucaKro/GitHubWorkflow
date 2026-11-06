"""
Opening a pull request of the owner's fork on the repository it was forked from: a
command only the person runs, which a draft's description suggests to them.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from basstler_domain_model.git.commands import RemoteBranch
from basstler_domain_model.github.labels import LabelWrite
from basstler_domain_model.github.repository_client import (
    Commenter,
    ForkDetails,
    LabelWriter,
    PullRequestsFromForks,
    RepositoryDetails,
    RepositoryLabels,
)
from basstler_domain_model.github.rest_models import RestPullRequest
from basstler_domain_model.github.vocabulary import PullRequestState
from basstler_domain_model.repository import Repository

from github_workflow.command_line import WorkflowCommand
from github_workflow.exceptions import (
    ForeignRepositoryError,
    ForkBranchDivergedError,
    NotAForkError,
    PersonOnlyCommandError,
    PullRequestNotProposableError,
)
from github_workflow.install import Launcher
from github_workflow.labels import DescribedLabel
from github_workflow.settings import WorkflowSettings
from github_workflow.policy import WritePolicy
from github_workflow.work import DescriptionEnding, LocalBranchFollowing, WorkflowStep

# %% proposing


class UpstreamLabel(DescribedLabel):
    """
    The labels a fork's pull request carries about its upstream.
    """

    OPENED_UPSTREAM = (
        "opened upstream",
        "This pull request is open on the upstream repository",
        "1d76db",
    )
    """
    Opened on the repository the fork was forked from, by ``upstream``.
    """


@dataclass(frozen=True)
class UpstreamProposal(WorkflowStep):
    """
    The open pull request of a branch of the owner's fork opened on the repository the
    fork was forked from, ready for review, with the same title and a description
    linking back to it; the fork's pull request then links to the new one and is
    labelled :attr:`UpstreamLabel.OPENED_UPSTREAM`.

    :raises PersonOnlyCommandError: If a Claude Code session runs it.
    :raises ForeignRepositoryError: If the repository is somebody else's.
    :raises NotAForkError: If the repository was forked from none.
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

    labeller: LabelWriter
    """
    Labels the fork's pull request.
    """

    fork_labels: RepositoryLabels
    """
    Creates the label when the fork lacks it.
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
        if not self.settings.owns(self.repository):
            raise ForeignRepositoryError(self.repository, self.settings.owner)
        upstream = self.fork_details.upstream()
        if upstream is None:
            raise NotAForkError(self.repository)
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
                self.branch,
                f"its pull request is open on {upstream} already, as "
                f"#{already[0].number}: {already[0].url}",
            )
        opened = proposals.open_pull_request_from(
            self.repository.owner,
            self.branch,
            self.upstream_details(upstream).default_branch(),
            local.title,
            self.body_linking(local.url),
        )
        self.commenter.add_comment(local.number, self.comment_linking(opened.url))
        if UpstreamLabel.OPENED_UPSTREAM not in self.fork_labels.labels():
            self.fork_labels.create_label(UpstreamLabel.OPENED_UPSTREAM)
        self.labeller.replace_labels(
            local.number,
            LabelWrite.replacing(local.labels, [UpstreamLabel.OPENED_UPSTREAM]).labels,
        )
        return f"opened {upstream}#{opened.number}: {opened.url}"

    def local_pull_request(self) -> RestPullRequest:
        """
        :return: The fork's open pull request from the branch, onto its default branch.
        :raises PullRequestNotProposableError: If there is none.
        """
        every = self.fork_pull_requests.pull_requests_from(
            self.repository.owner, self.branch
        )
        if not every:
            raise PullRequestNotProposableError(
                self.branch, f"{self.repository} has no pull request from it"
            )
        open_ones = [
            pull_request
            for pull_request in every
            if pull_request.state is PullRequestState.OPEN
        ]
        if not open_ones:
            latest = max(every, key=lambda pull_request: pull_request.number)
            raise PullRequestNotProposableError(
                self.branch,
                f"its pull request #{latest.number} is {latest.state}, not open",
            )
        default_branch = self.fork_repository_details.default_branch()
        onto_default = [
            pull_request
            for pull_request in open_ones
            if pull_request.base == default_branch
        ]
        if not onto_default:
            stacked = open_ones[0]
            raise PullRequestNotProposableError(
                self.branch,
                f"its pull request #{stacked.number} is stacked on {stacked.base}, not "
                f"onto {default_branch}: open the one below upstream first",
            )
        return onto_default[0]

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


# %% following the upstream


@dataclass(frozen=True)
class ForkMainSync(WorkflowStep):
    """
    The fork's default branch fast-forwarded to the same branch of the repository it was
    forked from, as GitHub's *Sync fork* does, and the local copy after it; only ever
    fast-forwarded, never merged or forced. Everything goes through git, the upstream's
    branch fetched over HTTPS and the fork's pushed to without force, since a cloud
    session's proxy refuses GitHub's cross-fork compares and its merge-upstream.

    .. note:: The push skips the checkout's ``pre-push`` hook, which refuses every
       change to the default branch: this fast-forward to the upstream's commit is the
       one the workflow makes itself.

    :raises NotAForkError: If the repository was forked from none.
    :raises ForkBranchDivergedError: If the fork's branch has commits of its own.
    """

    policy: WritePolicy
    """
    The checkout of the owner's fork, and its default branch.
    """

    fork_details: ForkDetails
    """
    Reads which repository the fork was forked from.
    """

    upstream_name: str = "upstream"
    """
    The remote name the upstream's branch is fetched under, as ``refs/remotes/<name>``.
    """

    def run(self) -> str:
        repository = self.policy.remote.repository
        upstream = self.fork_details.upstream()
        if upstream is None:
            raise NotAForkError(repository)
        branch = self.policy.default_branch
        git = self.policy.checkout.git
        fork = RemoteBranch(self.policy.remote.name, branch)
        theirs = RemoteBranch(self.upstream_name, branch)
        git.fetch_branch(fork).raise_if_failed()
        git.run(
            "fetch",
            "--quiet",
            "--no-write-fetch-head",
            upstream.clone_url_under(),
            f"+{theirs.reference}:{theirs.tracking_reference}",
        )
        fork_tip = git.commit_at(fork.tracking_reference)
        upstream_tip = git.commit_at(theirs.tracking_reference)
        if fork_tip == upstream_tip:
            return f"{branch} is up to date with {upstream}'s"
        if not git.contains(fork_tip, upstream_tip):
            own = git.run("rev-list", "--count", f"{upstream_tip}..{fork_tip}")
            raise ForkBranchDivergedError(branch, upstream, int(own))
        behind = git.run("rev-list", "--count", f"{fork_tip}..{upstream_tip}")
        git.attempt(
            "push",
            "--quiet",
            "--no-verify",
            fork.remote,
            f"{upstream_tip}:{fork.reference}",
        ).raise_if_failed()
        git.fetch_branch(fork).raise_if_failed()
        local = LocalBranchFollowing(git).follow(fork)
        return f"{branch} fast-forwarded by {behind} commit(s) to {upstream}'s{local}"


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
        ending = (
            f"---\n\n"
            f"To open this pull request on {upstream}, run this yourself (a Claude "
            f"Code session may not):\n\n"
            f"```bash\n{self.command_for(self.repository, branch)}\n```"
        )
        return f"{body.replace(ending, '').rstrip()}\n\n{ending}\n"

    @staticmethod
    def command_for(repository: Repository, branch: str) -> str:
        """
        :param repository: The owner's fork.
        :param branch: Its branch.
        :return: The command line opening the branch's pull request upstream, as the
            person runs it on their own machine.
        """
        return " ".join(
            [Launcher.COMMAND, WorkflowCommand.UPSTREAM, repository.full_name, branch]
        )
