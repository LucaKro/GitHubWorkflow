"""
Which git calls only read: they move no reference, leave the index and the working files
alone and run no program of the caller's choosing.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Sequence
from dataclasses import dataclass
from enum import Enum, StrEnum, auto
from inspect import isabstract
from pathlib import PurePath

from domain_model.class_property import classproperty
from domain_model.git.exceptions import UnjudgedSubcommandError
from domain_model.git.remotes import (
    ReflogOption,
    ReflogReadingCommand,
    RemoteOption,
    RemoteReadingCommand,
)
from domain_model.git.revisions import FetchOption, ReferenceNamespace
from domain_model.git.subcommands import (
    GitGlobalOption,
    GitOption,
    GitSubcommand,
    SubcommandReading,
)
from domain_model.git.working_tree import BranchOption

# %% where git reads its configuration


class GitConfigurationLocation(StrEnum):
    """
    The names marking a file git reads its configuration or hooks from, and so runs the
    programs it names.
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


# %% options and subcommands


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
    def runs_program(cls, subcommand: str, arguments: Sequence[str]) -> bool:
        """
        :param subcommand: The git subcommand.
        :param arguments: What follows it.
        :return: Whether one of the arguments runs a program or writes a file.
        """
        remote = (GitSubcommand.LS_REMOTE, GitSubcommand.FETCH)
        for argument in arguments:
            if argument.partition("=")[0] in cls:
                return True
            short = argument.startswith("-") and not argument.startswith("--")
            if short and subcommand in remote and cls.short_letter in argument:
                return True
        return False


class ReadingFetch(StrEnum):
    """
    The starts of the ``fetch`` arguments holding a colon that only read.
    """

    HTTPS = "https://"
    """
    A repository's URL over HTTPS, a transport that runs no program.
    """

    @classmethod
    def reads(cls, argument: str) -> bool:
        """
        :param argument: A ``fetch`` argument holding a colon: a URL or a refspec.
        :return: Whether it only reads: an HTTPS URL, or a refspec storing what it
            fetches as a remote-tracking branch, never a local one.
        """
        if argument.startswith(cls.HTTPS):
            return True
        _, _, destination = argument.removeprefix("+").partition(":")
        return destination.startswith(ReferenceNamespace.REMOTE_TRACKING_BRANCHES)


# %% the options and commands only told apart here


class GrepOption(GitOption):
    """
    The options of ``git grep``.
    """

    OPEN_FILES_IN_PAGER = "--open-files-in-pager", False
    """
    Open the matching files in the given program.
    """

    OPEN_FILES_IN_PAGER_SHORT = "-O", False
    """
    Open the matching files in the given program, short form.
    """


class TagOption(GitOption):
    """
    The options of ``git tag``.
    """

    LIST = "--list", True
    """
    List the tags, those matching the patterns given when any is.
    """

    LIST_SHORT = "-l", True
    """
    List the tags, short form.
    """

    LINES = "-n", True
    """
    List each tag with the given number of lines of its message.
    """

    COLOR = "--color", True
    """
    Colour the list.
    """

    NO_COLOR = "--no-color", True
    """
    Leave the list uncoloured.
    """

    CONTAINS = "--contains", True
    """
    List only the tags whose history holds the given commit.
    """

    NO_CONTAINS = "--no-contains", True
    """
    List only the tags whose history lacks the given commit.
    """

    MERGED = "--merged", True
    """
    List only the tags the given commit's history holds.
    """

    NO_MERGED = "--no-merged", True
    """
    List only the tags the given commit's history lacks.
    """

    POINTS_AT = "--points-at", True
    """
    List only the tags at the given commit.
    """

    SORT = "--sort", True
    """
    Order the list by the given key.
    """

    FORMAT = "--format", True
    """
    Print each tag as the given format says.
    """


