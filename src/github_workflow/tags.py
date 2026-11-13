"""
Comments the person tagged by mentioning themselves in them, anywhere on GitHub: found
by searching, listed at session start, and filed as findings on the owner's
repositories or dismissed on the person's word, each recorded in a ledger on the notes
branch. Nothing is ever written where a comment was tagged.

Usage on the runner: ``python -m github_workflow.tags <requests directory> <answers
directory>``; answers every waiting request and removes it.
"""

from __future__ import annotations

import json
from abc import ABC, abstractmethod
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from enum import StrEnum
from http import HTTPMethod
from typing import Any, Self

from domain_model.class_property import classproperty
from domain_model.git.revisions import TextFiles
from domain_model.github.clients import GitHubReader, RestWriter
from domain_model.github.conversations import (
    Conversation,
    ConversationReader,
    SelfMention,
    SelfMentionSearch,
)
from domain_model.github.repository_client import IssueTracker
from domain_model.github.routes import RepositoryRoute
from domain_model.repository import Repository

from github_workflow.exceptions import ForwardedReadUnavailable, UnknownTagError
from github_workflow.findings import FindingFiling, Priority
from github_workflow.forwarded_reads import (
    ForwardedReadAnswering,
    ForwardedReading,
    ForwardedRequest,
)
from github_workflow.locations import NotesFile
from github_workflow.notes.branch import NotesBranch
from github_workflow.report_lines import ReportLine, Speaker, Tone
from github_workflow.report_section import ReportGroup, ReportSection
from github_workflow.workflow_step import WorkflowStep
from github_workflow.workflow_templates import ForwardedSubject

# %% what a search found


@dataclass(frozen=True)
class FoundTags:
    """
    The comments the person tagged that a search found, and how far it is complete.
    """

    mentions: tuple[SelfMention, ...]
    """
    Every tagged comment found, oldest first.
    """

    complete_until: datetime | None
    """
    The time up to which every tagged comment is among :attr:`mentions`, ``None``
    when the search could not read every conversation it found.
    """

    missing_reason: ForwardedReadUnavailable | None = None
    """
    Why the tagged comments in the conversations this session does not reach are not
    among :attr:`mentions`, ``None`` when nothing is missing for that reason.
    """


# %% the request the repository's Actions answer


class TagRequestKey(StrEnum):
    """
    The keys of a request, as the notes branch holds it.
    """

    LOGIN = "login"
    """
    The person, who tags a comment by mentioning themselves.
    """

    SINCE = "since"
    """
    The time before which tags are not looked for, absent to look for all.
    """

    ASKED_AT = "asked_at"
    """
    When the request was made.
    """


@dataclass(frozen=True)
class TagRequest(ForwardedRequest[FoundTags]):
    """
    A search for every comment the person tagged since a time, in issues, pull
    requests and discussions anywhere on GitHub.
    """

    login: str
    """
    The person, who tags a comment by mentioning themselves.
    """

    since: datetime | None
    """
    The time before which tags are not looked for, ``None`` to look for all.
    """

    asked_at: datetime
    """
    When the request was made, up to which the search is complete.
    """

    @classproperty
    def subject(cls) -> ForwardedSubject:
        return ForwardedSubject.TAGGED_COMMENTS

    def to_json(self) -> dict[str, Any]:
        written = {
            TagRequestKey.LOGIN: self.login,
            TagRequestKey.ASKED_AT: self.asked_at.isoformat(),
        }
        if self.since is not None:
            written[TagRequestKey.SINCE] = self.since.isoformat()
        return written

    @classmethod
    def from_json(cls, data: dict[str, Any], name: str) -> Self:
        since = data.get(TagRequestKey.SINCE)
        return cls(
            data[TagRequestKey.LOGIN],
            None if since is None else datetime.fromisoformat(since),
            datetime.fromisoformat(data[TagRequestKey.ASKED_AT]),
            name=name,
        )

    @classmethod
    def from_current_time(cls, login: str, since: datetime | None) -> TagRequest:
        """
        :param login: The person.
        :param since: The time before which tags are not looked for.
        :return: The request, made now.
        """
        return cls(login, since, datetime.now(timezone.utc))

    def read(self, client: GitHubReader) -> FoundTags:
        search = SelfMentionSearch(client, self.login, self.since)
        reader = ConversationReader(client)
        conversations = [
            reader.read(address)
            for address in search.issue_conversations() + search.discussions()
        ]
        return FoundTags(
            tuple(SelfMention.every_mention(conversations, self.login)),
            self.asked_at,
        )


