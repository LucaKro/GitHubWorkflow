"""
Reading and writing a repository's pull requests, labels and stacks.

The reading and the writing halves are declared separately, so a caller that must not
write can be handed a reader and provably cannot.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from enum import Enum
from typing import Any

from domain_model.git.revisions import BranchName
from domain_model.github.clients import GitHubApi, RestApi
from domain_model.github.commit_checks import CommitCheckReader
from domain_model.github.exceptions import NotAnIssueError
from domain_model.github.issue_models import Issue, IssueComment, LabelEvent
from domain_model.github.labels import GitHubLabel
from domain_model.github.rest_models import (
    RestPullRequest,
    RestRepository,
    SearchedPullRequest,
    Workflow,
    WorkflowRun,
)
from domain_model.github.routes import RepositoryRoute
from domain_model.github.stack_models import Stack
from domain_model.github.vocabulary import (
    IssueState,
    IssueStateReason,
    PullRequestState,
    QueryParameter,
    RestJSONKey,
    RollupState,
    StackAction,
)
from domain_model.repository import Repository

# %% what a caller reads and writes


@dataclass(frozen=True)
class PullRequestReader(ABC):
    """
    Reading a repository's pull requests.

    Implementations inherit rather than merely match the shape, so one that omits a read
    is refused when it is constructed rather than when the missing call is first made.
    """

    @abstractmethod
    def open_pull_requests(self) -> list[RestPullRequest]:
        """:return: Every open pull request in the repository."""

    @abstractmethod
    def pull_request(self, number: int) -> RestPullRequest:
        """:param number: The pull request to read.
        :return: That pull request."""


@dataclass(frozen=True)
class LabelWriter(ABC):
    """
    Writing the labels an issue or pull request carries.
    """

    @abstractmethod
    def replace_labels(self, number: int, labels: Sequence[str]) -> None:
        """
        :param number: The issue or pull request to write.
        :param labels: The complete label set it must end up with.
        """


@dataclass(frozen=True)
class Commenter(ABC):
    """
    Commenting on an issue or pull request.
    """

    @abstractmethod
    def add_comment(self, number: int, body: str) -> str:
        """
        :param number: The issue or pull request to comment on.
        :param body: The comment.
        :return: The comment's URL.
        """


@dataclass(frozen=True)
class PullRequestWriter(LabelWriter, Commenter, ABC):
    """
    Writing a pull request's labels, comments and description.
    """

    @abstractmethod
    def set_description(self, number: int, body: str) -> None:
        """:param number: The pull request to write.
        :param body: The new description."""


@dataclass(frozen=True)
class RepositoryLabels(ABC):
    """
    The labels a repository carries, and adding one it lacks.
    """

    @abstractmethod
    def labels(self) -> set[str]:
        """:return: The name of every label the repository carries."""

    @abstractmethod
    def create_label(self, label: GitHubLabel) -> None:
        """:param label: The label to add, created with its description."""

    def create_missing_labels(self, labels: Iterable[GitHubLabel]) -> None:
        """
        Create each of the labels the repository does not carry yet.

        :param labels: The labels the repository has to carry.
        """
        present = self.labels()
        for label in labels:
            if label not in present:
                self.create_label(label)


@dataclass(frozen=True)
class PullRequestCloser(ABC):
    """
    Closing a pull request without merging it.
    """

    @abstractmethod
    def close_pull_request(self, number: int) -> None:
        """:param number: The open pull request to close; it can be reopened."""


@dataclass(frozen=True)
class PullRequestBaseWriter(ABC):
    """
    Retargeting a pull request at another branch.
    """

    @abstractmethod
    def set_base(self, number: int, branch: BranchName) -> None:
        """:param number: The pull request to retarget.
        :param branch: The branch it is to merge into."""


@dataclass(frozen=True)
class StackReader(ABC):
    """
    Reading a repository's native stacks of pull requests.
    """

    @abstractmethod
    def stacks(self) -> list[Stack]:
        """:return: Every stack in the repository, newest first."""

    @abstractmethod
    def stack(self, number: int) -> Stack:
        """:param number: The stack's number.
        :return: That stack."""

    @abstractmethod
    def containing_stack(self, pull_request: int) -> Stack | None:
        """:param pull_request: A pull request's number.
        :return: The stack holding it, ``None`` when it is in none."""


@dataclass(frozen=True)
class StackWriter(ABC):
    """
    Forming, growing and dissolving native stacks of pull requests.
    """

    @abstractmethod
    def create_stack(self, pull_requests: Sequence[int]) -> Stack:
        """
        :param pull_requests: At least two pull requests, bottom first, each targeting
            the branch of the one before it.
        :return: The new stack.
        """

    @abstractmethod
    def add_to_stack(self, stack: Stack, pull_requests: Sequence[int]) -> Stack:
        """
        :param stack: The stack to grow.
        :param pull_requests: The pull requests to put on top, lowest first, the first
            targeting the stack's top branch.
        :return: The grown stack.
        """

    @abstractmethod
    def unstack(self, stack: Stack) -> Stack | None:
        """
        :param stack: The stack to take the pull requests out of.
        :return: What remains of it, ``None`` when it dissolved.
        """


@dataclass(frozen=True)
class PullRequestOpener(ABC):
    """
    Opening a pull request.
    """

    @abstractmethod
    def open_draft(
        self, head: BranchName, base: BranchName, title: str, body: str
    ) -> int:
        """
        :param head: The branch to merge, in this repository.
        :param base: The branch to merge it into.
        :param title: The pull request's title.
        :param body: Its description.
        :return: The number of the new draft pull request.
        """


@dataclass(frozen=True)
class ForkDetails(ABC):
    """
    Reading which repository a repository was forked from.
    """

    @abstractmethod
    def upstream(self) -> Repository | None:
        """
        :return: The repository it was forked from, ``None`` when it is no fork.
        """


@dataclass(frozen=True)
class PullRequestSearch(ABC):
    """
    Finding a repository's pull requests through GitHub's search, which a cloud
    session reaches on repositories its proxy refuses otherwise.
    """

    @abstractmethod
    def search_branch_pull_requests(
        self, author: str, branch: BranchName
    ) -> list[SearchedPullRequest]:
        """
        :param author: Who opened them.
        :param branch: The branch they were opened from, on any repository.
        :return: The repository's pull requests opened so, in any state.
        """


@dataclass(frozen=True)
class RepositoryWorkflows(ABC):
    """
    Reading a repository's Actions workflows and their runs.
    """

    @abstractmethod
    def workflows(self) -> list[Workflow]:
        """
        :return: Every workflow, from a file on any of the repository's branches.
        """

    @abstractmethod
    def branch_runs(self, branch: BranchName) -> list[WorkflowRun]:
        """
        :param branch: A branch.
        :return: The latest runs its pushes and events started, newest first.
        """


@dataclass(frozen=True)
class ForkSync(ABC):
    """
    Bringing a fork's branch up to its upstream's.
    """

    @abstractmethod
    def sync_with_upstream(self, branch: BranchName) -> None:
        """
        Bring a branch of this fork up to the same branch of its upstream, as GitHub's
        *Sync fork* does.

        :param branch: The fork's branch.
        """


@dataclass(frozen=True)
class PullRequestsFromForks(ABC):
    """
    Finding and opening pull requests into this repository from a fork's branch.
    """

    @abstractmethod
    def fork_branch_pull_requests(
        self, owner: str, branch: BranchName
    ) -> list[RestPullRequest]:
        """
        :param owner: The fork's owner.
        :param branch: The fork's branch.
        :return: Every pull request opened from it, open or closed.
        """

    def open_fork_branch_pull_requests(
        self, owner: str, branch: BranchName
    ) -> list[RestPullRequest]:
        """
        :param owner: The fork's owner.
        :param branch: The fork's branch.
        :return: The pull requests opened from it that are open still.
        """
        return [
            pull_request
            for pull_request in self.fork_branch_pull_requests(owner, branch)
            if pull_request.state is PullRequestState.OPEN
        ]

    @abstractmethod
    def open_fork_pull_request(
        self, owner: str, branch: BranchName, base: BranchName, title: str, body: str
    ) -> RestPullRequest:
        """
        Open a pull request, ready for review, from a fork's branch.

        :param owner: The fork's owner.
        :param branch: The fork's branch.
        :param base: The branch of this repository to merge it into.
        :param title: The pull request's title.
        :param body: Its description.
        :return: The new pull request.
        """


@dataclass(frozen=True)
class RepositoryDetails(ABC):
    """
    Reading facts about the repository itself.
    """

    @abstractmethod
    def default_branch(self) -> BranchName:
        """:return: The branch pull requests target unless told otherwise."""


@dataclass(frozen=True)
class IssueLabelHistory(ABC):
    """
    Reading the labels added to and removed from an issue over time.
    """

    @abstractmethod
    def label_events(self, number: int) -> list[LabelEvent]:
        """
        :param number: The issue or pull request.
        :return: Its labels added and removed, oldest first.
        """


@dataclass(frozen=True)
class RepositoryDiscussions(ABC):
    """
    Reading whether the repository has Discussions turned on.
    """

    @abstractmethod
    def discussions_enabled(self) -> bool:
        """:return: Whether the repository has Discussions turned on."""


@dataclass(frozen=True)
class RepositorySettings(ABC):
    """
    Whether GitHub deletes merged branches, and turning that on, which not every
    credential may.
    """

    @abstractmethod
    def deletes_merged_branches(self) -> bool:
        """:return: Whether GitHub deletes a pull request's branch once it is merged."""

    @abstractmethod
    def turn_on_merged_branch_deletion(self) -> bool:
        """
        Have GitHub delete a pull request's branch once it is merged.

        :return: Whether GitHub accepted the change; ``False`` only when the credential
            may not make it.
        :raises GitHubRequestFailed: If GitHub fails the change for another reason.
        """

    @abstractmethod
    def issues_enabled(self) -> bool:
        """:return: Whether the repository has issues turned on."""

    @abstractmethod
    def turn_on_issues(self) -> bool:
        """
        Turn the repository's issues on.

        :return: Whether GitHub accepted the change; ``False`` only when the credential
            may not make it.
        :raises GitHubRequestFailed: If GitHub fails the change for another reason.
        """

    @abstractmethod
    def actions_enabled(self) -> bool | None:
        """
        :return: Whether GitHub Actions may run in the repository, ``None`` when the
            credential may not read that.
        :raises GitHubRequestFailed: If GitHub fails the read for another reason.
        """

    @abstractmethod
    def turn_on_actions(self) -> bool:
        """
        Let GitHub Actions run in the repository.

        :return: Whether GitHub accepted the change; ``False`` only when the credential
            may not make it.
        :raises GitHubRequestFailed: If GitHub fails the change for another reason.
        """


