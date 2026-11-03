"""
The repository features the workflow relies on: GitHub deleting merged branches and
issues, turned on where they are off, and where this session may not change settings,
one line saying where to turn them on; and Actions, which only the person turns on.
"""

from __future__ import annotations

from dataclasses import dataclass

from basstler_domain_model.github.repository_client import RepositorySettings
from basstler_domain_model.repository import Repository

from github_workflow.hooks import ReportLine, Tone
from github_workflow.report_section import ReportSection

# %% the features


@dataclass(frozen=True)
class RepositorySetup(ReportSection):
    """
    Merged-branch deletion and issues on one repository made sure of, and Actions
    reported when they are off.
    """

    repository: Repository
    """
    The repository.
    """

    settings: RepositorySettings
    """
    Reads and changes its settings.
    """

    def lines(self) -> list[ReportLine]:
        lines = []
        if not self.settings.deletes_merged_branches():
            lines.append(
                self._turned_on(
                    self.settings.turn_on_merged_branch_deletion(),
                    "GitHub's deletion of merged branches",
                    '"Automatically delete head branches"',
                    self.repository.settings_url,
                )
            )
        if not self.settings.issues_enabled():
            lines.append(
                self._turned_on(
                    self.settings.turn_on_issues(),
                    "issues",
                    '"Issues"',
                    self.repository.settings_url,
                )
            )
        if self.settings.actions_enabled() is False:
            lines.append(
                ReportLine(
                    f"github-workflow: {self.repository} has GitHub Actions turned "
                    f"off, so the workflows the notes branch carries do not run. "
                    f"Turned on, Actions run every workflow on the repository, an "
                    f"upstream's on a fork among them, under your account: ask the "
                    f"person whether to turn them on at "
                    f"{self.repository.settings_url}/actions",
                    Tone.ACTION,
                )
            )
        return lines

    def _turned_on(
        self, accepted: bool, feature: str, setting: str, page: str
    ) -> ReportLine:
        """
        :param accepted: Whether GitHub accepted turning the feature on.
        :param feature: The feature, as the line names it.
        :param setting: The setting that turns it on, as GitHub's page names it.
        :param page: The page the setting is on.
        :return: That it was turned on, or where to turn it on by hand.
        """
        if accepted:
            return ReportLine(
                f"github-workflow: turned on {feature} for {self.repository}",
                Tone.NEWS,
            )
        return ReportLine(
            f"github-workflow: {self.repository} has {feature} turned off, and this "
            f"session may not change that: turn on {setting} at {page}",
            Tone.ACTION,
        )