# %% where the tags are read from


class TagSource(ABC):
    """
    Finds the comments the person tagged.
    """

    @abstractmethod
    def found_tags(self, since: datetime | None) -> FoundTags:
        """
        :param since: The time before which tags are not looked for, ``None`` to look
            for all.
        :return: The tagged comments found.
        """


@dataclass(frozen=True)
class DirectTagSource(TagSource):
    """
    Searches GitHub itself, where every repository and GitHub's GraphQL are reached.
    """

    client: GitHubReader
    """
    How the reads reach GitHub.
    """

    login: str
    """
    The person.
    """

    def found_tags(self, since: datetime | None) -> FoundTags:
        return TagRequest.from_current_time(self.login, since).read(self.client)


@dataclass(frozen=True)
class ForwardedTagSource(TagSource):
    """
    Has the repository's Actions search, and waits for their answer.
    """

    reading: ForwardedReading
    """
    Has the repository's Actions answer the request.
    """

    login: str
    """
    The person.
    """

    def found_tags(self, since: datetime | None) -> FoundTags:
        found = self.reading.read(TagRequest.from_current_time(self.login, since))
        if isinstance(found, ForwardedReadUnavailable):
            return FoundTags((), None, found)
        return found


class RepositoryReach(ABC):
    """
    Which repositories this session's own reads reach.
    """

    @abstractmethod
    def reaches(self, repository: Repository) -> bool:
        """
        :param repository: A repository.
        :return: Whether this session's reads of it are answered.
        """


@dataclass(frozen=True)
class ApiRepositoryReach(RepositoryReach):
    """
    Asks GitHub's REST API for each repository, and takes an answer as reach.
    """

    api: RestWriter
    """
    How this session's reads reach GitHub.
    """

    def reaches(self, repository: Repository) -> bool:
        route = RepositoryRoute(repository)
        return self.api.attempt(HTTPMethod.GET, route.root).succeeded


@dataclass(frozen=True)
class SavedTagSource(TagSource):
    """
    Reads the newest answer the repository's Actions saved, and adds what this session
    reads itself: the issues and pull requests on the repositories it reaches.
    """

    reading: ForwardedReading
    """
    Reads the answers the repository's Actions saved.
    """

    client: GitHubReader
    """
    How this session's own reads reach GitHub.
    """

    reach: RepositoryReach
    """
    Which repositories this session's own reads reach.
    """

    login: str
    """
    The person.
    """

    def found_tags(self, since: datetime | None) -> FoundTags:
        """
        :return: The tagged comments found, complete up to when the saved answer was
            asked for; see :meth:`TagSource.found_tags`.
        """
        self.reading.notes.fetch()
        saved = self.reading.latest_answer(TagRequest)
        read_here = SelfMention.every_mention(
            self.reachable_conversations(since), self.login
        )
        if isinstance(saved, ForwardedReadUnavailable):
            return FoundTags(tuple(read_here), None, saved)
        urls = {mention.comment.url for mention in read_here}
        merged = read_here + [
            mention for mention in saved.mentions if mention.comment.url not in urls
        ]
        ordered = sorted(merged, key=lambda mention: mention.comment.created_at)
        return FoundTags(tuple(ordered), saved.complete_until)

    def reachable_conversations(self, since: datetime | None) -> list[Conversation]:
        """
        :param since: The time before which conversations are not looked for.
        :return: The issues and pull requests found on the repositories this session
            reaches, read.
        """
        search = SelfMentionSearch(self.client, self.login, since)
        reader = ConversationReader(self.client)
        found = search.issue_conversations()
        reached = {
            repository: self.reach.reaches(repository)
            for repository in {address.repository for address in found}
        }
        return [
            reader.read(address) for address in found if reached[address.repository]
        ]


