"""
The commands ``python -m github_workflow`` takes, the only way the workflow's agent
writes to git and GitHub: each command's words, who may run it, and the arguments it
takes, from which its parser and every line naming it are built.

Runs on the standard library alone, like :mod:`github_workflow.guard`, which reads it.
"""

from __future__ import annotations

import argparse
import shutil
import sys
from abc import ABC, abstractmethod
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from enum import Enum, StrEnum
from pathlib import Path
from typing import Any

from domain_model.class_property import classproperty
from domain_model.git.revisions import BranchName

import github_workflow
from github_workflow.plugin import Launcher, LauncherInstallation, ToolRepository

# %% the words


class WorkflowCommand(StrEnum):
    """
    The commands ``python -m github_workflow`` takes, each with its subcommands, if any,
    in :class:`RunnableCommand`.
    """

    BRANCH = "branch"
    """
    Start a work branch, switch to one, or discard one.
    """

    COMMIT = "commit"
    """
    Commit named files on the work branch.
    """

    PUSH = "push"
    """
    Push the work branch to the owner's remote.
    """

    DRAFT = "draft"
    """
    Open a draft pull request for the work branch, working on an accepted, proven
    finding when one is named.
    """

    SYNC = "sync"
    """
    Bring the checked-out branch up to date with GitHub.
    """

    STACK = "stack"
    """
    Put one pull request on top of another in a native stack.
    """

    NOTES = "notes"
    """
    Save the notes block to the notes branch.
    """

    FINDING = "finding"
    """
    File, prioritize, list, accept, shelve, reject, prove or recheck findings, or have
    GitHub complete the finding labels picked there.
    """

    IDEA = "idea"
    """
    Post an idea, not a finding, to the repository's Discussions.
    """

    CLEANUP = "cleanup"
    """
    Delete the branches GitHub kept although their pull request is closed, and the
    branches discarded; remove the clones of somebody else's repositories no session
    uses.
    """

    DETAILS = "details"
    """
    Show what a pull request's signals are about.
    """

    DESCRIBE = "describe"
    """
    Rewrite the description, the title or both of an open pull request, a draft or
    ready for review.
    """

    CLONE = "clone"
    """
    Clone a repository, next to the checkout the command runs in: the owner's to work
    in, anyone else's to read.
    """

    UPSTREAM = "upstream"
    """
    Open a pull request of the owner's fork on the repository it was forked from; the
    person's alone, never a session's.
    """

    LABEL = "label"
    """
    Add labels of the repository's to the work branch's pull request, or remove them.
    """

    REVIEW = "review"
    """
    List, reply to or resolve the review threads of the work branch's pull request.
    """

    @classmethod
    def command_line(cls, *arguments: str) -> str:
        """
        :param arguments: A command and its arguments, none for the bare entry point.
        :return: The command line running it with the interpreter the package runs in:
            the launcher's name when the launcher found on the path runs that
            interpreter, the interpreter's full path otherwise.
        """
        launcher = shutil.which(Launcher.COMMAND)
        runtime = Path(sys.executable).parents[1]
        if (
            launcher is not None
            and Path(launcher).read_text()
            == LauncherInstallation(Path(launcher).parent, runtime).script
        ):
            return " ".join([Launcher.COMMAND, *arguments])
        return " ".join([sys.executable, "-m", github_workflow.__name__, *arguments])


class BranchSubcommand(StrEnum):
    """
    What ``branch`` does.
    """

    START = "start"
    """
    Create a work branch from the default branch, or from another branch, and switch to
    it.
    """

    SWITCH = "switch"
    """
    Switch to an existing branch.
    """

    DISCARD = "discard"
    """
    Mark a pushed branch as thrown away, so the cleanup deletes it.
    """


class FindingSubcommand(StrEnum):
    """
    What ``finding`` does.
    """

    FILE = "file"
    """
    File something noticed outside the current work, as unreviewed, and proven when a
    test failing on the default branch is given.
    """

    PRIORITIZE = "prioritize"
    """
    Give an existing issue a priority, replacing any other, making it an unreviewed
    finding when it is none yet.
    """

    LIST = "list"
    """
    List the open findings.
    """

    CLOSE = "close"
    """
    Close an accepted, proven finding whose fix is merged and whose proof now passes.
    """

    ACCEPT = "accept"
    """
    Accept an unreviewed or shelved finding, on the person's word.
    """

    SHELVE = "shelve"
    """
    Set an unreviewed or accepted finding aside, on the person's word.
    """

    REJECT = "reject"
    """
    Reject a finding as incorrect, with a reason, on the person's word.
    """

    COMMENT = "comment"
    """
    Comment on a finding, open or closed.
    """

    EDIT = "edit"
    """
    Rewrite an open finding's title or text.
    """

    PROVE = "prove"
    """
    Prove an open finding with a test failing on the default branch.
    """

    MARK_UNPROVEN = "mark-unproven"
    """
    Mark an open finding unproven, with the reason no failing test could be written.
    """

    RECHECK = "recheck"
    """
    Run the test proving a finding again on the default branch, writing nothing.
    """

    AUTOMATE = "automate"
    """
    Write the Actions workflow completing finding labels picked on GitHub into the
    checkout.
    """


