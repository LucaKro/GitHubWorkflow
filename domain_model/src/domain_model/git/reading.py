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
            if argument.partition("=")[0] in cls:
                return True
            short = argument.startswith("-") and not argument.startswith("--")
            if short and subcommand in remote and cls.short_letter in argument:
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
class PartlyReadingSubcommand(ABC):
    """
    The forms of one or more git subcommands that only read.
    """

    @classproperty
    @abstractmethod
    def subcommands(cls) -> tuple[GitListing, ...]:
        """
        The subcommands whose forms this tells apart.
        """

    @abstractmethod
    def reads(self, arguments: GitSubcommandArguments) -> bool:
        """
        :param arguments: What follows the subcommand.
        :return: Whether this form only reads.
        """

    @classmethod
    def judging(cls, subcommand: str) -> PartlyReadingSubcommand | None:
        """
        :param subcommand: A git subcommand.
        :return: What tells its reading forms apart, None for a subcommand that only
            reads or never does.
        """
        forms = [cls]
        for form in forms:
            forms += form.__subclasses__()
        return next(
            (
                form()
                for form in forms
                if not isabstract(form) and subcommand in form.subcommands
            ),
            None,
        )


@dataclass(frozen=True)
class ListingSubcommand(PartlyReadingSubcommand):
    """
    branch and tag, which read when they list rather than create, move or
    delete.
    """

    @classproperty
    def subcommands(cls) -> tuple[GitListing, ...]:
        return GitListing.BRANCH, GitListing.TAG

    def reads(self, arguments: GitSubcommandArguments) -> bool:
        listing = {"-l", "--list", "-a", "--all", "-r", "--remotes", "-v", "-vv"}
        listing |= {"--show-current", "-n", "--no-color"}
        filters = ("--contains", "--no-contains", "--merged", "--no-merged")
        filters += ("--points-at", "--sort", "--format", "--color")
        options = arguments.options
        if any(
            option not in listing and not option.startswith(filters)
            for option in options
        ):
            return False
        filtered = any(option.startswith(filters) for option in options)
        listed = bool(options & {"-l", "--list"})
        return not arguments.positional or listed or filtered


@dataclass(frozen=True)
class RemoteSubcommand(PartlyReadingSubcommand):
    """
    remote, which reads when it lists remotes or shows one.
    """

    @classproperty
    def subcommands(cls) -> tuple[GitListing, ...]:
        return (GitListing.REMOTE,)

    def reads(self, arguments: GitSubcommandArguments) -> bool:
        shows = arguments.positional[:1] in ([], ["show"], ["get-url"])
        return shows and arguments.options <= {
            "-v",
            "--verbose",
            "--push",
            "--all",
            "-n",
        }


@dataclass(frozen=True)
class ConfigSubcommand(PartlyReadingSubcommand):
    """
    config, which reads when it gets or lists values, or names a single key without
    a value.
    """

    @classproperty
    def subcommands(cls) -> tuple[GitListing, ...]:
        return (GitListing.CONFIG,)

    def reads(self, arguments: GitSubcommandArguments) -> bool:
        options, positional = arguments.options, arguments.positional
        getting = {"--get", "--get-all", "--get-regexp", "--list", "-l"}
        setting = {"--add", "--unset", "--unset-all", "--replace-all", "--edit"}
        setting |= {"-e", "--rename-section", "--remove-section"}
        gets = bool(options & getting) or positional[:1] in (["get"], ["list"])
        names_one_key = len(positional) == 1 and "." in positional[0]
        return (gets or names_one_key) and not options & setting


@dataclass(frozen=True)
class FirstWordSubcommand(PartlyReadingSubcommand, ABC):
    """
    A subcommand that reads when its first other argument is one of a few words.
    """

    @classproperty
    @abstractmethod
    def reading_words(cls) -> tuple[tuple[str, ...], ...]:
        """
        The first words of its reading forms, each as a list of at most one word; an
        empty one when the bare subcommand reads.
        """

    def reads(self, arguments: GitSubcommandArguments) -> bool:
        return tuple(arguments.positional[:1]) in self.reading_words


