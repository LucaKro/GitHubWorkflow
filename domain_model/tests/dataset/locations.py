"""
The files the tests read their payloads from, each named once.
"""

from __future__ import annotations

from pathlib import Path

from basstler_domain_model.locations import PathEnumeration


class DatasetLocation(PathEnumeration):
    """
    The recorded GitHub payloads the tests parse.
    """

    DIRECTORY = Path(__file__).parent
    """
    The directory holding every payload.
    """

    GRAPHQL_BRANCH_PULL_REQUEST_MERGED = (
        DIRECTORY / "graphql-branch-pull-request-merged.json"
    )
    """
    A pull request a GraphQL head-branch search found, merged.
    """

    REST_PULL_REQUEST_MERGED = DIRECTORY / "rest-pull-request-merged.json"
    """
    A pull request as REST describes it once merged: closed, with a merge time.
    """

    REST_PULL_REQUEST_CLOSED_UNMERGED = (
        DIRECTORY / "rest-pull-request-closed-unmerged.json"
    )
    """
    A pull request as REST describes it once closed without merging.
    """

    STACK_CREATED = DIRECTORY / "stacks" / "create.json"
    """
    A stack of two pull requests, as creating it answered.
    """

    STACK_GROWN = DIRECTORY / "stacks" / "add.json"
    """
    The same stack with a third pull request put on top, as adding it answered.
    """

    STACK_READ = DIRECTORY / "stacks" / "get.json"
    """
    The same stack, read by its number.
    """

    STACKS_HOLDING_A_PULL_REQUEST = DIRECTORY / "stacks" / "find.json"
    """
    The stacks holding the stack's middle pull request: the stack itself.
    """

    STACKS_HOLDING_NOTHING = DIRECTORY / "stacks" / "find-none.json"
    """
    The stacks holding a pull request no stack holds: none.
    """

    STACKS_LISTED = DIRECTORY / "stacks" / "list.json"
    """
    Every stack in the repository, one page.
    """

    STACK_WITH_ITS_BOTTOM_MERGED = DIRECTORY / "stacks" / "find-bottom-merged.json"
    """
    The stack found by pull request, its bottom pull request merged.
    """

    GRAPHQL_DATA = DIRECTORY / "api" / "graphql-data.json"
    """
    A GraphQL answer carrying data.
    """

    GRAPHQL_NO_DATA = DIRECTORY / "api" / "graphql-no-data.json"
    """
    A GraphQL response with neither data nor errors.
    """

    GRAPHQL_ERRORS = DIRECTORY / "api" / "graphql-errors.json"
    """
    A GraphQL answer carrying errors instead of data.
    """

    PAGE_ONE = DIRECTORY / "api" / "page-one.json"
    """
    The first page of a listing.
    """

    PAGE_TWO = DIRECTORY / "api" / "page-two.json"
    """
    The second and last page of the same listing.
    """

    JOB_LOG = DIRECTORY / "api" / "job-log.txt"
    """
    A job's log, as blob storage serves it.
    """

    REPOSITORY = DIRECTORY / "api" / "repository.json"
    """
    A repository as REST describes it: trunk as its default branch, issues and the
    deletion of merged branches off.
    """

    FORK = DIRECTORY / "api" / "fork.json"
    """
    A fork as REST describes it, naming the repository it was forked from.
    """

    WORKFLOWS = DIRECTORY / "api" / "workflows.json"
    """
    A repository's workflows, one of them off because the repository is a fork.
    """

    WORKFLOW_RUNS = DIRECTORY / "api" / "workflow-runs.json"
    """
    A branch's runs: one failed, one still going.
    """

    SEARCHED_PULL_REQUESTS = DIRECTORY / "api" / "searched-pull-requests.json"
    """
    Pull requests an issue search found: one merged, one open.
    """

    REFUSAL = DIRECTORY / "api" / "refusal.json"
    """
    The body of a refused call.
    """

    GH_STUB = DIRECTORY / "stubs" / "gh.sh"
    """
    A ``gh`` that only answers ``gh auth token``, with ``STUB_TOKEN``.
    """

    GRAPHQL_BRANCH_SEARCH = DIRECTORY / "readers" / "graphql" / "branch-search.json"
    """
    A head-branch search matching the fork's closed, open and merged pull requests, and
    another owner's.
    """

    GRAPHQL_BRANCH_SEARCH_CLOSED = (
        DIRECTORY / "readers" / "graphql" / "branch-search-closed.json"
    )
    """
    A head-branch search matching only the fork's closed and merged pull requests,
    newest first.
    """

    GRAPHQL_BRANCH_SEARCH_FOREIGN = (
        DIRECTORY / "readers" / "graphql" / "branch-search-foreign.json"
    )
    """
    A head-branch search matching only another owner's pull request.
    """

    GRAPHQL_THREADS_PAGE_ONE = (
        DIRECTORY / "readers" / "graphql" / "threads-page-one.json"
    )
    """
    The first page of a pull request's review threads, with a next page.
    """

    GRAPHQL_THREADS_PAGE_TWO = (
        DIRECTORY / "readers" / "graphql" / "threads-page-two.json"
    )
    """
    The second and last page of the same pull request's review threads.
    """

    REST_PULLS_PAGE_ONE = DIRECTORY / "readers" / "rest" / "pulls-page-one.json"
    """
    The first page of a head-branch listing: the fork's closed pull request.
    """

    REST_PULLS_PAGE_TWO = DIRECTORY / "readers" / "rest" / "pulls-page-two.json"
    """
    The second page of the same listing: the fork's open pull request.
    """

    REST_PULL_REQUEST = DIRECTORY / "readers" / "rest" / "pull-request.json"
    """
    The fork's open pull request, read by its number.
    """

    REST_REVIEWS = DIRECTORY / "readers" / "rest" / "reviews.json"
    """
    Its submitted reviews.
    """

    REST_REVIEW_COMMENTS = DIRECTORY / "readers" / "rest" / "review-comments.json"
    """
    Every review comment on it.
    """

    REST_REVIEW_THREADS = DIRECTORY / "readers" / "rest" / "review-threads.json"
    """
    Its review threads, naming their comments.
    """

    REST_REVIEW_THREAD_WITHOUT_COMMENTS = (
        DIRECTORY / "readers" / "rest" / "review-thread-without-comments.json"
    )
    """
    A review thread naming no comments.
    """

    REST_CHECK_RUNS = DIRECTORY / "readers" / "rest" / "check-runs.json"
    """
    The check runs on its head commit: one passed, one unfinished.
    """

    REST_COMMIT_STATUS = DIRECTORY / "readers" / "rest" / "commit-status.json"
    """
    The commit statuses on its head commit: one failed.
    """

    REST_CHECK_RUNS_NONE = DIRECTORY / "readers" / "rest" / "check-runs-none.json"
    """
    No check runs on a commit.
    """

    REST_COMMIT_STATUS_NONE = DIRECTORY / "readers" / "rest" / "commit-status-none.json"
    """
    No commit statuses on a commit.
    """

    PULL_REQUEST_OPEN = DIRECTORY / "pull_requests" / "open.json"
    """
    An open draft pull request as REST reads it, conflicting with its base.
    """

    PULL_REQUEST_HEAD_REPOSITORY_DELETED = (
        DIRECTORY / "pull_requests" / "head-repository-deleted.json"
    )
    """
    The same pull request, its head repository deleted.
    """

    PULL_REQUEST_WITHOUT_DRAFT = DIRECTORY / "pull_requests" / "without-draft.json"
    """
    The same pull request, missing whether it is a draft.
    """

    PULL_REQUEST_HEAD_WITHOUT_COMMIT = (
        DIRECTORY / "pull_requests" / "head-without-commit.json"
    )
    """
    The same pull request, its head missing the commit it is at.
    """

    SLEEPING_SCRIPT = DIRECTORY / "commands" / "sleeps.py"
    """
    A Python script that sleeps far longer than any test waits for it.
    """

    CHECK_RUN_UNRECOGNISED_CONCLUSION = (
        DIRECTORY / "checks" / "check-run-unrecognised-conclusion.json"
    )
    """
    A rollup's check run, concluded in a way this package does not know.
    """
