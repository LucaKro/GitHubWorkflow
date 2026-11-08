"""
Every error reading or writing GitHub ends in, whichever way it is reached.
"""

from __future__ import annotations

from abc import ABC
from dataclasses import dataclass
from enum import StrEnum

from basstler_domain_model.exceptions import DataclassException, ExternalCallFailed
from basstler_domain_model.repository import Repository

# %% reading one pull request's review state


class PullRequestReadError(DataclassException, ABC):
    """
    Base class for every failure reading a pull request's checks and review state.
    """


@dataclass
class GraphQLErrorsReturned(PullRequestReadError):
    """
    Raised when GitHub answers with an ``errors`` array instead of data.
    """

    messages: list[str]
    """
    Every message GitHub reported.
    """

    def error_message(self) -> str:
        return "GitHub answered with errors: " + "; ".join(self.messages)

    def suggest_correction(self) -> str:
        return (
            "Check that the upstream repository and pull request exist and that the "
            "logged-in account can read them"
        )


@dataclass
class GraphQLDataMissingError(PullRequestReadError):
    """
    Raised when GitHub answers a query with neither data nor errors.
    """

    def error_message(self) -> str:
        return "GitHub answered the query with neither data nor errors"

    def suggest_correction(self) -> str:
        return (
            "Run the query again; if it keeps coming back empty, check GitHub's status."
        )


@dataclass
class ReviewThreadWithoutCommentsError(PullRequestReadError, ValueError):
    """
    Raised when GitHub lists a review thread that names no comments.
    """

    path: str
    """
    The file the thread is attached to.
    """

    line: int | None
    """
    The line the thread is attached to, ``None`` once its hunk is outdated.
    """

    def error_message(self) -> str:
        return f"the review thread on {self.path}:{self.line} names no comments"

    def suggest_correction(self) -> str:
        return "Read the pull request's review threads again."


@dataclass
class UpstreamPullRequestNotFound(PullRequestReadError):
    """
    Raised when a branch has no pull request open on the upstream.
    """

    branch: str
    """
    The fork branch that was looked up.
    """

    upstream: Repository
    """
    The repository that was searched.
    """

    fork_owner: str
    """
    The owner whose head branches were being claimed.
    """

    def error_message(self) -> str:
        return (
            f"no pull request on {self.upstream} has head "
            f"'{self.fork_owner}:{self.branch}'"
        )

    def suggest_correction(self) -> str:
        return (
            "The branch has most likely not been promoted upstream yet; read it once "
            "its upstream pull request is open"
        )


# %% reading GitHub's fixed values


@dataclass
class UnrecognisedGitHubValueError(DataclassException, ValueError):
    """
    Raised when GitHub reports a value its vocabulary here does not know, such as one
    GitHub added later.
    """

    vocabulary: type[StrEnum]
    """
    The set of values it was read as.
    """

    value: str
    """
    The value GitHub reported.
    """

    def error_message(self) -> str:
        return f"GitHub reported {self.value!r}, which {self.vocabulary.__name__} does not know"

    def suggest_correction(self) -> str:
        return f"Add {self.value!r} to {self.vocabulary.__name__}, with what it means."


@dataclass
class NoCheckOutcomesError(DataclassException, ValueError):
    """
    Raised when a verdict is asked for over no checks at all.
    """

    def error_message(self) -> str:
        return "a verdict needs at least one check's outcome"

    def suggest_correction(self) -> str:
        return "Report no verdict when no check has reported."


# %% calling the REST API with a token


@dataclass
class GitHubCredentialUnavailableError(DataclassException, RuntimeError):
    """
    Raised when no token is available to authenticate the API calls with.
    """

    variables: tuple[str, ...]
    """
    The environment variables that were consulted.
    """

    def error_message(self) -> str:
        return (
            f"no GitHub token: set one of {', '.join(self.variables)}, or run this "
            f"with a caller that has one"
        )

    def suggest_correction(self) -> str:
        return ""


@dataclass
class GitHubRequestFailed(ExternalCallFailed):
    """
    Raised when the API refuses a call the caller depends on.
    """

    method: str = ""
    """
    The HTTP method used.
    """

    path: str = ""
    """
    The API path called, without the host.
    """

    @property
    def call(self) -> str:
        """:return: The request line, as issued."""
        return f"{self.method} {self.path}"


# %% reading a fetched pull request


@dataclass
class MissingPullRequestFieldError(DataclassException, ValueError):
    """
    Raised when a fetched pull request omits a field the caller reads it by.

    A fetch that drops a field is not partially correct: absent and legitimately empty
    are different facts, and defaulting one to the other is what makes bad data
    indistinguishable from good.
    """

    field_name: str
    """
    The key of the field that was absent.
    """

    pull_request_number: int | None
    """
    The pull request it was absent from, or ``None`` when the number itself is.
    """

    def error_message(self) -> str:
        subject = (
            f"pull request {self.pull_request_number}"
            if self.pull_request_number is not None
            else "a fetched pull request"
        )
        return f"{subject} has no '{self.field_name}'"

    def suggest_correction(self) -> str:
        return ""


# %% reading an issue


@dataclass
class NotAnIssueError(DataclassException, ValueError):
    """
    Raised when the number read as an issue belongs to a pull request.
    """

    number: int
    """
    The pull request's number.
    """

    def error_message(self) -> str:
        return f"#{self.number} is a pull request, not an issue"

    def suggest_correction(self) -> str:
        return "Name the number of an issue."


# %% writing labels


@dataclass
class ContradictoryLabelWriteError(DataclassException, ValueError):
    """
    Raised when one write is asked both to carry a label and to drop it.
    """

    labels: tuple[str, ...]
    """
    The labels asked for in both directions.
    """

    def error_message(self) -> str:
        return (
            f"cannot both add and remove {', '.join(self.labels)}: "
            f"either outcome would be a guess at what was meant"
        )

    def suggest_correction(self) -> str:
        return "Ask for each label to be either added or removed, not both."


# %% recorded answers


@dataclass
class RecordedAnswersExhaustedError(DataclassException, LookupError):
    """
    Raised when a query is sent to recorded GraphQL answers that have all been given.
    """

    given: int
    """
    How many answers were recorded, and given.
    """

    def error_message(self) -> str:
        return f"all {self.given} recorded GraphQL answers were given already"

    def suggest_correction(self) -> str:
        return (
            "Replay the answers to the same queries, in the order they were recorded."
        )


# %% stacks


@dataclass
class StackContinuesAboveError(DataclassException, ValueError):
    """
    Raised when a pull request is to go on top of one that other pull requests in its
    stack already build on.
    """

    below: int
    """
    The pull request that was to be built on.
    """

    above: tuple[int, ...]
    """
    The pull requests the stack already holds above it.
    """

    def error_message(self) -> str:
        holders = ", ".join(f"#{number}" for number in self.above)
        return f"#{self.below} already has {holders} stacked on it; a stack is a single line"

    def suggest_correction(self) -> str:
        return "Stack the pull request on the top of that stack instead."