@dataclass(frozen=True)
class IssueTitleWriter(ABC):
    """
    Rewriting the title of an issue or pull request, a pull request being an issue to
    GitHub too.
    """

    @abstractmethod
    def set_issue_title(self, number: int, title: str) -> None:
        """
        Rewrite an issue's title and nothing else.

        :param number: The issue to write.
        :param title: The new title.
        """


@dataclass(frozen=True)
class CommentReader(ABC):
    """
    Reads the comments on a repository's issues and pull requests.
    """

    @abstractmethod
    def comments(self, number: int) -> list[IssueComment]:
        """
        :param number: The issue or pull request to read.
        :return: Its comments, oldest first.
        """


class IssueBoard(LabelWriter, Commenter, IssueTitleWriter, CommentReader, ABC):
    """
    Filing, listing, labelling, rewriting and closing a repository's issues.
    """

    @abstractmethod
    def open_issue(self, title: str, body: str, labels: Sequence[str]) -> int:
        """
        :param title: The issue's title.
        :param body: Its description.
        :param labels: The labels it is filed with.
        :return: The new issue's number.
        """

    @abstractmethod
    def issues(self, labels: Sequence[str], state: IssueState) -> list[Issue]:
        """
        :param labels: Labels every listed issue carries.
        :param state: Whether to list open or closed issues.
        :return: The issues, pull requests left out.
        """

    @abstractmethod
    def issue(self, number: int) -> Issue:
        """
        :param number: The issue to read.
        :return: That issue.
        :raises NotAnIssueError: If the number belongs to a pull request.
        """

    @abstractmethod
    def add_labels(self, number: int, labels: Sequence[str]) -> None:
        """
        Add labels, leaving every label the issue already carries in place.

        :param number: The issue or pull request to write.
        :param labels: The labels it must carry afterwards.
        """

    @abstractmethod
    def remove_label(self, number: int, label: str) -> None:
        """
        Remove one label, leaving every other label in place.

        :param number: The issue or pull request to write.
        :param label: A label it carries.
        """

    @abstractmethod
    def close_issue(self, number: int, reason: IssueStateReason) -> None:
        """
        :param number: The issue to close.
        :param reason: Why it is closed.
        """

    @abstractmethod
    def set_issue_description(self, number: int, body: str) -> None:
        """
        Rewrite an issue's description and nothing else.

        :param number: The issue to write.
        :param body: The new description.
        """


