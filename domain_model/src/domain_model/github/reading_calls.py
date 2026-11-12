"""
Which calls to GitHub only read: gh commands, GraphQL documents, the GitHub MCP
server's tools, and HTTP clients sending to GitHub.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass
from enum import Enum, StrEnum, auto
from http import HTTPMethod

from domain_model.class_property import classproperty
from domain_model.github.vocabulary import (
    GitHubCliReading,
    GitHubCliSubcommand,
    GitHubHost,
    GraphQLOperation,
)

# %% sending options


@dataclass(frozen=True)
class SendingOptions:
    """
    The options with which an HTTP client sends something rather than reads.
    """

    short: str
    """
    The single letters that send, wherever they stand in a cluster of short options.
    """

    long: tuple[str, ...]
    """
    The long options that send, matched as prefixes so ``--data-raw`` counts as
    ``--data``.
    """

    method_short: str
    """
    The single letter naming the request method, which reads when it is ``GET``.
    """

    method_long: tuple[str, ...]
    """
    The long options naming the request method.
    """

    def sends(self, arguments: Sequence[str]) -> bool:
        """
        :param arguments: A call's arguments.
        :return: Whether one of them sends something.
        """
        for index, argument in enumerate(arguments):
            following = "".join(arguments[index + 1 : index + 2])
            if argument.startswith("--"):
                option, _, value = argument.partition("=")
                if option.startswith(self.long):
                    return True
                if option in self.method_long and (value or following).upper() != "GET":
                    return True
                continue
            if not argument.startswith("-"):
                continue
            letters = argument[1:]
            for position, letter in enumerate(letters):
                if letter == self.method_short:
                    method = letters[position + 1 :] or following
                    if method.upper() != "GET":
                        return True
                    break
                if letter in self.short:
                    return True
        return False

    def named_method(self, arguments: Sequence[str]) -> str | None:
        """
        :param arguments: A call's arguments.
        :return: The request method an option of its own names, in upper case;
            ``None`` when none does, or only within a cluster of short options.
        """
        for index, argument in enumerate(arguments):
            following = "".join(arguments[index + 1 : index + 2])
            option, _, value = argument.partition("=")
            if option in self.method_long:
                return (value or following).upper()
            short = f"-{self.method_short}"
            if self.method_short and argument.startswith(short):
                return (argument.removeprefix(short) or following).upper()
        return None


# %% gh


@dataclass(frozen=True)
class GraphQLCall:
    """
    A ``gh api graphql`` call, which sends its document as the field ``query``.
    """

    options: Sequence[str]
    """
    What follows ``graphql``.
    """

    @classproperty
    def endpoint(cls) -> str:
        """
        The endpoint ``gh api`` sends GraphQL documents to.
        """
        return "graphql"

    @classproperty
    def field_options(cls) -> tuple[str, ...]:
        """
        The options each naming one field as ``name=value``.
        """
        return ("-f", "-F", "--field", "--raw-field")

    @classproperty
    def shaping_options(cls) -> tuple[str, ...]:
        """
        The options taking a value that only shape what is printed or how it is asked
        for, never what is sent.
        """
        return ("--jq", "-q", "--template", "-t", "--cache", "--header", "-H")

    @classproperty
    def shaping_flags(cls) -> tuple[str, ...]:
        """
        The options without a value that only shape what is printed.
        """
        return ("--paginate", "--slurp", "--silent", "--include", "-i", "--verbose")

    def fields(self) -> dict[str, str] | None:
        """
        :return: Every field sent, by name; ``None`` when an option is neither a field
            nor one only shaping the output.
        """
        fields: dict[str, str] = {}
        options = list(self.options)
        while options:
            option = options.pop(0)
            if option in self.shaping_flags:
                continue
            if option in self.shaping_options and options:
                options.pop(0)
                continue
            if option.startswith(
                tuple(f"{shaping}=" for shaping in self.shaping_options)
            ):
                continue
            if option in self.field_options and options:
                given = options.pop(0)
            elif option.startswith(("-f", "-F")) and len(option) > 2:
                given = option[2:]
            elif option.startswith(("--field=", "--raw-field=")):
                given = option.partition("=")[2]
            else:
                return None
            name, _, value = given.partition("=")
            fields[name] = value
        return fields

    def reads(self) -> bool:
        """
        :return: Whether every option is a field and the document, given in place
            rather than read from a file, holds queries alone.
        """
        fields = self.fields()
        if fields is None:
            return False
        document = fields.get(GraphQLOperation.QUERY, "")
        if not document or document.startswith("@"):
            return False
        words = set(re.findall(r"[A-Za-z_]+", document))
        written = {GraphQLOperation.MUTATION, GraphQLOperation.SUBSCRIPTION}
        return not words & written and document.lstrip().startswith(
            ("{", GraphQLOperation.QUERY)
        )


class GitHubCliEffect(Enum):
    """
    What a gh call does beyond reading.
    """

    GRAPHQL_WRITE = auto()
    """
    It sends GraphQL a mutation, or a document that cannot be read.
    """

    API_SENDS = auto()
    """
    gh api sends a method other than GET, a field or an input.
    """

    WRITES = auto()
    """
    It writes, or is no command known to only read.
    """


@dataclass(frozen=True)
class GitHubCliCall:
    """
    One gh call, by what follows gh.
    """

    arguments: Sequence[str]
    """
    What follows gh.
    """

    @classproperty
    def api_sending(cls) -> SendingOptions:
        """
        The options with which gh api sends something; a field alone makes it a
        POST.
        """
        return SendingOptions(
            "fF", ("--field", "--raw-field", "--input"), "X", ("--method",)
        )

    @classproperty
    def api_input(cls) -> str:
        """
        The option sending a file as the request's body, whatever the method.
        """
        return "--input"

    @property
    def command(self) -> str:
        """:return: The command's first two words, its options left out."""
        words = [
            argument for argument in self.arguments if not argument.startswith("-")
        ]
        return " ".join(words[:2])

    def effect(self) -> GitHubCliEffect | None:
        """
        :return: What the call does beyond reading, None when it only reads.
        """
        first = self.command.partition(" ")[0]
        if first == GitHubCliSubcommand.API:
            return self.api_effect(self.arguments[1:])
        if first == GitHubCliSubcommand.SEARCH or self.command in GitHubCliReading:
            return None
        return GitHubCliEffect.WRITES

    def api_effect(self, options: Sequence[str]) -> GitHubCliEffect | None:
        """
        :param options: What follows gh api.
        :return: What the call does beyond reading, None when it only reads.
        """
        if options[:1] == [GraphQLCall.endpoint]:
            if GraphQLCall(options[1:]).reads():
                return None
            return GitHubCliEffect.GRAPHQL_WRITE
        queries = self.api_sending.named_method(options) == HTTPMethod.GET and not any(
            argument.startswith(self.api_input) for argument in options
        )
        if self.api_sending.sends(options) and not queries:
            return GitHubCliEffect.API_SENDS
        return None


