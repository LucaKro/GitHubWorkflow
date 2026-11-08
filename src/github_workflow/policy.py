"""
The rules every write the workflow makes passes first: only the owner's repository,
never the default branch directly, and commits that credit no assistant.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from functools import cached_property

from basstler_domain_model.git.commands import GitIdentity
from basstler_domain_model.git.identity import PersonIdentity
from basstler_domain_model.github.repository_client import RepositoryDetails

from github_workflow.checkout import ProjectCheckout
from github_workflow.exceptions import (
    AssistantCreditError,
    DefaultBranchWriteError,
    DetachedHeadError,
    MergeInProgressError,
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
    What marks an identity, written as ``Name <address>``, as an assistant's; compared
    in lower case.
    """

    ANTHROPIC = "anthropic.com"
    """
    The domain an assistant's commit address is at.
    """

    CLAUDE = "claude"
    """
    The assistant's name, when it is the whole name.
    """

    @classmethod
    def names_an_assistant(cls, identity: str) -> bool:
        """
        :param identity: An identity, as ``Name <address>`` with anything after it.
        :return: Whether it is an assistant's.
        """
        person = PersonIdentity.parse(identity)
        domain = person.domain
        on_the_domain = domain == cls.ANTHROPIC or domain.endswith(f".{cls.ANTHROPIC}")
        return on_the_domain or person.name.casefold() == cls.CLAUDE


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

    def refuse_while_merging(self, branch: str) -> None:
        """
        :param branch: The checked-out branch.
        :raises MergeInProgressError: If a merge is in progress on it.
        """
        if self.checkout.git.merge_in_progress():
            raise MergeInProgressError(branch)

    def commit_message(self, message: str) -> str:
        """
        :param message: The message asked for.
        :return: It, acknowledging the assistant's help.
        :raises AssistantCreditError: If the commit's author or committer, or a trailer
            of the message, credits an assistant.
        """
        for identity in GitIdentity:
            recorded = self.checkout.git.identity(identity)
            if AssistantMarker.names_an_assistant(recorded):
                raise AssistantCreditError(recorded)
        for line in message.splitlines():
            trailer, _, co_author = line.strip().partition(":")
            credits_co_author = (
                f"{trailer.casefold()}:" == Attribution.CO_AUTHOR_TRAILER
            )
            if credits_co_author and AssistantMarker.names_an_assistant(co_author):
                raise AssistantCreditError(line.strip())
        if Attribution.ACKNOWLEDGEMENT in message:
            return message
        return f"{message.rstrip()}\n\n{Attribution.ACKNOWLEDGEMENT}"
