"""
A property that answers on the class rather than on an instance.
"""

from __future__ import annotations

from typing import Any, Callable


class classproperty:
    """
    Reads a value off the class itself, and stays abstract until one is supplied.

    An abstract accessor answers with the descriptor instead of calling it, so
    :class:`abc.ABCMeta` still sees it as abstract on a subclass that supplied nothing.
    """

    def __init__(self, accessor: Callable[[type], Any]) -> None:
        """:param accessor: The function answering the value, given the owning class."""
        self.accessor = accessor
        self.__isabstractmethod__ = getattr(accessor, "__isabstractmethod__", False)
        self.__doc__ = accessor.__doc__

    def __get__(self, instance: Any, owner: type | None = None) -> Any:
        """:param instance: The instance read through, absent on class access.
        :param owner: The class read from.
        :return: The value for the owning class, or this descriptor while it is
            abstract."""
        if self.__isabstractmethod__:
            return self
        return self.accessor(owner if owner is not None else type(instance))
