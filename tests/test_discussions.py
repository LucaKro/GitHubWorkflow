"""
Tests for :mod:`github_workflow.discussions`: ideas queued on the notes branch, and the
Actions script posting what is queued.
"""

from __future__ import annotations

import json
import os
import subprocess
from dataclasses import dataclass
from http import HTTPStatus
from pathlib import Path

import pytest

import github_workflow
from basstler_domain_model.github.discussions import (
    DefaultDiscussionCategory,
    DiscussionCategory,
)
from basstler_domain_model.github.replayed_api import RecordedAnswer, ReplayedApi
from basstler_domain_model.github.repository_client import PullRequestListState
from basstler_domain_model.github.routes import QueryParameter, RepositoryRoute
from basstler_domain_model.github.repository_client import RepositoryDiscussions
from basstler_domain_model.github.vocabulary import RestJSONKey
from basstler_domain_model.locations import PathEnumeration
from basstler_domain_model.repository import Repository

from github_workflow.workflow_templates import TemplatePlaceholder
from github_workflow.command_line import RunnableCommand
from github_workflow.session import WorkflowSession
from github_workflow.command_line import IdeaSubcommand, WorkflowCommand
from github_workflow.discussions import (
    DiscussionPost,
    DiscussionPostKey,
    DiscussionPostKind,
    DiscussionPosting,
    DiscussionSessionLog,
    DiscussionTitle,
    IdeaFiling,
)
from github_workflow.exceptions import DiscussionsDisabledError
from github_workflow.locations import NotesFile, WorkflowTemplate
from github_workflow.notes.branch import NotesBranch
from github_workflow.remotes import OwnedRemotes
from github_workflow.settings import WorkflowSettings

from .repositories_by_owner import RepositoriesByOwner
from .test_commands import (  # noqa: F401
    UpstreamDataset,
    github,
    root_path,
    run,
    setting,
)

# %% the dataset


class DiscussionDataset(PathEnumeration):
    """
    The stand-ins the posting script is run with.
    """

    GH = Path(__file__).parent / "dataset" / "discussions" / "gh"
    """
    Stands in for ``gh``, recording its calls.
    """

    CATEGORIES = Path(__file__).parent / "dataset" / "discussions" / "categories.json"
    """
    GitHub's answer naming the repository's discussion categories.
    """

    NO_DISCUSSIONS = (
        Path(__file__).parent / "dataset" / "discussions" / "no_discussions.json"
    )
    """
    GitHub's answer listing a category without discussions.
    """

    SESSION_LOG = Path(__file__).parent / "dataset" / "discussions" / "session_log.json"
    """
    GitHub's answer listing a category holding the session log twice, the oldest
    ``D_log``, and another discussion.
    """


@dataclass(frozen=True)
class DiscussionsSetTo(RepositoryDiscussions):
    """
    A repository whose Discussions are turned on or off as the test says.
    """

    enabled: bool
    """
    Whether they are on.
    """

    def discussions_enabled(self) -> bool:
        return self.enabled


# %% helpers


def notes_in(
    repositories: RepositoriesByOwner, url: str, settings: WorkflowSettings
) -> NotesBranch:
    """
    :param repositories: Where to clone.
    :param url: The owner's repository.
    :param settings: The workflow's settings.
    :return: The notes branch of a fresh clone.
    """
    git = repositories.clone(url, "session").git
    return NotesBranch.from_settings(
        git, OwnedRemotes.read(git, settings).chosen, settings
    )


def queued_posts(notes: NotesBranch) -> list[dict[str, str]]:
    """
    :param notes: The notes branch.
    :return: The posts waiting on it, in order, as the posting script reads them.
    """
    notes.fetch()
    listed = notes.git.run(
        "ls-tree",
        "--name-only",
        notes.branch.tracking_reference,
        f"{NotesFile.DISCUSSION_POSTS.value}/",
    ).split()
    return [json.loads(notes.read(Path(path))) for path in sorted(listed)]


def calls_of(record: str) -> list[list[str]]:
    """
    :param record: The stand-in ``gh``'s record of its calls.
    :return: Each call's arguments, in order.
    """
    return [
        call.splitlines()
        for call in record.split("--- end of call ---\n")
        if call.strip()
    ]


