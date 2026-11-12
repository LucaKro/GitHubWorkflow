"""
Tests for :class:`domain_model.github.labels.GitHubLabel`, which a caller's own set of
labels extends, and for :class:`domain_model.github.labels.LabelWrite`.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import ReprEnum

import pytest

from domain_model.github.exceptions import ContradictoryLabelWriteError
from domain_model.github.labels import GitHubLabel, LabelWrite
from domain_model.github.repository_client import RepositoryLabels

# %% an enumeration of labels


class EnumeratedLabel(GitHubLabel, ReprEnum):
    """
    A caller's labels, enumerated, each its own name and carrying its description.
    """

    def __new__(cls, label: str, description: str) -> EnumeratedLabel:
        """
        :param label: The label's name.
        :param description: What it means.
        :return: The member.
        """
        member = str.__new__(cls, label)
        member._value_ = label
        member.description = description
        return member

    READY = ("ready", "Ready for review")
    """
    A label the tests create.
    """


def test_an_enumerated_label_is_its_own_name():
    assert EnumeratedLabel.READY == EnumeratedLabel.READY.value


def test_an_enumerated_label_is_a_label():
    assert isinstance(EnumeratedLabel.READY, GitHubLabel)


# %% the label set a write leaves behind


def test_a_label_added_twice_is_written_once() -> None:
    assert LabelWrite.from_changes(["kept"], added=["new", "new"]).labels == (
        "kept",
        "new",
    )


def test_a_label_carried_in_another_case_is_not_added_again() -> None:
    assert LabelWrite.from_changes(["Ready"], added=["ready"]).labels == ("Ready",)


def test_a_label_is_removed_whatever_its_case() -> None:
    assert LabelWrite.from_changes(["Ready", "kept"], removed=["ready"]).labels == (
        "kept",
    )


def test_a_label_both_added_and_removed_in_different_cases_is_refused() -> None:
    with pytest.raises(ContradictoryLabelWriteError):
        LabelWrite.from_changes([], added=["Ready"], removed=["ready"])


def test_labels_are_kept_in_the_order_carried_then_added() -> None:
    assert LabelWrite.from_changes(
        ["b", "a", "gone"], added=["d", "c"], removed=["gone"]
    ).labels == (
        "b",
        "a",
        "d",
        "c",
    )


# %% creating the labels a repository lacks


@dataclass(frozen=True)
class LabelsInMemory(RepositoryLabels):
    """
    A repository's labels, kept in memory, recording each label created.
    """

    present: set[str]
    """
    The labels the repository carries.
    """

    created: list[GitHubLabel] = field(default_factory=list)
    """
    Each label created, in order.
    """

    def labels(self) -> set[str]:
        return set(self.present)

    def create_label(self, label: GitHubLabel) -> None:
        self.present.add(label)
        self.created.append(label)


class WaitingLabel(GitHubLabel, ReprEnum):
    """
    Labels of a kind a repository carries some of.
    """

    def __new__(cls, label: str, description: str) -> WaitingLabel:
        """
        :param label: The label's name.
        :param description: What it means.
        :return: The member.
        """
        member = str.__new__(cls, label)
        member._value_ = label
        member.description = description
        return member

    BLOCKED = ("blocked", "Waiting on something else")
    """
    A label the repository lacks.
    """
    WAITING = ("waiting", "Waiting on its author")
    """
    A label the repository carries already.
    """


def test_only_the_labels_a_repository_lacks_are_created():
    repository = LabelsInMemory({WaitingLabel.WAITING.value})

    repository.create_missing_labels(list(WaitingLabel))

    assert repository.created == [WaitingLabel.BLOCKED]
