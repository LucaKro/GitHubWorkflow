"""
The notes branch: the domain model's storage branch, on the owner's remote, under the
name the settings give it.
"""

from __future__ import annotations

import time
from dataclasses import dataclass

from domain_model.git.storage_branch import StorageBranch

from github_workflow.remotes import OwnedRemote
from github_workflow.settings import WorkflowSettings

# %% the branch


@dataclass(frozen=True)
class NotesBranch(StorageBranch):
    """
    The branch the notes and progress are kept on, read and written without touching the
    checkout.
    """

    @classmethod
    def from_settings(
        cls, remote: OwnedRemote, settings: WorkflowSettings
    ) -> NotesBranch:
        """
        :param remote: The owner's remote the branch lives on.
        :param settings: The branch's name.
        :return: The notes branch.
        """
        return cls(remote.branch(settings.notes_branch))

    @staticmethod
    def queued_file_name() -> str:
        """
        :return: A name for one file queued on the branch, sorting after the name of
            every file queued before it.
        """
        return f"{time.time_ns()}.json"
