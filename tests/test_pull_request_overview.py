"""
Tests for :mod:`github_workflow.pull_request_overview`: one line per open pull request
with the signals that ask for attention, and the details only when asked for.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace

import pytest
from basstler_domain_model.github.labels import GitHubLabel
from basstler_domain_model.github.number_links import NumberLink
from basstler_domain_model.github.pull_request_models import (
    CheckResult,
    CheckStatus,
    UpstreamPullRequestSnapshot,
)
from basstler_domain_model.github.readers import PullRequestSource
from basstler_domain_model.github.repository_client import (
    PullRequestReader,
    RepositoryLabels,
    ReviewRequests,
)
from basstler_domain_model.github.rest_models import RestPullRequest
from basstler_domain_model.github.review_models import (
    Author,
    ReviewThread,
    ThreadComment,
)
from basstler_domain_model.github.vocabulary import CheckOutcome, MergeableState

from github_workflow.pull_request_overview import (
    PullRequestDetails,
    PullRequestGroup,
    PullRequestLabel,
    PullRequestOverview,
    PullRequestSignalReader,
)
from github_workflow.report_lines import (
    CountedThing,
    Emphasis,
    Highlight,
    Speaker,
    Tone,
)
from github_workflow.upstream import UpstreamLabel

from .pull_requests import pull_request

# %% pull requests in memory


def thread(resolved: bool) -> ReviewThread:
    """:param resolved: Whether the thread is resolved.
    :return: A thread with one comment on ``src/a.py`` line 3."""
    comment = ThreadComment(
        database_identifier=1,
        author=Author(login="reviewer"),
        body="Rename this\nand explain why",
        created_at="2026-11-02T00:00:00Z",
        url="https://github.com/LucaKro/project/pull/1#discussion_r1",
    )
    return ReviewThread(
        identifier="thread",
        is_resolved=resolved,
        is_outdated=False,
        path="src/a.py",
        line=3,
        comments=[comment],
    )


@dataclass(frozen=True)
class PullRequestsWithSignals(
    PullRequestReader, PullRequestSource, ReviewRequests, RepositoryLabels
):
    """
    Open pull requests with their merge state, checks, threads and labels, how many wait
    on the person's review, and the repository's labels.
    """

    mergeable: dict[int, MergeableState] = field(default_factory=dict)
    """
    Each pull request's merge state, by number.
    """

    checks: dict[int, CheckStatus | None] = field(default_factory=dict)
    """
    Each pull request's checks, by number.
    """

    threads: dict[int, list[ReviewThread]] = field(default_factory=dict)
    """
    Each pull request's review threads, by number.
    """

    drafts: frozenset[int] = frozenset()
    """
    The pull requests that are drafts.
    """

    waiting: int = 0
    """
    How many pull requests wait on the person's review.
    """

    shelved: frozenset[int] = frozenset()
    """
    The pull requests the person shelved.
    """

    opened_upstream: frozenset[int] = frozenset()
    """
    The pull requests labelled as opened upstream.
    """

    present: set[str] = field(default_factory=set)
    """
    The repository's labels, with each one created.
    """

    def open_pull_requests(self) -> list[RestPullRequest]:
        return [self.pull_request(number) for number in self.mergeable]

    def pull_request(self, number: int) -> RestPullRequest:
        listed = pull_request(
            number,
            f"branch-{number}",
            title=f"Change {number}",
            draft=number in self.drafts,
            mergeable_state=self.mergeable[number],
        )
        shelving = (PullRequestLabel.SHELVED,) if number in self.shelved else ()
        upstream = (
            (UpstreamLabel.OPENED_UPSTREAM,) if number in self.opened_upstream else ()
        )
        return replace(listed, labels=shelving + upstream)

    def resolve_pull_request_number(self, branch: str) -> int:
        return int(branch.removeprefix("branch-"))

    def read_current_state(
        self, pull_request_number: int
    ) -> UpstreamPullRequestSnapshot:
        return UpstreamPullRequestSnapshot(
            number=pull_request_number,
            title=f"Change {pull_request_number}",
            url=f"https://github.com/LucaKro/project/pull/{pull_request_number}",
            reviews=[],
            threads=self.threads.get(pull_request_number, []),
            checks=self.checks.get(pull_request_number),
        )

    def awaiting_my_review(self) -> int:
        return self.waiting

    def labels(self) -> set[str]:
        return set(self.present)

    def create_label(self, label: GitHubLabel) -> None:
        self.present.add(label)

    def overview(self, checked_out: str = "elsewhere") -> PullRequestOverview:
        """:param checked_out: The branch the session works on.
        :return: The section over these pull requests."""
        return PullRequestOverview(
            PullRequestSignalReader(self, self), self, self, checked_out
        )


def failing_checks() -> CheckStatus:
    """:return: Checks one of which failed."""
    return CheckStatus.over(
        [CheckResult("build", CheckOutcome.FAILURE, "https://example.com/build")]
    )


# %% the lines


def test_a_pull_request_nothing_asks_attention_for_is_ok() -> None:
    github = PullRequestsWithSignals(mergeable={1: MergeableState.CLEAN})

    [_, line] = github.overview().lines()

    assert line.text.endswith("Change 1 - ok")
    assert line.tone is Tone.NEWS


@pytest.mark.parametrize(
    "github, signal",
    [
        (
            PullRequestsWithSignals(
                mergeable={1: MergeableState.CLEAN}, checks={1: failing_checks()}
            ),
            "CI failing",
        ),
        (PullRequestsWithSignals(mergeable={1: MergeableState.DIRTY}), "conflict"),
        (
            PullRequestsWithSignals(mergeable={1: MergeableState.BEHIND}),
            "behind its base",
        ),
        (
            PullRequestsWithSignals(
                mergeable={1: MergeableState.CLEAN},
                threads={1: [thread(resolved=False), thread(resolved=True)]},
            ),
            "1 unresolved thread",
        ),
    ],
    ids=["checks", "conflict", "behind", "threads"],
)
def test_a_signal_is_named_and_asks_for_attention(
    github: PullRequestsWithSignals, signal: str
) -> None:
    [_, line] = github.overview().lines()

    assert line.text.endswith(f"Change 1 - {signal}")
    assert line.tone is Tone.ACTION


def test_the_pull_request_of_the_session_s_branch_is_marked() -> None:
    github = PullRequestsWithSignals(mergeable={1: MergeableState.CLEAN})

    [_, line] = github.overview(checked_out="branch-1").lines()

    assert line.text.endswith("Change 1 - this branch · ok")


def test_a_pull_request_s_status_tags_are_shown_in_their_own_style() -> None:
    github = PullRequestsWithSignals(mergeable={1: MergeableState.CLEAN})

    [_, line] = github.overview().lines()

    assert line.emphases == (Emphasis("- ok", Highlight.STATUS),)


def test_a_pull_request_is_named_with_its_page() -> None:
    github = PullRequestsWithSignals(mergeable={1: MergeableState.CLEAN})

    [_, line] = github.overview().lines()

    assert line.text.split()[0] == NumberLink(1, github.pull_request(1).url).markdown()


def test_pull_requests_are_grouped_open_upstream_then_drafts_then_ready() -> None:
    github = PullRequestsWithSignals(
        mergeable={number: MergeableState.CLEAN for number in (1, 2, 3, 4)},
        drafts=frozenset({2, 4}),
        opened_upstream=frozenset({3, 4}),
    )

    lines = github.overview().lines()

    headings = [line.text for line in lines if not line.text.startswith(" ")]
    named = [line.text.split()[0] for line in lines if line.text.startswith(" ")]
    assert (headings, named) == (
        [Speaker.WORKFLOW.says(f"{group}:") for group in PullRequestGroup],
        [
            NumberLink(number, github.pull_request(number).url).markdown()
            for number in (3, 4, 2, 1)
        ],
    )


def test_pull_requests_waiting_on_the_person_are_counted() -> None:
    github = PullRequestsWithSignals(waiting=2)

    [line] = github.overview().lines()

    assert line.text == Speaker.WORKFLOW.says(
        f"{CountedThing.WAITING_PULL_REQUEST.counted(2)} on your review"
    )


def test_a_shelved_pull_request_is_left_out() -> None:
    github = PullRequestsWithSignals(
        mergeable={1: MergeableState.DIRTY}, shelved=frozenset({1})
    )

    assert github.overview().lines() == []


def test_the_shelving_label_is_created_for_the_person_to_pick() -> None:
    github = PullRequestsWithSignals()

    github.overview().lines()

    assert github.present == {PullRequestLabel.SHELVED}


# %% the details


def test_the_details_name_the_failing_check_the_merge_state_and_the_thread() -> None:
    github = PullRequestsWithSignals(
        mergeable={1: MergeableState.DIRTY},
        checks={1: failing_checks()},
        threads={1: [thread(resolved=False)]},
    )

    details = PullRequestDetails(PullRequestSignalReader(github, github), 1).run()

    [check] = failing_checks().unsuccessful
    assert details.splitlines()[1:] == [
        f"check {check.outcome}: {check.name} {check.url}",
        f"merge state: {MergeableState.DIRTY}",
        "unresolved thread at src/a.py:3: Rename this",
    ]