class ConfigOption(GitOption):
    """
    The options of ``git config``.
    """

    GET = "--get", True
    """
    Print the value of the key given.
    """

    GET_ALL = "--get-all", True
    """
    Print every value of the key given.
    """

    GET_REGEXP = "--get-regexp", True
    """
    Print every key matching the pattern given, with its values.
    """

    LIST = "--list", True
    """
    Print every key and value.
    """

    LIST_SHORT = "-l", True
    """
    Print every key and value, short form.
    """

    GLOBAL = "--global", True
    """
    Use the user's configuration file.
    """

    SYSTEM = "--system", True
    """
    Use the system's configuration file.
    """

    LOCAL = "--local", True
    """
    Use the repository's configuration file.
    """

    WORKTREE = "--worktree", True
    """
    Use the worktree's configuration file.
    """

    FILE = "--file", True
    """
    Use the configuration file given.
    """

    SHOW_ORIGIN = "--show-origin", True
    """
    Print which file each value comes from.
    """

    SHOW_SCOPE = "--show-scope", True
    """
    Print which scope each value comes from.
    """

    NAME_ONLY = "--name-only", True
    """
    Print the keys without their values.
    """

    NULL = "--null", True
    """
    End each value with a null character rather than a newline.
    """

    TYPE = "--type", True
    """
    Print each value as the type given, such as ``bool``.
    """

    DEFAULT = "--default", True
    """
    Print the value given when the key is not set.
    """


class StashOption(GitOption):
    """
    The options of ``git stash``.
    """

    PATCH = "--patch", True
    """
    Show a stash's changes in full.
    """

    PATCH_SHORT = "-p", True
    """
    Show a stash's changes in full, short form.
    """

    STAT = "--stat", True
    """
    Show how much each file of a stash changes.
    """

    NAME_ONLY = "--name-only", True
    """
    Show only the names of the files a stash changes.
    """


class WorktreeOption(GitOption):
    """
    The options of ``git worktree``.
    """

    PORCELAIN = "--porcelain", True
    """
    List in a form meant for programs.
    """

    VERBOSE = "--verbose", True
    """
    List each worktree with why it is locked or prunable.
    """

    VERBOSE_SHORT = "-v", True
    """
    List each worktree with why it is locked or prunable, short form.
    """


class SubmoduleOption(GitOption):
    """
    The options of ``git submodule``.
    """

    QUIET = "--quiet", True
    """
    Print only errors.
    """

    RECURSIVE = "--recursive", True
    """
    Report the submodules nested in submodules too.
    """

    CACHED = "--cached", True
    """
    Report the commit the superproject records rather than the one checked out.
    """


class ConfigReadingCommand(StrEnum):
    """
    The commands of ``git config`` that only read.
    """

    GET = "get"
    """
    Print the value of the key given.
    """

    LIST = "list"
    """
    Print every key and value.
    """


class StashReadingCommand(StrEnum):
    """
    The commands of ``git stash`` that only read.
    """

    LIST = "list"
    """
    List the stashes.
    """

    SHOW = "show"
    """
    Show a stash's changes.
    """


class WorktreeReadingCommand(StrEnum):
    """
    The commands of ``git worktree`` that only read.
    """

    LIST = "list"
    """
    List the worktrees.
    """


class SubmoduleReadingCommand(StrEnum):
    """
    The commands of ``git submodule`` that only read.
    """

    STATUS = "status"
    """
    Report each submodule's commit and whether it is checked out there.
    """


class ArchiveOption(GitOption):
    """
    The options of ``git archive``.
    """

    OUTPUT_SHORT = "-o", True
    """
    Write the archive to the file given; where is told apart by the form.
    """

    FORMAT = "--format", True
    """
    Pack the archive in the format given.
    """

    PREFIX = "--prefix", True
    """
    Put the prefix given before every path in the archive.
    """

    LIST = "--list", True
    """
    List the formats it can pack.
    """

    LIST_SHORT = "-l", True
    """
    List the formats it can pack, short form.
    """

    VERBOSE = "--verbose", True
    """
    Report each file packed.
    """

    VERBOSE_SHORT = "-v", True
    """
    Report each file packed, short form.
    """

    WORKTREE_ATTRIBUTES = "--worktree-attributes", True
    """
    Read the attributes of the working tree too.
    """


# %% the subcommands that read in some forms


