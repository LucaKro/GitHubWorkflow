"""
Discussions posted through the repository's Actions: a session queues each post on the
notes branch, with the workflow posting it, since a cloud session cannot write
Discussions itself. Ideas are posted this way, and the session log is kept this way.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum

from basstler_domain_model.git.commands import GitCommandRunner
from basstler_domain_model.github.discussions import (
    DefaultDiscussionCategory,
    DiscussionCategory,
)
from basstler_domain_model.github.repository_client import RepositoryDiscussions
from basstler_domain_model.repository import Repository

from github_workflow.exceptions import DiscussionsDisabledError
from github_workflow.locations import NotesFile, WorkflowTemplate
from github_workflow.notes.branch import NotesBranch
from github_workflow.remotes import OwnedRemote
from github_workflow.settings import WorkflowSettings
from github_workflow.work import SessionLog, WorkflowStep

# %% vocabulary


class DiscussionPostKey(StrEnum):
    """
    The keys of a queued post, as the posting script reads them.
    """

    CATEGORY = "category"
    """
    The category it is posted in, by name.
    """

    TITLE = "title"
    """
    Its title.
    """

    BODY = "body"
    """
    Its text, in Markdown.
    """

    KIND = "kind"
    """
    What it is, a new discussion when absent.
    """

    INTRODUCTION = "introduction"
    """
    The text a comment's discussion is started with when it does not exist yet.
    """


class DiscussionPostKind(StrEnum):
    """
    What a queued post is, other than a new discussion.
    """

    COMMENT = "comment"
    """
    A comment on the discussion its title names.
    """


class DiscussionTitle(StrEnum):
    """
    The discussions the workflow keeps.
    """

    SESSION_LOG = "Session log"
    """
    What sessions did without asking, one comment per entry.
    """


class PostingPlaceholder(StrEnum):
    """
    The names the posting workflow template leaves to be filled in.
    """

    NOTES_BRANCH = "__NOTES_BRANCH__"
    """
    The notes branch, whose pushes run the workflow.
    """

    POSTS_DIRECTORY = "__POSTS_DIRECTORY__"
    """
    The directory holding the posts.
    """

    SCRIPT_FILE = "__SCRIPT_FILE__"
    """
    The script posting them.
    """

    CATEGORIES_QUERY = "__CATEGORIES_QUERY__"
    """
    The query reading the repository's categories.
    """

    CREATE_QUERY = "__CREATE_QUERY__"
    """
    The mutation creating a discussion.
    """

    FIND_QUERY = "__FIND_QUERY__"
    """
    The query finding the discussion a comment goes on.
    """

    COMMENT_QUERY = "__COMMENT_QUERY__"
    """
    The mutation commenting on a discussion.
    """


# %% posts


@dataclass(frozen=True)
class DiscussionPost:
    """
    One discussion to be posted.
    """

    category: DiscussionCategory
    """
    The category it is posted in.
    """

    title: str
    """
    Its title.
    """

    body: str
    """
    Its text, in Markdown.
    """

    def fields(self) -> dict[DiscussionPostKey, str]:
        """:return: The post's fields, by the key the posting script reads each by."""
        return {
            DiscussionPostKey.CATEGORY: self.category,
            DiscussionPostKey.TITLE: self.title,
            DiscussionPostKey.BODY: self.body,
        }

    def to_json(self) -> str:
        """:return: The post as the posting script reads it."""
        return json.dumps(self.fields(), indent=2)


@dataclass(frozen=True)
class DiscussionComment(DiscussionPost):
    """
    A comment on the oldest discussion titled :attr:`title` in :attr:`category`, which
    is started with :attr:`introduction` when there is none.
    """

    introduction: str
    """
    The text the discussion is started with when it does not exist yet.
    """

    def fields(self) -> dict[DiscussionPostKey, str]:
        return {
            **super().fields(),
            DiscussionPostKey.KIND: DiscussionPostKind.COMMENT,
            DiscussionPostKey.INTRODUCTION: self.introduction,
        }


