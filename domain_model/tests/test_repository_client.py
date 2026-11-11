"""
Tests for the repository client's calls that open a pull request and read the repository
itself, against replayed REST answers.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass, field
from http import HTTPStatus
from typing import Any
from urllib.parse import parse_qs, urlsplit

import pytest

from domain_model.github.clients import GitHubApi, RestAnswer, RestApi
from domain_model.github.exceptions import GitHubRequestFailed, NotAnIssueError
from domain_model.github.issue_models import Issue, IssueComment, LabelEvent
from domain_model.github.labels import GitHubLabel
from domain_model.github.replayed_api import RecordedAnswer, ReplayedApi
from domain_model.github.repository_client import GitHubRepository
from domain_model.github.rest_models import BranchComparison
from domain_model.github.routes import QueryParameter, RepositoryRoute
from domain_model.github.vocabulary import (
    ClosingKeyword,
    IssueEventType,
    IssueState,
    IssueStateReason,
    PullRequestState,
    RestJSONKey,
    WorkflowRunConclusion,
    WorkflowRunStatus,
    WorkflowState,
)
from domain_model.repository import Repository

from .dataset.locations import DatasetLocation

REPOSITORY = Repository("an-owner", "a-repository")
"""
The repository every call in these tests is made against.
"""

ROUTE = RepositoryRoute(REPOSITORY)
"""
Its REST paths.
"""

# %% helpers


def client(api: ReplayedApi) -> GitHubRepository:
    """:param api: The replayed API.
    :return: A client calling it."""
    return GitHubRepository(REPOSITORY, GitHubApi("a-token", api.url))


def answer(status: HTTPStatus, body: dict[str, object]) -> RecordedAnswer:
    """:param status: The status to answer with.
    :param body: The body to answer with.
    :return: The answer."""
    return RecordedAnswer(status, json.dumps(body))


def recorded_repository() -> dict[str, object]:
    """:return: The repository as REST describes it."""
    return json.loads(DatasetLocation.REPOSITORY.read_text())


def repository_answers() -> dict[tuple[str, str], RecordedAnswer]:
    """:return: The repository's own path, answered with its recording."""
    return {
        ("GET", f"/{ROUTE.root}"): RecordedAnswer.from_file(
            HTTPStatus.OK, DatasetLocation.REPOSITORY
        )
    }


# %% forks


def test_a_fork_names_the_repository_it_was_forked_from():
    answers = {
        ("GET", f"/{ROUTE.root}"): RecordedAnswer.from_file(
            HTTPStatus.OK, DatasetLocation.FORK
        )
    }

    with ReplayedApi(answers) as api:
        upstream = client(api).upstream()

    parent = json.loads(DatasetLocation.FORK.read_text())[RestJSONKey.PARENT]
    assert upstream == Repository.parse(parent[RestJSONKey.FULL_NAME])


def test_a_repository_forked_from_none_has_no_upstream():
    with ReplayedApi(repository_answers()) as api:
        assert client(api).upstream() is None


# %% searched pull requests


def test_pull_requests_opened_from_a_branch_are_searched_with_when_they_merged():
    path = ROUTE.pull_request_search("LucaKro", "feature")
    answers = {
        ("GET", f"/{path}"): RecordedAnswer.from_file(
            HTTPStatus.OK, DatasetLocation.SEARCHED_PULL_REQUESTS
        )
    }

    with ReplayedApi(answers) as api:
        found = client(api).search_branch_pull_requests("LucaKro", "feature")

    items = json.loads(DatasetLocation.SEARCHED_PULL_REQUESTS.read_text())[
        RestJSONKey.ITEMS
    ]
    assert [(each.number, each.merged_at) for each in found] == [
        (
            item[RestJSONKey.NUMBER],
            item[RestJSONKey.PULL_REQUEST][RestJSONKey.MERGED_AT],
        )
        for item in items
    ]


# %% Actions workflows