@dataclass(frozen=True)
class GitSubcommandArguments:
    """
    What follows a git subcommand, split into its options and its other arguments.
    """

    arguments: Sequence[str]
    """
    Every argument, in order.
    """

    @property
    def options(self) -> set[str]:
        """:return: The arguments that are options."""
        return {argument for argument in self.arguments if argument.startswith("-")}

    @property
    def positional(self) -> list[str]:
        """:return: The other arguments, in order."""
        return [argument for argument in self.arguments if not argument.startswith("-")]


@dataclass(frozen=True)
class ReadingForms(ABC):
    """
    The forms of one git subcommand that only read: every option is one of its own
    marked as reading, and the form reads.
    """

    @classproperty
    @abstractmethod
    def subcommand(cls) -> GitSubcommand:
        """
        The subcommand whose forms this tells apart.
        """

    @classproperty
    @abstractmethod
    def options(cls) -> type[GitOption]:
        """
        The subcommand's options.
        """

    @abstractmethod
    def form_reads(self, arguments: GitSubcommandArguments) -> bool:
        """
        :param arguments: What follows the subcommand, its options all reading.
        :return: Whether this form only reads.
        """

    def reads(self, arguments: GitSubcommandArguments) -> bool:
        """
        :param arguments: What follows the subcommand.
        :return: Whether the call only reads.
        """
        return self.options.only_reading(arguments.options) and self.form_reads(
            arguments
        )

    @classmethod
    def judging(cls, subcommand: GitSubcommand) -> ReadingForms:
        """
        :param subcommand: A subcommand reading in some forms.
        :return: What tells its reading forms apart.
        :raises UnjudgedSubcommandError: If nothing tells them apart.
        """
        forms = [cls]
        for form in forms:
            forms += form.__subclasses__()
        judging = (
            form()
            for form in forms
            if not isabstract(form) and form.subcommand == subcommand
        )
        found = next(judging, None)
        if found is None:
            raise UnjudgedSubcommandError(subcommand)
        return found


@dataclass(frozen=True)
class ListingReadingForms(ReadingForms, ABC):
    """
    The reading forms of a subcommand that reads when it lists rather than creates,
    moves or deletes.
    """

    @classproperty
    @abstractmethod
    def pattern_options(cls) -> frozenset[GitOption]:
        """
        The options after which the other arguments are patterns or commits to list by,
        never a name to create.
        """

    def form_reads(self, arguments: GitSubcommandArguments) -> bool:
        options = {self.options.look_up(option) for option in arguments.options}
        return not arguments.positional or bool(options & self.pattern_options)


@dataclass(frozen=True)
class BranchReadingForms(ListingReadingForms):
    """
    branch, which reads when it lists branches.
    """

    @classproperty
    def subcommand(cls) -> GitSubcommand:
        return GitSubcommand.BRANCH

    @classproperty
    def options(cls) -> type[GitOption]:
        return BranchOption

    @classproperty
    def pattern_options(cls) -> frozenset[GitOption]:
        return frozenset(
            {
                BranchOption.LIST,
                BranchOption.LIST_SHORT,
                BranchOption.CONTAINS,
                BranchOption.NO_CONTAINS,
                BranchOption.MERGED,
                BranchOption.NO_MERGED,
                BranchOption.POINTS_AT,
                BranchOption.SORT,
                BranchOption.FORMAT,
                BranchOption.COLOR,
            }
        )


@dataclass(frozen=True)
class TagReadingForms(ListingReadingForms):
    """
    tag, which reads when it lists tags.
    """

    @classproperty
    def subcommand(cls) -> GitSubcommand:
        return GitSubcommand.TAG

    @classproperty
    def options(cls) -> type[GitOption]:
        return TagOption

    @classproperty
    def pattern_options(cls) -> frozenset[GitOption]:
        return frozenset(
            {
                TagOption.LIST,
                TagOption.LIST_SHORT,
                TagOption.CONTAINS,
                TagOption.NO_CONTAINS,
                TagOption.MERGED,
                TagOption.NO_MERGED,
                TagOption.POINTS_AT,
                TagOption.SORT,
                TagOption.FORMAT,
                TagOption.COLOR,
            }
        )