@dataclass(frozen=True)
class ReviewRequests(ABC):
    """
    The repository's pull requests waiting on the credential's account.
    """

    @abstractmethod
    def awaiting_my_review(self) -> int:
        """
        :return: How many of the repository's open pull requests ask the account for a
            review.
        """


@dataclass(frozen=True)
class CommitChecks(ABC):
    """
    Reading the verdict over the checks reported on one commit.
    """

    @abstractmethod
    def check_state(self, commit: str) -> RollupState:
        """:param commit: The commit the checks ran on.
        :return: The verdict over every check run and commit status reported on it."""


@dataclass(frozen=True)
class CredentialHolder(ABC):
    """
    Telling whose credential a client calls GitHub with.
    """

    @abstractmethod
    def authenticated_login(self) -> str:
        """:return: The login of the account the credential belongs to."""


@dataclass(frozen=True)
class PullRequestListingSpecification:
    """
    One filter the pull request list API takes: what it is asked for by, and which
    :class:`PullRequestState` values it lets through.
    """

    query: str
    """
    The value the list API's ``state`` parameter takes for this filter.
    """

    states: tuple[PullRequestState, ...]
    """
    The pull request states this filter lets through.
    """


class PullRequestListState(PullRequestListingSpecification, Enum):
    """
    The pull request states the list API filters on: open, no longer open, and every
    state at once.

    Each member *is* a :class:`PullRequestListingSpecification`, written as its fields
    in declaration order - ``query``, then ``states`` - which the enum passes straight to
    the dataclass.
    """

    OPEN = PullRequestState.OPEN.value, (PullRequestState.OPEN,)
    """
    Pull requests whose state is :attr:`PullRequestState.OPEN`: drafts and those ready
    for review alike.
    """

    CLOSED = PullRequestState.CLOSED.value, (
        PullRequestState.CLOSED,
        PullRequestState.MERGED,
    )
    """
    Pull requests that are no longer open: closed unmerged and merged alike, which REST
    reports under one state.
    """

    ALL = "all", tuple(PullRequestState)
    """
    Every pull request, whatever its :class:`PullRequestState`.
    """


