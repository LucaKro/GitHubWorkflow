"""
The guard every tool call passes before it runs, as a Claude Code ``PreToolUse`` hook:
it denies writing to git or GitHub directly, so every write goes through the workflow's
commands, and prints nothing for a call it leaves to the usual permissions.

Usage: ``python -m github_workflow.guard < hook-input.json``
"""

from __future__ import annotations

import json
import re
import sys
from abc import ABC, abstractmethod
from collections.abc import Sequence
from dataclasses import dataclass, replace
from enum import StrEnum
from pathlib import PurePath
from typing import Any

from domain_model.call_effects import CallEffect
from domain_model.class_family import ClassFamily
from domain_model.class_property import classproperty
from domain_model.claude_code.hooks import (
    FileWriteCall,
    GitHubToolCall,
    OtherToolCall,
    ShellCommandCall,
    ToolCall,
    ToolCallDenial,
    ToolCallJudge,
)
from domain_model.environment import ClaudeCodeVariable, GitVariable
from domain_model.git.reading import GitCall, GitConfigurationLocation
from domain_model.git.subcommands import GitSubcommand
from domain_model.github.reading_calls import (
    GitHubCliCall,
    GitHubToolReading,
    HttpClient,
    WritingGitHubTool,
)
from domain_model.programs import Program
from domain_model.shell import (
    CommandLine,
    EnvironmentOption,
    Shell,
    SimpleCommand,
    VariableExport,
    VariableRemoval,
    Wrapper,
)

import github_workflow
from github_workflow.command_line import (
    ArgumentName,
    CommandOption,
    RefusalAdvice,
    RunnableCommand,
)
from github_workflow.plugin import Launcher
from github_workflow.report_lines import Speaker

# %% what to do instead


@dataclass(frozen=True)
class Denial:
    """
    Why a call is denied, and the workflow command doing the same job.
    """

    reason: str
    """
    Why the call is denied.
    """

    instead: str | None = None
    """
    The workflow command line to run instead, ``None`` when no workflow command does
    the job and the person running the tool has to.
    """

    saw_write: bool = True
    """
    Whether the guard saw the call write; ``False`` when it denies the call only because
    it cannot see what the call would run, which the person is shown.
    """

    @classmethod
    def from_effect(cls, effect: CallEffect) -> Denial:
        """
        :param effect: What a call does beyond reading.
        :return: The denial, naming the workflow command doing the job when one does.
        """
        write = effect.write
        alternative = None if write is None else WorkflowAlternative.from_write(write)
        return cls(
            effect.description,
            None if alternative is None else alternative.command_line(),
        )

    def message(self) -> str:
        """:return: What the hook tells the model: the reason, and what to run instead."""
        instead = (
            f"Instead run `{self.instead}`."
            if self.instead
            else "No workflow command does this: ask the person running the tool."
        )
        return Speaker.WORKFLOW.says(
            f"{self.reason}. {instead} {RefusalAdvice.pointer()}"
        )


class GitWrite(StrEnum):
    """
    The git subcommands that write and have a workflow command doing the same job.
    """

    PUSH = GitSubcommand.PUSH
    """
    Publishing the branch.
    """

    COMMIT = GitSubcommand.COMMIT
    """
    Recording changes.
    """

    ADD = GitSubcommand.ADD
    """
    Staging changes, which the workflow's commit does with the files it is given.
    """

    SWITCH = GitSubcommand.SWITCH
    """
    Changing or creating the checked-out branch.
    """

    CHECKOUT = GitSubcommand.CHECKOUT
    """
    Changing or creating the checked-out branch, the older way.
    """

    BRANCH = GitSubcommand.BRANCH
    """
    Creating a branch.
    """

    PULL = GitSubcommand.PULL
    """
    Taking in GitHub's copy of the branch.
    """

    MERGE = GitSubcommand.MERGE
    """
    Taking in another branch, which for GitHub's copy is a sync.
    """

    CLONE = GitSubcommand.CLONE
    """
    Making a checkout of another repository.
    """


