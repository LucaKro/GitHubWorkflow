"""
Shapes, the colours they are drawn in, and the error drawing one ends in.
"""

from __future__ import annotations

from abc import ABC
from dataclasses import dataclass
from enum import StrEnum

# %% shapes


class Colour(StrEnum):
    """
    A colour a shape is drawn in, left out of class diagrams as an enumeration.
    """

    RED = "red"
    """
    Red.
    """


class ShapeTooSmallError(ValueError):
    """
    An error, left out of class diagrams.
    """


@dataclass
class Point:
    """
    A point in the plane.
    """

    x: float
    """
    Its horizontal position.
    """


@dataclass
class Shape(ABC):
    """
    A shape, filled with a colour.
    """

    fill: Colour
    """
    The colour inside it.
    """


@dataclass
class Circle(Shape):
    """
    A shape around a point.
    """

    centre: Point
    """
    The point it lies around.
    """
