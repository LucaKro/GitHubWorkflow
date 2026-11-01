"""
The files the tests read their recorded command output from, each named once.
"""

from __future__ import annotations

from pathlib import Path

from basstler_domain_model.locations import PathEnumeration


class DatasetLocation(PathEnumeration):
    """
    What ``curl`` printed for the calls the tests replay: the body, then the status.
    """

    DIRECTORY = Path(__file__).parent
    """
    The directory holding every recording.
    """

    CURL_REFUSED = DIRECTORY / "curl-refused.txt"
    """
    A refusal, carrying the API's own message.
    """

    CURL_LISTING = DIRECTORY / "curl-listing.txt"
    """
    A listing of two entries.
    """

    CURL_NO_CONTENT = DIRECTORY / "curl-no-content.txt"
    """
    A success with no body, as a deletion answers.
    """