class ReviewSubcommand(StrEnum):
    """
    What ``review`` does.
    """

    LIST = "list"
    """
    List the threads, each with the identifier the others take.
    """

    REPLY = "reply"
    """
    Reply in a thread.
    """

    RESOLVE = "resolve"
    """
    Resolve a thread, once its fix is pushed.
    """

    ADDRESSED = "addressed"
    """
    Say on the pull request what was changed for a review comment upstream, linking it.
    """


class IdeaSubcommand(StrEnum):
    """
    What ``idea`` does.
    """

    FILE = "file"
    """
    Queue an idea to be posted to the repository's Discussions.
    """


class StackSubcommand(StrEnum):
    """
    What ``stack`` does.
    """

    ON = "on"
    """
    Put the second pull request on top of the first.
    """


class NotesSubcommand(StrEnum):
    """
    What ``notes`` does.
    """

    SAVE = "save"
    """
    Push the edited notes block to the notes branch.
    """


class ArgumentName(StrEnum):
    """
    The names of the positional arguments the commands take, each spelled once.
    """

    ABOVE = "above"
    """
    The pull request a stack ends at, the top of the range.
    """

    ADDRESS = "address"
    """
    The address of a review comment on the pull request opened upstream.
    """

    BELOW = "below"
    """
    The pull request a stack starts at, the bottom of the range.
    """

    BRANCH = "branch"
    """
    A branch of the repository named.
    """

    COMMENT = "comment"
    """
    The identifier of a comment in a review thread.
    """

    NAME = "name"
    """
    A branch's name.
    """

    NUMBER = "number"
    """
    A pull request's or issue's number.
    """

    PATHS = "paths"
    """
    The files a command works on.
    """

    REPOSITORY = "repository"
    """
    A repository, as ``owner/name``.
    """


class CommandOption(StrEnum):
    """
    The options the commands take, each spelled once.
    """

    ON = "--on"
    """
    The pull request or branch a command builds on or runs on.
    """

    TITLE = "--title"
    """
    A pull request's, finding's or idea's title.
    """

    BODY_FILE = "--body-file"
    """
    The file holding a description, a comment or a reply.
    """

    REPLACES = "--replaces"
    """
    The pull request a draft replaces.
    """

    FINDING = "--finding"
    """
    The finding a draft works on.
    """

    PYTHON = "--python"
    """
    The interpreter the project's tests run with.
    """

    UPSTREAM = "--upstream"
    """
    Sync the fork's default branch with its upstream's instead.
    """

    BASE = "--base"
    """
    Sync by merging the default branch into the work branch instead.
    """

    CONTINUE = "--continue"
    """
    Commit the merge in progress instead, once its conflicts are resolved.
    """

    ABORT = "--abort"
    """
    Undo the merge in progress instead.
    """

    PRIORITY = "--priority"
    """
    How urgent a finding is.
    """

    TEST = "--test"
    """
    The uncommitted test file proving a finding.
    """

    REPOSITORY = "--repository"
    """
    Another of the owner's repositories a finding is on.
    """

    REASON = "--reason"
    """
    Why a finding is rejected, or unproven.
    """

    FIXED_BY = "--fixed-by"
    """
    The merged pull request fixing a finding.
    """

    CATEGORY = "--category"
    """
    The discussion category an idea is posted in.
    """

    ADD = "--add"
    """
    A label to add.
    """

    REMOVE = "--remove"
    """
    A label to remove.
    """

    MESSAGE = "--message"
    """
    A commit's message.
    """


