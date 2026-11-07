"""
The guard every tool call passes before it runs, as a Claude Code ``PreToolUse`` hook:
it denies writing to git or GitHub directly, so every write goes through the workflow's
commands, and prints nothing for a call it leaves to the usual permissions.

Usage: ``python -m github_workflow.guard < hook-input.json``
"""

from __future__ import annotations

import json
import re
import shlex
import sys
from abc import ABC, abstractmethod
from collections.abc import Sequence
from dataclasses import dataclass, replace
from enum import Enum, StrEnum
from http import HTTPMethod
from pathlib import PurePath
from typing import Any

import github_workflow
from github_workflow.coarse_guard import GitConfigurationLocation, Program
from github_workflow.command_line import (
    CommandAuthority,
    CommandOption,
    RefusalAdvice,
    RunnableCommand,
)
from github_workflow.hooks import HookInput, Speaker, ToolCallDenial, ToolKind
from github_workflow.install import Launcher

# %% the session


class SessionVariable(StrEnum):
    """
    The variable Claude Code sets for every command it runs.
    """

    COMMAND_MARKER = "CLAUDECODE"
    """
    Marks a command as run from a Claude Code session; the push hook checks only those.
    """


# %% programs


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
    """
    Exports a variable.
    """

    DECLARE = "declare"
    """
    Declares a variable, exported with ``-x``.
    """

    TYPESET = "typeset"
    """
    Declares a variable, the Korn shell's spelling of ``declare``.
    """


class VariableRemoval(StrEnum):
    """
    The shell builtins that remove a variable from the environment of every program run
    after them.
    """

    UNSET = "unset"
    """
    Removes a variable.
    """


class EnvironmentOption(StrEnum):
    """
    The options of ``env`` that the guard reads before the command it runs.
    """

    IGNORE_ENVIRONMENT = "-i"
    """
    Runs the command with no variables at all.
    """

    IGNORE_ENVIRONMENT_LONG = "--ignore-environment"
    """
    Runs the command with no variables at all.
    """

    EMPTY_ENVIRONMENT = "-"
    """
    Runs the command with no variables at all, the older way.
    """

    UNSET = "-u"
    """
    Removes the variable it is followed by.
    """

    UNSET_LONG = "--unset"
    """
    Removes the variable it is followed by.
    """

    DIRECTORY = "-C"
    """
    Runs the command in the directory it is followed by.
    """

    DIRECTORY_LONG = "--chdir"
    """
    Runs the command in the directory it is followed by.
    """

    @property
    def drops_every_variable(self) -> bool:
        """:return: Whether the command runs with no variables at all."""
        return self in (
            EnvironmentOption.IGNORE_ENVIRONMENT,
            EnvironmentOption.IGNORE_ENVIRONMENT_LONG,
            EnvironmentOption.EMPTY_ENVIRONMENT,
        )

    @property
    def takes_value(self) -> bool:
        """:return: Whether the option is followed by a value of its own."""
        return self in (
            EnvironmentOption.UNSET,
            EnvironmentOption.UNSET_LONG,
            EnvironmentOption.DIRECTORY,
            EnvironmentOption.DIRECTORY_LONG,
        )


class ShellKeyword(StrEnum):
    """
    The words the shell reads as syntax where a command's program would stand.
    """

    IF = "if"
    """
    Opens a conditional, whose condition runs as a command.
    """

    THEN = "then"
    """
    Opens what a condition that held runs.
    """

    ELIF = "elif"
    """
    Opens a further condition.
    """

    ELSE = "else"
    """
    Opens what runs when no condition held.
    """

    FI = "fi"
    """
    Closes a conditional.
    """

    WHILE = "while"
    """
    Opens a loop running while its condition holds.
    """

    UNTIL = "until"
    """
    Opens a loop running until its condition holds.
    """

    DO = "do"
    """
    Opens a loop's body.
    """

    DONE = "done"
    """
    Closes a loop.
    """

    OPENING_BRACE = "{"
    """
    Opens a group of commands run in the current shell.
    """

    CLOSING_BRACE = "}"
    """
    Closes a group of commands.
    """

    NEGATION = "!"
    """
    Negates the status of the command after it.
    """

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

    @classmethod
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
            if argument.partition("=")[0] in cls:
                return True
            short = argument.startswith("-") and not argument.startswith("--")
            if short and subcommand in remote and cls.short_letter() in argument:
                return True
        return False