class GitHubCliWrite(StrEnum):
    """
    The ``gh`` commands that write and have a workflow command doing the same job, by
    their first two words.
    """

    PULL_REQUEST_CREATE = "pr create"
    """
    Opening a pull request.
    """

    PULL_REQUEST_EDIT = "pr edit"
    """
    Rewriting a pull request.
    """

    PULL_REQUEST_COMMENT = "pr comment"
    """
    Commenting on a pull request.
    """


class GitHubToolWrite(StrEnum):
    """
    The GitHub MCP tools that write and have a workflow command doing the same job.
    """

    CREATE_PULL_REQUEST = "create_pull_request"
    """
    Opens a pull request.
    """

    UPDATE_PULL_REQUEST = "update_pull_request"
    """
    Rewrites a pull request.
    """

    ISSUE_WRITE = "issue_write"
    """
    Writes an issue or pull request, its labels among it.
    """

    ADD_REPLY_TO_PULL_REQUEST_COMMENT = "add_reply_to_pull_request_comment"
    """
    Replies in a review thread.
    """

    RESOLVE_REVIEW_THREAD = "resolve_review_thread"
    """
    Resolves a review thread.
    """

    ADD_ISSUE_COMMENT = "add_issue_comment"
    """
    Comments on an issue or pull request.
    """


@dataclass(frozen=True)
class WorkflowAlternative(ClassFamily, ABC):
    """
    A job done by writing to git or GitHub directly that a workflow command does
    instead.
    """

    @classproperty
    def writes(cls) -> tuple[str, ...]:
        """
        The git subcommands, ``gh`` commands and GitHub MCP tools doing the job.
        """
        return ()

    @abstractmethod
    def command_line(self) -> str:
        """
        :return: The workflow command line doing the job.
        """

    @classmethod
    def from_write(cls, write: str) -> WorkflowAlternative | None:
        """
        :param write: A git subcommand, ``gh`` command or GitHub MCP tool that writes.
        :return: The workflow command doing its job, ``None`` when none does.
        """
        return next(
            (
                alternative()
                for alternative in cls.concrete_subclasses()
                if write in alternative.writes
            ),
            None,
        )


@dataclass(frozen=True)
class PushAlternative(WorkflowAlternative):
    """
    Publishing the work branch, with ``push``.
    """

    @classproperty
    def writes(cls) -> tuple[str, ...]:
        return (GitWrite.PUSH,)

    def command_line(self) -> str:
        return RunnableCommand.PUSH.usage()


@dataclass(frozen=True)
class CommitAlternative(WorkflowAlternative):
    """
    Recording changes, with ``commit``, which stages the files it is given.
    """

    @classproperty
    def writes(cls) -> tuple[str, ...]:
        return GitWrite.COMMIT, GitWrite.ADD

    def command_line(self) -> str:
        return RunnableCommand.COMMIT.usage(CommandOption.MESSAGE, ArgumentName.PATHS)


@dataclass(frozen=True)
class BranchSwitchAlternative(WorkflowAlternative):
    """
    Changing the checked-out branch, with ``branch switch``, or ``branch start`` for a
    new one.
    """

    @classproperty
    def writes(cls) -> tuple[str, ...]:
        return GitWrite.SWITCH, GitWrite.CHECKOUT

    def command_line(self) -> str:
        start = RunnableCommand.BRANCH_START.usage(ArgumentName.NAME)
        switch = RunnableCommand.BRANCH_SWITCH.usage(ArgumentName.NAME)
        return f"{switch}`, or for a new one `{start}"


@dataclass(frozen=True)
class BranchStartAlternative(WorkflowAlternative):
    """
    Creating a branch, with ``branch start``.
    """

    @classproperty
    def writes(cls) -> tuple[str, ...]:
        return (GitWrite.BRANCH,)

    def command_line(self) -> str:
        return RunnableCommand.BRANCH_START.usage(ArgumentName.NAME)


