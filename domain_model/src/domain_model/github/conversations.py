"""
Conversations on GitHub - issues, pull requests and discussions - read as the comments
written in them, and found by searching for an account that mentions itself in one.
"""

from __future__ import annotations

import re
from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import StrEnum
from typing import Any
from urllib.parse import urlsplit

from domain_model.github.clients import GitHubReader
from domain_model.github.exceptions import MalformedConversationUrlError
from domain_model.github.review_models import PageInfo
from domain_model.github.routes import RepositoryRoute
from domain_model.github.vocabulary import (
    GraphQLDocument,
    IssueSearchType,
    PullRequestJSONKey,
    QueryVariable,
    RestJSONKey,
    SearchQualifier,
)
from domain_model.repository import GitHubAddress, Repository

# %% where a conversation is


class ConversationKind(StrEnum):
    """
    What a conversation is, by the path segment of its page on GitHub.
    """

    ISSUE = "issues"
    """
    An issue.
    """

    PULL_REQUEST = "pull"
    """
    A pull request, with its reviews and the comments on its changes.
    """

    DISCUSSION = "discussions"
    """
    A discussion, with the replies to its comments.
    """


@dataclass(frozen=True)
class ConversationAddress:
    """
    Which conversation, on which repository.
    """

    repository: Repository
    """
    The repository it is held in.
    """

    kind: ConversationKind
    """
    Whether it is an issue, a pull request or a discussion.
    """

    number: int
    """
    Its number on the repository.
    """

    @classmethod
    def from_url(cls, url: str) -> ConversationAddress:
        """
        :param url: The page of a conversation, or of one comment in it.
        :return: The conversation.
        :raises MalformedConversationUrlError: If *url* is no such page.
        """
        address = urlsplit(url)
        segments = [segment for segment in address.path.split("/") if segment]
        kinds = {kind.value for kind in ConversationKind}
        if (
            f"{address.scheme}://{address.netloc}" != GitHubAddress.WEB
            or len(segments) != 4
            or segments[2] not in kinds
            or not segments[3].isdigit()
        ):
            raise MalformedConversationUrlError(url)
        owner, name, kind, number = segments
        return cls(Repository(owner, name), ConversationKind(kind), int(number))

    @property
    def url(self) -> str:
        """:return: The conversation's page on GitHub."""
        return f"{self.repository.url}/{self.kind}/{self.number}"

    @property
    def described(self) -> str:
        """:return: The conversation as GitHub names it, ``owner/name#number``."""
        return f"{self.repository.full_name}#{self.number}"


# %% what is said in one


@dataclass(frozen=True)
class Comment:
    """
    One text written in a conversation: its opening post, a comment, a reply, a
    review, or a comment on a pull request's changes.
    """

    url: str
    """
    Its page on GitHub, which leads to the text itself.
    """

    author: str | None
    """
    The login of the account that wrote it, ``None`` once that account is deleted.
    """

    body: str
    """
    Its text, as Markdown.
    """

    created_at: datetime
    """
    When it was written.
    """

    @classmethod
    def from_json(cls, data: dict[str, Any]) -> Comment:
        """
        :param data: An issue, a pull request or a comment, as REST reads it.
        :return: The text it holds.
        """
        return cls.from_rest_fields(data, data[RestJSONKey.CREATED_AT])

    @classmethod
    def from_review_json(cls, data: dict[str, Any]) -> Comment:
        """
        :param data: A submitted review, as REST reads it.
        :return: The text it holds.
        """
        return cls.from_rest_fields(data, data[RestJSONKey.SUBMITTED_AT])

    @classmethod
    def from_rest_fields(cls, data: dict[str, Any], written: str) -> Comment:
        """
        :param data: An object holding a text, as REST reads it.
        :param written: When it was written, as REST writes a time.
        :return: The text it holds.
        """
        user = data[RestJSONKey.USER]
        return cls(
            data[RestJSONKey.HTML_URL],
            None if user is None else user[RestJSONKey.LOGIN],
            data[RestJSONKey.BODY] or "",
            datetime.fromisoformat(written),
        )

    @classmethod
    def from_graphql_json(cls, data: dict[str, Any]) -> Comment:
        """
        :param data: A discussion or one of its comments, as GraphQL reads it.
        :return: The text it holds.
        """
        author = data[PullRequestJSONKey.AUTHOR]
        return cls(
            data[PullRequestJSONKey.URL],
            None if author is None else author[PullRequestJSONKey.LOGIN],
            data[PullRequestJSONKey.BODY] or "",
            datetime.fromisoformat(data[PullRequestJSONKey.CREATED_AT]),
        )

    def mentions(self, login: str) -> bool:
        """
        :param login: An account.
        :return: Whether the text mentions it, ``@login``, as GitHub links a mention.
        """
        pattern = rf"(?<![\w@./-])@{re.escape(login)}(?![\w-]|/\w)"
        return re.search(pattern, self.body, re.IGNORECASE) is not None

    def is_written_by(self, login: str) -> bool:
        """
        :param login: An account.
        :return: Whether it wrote the text.
        """
        return self.author is not None and self.author.lower() == login.lower()


