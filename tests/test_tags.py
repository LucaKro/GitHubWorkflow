"""
Tests for :mod:`github_workflow.tags`: the comments the person tagged by mentioning
themselves are found, listed, shown, filed as findings or dismissed, and recorded in the
ledger on the notes branch, read directly or through the repository's Actions.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pytest
from domain_model.git.revisions import TextFiles
from domain_model.github.clients import GitHubReader
from domain_model.github.conversations import SelfMention
from domain_model.github.routes import RepositoryRoute
from domain_model.locations import PathEnumeration
from domain_model.repository import Repository

from github_workflow.command_line import PriorityLevel
from github_workflow.exceptions import ForwardedAnswerMissing, UnknownTagError
from github_workflow.findings import FindingStage, Priority
from github_workflow.forwarded_reads import (
    ForwardedAnswer,
    ForwardedReadAnswering,
    ForwardedReading,
)
from github_workflow.locations import NotesFile
from github_workflow.notes.branch import NotesBranch
from github_workflow.report_lines import ReportLine, Speaker, Tone
from github_workflow.report_section import ReportGroup
from github_workflow.settings import WorkflowSettings
from github_workflow.tags import (
    DirectTagSource,
    FoundTags,
    RepositoryReach,
    SavedTagSource,
    TagDescription,
    TagDismissal,
    TagFiling,
    TagLedger,
    TagListing,
    TagRefresh,
    TagRequest,
    TagSection,
    TagShowing,
    TagSource,
    WaitingTags,
)

from .issues_in_memory import IssuesInMemory, finding_upstream
from .repositories_by_owner import RepositoriesByOwner
from .scratch_github import ScratchGitHub
from .test_discussions import clone_notes_branch
from .test_upstream_reviews import RunsOfTheQueuedRequest

# %% GitHub's answers


class TagDataset(PathEnumeration):
    """
    GitHub's answers to searching for the person's tags: one issue upstream, two of
    whose comments the person tagged.
    """

    ISSUE_SEARCH = Path(__file__).parent / "dataset" / "tags" / "issue-search.json"
    """
    One page of an issue search, finding the issue.
    """

    ISSUE = Path(__file__).parent / "dataset" / "tags" / "issue.json"
    """
    The issue, opened by someone else.
    """

    ISSUE_COMMENTS = Path(__file__).parent / "dataset" / "tags" / "issue-comments.json"
    """
    Its comments: two the person wrote mentioning themselves, one by someone else
    mentioning them.
    """

    DISCUSSION_SEARCH = (
        Path(__file__).parent / "dataset" / "tags" / "discussion-search.json"
    )
    """
    One page of a discussion search, finding nothing.
    """

    def decode_answer(self) -> Any:
        """:return: The answer, decoded."""
        return json.loads(self.value.read_text())


@dataclass(frozen=True)
class TaggedIssueAnswers(GitHubReader):
    """
    Answers every issue search with the tagged issue, the issue's reads with their
    recordings, and every discussion search with nothing.
    """

    def get(self, path: str) -> Any:
        return {self.route.issue(4): TagDataset.ISSUE.decode_answer()}[path]

    def get_pages(self, path: str) -> list[Any]:
        if path.startswith("search/"):
            return [TagDataset.ISSUE_SEARCH.decode_answer()]
        comments = self.route.listing(self.route.issue_comments(4))
        return {comments: [TagDataset.ISSUE_COMMENTS.decode_answer()]}[path]

    def execute(self, query: str, variables: dict[str, Any]) -> dict[str, Any]:
        return TagDataset.DISCUSSION_SEARCH.decode_answer()

    @property
    def route(self) -> RepositoryRoute:
        """:return: The paths of the tagged issue's repository."""
        return RepositoryRoute(ScratchGitHub.upstream)


@dataclass(frozen=True)
class FixedTagSource(TagSource):
    """
    Finds the same tagged comments whatever is asked.
    """

    found: FoundTags
    """
    What it finds.
    """

    def found_tags(self, since: datetime | None) -> FoundTags:
        return self.found