def test_the_workflows_are_read_with_whether_github_runs_them():
    answers = {
        ("GET", f"/{ROUTE.listing(ROUTE.workflows)}"): RecordedAnswer.from_file(
            HTTPStatus.OK, DatasetLocation.WORKFLOWS
        )
    }

    with ReplayedApi(answers) as api:
        workflows = client(api).workflows()

    recorded = json.loads(DatasetLocation.WORKFLOWS.read_text())[RestJSONKey.WORKFLOWS]
    assert [(workflow.path, workflow.state) for workflow in workflows] == [
        (entry[RestJSONKey.PATH], WorkflowState.from_value(entry[RestJSONKey.STATE]))
        for entry in recorded
    ]


def test_a_branch_s_runs_are_read_newest_first():
    answers = {
        ("GET", f"/{ROUTE.workflow_runs('github-workflow/notes')}"): (
            RecordedAnswer.from_file(HTTPStatus.OK, DatasetLocation.WORKFLOW_RUNS)
        )
    }

    with ReplayedApi(answers) as api:
        runs = client(api).branch_runs("github-workflow/notes")

    recorded = json.loads(DatasetLocation.WORKFLOW_RUNS.read_text())
    assert [(run.identifier, run.status, run.conclusion) for run in runs] == [
        (
            entry[RestJSONKey.IDENTIFIER],
            WorkflowRunStatus(entry[RestJSONKey.STATUS]),
            (
                None
                if entry[RestJSONKey.CONCLUSION] is None
                else WorkflowRunConclusion.from_value(entry[RestJSONKey.CONCLUSION])
            ),
        )
        for entry in recorded[RestJSONKey.WORKFLOW_RUNS]
    ]


def test_a_pull_request_is_opened_from_a_fork_s_branch_ready_for_review():
    answers = {
        ("POST", f"/{ROUTE.pull_requests}"): RecordedAnswer.from_file(
            HTTPStatus.CREATED, DatasetLocation.PULL_REQUEST_OPEN
        )
    }

    with ReplayedApi(answers) as api:
        opened = client(api).open_fork_pull_request(
            "a-fork-owner", "a-branch", "trunk", "A title", "A body"
        )

    assert api.sent[0].payload == {
        RestJSONKey.HEAD: "a-fork-owner:a-branch",
        RestJSONKey.BASE: "trunk",
        RestJSONKey.TITLE: "A title",
        RestJSONKey.BODY: "A body",
        RestJSONKey.DRAFT: False,
    }
    recorded = json.loads(DatasetLocation.PULL_REQUEST_OPEN.read_text())
    assert opened.number == recorded[RestJSONKey.NUMBER]


def test_the_pull_requests_from_a_fork_s_branch_are_listed():
    listing = ROUTE.pull_requests_for_head("a-fork-owner", "a-branch")
    recorded = json.loads(DatasetLocation.PULL_REQUEST_OPEN.read_text())
    answers = {("GET", f"/{listing}"): answer(HTTPStatus.OK, [recorded])}

    with ReplayedApi(answers) as api:
        found = client(api).fork_branch_pull_requests("a-fork-owner", "a-branch")

    assert [pull_request.number for pull_request in found] == [
        recorded[RestJSONKey.NUMBER]
    ]


def test_only_the_open_pull_requests_from_a_fork_s_branch_are_kept_open():
    listing = ROUTE.pull_requests_for_head("a-fork-owner", "a-branch")
    opened = json.loads(DatasetLocation.PULL_REQUEST_OPEN.read_text())
    merged = json.loads(DatasetLocation.REST_PULL_REQUEST_MERGED.read_text())
    answers = {("GET", f"/{listing}"): answer(HTTPStatus.OK, [merged, opened])}

    with ReplayedApi(answers) as api:
        found = client(api).open_fork_branch_pull_requests("a-fork-owner", "a-branch")

    assert [pull_request.number for pull_request in found] == [
        opened[RestJSONKey.NUMBER]
    ]