class PriorityLevel(StrEnum):
    """
    How urgent a finding is, as the command line names it, each with what it means.
    """

    meaning: str
    """
    What the level means, in a few words.
    """

    def __new__(cls, level: str, meaning: str) -> PriorityLevel:
        """
        :param level: The level, as the command line takes it.
        :param meaning: What it means.
        :return: The member.
        """
        member = str.__new__(cls, level)
        member._value_ = level
        member.meaning = meaning
        return member

    CRITICAL = ("critical", "Breaks the default branch, security, or data")
    """
    Worked on before anything else.
    """

    HIGH = ("high", "Wrong behaviour in normal use")
    """
    Worked on next.
    """

    MEDIUM = ("medium", "Wrong in edge cases, or a maintainability risk")
    """
    Worked on when nothing more urgent waits.
    """

    LOW = ("low", "Cosmetic, or cleanup")
    """
    Worked on last.
    """

    @classmethod
    def guide(cls) -> str:
        """:return: What each level means, in one line."""
        return "; ".join(f"{level}: {level.meaning}" for level in cls)


# %% who runs a command


@dataclass(frozen=True)
class CommandAuthority(ABC):
    """
    Whose decision runs a command.
    """

    @classproperty
    def session_may_run(cls) -> bool:
        """
        Whether a session runs the command at all, on its own or on the person's word.
        """
        return True

    @abstractmethod
    def runs_unasked(self, arguments: Sequence[str]) -> bool:
        """
        :param arguments: The words following the command's own, options left out.
        :return: Whether a session runs the command line on its own.
        """


@dataclass(frozen=True)
class SessionRuns(CommandAuthority):
    """
    A session runs the command on its own, without asking.
    """

    def runs_unasked(self, arguments: Sequence[str]) -> bool:
        return True


@dataclass(frozen=True)
class SessionRunsOnOwnPullRequest(CommandAuthority):
    """
    A session runs the command on its own on the work branch's own pull request,
    naming no number; naming another's is the person's word.
    """

    def runs_unasked(self, arguments: Sequence[str]) -> bool:
        return not any(word.isdigit() for word in arguments)


@dataclass(frozen=True)
class SessionRunsOnPersonsWord(CommandAuthority):
    """
    A session runs the command only on the person's word.
    """

    def runs_unasked(self, arguments: Sequence[str]) -> bool:
        return False


@dataclass(frozen=True)
class PersonRuns(CommandAuthority):
    """
    Only the person runs the command, never a session, even with the person's
    go-ahead.
    """

    @classproperty
    def session_may_run(cls) -> bool:
        return False

    def runs_unasked(self, arguments: Sequence[str]) -> bool:
        return False


# %% the arguments


@dataclass(eq=False)
class ValueCountParsing:
    """
    How the command line's parser reads an argument's values.
    """

    values_taken: str | None = None
    """
    How many values it takes, as :mod:`argparse`'s ``nargs`` spells it; ``None`` for
    exactly one.
    """

    parser_action: str | None = None
    """
    What the parser does with them, as :mod:`argparse`'s ``action`` spells it; ``None``
    to store the value.
    """


class ArgumentCount(ValueCountParsing, Enum):
    """
    How many values an argument takes.
    """

    ONE = ()
    """
    Exactly one.
    """

    OPTIONAL = ("?",)
    """
    One, or none for a positional argument that may be left out.
    """

    SEVERAL = ("+",)
    """
    One or more.
    """

    REPEATED = (None, "append")
    """
    One each time the option is given; the option may be given several times.
    """

    NONE = (None, "store_true")
    """
    None: the option is a flag, true when given.
    """


