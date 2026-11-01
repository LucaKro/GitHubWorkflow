"""
Tests for :mod:`github_workflow.probe.rest`: reading what ``curl`` printed.
"""

from __future__ import annotations

import json

import pytest

from github_workflow.probe.commands import CommandResult
from github_workflow.probe.rest import RestResponse

from .dataset.locations import DatasetLocation

# %% reading curl's output


def recorded(location: DatasetLocation) -> RestResponse:
    """
    :param location: What ``curl`` printed.
    :return: It read as a response.
    """
    return RestResponse.from_command(
        CommandResult(("curl",), 0, location.read_text(), "", 0.0)
    )


def recorded_body(location: DatasetLocation) -> str:
    """
    :param location: What ``curl`` printed.
    :return: The body it printed before the status.
    """
    return location.read_text().rpartition(RestResponse.status_separator)[0]


def test_a_refusal_reads_as_failed_with_the_api_s_message():
    response = recorded(DatasetLocation.CURL_REFUSED)

    assert not response.succeeded
    assert (
        response.summary
        == json.loads(recorded_body(DatasetLocation.CURL_REFUSED))["message"]
    )


def test_a_listing_reads_as_its_entries():
    response = recorded(DatasetLocation.CURL_LISTING)

    assert response.body == json.loads(recorded_body(DatasetLocation.CURL_LISTING))


def test_an_answer_without_a_body_still_succeeds():
    assert recorded(DatasetLocation.CURL_NO_CONTENT).succeeded


@pytest.mark.parametrize("exit_status", [None, 7])
def test_a_call_that_got_no_answer_reads_as_failed(exit_status: int | None):
    """
    ``curl`` not installed, or no connection: there is no status to read.
    """
    response = RestResponse.from_command(
        CommandResult(("curl",), exit_status, "", "no connection", 0.0)
    )

    assert response.status == 0