# %% the ledger


class TagLedgerKey(StrEnum):
    """
    The keys of the ledger, as the notes branch holds it.
    """

    CURSOR = "cursor"
    """
    The time before which every tag is handled.
    """

    HANDLED = "handled"
    """
    The tags handled since that time.
    """

    COMMENT = "comment"
    """
    A handled tag's comment page.
    """

    WRITTEN = "written"
    """
    When a handled tag's comment was written.
    """

    ISSUE = "issue"
    """
    The page of the issue a tag was filed as, absent when it was dismissed.
    """


@dataclass(frozen=True)
class HandledTag:
    """
    A tagged comment filed or dismissed.
    """

    comment: str
    """
    The comment's page.
    """

    written: datetime
    """
    When the comment was written.
    """

    issue: str | None
    """
    The page of the issue it was filed as, ``None`` when it was dismissed.
    """

    def to_json(self) -> dict[str, str]:
        """:return: The tag, as the ledger holds it."""
        written = {
            TagLedgerKey.COMMENT: self.comment,
            TagLedgerKey.WRITTEN: self.written.isoformat(),
        }
        if self.issue is not None:
            written[TagLedgerKey.ISSUE] = self.issue
        return written

    @classmethod
    def from_json(cls, data: dict[str, str]) -> HandledTag:
        """
        :param data: A tag, as :meth:`to_json` wrote it.
        :return: The tag.
        """
        return cls(
            data[TagLedgerKey.COMMENT],
            datetime.fromisoformat(data[TagLedgerKey.WRITTEN]),
            data.get(TagLedgerKey.ISSUE),
        )


@dataclass(frozen=True)
class TagLedger:
    """
    What is done about the tagged comments: a cursor before which every tag is
    handled, and each tag handled since, filed or dismissed.
    """

    cursor: datetime | None = None
    """
    The time before which every tag is handled, ``None`` before the first is.
    """

    handled: tuple[HandledTag, ...] = ()
    """
    The tags handled whose comment was written since :attr:`cursor`.
    """

    @classmethod
    def read(cls, notes: NotesBranch) -> TagLedger:
        """
        :param notes: The notes branch, as last fetched.
        :return: The ledger it holds, an empty one when it holds none.
        """
        text = notes.read(NotesFile.TAG_LEDGER)
        if text is None:
            return cls()
        data = json.loads(text)
        cursor = data.get(TagLedgerKey.CURSOR)
        return cls(
            None if cursor is None else datetime.fromisoformat(cursor),
            tuple(HandledTag.from_json(entry) for entry in data[TagLedgerKey.HANDLED]),
        )

    def to_json(self) -> str:
        """:return: The ledger, as :meth:`read` reads it."""
        written: dict[str, Any] = {
            TagLedgerKey.HANDLED: [tag.to_json() for tag in self.handled]
        }
        if self.cursor is not None:
            written[TagLedgerKey.CURSOR] = self.cursor.isoformat()
        return json.dumps(written, indent=2) + "\n"

    def waiting(self, found: FoundTags) -> list[SelfMention]:
        """
        :param found: The tagged comments a search found.
        :return: Those neither before the cursor nor handled, oldest first.
        """
        handled = {tag.comment for tag in self.handled}
        return [
            mention
            for mention in found.mentions
            if mention.comment.url not in handled
            and (self.cursor is None or mention.comment.created_at >= self.cursor)
        ]

    def handle(
        self, mention: SelfMention, issue: str | None, found: FoundTags
    ) -> TagLedger:
        """
        :param mention: A tagged comment waiting.
        :param issue: The page of the issue it was filed as, ``None`` when dismissed.
        :param found: The search it was found by.
        :return: The ledger with it handled, the cursor moved up to the oldest tag
            still waiting, as far as the search is complete, and the tags written
            before the cursor left out.
        """
        tag = HandledTag(mention.comment.url, mention.comment.created_at, issue)
        ledger = replace(self, handled=(*self.handled, tag))
        if found.complete_until is None:
            return ledger
        still_waiting = [
            mention.comment.created_at for mention in ledger.waiting(found)
        ]
        cursor = min([found.complete_until, *still_waiting])
        if self.cursor is not None:
            cursor = max(cursor, self.cursor)
        return TagLedger(
            cursor, tuple(tag for tag in ledger.handled if tag.written >= cursor)
        )

    def save(self, notes: NotesBranch, message: str) -> None:
        """
        :param notes: The notes branch to write the ledger to.
        :param message: The commit message.
        """
        notes.write(TextFiles({NotesFile.TAG_LEDGER: self.to_json()}), message)