@dataclass(frozen=True)
class CommandArgument:
    """
    One argument a command takes: an option, or a positional argument.
    """

    name: str
    """
    The option, or the positional argument's name, which the parsed command line holds
    its value under.
    """

    placeholder: str = ""
    """
    What a line naming the command shows in place of the value, empty for a flag.
    """

    description: str | None = None
    """
    What the argument is, as ``--help`` shows it.
    """

    value_type: Callable[[str], Any] | None = None
    """
    What the value is converted to, ``None`` to keep it text.
    """

    required: bool = False
    """
    Whether an option has to be given.
    """

    count: ArgumentCount = ArgumentCount.ONE
    """
    How many values it takes.
    """

    default: str | None = None
    """
    The value when it is left out.
    """

    choices: tuple[str, ...] = ()
    """
    The values it takes, any when empty.
    """

    destination: str | None = None
    """
    The name the parsed command line holds an option's value under, when it is not the
    option's own.
    """

    alternative: bool = False
    """
    Whether it excludes the command's other alternative arguments.
    """

    short_name: str | None = None
    """
    The option's one-letter form, if any.
    """

    @classmethod
    def interpreter(cls) -> CommandArgument:
        """
        The interpreter a command running a test runs it with.
        """
        return cls(
            CommandOption.PYTHON,
            "interpreter",
            "the interpreter the project's tests run with (default: %(default)s)",
            default="python",
        )

    @classmethod
    def priority(cls) -> CommandArgument:
        """
        How urgent a finding is.
        """
        return cls(
            CommandOption.PRIORITY,
            "level",
            PriorityLevel.guide(),
            required=True,
            choices=tuple(PriorityLevel),
        )

    @classmethod
    def other_repository(cls, alternative: bool = False) -> CommandArgument:
        """
        :param alternative: Whether it excludes the command's other alternative
            arguments.
        :return: Another of the owner's repositories a finding is on.
        """
        return cls(
            CommandOption.REPOSITORY,
            "owner/name",
            "another of the owner's repositories, as owner/name, no checkout needed; "
            "the checkout's when left out",
            alternative=alternative,
        )

    @classmethod
    def branch_to_run_on(cls) -> CommandArgument:
        """
        The branch a finding's test runs on.
        """
        return cls(
            CommandOption.ON,
            "pull request or branch",
            "an open pull request's number, or a branch, of the owner's repository to "
            "run the test on; the default branch when left out",
        )

    @classmethod
    def body_file(
        cls, description: str | None = None, required: bool = True
    ) -> CommandArgument:
        """
        :param description: What the file holds, as ``--help`` shows it.
        :param required: Whether it has to be given.
        :return: The file holding a text the command writes.
        """
        return cls(CommandOption.BODY_FILE, "file", description, Path, required)

    @classmethod
    def number(cls, description: str | None = None) -> CommandArgument:
        """
        :param description: What it is the number of, as ``--help`` shows it.
        :return: The number of an issue or pull request.
        """
        return cls(ArgumentName.NUMBER, "number", description, int)

    @property
    def is_option(self) -> bool:
        """:return: Whether it is an option rather than a positional argument."""
        return self.name.startswith("-")

    def format_usage(self, value: str | None = None) -> str:
        """
        :param value: The value shown, ``None`` for the placeholder.
        :return: The argument as a line naming the command shows it.
        """
        shown = f"<{self.placeholder}>" if value is None else value
        if self.count is ArgumentCount.SEVERAL and value is None:
            shown += "..."
        if not self.is_option:
            return shown
        if self.count is ArgumentCount.NONE:
            return self.name
        return f"{self.name} {shown}"

    def register(self, parser: argparse._ActionsContainer) -> None:
        """
        :param parser: The parser, or a group of its arguments, to add the argument to.
        """
        names = [self.short_name, self.name] if self.short_name else [self.name]
        keywords: dict[str, Any] = {"help": self.description}
        if self.count.parser_action is not None:
            keywords["action"] = self.count.parser_action
        if self.count is ArgumentCount.NONE:
            parser.add_argument(*names, **keywords)
            return
        if self.value_type is not None:
            keywords["type"] = self.value_type
        if self.default is not None:
            keywords["default"] = self.default
        if self.choices:
            keywords["choices"] = self.choices
        if self.destination is not None:
            keywords["dest"] = self.destination
        if self.count.values_taken is not None:
            keywords["nargs"] = self.count.values_taken
        if self.is_option:
            keywords["required"] = self.required
            keywords["metavar"] = self.placeholder.upper().replace(" ", "_")
        parser.add_argument(*names, **keywords)


# %% the commands


@dataclass(eq=False)
class CommandSpecification:
    """
    One command line the workflow runs: its words, who runs it, and what it takes.
    """

    words: tuple[str, ...]
    """
    The command and its subcommand, if any.
    """

    summary: str
    """
    What it does, as ``--help`` lists it.
    """

    authority: CommandAuthority
    """
    Whose decision runs it.
    """

    arguments: tuple[CommandArgument, ...] = ()
    """
    What it takes.
    """

    def argument(self, name: str) -> CommandArgument:
        """
        :param name: An option, or a positional argument's name.
        :return: The argument of this command of that name.
        :raises KeyError: If the command takes none.
        """
        return {argument.name: argument for argument in self.arguments}[name]

    def words_naming(
        self,
        *shown: str,
        optional: Sequence[str] = (),
        values: Mapping[str, str] | None = None,
    ) -> list[str]:
        """
        :param shown: The arguments shown, by name, in order.
        :param optional: Further arguments shown, by name, marked as optional.
        :param values: The value shown for an argument, by name, in place of its
            placeholder.
        :return: The command's words followed by the arguments.
        :raises KeyError: If the command takes no argument of a name.
        """
        given = values or {}
        named = [self.argument(name).format_usage(given.get(name)) for name in shown]
        named += [
            f"[{self.argument(name).format_usage(given.get(name))}]"
            for name in optional
        ]
        return [*self.words, *named]

    def usage(
        self,
        *shown: str,
        optional: Sequence[str] = (),
        values: Mapping[str, str] | None = None,
    ) -> str:
        """
        :param shown: The arguments shown, by name, in order.
        :param optional: Further arguments shown, by name, marked as optional.
        :param values: The value shown for an argument, by name, in place of its
            placeholder.
        :return: The command line running the command with the interpreter the package
            runs in, as :meth:`WorkflowCommand.command_line` names it.
        :raises KeyError: If the command takes no argument of a name.
        """
        return WorkflowCommand.command_line(
            *self.words_naming(*shown, optional=optional, values=values)
        )

    def runs_unasked(self, words: Sequence[str]) -> bool:
        """
        :param words: The words of a command line running this command, options left
            out.
        :return: Whether a session runs that line on its own.
        """
        return self.authority.runs_unasked(words[len(self.words) :])