class GitReading(StrEnum):
    """
    The git subcommands that only read, whatever their arguments: they move no
    reference and leave the index and the working files alone. ``merge-tree`` may store
    the merged files as objects nothing refers to, which ``git gc`` removes.
    """

    STATUS = "status"
    """
    Shows the working tree's state.
    """

    DIFF = "diff"
    """
    Shows changes.
    """

    LOG = "log"
    """
    Shows commits.
    """

    SHOW = "show"
    """
    Shows objects.
    """

    BLAME = "blame"
    """
    Shows who last changed each line.
    """

    GREP = "grep"
    """
    Searches tracked files.
    """

    REV_PARSE = "rev-parse"
    """
    Resolves references and git's paths.
    """

    REV_LIST = "rev-list"
    """
    Lists commits.
    """

    LS_FILES = "ls-files"
    """
    Lists the index's files.
    """

    LS_TREE = "ls-tree"
    """
    Lists a tree's files.
    """

    LS_REMOTE = "ls-remote"
    """
    Lists a remote's references.
    """

    CAT_FILE = "cat-file"
    """
    Prints objects.
    """

    MERGE_BASE = "merge-base"
    """
    Finds common ancestors.
    """

    MERGE_TREE = "merge-tree"
    """
    Merges without touching a branch, the index or the working tree.
    """

    DESCRIBE = "describe"
    """
    Names a commit after the nearest tag.
    """

    SHORTLOG = "shortlog"
    """
    Summarizes commits by author.
    """

    FOR_EACH_REF = "for-each-ref"
    """
    Lists references.
    """

    SHOW_REF = "show-ref"
    """
    Lists references and their commits.
    """

    NAME_REV = "name-rev"
    """
    Names a commit after the references reaching it.
    """

    CHECK_IGNORE = "check-ignore"
    """
    Says why a path is ignored.
    """

    VAR = "var"
    """
    Prints git's logical variables, such as the author's identity.
    """

    VERSION = "version"
    """
    Prints git's version.
    """

    HELP = "help"
    """
    Prints git's help.
    """


