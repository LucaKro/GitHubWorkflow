"""
The contract every model of GitHub's data keeps, and the fixed values GitHub's data is
written in.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from enum import StrEnum
from typing import Any, Self, TypeVar

from domain_model.github.exceptions import (
    NoCheckOutcomesError,
    UnrecognisedGitHubValueError,
)
from domain_model.locations import PackageLocation

# %% the reading contract


class JSONModel(ABC):
    """
    A dataclass mirroring one object GitHub returns, able to read itself from it.

    Declaring the reader here is what lets :meth:`PullRequestJSONKey.read_list` call
    it on any model. Without it the shared name would be a convention every model
    is trusted to have followed, and a model that spelled it differently would fail
    only when something happened to parse that field.

    Every response is parsed into these models as soon as it arrives, and every
    decision after that is made on their attributes, never on the raw object. A
    reader reads its own object's fields and hands each nested object to that
    object's own model, so no access path into a response is spelled out twice.
    """

    @classmethod
    @abstractmethod
    def from_json(cls, data: dict[str, Any]) -> JSONModel:
        """
        Read one of these out of the object GitHub returned.

        :param data: The object to read.
        :return: The parsed model.
        """


ParsedItem = TypeVar("ParsedItem", bound=JSONModel)
"""
Whatever model a list-valued field is being parsed into.
"""


# %% GraphQL vocabulary


class PullRequestJSONKey(StrEnum):
    """
    Every field name read out of a GraphQL response.

    Named once here so a key is never spelled twice, and so a rename in the query
    document has exactly one place to follow.
    """

    DATA = "data"
    ERRORS = "errors"
    MESSAGE = "message"
    REPOSITORY = "repository"
    PULL_REQUEST = "pullRequest"
    NODES = "nodes"
    PAGE_INFO = "pageInfo"
    HAS_NEXT_PAGE = "hasNextPage"
    END_CURSOR = "endCursor"
    IDENTIFIER = "id"
    IS_RESOLVED = "isResolved"
    IS_OUTDATED = "isOutdated"
    PATH = "path"
    LINE = "line"
    COMMENTS = "comments"
    DATABASE_IDENTIFIER = "databaseId"
    AUTHOR = "author"
    LOGIN = "login"
    BODY = "body"
    CREATED_AT = "createdAt"
    URL = "url"
    REVIEW_THREADS = "reviewThreads"
    QUERY = "query"
    VARIABLES = "variables"

    def read_list(
        self, data: dict[str, Any], model: type[ParsedItem]
    ) -> list[ParsedItem]:
        """
        Parse every entry of the list-valued field this key names.

        GitHub returns a list-valued field as an object holding the array under
        ``nodes`` rather than as the array itself, so that step happens here rather
        than at each call site.

        :param data: The object the field belongs to.
        :param model: The model to parse each entry into.
        :return: The parsed entries, in the order GitHub returned them.
        """
        entries = data[self][PullRequestJSONKey.NODES]
        return [model.from_json(entry) for entry in entries]


class QueryVariable(StrEnum):
    """
    The variables the query documents declare.
    """

    OWNER = "owner"
    NAME = "name"
    NUMBER = "number"
    THREAD_CURSOR = "threadCursor"
    THREAD_ID = "threadId"


class GraphQLDocument(StrEnum):
    """
    The query documents, stored as ``.graphql`` files in :attr:`PackageLocation.QUERIES`.
    """

    REVIEW_THREADS_PAGE = "review_threads_page"
    RESOLVE_REVIEW_THREAD = "resolve_review_thread"

    def read(self) -> str:
        """:return: The document's text."""
        return (PackageLocation.QUERIES / f"{self}.graphql").read_text()