# %% roles: what one caller reads and writes of one repository


@dataclass(frozen=True)
class IssueTracker(IssueBoard, RepositoryLabels, ABC):
    """
    A repository's issues, and the labels it can give them.
    """


@dataclass(frozen=True)
class IssueLabelTracker(IssueTracker, IssueLabelHistory, ABC):
    """
    A repository's issues and labels, and in which order its issues' labels were added.
    """


@dataclass(frozen=True)
class IssueAndPullRequestTracker(PullRequestReader, IssueTracker, ABC):
    """
    A repository's issues and labels, and reading its pull requests.
    """


@dataclass(frozen=True)
class ClosablePullRequests(IssueAndPullRequestTracker, PullRequestCloser, ABC):
    """
    A repository's pull requests as far as closing them with a comment and a label goes:
    reading and closing them, and its issues and labels, a pull request being an issue
    to GitHub too.
    """


@dataclass(frozen=True)
class RewritablePullRequests(
    PullRequestReader, RepositoryDetails, PullRequestWriter, IssueTitleWriter, ABC
):
    """
    A repository's pull requests as far as rewriting their description and title goes,
    and the default branch they may target.
    """


@dataclass(frozen=True)
class PullRequestTracker(PullRequestReader, RepositoryLabels, ReviewRequests, ABC):
    """
    A repository's pull requests, the labels it can give them, and how many wait on the
    credential's account for review.
    """


