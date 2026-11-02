"""
The guard every tool call passes before it runs: it denies writing to git or GitHub
directly, so every write goes through the workflow's commands. Reading stays allowed.

Run as a Claude Code ``PreToolUse`` hook: reads the hook's JSON on stdin and prints a
denial, or nothing to leave the decision to the usual permissions.

Usage: ``python -m github_workflow.guard < hook-input.json``
"""

from __future__ import annotations

import json
import re
import shlex
import sys
from abc import ABC, abstractmethod
from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum
from pathlib import PurePath
from typing import Any

from basstler_domain_model.class_property import classproperty

from github_workflow.command_line import BranchSubcommand, WorkflowCommand
from github_workflow.hooks import FileWritingTool, HookKey, HookValue

# %% programs


class Program(StrEnum):
    """
    The programs the guard judges, by their executable's name.
    """

    GIT = "git"
    """
    Git itself.
    """

    GITHUB_CLI = "gh"
    """
    GitHub's command-line client.
    """

    CURL = "curl"
    """
    An HTTP client that could call GitHub's API.
    """

    WGET = "wget"
    """
    Another HTTP client that could call GitHub's API.
    """


class Shell(StrEnum):
    """
    Programs that run commands given as a string or on their input, which are judged in
    turn.
    """

    BASH = "bash"
    """
    Bash.
    """

    SH = "sh"
    """
    The POSIX shell.
    """

    ZSH = "zsh"
    """
    The Z shell.
    """

    EVAL = "eval"
    """
    The shell builtin running its arguments as a command line.
    """


class Wrapper(StrEnum):
    """
    Programs that run another command given after their own options and arguments.
    """

    ENV = "env"
    """
    Runs a command with a changed environment.
    """

    SUDO = "sudo"
    """
    Runs a command as another user.
    """

    NOHUP = "nohup"
    """
    Runs a command immune to hangups.
    """

    TIME = "time"
    """
    Runs a command and times it.
    """

    COMMAND = "command"
    """
    The shell builtin running a command past functions and aliases.
    """

    EXEC = "exec"
    """
    The shell builtin replacing the shell with a command.
    """

    NICE = "nice"
    """
    Runs a command at another priority.
    """

    TIMEOUT = "timeout"
    """
    Runs a command with a time limit.
    """

    XARGS = "xargs"
    """
    Runs a command with arguments read from its input.
    """

    WATCH = "watch"
    """
    Runs a command repeatedly.
    """


class VariableExport(StrEnum):
    """
    The shell builtins that can export a variable to every program run after them.
    """

    EXPORT = "export"
    DECLARE = "declare"
    TYPESET = "typeset"


class ShellKeyword(StrEnum):
    """
    The words the shell reads as syntax where a command's program would stand.
    """

    IF = "if"
    THEN = "then"
    ELIF = "elif"
    ELSE = "else"
    FI = "fi"
    WHILE = "while"
    UNTIL = "until"
    DO = "do"
    DONE = "done"
    OPENING_BRACE = "{"
    CLOSING_BRACE = "}"
    NEGATION = "!"

    FUNCTION = "function"
    """
    Defines the function the following word names.
    """

    FOR = "for"
    """
    Starts a loop whose header names a variable and its values, and runs nothing.
    """

    SELECT = "select"
    """
    Starts a menu whose header names a variable and its values, and runs nothing.
    """

    CASE = "case"
    """
    Starts a branching whose header names the word matched, and runs nothing.
    """


# %% git


class GitGlobalOption(StrEnum):
    """
    The options before a git subcommand that change nothing it writes.
    """

    DIRECTORY = "-C"
    """
    Run as if started in another directory; takes the directory.
    """

    NO_PAGER = "--no-pager"
    """
    Print without a pager.
    """

    NO_PAGER_SHORT = "-P"
    """
    Print without a pager, short form.
    """

    VERSION = "--version"
    """
    Print git's version.
    """

    HELP = "--help"
    """
    Print git's help.
    """