def idea(title: str, category: DiscussionCategory) -> DiscussionPost:
    """
    :param title: The idea's title.
    :param category: The category it is posted in.
    :return: The idea.
    """
    return DiscussionPost(category, title, f"What {title} is about.")


def run_posting_workflow(
    repositories: RepositoriesByOwner,
    url: str,
    settings: WorkflowSettings,
    tmp_path: Path,
    refused_title: str = "",
    discussions: DiscussionDataset = DiscussionDataset.NO_DISCUSSIONS,
) -> tuple[subprocess.CompletedProcess[str], str]:
    """
    Run the posting workflow's script as a push of the notes branch runs it: in a
    checkout of the notes branch, with ``gh`` signed in.

    :param repositories: Where to clone.
    :param url: The owner's repository.
    :param settings: The workflow's settings.
    :param tmp_path: Where the stand-in ``gh`` records its calls.
    :param refused_title: The title of a post GitHub refuses to create.
    :param discussions: GitHub's answer listing a category's discussions.
    :return: The finished script, and the stand-in's record of its calls.
    """
    runner = repositories.clone(url, "actions-runner").git
    runner.run("checkout", "--quiet", settings.notes_branch)
    calls = tmp_path / "gh-calls.txt"
    calls.touch()
    finished = subprocess.run(
        [
            "bash",
            str(NotesFile.POSTING_SCRIPT.value),
            str(NotesFile.DISCUSSION_POSTS.value),
            str(NotesFile.CATEGORIES_QUERY.value),
            str(NotesFile.CREATE_QUERY.value),
            str(NotesFile.FIND_QUERY.value),
            str(NotesFile.COMMENT_QUERY.value),
            Repository(settings.owner, RepositoriesByOwner.repository_name).full_name,
            settings.notes_branch,
            str(NotesFile.COMMIT_SCRIPT.value),
        ],
        cwd=runner.working_directory,
        capture_output=True,
        text=True,
        env={
            **os.environ,
            "PATH": f"{DiscussionDataset.GH.value.parent}:{os.environ['PATH']}",
            "GH_CALLS": str(calls),
            "GH_CATEGORIES": str(DiscussionDataset.CATEGORIES.value),
            "GH_REFUSED_TITLE": refused_title,
            "GH_DISCUSSIONS": str(discussions.value),
        },
    )
    return finished, calls.read_text()


# %% queueing an idea


def test_an_idea_is_queued_for_the_repository_s_ideas_discussions(
    github: ReplayedApi,  # noqa: F811
    repositories: RepositoriesByOwner,
    owned_url: str,
    settings: WorkflowSettings,
    tmp_path: Path,
):
    github.answers[("GET", root_path(settings))] = setting(HTTPStatus.OK, True)
    checkout = repositories.clone(owned_url, "session")
    body = tmp_path / "idea.md"
    body.write_text("Ideas could live in Discussions.")

    run(
        github_workflow.__name__,
        checkout,
        WorkflowCommand.IDEA,
        IdeaSubcommand.FILE,
        "--title",
        "Keep ideas apart from findings",
        "--body-file",
        str(body),
    )

    notes = NotesBranch.from_settings(
        checkout.git, OwnedRemotes.read(checkout.git, settings).chosen, settings
    )
    assert queued_posts(notes) == [
        {
            DiscussionPostKey.CATEGORY: DefaultDiscussionCategory.IDEAS,
            DiscussionPostKey.TITLE: "Keep ideas apart from findings",
            DiscussionPostKey.BODY: body.read_text(),
        }
    ]


def test_an_idea_goes_into_the_category_named(
    repositories: RepositoriesByOwner, owned_url: str, settings: WorkflowSettings
):
    checkout = repositories.clone(owned_url, "session")
    arguments = RunnableCommand.parser().parse_args(
        [
            WorkflowCommand.IDEA,
            IdeaSubcommand.FILE,
            "--title",
            "An idea",
            "--body-file",
            os.devnull,
            "--category",
            "Brainstorming notes",
        ]
    )

    step = WorkflowSession(checkout.root, settings).step(arguments)

    assert step.post.category == DiscussionCategory("Brainstorming notes")


