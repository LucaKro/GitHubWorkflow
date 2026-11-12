"""
A base class whose concrete subclasses, at any depth, are the members of its family.
"""

from __future__ import annotations

from inspect import isabstract
from typing import Self

# %% the family


class ClassFamily:
    """
    A base class whose members are its concrete subclasses, however deep, so one is
    found by what it declares.
    """

    @classmethod
    def concrete_subclasses(cls) -> list[type[Self]]:
        """
        :return: Every subclass that can be instantiated, nearer ones first.
        """
        found = [cls]
        for family in found:
            found += family.__subclasses__()
        return [member for member in found[1:] if not isabstract(member)]