@dataclass(frozen=True)
class BranchStacks(PullRequestsFromForks, StackReader, ABC):
    """
    The pull requests opened from a repository's branches, and the native stacks
    holding them.
    """


@dataclass(frozen=True)
class StackHost(
    PullRequestReader, PullRequestBaseWriter, StackReader, StackWriter, ABC
):
    """
    A repository's pull requests as far as stacking them goes: reading them, pointing
    them at another branch, and its native stacks.
    """


@dataclass(frozen=True)
class RepositoryFeatures(
    RepositorySettings, RepositoryDiscussions, RepositoryWorkflows, ABC
):
    """
    The features of a repository a tool relies on: its settings, its Discussions and its
    Actions workflows.
    """


@dataclass(frozen=True)
class FollowedFork(
    PullRequestReader, RepositoryDetails, ForkDetails, StackReader, CommentReader, ABC
):
    """
    A fork, as far as following its pull requests upstream goes: its pull requests, their
    comments and the stacks holding them, its default branch and what it was forked
    from.
    """


@dataclass(frozen=True)
class ForkedRepository(PullRequestsFromForks, ForkDetails, ABC):
    """
    A repository that may be a fork: what it was forked from, and the pull requests
    opened from its branches.
    """


@dataclass(frozen=True)
class ForkCommenter(ForkDetails, Commenter, ABC):
    """
    A fork, as far as commenting on its pull requests about the repository it was
    forked from goes.
    """


@dataclass(frozen=True)
class UpstreamRepository(PullRequestsFromForks, RepositoryDetails, ABC):
    """
    The repository a fork was forked from, as far as proposing a fork's pull request
    there goes: its pull requests from forks, and its default branch.
    """


@dataclass(frozen=True)
class ProposingFork(
    UpstreamRepository,
    ForkedRepository,
    LabelWriter,
    ForkCommenter,
    RepositoryLabels,
    ABC,
):
    """
    A fork, as far as proposing its pull requests upstream goes: its pull requests and
    default branch, what it was forked from, and commenting on and labelling them.
    """


# %% the client that makes the calls


