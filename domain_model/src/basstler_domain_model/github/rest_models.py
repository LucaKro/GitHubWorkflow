"""
Models of GitHub's REST responses, each parsed into a typed model as it arrives.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from basstler_domain_model.class_property import classproperty
from basstler_domain_model.github.exceptions import (
    MissingPullRequestFieldError,
    ReviewThreadWithoutCommentsError,
)
from basstler_domain_model.github.pull_request_models import CheckResult
from basstler_domain_model.github.review_models import (
    Author,
    BranchPullRequest,
    ReviewThread,
    ThreadComment,
)
from basstler_domain_model.github.vocabulary import (
    JSONModel,
    MergeableState,
    PullRequestState,
    RestJSONKey,
    WorkflowRunConclusion,
    WorkflowRunStatus,
    WorkflowState,
)
from basstler_domain_model.repository import Repository

# %% a pull request


@dataclass(frozen=True)
class BranchComparison(JSONModel):
    """
    How far one branch is ahead of and behind another, as REST compares them.
    """

    ahead_by: int
    """
    The commits the compared branch has that the one it is compared against lacks.
    """

    behind_by: int
    """
    The commits the compared branch lacks that the one it is compared against has.
    """

    @classmethod
    def from_json(cls, data: dict[str, Any]) -> BranchComparison:
        """
        Read a comparison.

        :param data: The object to read.
        :return: The parsed comparison.
        """
        return cls(
            ahead_by=data[RestJSONKey.AHEAD_BY], behind_by=data[RestJSONKey.BEHIND_BY]
        )


@dataclass(frozen=True)
class PullRequestHead(JSONModel):
    """
    The branch a pull request would merge, where it lives, and the commit it is at.
    """

    branch: str
    """
    The head branch's name.
    """

    repository: str | None
    """
    The ``owner/name`` of the repository the head branch lives in, ``None`` once that
    repository is deleted.
    """

    commit: str
    """
    The commit the head branch points at, which the checks are reported against.
    """

    owner: Author
    """
    Whoever owns the head branch.
    """

    @classmethod
    def from_json(cls, data: dict[str, Any]) -> PullRequestHead:
        """
        Read a ``head`` object.

        :param data: The object to read.
        :return: The parsed head.
        """
        repository = data[RestJSONKey.REPOSITORY]
        return cls(
            branch=data[RestJSONKey.REFERENCE],
            repository=(
                None if repository is None else repository[RestJSONKey.FULL_NAME]
            ),
            commit=data[RestJSONKey.SHA],
            owner=Author.from_json(data[RestJSONKey.USER]),
        )


@dataclass(frozen=True)
class RestPullRequest(JSONModel):
    """
    One pull request as REST describes it, whether listed or read on its own.
    """

    number: int
    """
    Its number in the repository.
    """

    title: str
    """
    Its title.
    """

    body: str | None
    """
    Its description, ``None`` when it has none.
    """

    url: str
    """
    Its page on GitHub.
    """

    state: PullRequestState
    """
    Whether it is open or closed, as REST reports it: a merged one reads as closed.
    """

    merged: bool
    """
    Whether it closed by merging through GitHub.
    """

    draft: bool
    """
    Whether it is still a draft.
    """

    head: PullRequestHead
    """
    The branch it would merge.
    """

    base: str
    """
    The branch it would merge into.
    """

    labels: tuple[str, ...]
    """
    The names of the labels it carries.
    """

    mergeable_state: MergeableState | None
    """
    GitHub's verdict on whether it can merge, ``None`` where GitHub does not report one,
    as in a listing.
    """

    @classproperty
    def required_keys(cls) -> tuple[RestJSONKey, ...]:
        """
        The keys a pull request cannot be read without.
        """
        return (
            RestJSONKey.NUMBER,
            RestJSONKey.TITLE,
            RestJSONKey.HTML_URL,
            RestJSONKey.STATE,
            RestJSONKey.DRAFT,
            RestJSONKey.HEAD,
            RestJSONKey.BASE,
            RestJSONKey.LABELS,
        )

    @classmethod
    def from_json(cls, data: dict[str, Any]) -> RestPullRequest:
        """
        Read a pull request object.

        :param data: The object to read.
        :return: The parsed pull request.
        :raises MissingPullRequestFieldError: If a key it cannot be read without is
            absent, or its head does not say where it lives or which commit it is at.
        """
        number = data.get(RestJSONKey.NUMBER)
        missing = [key for key in cls.required_keys if data.get(key) is None]
        if missing:
            raise MissingPullRequestFieldError(missing[0], number)
        head = data[RestJSONKey.HEAD]
        if RestJSONKey.REPOSITORY not in head or not head.get(RestJSONKey.SHA):
            raise MissingPullRequestFieldError(RestJSONKey.HEAD, number)
        mergeable_state = data.get(RestJSONKey.MERGEABLE_STATE)
        return cls(
            number=number,
            title=data[RestJSONKey.TITLE],
            body=data.get(RestJSONKey.BODY),
            url=data[RestJSONKey.HTML_URL],
            state=PullRequestState.from_value(data[RestJSONKey.STATE]),
            merged=data.get(RestJSONKey.MERGED_AT) is not None,
            draft=data[RestJSONKey.DRAFT],
            head=PullRequestHead.from_json(head),
            base=data[RestJSONKey.BASE][RestJSONKey.REFERENCE],
            labels=tuple(label[RestJSONKey.NAME] for label in data[RestJSONKey.LABELS]),
            mergeable_state=(
                None
                if mergeable_state is None
                else MergeableState.from_value(mergeable_state)
            ),
        )

    @property
    def branch_pull_request(self) -> BranchPullRequest:
        """
        :return: The summary a branch search compares, in the lifecycle GraphQL names.
        """
        return BranchPullRequest(
            number=self.number,
            state=PullRequestState.MERGED if self.merged else self.state,
            head_owner=self.head.owner,
        )


# %% a repository


@dataclass(frozen=True)
class RestRepository(JSONModel):
    """
    The repository itself, as REST describes it.
    """

    default_branch: str
    """
    The branch pull requests target unless told otherwise.
    """

    deletes_merged_branches: bool
    """
    Whether GitHub deletes a pull request's branch once it is merged.
    """

    issues_enabled: bool
    """
    Whether the repository has issues turned on.
    """

    discussions_enabled: bool
    """
    Whether the repository has Discussions turned on.
    """

    upstream: Repository | None
    """
    The repository it was forked from, ``None`` when it is no fork.
    """

    @classmethod
    def from_json(cls, data: dict[str, Any]) -> RestRepository:
        """
        Read a repository object.

        :param data: The object to read.
        :return: The parsed repository.
        """
        return cls(
            default_branch=data[RestJSONKey.DEFAULT_BRANCH],
            deletes_merged_branches=data[RestJSONKey.DELETE_BRANCH_ON_MERGE],
            issues_enabled=data[RestJSONKey.HAS_ISSUES],
            discussions_enabled=data[RestJSONKey.HAS_DISCUSSIONS],
            upstream=(
                Repository.parse(data[RestJSONKey.PARENT][RestJSONKey.FULL_NAME])
                if RestJSONKey.PARENT in data
                else None
            ),
        )


# %% searched pull requests


@dataclass(frozen=True)
class SearchedPullRequest(JSONModel):
    """
    A pull request as GitHub's issue search finds it.
    """

    number: int
    """
    Its number.
    """

    url: str
    """
    Its page on GitHub.
    """

    merged_at: str | None
    """
    When it was merged, ``None`` while it is not.
    """

    @classmethod
    def from_json(cls, data: dict[str, Any]) -> SearchedPullRequest:
        """
        Read one item of an issue search's answer.

        :param data: The item to read.
        :return: The parsed pull request.
        """
        return cls(
            number=data[RestJSONKey.NUMBER],
            url=data[RestJSONKey.HTML_URL],
            merged_at=data[RestJSONKey.PULL_REQUEST][RestJSONKey.MERGED_AT],
        )


# %% Actions workflows


@dataclass(frozen=True)
class Workflow(JSONModel):
    """
    An Actions workflow, from a file on any of the repository's branches.
    """

    name: str
    """
    The name its file gives it.
    """

    path: str
    """
    Its file, relative to the repository's root.
    """

    state: WorkflowState
    """
    Whether GitHub runs it.
    """

    @classmethod
    def from_json(cls, data: dict[str, Any]) -> Workflow:
        """
        Read a workflow object.

        :param data: The object to read.
        :return: The parsed workflow.
        """
        return cls(
            name=data[RestJSONKey.NAME],
            path=data[RestJSONKey.PATH],
            state=WorkflowState.from_value(data[RestJSONKey.STATE]),
        )


@dataclass(frozen=True)
class WorkflowRun(JSONModel):
    """
    One run of an Actions workflow.
    """

    identifier: int
    """
    The run's number in GitHub's records.
    """

    path: str
    """
    The file of the workflow run.
    """

    commit: str
    """
    The commit whose push or event started it.
    """

    status: WorkflowRunStatus
    """
    Where it stands.
    """

    conclusion: WorkflowRunConclusion | None
    """
    How it ended, ``None`` until it completed.
    """

    url: str
    """
    Its page on GitHub, with its log.
    """

    @classmethod
    def from_json(cls, data: dict[str, Any]) -> WorkflowRun:
        """
        Read a workflow run object.

        :param data: The object to read.
        :return: The parsed run.
        """
        conclusion = data[RestJSONKey.CONCLUSION]
        return cls(
            identifier=data[RestJSONKey.IDENTIFIER],
            path=data[RestJSONKey.PATH],
            commit=data[RestJSONKey.HEAD_SHA],
            status=WorkflowRunStatus(data[RestJSONKey.STATUS]),
            conclusion=(
                None
                if conclusion is None
                else WorkflowRunConclusion.from_value(conclusion)
            ),
            url=data[RestJSONKey.HTML_URL],
        )


# %% review threads


@dataclass(frozen=True)
class RestReviewThread(JSONModel):
    """
    One review thread, as a Claude Code session's proxy reports it: its state and
    location, and the comments in it named by identifier only.
    """

    is_resolved: bool
    """
    Whether a reviewer has marked the thread resolved.
    """

    is_outdated: bool
    """
    Whether the diff hunk the thread was anchored to has since changed.
    """

    path: str
    """
    The file the thread is attached to.
    """

    line: int | None
    """
    The line the thread is attached to, absent once the hunk is outdated.
    """

    comment_identifiers: list[int]
    """
    The comments in the thread, oldest first.
    """

    def __post_init__(self) -> None:
        """
        :raises ReviewThreadWithoutCommentsError: If the thread names no comments.
        """
        if not self.comment_identifiers:
            raise ReviewThreadWithoutCommentsError(self.path, self.line)

    @classmethod
    def from_json(cls, data: dict[str, Any]) -> RestReviewThread:
        """
        Read a review thread object.

        :param data: The object to read.
        :return: The parsed thread.
        """
        return cls(
            is_resolved=data[RestJSONKey.RESOLVED],
            is_outdated=data[RestJSONKey.OUTDATED],
            path=data[RestJSONKey.PATH],
            line=data[RestJSONKey.LINE],
            comment_identifiers=list(data[RestJSONKey.COMMENT_IDENTIFIERS]),
        )

    def thread(self, comments: dict[int, ThreadComment]) -> ReviewThread:
        """
        Fill the thread in with its comments.

        The route carries no identifier of the thread's own, so its first comment's
        stands in for one. A comment deleted since the comments were listed is left out
        rather than failing the whole read.

        :param comments: Every comment on the pull request, by identifier.
        :return: The thread, as the report reads it.
        """
        return ReviewThread(
            identifier=str(self.comment_identifiers[0]),
            is_resolved=self.is_resolved,
            is_outdated=self.is_outdated,
            path=self.path,
            line=self.line,
            comments=[
                comments[identifier]
                for identifier in self.comment_identifiers
                if identifier in comments
            ],
        )


# %% checks on a commit


@dataclass(frozen=True)
class RestCheckRunPage(JSONModel):
    """
    One page of the check runs reported against a commit.
    """

    check_runs: list[CheckResult]
    """
    The check runs on this page.
    """

    @classmethod
    def from_json(cls, data: dict[str, Any]) -> RestCheckRunPage:
        """
        Read one page of the check-runs listing.

        :param data: The page to read.
        :return: The parsed page.
        """
        return cls(
            [
                CheckResult.from_check_run_json(run)
                for run in data[RestJSONKey.CHECK_RUNS]
            ]
        )


@dataclass(frozen=True)
class RestCombinedStatusPage(JSONModel):
    """
    One page of the statuses posted against a commit.

    Its own combined state is left unread: GitHub reports it pending when nothing has
    posted at all, which would misreport a commit no status applies to.
    """

    statuses: list[CheckResult]
    """
    The statuses on this page.
    """

    @classmethod
    def from_json(cls, data: dict[str, Any]) -> RestCombinedStatusPage:
        """
        Read one page of the combined status.

        :param data: The page to read.
        :return: The parsed page.
        """
        return cls(
            [
                CheckResult.from_commit_status_json(status)
                for status in data[RestJSONKey.STATUSES]
            ]
        )
