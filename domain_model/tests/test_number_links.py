"""
Tests for :mod:`domain_model.github.number_links`.
"""

from __future__ import annotations

from domain_model.github.number_links import NumberLink

# %% the link


def test_a_number_link_shows_the_number_and_links_its_page() -> None:
    url = "https://github.com/owner/project/pull/7"

    assert NumberLink(7, url).markdown() == f"[#7]({url})"
