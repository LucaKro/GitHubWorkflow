"""
A person as git records them: a commit's author or committer, or a trailer's co-author.
"""

from __future__ import annotations

from dataclasses import dataclass

# %% a person


@dataclass(frozen=True)
class PersonIdentity:
    """
    A person, as git writes them: ``Name <address>``.
    """

    name: str
    """
    Their name.
    """

    address: str
    """
    Their e-mail address, empty when none is written.
    """

    @classmethod
    def parse(cls, text: str) -> PersonIdentity:
        """
        :param text: ``Name <address>``, with anything after it, such as the time
            ``git var`` adds.
        :return: The person it names.
        """
        name, _, rest = text.partition("<")
        return cls(name.strip(), rest.partition(">")[0])

    @property
    def domain(self) -> str:
        """:return: The domain the address is at, in lower case."""
        return self.address.rpartition("@")[2].casefold()