@dataclass(frozen=True)
class FixedReach(RepositoryReach):
    """
    Reaches every repository, or none.
    """

    reaches_every: bool
    """
    Whether every repository is reached.
    """

    def reaches(self, repository: Repository) -> bool:
        return self.reaches_every


def owner() -> str:
    """:return: The person, who tags by mentioning themselves."""
    return WorkflowSettings().owner


def found_directly() -> FoundTags:
    """:return: The tags a direct search of the recorded answers finds."""
    return DirectTagSource(TaggedIssueAnswers(), owner()).found_tags(None)


def tag_urls() -> list[str]:
    """:return: The pages of the two tagged comments, oldest first."""
    comments = TagDataset.ISSUE_COMMENTS.decode_answer()
    return [comments[0]["html_url"], comments[2]["html_url"]]


def mention(index: int) -> SelfMention:
    """:param index: Which tagged comment, oldest first.
    :return: It, as a direct search finds it."""
    return found_directly().mentions[index]


def incomplete(found: FoundTags) -> FoundTags:
    """:param found: Tags found.
    :return: The same, from a search that could not read every conversation."""
    return replace(found, complete_until=None)


def waiting_urls(tags: WaitingTags) -> list[str]:
    """:param tags: Where the tags stand.
    :return: The page of each tag waiting."""
    status = tags.read()
    return [mention.comment.url for mention in status.ledger.waiting(status.found)]


@pytest.fixture
def notes(
    repositories: RepositoriesByOwner, owned_url: str, settings: WorkflowSettings
) -> NotesBranch:
    """:return: The notes branch of a fresh clone of the owner's repository."""
    return clone_notes_branch(repositories, owned_url, settings)


# %% finding the tags


def test_the_comments_the_person_wrote_mentioning_themselves_are_found() -> None:
    found = found_directly()

    assert [mention.comment.url for mention in found.mentions] == tag_urls()


def test_a_direct_search_is_complete_until_it_was_made() -> None:
    before = datetime.now(timezone.utc)

    found = found_directly()

    assert before <= found.complete_until <= datetime.now(timezone.utc)


def test_a_request_answered_on_the_runner_is_read_again_the_same(
    tmp_path: Path,
) -> None:
    requests, answers = tmp_path / "requests", tmp_path / "answers"
    requests.mkdir()
    request = TagRequest(owner(), None, datetime.now(timezone.utc), name="1.json")
    (requests / "1.json").write_text(json.dumps(request.to_json()))

    ForwardedReadAnswering(TagRequest, requests, answers, TaggedIssueAnswers()).run()

    saved = (answers / "1.json").read_text()
    replayed = ForwardedAnswer.replay(saved, TagRequest, "1.json")
    assert replayed == request.read(TaggedIssueAnswers())


def test_a_request_is_read_back_as_written() -> None:
    since = datetime(2026, 11, 1, tzinfo=timezone.utc)
    request = TagRequest(owner(), since, datetime.now(timezone.utc), name="1.json")

    assert TagRequest.from_json(request.to_json(), "1.json") == request


# %% the ledger


def test_every_tag_waits_before_the_first_is_handled() -> None:
    assert TagLedger().waiting(found_directly()) == list(found_directly().mentions)


def test_a_tag_written_before_the_cursor_does_not_wait() -> None:
    ledger = TagLedger(mention(1).comment.created_at)

    assert ledger.waiting(found_directly()) == [mention(1)]


def test_handling_a_tag_of_a_complete_search_moves_the_cursor_to_the_oldest_waiting() -> (
    None
):
    ledger = TagLedger().handle(mention(0), None, found_directly())

    assert ledger == TagLedger(mention(1).comment.created_at, ())


def test_handling_the_last_tag_moves_the_cursor_to_when_the_search_was_made() -> None:
    found = found_directly()
    first = TagLedger().handle(mention(0), None, found)

    ledger = first.handle(mention(1), None, found)

    assert ledger.cursor == found.complete_until


