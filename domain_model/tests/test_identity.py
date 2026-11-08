"""
Tests for :mod:`basstler_domain_model.git.identity`: a person read from how git writes
them.
"""

from __future__ import annotations

from basstler_domain_model.git.identity import PersonIdentity

# %% reading a person


def test_a_person_is_read_from_what_git_var_prints() -> None:
    assert PersonIdentity.parse("Ada Lovelace <ada@Example.org> 1700000000 +0100") == (
        PersonIdentity("Ada Lovelace", "ada@Example.org")
    )


def test_the_domain_is_the_part_of_the_address_after_its_last_at() -> None:
    assert PersonIdentity("Ada", "ada@mail.Example.org").domain == "mail.example.org"


def test_a_person_written_without_an_address_has_none() -> None:
    assert PersonIdentity.parse("Ada") == PersonIdentity("Ada", "")
