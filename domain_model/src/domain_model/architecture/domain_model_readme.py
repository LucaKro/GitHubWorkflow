"""
The domain model's own README and the diagrams of its architecture it holds.
"""

from __future__ import annotations

from enum import StrEnum
from pathlib import Path

from domain_model import git, github
from domain_model.architecture.diagrams import (
    ClassDiagram,
    Diagram,
    ImportDiagram,
    ModuleGroup,
)
from domain_model.architecture.readme import ArchitectureReadme
from domain_model.architecture.source import PythonPackage
from domain_model.github import (
    answer_recording,
    clients,
    closing_lines,
    commit_checks,
    credential,
    discussions,
    labels,
    number_links,
    pull_request_models,
    readers,
    reading_calls,
    replayed_api,
    repository_client,
    review_models,
    review_writers,
    routes,
    stack_placement,
)
from domain_model.github.vocabulary import JSONModel
from domain_model.locations import PackageLocation

# %% the diagrams


class DomainModelDiagram(StrEnum):
    """
    The diagrams of the domain model's README, by the key marking each.
    """

    OVERVIEW = "overview"
    """
    The subpackages and top-level modules, and which imports which.
    """

    GIT_MODULES = "git modules"
    """
    The modules of :mod:`domain_model.git`, and which imports which.
    """

    GITHUB_MODULES = "github modules"
    """
    The modules of :mod:`domain_model.github`, and which imports which.
    """

    GIT_CLASSES = "git classes"
    """
    The classes of :mod:`domain_model.git`.
    """

    GITHUB_CLIENT_CLASSES = "github client classes"
    """
    The classes calling GitHub's APIs, recording and replaying their answers.
    """

    GITHUB_READER_CLASSES = "github reader classes"
    """
    The classes reading and writing pull requests, reviews, checks and labels.
    """

    GITHUB_REPOSITORY_CLASSES = "github repository classes"
    """
    The classes of :mod:`domain_model.github.repository_client`.
    """


# %% the README


class DomainModelReadme(ArchitectureReadme):
    """
    The domain model's README.
    """

    @property
    def path(self) -> Path:
        return PackageLocation.README

    @property
    def package(self) -> PythonPackage:
        return PythonPackage(directory=PackageLocation.DIRECTORY)

    @property
    def left_out_bases(self) -> tuple[type, ...]:
        """
        :return: What :meth:`ArchitectureReadme.left_out_bases` leaves out, and JSON
            models.
        """
        return *super().left_out_bases, JSONModel

    @property
    def diagrams(self) -> list[Diagram]:
        class_groups = {
            DomainModelDiagram.GIT_CLASSES: [git],
            DomainModelDiagram.GITHUB_CLIENT_CLASSES: [
                answer_recording,
                clients,
                credential,
                reading_calls,
                replayed_api,
                routes,
            ],
            DomainModelDiagram.GITHUB_READER_CLASSES: [
                closing_lines,
                commit_checks,
                discussions,
                labels,
                number_links,
                pull_request_models,
                readers,
                review_models,
                review_writers,
                stack_placement,
            ],
            DomainModelDiagram.GITHUB_REPOSITORY_CLASSES: [repository_client],
        }
        return [
            ImportDiagram(
                key=DomainModelDiagram.OVERVIEW, package_name=self.package.name
            ),
            ImportDiagram(
                key=DomainModelDiagram.GIT_MODULES, package_name=git.__name__
            ),
            ImportDiagram(
                key=DomainModelDiagram.GITHUB_MODULES, package_name=github.__name__
            ),
            *(
                ClassDiagram(
                    key=key,
                    modules=ModuleGroup.from_modules(title=key, modules=modules),
                    left_out_bases=self.left_out_bases,
                )
                for key, modules in class_groups.items()
            ),
        ]
