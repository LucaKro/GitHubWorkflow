"""
The notes branch: the domain model's storage branch, on the owner's remote, under the
name the settings give it.
"""

from __future__ import annotations

from dataclasses import dataclass

from basstler_domain_model.git.commands import GitCommandRunner, RemoteBranch
from basstler_domain_model.git.storage_branch import StorageBranch

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
    def on(
        cls, git: GitCommandRunner, remote: OwnedRemote, settings: WorkflowSettings
    ) -> NotesBranch:
        """
        :param git: Runs git in the checkout.
        :param remote: The owner's remote the branch lives on.
        :param settings: The branch's name.
        :return: The notes branch.
        """
        return cls(git, RemoteBranch(remote.name, settings.notes_branch))