@dataclass(frozen=True)
class SyncAlternative(WorkflowAlternative):
    """
    Taking in GitHub's copy of the branch, with ``sync``.
    """

    @classproperty
    def writes(cls) -> tuple[str, ...]:
        return (GitWrite.PULL,)

    def command_line(self) -> str:
        return RunnableCommand.SYNC.usage()


@dataclass(frozen=True)
class MergeAlternative(WorkflowAlternative):
    """
    Taking in another branch, with ``sync --base`` or ``sync --on``.
    """

    @classproperty
    def writes(cls) -> tuple[str, ...]:
        return (GitWrite.MERGE,)

    def command_line(self) -> str:
        base = RunnableCommand.SYNC.usage(CommandOption.BASE)
        stacked = RunnableCommand.SYNC.usage(CommandOption.ON)
        return f"{base}`, or for another open pull request's branch `{stacked}"


@dataclass(frozen=True)
class CloneAlternative(WorkflowAlternative):
    """
    Making a checkout of another repository, with ``clone``.
    """

    @classproperty
    def writes(cls) -> tuple[str, ...]:
        return (GitWrite.CLONE,)

    def command_line(self) -> str:
        clone = RunnableCommand.CLONE.usage(ArgumentName.REPOSITORY)
        return (
            f"{clone}`; to review a pull request, then run in the clone `git fetch "
            f"origin +refs/pull/<number>/head:refs/remotes/pull/<number>"
        )


@dataclass(frozen=True)
class DraftAlternative(WorkflowAlternative):
    """
    Opening a pull request, with ``draft``.
    """

    @classproperty
    def writes(cls) -> tuple[str, ...]:
        return GitHubCliWrite.PULL_REQUEST_CREATE, GitHubToolWrite.CREATE_PULL_REQUEST

    def command_line(self) -> str:
        return RunnableCommand.DRAFT.usage(CommandOption.TITLE, CommandOption.BODY_FILE)


@dataclass(frozen=True)
class DescribeAlternative(WorkflowAlternative):
    """
    Rewriting an open pull request's description or title, with ``describe``.
    """

    @classproperty
    def writes(cls) -> tuple[str, ...]:
        return GitHubCliWrite.PULL_REQUEST_EDIT, GitHubToolWrite.UPDATE_PULL_REQUEST

    def command_line(self) -> str:
        return RunnableCommand.DESCRIBE.usage(
            ArgumentName.NUMBER, optional=(CommandOption.BODY_FILE, CommandOption.TITLE)
        )


@dataclass(frozen=True)
class LabelAlternative(WorkflowAlternative):
    """
    Labelling the work branch's own pull request, with ``label``.
    """

    @classproperty
    def writes(cls) -> tuple[str, ...]:
        return (GitHubToolWrite.ISSUE_WRITE,)

    def command_line(self) -> str:
        return RunnableCommand.LABEL.usage(CommandOption.ADD, CommandOption.REMOVE)


@dataclass(frozen=True)
class CommentAlternative(WorkflowAlternative):
    """
    Commenting on a pull request, with ``comment``, which a session runs only when the
    person asks for the comment.
    """

    @classproperty
    def writes(cls) -> tuple[str, ...]:
        return GitHubCliWrite.PULL_REQUEST_COMMENT, GitHubToolWrite.ADD_ISSUE_COMMENT

    def command_line(self) -> str:
        return RunnableCommand.COMMENT.usage(
            ArgumentName.NUMBER, CommandOption.BODY_FILE
        )


@dataclass(frozen=True)
class ReviewReplyAlternative(WorkflowAlternative):
    """
    Replying in a review thread of the work branch's own pull request, with
    ``review reply``.
    """

    @classproperty
    def writes(cls) -> tuple[str, ...]:
        return (GitHubToolWrite.ADD_REPLY_TO_PULL_REQUEST_COMMENT,)

    def command_line(self) -> str:
        return RunnableCommand.REVIEW_REPLY.usage(
            ArgumentName.COMMENT, CommandOption.BODY_FILE
        )


