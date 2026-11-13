"""
Strokes a pen draws, sharing a class name with the shapes.
"""

from __future__ import annotations

from drawn_package.rendering.pens import Pen

# %% strokes


class Point(Pen):
    """
    A stroke of a single point, named like :class:`drawn_package.shapes.Point`.
    """