@dataclass(frozen=True)
class Conversation:
    """
    One issue, pull request or discussion, and every text written in it.
    """

    address: ConversationAddress
    """
    Which conversation it is.
    """

    title: str
    """
    Its title.
    """

    comments: tuple[Comment, ...]
    """
    Every text written in it, its opening post first.
    """

    def self_mentions(self, login: str) -> list[Comment]:
        """
        :param login: An account.
        :return: The texts it wrote that mention it.
        """
        return [
            comment
            for comment in self.comments
            if comment.is_written_by(login) and comment.mentions(login)
        ]


# %% reading them


@dataclass(frozen=True)
class GraphQLConnectionPages:
    """
    Every page of one paged list a GraphQL document reads, asked for one after the
    other.
    """

    client: GitHubReader
    """
    How the document reaches GitHub.
    """

    document: GraphQLDocument
    """
    The document reading one page.
    """

    variables: dict[str, Any]
    """
    The document's variables, besides the cursor.
    """

    cursor: QueryVariable
    """
    The variable the document takes the page's cursor in.
    """

    holder_path: tuple[PullRequestJSONKey, ...]
    """
    The keys leading from the answer's ``data`` to the object holding the paged list.
    """

    connection: PullRequestJSONKey
    """
    The key of the paged list in that object.
    """

    def read(self) -> Iterator[dict[str, Any]]:
        """
        :return: The object holding the paged list, once per page, in order.
        """
        cursor: str | None = None
        while True:
            holder = self.client.execute(
                self.document.read(), {**self.variables, self.cursor: cursor}
            )
            for key in self.holder_path:
                holder = holder[key]
            yield holder
            page = PageInfo.from_json(
                holder[self.connection][PullRequestJSONKey.PAGE_INFO]
            )
            if not page.has_next_page:
                return
            cursor = page.end_cursor


@dataclass(frozen=True)
class ConversationReader:
    """
    Reads conversations of any repository the client reaches: issues and pull requests
    over REST, discussions over GraphQL.
    """

    client: GitHubReader
    """
    How the reads reach GitHub.
    """

    def read(self, address: ConversationAddress) -> Conversation:
        """
        :param address: The conversation.
        :return: It, with every text written in it.
        """
        if address.kind is ConversationKind.DISCUSSION:
            return self.read_discussion(address)
        route = RepositoryRoute(address.repository)
        opening = self.client.get(route.issue(address.number))
        comments = [Comment.from_json(opening)]
        comments += self.read_listing(
            route.listing(route.issue_comments(address.number))
        )
        if address.kind is ConversationKind.PULL_REQUEST:
            comments += [
                Comment.from_review_json(review)
                for page in self.client.get_pages(route.reviews(address.number))
                for review in page
                if review[RestJSONKey.SUBMITTED_AT] is not None
            ]
            comments += self.read_listing(route.review_comments(address.number))
        return Conversation(address, opening[RestJSONKey.TITLE], tuple(comments))

    def read_listing(self, path: str) -> list[Comment]:
        """
        :param path: The first page of a listing of comments.
        :return: Every comment on every page.
        """
        return [
            Comment.from_json(entry)
            for page in self.client.get_pages(path)
            for entry in page
        ]

    def read_discussion(self, address: ConversationAddress) -> Conversation:
        """
        :param address: A discussion.
        :return: It, with every comment and reply written in it.
        """
        pages = GraphQLConnectionPages(
            self.client,
            GraphQLDocument.DISCUSSION_COMMENTS_PAGE,
            {
                QueryVariable.OWNER: address.repository.owner,
                QueryVariable.NAME: address.repository.name,
                QueryVariable.NUMBER: address.number,
            },
            QueryVariable.COMMENT_CURSOR,
            (PullRequestJSONKey.REPOSITORY, PullRequestJSONKey.DISCUSSION),
            PullRequestJSONKey.COMMENTS,
        )
        discussions = list(pages.read())
        comments = [Comment.from_graphql_json(discussions[0])]
        for discussion in discussions:
            for node in discussion[PullRequestJSONKey.COMMENTS][
                PullRequestJSONKey.NODES
            ]:
                comments.append(Comment.from_graphql_json(node))
                comments += [
                    Comment.from_graphql_json(reply)
                    for reply in node[PullRequestJSONKey.REPLIES][
                        PullRequestJSONKey.NODES
                    ]
                ]
        return Conversation(
            address, discussions[0][PullRequestJSONKey.TITLE], tuple(comments)
        )