def test_a_branch_is_compared_with_another_repository_s_branch():
    compared = ROUTE.comparison("trunk", "an-upstream:a-repository:main")
    answers = {
        ("GET", f"/{compared}"): answer(
            HTTPStatus.OK,
            {
                RestJSONKey.STATUS: "ahead",
                RestJSONKey.AHEAD_BY: 2,
                RestJSONKey.BEHIND_BY: 0,
            },
        )
    }

    with ReplayedApi(answers) as api:
        comparison = client(api).compare("trunk", "an-upstream:a-repository:main")

    assert comparison == BranchComparison(ahead_by=2, behind_by=0)


def test_a_fork_s_branch_is_synced_with_its_upstream():
    answers = {
        ("POST", f"/{ROUTE.merge_upstream}"): answer(
            HTTPStatus.OK, {"merge_type": "fast-forward"}
        )
    }

    with ReplayedApi(answers) as api:
        client(api).sync_with_upstream("trunk")

    assert api.sent[0].payload == {RestJSONKey.BRANCH: "trunk"}


# %% opening a pull request


def test_a_draft_is_opened_from_the_head_onto_the_base():
    answers = {
        ("POST", f"/{ROUTE.pull_requests}"): answer(
            HTTPStatus.CREATED, {RestJSONKey.NUMBER: 7}
        )
    }

    with ReplayedApi(answers) as api:
        number = client(api).open_draft("feature", "main", "A title", "A body")

    assert number == 7
    assert api.sent[0].payload == {
        RestJSONKey.HEAD: "feature",
        RestJSONKey.BASE: "main",
        RestJSONKey.TITLE: "A title",
        RestJSONKey.BODY: "A body",
        RestJSONKey.DRAFT: True,
    }


# %% the repository itself


def test_the_default_branch_is_read_from_the_repository():
    with ReplayedApi(repository_answers()) as api:
        assert (
            client(api).default_branch()
            == recorded_repository()[RestJSONKey.DEFAULT_BRANCH]
        )


def test_whether_merged_branches_are_deleted_is_read_from_the_repository():
    with ReplayedApi(repository_answers()) as api:
        assert (
            client(api).deletes_merged_branches()
            is recorded_repository()[RestJSONKey.DELETE_BRANCH_ON_MERGE]
        )


# %% changing settings


def test_turning_on_merged_branch_deletion_asks_github_for_it():
    answers = {
        ("PATCH", f"/{ROUTE.root}"): answer(
            HTTPStatus.OK, {RestJSONKey.DELETE_BRANCH_ON_MERGE: True}
        )
    }

    with ReplayedApi(answers) as api:
        accepted = client(api).turn_on_merged_branch_deletion()

    assert accepted is True
    assert api.sent[0].payload == {RestJSONKey.DELETE_BRANCH_ON_MERGE: True}


def test_a_refused_settings_change_is_reported_rather_than_raised():
    answers = {
        ("PATCH", f"/{ROUTE.root}"): answer(
            HTTPStatus.FORBIDDEN, {"message": "settings writes are not permitted"}
        )
    }

    with ReplayedApi(answers) as api:
        assert client(api).turn_on_merged_branch_deletion() is False


@pytest.mark.parametrize("status", [HTTPStatus.FORBIDDEN, HTTPStatus.NOT_FOUND])
def test_a_settings_change_the_credential_may_not_make_is_not_made(
    status: HTTPStatus,
) -> None:
    answers = {("PATCH", f"/{ROUTE.root}"): answer(status, {})}

    with ReplayedApi(answers) as api:
        assert client(api).turn_on_issues() is False


def test_a_settings_change_github_fails_on_is_raised() -> None:
    answers = {("PATCH", f"/{ROUTE.root}"): answer(HTTPStatus.BAD_GATEWAY, {})}

    with ReplayedApi(answers) as api:
        with pytest.raises(GitHubRequestFailed) as raised:
            client(api).turn_on_issues()

    assert raised.value.status == HTTPStatus.BAD_GATEWAY