def test_an_idea_is_not_queued_where_discussions_are_off(
    repositories: RepositoriesByOwner, owned_url: str, settings: WorkflowSettings
):
    notes = notes_in(repositories, owned_url, settings)
    filing = IdeaFiling(
        DiscussionsSetTo(False),
        DiscussionPosting(notes),
        Repository(settings.owner, RepositoriesByOwner.repository_name),
        idea("An idea", DefaultDiscussionCategory.IDEAS),
    )

    with pytest.raises(DiscussionsDisabledError):
        filing.run()

    assert not notes.fetch()


def test_the_queued_workflow_has_every_placeholder_filled(
    repositories: RepositoriesByOwner, owned_url: str, settings: WorkflowSettings
):
    notes = notes_in(repositories, owned_url, settings)

    DiscussionPosting(notes).queue(idea("An idea", DefaultDiscussionCategory.IDEAS))

    notes.fetch()
    workflow = notes.read(NotesFile.POSTING_WORKFLOW.value)
    assert [
        placeholder for placeholder in TemplatePlaceholder if placeholder in workflow
    ] == []


def test_ideas_are_queued_in_the_order_they_were_filed(
    repositories: RepositoriesByOwner, owned_url: str, settings: WorkflowSettings
):
    notes = notes_in(repositories, owned_url, settings)
    first = idea("First", DefaultDiscussionCategory.IDEAS)
    second = idea("Second", DefaultDiscussionCategory.IDEAS)

    DiscussionPosting(notes).queue(first)
    DiscussionPosting(notes).queue(second)

    assert [post[DiscussionPostKey.TITLE] for post in queued_posts(notes)] == [
        first.title,
        second.title,
    ]


# %% the posting workflow


def test_the_workflow_posts_an_idea_in_its_category(
    repositories: RepositoriesByOwner,
    owned_url: str,
    settings: WorkflowSettings,
    tmp_path: Path,
):
    notes = notes_in(repositories, owned_url, settings)
    posted = idea("An idea", DefaultDiscussionCategory.IDEAS)
    DiscussionPosting(notes).queue(posted)

    _, record = run_posting_workflow(repositories, owned_url, settings, tmp_path)

    [_, create] = calls_of(record)
    assert {
        argument
        for argument in create
        if argument.startswith(("categoryId=", "title="))
    } == {"categoryId=DIC_ideas", f"title={posted.title}"}


def test_the_workflow_removes_what_it_posted(
    repositories: RepositoriesByOwner,
    owned_url: str,
    settings: WorkflowSettings,
    tmp_path: Path,
):
    notes = notes_in(repositories, owned_url, settings)
    DiscussionPosting(notes).queue(idea("An idea", DefaultDiscussionCategory.IDEAS))

    run_posting_workflow(repositories, owned_url, settings, tmp_path)

    assert queued_posts(notes) == []


def test_a_post_in_a_category_the_repository_lacks_is_kept(
    repositories: RepositoriesByOwner,
    owned_url: str,
    settings: WorkflowSettings,
    tmp_path: Path,
):
    notes = notes_in(repositories, owned_url, settings)
    kept = idea("An idea", DiscussionCategory("Brainstorming notes"))
    DiscussionPosting(notes).queue(kept)

    finished, _ = run_posting_workflow(repositories, owned_url, settings, tmp_path)

    assert finished.returncode != 0
    assert [post[DiscussionPostKey.TITLE] for post in queued_posts(notes)] == [
        kept.title
    ]


def test_a_post_github_refuses_is_kept_and_the_others_are_removed(
    repositories: RepositoriesByOwner,
    owned_url: str,
    settings: WorkflowSettings,
    tmp_path: Path,
):
    notes = notes_in(repositories, owned_url, settings)
    refused = idea("Refused", DefaultDiscussionCategory.IDEAS)
    DiscussionPosting(notes).queue(refused)
    DiscussionPosting(notes).queue(idea("Posted", DefaultDiscussionCategory.IDEAS))

    finished, _ = run_posting_workflow(
        repositories, owned_url, settings, tmp_path, refused.title
    )

    assert finished.returncode != 0
    assert [post[DiscussionPostKey.TITLE] for post in queued_posts(notes)] == [
        refused.title
    ]


# %% the session log


def session_log(notes: NotesBranch, enabled: bool = True) -> DiscussionSessionLog:
    """
    :param notes: The notes branch the entries are queued on.
    :param enabled: Whether the repository has Discussions turned on.
    :return: The session log of a session working on ``work``.
    """
    return DiscussionSessionLog(
        DiscussionsSetTo(enabled), DiscussionPosting(notes), "work"
    )


