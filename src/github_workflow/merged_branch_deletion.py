"""
Have GitHub delete a pull request's branch once it is merged, on the owner's repository:
turned on where it is off, and where this session may not change settings, one line
saying where to turn it on.

Usage: ``python -m github_workflow.merged_branch_deletion``; prints one report line as
JSON, or nothing when GitHub already deletes merged branches.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from basstler_domain_model.github.repository_client import (
    GitHubRepository,
    RepositorySettings,
)
from basstler_domain_model.repository import Repository

from github_workflow.checkout import ProjectCheckout
from github_workflow.hooks import ReportLine, Tone
from github_workflow.remotes import OwnedRemotes
from github_workflow.settings import WorkflowSettings

# %% the setting


@dataclass(frozen=True)
class MergedBranchDeletion:
    """
    GitHub's deletion of merged branches on one repository, made sure of.
    """

    repository: Repository
    """
    The repository.
    """

    settings: RepositorySettings
    """
    Reads and changes its settings.
    """

    def ensure(self) -> ReportLine | None:
        """
        Turn the deletion on where it is off.

        :return: What was done, or where to do it by hand, in one line; ``None`` when it
            was on already.
        """
        if self.settings.deletes_merged_branches():
            return None
        if self.settings.turn_on_merged_branch_deletion():
            return ReportLine(
                f"github-workflow: turned on GitHub's deletion of merged branches "
                f"for {self.repository}",
                Tone.NEWS,
            )
        return ReportLine(
            f"github-workflow: GitHub keeps the merged branches of {self.repository}, "
            f'and this session may not change that: turn on "Automatically delete '
            f'head branches" at {self.repository.settings_url}',
            Tone.ACTION,
        )


# %% entry point


def main() -> None:
    """
    Make sure of the deletion on the owner's repository the checkout pushes to.
    """
    checkout = ProjectCheckout.containing(Path.cwd())
    repository = OwnedRemotes.read(checkout.git, WorkflowSettings()).chosen.repository
    done = MergedBranchDeletion(
        repository, GitHubRepository.from_environment(repository)
    ).ensure()
    if done is not None:
        print(done.json())


if __name__ == "__main__":
    main()