class ReadingFetch(StrEnum):
    """
    The starts of the ``fetch`` arguments holding a colon that only read.
    """

    HTTPS = "https://"
    """
    A repository's URL over HTTPS, a transport that runs no program.
    """

    REMOTE_TRACKING = "refs/remotes/"
    """
    Where a refspec stores what it fetches when it moves only a remote-tracking
    reference, never a local branch.
    """

    @classmethod
    def reads(cls, argument: str) -> bool:
        """
        :param argument: A ``fetch`` argument holding a colon: a URL or a refspec.
        :return: Whether it only reads.
        """
        if argument.startswith(cls.HTTPS):
            return True
        _, _, destination = argument.removeprefix("+").partition(":")
        return destination.startswith(cls.REMOTE_TRACKING)


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
    Reads when it gets or lists values, or names a single key without a value.
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
    Reads from a remote or an HTTPS URL, moving only remote-tracking references,
    unless a refspec names a local branch or the URL another transport.
    """

    ARCHIVE = "archive"
    """
    Reads a commit's files into an archive, unless it asks another repository for them
    or writes the archive where git reads its configuration or hooks.
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
                names_one_key = len(positional) == 1 and "." in positional[0]
                return (gets or names_one_key) and not options & setting
            case GitListing.STASH:
                return positional[:1] in (["list"], ["show"])
            case GitListing.WORKTREE:
                return positional[:1] == ["list"]
            case GitListing.REFLOG:
                return positional[:1] in ([], ["show"])
            case GitListing.SUBMODULE:
                return positional[:1] == ["status"]
            case GitListing.FETCH:
                return all(
                    ReadingFetch.reads(argument)
                    for argument in positional
                    if ":" in argument
                )
            case GitListing.ARCHIVE:
                return not any(
                    argument.startswith("--remote") for argument in options
                ) and not any(
                    GitConfigurationLocation.holds(PurePath(path))
                    for path in self._archive_files(arguments)
                )

    @staticmethod
    def _archive_files(arguments: Sequence[str]) -> list[str]:
        """
        :param arguments: What follows ``archive``.
        :return: The files ``-o`` writes the archive to.
        """
        files = []
        for index, argument in enumerate(arguments):
            if argument == "-o" and index + 1 < len(arguments):
                files.append(arguments[index + 1])
            elif argument.startswith("-o") and argument != "-o":
                files.append(argument.removeprefix("-o"))
        return files

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
    """
    Shows a pull request.
    """

    PULL_REQUEST_LIST = "pr list"
    """
    Lists pull requests.
    """

    PULL_REQUEST_DIFF = "pr diff"
    """
    Shows a pull request's changes.
    """

    PULL_REQUEST_CHECKS = "pr checks"
    """
    Shows a pull request's checks.
    """

    PULL_REQUEST_STATUS = "pr status"
    """
    Shows the pull requests relevant to the signed-in account.
    """

    ISSUE_VIEW = "issue view"
    """
    Shows an issue.
    """

    ISSUE_LIST = "issue list"
    """
    Lists issues.
    """

    ISSUE_STATUS = "issue status"
    """
    Shows the issues relevant to the signed-in account.
    """

    RUN_VIEW = "run view"
    """
    Shows an Actions run.
    """

    RUN_LIST = "run list"
    """
    Lists Actions runs.
    """

    RUN_WATCH = "run watch"
    """
    Follows an Actions run until it ends.
    """

    REPOSITORY_VIEW = "repo view"
    """
    Shows a repository.
    """

    RELEASE_VIEW = "release view"
    """
    Shows a release.
    """

    RELEASE_LIST = "release list"
    """
    Lists releases.
    """

    WORKFLOW_VIEW = "workflow view"
    """
    Shows an Actions workflow.
    """

    WORKFLOW_LIST = "workflow list"
    """
    Lists Actions workflows.
    """

    AUTHENTICATION_STATUS = "auth status"
    """
    Shows which account gh is signed in as.
    """


class GitHubCliSubcommand(StrEnum):
    """
    The ``gh`` subcommands judged by their arguments rather than their name.
    """

    API = "api"
    """
    A raw API call, which reads unless given a method, a field or an input, or, to
    GraphQL, a document holding anything but queries.
    """

    SEARCH = "search"
    """
    A search, which only reads.
    """


class GraphQLOperation(StrEnum):
    """
    The kinds of operation a GraphQL document holds.
    """

    QUERY = "query"
    """
    Reads.
    """

    MUTATION = "mutation"
    """
    Writes.
    """

    SUBSCRIPTION = "subscription"
    """
    Waits for changes; not a read the guard lets through.
    """