class GitProgramOption(StrEnum):
    """
    The options with which a git subcommand that otherwise reads runs a program of the
    caller's choosing, or writes a file.
    """

    UPLOAD_PACK = "--upload-pack"
    """
    Runs the given program as the remote's end of a fetch.
    """

    RECEIVE_PACK = "--receive-pack"
    """
    Runs the given program as the remote's end of a push.
    """

    EXEC = "--exec"
    """
    Runs the given program as the remote's end, the older spelling.
    """

    OUTPUT = "--output"
    """
    Writes the output to the given file.
    """

    EXTERNAL_DIFF = "--ext-diff"
    """
    Runs the configured external diff program.
    """

    TEXT_CONVERSION = "--textconv"
    """
    Runs the configured program converting files to text.
    """

    @classproperty
    def short_letter(cls) -> str:
        """
        The single letter with which ``ls-remote`` runs the program given and ``fetch``
        moves the checked-out branch.
        """
        return "u"

    @classmethod
    def present_in(cls, subcommand: str, arguments: Sequence[str]) -> bool:
        """
        :param subcommand: The git subcommand.
        :param arguments: What follows it.
        :return: Whether one of the arguments runs a program or writes a file.
        """
        remote = (GitReading.LS_REMOTE, GitListing.FETCH)
        for argument in arguments:
            if argument.partition("=")[0] in cls._value2member_map_:
                return True
            short = argument.startswith("-") and not argument.startswith("--")
            if short and subcommand in remote and cls.short_letter in argument:
                return True
        return False


class GitReading(StrEnum):
    """
    The git subcommands that only read, whatever their arguments.
    """

    STATUS = "status"
    DIFF = "diff"
    LOG = "log"
    SHOW = "show"
    BLAME = "blame"
    GREP = "grep"
    REV_PARSE = "rev-parse"
    REV_LIST = "rev-list"
    LS_FILES = "ls-files"
    LS_TREE = "ls-tree"
    LS_REMOTE = "ls-remote"
    CAT_FILE = "cat-file"
    MERGE_BASE = "merge-base"
    DESCRIBE = "describe"
    SHORTLOG = "shortlog"
    FOR_EACH_REF = "for-each-ref"
    SHOW_REF = "show-ref"
    NAME_REV = "name-rev"
    CHECK_IGNORE = "check-ignore"
    VAR = "var"
    VERSION = "version"
    HELP = "help"


class GitListing(StrEnum):
    """
    The git subcommands that read only in some of their forms.
    """

    BRANCH = "branch"
    """
    Reads when it lists branches.
    """

    TAG = "tag"
    """
    Reads when it lists tags.
    """

    REMOTE = "remote"
    """
    Reads when it lists remotes or shows one.
    """

    CONFIG = "config"
    """
    Reads when it gets or lists values.
    """

    STASH = "stash"
    """
    Reads when it lists or shows stashes.
    """

    WORKTREE = "worktree"
    """
    Reads when it lists worktrees.
    """

    REFLOG = "reflog"
    """
    Reads when it shows the reflog.
    """

    SUBMODULE = "submodule"
    """
    Reads when it reports submodules' status.
    """

    FETCH = "fetch"
    """
    Reads from a remote, moving only remote-tracking references, unless a refspec
    names a local branch.
    """

    def reads(self, arguments: Sequence[str]) -> bool:
        """
        :param arguments: What follows the subcommand.
        :return: Whether this form only reads.
        """
        options = {argument for argument in arguments if argument.startswith("-")}
        positional = [argument for argument in arguments if argument not in options]
        match self:
            case GitListing.BRANCH | GitListing.TAG:
                return self._lists(options, positional)
            case GitListing.REMOTE:
                return positional[:1] in ([], ["show"], ["get-url"]) and options <= {
                    "-v",
                    "--verbose",
                    "--push",
                    "--all",
                    "-n",
                }
            case GitListing.CONFIG:
                getting = {"--get", "--get-all", "--get-regexp", "--list", "-l"}
                setting = {"--add", "--unset", "--unset-all", "--replace-all", "--edit"}
                setting |= {"-e", "--rename-section", "--remove-section"}
                gets = bool(options & getting) or positional[:1] in (["get"], ["list"])
                return gets and not options & setting
            case GitListing.STASH:
                return positional[:1] in (["list"], ["show"])
            case GitListing.WORKTREE:
                return positional[:1] == ["list"]
            case GitListing.REFLOG:
                return positional[:1] in ([], ["show"])
            case GitListing.SUBMODULE:
                return positional[:1] == ["status"]
            case GitListing.FETCH:
                return not any(":" in argument for argument in positional)

    @staticmethod
    def _lists(options: set[str], positional: list[str]) -> bool:
        """
        :param options: The options given to ``branch`` or ``tag``.
        :param positional: The other arguments.
        :return: Whether the call lists rather than creates, moves or deletes.
        """
        listing = {"-l", "--list", "-a", "--all", "-r", "--remotes", "-v", "-vv"}
        listing |= {"--show-current", "-n", "--no-color"}
        filters = ("--contains", "--no-contains", "--merged", "--no-merged")
        filters += ("--points-at", "--sort", "--format", "--color")
        if any(
            option not in listing and not option.startswith(filters)
            for option in options
        ):
            return False
        filtered = any(option.startswith(filters) for option in options)
        return not positional or bool(options & {"-l", "--list"}) or filtered


