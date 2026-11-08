"""
The base every error of this package extends, and the errors raised across its
subpackages.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass

# %% the base every error extends


class DataclassException(Exception, ABC):
    """
    A base exception class for dataclass-based exceptions.

    Subclasses implement error_message() and suggest_correction(); both are evaluated at
    construction time and composed into the actual exception message (the args passed to
    Exception). A non-empty suggest_correction() is rendered as a trailing "Suggestion:
    ..." line. Subclasses that override __post_init__ must call super().__post_init__()
    at the end.
    """

    def __post_init__(self) -> None:
        """
        Refuse an abstract subclass, and compose the message the exception carries.

        :raises TypeError: If the subclass leaves an abstract method unimplemented.
        """
        # BaseException.__new__ bypasses the usual ABC instantiation check, so enforce it here.
        if type(self).__abstractmethods__:
            raise TypeError(
                f"Can't instantiate abstract class {type(self).__name__} without an implementation of "
                f"{', '.join(sorted(type(self).__abstractmethods__))}."
            )
        message = self.error_message()
        correction = self.suggest_correction()
        if correction:
            message = f"{message}\nSuggestion: {correction}"
        super().__init__(message)

    def __str__(self) -> str:
        # Stdlib mixins like KeyError override __str__ to repr their args; always render the
        # plain message that __post_init__ baked into the args.
        return Exception.__str__(self)

    @abstractmethod
    def error_message(self) -> str:
        """
        :return: A human-readable description of what went wrong.
        """

    @abstractmethod
    def suggest_correction(self) -> str:
        """
        :return: Advice on how to fix the error, or an empty string if there is no specific advice.
        """


# %% calls to git or GitHub


@dataclass
class ExternalCallFailed(DataclassException, RuntimeError, ABC):
    """
    Base for a call to git or GitHub that the caller depended on and did not get.

    Both carry the same three things under different names - what was called, the status
    it came back with, and what it said - so they say so once here and differ only in how
    they name the call.
    """

    status: int | None
    """
    The status the call came back with, ``None`` when it could not be made at all.
    """

    detail: str
    """
    What the far side said about it.
    """

    @property
    @abstractmethod
    def call(self) -> str:
        """
        :return: The call that failed, named the way its own caller named it.
        """

    def error_message(self) -> str:
        return f"{self.call} failed with {self.status}: {self.detail}"

    def suggest_correction(self) -> str:
        return ""


# %% repositories


@dataclass
class MalformedRepositoryError(DataclassException, ValueError):
    """
    Raised when a repository reference is not in ``owner/name`` form.
    """

    text: str
    """
    The value that could not be parsed.
    """

    def error_message(self) -> str:
        return f"expected a repository as 'owner/name', got {self.text!r}"

    def suggest_correction(self) -> str:
        return ""
