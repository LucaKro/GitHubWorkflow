"""
Issues and their comments as the REST API lists them.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from domain_model.github.vocabulary import (
    IssueEventType,
    IssueState,
    JSONModel,
    RestJSONKey,
)

# %% one issue


@dataclass(frozen=True)
class Issue(JSONModel):
    """
    One issue: its number, title, labels and whether it is open.
    """

    number: int
    """
    The issue's number.
    """

    title: str
    """
    Its title.
    """

    labels: tuple[str, ...]
    """
    The names of the labels it carries.
    """

    state: IssueState
    """
    Whether it is open.
    """

    @classmethod
    def from_json(cls, data: dict[str, Any]) -> Issue:
        return cls(
            data[RestJSONKey.NUMBER],
            data[RestJSONKey.TITLE],
            tuple(label[RestJSONKey.NAME] for label in data[RestJSONKey.LABELS]),
            IssueState(data[RestJSONKey.STATE]),
        )

    @staticmethod
    def is_pull_request(data: dict[str, Any]) -> bool:
        """
        :param data: One entry of an issue listing.
        :return: Whether it is a pull request, which the issues API lists among the
            issues.
        """
        return RestJSONKey.PULL_REQUEST in data


# %% one comment


@dataclass(frozen=True)
class IssueComment(JSONModel):
    """
    One comment on an issue: who wrote it, and what it says.
    """

    author: str
    """
    The login of the account that wrote it.
    """

    body: str
    """
    Its text, as Markdown.
    """

    @classmethod
    def from_json(cls, data: dict[str, Any]) -> IssueComment:
        return cls(data[RestJSONKey.USER][RestJSONKey.LOGIN], data[RestJSONKey.BODY])


@dataclass(frozen=True)
class LabelEvent(JSONModel):
    """
    A label added to or removed from an issue.
    """

    label: str
    """
    The label's name.
    """

    added: bool
    """
    Whether it was added; removed otherwise.
    """

    @classmethod
    def from_json(cls, data: dict[str, Any]) -> LabelEvent:
        return cls(
            data[RestJSONKey.LABEL][RestJSONKey.NAME],
            data[RestJSONKey.EVENT] == IssueEventType.LABELED,
        )

    @staticmethod
    def is_label_event(data: dict[str, Any]) -> bool:
        """
        :param data: One of an issue's events.
        :return: Whether it adds or removes a label.
        """
        return data.get(RestJSONKey.EVENT) in set(IssueEventType)
