"""
The events GitHub hands an Actions workflow about an issue.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from domain_model.github.vocabulary import JSONModel, RestJSONKey
from domain_model.repository import Repository

# %% a label added


class IssueEventKey(StrEnum):
    """
    The keys of an ``issues`` event that the REST answers do not share.
    """

    ISSUE = "issue"
    """
    The issue the event is about.
    """

    LABEL = "label"
    """
    The label just added.
    """

    REPOSITORY = "repository"
    """
    The repository the issue is in.
    """

    FULL_NAME = "full_name"
    """
    A repository's ``owner/name``.
    """


@dataclass(frozen=True)
class IssueLabelled(JSONModel):
    """
    A label added to an issue, as the ``issues`` event of type ``labeled`` reports it.
    """

    repository: Repository
    """
    The repository the issue is in.
    """

    number: int
    """
    The issue's number.
    """

    label: str
    """
    The name of the label added.
    """

    @classmethod
    def from_json(cls, data: dict[str, Any]) -> IssueLabelled:
        return cls(
            Repository.parse(data[IssueEventKey.REPOSITORY][IssueEventKey.FULL_NAME]),
            data[IssueEventKey.ISSUE][RestJSONKey.NUMBER],
            data[IssueEventKey.LABEL][RestJSONKey.NAME],
        )
