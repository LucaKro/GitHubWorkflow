"""
Which git calls only read: they move no reference, leave the index and the working files
alone and run no program of the caller's choosing.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum
from pathlib import PurePath

from domain_model.call_effects import CallEffect
from domain_model.class_family import ClassFamily
from domain_model.class_property import classproperty
from domain_model.git.options import (
    ApplyOption,
    ArchiveOption,
    BranchOption,
    ConfigOption,
    ConfigReadingCommand,
    DetachedWorktreeCommand,
    FetchOption,
    GitGlobalOption,
    GitOption,
    GrepOption,
    ReflogOption,
    ReflogReadingCommand,
    RemoteOption,
    RemoteReadingCommand,
    StashOption,
    StashReadingCommand,
    SubmoduleOption,
    SubmoduleReadingCommand,
    TagOption,
    WorktreeOption,
    WorktreeReadingCommand,
)
from domain_model.git.references import ReferenceNamespace
from domain_model.git.subcommands import GitSubcommand

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

    SYSTEM = "gitconfig"
    """
    The system's configuration file, in ``/etc``.
    """

    CONFIGURATION_HOME = ".config"
    """
    The user's directory of configuration, holding :attr:`USER_DIRECTORY`.
    """

    USER_DIRECTORY = "git"
    """
    The user's directory of git's configuration files, inside
    :attr:`CONFIGURATION_HOME`.
    """

    @classmethod
    def holds(cls, path: PurePath) -> bool:
        """
        :param path: A file's path.
        :return: Whether git reads its configuration or hooks from the file.
        """
        parts = path.parts
        in_user_directory = any(
            parts[index : index + 2] == (cls.CONFIGURATION_HOME, cls.USER_DIRECTORY)
            for index in range(len(parts))
        )
        named = path.name in (cls.USER, cls.SYSTEM)
        return cls.REPOSITORY in parts or named or in_user_directory


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
class ReadingForms(ClassFamily, ABC):
    """
    The forms of git subcommands that only read: move no reference, leave the index and
    the working files alone and run no program of the caller's choosing.
    """

    @classproperty
    @abstractmethod
    def subcommands(cls) -> frozenset[GitSubcommand]:
        """
        The subcommands whose forms this tells apart.
        """

    @abstractmethod
    def reads(self, arguments: GitSubcommandArguments) -> bool:
        """
        :param arguments: What follows the subcommand.
        :return: Whether the call only reads.
        """

    @classmethod
    def from_subcommand(cls, subcommand: GitSubcommand) -> ReadingForms:
        """
        :param subcommand: A subcommand.
        :return: What tells its reading forms apart; :class:`NeverReadingForms` when
            nothing does.
        """
        return next(
            (
                form()
                for form in cls.concrete_subclasses()
                if subcommand in form.subcommands
            ),
            NeverReadingForms(),
        )


@dataclass(frozen=True)
class AlwaysReadingForms(ReadingForms):
    """
    The subcommands that read whatever their arguments.
    """

    @classproperty
    def subcommands(cls) -> frozenset[GitSubcommand]:
        return frozenset(
            {
                GitSubcommand.STATUS,
                GitSubcommand.DIFF,
                GitSubcommand.LOG,
                GitSubcommand.SHOW,
                GitSubcommand.BLAME,
                GitSubcommand.GREP,
                GitSubcommand.REV_PARSE,
                GitSubcommand.REV_LIST,
                GitSubcommand.LS_FILES,
                GitSubcommand.LS_TREE,
                GitSubcommand.LS_REMOTE,
                GitSubcommand.CAT_FILE,
                GitSubcommand.MERGE_BASE,
                GitSubcommand.MERGE_TREE,
                GitSubcommand.DESCRIBE,
                GitSubcommand.SHORTLOG,
                GitSubcommand.FOR_EACH_REF,
                GitSubcommand.SHOW_REF,
                GitSubcommand.NAME_REV,
                GitSubcommand.CHECK_IGNORE,
                GitSubcommand.VAR,
                GitSubcommand.VERSION,
                GitSubcommand.HELP,
            }
        )

    def reads(self, arguments: GitSubcommandArguments) -> bool:
        return True


@dataclass(frozen=True)
class NeverReadingForms(ReadingForms):
    """
    The forms of a subcommand that writes, or reads in no form known to: none reads.
    """

    @classproperty
    def subcommands(cls) -> frozenset[GitSubcommand]:
        return frozenset()

    def reads(self, arguments: GitSubcommandArguments) -> bool:
        return False


@dataclass(frozen=True)
class PartlyReadingForms(ReadingForms, ABC):
    """
    The forms of one subcommand that only read, told apart by its arguments: every
    option is one of its own marked as reading, and the form reads.
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

    @classproperty
    def subcommands(cls) -> frozenset[GitSubcommand]:
        return frozenset({cls.subcommand})

    @abstractmethod
    def form_reads(self, arguments: GitSubcommandArguments) -> bool:
        """
        :param arguments: What follows the subcommand, its options all reading.
        :return: Whether this form only reads.
        """

    def reads(self, arguments: GitSubcommandArguments) -> bool:
        return self.options.only_reading(arguments.options) and self.form_reads(
            arguments
        )


