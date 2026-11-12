"""
Tests for :mod:`domain_model.github.issue_events`.
"""

from __future__ import annotations

import json

from domain_model.github.issue_events import IssueLabelled
from domain_model.repository import Repository

from .dataset.locations import DatasetLocation

# %% a label added


def test_the_labelled_issue_and_label_are_read_from_the_event():
    data = json.loads(DatasetLocation.ISSUE_LABELLED.read_text())

    event = IssueLabelled.from_json(data)

    assert event == IssueLabelled(
        Repository.parse(data["repository"]["full_name"]),
        data["issue"]["number"],
        data["label"]["name"],
    )