# %% GitHub


class GitHubCliReading(StrEnum):
    """
    The ``gh`` commands that only read, by their first two words.
    """

    PULL_REQUEST_VIEW = "pr view"
    PULL_REQUEST_LIST = "pr list"
    PULL_REQUEST_DIFF = "pr diff"
    PULL_REQUEST_CHECKS = "pr checks"
    PULL_REQUEST_STATUS = "pr status"
    ISSUE_VIEW = "issue view"
    ISSUE_LIST = "issue list"
    ISSUE_STATUS = "issue status"
    RUN_VIEW = "run view"
    RUN_LIST = "run list"
    RUN_WATCH = "run watch"
    REPOSITORY_VIEW = "repo view"
    RELEASE_VIEW = "release view"
    RELEASE_LIST = "release list"
    WORKFLOW_VIEW = "workflow view"
    WORKFLOW_LIST = "workflow list"
    AUTHENTICATION_STATUS = "auth status"


class GitHubCliSubcommand(StrEnum):
    """
    The ``gh`` subcommands judged by their arguments rather than their name.
    """

    API = "api"
    """
    A raw API call, which reads unless given a method, a field or an input.
    """

    SEARCH = "search"
    """
    A search, which only reads.
    """


class GitHubHost(StrEnum):
    """
    The hosts whose addresses mark a ``curl`` or ``wget`` call as one to GitHub.
    """

    WEB = "github.com"
    """
    GitHub and its API, ``api.github.com``.
    """

    CONTENT = "githubusercontent.com"
    """
    GitHub's raw file host.
    """


class GitHubToolReading(StrEnum):
    """
    How the names of GitHub MCP tools that only read start or end.
    """

    GET = "get_"
    """
    Reads one thing.
    """

    LIST = "list_"
    """
    Lists things.
    """

    SEARCH = "search_"
    """
    Searches.
    """

    READ = "_read"
    """
    Reads, in the newer tool names.
    """


class GitConfigurationLocation(StrEnum):
    """
    The names marking a file git reads its configuration or hooks from, and so runs
    the programs it names.
    """

    REPOSITORY = ".git"
    """
    A repository's own directory, its configuration and hooks among it.
    """

    USER = ".gitconfig"
    """
    The user's configuration file.
    """

    @classmethod
    def holds(cls, path: PurePath) -> bool:
        """
        :param path: A file's path.
        :return: Whether git reads its configuration or hooks from the file.
        """
        return cls.REPOSITORY in path.parts or path.name == cls.USER


# %% sending options


@dataclass(frozen=True)
class SendingOptions:
    """
    The options with which an HTTP client sends something rather than reads.
    """

    short: str
    """
    The single letters that send, wherever they stand in a cluster of short options.
    """

    long: tuple[str, ...]
    """
    The long options that send, matched as prefixes so ``--data-raw`` counts as
    ``--data``.
    """

    method_short: str
    """
    The single letter naming the request method, which reads when it is ``GET``.
    """

    method_long: tuple[str, ...]
    """
    The long options naming the request method.
    """

    def present_in(self, arguments: Sequence[str]) -> bool:
        """
        :param arguments: A call's arguments.
        :return: Whether one of them sends something.
        """
        for index, argument in enumerate(arguments):
            following = "".join(arguments[index + 1 : index + 2])
            if argument.startswith("--"):
                option, _, value = argument.partition("=")
                if option.startswith(self.long):
                    return True
                if option in self.method_long and (value or following).upper() != "GET":
                    return True
                continue
            if not argument.startswith("-"):
                continue
            letters = argument[1:]
            for position, letter in enumerate(letters):
                if letter == self.method_short:
                    method = letters[position + 1 :] or following
                    if method.upper() != "GET":
                        return True
                    break
                if letter in self.short:
                    return True
        return False


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

    def message(self) -> str:
        """:return: What the hook tells the model: the reason, and what to run instead."""
        instead = (
            f"Instead run `{self.instead}`."
            if self.instead
            else "No workflow command does this: ask the person running the tool."
        )
        return (
            f"github-workflow: {self.reason}. {instead} Read git directly, but write to "
            f"git and GitHub only through `{WorkflowCommand.command_line()}` "
            f"({', '.join(WorkflowCommand)}; --help for each)."
        )