@dataclass(frozen=True)
class GraphQLCall:
    """
    A ``gh api graphql`` call, which sends its document as the field ``query``.
    """

    options: Sequence[str]
    """
    What follows ``graphql``.
    """

    @classmethod
    def endpoint(cls) -> str:
        """
        The endpoint ``gh api`` sends GraphQL documents to.
        """
        return "graphql"

    @classmethod
    def field_options(cls) -> tuple[str, ...]:
        """
        The options each naming one field as ``name=value``.
        """
        return ("-f", "-F", "--field", "--raw-field")

    @classmethod
    def shaping_options(cls) -> tuple[str, ...]:
        """
        The options taking a value that only shape what is printed or how it is asked
        for, never what is sent.
        """
        return ("--jq", "-q", "--template", "-t", "--cache", "--header", "-H")

    @classmethod
    def shaping_flags(cls) -> tuple[str, ...]:
        """
        The options without a value that only shape what is printed.
        """
        return ("--paginate", "--slurp", "--silent", "--include", "-i", "--verbose")

    def fields(self) -> dict[str, str] | None:
        """
        :return: Every field sent, by name; ``None`` when an option is neither a field
            nor one only shaping the output.
        """
        fields: dict[str, str] = {}
        options = list(self.options)
        while options:
            option = options.pop(0)
            if option in self.shaping_flags():
                continue
            if option in self.shaping_options() and options:
                options.pop(0)
                continue
            if option.startswith(
                tuple(f"{shaping}=" for shaping in self.shaping_options())
            ):
                continue
            if option in self.field_options() and options:
                given = options.pop(0)
            elif option.startswith(("-f", "-F")) and len(option) > 2:
                given = option[2:]
            elif option.startswith(("--field=", "--raw-field=")):
                given = option.partition("=")[2]
            else:
                return None
            name, _, value = given.partition("=")
            fields[name] = value
        return fields

    def reads(self) -> bool:
        """
        :return: Whether every option is a field and the document, given in place
            rather than read from a file, holds queries alone.
        """
        fields = self.fields()
        if fields is None:
            return False
        document = fields.get(GraphQLOperation.QUERY, "")
        if not document or document.startswith("@"):
            return False
        words = set(re.findall(r"[A-Za-z_]+", document))
        written = {GraphQLOperation.MUTATION, GraphQLOperation.SUBSCRIPTION}
        return not words & written and document.lstrip().startswith(
            ("{", GraphQLOperation.QUERY)
        )


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
    How the names of GitHub MCP tools that only read start.
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

    @classmethod
    def names_a_read(cls, name: str) -> bool:
        """
        :param name: A GitHub MCP tool's name, without its server's prefix.
        :return: Whether the tool only reads.
        """
        return name.startswith(tuple(cls)) or name.endswith(
            tuple(GitHubToolReadingEnding)
        )


class GitHubToolReadingEnding(StrEnum):
    """
    How the names of GitHub MCP tools that only read end, in the newer tool names,
    which name the thing first and what they do with it last.
    """

    READ = "_read"
    """
    Reads, such as ``pull_request_read``.
    """

    LIST = "_list"
    """
    Lists things, such as ``actions_list``.
    """

    GET = "_get"
    """
    Reads one thing, such as ``actions_get``.
    """


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

    def named_method(self, arguments: Sequence[str]) -> str | None:
        """
        :param arguments: A call's arguments.
        :return: The request method an option of its own names, in upper case;
            ``None`` when none does, or only within a cluster of short options.
        """
        for index, argument in enumerate(arguments):
            following = "".join(arguments[index + 1 : index + 2])
            option, _, value = argument.partition("=")
            if option in self.method_long:
                return (value or following).upper()
            short = f"-{self.method_short}"
            if self.method_short and argument.startswith(short):
                return (argument.removeprefix(short) or following).upper()
        return None


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
                return RunnableCommand.PUSH.usage()
            case GitWrite.COMMIT | GitWrite.ADD:
                return RunnableCommand.COMMIT.usage(CommandOption.MESSAGE, "paths")
            case GitWrite.SWITCH | GitWrite.CHECKOUT:
                start = RunnableCommand.BRANCH_START.usage("name")
                switch = RunnableCommand.BRANCH_SWITCH.usage("name")
                return f"{switch}`, or for a new one `{start}"
            case GitWrite.BRANCH:
                return RunnableCommand.BRANCH_START.usage("name")
            case GitWrite.PULL:
                return RunnableCommand.SYNC.usage()
            case GitWrite.MERGE:
                base = RunnableCommand.SYNC.usage(CommandOption.BASE)
                stacked = RunnableCommand.SYNC.usage(CommandOption.ON)
                return f"{base}`, or for another open pull request's branch `{stacked}"
            case GitWrite.CLONE:
                clone = RunnableCommand.CLONE.usage("repository")
                return (
                    f"{clone}`; to review a pull request, then run in the clone `git "
                    f"fetch origin +refs/pull/<number>/head:refs/remotes/pull/<number>"
                )