@dataclass(frozen=True)
class ReviewResolveAlternative(WorkflowAlternative):
    """
    Resolving a review thread of the work branch's own pull request, with
    ``review resolve``.
    """

    @classproperty
    def writes(cls) -> tuple[str, ...]:
        return (GitHubToolWrite.RESOLVE_REVIEW_THREAD,)

    def command_line(self) -> str:
        return RunnableCommand.REVIEW_RESOLVE.usage(ArgumentName.COMMENT)


# %% judging one program


@dataclass(frozen=True)
class ProgramCheck(ClassFamily, ABC):
    """
    Judges the calls of one program.
    """

    @classproperty
    @abstractmethod
    def program(cls) -> Program:
        """
        The program whose calls it judges.
        """

    @abstractmethod
    def denial(self, arguments: Sequence[str]) -> Denial | None:
        """
        :param arguments: What follows the program's name.
        :return: Why the call is denied, ``None`` when it may run.
        """

    @classmethod
    def from_program(cls, program: str) -> ProgramCheck | None:
        """
        :param program: A program's name.
        :return: The check of its calls, ``None`` for a program the guard leaves alone.
        """
        return next(
            (
                check()
                for check in cls.concrete_subclasses()
                if check.program == program
            ),
            None,
        )


@dataclass(frozen=True)
class ReadOnlyCheck(ProgramCheck, ABC):
    """
    Lets a program read, and denies every call doing more.
    """

    @abstractmethod
    def effect(self, arguments: Sequence[str]) -> CallEffect | None:
        """
        :param arguments: What follows the program's name.
        :return: What the call does beyond reading, ``None`` when it only reads.
        """

    def denial(self, arguments: Sequence[str]) -> Denial | None:
        effect = self.effect(arguments)
        return None if effect is None else Denial.from_effect(effect)


@dataclass(frozen=True)
class GitCheck(ReadOnlyCheck):
    """
    Lets git read, and denies every write.
    """

    @classproperty
    def program(cls) -> Program:
        return Program.GIT

    def effect(self, arguments: Sequence[str]) -> CallEffect | None:
        return GitCall(arguments).effect()


@dataclass(frozen=True)
class GitHubCliCheck(ReadOnlyCheck):
    """
    Lets ``gh`` read, and denies every write.
    """

    @classproperty
    def program(cls) -> Program:
        return Program.GITHUB_CLI

    def effect(self, arguments: Sequence[str]) -> CallEffect | None:
        return GitHubCliCall(arguments).effect()


@dataclass(frozen=True)
class HttpClientCheck(ProgramCheck, ABC):
    """
    Lets an HTTP client read from GitHub, and denies sending anything to it.
    """

    @classproperty
    @abstractmethod
    def client(cls) -> HttpClient:
        """
        The client whose calls it judges.
        """

    @classproperty
    def program(cls) -> Program:
        return Program(cls.client.program)

    def denial(self, arguments: Sequence[str]) -> Denial | None:
        if self.client.sends_to_github(arguments):
            return Denial("sending to GitHub directly writes")
        return None


@dataclass(frozen=True)
class CurlCheck(HttpClientCheck):
    """
    The check of ``curl``.
    """

    @classproperty
    def client(cls) -> HttpClient:
        return HttpClient.CURL


@dataclass(frozen=True)
class WgetCheck(HttpClientCheck):
    """
    The check of ``wget``.
    """

    @classproperty
    def client(cls) -> HttpClient:
        return HttpClient.WGET


# %% judging a command line