class GitWrite(StrEnum):
    """
    The git subcommands that write and have a workflow command doing the same job.
    """

    PUSH = "push"
    """
    Publishing the branch.
    """

    COMMIT = "commit"
    """
    Recording changes.
    """

    ADD = "add"
    """
    Staging changes, which the workflow's commit does with the files it is given.
    """

    SWITCH = "switch"
    """
    Changing or creating the checked-out branch.
    """

    CHECKOUT = "checkout"
    """
    Changing or creating the checked-out branch, the older way.
    """

    BRANCH = "branch"
    """
    Creating a branch.
    """

    PULL = "pull"
    """
    Taking in GitHub's copy of the branch.
    """

    MERGE = "merge"
    """
    Taking in another branch, which for GitHub's copy is a sync.
    """

    CLONE = "clone"
    """
    Making a checkout of another repository.
    """

    @property
    def instead(self) -> str:
        """:return: The workflow command line doing the same job."""
        match self:
            case GitWrite.PUSH:
                return WorkflowCommand.command_line(WorkflowCommand.PUSH)
            case GitWrite.COMMIT | GitWrite.ADD:
                return WorkflowCommand.command_line(
                    WorkflowCommand.COMMIT, "-m", "<message>", "<paths>..."
                )
            case GitWrite.SWITCH | GitWrite.CHECKOUT:
                return (
                    WorkflowCommand.command_line(
                        WorkflowCommand.BRANCH, BranchSubcommand.SWITCH, "<branch>"
                    )
                    + " (or `branch start <name>` for a new one)"
                )
            case GitWrite.BRANCH:
                return WorkflowCommand.command_line(
                    WorkflowCommand.BRANCH, BranchSubcommand.START, "<name>"
                )
            case GitWrite.PULL | GitWrite.MERGE:
                return WorkflowCommand.command_line(WorkflowCommand.SYNC)
            case GitWrite.CLONE:
                return WorkflowCommand.command_line(
                    WorkflowCommand.CLONE, "<owner>/<name>"
                )


class PullRequestOpening(StrEnum):
    """
    The ways of opening a pull request directly, all done by the workflow's ``draft``.
    """

    CLI = "pr create"
    """
    ``gh pr create``.
    """

    TOOL = "create_pull_request"
    """
    The GitHub MCP tool.
    """

    @classproperty
    def instead(cls) -> str:
        """
        The workflow command line opening a draft pull request.
        """
        return WorkflowCommand.command_line(
            WorkflowCommand.DRAFT, "--title", "<title>", "--body-file", "<file>"
        )


class DescriptionRewriting(StrEnum):
    """
    The ways of rewriting a pull request directly, whose description the workflow's
    ``describe`` rewrites on a draft.
    """

    CLI = "pr edit"
    """
    ``gh pr edit``.
    """

    TOOL = "update_pull_request"
    """
    The GitHub MCP tool.
    """

    @classproperty
    def instead(cls) -> str:
        """
        The workflow command line rewriting a draft's description.
        """
        return WorkflowCommand.command_line(
            WorkflowCommand.DESCRIBE, "<number>", "--body-file", "<file>"
        )


# %% judging one program


class ProgramCheck(ABC):
    """
    Judges the calls of one program.
    """

    @abstractmethod
    def denial(self, arguments: Sequence[str]) -> Denial | None:
        """
        :param arguments: What follows the program's name.
        :return: Why the call is denied, ``None`` when it may run.
        """


