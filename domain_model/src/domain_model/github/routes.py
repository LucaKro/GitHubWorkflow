"""
The REST paths the API is called at, each built in one place.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import quote, urlencode

from domain_model.class_property import classproperty
from domain_model.git.revisions import BranchName
from domain_model.github.vocabulary import QueryParameter, StackAction
from domain_model.repository import Repository

# %% the paths


@dataclass(frozen=True)
class RepositoryRoute:
    """
    Every REST path below one repository, and the few beside it, as the API takes them.
    """

    repository: Repository
    """
    The repository the paths are under.
    """

    @classproperty
    def page_size(cls) -> int:
        """
        The most entries GitHub hands back per page, asked for so a long list takes as
        few requests as it can.
        """
        return 100

    def listing(
        self, path: str, filters: Mapping[QueryParameter, str | int] | None = None
    ) -> str:
        """
        :param path: A listing's path.
        :param filters: Query parameters narrowing the listing.
        :return: Its first page, as large as GitHub hands out.
        """
        query = {**(filters or {}), QueryParameter.PAGE_SIZE: self.page_size}
        return f"{path}?{urlencode(query, safe=':')}"

    @property
    def root(self) -> str:
        """:return: The repository itself."""
        return self.repository.api_path

    @property
    def pull_requests(self) -> str:
        """:return: The repository's pull requests."""
        return f"{self.root}/pulls"

    @property
    def branches(self) -> str:
        """:return: The repository's branches."""
        return f"{self.root}/branches"

    @property
    def merge_upstream(self) -> str:
        """:return: The bringing of a fork's branch up to its upstream's."""
        return f"{self.root}/merge-upstream"

    def pull_requests_for_head(self, owner: str, branch: BranchName) -> str:
        """
        :param owner: Whose branch to search for.
        :param branch: The branch's name.
        :return: The search for pull requests opened from it, in any state.
        """
        return self.listing(
            self.pull_requests,
            {QueryParameter.HEAD: f"{owner}:{branch}", QueryParameter.STATE: "all"},
        )

    def pull_request(self, number: int) -> str:
        """
        :param number: The pull request's number.
        :return: The pull request itself.
        """
        return f"{self.pull_requests}/{number}"

    def reviews(self, number: int) -> str:
        """
        :param number: The pull request's number.
        :return: Its submitted reviews.
        """
        return self.listing(f"{self.pull_request(number)}/reviews")

    def review_comments(self, number: int) -> str:
        """
        :param number: The pull request's number.
        :return: Every review comment on it, across all its threads.
        """
        return self.listing(f"{self.pull_request(number)}/comments")

    def review_comment_replies(self, number: int, comment: int) -> str:
        """
        :param number: The pull request's number.
        :param comment: A review comment on it, the first of its thread.
        :return: The replies to that comment's thread.
        """
        return f"{self.pull_request(number)}/comments/{comment}/replies"

    def thread_resolution(self, number: int, comment: int) -> str:
        """
        The resolving of a thread - a route of the Claude Code session proxy's own,
        standing in for the GraphQL GitHub keeps resolving behind.

        :param number: The pull request's number.
        :param comment: The first comment of the thread to resolve.
        :return: The resolving of that thread.
        """
        return f"{self.pull_request(number)}/ccr/comments/{comment}/resolve"

    def review_threads(self, number: int) -> str:
        """
        The threads with their resolved state - a route of the Claude Code session
        proxy's own, standing in for the GraphQL GitHub keeps that state behind, which
        answers with every thread at once.

        :param number: The pull request's number.
        :return: Its review threads.
        """
        return f"{self.pull_request(number)}/ccr/review_threads"

    def check_runs(self, sha: str) -> str:
        """
        :param sha: The commit.
        :return: The check runs reported against it.
        """
        return self.listing(f"{self.root}/commits/{sha}/check-runs")

    def commit_status(self, sha: str) -> str:
        """
        :param sha: The commit.
        :return: The statuses posted against it.
        """
        return self.listing(f"{self.root}/commits/{sha}/status")

    def issues(self, **filters: str) -> str:
        """
        :param filters: Query parameters narrowing the listing.
        :return: The repository's issues, its pull requests among them.
        """
        query = f"?{urlencode(filters)}" if filters else ""
        return f"{self.root}/issues{query}"

    def contents(self, path: Path) -> str:
        """
        :param path: A directory or file of the repository, relative to its root.
        :return: Its content on the default branch: a directory's entries, or the file.
        """
        relative = "" if path == Path() else quote(path.as_posix())
        return f"{self.root}/contents/{relative}"

    def issue(self, number: int) -> str:
        """:param number: The issue or pull request.
        :return: That issue."""
        return f"{self.root}/issues/{number}"

    def issue_events(self, number: int) -> str:
        """:param number: The issue or pull request.
        :return: What happened to it, its labels added and removed among it."""
        return f"{self.issue(number)}/events"

    def issue_comments(self, number: int) -> str:
        """:param number: The issue or pull request.
        :return: Its comments."""
        return f"{self.issue(number)}/comments"

    def issue_labels(self, number: int) -> str:
        """:param number: The issue or pull request.
        :return: The labels it carries."""
        return f"{self.issue(number)}/labels"

    def issue_label(self, number: int, name: str) -> str:
        """
        :param number: The issue or pull request.
        :param name: One label it carries.
        :return: That label on it.
        """
        return f"{self.issue_labels(number)}/{quote(name, safe='')}"

    @property
    def labels(self) -> str:
        """:return: The repository's labels."""
        return f"{self.root}/labels"

    def label(self, name: str) -> str:
        """:param name: The label.
        :return: That label."""
        return f"{self.labels}/{quote(name, safe='')}"

    def comparison(self, base: str, head: str) -> str:
        """
        :param base: The branch compared against.
        :param head: The branch compared.
        :return: How far *head* is ahead of and behind *base*.
        """
        return f"{self.root}/compare/{quote(base)}...{quote(head)}"

    @property
    def actions_permissions(self) -> str:
        """:return: Whether Actions may run in the repository, and which."""
        return f"{self.root}/actions/permissions"

    @property
    def workflows(self) -> str:
        """:return: The repository's Actions workflows, on every branch."""
        return f"{self.root}/actions/workflows"

    def workflow_runs(self, branch: BranchName) -> str:
        """:param branch: The branch the runs were triggered on.
        :return: Its workflow runs, newest first."""
        return f"{self.root}/actions/runs?{urlencode({QueryParameter.BRANCH: branch})}"

    @property
    def stacks(self) -> str:
        """:return: The repository's native stacks of pull requests."""
        return f"{self.root}/stacks"

    def stack(self, number: int) -> str:
        """:param number: The stack.
        :return: That stack."""
        return f"{self.stacks}/{number}"

    def stacks_holding(self, number: int) -> str:
        """:param number: The pull request.
        :return: The stacks holding it."""
        return f"{self.stacks}?{urlencode({QueryParameter.PULL_REQUEST: number})}"

    def stack_action(self, number: int, action: StackAction) -> str:
        """:param number: The stack.
        :param action: What is done to it.
        :return: Where that is asked for."""
        return f"{self.stack(number)}/{action}"

    @staticmethod
    def authenticated_user() -> str:
        """:return: The account the token belongs to."""
        return "user"

    def pull_request_search(self, author: str, branch: BranchName) -> str:
        """
        :param author: Who opened the pull requests.
        :param branch: The branch they were opened from, on any repository.
        :return: The search for the repository's pull requests opened so, in any state.
        """
        terms = f"is:pr repo:{self.repository.full_name} head:{branch} author:{author}"
        return f"search/issues?{urlencode({QueryParameter.SEARCH: terms})}"

    @classmethod
    def issue_search(cls, terms: str) -> str:
        """
        :param terms: The search query.
        :return: The first page of the issues and pull requests it finds, on any
            repository, as large as GitHub hands out.
        """
        query = {QueryParameter.SEARCH: terms, QueryParameter.PAGE_SIZE: cls.page_size}
        return f"search/issues?{urlencode(query)}"

    def review_requests(self) -> str:
        """
        :return: The search for the repository's open pull requests waiting on the
            caller's review.
        """
        terms = f"is:open is:pr review-requested:@me repo:{self.repository.full_name}"
        return f"search/issues?{urlencode({QueryParameter.SEARCH: terms})}"