class RunnableCommand(CommandSpecification, Enum):
    """
    Every command line the workflow runs.
    """

    BRANCH_START = (
        (WorkflowCommand.BRANCH, BranchSubcommand.START),
        "start a work branch",
        SessionRuns(),
        (
            CommandArgument(ArgumentName.NAME, "name", value_type=BranchName),
            CommandArgument(
                CommandOption.ON, "branch", "the branch to start from", BranchName
            ),
        ),
    )
    """
    ``branch start``.
    """

    BRANCH_SWITCH = (
        (WorkflowCommand.BRANCH, BranchSubcommand.SWITCH),
        "switch to a branch",
        SessionRuns(),
        (CommandArgument(ArgumentName.NAME, "branch", value_type=BranchName),),
    )
    """
    ``branch switch``.
    """

    BRANCH_DISCARD = (
        (WorkflowCommand.BRANCH, BranchSubcommand.DISCARD),
        "mark a pushed branch as thrown away, for the cleanup to delete",
        SessionRuns(),
        (
            CommandArgument(
                ArgumentName.NAME,
                "branch",
                "the branch, the checked-out one when left out",
                BranchName,
                count=ArgumentCount.OPTIONAL,
            ),
        ),
    )
    """
    ``branch discard``.
    """

    COMMIT = (
        (WorkflowCommand.COMMIT,),
        "commit files",
        SessionRuns(),
        (
            CommandArgument(
                CommandOption.MESSAGE, "message", required=True, short_name="-m"
            ),
            CommandArgument(
                ArgumentName.PATHS,
                "paths",
                value_type=Path,
                count=ArgumentCount.SEVERAL,
            ),
        ),
    )
    """
    ``commit``.
    """

    PUSH = ((WorkflowCommand.PUSH,), "push the work branch", SessionRuns())
    """
    ``push``.
    """

    DRAFT = (
        (WorkflowCommand.DRAFT,),
        "open a draft",
        SessionRuns(),
        (
            CommandArgument(CommandOption.TITLE, "title", required=True),
            CommandArgument.body_file(),
            CommandArgument(
                CommandOption.ON, "pull request", "the pull request to stack it on", int
            ),
            CommandArgument(
                CommandOption.REPLACES,
                "old",
                "the pull request it replaces, closed once it is open",
                int,
            ),
            CommandArgument(
                CommandOption.FINDING,
                "number",
                "the accepted, proven finding it works on, rechecked first",
                int,
            ),
            CommandArgument.interpreter(),
        ),
    )
    """
    ``draft``.
    """

    SYNC = (
        (WorkflowCommand.SYNC,),
        "bring the branch up to date",
        SessionRuns(),
        (
            CommandArgument(
                CommandOption.UPSTREAM,
                description="instead, fast-forward a fork's default branch to its upstream's",
                count=ArgumentCount.NONE,
                alternative=True,
            ),
            CommandArgument(
                CommandOption.BASE,
                description="instead, merge GitHub's default branch into the work branch",
                count=ArgumentCount.NONE,
                alternative=True,
            ),
            CommandArgument(
                CommandOption.ON,
                "number",
                "instead, merge the branch of this open pull request into the work "
                "branch, to build on it",
                int,
                alternative=True,
            ),
            CommandArgument(
                CommandOption.CONTINUE,
                "file",
                "instead, commit the merge in progress, once these files it left "
                "conflicting are resolved",
                Path,
                count=ArgumentCount.SEVERAL,
                destination="resolved",
                alternative=True,
            ),
            CommandArgument(
                CommandOption.ABORT,
                description="instead, undo the merge in progress",
                count=ArgumentCount.NONE,
                alternative=True,
            ),
        ),
    )
    """
    ``sync``.
    """

    STACK_ON = (
        (WorkflowCommand.STACK, StackSubcommand.ON),
        "put above on below",
        SessionRunsOnPersonsWord(),
        (
            CommandArgument(ArgumentName.BELOW, "below", value_type=int),
            CommandArgument(ArgumentName.ABOVE, "above", value_type=int),
        ),
    )
    """
    ``stack on``.
    """

    NOTES_SAVE = (
        (WorkflowCommand.NOTES, NotesSubcommand.SAVE),
        "save the notes block",
        SessionRuns(),
    )
    """
    ``notes save``.
    """

    FINDING_FILE = (
        (WorkflowCommand.FINDING, FindingSubcommand.FILE),
        "file something noticed outside the current work",
        SessionRuns(),
        (
            CommandArgument.priority(),
            CommandArgument(CommandOption.TITLE, "title", required=True),
            CommandArgument.body_file(),
            CommandArgument(
                CommandOption.TEST,
                "file",
                "an uncommitted test file failing on the default branch, proving it",
                Path,
                alternative=True,
            ),
            CommandArgument.other_repository(alternative=True),
            CommandArgument.interpreter(),
        ),
    )
    """
    ``finding file``.
    """

    FINDING_PRIORITIZE = (
        (WorkflowCommand.FINDING, FindingSubcommand.PRIORITIZE),
        "give an existing issue a priority, as a finding",
        SessionRunsOnPersonsWord(),
        (CommandArgument.number("the issue"), CommandArgument.priority()),
    )
    """
    ``finding prioritize``.
    """

    FINDING_LIST = (
        (WorkflowCommand.FINDING, FindingSubcommand.LIST),
        "list open findings",
        SessionRuns(),
        (CommandArgument.other_repository(),),
    )
    """
    ``finding list``.
    """

    FINDING_ACCEPT = (
        (WorkflowCommand.FINDING, FindingSubcommand.ACCEPT),
        "accept a finding, on the person's word",
        SessionRunsOnPersonsWord(),
        (CommandArgument.number(),),
    )
    """
    ``finding accept``.
    """

    FINDING_SHELVE = (
        (WorkflowCommand.FINDING, FindingSubcommand.SHELVE),
        "set a finding aside, on the person's word",
        SessionRunsOnPersonsWord(),
        (CommandArgument.number(),),
    )
    """
    ``finding shelve``.
    """

    FINDING_REJECT = (
        (WorkflowCommand.FINDING, FindingSubcommand.REJECT),
        "reject a finding as incorrect, on the person's word",
        SessionRunsOnPersonsWord(),
        (
            CommandArgument.number(),
            CommandArgument(CommandOption.REASON, "reason", required=True),
        ),
    )
    """
    ``finding reject``.
    """

    FINDING_COMMENT = (
        (WorkflowCommand.FINDING, FindingSubcommand.COMMENT),
        "comment on a finding, open or closed",
        SessionRuns(),
        (
            CommandArgument.number(),
            CommandArgument.body_file(),
            CommandArgument.other_repository(),
        ),
    )
    """
    ``finding comment``.
    """

    FINDING_EDIT = (
        (WorkflowCommand.FINDING, FindingSubcommand.EDIT),
        "rewrite an open finding's title or text",
        SessionRunsOnPersonsWord(),
        (
            CommandArgument.number(),
            CommandArgument(CommandOption.TITLE, "title"),
            CommandArgument.body_file(required=False),
            CommandArgument.other_repository(),
        ),
    )
    """
    ``finding edit``.
    """

    FINDING_PROVE = (
        (WorkflowCommand.FINDING, FindingSubcommand.PROVE),
        "prove an open finding with a test failing on the default branch, or on the "
        "branch --on names",
        SessionRuns(),
        (
            CommandArgument.number(),
            CommandArgument(
                CommandOption.TEST,
                "file",
                "the uncommitted test file",
                Path,
                required=True,
            ),
            CommandArgument.branch_to_run_on(),
            CommandArgument.interpreter(),
        ),
    )
    """
    ``finding prove``.
    """

    FINDING_MARK_UNPROVEN = (
        (WorkflowCommand.FINDING, FindingSubcommand.MARK_UNPROVEN),
        "mark an open finding no failing test could be written for",
        SessionRuns(),
        (
            CommandArgument.number(),
            CommandArgument(CommandOption.REASON, "reason", required=True),
        ),
    )
    """
    ``finding mark-unproven``.
    """

    FINDING_RECHECK = (
        (WorkflowCommand.FINDING, FindingSubcommand.RECHECK),
        "run a finding's proof again on the default branch, or on the branch --on "
        "names",
        SessionRuns(),
        (
            CommandArgument.number(),
            CommandArgument.branch_to_run_on(),
            CommandArgument.interpreter(),
        ),
    )
    """
    ``finding recheck``.
    """

    FINDING_CLOSE = (
        (WorkflowCommand.FINDING, FindingSubcommand.CLOSE),
        "close an accepted, proven finding once its fix is merged and its proof passes "
        "on the default branch",
        SessionRuns(),
        (
            CommandArgument.number(),
            CommandArgument(
                CommandOption.FIXED_BY,
                "pull request",
                "the merged pull request",
                int,
                required=True,
            ),
            CommandArgument.interpreter(),
        ),
    )
    """
    ``finding close``.
    """

    FINDING_AUTOMATE = (
        (WorkflowCommand.FINDING, FindingSubcommand.AUTOMATE),
        "write the Actions workflow completing finding labels picked on GitHub",
        SessionRunsOnPersonsWord(),
    )
    """
    ``finding automate``.
    """

    IDEA_FILE = (
        (WorkflowCommand.IDEA, IdeaSubcommand.FILE),
        "queue an idea; the repository's Actions post it",
        SessionRuns(),
        (
            CommandArgument(CommandOption.TITLE, "title", required=True),
            CommandArgument.body_file(),
            CommandArgument(
                CommandOption.CATEGORY,
                "name",
                "the discussion category, by name; the ideas category when left out",
            ),
        ),
    )
    """
    ``idea file``.
    """

    CLEANUP = (
        (WorkflowCommand.CLEANUP,),
        "delete branches of closed pull requests, and clones of somebody else's "
        "repositories no session uses",
        SessionRuns(),
    )
    """
    ``cleanup``.
    """

    DETAILS = (
        (WorkflowCommand.DETAILS,),
        "what a pull request's signals are about",
        SessionRuns(),
        (CommandArgument.number("the pull request"),),
    )
    """
    ``details``.
    """

    DESCRIBE = (
        (WorkflowCommand.DESCRIBE,),
        "rewrite an open pull request's description or title",
        SessionRunsOnOwnPullRequest(),
        (
            CommandArgument(
                ArgumentName.NUMBER,
                "number",
                "the open pull request, the work branch's own when left out",
                int,
                count=ArgumentCount.OPTIONAL,
            ),
            CommandArgument.body_file("the new description", required=False),
            CommandArgument(CommandOption.TITLE, "title", "the new title"),
        ),
    )
    """
    ``describe``.
    """

    CLONE = (
        (WorkflowCommand.CLONE,),
        "clone a repository: the owner's to work in, anyone's to read",
        SessionRuns(),
        (
            CommandArgument(
                ArgumentName.REPOSITORY, "owner/name", "the repository, as owner/name"
            ),
        ),
    )
    """
    ``clone``.
    """

    LABEL = (
        (WorkflowCommand.LABEL,),
        "label the work branch's own pull request, without asking",
        SessionRuns(),
        (
            CommandArgument(
                CommandOption.ADD,
                "label",
                "a label to add, repeatable",
                count=ArgumentCount.REPEATED,
            ),
            CommandArgument(
                CommandOption.REMOVE,
                "label",
                "a label to remove, repeatable",
                count=ArgumentCount.REPEATED,
            ),
        ),
    )
    """
    ``label``.
    """

    REVIEW_LIST = (
        (WorkflowCommand.REVIEW, ReviewSubcommand.LIST),
        "list the threads, each with its identifier",
        SessionRuns(),
    )
    """
    ``review list``.
    """

    REVIEW_REPLY = (
        (WorkflowCommand.REVIEW, ReviewSubcommand.REPLY),
        "reply in a thread, without asking",
        SessionRuns(),
        (
            CommandArgument(
                ArgumentName.COMMENT, "comment", "the thread's identifier", int
            ),
            CommandArgument.body_file(),
        ),
    )
    """
    ``review reply``.
    """

    REVIEW_RESOLVE = (
        (WorkflowCommand.REVIEW, ReviewSubcommand.RESOLVE),
        "resolve a thread once its fix is pushed, without asking",
        SessionRuns(),
        (
            CommandArgument(
                ArgumentName.COMMENT, "comment", "the thread's identifier", int
            ),
        ),
    )
    """
    ``review resolve``.
    """

    REVIEW_ADDRESSED = (
        (WorkflowCommand.REVIEW, ReviewSubcommand.ADDRESSED),
        "say on the pull request what was changed for a review comment upstream, "
        "without asking; nothing is written upstream",
        SessionRuns(),
        (
            CommandArgument(
                ArgumentName.ADDRESS,
                "its address",
                "the upstream comment's address, as `review list` shows it",
            ),
            CommandArgument.body_file("what was changed for it"),
        ),
    )
    """
    ``review addressed``.
    """

    UPSTREAM = (
        (WorkflowCommand.UPSTREAM,),
        "open a fork's pull request on its upstream; the person's alone",
        PersonRuns(),
        (
            CommandArgument(
                ArgumentName.REPOSITORY, "owner/name", "the owner's fork, as owner/name"
            ),
            CommandArgument(
                ArgumentName.BRANCH,
                "branch",
                "the fork's branch with the pull request",
                BranchName,
            ),
        ),
    )
    """
    ``upstream``.
    """

    @classmethod
    def from_words(cls, words: Sequence[str]) -> RunnableCommand | None:
        """
        :param words: A workflow command line's words, options left out.
        :return: The command they run, ``None`` when they run none.
        """
        return next(
            (
                command
                for command in cls
                if tuple(words[: len(command.words)]) == command.words
            ),
            None,
        )

    @classmethod
    def parser(cls) -> argparse.ArgumentParser:
        """
        :return: The parser of every command's line, each command's words under
            ``command`` and ``action``.
        """
        parser = argparse.ArgumentParser(
            prog=WorkflowCommand.command_line(),
            description=__doc__.strip().splitlines()[0],
        )
        parser.set_defaults(action=None)
        commands = parser.add_subparsers(dest="command", required=True)
        subcommands: dict[str, argparse._SubParsersAction] = {}
        for command in cls:
            first = command.words[0]
            if len(command.words) == 1:
                command.register_arguments(
                    commands.add_parser(first, help=command.summary)
                )
                continue
            if first not in subcommands:
                actions = ", ".join(
                    other.words[1] for other in cls if other.words[0] == first
                )
                group = commands.add_parser(first, help=actions)
                subcommands[first] = group.add_subparsers(dest="action", required=True)
            command.register_arguments(
                subcommands[first].add_parser(command.words[1], help=command.summary)
            )
        return parser

    def register_arguments(self, parser: argparse.ArgumentParser) -> None:
        """
        :param parser: The command's own parser, given each of its arguments.
        """
        alternatives = (
            parser.add_mutually_exclusive_group()
            if any(argument.alternative for argument in self.arguments)
            else None
        )
        for argument in self.arguments:
            argument.register(alternatives if argument.alternative else parser)