# %% what the person is shown


@dataclass(frozen=True)
class TagDescription:
    """
    A tagged comment, as the person and the session are shown it.
    """

    mention: SelfMention
    """
    The tagged comment.
    """

    @property
    def listing_line(self) -> str:
        """
        :return: A Markdown link to the comment, named by its conversation, with the
            conversation's title and the comment's first line.
        """
        address = self.mention.conversation.address
        first_line = next(iter(self.mention.comment.body.strip().splitlines()), "")
        return (
            f"[{address.described}]({self.mention.comment.url}) "
            f"{self.mention.conversation.title}: {first_line}"
        )

    @property
    def conversation_text(self) -> str:
        """
        :return: The whole conversation the comment was written in: its title and page,
            then every text in it, oldest first, with who wrote it, when and where.
        """
        conversation = self.mention.conversation
        texts = sorted(conversation.comments, key=lambda comment: comment.created_at)
        parts = [f"{conversation.title} ({conversation.address.url})"]
        parts += [
            f"--- {comment.author or 'a deleted account'}, "
            f"{comment.created_at.isoformat()}, {comment.url}"
            f"{' (the tagged comment)' if comment == self.mention.comment else ''}:\n"
            f"{comment.body.strip()}"
            for comment in texts
        ]
        return "\n\n".join(parts)


# %% the tags waiting


@dataclass(frozen=True)
class TagStatus:
    """
    The ledger, and the tagged comments a search since its cursor found.
    """

    ledger: TagLedger
    """
    What is done about the tagged comments.
    """

    found: FoundTags
    """
    The tagged comments found.
    """

    def waiting_tag(self, comment: str) -> SelfMention:
        """
        :param comment: A tagged comment's page.
        :return: The tagged comment waiting at that page.
        :raises UnknownTagError: If none waits there.
        """
        mention = next(
            (
                mention
                for mention in self.ledger.waiting(self.found)
                if mention.comment.url == comment
            ),
            None,
        )
        if mention is None:
            raise UnknownTagError(comment)
        return mention


@dataclass(frozen=True)
class WaitingTags:
    """
    Reads where the tagged comments stand: the ledger and a search since its cursor.
    """

    source: TagSource
    """
    Finds the tagged comments.
    """

    notes: NotesBranch
    """
    The notes branch holding the ledger.
    """

    def read(self) -> TagStatus:
        """
        :return: The ledger as the notes branch holds it now, and what a search since
            its cursor found.
        """
        self.notes.fetch()
        ledger = TagLedger.read(self.notes)
        return TagStatus(ledger, self.source.found_tags(ledger.cursor))