@dataclass(frozen=True)
class GitHubRepository(
    CredentialHolder,
    PullRequestSearch,
    CommitChecks,
    StackHost,
    IssueLabelTracker,
    RepositoryFeatures,
    PullRequestOpener,
    ForkSync,
    BranchStacks,
    PullRequestTracker,
    ClosablePullRequests,
    FollowedFork,
    ProposingFork,
    RewritablePullRequests,
):
    """
    Every pull-request, stack and label call this tooling makes, against one repository.
    """

    repository: Repository
    """
    The repository to read and write.
    """

    api: RestApi
    """
    Makes the calls.
    """

    @classmethod
    def from_environment(cls, repository: Repository) -> GitHubRepository:
        """
        :param repository: The repository to read and write.
        :return: A client calling with the credential :meth:`GitHubApi.from_environment`
            finds.
        :raises GitHubCredentialUnavailableError: If no token is found.
        """
        return cls(repository, GitHubApi.from_environment())

    @property
    def route(self) -> RepositoryRoute:
        """:return: The repository's paths."""
        return RepositoryRoute(self.repository)

    def open_pull_requests(self) -> list[RestPullRequest]:
        """:return: Every open pull request on the repository, oldest page first."""
        return self._pull_requests_in_state(PullRequestListState.OPEN)

    def all_pull_requests(self) -> list[RestPullRequest]:
        """:return: Every pull request on the repository, open or closed."""
        return self._pull_requests_in_state(PullRequestListState.ALL)

    def issue(self, number: int) -> Issue:
        entry = self.api.get(self.route.issue(number))
        if Issue.is_pull_request(entry):
            raise NotAnIssueError(number)
        return Issue.from_json(entry)

    def _pull_requests_in_state(
        self, state: PullRequestListState
    ) -> list[RestPullRequest]:
        """
        :param state: Which pull requests to list.
        :return: Them, oldest page first.
        """
        listing = self.route.listing(
            self.route.pull_requests, {QueryParameter.STATE: state.query}
        )
        return [
            RestPullRequest.from_json(entry) for entry in self._every_entry(listing)
        ]

    def labels(self) -> set[str]:
        return {
            label[RestJSONKey.NAME]
            for label in self._every_entry(self.route.listing(self.route.labels))
        }

    def create_label(self, label: GitHubLabel) -> None:
        payload = {RestJSONKey.NAME: label, RestJSONKey.DESCRIPTION: label.description}
        if label.color is not None:
            payload[RestJSONKey.COLOR] = label.color
        self.api.request("POST", self.route.labels, payload)

    def check_state(self, commit: str) -> RollupState:
        checks = CommitCheckReader(self.api, self.route).checks(commit)
        return RollupState.NOT_REPORTED if checks is None else checks.state

    def authenticated_login(self) -> str:
        account = self.api.get(self.route.authenticated_user())
        return str(account[RestJSONKey.LOGIN])

    def _every_entry(self, listing: str) -> list[Any]:
        """
        :param listing: A paged listing whose pages are lists.
        :return: Every entry of every page, first page first.
        """
        return [entry for page in self.api.get_pages(listing) for entry in page]

    def pull_request(self, number: int) -> RestPullRequest:
        return RestPullRequest.from_json(self.api.get(self.route.pull_request(number)))

    def replace_labels(self, number: int, labels: Sequence[str]) -> None:
        """
        Write a pull request's complete label set.

        :param number: The pull request to write.
        :param labels: The complete set it must end up with - this call replaces rather
            than adds.
        """
        self.api.request(
            "PUT", self.route.issue_labels(number), {RestJSONKey.LABELS: list(labels)}
        )

    def add_labels(self, number: int, labels: Sequence[str]) -> None:
        self.api.request(
            "POST", self.route.issue_labels(number), {RestJSONKey.LABELS: list(labels)}
        )

    def remove_label(self, number: int, label: str) -> None:
        self.api.request("DELETE", self.route.issue_label(number, label))

    def add_comment(self, number: int, body: str) -> str:
        """:param number: The pull request to comment on.
        :param body: The comment.
        :return: The comment's URL."""
        created = self.api.request(
            "POST", self.route.issue_comments(number), {RestJSONKey.BODY: body}
        )
        return str(created[RestJSONKey.HTML_URL])

    def label_events(self, number: int) -> list[LabelEvent]:
        return [
            LabelEvent.from_json(entry)
            for entry in self._every_entry(
                self.route.listing(self.route.issue_events(number))
            )
            if LabelEvent.is_label_event(entry)
        ]

    def comments(self, number: int) -> list[IssueComment]:
        return [
            IssueComment.from_json(entry)
            for entry in self._every_entry(
                self.route.listing(self.route.issue_comments(number))
            )
        ]

    def set_description(self, number: int, body: str) -> None:
        """
        Rewrite a pull request's description and nothing else.

        :param number: The pull request to write.
        :param body: The new description.
        """
        self.api.request(
            "PATCH", self.route.pull_request(number), {RestJSONKey.BODY: body}
        )

    def open_draft(
        self, head: BranchName, base: BranchName, title: str, body: str
    ) -> int:
        created = self.api.request(
            "POST",
            self.route.pull_requests,
            {
                RestJSONKey.HEAD: head,
                RestJSONKey.BASE: base,
                RestJSONKey.TITLE: title,
                RestJSONKey.BODY: body,
                RestJSONKey.DRAFT: True,
            },
        )
        return int(created[RestJSONKey.NUMBER])

    def default_branch(self) -> BranchName:
        return RestRepository.from_json(self.api.get(self.route.root)).default_branch

    def upstream(self) -> Repository | None:
        return RestRepository.from_json(self.api.get(self.route.root)).upstream

    def workflows(self) -> list[Workflow]:
        return [
            Workflow.from_json(entry)
            for page in self.api.get_pages(self.route.listing(self.route.workflows))
            for entry in page[RestJSONKey.WORKFLOWS]
        ]

    def search_branch_pull_requests(
        self, author: str, branch: BranchName
    ) -> list[SearchedPullRequest]:
        found = self.api.get(self.route.pull_request_search(author, branch))
        return [
            SearchedPullRequest.from_json(item) for item in found[RestJSONKey.ITEMS]
        ]

    def branch_runs(self, branch: BranchName) -> list[WorkflowRun]:
        listed = self.api.get(self.route.workflow_runs(branch))
        return [
            WorkflowRun.from_json(entry) for entry in listed[RestJSONKey.WORKFLOW_RUNS]
        ]

    def sync_with_upstream(self, branch: BranchName) -> None:
        self.api.request(
            "POST", self.route.merge_upstream, {RestJSONKey.BRANCH: branch}
        )

    def fork_branch_pull_requests(
        self, owner: str, branch: BranchName
    ) -> list[RestPullRequest]:
        return [
            RestPullRequest.from_json(entry)
            for entry in self._every_entry(
                self.route.pull_requests_for_head(owner, branch)
            )
        ]

    def open_fork_pull_request(
        self, owner: str, branch: BranchName, base: BranchName, title: str, body: str
    ) -> RestPullRequest:
        created = self.api.request(
            "POST",
            self.route.pull_requests,
            {
                RestJSONKey.HEAD: f"{owner}:{branch}",
                RestJSONKey.BASE: base,
                RestJSONKey.TITLE: title,
                RestJSONKey.BODY: body,
                RestJSONKey.DRAFT: False,
            },
        )
        return RestPullRequest.from_json(created)

    def deletes_merged_branches(self) -> bool:
        return RestRepository.from_json(
            self.api.get(self.route.root)
        ).deletes_merged_branches

    def turn_on_merged_branch_deletion(self) -> bool:
        return self._change_setting(
            "PATCH", self.route.root, {RestJSONKey.DELETE_BRANCH_ON_MERGE: True}
        )

    def issues_enabled(self) -> bool:
        return RestRepository.from_json(self.api.get(self.route.root)).issues_enabled

    def discussions_enabled(self) -> bool:
        return RestRepository.from_json(
            self.api.get(self.route.root)
        ).discussions_enabled

    def turn_on_issues(self) -> bool:
        return self._change_setting(
            "PATCH", self.route.root, {RestJSONKey.HAS_ISSUES: True}
        )

    def actions_enabled(self) -> bool | None:
        permissions = self.api.attempt("GET", self.route.actions_permissions)
        if permissions.refused:
            return None
        permissions.raise_if_failed("GET", self.route.actions_permissions)
        return bool(permissions.body[RestJSONKey.ENABLED])

    def turn_on_actions(self) -> bool:
        return self._change_setting(
            "PUT", self.route.actions_permissions, {RestJSONKey.ENABLED: True}
        )

    def _change_setting(self, method: str, path: str, payload: dict[str, Any]) -> bool:
        """
        :param method: The HTTP method of the change.
        :param path: The path it is made at.
        :param payload: The change.
        :return: Whether GitHub accepted it; ``False`` only when the credential may not
            make it.
        :raises GitHubRequestFailed: If GitHub fails it for another reason.
        """
        answer = self.api.attempt(method, path, payload)
        if answer.refused:
            return False
        answer.raise_if_failed(method, path)
        return True

    def open_issue(self, title: str, body: str, labels: Sequence[str]) -> int:
        created = self.api.request(
            "POST",
            self.route.issues(),
            {
                RestJSONKey.TITLE: title,
                RestJSONKey.BODY: body,
                RestJSONKey.LABELS: list(labels),
            },
        )
        return int(created[RestJSONKey.NUMBER])

    def issues(self, labels: Sequence[str], state: IssueState) -> list[Issue]:
        listing = self.route.listing(
            self.route.issues(),
            {QueryParameter.LABELS: ",".join(labels), QueryParameter.STATE: state},
        )
        return [
            Issue.from_json(entry)
            for entry in self._every_entry(listing)
            if not Issue.is_pull_request(entry)
        ]

    def close_issue(self, number: int, reason: IssueStateReason) -> None:
        self.api.request(
            "PATCH",
            self.route.issue(number),
            {RestJSONKey.STATE: IssueState.CLOSED, RestJSONKey.STATE_REASON: reason},
        )

    def set_issue_title(self, number: int, title: str) -> None:
        self.api.request("PATCH", self.route.issue(number), {RestJSONKey.TITLE: title})

    def set_issue_description(self, number: int, body: str) -> None:
        self.api.request("PATCH", self.route.issue(number), {RestJSONKey.BODY: body})

    def awaiting_my_review(self) -> int:
        found = self.api.get(self.route.review_requests())
        return int(found[RestJSONKey.TOTAL_COUNT])

    def set_base(self, number: int, branch: BranchName) -> None:
        self.api.request(
            "PATCH", self.route.pull_request(number), {RestJSONKey.BASE: branch}
        )

    def close_pull_request(self, number: int) -> None:
        self.api.request(
            "PATCH",
            self.route.pull_request(number),
            {RestJSONKey.STATE: PullRequestState.CLOSED},
        )

    def stacks(self) -> list[Stack]:
        return [
            Stack.from_json(entry)
            for entry in self._every_entry(self.route.listing(self.route.stacks))
        ]

    def stack(self, number: int) -> Stack:
        return Stack.from_json(self.api.get(self.route.stack(number)))

    def containing_stack(self, pull_request: int) -> Stack | None:
        found = self.api.get(self.route.stacks_holding(pull_request))
        return Stack.from_json(found[0]) if found else None

    def create_stack(self, pull_requests: Sequence[int]) -> Stack:
        return Stack.from_json(
            self.api.request(
                "POST",
                self.route.stacks,
                {RestJSONKey.PULL_REQUESTS: list(pull_requests)},
            )
        )

    def add_to_stack(self, stack: Stack, pull_requests: Sequence[int]) -> Stack:
        return Stack.from_json(
            self.api.request(
                "POST",
                self.route.stack_action(stack.number, StackAction.ADD),
                {RestJSONKey.PULL_REQUESTS: list(pull_requests)},
            )
        )

    def unstack(self, stack: Stack) -> Stack | None:
        remaining = self.api.request(
            "POST", self.route.stack_action(stack.number, StackAction.UNSTACK)
        )
        return None if remaining is None else Stack.from_json(remaining)