def test_an_entry_is_queued_as_a_comment_on_the_session_log(
    repositories: RepositoriesByOwner, owned_url: str, settings: WorkflowSettings
):
    notes = notes_in(repositories, owned_url, settings)
    log = session_log(notes)

    log.enter("closed pull request #3")

    [entry] = queued_posts(notes)
    assert {
        key: value for key, value in entry.items() if key != DiscussionPostKey.BODY
    } == {
        DiscussionPostKey.CATEGORY: log.category,
        DiscussionPostKey.TITLE: log.title,
        DiscussionPostKey.KIND: DiscussionPostKind.COMMENT,
        DiscussionPostKey.INTRODUCTION: (
            WorkflowTemplate.SESSION_LOG_INTRODUCTION.value.read_text()
        ),
    }
    assert entry[DiscussionPostKey.BODY].endswith(
        f" on `{log.branch}`: closed pull request #3"
    )


def test_nothing_is_entered_where_discussions_are_off(
    repositories: RepositoriesByOwner, owned_url: str, settings: WorkflowSettings
):
    notes = notes_in(repositories, owned_url, settings)

    session_log(notes, enabled=False).enter("closed pull request #3")

    assert not notes.fetch()


def test_a_branch_the_cleanup_deletes_is_entered_in_the_session_log(
    github: ReplayedApi,  # noqa: F811
    repositories: RepositoriesByOwner,
    owned_url: str,
    settings: WorkflowSettings,
):
    repository = Repository(settings.owner, RepositoriesByOwner.repository_name)
    checkout = repositories.clone(owned_url, "session")
    git = checkout.git
    git.run("push", "--quiet", "origin", "HEAD:refs/heads/closed-work")
    closed = json.loads(UpstreamDataset.FORK_PULL_REQUESTS.value.read_text())[0]
    closed["state"] = "closed"
    closed["head"]["ref"] = "closed-work"
    closed["head"]["sha"] = git.commit_at("HEAD")
    closed["head"]["repo"]["full_name"] = repository.full_name
    route = RepositoryRoute(repository)
    listing = route.listing(
        route.pull_requests, {QueryParameter.STATE: PullRequestListState.ALL.query}
    )
    github.answers[("GET", f"/{listing}")] = RecordedAnswer(
        HTTPStatus.OK, json.dumps([closed])
    )

    run(github_workflow.__name__, checkout, WorkflowCommand.CLEANUP)

    notes = NotesBranch.from_settings(
        git, OwnedRemotes.read(git, settings).chosen, settings
    )
    [entry] = queued_posts(notes)
    assert entry[DiscussionPostKey.TITLE] == DiscussionTitle.SESSION_LOG
    assert "`closed-work`" in entry[DiscussionPostKey.BODY]


def test_the_workflow_comments_on_the_oldest_session_log(
    repositories: RepositoriesByOwner,
    owned_url: str,
    settings: WorkflowSettings,
    tmp_path: Path,
):
    notes = notes_in(repositories, owned_url, settings)
    session_log(notes).enter("closed pull request #3")

    _, record = run_posting_workflow(
        repositories,
        owned_url,
        settings,
        tmp_path,
        discussions=DiscussionDataset.SESSION_LOG,
    )

    commented = [
        argument
        for call in calls_of(record)
        for argument in call
        if argument.startswith("discussionId=")
    ]
    assert commented == ["discussionId=D_log"]


def test_the_workflow_starts_the_session_log_when_there_is_none(
    repositories: RepositoriesByOwner,
    owned_url: str,
    settings: WorkflowSettings,
    tmp_path: Path,
):
    notes = notes_in(repositories, owned_url, settings)
    log = session_log(notes)
    log.enter("closed pull request #3")

    _, record = run_posting_workflow(repositories, owned_url, settings, tmp_path)

    calls = calls_of(record)
    [created] = [call for call in calls if f"title={log.title}" in call]
    commented = [
        argument
        for call in calls
        for argument in call
        if argument.startswith("discussionId=")
    ]
    assert (
        f"body={WorkflowTemplate.SESSION_LOG_INTRODUCTION.value.read_text().rstrip()}"
        in "\n".join(created)
    )
    assert commented == ["discussionId=D_created"]