@dataclass(frozen=True)
class GitCheck(ProgramCheck):
    """
    Lets git read, and denies every write.
    """

    def denial(self, arguments: Sequence[str]) -> Denial | None:
        index = 0
        while index < len(arguments) and arguments[index].startswith("-"):
            option = arguments[index]
            if option not in GitGlobalOption._value2member_map_:
                return Denial(f"git {option} is not an option the guard lets through")
            index += 2 if option == GitGlobalOption.DIRECTORY else 1
        if index >= len(arguments):
            return None
        subcommand, rest = arguments[index], arguments[index + 1 :]
        if GitProgramOption.present_in(subcommand, rest):
            return Denial(f"git {subcommand} with this option runs a program or writes")
        if subcommand == GitReading.GREP and any(
            argument.startswith(("-O", "--open-files-in-pager")) for argument in rest
        ):
            return Denial("git grep opening files runs a program")
        if subcommand in GitReading._value2member_map_:
            return None
        if subcommand in GitListing._value2member_map_:
            if GitListing(subcommand).reads(rest):
                return None
        reason = f"git {subcommand} writes, or is not a form the guard knows reads"
        if subcommand in GitWrite._value2member_map_:
            return Denial(reason, GitWrite(subcommand).instead)
        return Denial(reason)


@dataclass(frozen=True)
class GitHubCliCheck(ProgramCheck):
    """
    Lets ``gh`` read, and denies every write.
    """

    @classproperty
    def api_sending(cls) -> SendingOptions:
        """
        The options with which ``gh api`` sends something; a field alone makes it a
        ``POST``.
        """
        return SendingOptions(
            "fF", ("--field", "--raw-field", "--input"), "X", ("--method",)
        )

    def denial(self, arguments: Sequence[str]) -> Denial | None:
        words = [argument for argument in arguments if not argument.startswith("-")]
        if words[:1] == [GitHubCliSubcommand.API]:
            if self.api_sending.present_in(arguments[1:]):
                return Denial("gh api with a method, a field or an input writes")
            return None
        if words[:1] == [GitHubCliSubcommand.SEARCH]:
            return None
        if " ".join(words[:2]) in GitHubCliReading._value2member_map_:
            return None
        command = " ".join(words[:2])
        reason = f"gh {command} writes, or is not a command the guard knows reads"
        if command == PullRequestOpening.CLI:
            return Denial(reason, PullRequestOpening.instead)
        if command == DescriptionRewriting.CLI:
            return Denial(reason, DescriptionRewriting.instead)
        return Denial(reason)


@dataclass(frozen=True)
class HttpClientCheck(ProgramCheck):
    """
    Lets ``curl`` and ``wget`` read from GitHub, and denies sending anything to it.
    """

    sending: SendingOptions
    """
    The client's options that send something.
    """

    @classproperty
    def curl(cls) -> HttpClientCheck:
        """
        The check of ``curl``.
        """
        return cls(
            SendingOptions(
                "dFT",
                ("--data", "--json", "--form", "--upload-file"),
                "X",
                ("--request",),
            )
        )

    @classproperty
    def wget(cls) -> HttpClientCheck:
        """
        The check of ``wget``.
        """
        return cls(
            SendingOptions(
                "",
                ("--post-data", "--post-file", "--body-data", "--body-file"),
                "",
                ("--method",),
            )
        )

    def denial(self, arguments: Sequence[str]) -> Denial | None:
        reaches_github = any(
            host in argument for argument in arguments for host in GitHubHost
        )
        if reaches_github and self.sending.present_in(arguments):
            return Denial("sending to GitHub directly writes")
        return None


# %% judging a command line