def test_actions_permissions_github_fails_to_answer_are_raised() -> None:
    answers = {
        ("GET", f"/{ROUTE.actions_permissions}"): answer(
            HTTPStatus.INTERNAL_SERVER_ERROR, {}
        )
    }

    with ReplayedApi(answers) as api:
        with pytest.raises(GitHubRequestFailed) as raised:
            client(api).actions_enabled()

    assert raised.value.status == HTTPStatus.INTERNAL_SERVER_ERROR


# %% issues and Actions


def test_whether_issues_are_on_is_read_from_the_repository():
    with ReplayedApi(repository_answers()) as api:
        assert (
            client(api).issues_enabled()
            is recorded_repository()[RestJSONKey.HAS_ISSUES]
        )


def test_whether_discussions_are_on_is_read_from_the_repository():
    with ReplayedApi(repository_answers()) as api:
        assert (
            client(api).discussions_enabled()
            is recorded_repository()[RestJSONKey.HAS_DISCUSSIONS]
        )


def test_turning_on_issues_asks_github_for_them():
    answers = {("PATCH", f"/{ROUTE.root}"): answer(HTTPStatus.OK, {})}

    with ReplayedApi(answers) as api:
        accepted = client(api).turn_on_issues()

    assert accepted is True
    assert api.sent[0].payload == {RestJSONKey.HAS_ISSUES: True}


def test_whether_actions_may_run_is_read_from_their_permissions():
    answers = {
        ("GET", f"/{ROUTE.actions_permissions}"): answer(
            HTTPStatus.OK, {RestJSONKey.ENABLED: False}
        )
    }

    with ReplayedApi(answers) as api:
        assert client(api).actions_enabled() is False


def test_actions_a_credential_may_not_read_are_unknown():
    answers = {
        ("GET", f"/{ROUTE.actions_permissions}"): answer(
            HTTPStatus.FORBIDDEN, {"message": "not permitted"}
        )
    }

    with ReplayedApi(answers) as api:
        assert client(api).actions_enabled() is None


def test_turning_on_actions_asks_github_for_them():
    answers = {("PUT", f"/{ROUTE.actions_permissions}"): answer(HTTPStatus.OK, {})}

    with ReplayedApi(answers) as api:
        accepted = client(api).turn_on_actions()

    assert accepted is True
    assert api.sent[0].payload == {RestJSONKey.ENABLED: True}


# %% the issue board


def issue_entry(number: int, labels: list[str]) -> dict[str, object]:
    """:param number: The issue's number.
    :param labels: The names of its labels.
    :return: The issue as the issues API lists it."""
    return {
        RestJSONKey.NUMBER: number,
        RestJSONKey.TITLE: f"Issue {number}",
        RestJSONKey.LABELS: [{RestJSONKey.NAME: label} for label in labels],
        RestJSONKey.STATE: IssueState.OPEN.value,
    }


def test_an_issue_is_filed_with_its_labels():
    answers = {
        ("POST", f"/{ROUTE.issues()}"): answer(
            HTTPStatus.CREATED, {RestJSONKey.NUMBER: 12}
        )
    }

    with ReplayedApi(answers) as api:
        number = client(api).open_issue("A title", "A body", ["finding"])

    assert number == 12
    assert api.sent[0].payload == {
        RestJSONKey.TITLE: "A title",
        RestJSONKey.BODY: "A body",
        RestJSONKey.LABELS: ["finding"],
    }


def test_listed_issues_leave_the_pull_requests_out():
    listing = ROUTE.listing(
        ROUTE.issues(),
        {QueryParameter.LABELS: "finding", QueryParameter.STATE: IssueState.OPEN},
    )
    pull_request = {**issue_entry(2, ["finding"]), RestJSONKey.PULL_REQUEST: {}}
    answers = {
        ("GET", f"/{listing}"): RecordedAnswer(
            HTTPStatus.OK, json.dumps([issue_entry(1, ["finding"]), pull_request])
        )
    }

    with ReplayedApi(answers) as api:
        issues = client(api).issues(["finding"], IssueState.OPEN)

    assert issues == [Issue(1, "Issue 1", ("finding",), IssueState.OPEN)]