def test_handling_a_tag_of_an_incomplete_search_keeps_the_cursor() -> None:
    found = incomplete(found_directly())

    ledger = TagLedger().handle(mention(0), "an-issue", found)

    assert (ledger.cursor, [tag.comment for tag in ledger.handled]) == (
        None,
        [tag_urls()[0]],
    )


def test_the_cursor_never_moves_back() -> None:
    later = datetime.now(timezone.utc) + timedelta(days=1)

    ledger = TagLedger(later).handle(mention(0), None, found_directly())

    assert ledger.cursor == later


def test_the_ledger_is_read_back_as_saved(notes: NotesBranch) -> None:
    ledger = TagLedger().handle(mention(0), "an-issue", incomplete(found_directly()))

    ledger.save(notes, "Save")

    notes.fetch()
    assert TagLedger.read(notes) == ledger


# %% the commands


def test_the_tags_waiting_are_listed_as_links_to_the_comments(
    notes: NotesBranch,
) -> None:
    listing = TagListing(WaitingTags(FixedTagSource(found_directly()), notes))

    assert listing.run().splitlines() == [
        TagDescription(mention(0)).listing_line,
        TagDescription(mention(1)).listing_line,
    ]


def test_a_tag_is_listed_by_its_conversation_title_and_first_line() -> None:
    issue = TagDataset.ISSUE.decode_answer()

    line = TagDescription(mention(0)).listing_line

    first_line = mention(0).comment.body.splitlines()[0]
    assert line == (
        f"[{ScratchGitHub.upstream.full_name}#4]({tag_urls()[0]}) "
        f"{issue['title']}: {first_line}"
    )


def test_a_tag_s_conversation_is_shown_with_every_text_oldest_first(
    notes: NotesBranch,
) -> None:
    showing = TagShowing(
        WaitingTags(FixedTagSource(found_directly()), notes), tag_urls()[0]
    )

    shown = showing.run()

    issue = TagDataset.ISSUE.decode_answer()
    comments = TagDataset.ISSUE_COMMENTS.decode_answer()
    headers = [line for line in shown.splitlines() if line.startswith("--- ")]
    assert [header.split(", ")[2].removesuffix(":") for header in headers] == [
        issue["html_url"],
        f"{tag_urls()[0]} (the tagged comment)",
        comments[1]["html_url"],
        tag_urls()[1],
    ]


def filing(notes: NotesBranch, board: IssuesInMemory, comment: str) -> TagFiling:
    """
    :param notes: The notes branch holding the ledger.
    :param board: The owner's repository's issues.
    :param comment: The tagged comment to file.
    :return: Its filing as a medium finding, from an incomplete search.
    """
    return TagFiling(
        WaitingTags(FixedTagSource(incomplete(found_directly())), notes),
        comment,
        board,
        finding_upstream(),
        "Test restarts",
        "The planner loses its goals on restart.",
        Priority.at_level(PriorityLevel.MEDIUM),
    )


def test_filing_a_tag_files_an_unreviewed_finding_linking_the_comment(
    notes: NotesBranch,
) -> None:
    board = IssuesInMemory()

    filing(notes, board, tag_urls()[0]).run()

    issue = board.open_issues[1]
    assert (issue.labels, board.descriptions[1].splitlines()[-1]) == (
        (FindingStage.UNREVIEWED, Priority.at_level(PriorityLevel.MEDIUM)),
        f"Tagged in {tag_urls()[0]}",
    )


def test_a_filed_tag_is_recorded_with_its_issue_and_waits_no_longer(
    notes: NotesBranch,
) -> None:
    filing(notes, IssuesInMemory(), tag_urls()[0]).run()

    notes.fetch()
    handled = TagLedger.read(notes).handled
    tags = WaitingTags(FixedTagSource(incomplete(found_directly())), notes)
    assert (
        [(tag.comment, tag.issue) for tag in handled],
        waiting_urls(tags),
    ) == (
        [(tag_urls()[0], ScratchGitHub.owned.issue_url(1))],
        [tag_urls()[1]],
    )


