"""
The templates the workflow fills in, and the Actions workflows the notes branch carries
together with the files each runs.
"""

from __future__ import annotations

import re
import shlex
from collections.abc import Mapping
from dataclasses import dataclass
from enum import Enum, StrEnum, auto
from pathlib import Path, PurePath

from basstler_domain_model.repository import Repository

from github_workflow.install import Distribution, PluginSource, ToolRepository
from github_workflow.locations import NotesFile, WorkflowTemplate

# %% filling a template in


class TemplatePlaceholder(StrEnum):
    """
    The names the package's templates leave to be filled in, each written as
    ``__<NAME>__``.
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

    NOTES_BRANCH = auto()
    """
    The notes branch, whose pushes run its workflows.
    """

    COMMIT_SCRIPT = auto()
    """
    The script the notes branch's workflows commit and push with.
    """

    SCRIPT_FILE = auto()
    """
    The script a workflow runs.
    """

    LIST_FILE = auto()
    """
    The file listing the branches to delete.
    """

    POSTS_DIRECTORY = auto()
    """
    The directory holding the discussions to post.
    """

    CATEGORIES_QUERY = auto()
    """
    The query reading the repository's discussion categories.
    """

    CREATE_QUERY = auto()
    """
    The mutation creating a discussion.
    """

    FIND_QUERY = auto()
    """
    The query finding the discussion a comment goes on.
    """

    COMMENT_QUERY = auto()
    """
    The mutation commenting on a discussion.
    """

    REQUESTS_DIRECTORY = auto()
    """
    The directory holding the requests for upstream reviews.
    """

    ANSWERS_DIRECTORY = auto()
    """
    The directory the answers to them are saved in.
    """

    REQUIREMENTS = auto()
    """
    What ``pip`` installs to run the workflow on an Actions runner.
    """

    ENTRY_POINT = auto()
    """
    The command an Actions workflow runs, before its own arguments.
    """

    MARKER_VARIABLE = auto()
    """
    The variable set only in commands a Claude Code session runs.
    """

    PYTHON = auto()
    """
    The interpreter the package is installed in.
    """

    MODULE = auto()
    """
    The module a hook runs.
    """

    RECORD = auto()
    """
    A proof as the record its comment carries, between its markers.
    """

    BRANCH = auto()
    """
    The branch a finding's test failed on.
    """

    COMMIT = auto()
    """
    The commit it failed on.
    """

    FAILURE = auto()
    """
    pytest's message on the failure.
    """

    PATH = auto()
    """
    The test's path in the repository.
    """

    FENCE = auto()
    """
    The backticks fencing the test's text, more than any run of them inside it.
    """

    SOURCE = auto()
    """
    The test's text.
    """

    WORKFLOW_BRANCH = auto()
    """
    The branch carrying the probe's workflow, which triggers it and is deleted last.
    """

    DELETED_BRANCH = auto()
    """
    The other branch the probe's workflow deletes.
    """

    SAVE_COMMAND = auto()
    """
    The command saving the notes block.
    """

    SOURCE_OF_NOTES = auto()
    """
    Where the notes were read from.
    """

    WORKFLOW_COMMAND = auto()
    """
    The command every write to git and GitHub goes through.
    """

    COMMANDS = auto()
    """
    The workflow's commands, listed.
    """

    FINDING_GUIDE = auto()
    """
    What each finding priority means.
    """

    IDEAS_CATEGORY = auto()
    """
    The discussion category ideas are posted in unless told otherwise.
    """

    REFUSAL_HINT = auto()
    """
    What a session does about a refusal.
    """

    CO_AUTHOR_TRAILER = auto()
    """
    The trailer crediting a co-author.
    """

    ACKNOWLEDGEMENT = auto()
    """
    The line every commit's message carries.
    """

    @classmethod
    def fill(cls, template: str, values: Mapping[TemplatePlaceholder, str]) -> str:
        """
        :param template: A template's text.
        :param values: The text of each placeholder it holds.
        :return: The template with every placeholder given replaced in one pass, so a
            value holding a placeholder's name is kept as it is.
        """
        if not values:
            return template
        return re.sub(
            "|".join(map(re.escape, values)),
            lambda found: values[cls(found.group())],
            template,
        )


# %% running the workflow on an Actions runner


class ActionRequirement(StrEnum):
    """
    What an Actions workflow installs to run the workflow's code.
    """

    DOMAIN_MODEL = Repository.parse(ToolRepository.WORKFLOW).git_requirement(
        Distribution.DOMAIN_MODEL,
        "main",
        str(PurePath(PluginSource.DOMAIN_MODEL.path).parent),
    )
    """
    The model of git and GitHub, which no index serves, from the workflow's default
    branch.
    """

    WORKFLOW = Repository.parse(ToolRepository.WORKFLOW).git_requirement(
        Distribution.WORKFLOW, "main"
    )
    """
    This package, from its default branch.
    """

    @classmethod
    def placeholder_values(cls, module: str) -> dict[TemplatePlaceholder, str]:
        """
        :param module: The module the workflow runs.
        :return: What an Actions workflow running it installs, and the command it runs.
        """
        return {
            TemplatePlaceholder.REQUIREMENTS: shlex.join(list(cls)),
            TemplatePlaceholder.ENTRY_POINT: f"python -m {module}",
        }


# %% the notes branch's workflows


@dataclass(frozen=True)
class CarriedFile:
    """
    A file a workflow on the notes branch runs, copied there from the package.
    """

    template: WorkflowTemplate
    """
    The file, as shipped in the package.
    """

    destination: NotesFile
    """
    Where the notes branch keeps it.
    """

    placeholder: TemplatePlaceholder
    """
    How the workflow names it.
    """


class NotesBranchWorkflow(Enum):
    """
    The Actions workflows the notes branch carries, each with the files it runs.
    """

    DELETION = (
        WorkflowTemplate.DELETION_WORKFLOW,
        NotesFile.DELETION_WORKFLOW,
        (
            CarriedFile(
                WorkflowTemplate.DELETION_SCRIPT,
                NotesFile.DELETION_SCRIPT,
                TemplatePlaceholder.SCRIPT_FILE,
            ),
        ),
    )
    """
    Deletes the branches listed for deletion.
    """

    POSTING = (
        WorkflowTemplate.POSTING_WORKFLOW,
        NotesFile.POSTING_WORKFLOW,
        (
            CarriedFile(
                WorkflowTemplate.POSTING_SCRIPT,
                NotesFile.POSTING_SCRIPT,
                TemplatePlaceholder.SCRIPT_FILE,
            ),
            CarriedFile(
                WorkflowTemplate.CATEGORIES_QUERY,
                NotesFile.CATEGORIES_QUERY,
                TemplatePlaceholder.CATEGORIES_QUERY,
            ),
            CarriedFile(
                WorkflowTemplate.CREATE_QUERY,
                NotesFile.CREATE_QUERY,
                TemplatePlaceholder.CREATE_QUERY,
            ),
            CarriedFile(
                WorkflowTemplate.FIND_QUERY,
                NotesFile.FIND_QUERY,
                TemplatePlaceholder.FIND_QUERY,
            ),
            CarriedFile(
                WorkflowTemplate.COMMENT_QUERY,
                NotesFile.COMMENT_QUERY,
                TemplatePlaceholder.COMMENT_QUERY,
            ),
        ),
    )
    """
    Posts the discussions queued.
    """

    UPSTREAM_REVIEWS = (
        WorkflowTemplate.UPSTREAM_REVIEW_WORKFLOW,
        NotesFile.UPSTREAM_REVIEW_WORKFLOW,
        (),
    )
    """
    Reads the reviews of the pull requests opened upstream that are asked for.
    """

    def __init__(
        self,
        template: WorkflowTemplate,
        destination: NotesFile,
        companions: tuple[CarriedFile, ...],
    ) -> None:
        """
        :param template: The workflow, as shipped in the package.
        :param destination: Where the notes branch keeps it.
        :param companions: The files it runs besides the commit script.
        """
        self.template = template
        self.destination = destination
        self.companions = (
            *companions,
            CarriedFile(
                WorkflowTemplate.COMMIT_SCRIPT,
                NotesFile.COMMIT_SCRIPT,
                TemplatePlaceholder.COMMIT_SCRIPT,
            ),
        )

    def files(
        self, notes_branch: str, values: Mapping[TemplatePlaceholder, str]
    ) -> dict[Path, str]:
        """
        :param notes_branch: The notes branch's name.
        :param values: The text of the workflow's other placeholders.
        :return: The workflow, filled in, and the files it runs, by where the notes
            branch keeps each.
        """
        filled = {
            TemplatePlaceholder.NOTES_BRANCH: notes_branch,
            **{
                companion.placeholder: str(companion.destination)
                for companion in self.companions
            },
            **values,
        }
        return {
            self.destination.value: TemplatePlaceholder.fill(
                self.template.read_text(), filled
            ),
            **{
                companion.destination.value: companion.template.read_text()
                for companion in self.companions
            },
        }