# %% HTTP clients


class HttpClient(Enum):
    """
    The HTTP clients that could call GitHub's API, by their program's name, each with
    the options with which it sends something.
    """

    CURL = (
        "curl",
        SendingOptions(
            "dFT", ("--data", "--json", "--form", "--upload-file"), "X", ("--request",)
        ),
    )
    """
    curl.
    """

    WGET = (
        "wget",
        SendingOptions(
            "",
            ("--post-data", "--post-file", "--body-data", "--body-file"),
            "",
            ("--method",),
        ),
    )
    """
    wget.
    """

    def __init__(self, program: str, sending: SendingOptions) -> None:
        """
        :param program: The client's program, by its name.
        :param sending: Its options that send something.
        """
        self.program = program
        self.sending = sending

    def sends_to_github(self, arguments: Sequence[str]) -> bool:
        """
        :param arguments: What follows the client's name.
        :return: Whether the call sends something to GitHub.
        """
        reaches_github = any(
            host in argument for argument in arguments for host in GitHubHost
        )
        return reaches_github and self.sending.sends(arguments)


# %% the GitHub MCP server


class GitHubToolReading(StrEnum):
    """
    How the names of GitHub MCP tools that only read start.
    """

    GET = "get_"
    """
    Reads one thing.
    """

    LIST = "list_"
    """
    Lists things.
    """

    SEARCH = "search_"
    """
    Searches.
    """

    @classmethod
    def names_a_read(cls, name: str) -> bool:
        """
        :param name: A GitHub MCP tool's name, without its server's prefix.
        :return: Whether the tool only reads.
        """
        return name.startswith(tuple(cls)) or name.endswith(
            tuple(GitHubToolReadingEnding)
        )


class GitHubToolReadingEnding(StrEnum):
    """
    How the names of GitHub MCP tools that only read end, in the newer tool names,
    which name the thing first and what they do with it last.
    """

    READ = "_read"
    """
    Reads, such as ``pull_request_read``.
    """

    LIST = "_list"
    """
    Lists things, such as ``actions_list``.
    """

    GET = "_get"
    """
    Reads one thing, such as ``actions_get``.
    """