@dataclass(frozen=True)
class SimpleCommand:
    """
    One simple command, split into words the way the shell runs it.
    """

    words: Sequence[str]
    """
    The command's words, shell syntax and variable assignments before its program
    included.
    """

    @property
    def program_start(self) -> int:
        """
        The position of the word naming the program run, past shell syntax, a defined
        function's name and variable assignments; the number of words when none runs.
        """
        index = 0
        while index < len(self.words):
            word = self.words[index]
            if word in (ShellKeyword.FOR, ShellKeyword.SELECT, ShellKeyword.CASE):
                return len(self.words)
            if word == ShellKeyword.FUNCTION:
                index += 2
                continue
            syntax = word in ShellKeyword._value2member_map_
            if not syntax and not CommandLine.assignment.fullmatch(word):
                return index
            index += 1
        return index

    @property
    def assignments(self) -> list[str]:
        """
        The variables assigned for the program, as ``NAME=value``.
        """
        return [
            word
            for word in self.words[: self.program_start]
            if CommandLine.assignment.fullmatch(word)
        ]

    @property
    def program(self) -> str:
        """
        The name of the program run, empty when none runs.
        """
        if self.program_start == len(self.words):
            return ""
        return PurePath(self.words[self.program_start]).name

    @property
    def arguments(self) -> list[str]:
        """
        What follows the program's name.
        """
        return list(self.words[self.program_start + 1 :])


@dataclass(frozen=True)
class CommandLine:
    """
    One Bash command line, split the way the shell runs it.
    """

    text: str
    """
    The command line.
    """

    @classproperty
    def assignment(cls) -> re.Pattern[str]:
        """
        A word assigning an environment variable, as ``NAME=value``.
        """
        return re.compile(r"[A-Za-z_][A-Za-z0-9_]*=.*", re.DOTALL)

    @classproperty
    def here_document(cls) -> re.Pattern[str]:
        """
        The start of a here-document, capturing the word that ends it; a here-string
        (``<<<``) is not one.
        """
        return re.compile(r"(?<!<)<<(?!<)-?\s*\\?['\"]?([A-Za-z_][A-Za-z0-9_]*)['\"]?")

    @classproperty
    def shell_reading_input(cls) -> re.Pattern[str]:
        """
        A shell started without a command line, which runs what its input holds.
        """
        return re.compile(
            r"(^|[;&|(]\s*|\s)(bash|sh|zsh)(\s+-[A-Za-z]+)*\s*($|[<|;&)])"
        )

    def simple_commands(self) -> list[list[str]]:
        """
        :return: The words of every simple command the line runs, those in command
            substitutions included. A here-document is data unless a shell reads it.
        :raises ValueError: If its quotes do not balance.
        """
        text = self._without_here_documents()
        nested = re.findall(r"\$\(([^()]*)\)|<\(([^()]*)\)|`([^`]*)`", text)
        commands = [
            command
            for groups in nested
            for inner in groups
            if inner
            for command in CommandLine(inner).simple_commands()
        ]
        lexer = shlex.shlex(
            text.replace("\n", " ; "), posix=True, punctuation_chars=True
        )
        lexer.whitespace_split = True
        current: list[str] = []
        for word in lexer:
            if word and set(word) <= set(";&|()<>"):
                commands.append(current)
                current = []
                continue
            current.append(word)
        commands.append(current)
        return [command for command in commands if command]

    def runs_input_through_a_shell(self) -> bool:
        """
        :return: Whether a shell runs whatever reaches its input, which the guard
            cannot see.
        """
        return bool(self.shell_reading_input.search(self.text))

    def _without_here_documents(self) -> str:
        """
        :return: The line with the body of every here-document no shell reads removed.
        """
        kept = []
        ending: str | None = None
        for line in self.text.split("\n"):
            if ending is not None:
                if line.strip() == ending:
                    ending = None
                continue
            kept.append(line)
            opened = self.here_document.search(line)
            if opened and not self.shell_reading_input.search(line):
                ending = opened.group(1)
        return "\n".join(kept)