class GitHubVocabulary(StrEnum):
    """
    A fixed set of values GitHub reports, read by member name or by value.
    """

    @classmethod
    def from_name(cls, name: str) -> Self:
        """
        :param name: A value as GitHub spells it, which names a member.
        :return: The member it names.
        :raises UnrecognisedGitHubValueError: If no member has that name.
        """
        if name not in cls.__members__:
            raise UnrecognisedGitHubValueError(cls, name)
        return cls[name]

    @classmethod
    def from_value(cls, value: str) -> Self:
        """
        :param value: A value as GitHub spells it, which is a member's value.
        :return: The member with that value.
        :raises UnrecognisedGitHubValueError: If no member has that value.
        """
        if value not in cls:
            raise UnrecognisedGitHubValueError(cls, value)
        return cls(value)


class ReviewState(GitHubVocabulary):
    """
    The verdict a reviewer submitted with a review.

    Members are named as GitHub spells them, so a payload's value is looked up by
    name, and each member's value is how the verdict reads in the report.
    """

    APPROVED = "approved"
    """
    The reviewer approved the changes.
    """

    CHANGES_REQUESTED = "changes requested"
    """
    The reviewer asked for changes before the pull request can merge.
    """

    COMMENTED = "commented"
    """
    The reviewer left comments without a verdict.
    """

    DISMISSED = "dismissed"
    """
    The review was dismissed and no longer counts towards the verdict.
    """

    PENDING = "pending"
    """
    The review was started but not yet submitted.
    """


class PullRequestState(GitHubVocabulary):
    """
    Where a pull request stands in its lifecycle.

    Members are named as GraphQL spells them, so a GraphQL payload's value is looked up
    by name. Each member's value is how REST spells it, where REST has one: REST reports
    a merged pull request as closed, with a merge time.
    """

    OPEN = "open"
    """
    Open, as a draft or ready for review.
    """

    CLOSED = "closed"
    """
    Closed without being merged through GitHub.
    """

    MERGED = "merged"
    """
    Merged through GitHub.
    """


class RollupState(GitHubVocabulary):
    """
    The verdict GitHub itself computes over all of a pull request's checks, or that
    nothing has reported one yet.

    Members are named as GitHub spells them, so a payload's value is looked up by
    name, and each member's value is how the verdict reads in the report.
    """

    failed: bool
    """
    Whether at least one check failed or reported an error.
    """

    def __new__(cls, value: str, failed: bool) -> RollupState:
        member = str.__new__(cls, value)
        member._value_ = value
        member.failed = failed
        return member

    SUCCESS = "success", False
    """
    Every check passed.
    """

    FAILURE = "failure", True
    """
    At least one check failed.
    """

    ERROR = "error", True
    """
    At least one commit status reported an error.
    """

    PENDING = "pending", False
    """
    At least one check has not finished yet.
    """

    EXPECTED = "expected", False
    """
    At least one required commit status has not been reported yet.
    """

    NOT_REPORTED = "not reported", False
    """
    No check run or commit status has been reported at all.
    """

    @classmethod
    def from_outcomes(cls, outcomes: list[CheckOutcome]) -> RollupState:
        """
        Compute the verdict GitHub would over a set of checks, for a source that does
        not report one: the worst any single check would give.

        :param outcomes: Every check's outcome.
        :return: The verdict.
        :raises NoCheckOutcomesError: If *outcomes* is empty.
        """
        if not outcomes:
            raise NoCheckOutcomesError()
        reached = {outcome.rolls_up_to for outcome in outcomes}
        return next(state for state in cls.severity_order() if state in reached)

    @classmethod
    def severity_order(cls) -> list[RollupState]:
        """
        :return: Every verdict a reported check can give, worst first.
        """
        return [cls.FAILURE, cls.ERROR, cls.PENDING, cls.EXPECTED, cls.SUCCESS]


