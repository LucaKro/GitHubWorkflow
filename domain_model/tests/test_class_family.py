"""
Tests for :mod:`domain_model.class_family`: a family's members are its concrete
subclasses at any depth.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from domain_model.class_family import ClassFamily

# %% a family with an abstract branch


class Shape(ClassFamily, ABC):
    """
    The family's abstract root.
    """

    @abstractmethod
    def corners(self) -> int:
        """:return: How many corners the shape has."""


class Square(Shape):
    """
    A member directly below the root.
    """

    def corners(self) -> int:
        return 4


class RoundShape(Shape, ABC):
    """
    An abstract branch, which is no member.
    """


class Circle(RoundShape):
    """
    A member below the abstract branch.
    """

    def corners(self) -> int:
        return 0


class Disc(Circle):
    """
    A member below another member.
    """


# %% listing the members


def test_a_family_lists_its_concrete_subclasses_at_any_depth_nearer_first() -> None:
    assert Shape.concrete_subclasses() == [Square, Circle, Disc]


def test_a_member_s_family_holds_only_the_members_below_it() -> None:
    assert Circle.concrete_subclasses() == [Disc]