class PullRequestWrite(Enum):
    """
    The jobs of writing a pull request directly, each done by a workflow command, with
    the ``gh`` command and the GitHub MCP tool doing it.
    """

    OPENING = ("pr create", "create_pull_request")
    """
    Opening one, which the workflow's ``draft`` does.
    """

    REWRITING = ("pr edit", "update_pull_request")
    """
    Rewriting one, whose description and title the workflow's ``describe`` rewrites
    on an open pull request.
    """

    def __init__(self, cli: str, tool: str) -> None:
        """
        :param cli: The ``gh`` command doing it, by its first two words.
        :param tool: The GitHub MCP tool doing it.
        """
        self.cli = cli
        self.tool = tool

    @property
    def instead(self) -> str:
        """:return: The workflow command line doing the job."""
        match self:
            case PullRequestWrite.OPENING:
                return RunnableCommand.DRAFT.usage(
                    CommandOption.TITLE, CommandOption.BODY_FILE
                )
            case PullRequestWrite.REWRITING:
                return RunnableCommand.DESCRIBE.usage(
                    "number", optional=(CommandOption.BODY_FILE, CommandOption.TITLE)
                )

    @classmethod
    def denial(cls, reason: str, cli: str = "", tool: str = "") -> Denial:
        """
        :param reason: Why a call is denied.
        :param cli: The ``gh`` command it runs, by its first two words, if any.
        :param tool: The GitHub MCP tool it calls, if any.
        :return: The denial, naming the workflow command doing the job when one does.
        """
        job = next(
            (job for job in cls if (cli and job.cli == cli) or job.tool == tool), None
        )
        return Denial(reason, None if job is None else job.instead)


class OwnPullRequestTool(StrEnum):
    """
    The GitHub MCP tools writing to a pull request's labels or review threads, which the
    workflow's commands write on the work branch's own pull request.
    """

    LABELS = "issue_write"
    """
    Writes an issue or pull request, its labels among it.
    """

    REPLY = "add_reply_to_pull_request_comment"
    """
    Replies in a review thread.
    """

    RESOLVE = "resolve_review_thread"
    """
    Resolves a review thread.
    """

    def instead(self) -> str:
        """
        :return: The workflow command line doing the same on the work branch's own
            pull request.
        """
        match self:
            case OwnPullRequestTool.LABELS:
                return RunnableCommand.LABEL.usage(
                    CommandOption.ADD, CommandOption.REMOVE
                )
            case OwnPullRequestTool.REPLY:
                return RunnableCommand.REVIEW_REPLY.usage(
                    "comment", CommandOption.BODY_FILE
                )
            case OwnPullRequestTool.RESOLVE:
                return RunnableCommand.REVIEW_RESOLVE.usage("comment")


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
            if option not in GitGlobalOption:
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
        if subcommand in GitReading:
            return None
        if subcommand in GitListing:
            if GitListing(subcommand).reads(rest):
                return None
        reason = f"git {subcommand} writes, or is not a form the guard knows reads"
        if subcommand in GitWrite:
            return Denial(reason, GitWrite(subcommand).instead)
        return Denial(reason)


@dataclass(frozen=True)
class GitHubCliCheck(ProgramCheck):
    """
    Lets ``gh`` read, and denies every write.
    """

    @classmethod
    def api_sending(cls) -> SendingOptions:
        """
        The options with which ``gh api`` sends something; a field alone makes it a
        ``POST``.
        """
        return SendingOptions(
            "fF", ("--field", "--raw-field", "--input"), "X", ("--method",)
        )

    @classmethod
    def api_input(cls) -> str:
        """
        The option sending a file as the request's body, whatever the method.
        """
        return "--input"

    def denial(self, arguments: Sequence[str]) -> Denial | None:
        words = [argument for argument in arguments if not argument.startswith("-")]
        if words[:1] == [GitHubCliSubcommand.API]:
            options = arguments[1:]
            if options[:1] == [GraphQLCall.endpoint()]:
                if GraphQLCall(options[1:]).reads():
                    return None
                return Denial(
                    "gh api graphql with a mutation, or a document the guard cannot read, writes"
                )
            queries = self.api_sending().named_method(
                options
            ) == HTTPMethod.GET and not any(
                argument.startswith(self.api_input()) for argument in options
            )
            if self.api_sending().present_in(options) and not queries:
                return Denial("gh api with a method, a field or an input writes")
            return None
        if words[:1] == [GitHubCliSubcommand.SEARCH]:
            return None
        if " ".join(words[:2]) in GitHubCliReading:
            return None
        command = " ".join(words[:2])
        reason = f"gh {command} writes, or is not a command the guard knows reads"
        return PullRequestWrite.denial(reason, cli=command)