def test_one_issue_is_read_with_its_labels():
    answers = {
        ("GET", f"/{ROUTE.issue(4)}"): answer(
            HTTPStatus.OK, issue_entry(4, ["finding", "urgent"])
        )
    }

    with ReplayedApi(answers) as api:
        issue = client(api).issue(4)

    assert issue == Issue(4, "Issue 4", ("finding", "urgent"), IssueState.OPEN)


def test_reading_a_pull_request_as_an_issue_is_refused():
    pull_request = {**issue_entry(5, []), RestJSONKey.PULL_REQUEST: {}}
    answers = {("GET", f"/{ROUTE.issue(5)}"): answer(HTTPStatus.OK, pull_request)}

    with ReplayedApi(answers) as api, pytest.raises(NotAnIssueError):
        client(api).issue(5)


def test_added_labels_are_sent_alone():
    answers = {("POST", f"/{ROUTE.issue_labels(6)}"): answer(HTTPStatus.OK, {})}

    with ReplayedApi(answers) as api:
        client(api).add_labels(6, ["finding", "urgent"])

    assert api.sent[0].payload == {RestJSONKey.LABELS: ["finding", "urgent"]}


def test_a_removed_label_is_named_in_the_path():
    answers = {
        ("DELETE", f"/{ROUTE.issue_label(7, 'priority: low')}"): answer(
            HTTPStatus.OK, {}
        )
    }

    with ReplayedApi(answers) as api:
        client(api).remove_label(7, "priority: low")

    assert [request.method for request in api.sent] == ["DELETE"]


def test_a_slash_in_an_issue_label_stays_within_its_path_segment():
    assert ROUTE.issue_label(8, "type/bug") == f"{ROUTE.issue_labels(8)}/type%2Fbug"


def test_a_slash_in_a_repository_label_stays_within_its_path_segment() -> None:
    assert ROUTE.label("type/bug") == f"{ROUTE.labels}/type%2Fbug"


def test_an_issue_is_closed_with_its_reason():
    answers = {("PATCH", f"/{ROUTE.issue(3)}"): answer(HTTPStatus.OK, {})}

    with ReplayedApi(answers) as api:
        client(api).close_issue(3, IssueStateReason.NOT_PLANNED)

    assert api.sent[0].payload == {
        RestJSONKey.STATE: IssueState.CLOSED,
        RestJSONKey.STATE_REASON: IssueStateReason.NOT_PLANNED,
    }


def test_a_pull_request_is_closed_without_being_merged():
    answers = {("PATCH", f"/{ROUTE.pull_request(4)}"): answer(HTTPStatus.OK, {})}

    with ReplayedApi(answers) as api:
        client(api).close_pull_request(4)

    assert api.sent[0].payload == {RestJSONKey.STATE: PullRequestState.CLOSED}


def test_an_issue_s_title_is_set_and_nothing_else():
    answers = {("PATCH", f"/{ROUTE.issue(3)}"): answer(HTTPStatus.OK, {})}

    with ReplayedApi(answers) as api:
        client(api).set_issue_title(3, "A sharper title")

    assert api.sent[0].payload == {RestJSONKey.TITLE: "A sharper title"}


def test_an_issue_s_description_is_set_and_nothing_else():
    answers = {("PATCH", f"/{ROUTE.issue(3)}"): answer(HTTPStatus.OK, {})}

    with ReplayedApi(answers) as api:
        client(api).set_issue_description(3, "What was found, corrected.")

    assert api.sent[0].payload == {RestJSONKey.BODY: "What was found, corrected."}


def test_a_label_with_a_colour_is_created_in_it():
    class ColouredLabel(GitHubLabel):
        description = "A coloured label"
        color = "b60205"

    answers = {("POST", f"/{ROUTE.labels}"): answer(HTTPStatus.CREATED, {})}

    with ReplayedApi(answers) as api:
        client(api).create_label(ColouredLabel("urgent"))

    assert api.sent[0].payload == {
        RestJSONKey.NAME: "urgent",
        RestJSONKey.DESCRIPTION: ColouredLabel.description,
        RestJSONKey.COLOR: ColouredLabel.color,
    }