@dataclass(frozen=True)
class ConfigReadingForms(ReadingForms):
    """
    config, which reads when it gets or lists values, or names a single key without
    a value.
    """

    @classproperty
    def subcommand(cls) -> GitSubcommand:
        return GitSubcommand.CONFIG

    @classproperty
    def options(cls) -> type[GitOption]:
        return ConfigOption

    @classproperty
    def getting_options(cls) -> frozenset[GitOption]:
        """
        The options that get or list values rather than name where to look.
        """
        return frozenset(
            {
                ConfigOption.GET,
                ConfigOption.GET_ALL,
                ConfigOption.GET_REGEXP,
                ConfigOption.LIST,
                ConfigOption.LIST_SHORT,
            }
        )

    def form_reads(self, arguments: GitSubcommandArguments) -> bool:
        positional = arguments.positional
        options = {self.options.look_up(option) for option in arguments.options}
        first = positional[0] if positional else None
        gets = bool(options & self.getting_options) or first in ConfigReadingCommand
        return gets or (len(positional) == 1 and "." in positional[0])


@dataclass(frozen=True)
class FirstWordReadingForms(ReadingForms, ABC):
    """
    The reading forms of a subcommand that reads when its first other argument names
    one of its reading commands, or, for some, when it has none.
    """

    @classproperty
    @abstractmethod
    def reading_commands(cls) -> type[StrEnum]:
        """
        The commands of the subcommand that only read.
        """

    @classproperty
    @abstractmethod
    def bare_reads(cls) -> bool:
        """
        Whether the subcommand reads when given no other argument.
        """

    def form_reads(self, arguments: GitSubcommandArguments) -> bool:
        if not arguments.positional:
            return self.bare_reads
        return arguments.positional[0] in self.reading_commands


@dataclass(frozen=True)
class RemoteReadingForms(FirstWordReadingForms):
    """
    remote, which reads when it lists remotes or shows one.
    """

    @classproperty
    def subcommand(cls) -> GitSubcommand:
        return GitSubcommand.REMOTE

    @classproperty
    def options(cls) -> type[GitOption]:
        return RemoteOption

    @classproperty
    def reading_commands(cls) -> type[StrEnum]:
        return RemoteReadingCommand

    @classproperty
    def bare_reads(cls) -> bool:
        return True


@dataclass(frozen=True)
class StashReadingForms(FirstWordReadingForms):
    """
    stash, which reads when it lists or shows stashes.
    """

    @classproperty
    def subcommand(cls) -> GitSubcommand:
        return GitSubcommand.STASH

    @classproperty
    def options(cls) -> type[GitOption]:
        return StashOption

    @classproperty
    def reading_commands(cls) -> type[StrEnum]:
        return StashReadingCommand

    @classproperty
    def bare_reads(cls) -> bool:
        return False


@dataclass(frozen=True)
class WorktreeReadingForms(FirstWordReadingForms):
    """
    worktree, which reads when it lists worktrees.
    """

    @classproperty
    def subcommand(cls) -> GitSubcommand:
        return GitSubcommand.WORKTREE

    @classproperty
    def options(cls) -> type[GitOption]:
        return WorktreeOption

    @classproperty
    def reading_commands(cls) -> type[StrEnum]:
        return WorktreeReadingCommand

    @classproperty
    def bare_reads(cls) -> bool:
        return False


@dataclass(frozen=True)
class ReflogReadingForms(FirstWordReadingForms):
    """
    reflog, which reads when it shows the reflog.
    """

    @classproperty
    def subcommand(cls) -> GitSubcommand:
        return GitSubcommand.REFLOG

    @classproperty
    def options(cls) -> type[GitOption]:
        return ReflogOption

    @classproperty
    def reading_commands(cls) -> type[StrEnum]:
        return ReflogReadingCommand

    @classproperty
    def bare_reads(cls) -> bool:
        return True


@dataclass(frozen=True)
class SubmoduleReadingForms(FirstWordReadingForms):
    """
    submodule, which reads when it reports submodules' status.
    """

    @classproperty
    def subcommand(cls) -> GitSubcommand:
        return GitSubcommand.SUBMODULE

    @classproperty
    def options(cls) -> type[GitOption]:
        return SubmoduleOption

    @classproperty
    def reading_commands(cls) -> type[StrEnum]:
        return SubmoduleReadingCommand

    @classproperty
    def bare_reads(cls) -> bool:
        return False