# %% finding them


@dataclass(frozen=True)
class SelfMentionSearch:
    """
    Finds the conversations in which an account may have mentioned itself: those
    mentioning it that it opened, commented on or reviewed.
    """

    client: GitHubReader
    """
    How the searches reach GitHub.
    """

    login: str
    """
    The account.
    """

    since: datetime | None
    """
    The time before which conversations that have not changed since are left out,
    ``None`` to search them all.
    """

    def terms(self, *narrowing: str) -> str:
        """
        :param narrowing: Further qualifiers, as a search query writes them.
        :return: The search query.
        """
        terms = list(narrowing)
        if self.since is not None:
            utc = self.since.astimezone(timezone.utc)
            terms.append(
                SearchQualifier.UPDATED.narrowing(
                    f">={utc.strftime('%Y-%m-%dT%H:%M:%SZ')}"
                )
            )
        return " ".join(terms)

    def issue_conversations(self) -> list[ConversationAddress]:
        """
        :return: The issues and pull requests found, each once, by their page.
        """
        mentions = SearchQualifier.MENTIONS.narrowing(self.login)
        involved = {
            IssueSearchType.ISSUE: (SearchQualifier.AUTHOR, SearchQualifier.COMMENTER),
            IssueSearchType.PULL_REQUEST: (
                SearchQualifier.AUTHOR,
                SearchQualifier.COMMENTER,
                SearchQualifier.REVIEWED_BY,
            ),
        }
        found = {
            ConversationAddress.from_url(item[RestJSONKey.HTML_URL])
            for search_type, qualifiers in involved.items()
            for qualifier in qualifiers
            for page in self.client.get_pages(
                RepositoryRoute.issue_search(
                    self.terms(
                        SearchQualifier.TYPE.narrowing(search_type),
                        mentions,
                        qualifier.narrowing(self.login),
                    )
                )
            )
            for item in page[RestJSONKey.ITEMS]
        }
        return self.ordered(found)

    def discussions(self) -> list[ConversationAddress]:
        """
        :return: The discussions found, each once, by their page.
        """
        found = set()
        for qualifier in (SearchQualifier.AUTHOR, SearchQualifier.COMMENTER):
            pages = GraphQLConnectionPages(
                self.client,
                GraphQLDocument.DISCUSSION_SEARCH_PAGE,
                {QueryVariable.SEARCH: self.terms(qualifier.narrowing(self.login))},
                QueryVariable.SEARCH_CURSOR,
                (),
                PullRequestJSONKey.SEARCH,
            )
            found |= {
                ConversationAddress.from_url(node[PullRequestJSONKey.URL])
                for data in pages.read()
                for node in data[PullRequestJSONKey.SEARCH][PullRequestJSONKey.NODES]
            }
        return self.ordered(found)

    @staticmethod
    def ordered(found: set[ConversationAddress]) -> list[ConversationAddress]:
        """
        :param found: Conversations found.
        :return: Them, by repository and number.
        """
        return sorted(
            found, key=lambda address: (address.repository.full_name, address.number)
        )


# %% what an account said about itself


@dataclass(frozen=True)
class SelfMention:
    """
    A text an account wrote that mentions it, in the conversation it was written in.
    """

    comment: Comment
    """
    The text.
    """

    conversation: Conversation
    """
    The conversation it was written in.
    """

    @classmethod
    def every_mention(
        cls, conversations: Sequence[Conversation], login: str
    ) -> list[SelfMention]:
        """
        :param conversations: Conversations read.
        :param login: An account.
        :return: Every text in them it wrote that mentions it, oldest first.
        """
        return sorted(
            (
                cls(comment, conversation)
                for conversation in conversations
                for comment in conversation.self_mentions(login)
            ),
            key=lambda mention: mention.comment.created_at,
        )