@dataclass(frozen=True)
class WorkflowInvocation:
    """
    A simple command, as a run of the workflow's commands.
    """

    command: SimpleCommand
    """
    The simple command.
    """

    def words(self) -> list[str] | None:
        """
        :return: The words it gives ``python -m github_workflow``, or the launcher,
            options left out, ``None`` when it runs neither.
        """
        arguments = self.command.arguments
        if self.command.program == Launcher.COMMAND:
            given = arguments
        elif self.command.program.startswith("python") and "-m" in arguments[:-1]:
            module = arguments.index("-m") + 1
            if arguments[module] != github_workflow.__name__:
                return None
            given = arguments[module + 1 :]
        else:
            return None
        return [word for word in given if not word.startswith("-")]

    def runs(self, command: RunnableCommand) -> bool:
        """
        :param command: A workflow command.
        :return: Whether this runs it.
        """
        words = self.words()
        return words is not None and RunnableCommand.from_words(words) is command


@dataclass(frozen=True)
class CommandGuard:
    """
    Judges whole command lines, looking through wrappers and shells into the programs
    they run.
    """

    enclosing_line_names_git: bool = False
    """
    Whether the command line the judged command belongs to, or one it runs inside -
    through ``eval``, a shell's ``-c`` or a wrapper - names git or gh, so an expansion
    naming a program could be either.
    """

    @classproperty
    def marker_change(cls) -> Denial:
        """
        Why changing the variable marking a Claude Code session's commands is denied.
        """
        return Denial(
            f"changing {ClaudeCodeVariable.COMMAND_MARKER} lets a push skip the "
            f"checkout's push hook"
        )

    def denial(self, command_line: str) -> Denial | None:
        """
        :param command_line: A Bash command line.
        :return: Why it is denied, ``None`` when it may run.
        """
        line = CommandLine(command_line)
        mentions_git = self.enclosing_line_names_git or bool(
            re.search(r"\b(git|gh)\b", command_line)
        )
        if line.runs_input_through_a_shell() and mentions_git:
            return Denial(
                "a shell reading its input could run git or gh unseen", saw_write=False
            )
        judge = replace(self, enclosing_line_names_git=mentions_git)
        for command in line.simple_commands():
            person_only = next(
                (
                    workflow_command
                    for workflow_command in RunnableCommand
                    if not workflow_command.authority.session_may_run
                    and WorkflowInvocation(command).runs(workflow_command)
                ),
                None,
            )
            if person_only is not None:
                return Denial(
                    f"only the person runs `{' '.join(person_only.words)}`, never a "
                    f"Claude Code session: put its command line in the pull request's "
                    f"description for them to copy"
                )
            if mentions_git and "$" in command.program:
                return Denial(
                    "a program named by an expansion could be git or gh",
                    saw_write=False,
                )
            reason = judge.command_denial(command)
            if reason is not None:
                return reason
        return None

    def command_denial(self, command: SimpleCommand) -> Denial | None:
        """
        :param command: One simple command.
        :return: Why it is denied, ``None`` when it may run.
        """
        program, arguments = command.program, command.arguments
        if any(
            GitVariable.steers_git(assignment) for assignment in command.assignments
        ):
            return Denial("setting git's environment can make it run a program")
        marker = ClaudeCodeVariable.COMMAND_MARKER
        if any(
            assignment.partition("=")[0] == marker for assignment in command.assignments
        ):
            return self.marker_change
        if not program:
            return None
        if program in VariableExport and any(
            GitVariable.steers_git(argument) for argument in arguments
        ):
            return Denial("exporting git's environment can make it run a program")
        changes_variables = program in VariableExport or program in VariableRemoval
        if changes_variables and any(
            argument.partition("=")[0] == marker for argument in arguments
        ):
            return self.marker_change
        if program in Wrapper:
            return self._wrapped_denial(Wrapper(program), arguments)
        if program in Shell:
            return self._shell_denial(Shell(program), arguments)
        check = ProgramCheck.from_program(program)
        return None if check is None else check.denial(arguments)

    def _wrapped_denial(self, wrapper: Wrapper, arguments: list[str]) -> Denial | None:
        """
        :param wrapper: The wrapper.
        :param arguments: Its arguments, its options and the command it runs.
        :return: Why the command it runs is denied, ``None`` when it may run.
        """
        if wrapper is Wrapper.ENV and self._drops_marker(arguments):
            return self.marker_change
        judged = {*Program, *Shell, *Wrapper}
        for index, argument in enumerate(arguments):
            if " " in argument:
                reason = self.denial(argument)
                if reason is not None:
                    return reason
            if GitVariable.steers_git(argument) and CommandLine.assignment.fullmatch(
                argument
            ):
                return Denial("setting git's environment can make it run a program")
            names_program_by_expansion = (
                "$" in argument and not CommandLine.assignment.fullmatch(argument)
            )
            if self.enclosing_line_names_git and names_program_by_expansion:
                return Denial(
                    f"a program {wrapper} runs, named by an expansion, could be git "
                    f"or gh",
                    saw_write=False,
                )
            program = PurePath(argument).name
            if wrapper is Wrapper.XARGS and program in Program:
                return Denial(
                    f"xargs gives {program} arguments the guard cannot see",
                    saw_write=False,
                )
            if program in judged:
                return self.command_denial(SimpleCommand(arguments[index:]))
        return None

    @staticmethod
    def _drops_marker(arguments: list[str]) -> bool:
        """
        :param arguments: The arguments of ``env``.
        :return: Whether ``env`` runs its command without the variable marking a Claude
            Code session's commands, or with it changed.
        """
        options = EnvironmentOption
        for index, argument in enumerate(arguments):
            if argument in options and EnvironmentOption(argument).drops_every_variable:
                return True
            if ClaudeCodeVariable.COMMAND_MARKER in argument:
                return True
            previous = arguments[index - 1] if index else ""
            is_value = previous in options and EnvironmentOption(previous).takes_value
            own = argument.startswith("-") or CommandLine.assignment.fullmatch(argument)
            if not own and not is_value:
                return False
        return False

    def _shell_denial(self, shell: Shell, arguments: list[str]) -> Denial | None:
        """
        :param shell: The shell.
        :param arguments: Its arguments.
        :return: Why the command line it runs is denied, ``None`` when it may run.
        """
        if shell is Shell.EVAL:
            return self.denial(" ".join(arguments))
        for index, argument in enumerate(arguments[:-1]):
            if re.fullmatch(r"-[A-Za-z]*c[A-Za-z]*", argument):
                return self.denial(arguments[index + 1])
        return None