@dataclass(frozen=True)
class DiscussionPosting:
    """
    Posts queued on the notes branch together with the Actions workflow that posts them
    whenever the branch is pushed.
    """

    notes: NotesBranch
    """
    The notes branch, which carries the posts and the workflow.
    """

    def queue(self, post: DiscussionPost) -> None:
        """
        :param post: The discussion to post, after those queued before it.
        """
        workflow = WorkflowTemplate.POSTING_WORKFLOW.value.read_text()
        for placeholder, value in {
            PostingPlaceholder.NOTES_BRANCH: self.notes.branch.name,
            PostingPlaceholder.POSTS_DIRECTORY: NotesFile.DISCUSSION_POSTS.value,
            PostingPlaceholder.SCRIPT_FILE: NotesFile.POSTING_SCRIPT.value,
            PostingPlaceholder.CATEGORIES_QUERY: NotesFile.CATEGORIES_QUERY.value,
            PostingPlaceholder.CREATE_QUERY: NotesFile.CREATE_QUERY.value,
            PostingPlaceholder.FIND_QUERY: NotesFile.FIND_QUERY.value,
            PostingPlaceholder.COMMENT_QUERY: NotesFile.COMMENT_QUERY.value,
        }.items():
            workflow = workflow.replace(placeholder, str(value))
        self.notes.fetch()
        self.notes.write(
            {
                NotesFile.DISCUSSION_POSTS.value
                / f"{time.time_ns()}.json": (post.to_json()),
                NotesFile.POSTING_WORKFLOW.value: workflow,
                NotesFile.POSTING_SCRIPT.value: (
                    WorkflowTemplate.POSTING_SCRIPT.value.read_text()
                ),
                NotesFile.CATEGORIES_QUERY.value: (
                    WorkflowTemplate.CATEGORIES_QUERY.value.read_text()
                ),
                NotesFile.CREATE_QUERY.value: (
                    WorkflowTemplate.CREATE_QUERY.value.read_text()
                ),
                NotesFile.FIND_QUERY.value: (
                    WorkflowTemplate.FIND_QUERY.value.read_text()
                ),
                NotesFile.COMMENT_QUERY.value: (
                    WorkflowTemplate.COMMENT_QUERY.value.read_text()
                ),
            },
            f"Queue the discussion {post.title!r}",
        )


# %% ideas


@dataclass(frozen=True)
class IdeaFiling(WorkflowStep):
    """
    An idea, not a finding, queued to be posted to the repository's Discussions.
    """

    discussions: RepositoryDiscussions
    """
    Says whether the repository has Discussions turned on.
    """

    posting: DiscussionPosting
    """
    Queues the post.
    """

    repository: Repository
    """
    The repository whose Discussions it is posted to.
    """

    post: DiscussionPost
    """
    The idea.
    """

    def run(self) -> str:
        """
        :raises DiscussionsDisabledError: If the repository has Discussions turned off.
        """
        if not self.discussions.discussions_enabled():
            raise DiscussionsDisabledError(self.repository)
        self.posting.queue(self.post)
        return (
            f"queued the idea {self.post.title!r} for the {self.post.category} "
            f"discussions of {self.repository}; the repository's Actions post it "
            f"within a minute or two, as github-actions[bot]"
        )


# %% the session log


@dataclass(frozen=True)
class DiscussionSessionLog(SessionLog):
    """
    The session log as a discussion of the repository's, one comment per entry, each
    with its time and the branch the session works on. Nothing is entered where the
    repository has Discussions turned off.
    """

    discussions: RepositoryDiscussions
    """
    Says whether the repository has Discussions turned on.
    """

    posting: DiscussionPosting
    """
    Queues the entries.
    """

    branch: str
    """
    The branch the session works on, empty when it works on none.
    """

    category: DiscussionCategory = DefaultDiscussionCategory.GENERAL
    """
    The category the log discussion is in.
    """

    title: str = DiscussionTitle.SESSION_LOG
    """
    The log discussion's title.
    """

    @classmethod
    def in_checkout(
        cls,
        discussions: RepositoryDiscussions,
        git: GitCommandRunner,
        remote: OwnedRemote,
        settings: WorkflowSettings,
    ) -> DiscussionSessionLog:
        """
        :param discussions: Says whether the repository has Discussions turned on.
        :param git: Runs git in the checkout the session works in.
        :param remote: The owner's remote, whose notes branch queues the entries.
        :param settings: Where the notes live.
        :return: The session log of a session working on the checked-out branch.
        """
        return cls(
            discussions,
            DiscussionPosting(NotesBranch.on(git, remote, settings)),
            git.checked_out_branch(),
        )

    def enter(self, action: str) -> None:
        if not self.discussions.discussions_enabled():
            return
        written = datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC")
        where = f" on `{self.branch}`" if self.branch else ""
        self.posting.queue(
            DiscussionComment(
                self.category,
                self.title,
                f"{written}{where}: {action}",
                WorkflowTemplate.SESSION_LOG_INTRODUCTION.value.read_text(),
            )
        )
