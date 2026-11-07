"""
Reading what reported against one commit: its check runs and its commit statuses.
"""

from __future__ import annotations

from dataclasses import dataclass

from basstler_domain_model.github.clients import RestClient
from basstler_domain_model.github.pull_request_models import CheckStatus
from basstler_domain_model.github.rest_models import (
    RestCheckRunPage,
    RestCombinedStatusPage,
)
from basstler_domain_model.github.routes import RepositoryRoute

# %% the reading


@dataclass(frozen=True)
class CommitCheckReader:
    """
    Reads the checks on commits of one repository, which REST reports in two listings.
    """

    client: RestClient
    """
    Reads the listings.
    """

    route: RepositoryRoute
    """
    The paths of the repository the commits are in.
    """

    def checks(self, sha: str) -> CheckStatus | None:
        """
        :param sha: The commit.
        :return: Its checks, ``None`` when nothing has reported.
        """
        runs = [
            run
            for page in self.client.get_pages(self.route.check_runs(sha))
            for run in RestCheckRunPage.from_json(page).check_runs
        ]
        statuses = [
            status
            for page in self.client.get_pages(self.route.commit_status(sha))
            for status in RestCombinedStatusPage.from_json(page).statuses
        ]
        return CheckStatus.over(runs + statuses)