# %% the hook


@dataclass(frozen=True)
class ToolGuard(ToolCallJudge[Denial | None]):
    """
    The hook's decision over a tool call: why it is denied, ``None`` when it may run.
    """

    def decide_shell_command(self, call: ShellCommandCall) -> Denial | None:
        return CommandGuard().denial(call.command)

    def decide_file_write(self, call: FileWriteCall) -> Denial | None:
        path = PurePath(call.file_path)
        if GitConfigurationLocation.holds(path):
            return Denial(f"git runs programs that {path} names")
        return None

    def decide_github_tool(self, call: GitHubToolCall) -> Denial | None:
        name = call.tool_without_server
        if GitHubToolReading.names_a_read(name):
            return None
        return Denial.from_effect(WritingGitHubTool(name))

    def decide_other_tool(self, call: OtherToolCall) -> Denial | None:
        return None

    def output(self, call: ToolCall) -> dict[str, Any] | None:
        """
        :param call: A tool call.
        :return: The hook's output denying it, ``None`` to leave it to the usual
            permissions.
        """
        denial = call.request_decision(self)
        if denial is None:
            return None
        shown = (
            None
            if denial.saw_write
            else Speaker.WORKFLOW.says(
                f"denied a command it cannot see into ({denial.reason}): "
                f"{call.shown_input}"
            )
        )
        return ToolCallDenial(denial.message(), shown).answer()


# %% entry point


def main() -> None:
    """
    Read the hook's input and print its decision.
    """
    output = ToolGuard().output(ToolCall.from_json(json.load(sys.stdin)))
    if output is not None:
        print(json.dumps(output))


if __name__ == "__main__":
    main()