@dataclass(frozen=True)
class TagSection(ReportSection):
    """
    The tagged comments waiting, each a Markdown link to the comment; nothing is
    written.
    """

    tags: WaitingTags
    """
    The tagged comments waiting.
    """

    def lines(self) -> list[ReportLine]:
        status = self.tags.read()
        items = [
            ReportLine(TagDescription(mention).listing_line, Tone.ACTION)
            for mention in status.ledger.waiting(status.found)
        ]
        heading = "comments you tagged, filed only on your word"
        lines = ReportGroup(heading, items).lines()
        reason = status.found.missing_reason
        if reason is not None:
            lines.append(ReportLine(Speaker.WORKFLOW.says(reason.line()), Tone.NEWS))
        return lines


# %% the commands


@dataclass(frozen=True)
class TagListing(WorkflowStep):
    """
    The tagged comments waiting, one per line; nothing is written.
    """

    tags: WaitingTags
    """
    The tagged comments waiting.
    """

    def run(self) -> str:
        """
        :return: One tagged comment per line; overrides :meth:`WorkflowStep.run`, which
            reports in one line.
        """
        status = self.tags.read()
        lines = [
            TagDescription(mention).listing_line
            for mention in status.ledger.waiting(status.found)
        ]
        lines = lines or ["no tagged comments waiting"]
        if status.found.missing_reason is not None:
            lines.append(status.found.missing_reason.line())
        return "\n".join(lines)


@dataclass(frozen=True)
class TagShowing(WorkflowStep):
    """
    The whole conversation a waiting tagged comment was written in; nothing is
    written.
    """

    tags: WaitingTags
    """
    The tagged comments waiting.
    """

    comment: str
    """
    The tagged comment's page.
    """

    def run(self) -> str:
        """
        :return: The conversation, over many lines; overrides :meth:`WorkflowStep.run`,
            which reports in one line.
        :raises UnknownTagError: If no tagged comment waits at the page.
        """
        mention = self.tags.read().waiting_tag(self.comment)
        return TagDescription(mention).conversation_text


@dataclass(frozen=True)
class TagFiling(WorkflowStep):
    """
    A waiting tagged comment filed as an unreviewed finding on one of the owner's
    repositories, linking the comment, and recorded in the ledger.
    """

    tags: WaitingTags
    """
    The tagged comments waiting.
    """

    comment: str
    """
    The tagged comment's page.
    """

    board: IssueTracker
    """
    The issues of the owner's repository the finding is filed on.
    """

    repository: Repository
    """
    That repository.
    """

    title: str
    """
    The finding's title.
    """

    body: str
    """
    The finding's text, summing up the conversation.
    """

    priority: Priority
    """
    How urgent the finding is.
    """

    def run(self) -> str:
        """
        :raises UnknownTagError: If no tagged comment waits at the page.
        """
        status = self.tags.read()
        mention = status.waiting_tag(self.comment)
        body = f"{self.body.rstrip()}\n\nTagged in {mention.comment.url}\n"
        number = FindingFiling(self.board, self.title, body, self.priority).file([])
        issue = self.repository.issue_url(number)
        status.ledger.handle(mention, issue, status.found).save(
            self.tags.notes, f"File the tagged comment {mention.comment.url}"
        )
        return f"filed {self.repository}#{number} ({self.priority.level}) for {self.comment}"


@dataclass(frozen=True)
class TagDismissal(WorkflowStep):
    """
    A waiting tagged comment recorded in the ledger as handled, without filing it.
    """

    tags: WaitingTags
    """
    The tagged comments waiting.
    """

    comment: str
    """
    The tagged comment's page.
    """

    def run(self) -> str:
        """
        :raises UnknownTagError: If no tagged comment waits at the page.
        """
        status = self.tags.read()
        mention = status.waiting_tag(self.comment)
        status.ledger.handle(mention, None, status.found).save(
            self.tags.notes, f"Dismiss the tagged comment {mention.comment.url}"
        )
        return f"dismissed {self.comment}"


# %% answering requests, on the runner


def main() -> None:
    """
    Answer the requests waiting in the directory the command line names.
    """
    ForwardedReadAnswering.answer_command_line(TagRequest)


if __name__ == "__main__":
    main()