def test_a_comment_that_is_no_tag_waiting_is_refused_and_nothing_filed(
    notes: NotesBranch,
) -> None:
    board = IssuesInMemory()
    other = TagDataset.ISSUE_COMMENTS.decode_answer()[1]["html_url"]

    with pytest.raises(UnknownTagError):
        filing(notes, board, other).run()

    assert board.open_issues == {}


def test_a_dismissed_tag_waits_no_longer(notes: NotesBranch) -> None:
    tags = WaitingTags(FixedTagSource(found_directly()), notes)

    TagDismissal(tags, tag_urls()[0]).run()

    assert waiting_urls(tags) == [tag_urls()[1]]


# %% the session start's section


def build_reading(notes: NotesBranch) -> ForwardedReading:
    """:param notes: The owner's notes branch.
    :return: Has the owner's repository's Actions read, given up on at once."""
    return ForwardedReading(
        notes,
        ScratchGitHub.owned,
        RunsOfTheQueuedRequest(notes),
        timeout_seconds=0,
        start_seconds=0,
    )


def test_the_section_lists_the_tags_waiting_under_a_heading(
    notes: NotesBranch,
) -> None:
    section = TagSection(WaitingTags(FixedTagSource(found_directly()), notes))

    items = [
        ReportLine(TagDescription(found).listing_line, Tone.ACTION)
        for found in found_directly().mentions
    ]
    heading = "comments you tagged, filed only on your word"
    assert section.lines() == ReportGroup(heading, items).lines()


def test_the_section_says_why_tags_out_of_reach_are_missing(
    notes: NotesBranch,
) -> None:
    missing = ForwardedAnswerMissing(TagRequest.subject, ScratchGitHub.owned)
    found = FoundTags((), None, missing)

    lines = TagSection(WaitingTags(FixedTagSource(found), notes)).lines()

    assert lines == [ReportLine(Speaker.WORKFLOW.says(missing.line()), Tone.NEWS)]


def test_the_section_asks_the_repository_s_actions_to_search_afresh(
    notes: NotesBranch,
) -> None:
    section = TagSection(
        WaitingTags(FixedTagSource(found_directly()), notes),
        TagRefresh(build_reading(notes), owner()),
    )

    section.lines()

    notes.fetch()
    queued = notes.branch.tracking_branch.file_names(NotesFile.TAG_REQUESTS.value)
    assert len(queued) == 1


# %% the newest answer and what a cloud session reaches


def save_answer(notes: NotesBranch, asked_at: datetime) -> TagRequest:
    """
    Save an answer on the notes branch as the runner does.

    :param notes: The notes branch.
    :param asked_at: When the request answered was made.
    :return: The request answered.
    """
    request = TagRequest(owner(), None, asked_at, name="1.json")
    answer = ForwardedAnswer.from_request(request, TaggedIssueAnswers())
    notes.fetch()
    notes.write(
        TextFiles({NotesFile.TAG_ANSWERS.value / request.name: answer.to_json()}),
        "Answer",
    )
    return request


def test_without_a_saved_answer_only_the_reachable_tags_are_found_and_why_said(
    notes: NotesBranch,
) -> None:
    source = SavedTagSource(
        build_reading(notes), TaggedIssueAnswers(), FixedReach(True), owner()
    )

    found = source.found_tags(None)

    assert (found.mentions, found.complete_until, found.missing_reason) == (
        found_directly().mentions,
        None,
        ForwardedAnswerMissing(TagRequest.subject, ScratchGitHub.owned),
    )


def test_the_saved_answer_gives_the_tags_out_of_reach_complete_until_it_was_asked(
    notes: NotesBranch,
) -> None:
    asked_at = datetime(2026, 11, 12, 12, tzinfo=timezone.utc)
    save_answer(notes, asked_at)
    source = SavedTagSource(
        build_reading(notes), TaggedIssueAnswers(), FixedReach(False), owner()
    )

    found = source.found_tags(None)

    assert found == FoundTags(found_directly().mentions, asked_at)