@dataclass(frozen=True)
class CommandGuard:
    """
    Judges whole command lines, looking through wrappers and shells into the programs
    they run.
    """

    def denial(self, command_line: str) -> Denial | None:
        """
        :param command_line: A Bash command line.
        :return: Why it is denied, ``None`` when it may run.
        """
        line = CommandLine(command_line)
        mentions_git = re.search(r"\b(git|gh)\b", command_line)
        if line.runs_input_through_a_shell() and mentions_git:
            return Denial("a shell reading its input could run git or gh unseen")
        for words in line.simple_commands():
            if mentions_git and "$" in SimpleCommand(words).program:
                return Denial("a program named by an expansion could be git or gh")
            reason = self.denial_of(words)
            if reason is not None:
                return reason
        return None

    def denial_of(self, words: Sequence[str]) -> Denial | None:
        """
        :param words: One simple command's words.
        :return: Why it is denied, ``None`` when it may run.
        """
        command = SimpleCommand(words)
        program, arguments = command.program, command.arguments
        if any(assignment.startswith("GIT_") for assignment in command.assignments):
            return Denial("setting git's environment can make it run a program")
        if not program:
            return None
        if program in VariableExport._value2member_map_ and any(
            argument.startswith("GIT_") for argument in arguments
        ):
            return Denial("exporting git's environment can make it run a program")
        if program in Wrapper._value2member_map_:
            return self._denial_of_wrapped(Wrapper(program), arguments)
        if program in Shell._value2member_map_:
            return self._denial_of_shell(Shell(program), arguments)
        match program:
            case Program.GIT:
                return GitCheck().denial(arguments)
            case Program.GITHUB_CLI:
                return GitHubCliCheck().denial(arguments)
            case Program.CURL:
                return HttpClientCheck.curl.denial(arguments)
            case Program.WGET:
                return HttpClientCheck.wget.denial(arguments)
        return None

    def _denial_of_wrapped(
        self, wrapper: Wrapper, arguments: list[str]
    ) -> Denial | None:
        """
        :param wrapper: The wrapper.
        :param arguments: Its arguments, its options and the command it runs.
        :return: Why the command it runs is denied, ``None`` when it may run.
        """
        judged = {*Program, *Shell, *Wrapper}
        for index, argument in enumerate(arguments):
            if " " in argument:
                reason = self.denial(argument)
                if reason is not None:
                    return reason
            if argument.startswith("GIT_") and CommandLine.assignment.fullmatch(
                argument
            ):
                return Denial("setting git's environment can make it run a program")
            program = PurePath(argument).name
            if wrapper is Wrapper.XARGS and program in Program._value2member_map_:
                return Denial(f"xargs gives {program} arguments the guard cannot see")
            if program in judged:
                return self.denial_of(arguments[index:])
        return None

    def _denial_of_shell(self, shell: Shell, arguments: list[str]) -> Denial | None:
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
class ToolGuard:
    """
    The hook's decision over one tool call.
    """

    hook_input: dict[str, Any]
    """
    The hook's input, as Claude Code sends it.
    """

    def denial(self) -> Denial | None:
        """
        :return: Why the call is denied, ``None`` when it may run.
        """
        tool = self.hook_input.get(HookKey.TOOL_NAME, "")
        if tool in FileWritingTool._value2member_map_:
            path = PurePath(self.hook_input[HookKey.TOOL_INPUT][HookKey.FILE_PATH])
            if GitConfigurationLocation.holds(path):
                return Denial(f"git runs programs that {path} names")
            return None
        if tool == HookValue.BASH_TOOL:
            command = self.hook_input[HookKey.TOOL_INPUT][HookKey.COMMAND]
            return CommandGuard().denial(command)
        if tool.startswith(HookValue.MCP_TOOL_PREFIX) and "github" in tool.casefold():
            name = tool.rsplit("__", 1)[-1]
            reading = (
                GitHubToolReading.GET,
                GitHubToolReading.LIST,
                GitHubToolReading.SEARCH,
            )
            if name.startswith(reading) or name.endswith(GitHubToolReading.READ):
                return None
            reason = f"the GitHub tool {name} writes"
            if name == PullRequestOpening.TOOL:
                return Denial(reason, PullRequestOpening.instead)
            if name == DescriptionRewriting.TOOL:
                return Denial(reason, DescriptionRewriting.instead)
            return Denial(reason)
        return None

    def output(self) -> dict[str, Any] | None:
        """
        :return: The hook's output denying the call, ``None`` to leave it to the usual
            permissions.
        """
        denial = self.denial()
        if denial is None:
            return None
        return {
            HookKey.HOOK_SPECIFIC_OUTPUT: {
                HookKey.HOOK_EVENT_NAME: HookValue.PRE_TOOL_USE,
                HookKey.PERMISSION_DECISION: HookValue.DENY,
                HookKey.PERMISSION_DECISION_REASON: denial.message(),
            }
        }


# %% entry point


def main() -> None:
    """
    Read the hook's input and print its decision.
    """
    output = ToolGuard(json.load(sys.stdin)).output()
    if output is not None:
        print(json.dumps(output))


if __name__ == "__main__":
    main()
