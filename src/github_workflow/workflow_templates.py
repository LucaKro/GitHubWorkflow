"""
The templates the workflow fills in, and the Actions workflows the notes branch carries
together with the files each runs.
"""

from __future__ import annotations

import shlex
from collections.abc import Mapping
from dataclasses import dataclass
from enum import Enum, StrEnum, auto
from pathlib import PurePath

from domain_model.git.revisions import BranchName, TextFiles
from domain_model.repository import Repository
from domain_model.templates import Placeholder

from github_workflow.command_line import RunnableCommand
from github_workflow.locations import NotesFile, WorkflowTemplate
from github_workflow.plugin import Distribution, PluginSource, ToolRepository

# %% the names the templates leave to be filled in


class NotesBranchPlaceholder(Placeholder):
    """
    The names every workflow on the notes branch leaves to be filled in.
    """

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


class DeletionPlaceholder(Placeholder):
    """
    The names the deletion workflow leaves to be filled in, besides the notes branch's.
    """

    LIST_FILE = auto()
    """
    The file listing the branches to delete.
    """


class PostingPlaceholder(Placeholder):
    """
    The names the posting workflow leaves to be filled in, besides the notes branch's.
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


class ForwardedReadPlaceholder(Placeholder):
    """
    The names a workflow answering read requests leaves to be filled in, besides the
    notes branch's.
    """

    SUBJECT = auto()
    """
    What the requests ask to be read, in a few words.
    """

    REQUESTS_DIRECTORY = auto()
    """
    The directory holding the requests.
    """

    ANSWERS_DIRECTORY = auto()
    """
    The directory the answers to them are saved in.
    """


class ActionPlaceholder(Placeholder):
    """
    The names every Actions workflow running the workflow's code leaves to be filled in.
    """

    REQUIREMENTS = auto()
    """
    What ``pip`` installs to run the workflow on an Actions runner.
    """

    ENTRY_POINT = auto()
    """
    The command an Actions workflow runs, before its own arguments.
    """


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
    def placeholder_values(cls, module: str) -> dict[Placeholder, str]:
        """
        :param module: The module the workflow runs.
        :return: What an Actions workflow running it installs, and the command it runs.
        """
        return {
            ActionPlaceholder.REQUIREMENTS: shlex.join(list(cls)),
            ActionPlaceholder.ENTRY_POINT: f"python -m {module}",
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

    placeholder: Placeholder
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
                NotesBranchPlaceholder.SCRIPT_FILE,
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
                NotesBranchPlaceholder.SCRIPT_FILE,
            ),
            CarriedFile(
                WorkflowTemplate.CATEGORIES_QUERY,
                NotesFile.CATEGORIES_QUERY,
                PostingPlaceholder.CATEGORIES_QUERY,
            ),
            CarriedFile(
                WorkflowTemplate.CREATE_QUERY,
                NotesFile.CREATE_QUERY,
                PostingPlaceholder.CREATE_QUERY,
            ),
            CarriedFile(
                WorkflowTemplate.FIND_QUERY,
                NotesFile.FIND_QUERY,
                PostingPlaceholder.FIND_QUERY,
            ),
            CarriedFile(
                WorkflowTemplate.COMMENT_QUERY,
                NotesFile.COMMENT_QUERY,
                PostingPlaceholder.COMMENT_QUERY,
            ),
        ),
    )
    """
    Posts the discussions queued.
    """

    UPSTREAM_REVIEWS = (
        WorkflowTemplate.FORWARDED_READ_WORKFLOW,
        NotesFile.UPSTREAM_REVIEW_WORKFLOW,
        (),
    )
    """
    Reads the reviews of the pull requests opened upstream that are asked for.
    """

    TAGGED_COMMENTS = (
        WorkflowTemplate.FORWARDED_READ_WORKFLOW,
        NotesFile.TAG_WORKFLOW,
        (),
    )
    """
    Reads the comments the person tagged by mentioning themselves.
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
                NotesBranchPlaceholder.COMMIT_SCRIPT,
            ),
        )

    def files(
        self, notes_branch: BranchName, values: Mapping[Placeholder, str]
    ) -> TextFiles:
        """
        :param notes_branch: The notes branch's name.
        :param values: The text of the workflow's other placeholders.
        :return: The workflow, filled in, and the files it runs, by where the notes
            branch keeps each.
        """
        filled = {
            NotesBranchPlaceholder.NOTES_BRANCH: notes_branch,
            **{
                companion.placeholder: str(companion.destination)
                for companion in self.companions
            },
            **values,
        }
        return TextFiles(
            {
                self.destination: Placeholder.fill(self.template.read_text(), filled),
                **{
                    companion.destination: companion.template.read_text()
                    for companion in self.companions
                },
            }
        )


# %% what a session has the notes branch's workflows read


class ForwardedSubject(Enum):
    """
    What a session has the repository's Actions read for it, through requests queued on
    the notes branch, each with where its requests and answers are kept.
    """

    UPSTREAM_REVIEWS = (
        "upstream reviews",
        NotesFile.UPSTREAM_REVIEW_REQUESTS,
        NotesFile.UPSTREAM_REVIEW_ANSWERS,
        NotesBranchWorkflow.UPSTREAM_REVIEWS,
        RunnableCommand.REVIEW_LIST,
    )
    """
    The reviews of the pull request a fork's branch has open upstream.
    """

    TAGGED_COMMENTS = (
        "tagged comments",
        NotesFile.TAG_REQUESTS,
        NotesFile.TAG_ANSWERS,
        NotesBranchWorkflow.TAGGED_COMMENTS,
        RunnableCommand.TAG_LIST,
    )
    """
    The comments the person tagged by mentioning themselves, anywhere on GitHub.
    """

    def __init__(
        self,
        described: str,
        requests: NotesFile,
        answers: NotesFile,
        workflow: NotesBranchWorkflow,
        reading_command: RunnableCommand,
    ) -> None:
        """
        :param described: What is read, in a few words.
        :param requests: The directory on the notes branch holding the requests.
        :param answers: The directory on the notes branch holding the answers.
        :param workflow: The workflow answering the requests.
        :param reading_command: The command reading it again.
        """
        self.described = described
        self.requests = requests
        self.answers = answers
        self.workflow = workflow
        self.reading_command = reading_command

    def workflow_files(self, notes_branch: BranchName, module: str) -> TextFiles:
        """
        :param notes_branch: The notes branch's name.
        :param module: The module answering the requests on the runner.
        :return: The workflow answering the requests, filled in, with the files it runs.
        """
        return self.workflow.files(
            notes_branch,
            {
                ForwardedReadPlaceholder.SUBJECT: self.described,
                ForwardedReadPlaceholder.REQUESTS_DIRECTORY: str(self.requests),
                ForwardedReadPlaceholder.ANSWERS_DIRECTORY: str(self.answers),
                **ActionRequirement.placeholder_values(module),
            },
        )