@dataclass(frozen=True)
class ListingReadingForms(PartlyReadingForms, ABC):
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
    Branch, which reads when it lists branches.
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
    Tag, which reads when it lists tags.
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
class ConfigReadingForms(PartlyReadingForms):
    """
    Config, which reads when it gets or lists values, or names a single key without a
    value.
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
class FirstWordReadingForms(PartlyReadingForms, ABC):
    """
    The reading forms of a subcommand that reads when its first other argument names one
    of its reading commands, or, for some, when it has none.
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
    Remote, which reads when it lists remotes or shows one.
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
    Stash, which reads when it lists or shows stashes.
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
    Worktree, which reads when it lists worktrees, and leaves every branch and the
    checkout's own files alone when it adds a worktree at a commit, removes one holding
    no changes or prunes those gone.
    """

    def form_reads(self, arguments: GitSubcommandArguments) -> bool:
        first = arguments.positional[0] if arguments.positional else None
        if first == DetachedWorktreeCommand.ADD:
            options = {self.options.look_up(option) for option in arguments.options}
            return WorktreeOption.DETACH in options
        if first in DetachedWorktreeCommand:
            return True
        return super().form_reads(arguments)

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
    Reflog, which reads when it shows the reflog.
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
    Submodule, which reads when it reports submodules' status.
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
class FetchReadingForms(PartlyReadingForms):
    """
    Fetch, which reads unless a refspec names a local branch or the URL another
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
class ArchiveReadingForms(PartlyReadingForms):
    """
    Archive, which reads unless it writes the archive where git reads its configuration
    or hooks.
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


@dataclass(frozen=True)
class ApplyReadingForms(PartlyReadingForms):
    """
    Apply, which reads when it only checks the patch or reports on it.
    """

    @classproperty
    def subcommand(cls) -> GitSubcommand:
        return GitSubcommand.APPLY

    @classproperty
    def options(cls) -> type[GitOption]:
        return ApplyOption

    @classproperty
    def reporting_options(cls) -> frozenset[GitOption]:
        """
        The options with which nothing is applied.
        """
        return frozenset(
            {
                ApplyOption.CHECK,
                ApplyOption.STAT,
                ApplyOption.NUMSTAT,
                ApplyOption.SUMMARY,
            }
        )

    def form_reads(self, arguments: GitSubcommandArguments) -> bool:
        options = {self.options.look_up(option) for option in arguments.options}
        return bool(options & self.reporting_options)


# %% one call


@dataclass(frozen=True)
class GitCallEffect(CallEffect, ABC):
    """
    What a git call does beyond reading.
    """


@dataclass(frozen=True)
class UnknownGlobalOption(GitCallEffect):
    """
    An option before the subcommand is not one known to change nothing it writes.
    """

    option: str
    """
    The first such option.
    """

    @property
    def description(self) -> str:
        return f"git {self.option} is not a global option known to change nothing"


@dataclass(frozen=True)
class ProgramRunningOption(GitCallEffect):
    """
    An option makes the call run a program of the caller's choosing, or write a file.
    """

    subcommand: str
    """
    The subcommand the option is given to.
    """

    @property
    def description(self) -> str:
        return f"git {self.subcommand} with this option runs a program or writes"


@dataclass(frozen=True)
class WritingSubcommand(GitCallEffect):
    """
    The call writes, or is in no form known to only read.
    """

    subcommand: str
    """
    The subcommand it was given.
    """

    @property
    def description(self) -> str:
        return f"git {self.subcommand} writes, or is not a form known to only read"

    @property
    def write(self) -> str:
        return self.subcommand


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
        unknown = self.unknown_global_option
        if unknown is not None:
            return UnknownGlobalOption(unknown)
        subcommand = self.subcommand
        if subcommand is None:
            return None
        rest = self.subcommand_arguments.arguments
        pager = (GrepOption.OPEN_FILES_IN_PAGER, GrepOption.OPEN_FILES_IN_PAGER_SHORT)
        opens_files = subcommand == GitSubcommand.GREP and any(
            argument.startswith(pager) for argument in rest
        )
        if GitProgramOption.runs_program(subcommand, rest) or opens_files:
            return ProgramRunningOption(subcommand)
        if subcommand not in GitSubcommand:
            return WritingSubcommand(subcommand)
        forms = ReadingForms.from_subcommand(GitSubcommand(subcommand))
        if forms.reads(self.subcommand_arguments):
            return None
        return WritingSubcommand(subcommand)