@dataclass(frozen=True)
class HttpClientCheck(ProgramCheck):
    """
    Lets ``curl`` and ``wget`` read from GitHub, and denies sending anything to it.
    """

    sending: SendingOptions
    """
    The client's options that send something.
    """

    @classmethod
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

    @classmethod
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
            syntax = word in ShellKeyword
            if not syntax and not CommandLine.assignment().fullmatch(word):
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
            if CommandLine.assignment().fullmatch(word)
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

    def workflow_words(self) -> list[str] | None:
        """
        :return: The words this gives ``python -m github_workflow``, or the launcher,
            options left out, ``None`` when it runs neither.
        """
        arguments = self.arguments
        if self.program == Launcher.COMMAND:
            given = arguments
        elif self.program.startswith("python") and "-m" in arguments[:-1]:
            module = arguments.index("-m") + 1
            if arguments[module] != github_workflow.__name__:
                return None
            given = arguments[module + 1 :]
        else:
            return None
        return [word for word in given if not word.startswith("-")]

    def runs_workflow(self, command: RunnableCommand) -> bool:
        """
        :param command: A workflow command.
        :return: Whether this runs it with ``python -m github_workflow``, or the
            launcher.
        """
        words = self.workflow_words()
        return words is not None and RunnableCommand.run_by(words) is command


class Redirection(StrEnum):
    """
    An operator sending a command's input or output elsewhere; the word after it is
    where, and never part of the command.
    """

    OUTPUT = ">"
    """
    Writes the output to a file.
    """

    APPENDED_OUTPUT = ">>"
    """
    Appends the output to a file.
    """

    FORCED_OUTPUT = ">|"
    """
    Writes the output to a file, even one the shell keeps from being overwritten.
    """

    DUPLICATED_OUTPUT = ">&"
    """
    Sends the output where another file descriptor goes.
    """

    INPUT = "<"
    """
    Reads the input from a file.
    """

    DUPLICATED_INPUT = "<&"
    """
    Reads the input from another file descriptor.
    """

    INPUT_AND_OUTPUT = "<>"
    """
    Opens a file for both.
    """

    HERE_DOCUMENT = "<<"
    """
    Reads the input from the lines up to the word after it.
    """

    HERE_STRING = "<<<"
    """
    Reads the input from the word after it.
    """

    BOTH_OUTPUTS = "&>"
    """
    Writes the output and the errors to a file.
    """

    BOTH_OUTPUTS_APPENDED = "&>>"
    """
    Appends the output and the errors to a file.
    """

    @property
    def takes_a_descriptor(self) -> bool:
        """
        Whether a file descriptor's number may be written right before it, as in
        ``2>``.
        """
        return self.value[0] in "<>"


@dataclass
class ShellInput:
    """
    A command line read one character at a time, which knows where its reading stands.
    """

    text: str
    """
    The command line.
    """

    position: int = 0
    """
    How many characters were read.
    """

    def read(self, size: int = 1) -> str:
        """
        :param size: How many characters to read.
        :return: The next ones.
        """
        start = self.position
        self.position = min(len(self.text), start + size)
        return self.text[start : self.position]

    def readline(self) -> str:
        """
        :return: The rest of the current line, its line break included.
        """
        end = self.text.find("\n", self.position)
        return self.read(len(self.text) - self.position if end < 0 else end + 1)

    def ends_in_a_descriptor(self, word: str) -> bool:
        """
        :param word: The word just read.
        :return: Whether it is a file descriptor's number, unquoted and standing alone,
            written right before the operator read after it.
        """
        before = self.text[: self.position - 1]
        if not word.isdigit() or self.text[self.position - 1] not in "<>":
            return False
        if not before.endswith(word):
            return False
        start = len(before) - len(word)
        return start == 0 or before[start - 1] in " \t;&|()"


