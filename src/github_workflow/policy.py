"""
The rules every write the workflow makes passes first: only the owner's repository,
never the default branch directly, and commits that credit no assistant.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from functools import cached_property

from basstler_domain_model.github.repository_client import RepositoryDetails

from github_workflow.checkout import ProjectCheckout
from github_workflow.exceptions import (
    AssistantCreditError,
    DefaultBranchWriteError,
    DetachedHeadError,
)
from github_workflow.remotes import OwnedRemote

# %% attribution


class Attribution(StrEnum):
    """
    How a commit acknowledges an assistant's help, and how one would credit it instead.
    """

    ACKNOWLEDGEMENT = "Made with AI assistance"
    """
    The line every commit's message carries.
    """

    CO_AUTHOR_TRAILER = "co-authored-by:"
    """
    The trailer crediting a co-author, compared in lower case.
    """


class AssistantMarker(StrEnum):
    """
    Words that, in an author or a co-author trailer, name an assistant; compared in
    lower case.
    """

    ANTHROPIC = "anthropic"
    """
    The company, as an assistant's commit address names it.
    """

    CLAUDE = "claude"
    """
    The assistant, by name.
    """

    @classmethod
    def names_an_assistant(cls, text: str) -> bool:
        """
        :param text: An author identity or a trailer line.
        :return: Whether it names an assistant.
        """
        return any(marker in text.casefold() for marker in cls)


# %% the rules


@dataclass(frozen=True)
class WritePolicy:
    """
    Where the workflow writes, and what it refuses to write.
    """

    checkout: ProjectCheckout
    """
    The checkout the writes start from.
    """

    remote: OwnedRemote
    """
    The owner's remote, the only one written to.
    """

    details: RepositoryDetails
    """
    Reads the repository's default branch.
    """

    @cached_property
    def default_branch(self) -> str:
        """
        The branch only pull requests change.
        """
        return self.details.default_branch()

    def work_branch(self) -> str:
        """
        :return: The checked-out branch, which a commit or a push may change.
        :raises DetachedHeadError: If no branch is checked out.
        :raises DefaultBranchWriteError: If it is the default branch.
        """
        branch = self.checkout.git.checked_out_branch()
        if not branch:
            raise DetachedHeadError()
        if branch == self.default_branch:
            raise DefaultBranchWriteError(branch)
        return branch

    def commit_message(self, message: str) -> str:
        """
        :param message: The message asked for.
        :return: It, acknowledging the assistant's help.
        :raises AssistantCreditError: If the commit's author or a trailer of the message
            credits an assistant.
        """
        author = self.checkout.git.run("var", "GIT_AUTHOR_IDENT")
        if AssistantMarker.names_an_assistant(author):
            raise AssistantCreditError(author)
        for line in message.splitlines():
            credits_co_author = (
                line.strip().casefold().startswith(Attribution.CO_AUTHOR_TRAILER)
            )
            if credits_co_author and AssistantMarker.names_an_assistant(line):
                raise AssistantCreditError(line.strip())
        if Attribution.ACKNOWLEDGEMENT in message:
            return message
        return f"{message.rstrip()}\n\n{Attribution.ACKNOWLEDGEMENT}"