class CheckOutcome(GitHubVocabulary):
    """
    Where one check stands, a check run and a commit status alike.

    Members are named as GitHub spells them, so a payload's value is looked up by
    name, and each member's value is how the outcome reads in the report. A check run
    that has not finished reports no conclusion at all, which reads here as
    :attr:`PENDING` so an unfinished check is never mistaken for a passing one.
    """

    rolls_up_to: RollupState
    """
    The verdict this outcome alone would give the whole rollup, the way GitHub counts
    it: a neutral or skipped check does not hold a pull request back, and everything
    that ended without passing fails it.
    """

    def __new__(cls, value: str, rolls_up_to: RollupState) -> CheckOutcome:
        member = str.__new__(cls, value)
        member._value_ = value
        member.rolls_up_to = rolls_up_to
        return member

    SUCCESS = "success", RollupState.SUCCESS
    """
    The check passed.
    """

    FAILURE = "failure", RollupState.FAILURE
    """
    The check failed.
    """

    ERROR = "error", RollupState.ERROR
    """
    The commit status reported an error.
    """

    CANCELLED = "cancelled", RollupState.FAILURE
    """
    The check run was cancelled before it finished.
    """

    TIMED_OUT = "timed out", RollupState.FAILURE
    """
    The check run exceeded its time limit.
    """

    ACTION_REQUIRED = "action required", RollupState.FAILURE
    """
    The check run needs someone to act before it can conclude.
    """

    NEUTRAL = "neutral", RollupState.SUCCESS
    """
    The check run finished without passing or failing.
    """

    SKIPPED = "skipped", RollupState.SUCCESS
    """
    The check run was skipped.
    """

    STALE = "stale", RollupState.FAILURE
    """
    GitHub marked the check run stale after it went too long without finishing.
    """

    STARTUP_FAILURE = "startup failure", RollupState.FAILURE
    """
    The check run failed before it could start.
    """

    PENDING = "pending", RollupState.PENDING
    """
    The check has not finished yet.
    """

    EXPECTED = "expected", RollupState.EXPECTED
    """
    A required commit status that has not been reported yet.
    """


class ThreadMarker(StrEnum):
    """
    The annotations a thread can carry in the report.
    """

    RESOLVED = "resolved"
    OUTDATED = "outdated"


# %% REST vocabulary


class RestJSONKey(StrEnum):
    """
    Every field name read out of a REST response.

    REST spells its fields apart from GraphQL, so they are named here rather than shared
    with :class:`PullRequestJSONKey`.
    """

    NUMBER = "number"
    TITLE = "title"
    HTML_URL = "html_url"
    STATE = "state"
    MERGED_AT = "merged_at"
    HEAD = "head"
    SHA = "sha"
    USER = "user"
    BODY = "body"
    SUBMITTED_AT = "submitted_at"
    IDENTIFIER = "id"
    CREATED_AT = "created_at"
    RESOLVED = "resolved"
    OUTDATED = "outdated"
    PATH = "path"
    LINE = "line"
    COMMENT_IDENTIFIERS = "comment_ids"
    CHECK_RUNS = "check_runs"
    NAME = "name"
    CONCLUSION = "conclusion"
    DETAILS_URL = "details_url"
    STATUSES = "statuses"
    CONTEXT = "context"
    TARGET_URL = "target_url"
    DRAFT = "draft"
    BASE = "base"
    LABELS = "labels"
    PULL_REQUEST = "pull_request"
    MERGEABLE_STATE = "mergeable_state"
    LOGIN = "login"
    DESCRIPTION = "description"
    PULL_REQUESTS = "pull_requests"
    OPEN = "open"
    DEFAULT_BRANCH = "default_branch"
    HAS_ISSUES = "has_issues"
    HAS_DISCUSSIONS = "has_discussions"
    EVENT = "event"
    LABEL = "label"
    STATE_REASON = "state_reason"
    REQUESTED_REVIEWERS = "requested_reviewers"
    AHEAD_BY = "ahead_by"
    BEHIND_BY = "behind_by"
    TOTAL_COUNT = "total_count"
    COLOR = "color"
    DELETE_BRANCH_ON_MERGE = "delete_branch_on_merge"
    ENABLED = "enabled"
    ALLOWED_ACTIONS = "allowed_actions"
    WORKFLOW_RUNS = "workflow_runs"
    WORKFLOWS = "workflows"
    ITEMS = "items"
    HEAD_SHA = "head_sha"
    STATUS = "status"
    REFERENCE = "ref"
    REPOSITORY = "repo"
    FULL_NAME = "full_name"
    PARENT = "parent"
    BRANCH = "branch"


