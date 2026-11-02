"""
Publish a directory of results to the probe results branch, outside every code branch,
so they can be read from elsewhere and the branch deleted once they have been.

Usage: ``python -m github_workflow.probe.publish <directory>``; publishes every file
directly in it under ``<directory name>/`` on the branch.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

from basstler_domain_model.git.commands import (
    GitCommandRunner,
    RemoteBranch,
    RemoteName,
)
from basstler_domain_model.git.storage_branch import StorageBranch

# %% where results go


class ResultsBranch(StrEnum):
    """
    The branch results are published to, outside every code branch, and deleted once
    they have been read.
    """

    NAME = "github-workflow/probe-results"
    """
    The branch on the remote.
    """


@dataclass(frozen=True)
class ResultsPublication:
    """
    One directory of results, published to the results branch of the checkout's origin.
    """

    git: GitCommandRunner
    """
    Runs git in the checkout.
    """

    directory: Path
    """
    The directory whose files are published, under its own name.
    """

    def publish(self) -> str:
        """
        :return: Where the results were published, in one line.
        """
        results = StorageBranch(
            self.git, RemoteBranch(RemoteName.ORIGIN, ResultsBranch.NAME)
        )
        results.fetch()
        results.write(
            {
                Path(self.directory.name) / file.name: file.read_text()
                for file in sorted(self.directory.iterdir())
                if file.is_file()
            },
            f"Record results {self.directory.name}",
        )
        return f"published to {ResultsBranch.NAME}: {self.directory.name}/"


# %% entry point


def main() -> None:
    """
    Publish the directory the command line names.
    """
    print(ResultsPublication(GitCommandRunner(Path.cwd()), Path(sys.argv[1])).publish())


if __name__ == "__main__":
    main()
