"""
Tests for :mod:`basstler_domain_model.class_property`.
"""

from __future__ import annotations

import inspect
from abc import ABC, abstractmethod

import pytest

from basstler_domain_model.class_property import classproperty


class Kind(ABC):
    """
    A base whose value each subclass names.
    """

    @classproperty
    @abstractmethod
    def value(cls) -> int:
        """
        :return: The value this kind carries.
        """


class OneKind(Kind):
    """
    A subclass naming its value.
    """

    @classproperty
    def value(cls) -> int:
        """
        :return: The value this kind carries.
        """
        return 1


def test_the_value_is_read_from_the_class_itself():
    assert OneKind.value == 1


def test_an_instance_reads_the_same_value_as_its_class():
    assert OneKind().value == OneKind.value


def test_a_class_that_names_no_value_stays_abstract():
    assert inspect.isabstract(Kind)
    assert not inspect.isabstract(OneKind)
    with pytest.raises(TypeError):
        Kind()