# %% issues and workflow runs


class IssueEventType(StrEnum):
    """
    The ``event`` of an issue's event that changes its labels.
    """

    LABELED = "labeled"
    """
    A label added.
    """

    UNLABELED = "unlabeled"
    """
    A label removed.
    """


class IssueState(StrEnum):
    """
    The ``state`` REST reads and writes on an issue or a pull request: the
    :class:`PullRequestState` values REST has, without :attr:`PullRequestState.MERGED`.
    """

    OPEN = PullRequestState.OPEN.value
    """
    Open, a draft pull request included.
    """

    CLOSED = PullRequestState.CLOSED.value
    """
    Closed, a merged pull request included.
    """


class ClosingKeyword(StrEnum):
    """
    A word that, written before an issue's number in a pull request's description,
    closes the issue when the pull request is merged.
    """

    FIXES = "Fixes"
    """
    Closes an issue that reports a bug.
    """

    def reference(self, number: int) -> str:
        """
        :param number: An issue.
        :return: The keyword and the issue, as a description writes them.
        """
        return f"{self} #{number}"


class IssueStateReason(StrEnum):
    """
    Why an issue was closed or reopened.
    """

    COMPLETED = "completed"
    """
    Closed because it was done.
    """

    NOT_PLANNED = "not_planned"
    """
    Closed without being done, because it will not be.
    """

    REOPENED = "reopened"
    """
    Opened again after being closed.
    """


class WorkflowRunStatus(StrEnum):
    """
    Where an Actions workflow run stands.
    """

    QUEUED = "queued"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"


class WorkflowRunConclusion(GitHubVocabulary):
    """
    How a completed Actions workflow run ended.
    """

    SUCCESS = "success"
    FAILURE = "failure"
    CANCELLED = "cancelled"
    SKIPPED = "skipped"
    TIMED_OUT = "timed_out"
    ACTION_REQUIRED = "action_required"
    NEUTRAL = "neutral"
    STALE = "stale"
    STARTUP_FAILURE = "startup_failure"


class WorkflowState(GitHubVocabulary):
    """
    Whether GitHub runs an Actions workflow when its events happen.
    """

    ACTIVE = "active"
    """
    It runs.
    """

    DELETED = "deleted"
    """
    Its file is gone.
    """

    DISABLED_FORK = "disabled_fork"
    """
    Off because the repository is a fork whose workflows were not turned on.
    """

    DISABLED_INACTIVITY = "disabled_inactivity"
    """
    Turned off by GitHub after the repository saw no activity for a while.
    """

    DISABLED_MANUALLY = "disabled_manually"
    """
    Turned off by someone.
    """


# %% pull request mergeability


class MergeableState(GitHubVocabulary):
    """
    The values GitHub reports as a pull request's ``mergeable_state``.

    Whether a branch conflicts with its base is read from :attr:`conflicts`.
    """

    conflicts: bool | None
    """
    Whether the branch conflicts with its base, ``None`` when this state does not say:
    GitHub has not computed it yet, or reports a draft as a draft whether or not it
    conflicts.
    """

    def __new__(cls, value: str, conflicts: bool | None) -> MergeableState:
        member = str.__new__(cls, value)
        member._value_ = value
        member.conflicts = conflicts
        return member

    DIRTY = "dirty", True
    """
    The branch conflicts with its base.
    """

    CLEAN = "clean", False
    """
    Mergeable, with every required check passing.
    """

    UNSTABLE = "unstable", False
    """
    Mergeable, with a check that is not required failing.
    """

    BLOCKED = "blocked", False
    """
    Mergeable once a required review or check passes.
    """

    BEHIND = "behind", False
    """
    Mergeable once brought up to date with its base.
    """

    HAS_HOOKS = "has_hooks", False
    """
    Mergeable, with pre-receive hooks configured.
    """

    DRAFT = "draft", None
    """
    A draft, which cannot be merged until it is marked ready.
    """

    UNKNOWN = "unknown", None
    """
    Not yet computed by GitHub.
    """


