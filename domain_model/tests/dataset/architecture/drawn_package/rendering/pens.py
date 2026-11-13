"""
The pens drawing shapes.
"""

from __future__ import annotations

from dataclasses import dataclass

from ..shapes import Point

# %% pens


@dataclass
class Pen:
    """
    A pen resting on a point.
    """

    tip: Point
    """
    Where it rests.
    """