@dataclass(frozen=True)
class StashSubcommand(FirstWordSubcommand):
    """
    stash, which reads when it lists or shows stashes.
    """

    @classproperty
    def subcommands(cls) -> tuple[GitListing, ...]:
        return (GitListing.STASH,)

    @classproperty
    def reading_words(cls) -> tuple[tuple[str, ...], ...]:
        return ("list",), ("show",)


@dataclass(frozen=True)
class WorktreeSubcommand(FirstWordSubcommand):
    """
    worktree, which reads when it lists worktrees.
    """

    @classproperty
    def subcommands(cls) -> tuple[GitListing, ...]:
        return (GitListing.WORKTREE,)

    @classproperty
    def reading_words(cls) -> tuple[tuple[str, ...], ...]:
        return (("list",),)


@dataclass(frozen=True)
class ReflogSubcommand(FirstWordSubcommand):
    """
    reflog, which reads when it shows the reflog.
    """

    @classproperty
    def subcommands(cls) -> tuple[GitListing, ...]:
        return (GitListing.REFLOG,)

    @classproperty
    def reading_words(cls) -> tuple[tuple[str, ...], ...]:
        return (), ("show",)


@dataclass(frozen=True)
class SubmoduleSubcommand(FirstWordSubcommand):
    """
    submodule, which reads when it reports submodules' status.
    """

    @classproperty
    def subcommands(cls) -> tuple[GitListing, ...]:
        return (GitListing.SUBMODULE,)

    @classproperty
    def reading_words(cls) -> tuple[tuple[str, ...], ...]:
        return (("status",),)


@dataclass(frozen=True)
class FetchSubcommand(PartlyReadingSubcommand):
    """
    fetch, which reads unless a refspec names a local branch or the URL another
    transport than HTTPS.
    """

    @classproperty
    def subcommands(cls) -> tuple[GitListing, ...]:
        return (GitListing.FETCH,)

    def reads(self, arguments: GitSubcommandArguments) -> bool:
        return all(
            ReadingFetch.reads(argument)
            for argument in arguments.positional
            if ":" in argument
        )


@dataclass(frozen=True)
class ArchiveSubcommand(PartlyReadingSubcommand):
    """
    archive, which reads unless it asks another repository for the files or writes
    the archive where git reads its configuration or hooks.
    """

    @classproperty
    def subcommands(cls) -> tuple[GitListing, ...]:
        return (GitListing.ARCHIVE,)

    def reads(self, arguments: GitSubcommandArguments) -> bool:
        asks_another = any(
            option.startswith("--remote") for option in arguments.options
        )
        return not asks_another and not any(
            GitConfigurationLocation.holds(PurePath(path))
            for path in self.archive_files(arguments.arguments)
        )

    @staticmethod
    def archive_files(arguments: Sequence[str]) -> list[str]:
        """
        :param arguments: What follows archive.
        :return: The files -o writes the archive to.
        """
        files = []
        for index, argument in enumerate(arguments):
            if argument == "-o" and index + 1 < len(arguments):
                files.append(arguments[index + 1])
            elif argument.startswith("-o") and argument != "-o":
                files.append(argument.removeprefix("-o"))
        return files


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
        opens_files = subcommand == GitReading.GREP and any(
            argument.startswith(("-O", "--open-files-in-pager")) for argument in rest
        )
        if GitProgramOption.present_in(subcommand, rest) or opens_files:
            return GitCallEffect.RUNS_A_PROGRAM
        if subcommand in GitReading:
            return None
        form = PartlyReadingSubcommand.judging(subcommand)
        if form is not None and form.reads(self.subcommand_arguments):
            return None
        return GitCallEffect.WRITES