# %% what a session does about a refusal


class RefusalAdvice:
    """
    What a session is told about the workflow's refusals.
    """

    @classmethod
    def workaround_ban(cls) -> str:
        """
        :return: That a session never gets around a refusal, opening what it does
            about one.
        """
        return (
            "Never get around a refusal, with a script or in any other way: ask the "
            "person, or report it."
        )

    @classmethod
    def pointer(cls) -> str:
        """
        :return: What ends every refusal: never to get around it, and where the notes
            say how to report one that was unnecessary.
        """
        return (
            f"{cls.workaround_ban()} How to report an unnecessary refusal is in the "
            f"notes."
        )

    @classmethod
    def hint(cls) -> str:
        """
        :return: What a session does about a refusal, never getting around it, for the
            notes header.
        """
        listing = RunnableCommand.FINDING_LIST.usage(
            CommandOption.REPOSITORY,
            values={CommandOption.REPOSITORY: ToolRepository.WORKFLOW},
        )
        filing = RunnableCommand.FINDING_FILE.usage(
            CommandOption.REPOSITORY,
            CommandOption.PRIORITY,
            CommandOption.TITLE,
            CommandOption.BODY_FILE,
            values={CommandOption.REPOSITORY: ToolRepository.WORKFLOW},
        )
        return (
            f"{cls.workaround_ban()} "
            f"When the workflow refuses something unnecessarily or lacks it, check "
            f"`{listing}` and file it there without asking first: `{filing}`, with "
            f"what you ran, what happened and what should have, for git and GitHub "
            f"themselves too. A cloud session reaches only the repositories attached to "
            f"it: attach {ToolRepository.WORKFLOW} with push access without asking, "
            f"never another account's copy of it."
        )