@dataclass(frozen=True)
class CommandLine:
    """
    One Bash command line, split the way the shell runs it.
    """

    text: str
    """
    The command line.
    """

    @classmethod
    def assignment(cls) -> re.Pattern[str]:
        """
        A word assigning an environment variable, as ``NAME=value``.
        """
        return re.compile(r"[A-Za-z_][A-Za-z0-9_]*=.*", re.DOTALL)

    @classmethod
    def here_document(cls) -> re.Pattern[str]:
        """
        The start of a here-document, capturing the word that ends it; a here-string
        (``<<<``) is not one.
        """
        return re.compile(r"(?<!<)<<(?!<)-?\s*\\?['\"]?([A-Za-z_][A-Za-z0-9_]*)['\"]?")

    @classmethod
    def shell_reading_input(cls) -> re.Pattern[str]:
        """
        A shell started without a command line, which runs what its input holds.
        """
        return re.compile(
            r"(^|[;&|(]\s*|\s)(bash|sh|zsh)(\s+-[A-Za-z]+)*\s*($|[<|;&)])"
        )

    @classmethod
    def substitution(cls) -> re.Pattern[str]:
        """
        A command or process substitution, ``$(...)``, ``<(...)`` or a backtick pair,
        whose command is its one group that matched; a ``$`` or a backtick escaped by a
        backslash starts none, and a backtick escaped inside one does not end it but,
        unescaped as the shell does, starts one nested in its command.
        """
        unescaped = r"(?<!\\)(?:\\\\)*"
        return re.compile(
            rf"{unescaped}\$\(([^()]*)\)"
            r"|<\(([^()]*)\)"
            rf"|{unescaped}`((?:[^`\\]|\\.)*)`"
        )

    def simple_commands(self) -> list[list[str]]:
        """
        :return: The words of every simple command the line runs, those in command
            substitutions included, without their redirections. A here-document is data
            unless a shell reads it.
        :raises ValueError: If its quotes do not balance.
        """
        text = self._without_here_documents()
        nested = re.findall(self.substitution(), text)
        inner_lines = [
            inner
            for dollar, process, backtick in nested
            for inner in (dollar, process, re.sub(r"\\([`\\$])", r"\1", backtick))
            if inner
        ]
        commands = [
            command
            for inner in inner_lines
            for command in CommandLine(inner).simple_commands()
        ]
        read = ShellInput(text.replace("\n", " ; "))
        lexer = shlex.shlex(read, posix=True, punctuation_chars=True)
        lexer.whitespace_split = True
        current: list[str] = []
        descriptor_read = False
        target_follows = False
        for word in lexer:
            operator = word and set(word) <= set(";&|()<>")
            if target_follows and not operator:
                target_follows = False
                continue
            if word in list(Redirection):
                if descriptor_read and Redirection(word).takes_a_descriptor:
                    current.pop()
                descriptor_read = False
                target_follows = True
                continue
            target_follows = False
            if operator:
                commands.append(current)
                current = []
                descriptor_read = False
                continue
            current.append(word)
            descriptor_read = read.ends_in_a_descriptor(word)
        commands.append(current)
        return [command for command in commands if command]

    def runs_input_through_a_shell(self) -> bool:
        """
        :return: Whether a shell runs whatever reaches its input, which the guard
            cannot see.
        """
        return bool(self.shell_reading_input().search(self.text))

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
            opened = self.here_document().search(line)
            if opened and not self.shell_reading_input().search(line):
                ending = opened.group(1)
        return "\n".join(kept)


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

    @classmethod
    def marker_change(cls) -> Denial:
        """
        Why changing the variable marking a Claude Code session's commands is denied.
        """
        return Denial(
            f"changing {SessionVariable.COMMAND_MARKER} lets a push skip the "
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
        for words in line.simple_commands():
            person_only = next(
                (
                    command
                    for command in RunnableCommand
                    if command.authority is CommandAuthority.PERSON
                    and SimpleCommand(words).runs_workflow(command)
                ),
                None,
            )
            if person_only is not None:
                return Denial(
                    f"only the person runs `{' '.join(person_only.words)}`, never a "
                    f"Claude Code session: put its command line in the pull request's "
                    f"description for them to copy"
                )
            if mentions_git and "$" in SimpleCommand(words).program:
                return Denial(
                    "a program named by an expansion could be git or gh",
                    saw_write=False,
                )
            reason = judge.command_denial(words)
            if reason is not None:
                return reason
        return None

    def command_denial(self, words: Sequence[str]) -> Denial | None:
        """
        :param words: One simple command's words.
        :return: Why it is denied, ``None`` when it may run.
        """
        command = SimpleCommand(words)
        program, arguments = command.program, command.arguments
        if any(assignment.startswith("GIT_") for assignment in command.assignments):
            return Denial("setting git's environment can make it run a program")
        marker = SessionVariable.COMMAND_MARKER
        if any(
            assignment.partition("=")[0] == marker for assignment in command.assignments
        ):
            return self.marker_change()
        if not program:
            return None
        if program in VariableExport and any(
            argument.startswith("GIT_") for argument in arguments
        ):
            return Denial("exporting git's environment can make it run a program")
        changes_variables = program in VariableExport or program in VariableRemoval
        if changes_variables and any(
            argument.partition("=")[0] == marker for argument in arguments
        ):
            return self.marker_change()
        if program in Wrapper:
            return self._wrapped_denial(Wrapper(program), arguments)
        if program in Shell:
            return self._shell_denial(Shell(program), arguments)
        match program:
            case Program.GIT:
                return GitCheck().denial(arguments)
            case Program.GITHUB_CLI:
                return GitHubCliCheck().denial(arguments)
            case Program.CURL:
                return HttpClientCheck.curl().denial(arguments)
            case Program.WGET:
                return HttpClientCheck.wget().denial(arguments)
        return None

    def _wrapped_denial(self, wrapper: Wrapper, arguments: list[str]) -> Denial | None:
        """
        :param wrapper: The wrapper.
        :param arguments: Its arguments, its options and the command it runs.
        :return: Why the command it runs is denied, ``None`` when it may run.
        """
        if wrapper is Wrapper.ENV and self._drops_marker(arguments):
            return self.marker_change()
        judged = {*Program, *Shell, *Wrapper}
        for index, argument in enumerate(arguments):
            if " " in argument:
                reason = self.denial(argument)
                if reason is not None:
                    return reason
            if argument.startswith("GIT_") and CommandLine.assignment().fullmatch(
                argument
            ):
                return Denial("setting git's environment can make it run a program")
            names_program_by_expansion = (
                "$" in argument and not CommandLine.assignment().fullmatch(argument)
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
                return self.command_denial(arguments[index:])
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
            if SessionVariable.COMMAND_MARKER in argument:
                return True
            previous = arguments[index - 1] if index else ""
            is_value = previous in options and EnvironmentOption(previous).takes_value
            own = argument.startswith("-") or CommandLine.assignment().fullmatch(
                argument
            )
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
class ToolGuard:
    """
    The hook's decision over one tool call.
    """

    call: HookInput
    """
    The tool call.
    """

    def denial(self) -> Denial | None:
        """
        :return: Why the call is denied, ``None`` when it may run.
        """
        match self.call.kind:
            case ToolKind.FILE_WRITE:
                path = PurePath(self.call.file_path)
                if GitConfigurationLocation.holds(path):
                    return Denial(f"git runs programs that {path} names")
                return None
            case ToolKind.BASH:
                return CommandGuard().denial(self.call.command)
            case ToolKind.GITHUB:
                name = self.call.tool_without_server
                if GitHubToolReading.names_a_read(name):
                    return None
                reason = f"the GitHub tool {name} writes"
                if name in OwnPullRequestTool:
                    return Denial(reason, OwnPullRequestTool(name).instead())
                return PullRequestWrite.denial(reason, tool=name)
        return None

    def output(self) -> dict[str, Any] | None:
        """
        :return: The hook's output denying the call, ``None`` to leave it to the usual
            permissions.
        """
        denial = self.denial()
        if denial is None:
            return None
        shown = (
            None
            if denial.saw_write
            else Speaker.WORKFLOW.says(
                f"denied a command it cannot see into ({denial.reason}): "
                f"{self.call.command}"
            )
        )
        return ToolCallDenial(denial.message(), shown).answer()


# %% entry point


def main() -> None:
    """
    Read the hook's input and print its decision.
    """
    output = ToolGuard(HookInput.from_json(json.load(sys.stdin))).output()
    if output is not None:
        print(json.dumps(output))


if __name__ == "__main__":
    main()