@dataclass(frozen=True)
class FetchReadingForms(ReadingForms):
    """
    fetch, which reads unless a refspec names a local branch or the URL another
    transport than HTTPS.
    """

    @classproperty
    def subcommand(cls) -> GitSubcommand:
        return GitSubcommand.FETCH

    @classproperty
    def options(cls) -> type[GitOption]:
        return FetchOption

    def form_reads(self, arguments: GitSubcommandArguments) -> bool:
        return all(
            ReadingFetch.reads(argument)
            for argument in arguments.positional
            if ":" in argument
        )


@dataclass(frozen=True)
class ArchiveReadingForms(ReadingForms):
    """
    archive, which reads unless it writes the archive where git reads its
    configuration or hooks.
    """

    @classproperty
    def subcommand(cls) -> GitSubcommand:
        return GitSubcommand.ARCHIVE

    @classproperty
    def options(cls) -> type[GitOption]:
        return ArchiveOption

    def form_reads(self, arguments: GitSubcommandArguments) -> bool:
        written = arguments.arguments
        files = [
            written[index + 1]
            for index, argument in enumerate(written[:-1])
            if argument == ArchiveOption.OUTPUT_SHORT
        ]
        return not any(GitConfigurationLocation.holds(PurePath(path)) for path in files)


# %% one call


class GitCallEffect(Enum):
    """
    What a git call does beyond reading.
    """

    UNKNOWN_GLOBAL_OPTION = auto()
    """
    An option before the subcommand is not one known to change nothing it writes.
    """

    RUNS_A_PROGRAM = auto()
    """
    An option makes it run a program of the caller's choosing, or write a file.
    """

    WRITES = auto()
    """
    It writes, or is in no form known to only read.
    """


@dataclass(frozen=True)
class GitCall:
    """
    One git call, by what follows git.
    """

    arguments: Sequence[str]
    """
    What follows git: its global options, the subcommand and its arguments.
    """

    @property
    def subcommand_position(self) -> int:
        """
        :return: Where the subcommand stands, past the global options; the number of
            arguments when there is none.
        """
        index = 0
        while index < len(self.arguments) and self.arguments[index].startswith("-"):
            option = self.arguments[index]
            index += 2 if option == GitGlobalOption.DIRECTORY else 1
        return index

    @property
    def unknown_global_option(self) -> str | None:
        """:return: The first global option not known to change nothing, if any."""
        global_options = self.arguments[: self.subcommand_position]
        return next(
            (
                option
                for option in global_options
                if option.startswith("-") and option not in GitGlobalOption
            ),
            None,
        )

    @property
    def subcommand(self) -> str | None:
        """:return: The subcommand, None when the call names none."""
        position = self.subcommand_position
        return self.arguments[position] if position < len(self.arguments) else None

    @property
    def subcommand_arguments(self) -> GitSubcommandArguments:
        """:return: What follows the subcommand."""
        return GitSubcommandArguments(self.arguments[self.subcommand_position + 1 :])

    def effect(self) -> GitCallEffect | None:
        """
        :return: What the call does beyond reading, None when it only reads.
        """
        if self.unknown_global_option is not None:
            return GitCallEffect.UNKNOWN_GLOBAL_OPTION
        subcommand = self.subcommand
        if subcommand is None:
            return None
        rest = self.subcommand_arguments.arguments
        pager = (GrepOption.OPEN_FILES_IN_PAGER, GrepOption.OPEN_FILES_IN_PAGER_SHORT)
        opens_files = subcommand == GitSubcommand.GREP and any(
            argument.startswith(pager) for argument in rest
        )
        if GitProgramOption.runs_program(subcommand, rest) or opens_files:
            return GitCallEffect.RUNS_A_PROGRAM
        if subcommand not in GitSubcommand:
            return GitCallEffect.WRITES
        match GitSubcommand(subcommand).reading:
            case SubcommandReading.ALWAYS:
                return None
            case SubcommandReading.IN_SOME_FORMS:
                form = ReadingForms.judging(GitSubcommand(subcommand))
                if form.reads(self.subcommand_arguments):
                    return None
        return GitCallEffect.WRITES
