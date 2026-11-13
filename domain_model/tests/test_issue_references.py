"""
Tests for :mod:`domain_model.github.issue_references`: bare issue numbers in Markdown
name their repository once the text moves to another.
"""

from __future__ import annotations

from domain_model.github.issue_references import IssueReferences
from domain_model.repository import Repository

from .dataset.locations import DatasetLocation

# %% qualifying references


def test_bare_numbers_outside_code_name_their_repository() -> None:
    relative = DatasetLocation.RELATIVE_REFERENCES.read_text()

    qualified = IssueReferences(relative).qualify(Repository("LucaKro", "cramera"))

    assert qualified == DatasetLocation.QUALIFIED_REFERENCES.read_text()


def test_text_without_bare_numbers_is_kept() -> None:
    text = "Nothing to see in AICOR-Solutions/cramera#7 or `#8`."

    assert IssueReferences(text).qualify(Repository("LucaKro", "cramera")) == text
