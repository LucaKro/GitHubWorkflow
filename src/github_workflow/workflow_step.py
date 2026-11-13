"""
What every write a session asks the workflow for has in common: it runs as one step that
reports in one line, and what it does without asking is entered in one log.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

# %% one step


class WorkflowStep(ABC):
    """
    One write a session asks the workflow for.
    """

    @abstractmethod
    def run(self) -> str:
        """
        Make the write.

        :return: What was done, in one line.
        """


# %% what a session did


class SessionLog(ABC):
    """
    Where what a session does without asking is entered, for the person to read in one
    place.
    """

    @abstractmethod
    def enter(self, action: str) -> None:
        """
        :param action: What the session did, in one line, naming the issues, pull
            requests and branches it touched.
        """
