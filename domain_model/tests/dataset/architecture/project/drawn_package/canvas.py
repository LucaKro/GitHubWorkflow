"""
A canvas holding shapes.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from drawn_package.shapes import Shape

if TYPE_CHECKING:
    from drawn_package.rendering import pens, strokes

# %% the canvas


@dataclass
class Canvas:
    """
    Shapes drawn with a pen.
    """

    shapes: list[Shape]
    """
    What it shows.
    """

    pen: pens.Pen | None
    """
    What draws it.
    """

    latest_stroke: strokes.Point | None
    """
    The stroke drawn last.
    """
