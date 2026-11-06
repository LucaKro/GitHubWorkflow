"""
Discussions posted through the repository's Actions: a session queues each post on the
notes branch, with the workflow posting it, since a cloud session cannot write
Discussions itself.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from enum import StrEnum

from basstler_domain_model.github.discussions import DiscussionCategory
from basstler_domain_model.github.repository_client import RepositoryDiscussions
from basstler_domain_model.repository import Repository

from github_workflow.exceptions import DiscussionsDisabledError
from github_workflow.locations import NotesFile, WorkflowTemplate
from github_workflow.notes.branch import NotesBranch
from github_workflow.work import WorkflowStep

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

    def to_json(self) -> str:
        """:return: The post as the posting script reads it."""
        return json.dumps(
            {
                DiscussionPostKey.CATEGORY: self.category,
                DiscussionPostKey.TITLE: self.title,
                DiscussionPostKey.BODY: self.body,
            },
            indent=2,
        )


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