# %% the GitHub command line and hosts


class GitHubCliReading(StrEnum):
    """
    The ``gh`` commands that only read, by their first two words.
    """

    PULL_REQUEST_VIEW = "pr view"
    """
    Shows a pull request.
    """

    PULL_REQUEST_LIST = "pr list"
    """
    Lists pull requests.
    """

    PULL_REQUEST_DIFF = "pr diff"
    """
    Shows a pull request's changes.
    """

    PULL_REQUEST_CHECKS = "pr checks"
    """
    Shows a pull request's checks.
    """

    PULL_REQUEST_STATUS = "pr status"
    """
    Shows the pull requests relevant to the signed-in account.
    """

    ISSUE_VIEW = "issue view"
    """
    Shows an issue.
    """

    ISSUE_LIST = "issue list"
    """
    Lists issues.
    """

    ISSUE_STATUS = "issue status"
    """
    Shows the issues relevant to the signed-in account.
    """

    RUN_VIEW = "run view"
    """
    Shows an Actions run.
    """

    RUN_LIST = "run list"
    """
    Lists Actions runs.
    """

    RUN_WATCH = "run watch"
    """
    Follows an Actions run until it ends.
    """

    REPOSITORY_VIEW = "repo view"
    """
    Shows a repository.
    """

    RELEASE_VIEW = "release view"
    """
    Shows a release.
    """

    RELEASE_LIST = "release list"
    """
    Lists releases.
    """

    WORKFLOW_VIEW = "workflow view"
    """
    Shows an Actions workflow.
    """

    WORKFLOW_LIST = "workflow list"
    """
    Lists Actions workflows.
    """

    AUTHENTICATION_STATUS = "auth status"
    """
    Shows which account gh is signed in as.
    """


class GitHubCliSubcommand(StrEnum):
    """
    The ``gh`` subcommands judged by their arguments rather than their name.
    """

    API = "api"
    """
    A raw API call, which reads unless given a method, a field or an input, or, to
    GraphQL, a document holding anything but queries.
    """

    SEARCH = "search"
    """
    A search, which only reads.
    """


class GraphQLOperation(StrEnum):
    """
    The kinds of operation a GraphQL document holds.
    """

    QUERY = "query"
    """
    Reads.
    """

    MUTATION = "mutation"
    """
    Writes.
    """

    SUBSCRIPTION = "subscription"
    """
    Waits for changes, so it never finishes as a read does.
    """


class GitHubHost(StrEnum):
    """
    The hosts whose addresses mark a ``curl`` or ``wget`` call as one to GitHub.
    """

    WEB = "github.com"
    """
    GitHub and its API, ``api.github.com``.
    """

    CONTENT = "githubusercontent.com"
    """
    GitHub's raw file host.
    """


# %% REST queries


class QueryParameter(StrEnum):
    """
    The query parameters the REST paths take.
    """

    STATE = "state"
    """
    Which entries to list, by state.
    """

    PAGE_SIZE = "per_page"
    """
    How many entries one page holds.
    """

    HEAD = "head"
    """
    The branch pull requests are listed for, as ``owner:branch``.
    """

    PULL_REQUEST = "pull_request"
    """
    The pull request a listed stack must hold.
    """

    BRANCH = "branch"
    """
    The branch listed workflow runs were triggered on.
    """

    LABELS = "labels"
    """
    The labels a listed issue must all carry, comma-separated.
    """

    SEARCH = "q"
    """
    The search query.
    """


class StackAction(StrEnum):
    """
    What is done to a stack, each at a path segment of that name below it.
    """

    ADD = "add"
    """
    Put pull requests on top.
    """

    UNSTACK = "unstack"
    """
    Take the pull requests out again.
    """