def test_an_issue_s_label_events_are_read_oldest_first_without_other_events():
    listing = ROUTE.listing(ROUTE.issue_events(9))
    entries = [
        {
            RestJSONKey.EVENT: IssueEventType.LABELED,
            RestJSONKey.LABEL: {RestJSONKey.NAME: "a"},
        },
        {RestJSONKey.EVENT: "closed"},
        {
            RestJSONKey.EVENT: IssueEventType.UNLABELED,
            RestJSONKey.LABEL: {RestJSONKey.NAME: "a"},
        },
        {
            RestJSONKey.EVENT: IssueEventType.LABELED,
            RestJSONKey.LABEL: {RestJSONKey.NAME: "b"},
        },
    ]
    answers = {
        ("GET", f"/{listing}"): RecordedAnswer(HTTPStatus.OK, json.dumps(entries))
    }

    with ReplayedApi(answers) as api:
        events = client(api).label_events(9)

    assert events == [
        LabelEvent("a", True),
        LabelEvent("a", False),
        LabelEvent("b", True),
    ]


def test_an_issue_s_comments_are_read_with_their_authors():
    listing = ROUTE.listing(ROUTE.issue_comments(9))
    entries = [
        {RestJSONKey.USER: {RestJSONKey.LOGIN: "an-owner"}, RestJSONKey.BODY: "First"},
        {RestJSONKey.USER: {RestJSONKey.LOGIN: "someone"}, RestJSONKey.BODY: "Second"},
    ]
    answers = {
        ("GET", f"/{listing}"): RecordedAnswer(HTTPStatus.OK, json.dumps(entries))
    }

    with ReplayedApi(answers) as api:
        comments = client(api).comments(9)

    assert comments == [
        IssueComment("an-owner", "First"),
        IssueComment("someone", "Second"),
    ]


def test_a_closing_reference_is_the_keyword_before_the_issue_s_number():
    assert ClosingKeyword.FIXES.reference(3) == f"{ClosingKeyword.FIXES} #3"


# %% against any REST API


@dataclass
class RestAnswersInMemory(RestApi):
    """
    Answers every call with one recorded answer, keeping each call made.
    """

    answer: RestAnswer
    """
    What every call is answered with.
    """

    calls: list[tuple[str, str, Any]] = field(default_factory=list)
    """
    The method, path and payload of every call, in order.
    """

    def attempt(
        self, method: str, path: str, payload: Mapping[str, Any] | None = None
    ) -> RestAnswer:
        self.calls.append((method, path, payload))
        return self.answer

    def request(
        self, method: str, path: str, payload: Mapping[str, Any] | None = None
    ) -> Any:
        return self.attempt(method, path, payload).raise_if_failed(method, path).body

    def get(self, path: str) -> Any:
        return self.request("GET", path)

    def get_pages(self, path: str) -> list[Any]:
        return [self.get(path)]


def test_a_repository_writes_through_any_rest_api() -> None:
    api = RestAnswersInMemory(RestAnswer(HTTPStatus.OK, "{}"))

    GitHubRepository(REPOSITORY, api).set_base(4, "main")

    assert api.calls == [("PATCH", ROUTE.pull_request(4), {RestJSONKey.BASE: "main"})]


# %% review requests


def test_the_pull_requests_awaiting_my_review_are_counted():
    answers = {
        ("GET", f"/{ROUTE.review_requests()}"): answer(
            HTTPStatus.OK, {RestJSONKey.TOTAL_COUNT: 2, "items": []}
        )
    }

    with ReplayedApi(answers) as api:
        assert client(api).awaiting_my_review() == 2


def test_only_the_repository_s_review_requests_are_searched():
    query = parse_qs(urlsplit(ROUTE.review_requests()).query)

    assert f"repo:{REPOSITORY.full_name}" in query[QueryParameter.SEARCH][0].split()
