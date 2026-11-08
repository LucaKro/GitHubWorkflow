"""
Templates a caller fills in: the names they leave to be filled in, and filling them.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from enum import StrEnum

# %% placeholders


class Placeholder(StrEnum):
    """
    The base of an enumeration of the names a template leaves to be filled in, each
    written as __<NAME>__; a template may hold the members of several.
    """

    @staticmethod
    def _generate_next_value_(
        name: str, start: int, count: int, last_values: list[str]
    ) -> str:
        """
        :param name: The member's name.
        :param start: Unused by string values.
        :param count: Unused by string values.
        :param last_values: Unused by string values.
        :return: The placeholder as a template writes it.
        """
        return f"__{name}__"

    @classmethod
    def fill(cls, template: str, values: Mapping[Placeholder, str]) -> str:
        """
        :param template: A template's text.
        :param values: The text of each placeholder it holds.
        :return: The template with every placeholder given replaced in one pass, so a
            value holding a placeholder's name is kept as it is.
        """
        if not values:
            return template
        texts = {str(placeholder): text for placeholder, text in values.items()}
        return re.sub(
            "|".join(map(re.escape, texts)),
            lambda found: texts[found.group()],
            template,
        )
