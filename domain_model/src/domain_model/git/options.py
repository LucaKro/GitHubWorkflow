"""
The options each git subcommand is given, each saying whether it only reads, and the
commands of the subcommands that read in some forms.
"""

from __future__ import annotations

from collections.abc import Iterable
from enum import StrEnum

from domain_model.class_property import classproperty

# %% options before a subcommand, and the base of every subcommand's


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


class GitOption(StrEnum):
    """
    The options one git subcommand is given, each saying whether it only reads.

    A subcommand's options are an enumeration of their own deriving from this one.
    """

    reads: bool
    """
    Whether the option itself is harmless: it neither writes nor runs a program. Whether
    a whole call reads still depends on its form.
    """

    def __new__(cls, value: str, reads: bool) -> GitOption:
        member = str.__new__(cls, value)
        member._value_ = value
        member.reads = reads
        return member

    @classproperty
    def end_of_options(cls) -> str:
        """
        The argument after which every argument is a path, even one starting with ``-``.
        """
        return "--"

    @classmethod
    def look_up(cls, option: str) -> GitOption | None:
        """
        :param option: An option as written on a command line, maybe with ``=`` and a
            value.
        :return: The member it is, compared whole and then without its value; ``None``
            when it is none.
        """
        name = option.partition("=")[0]
        return next(
            (cls(spelling) for spelling in (option, name) if spelling in cls), None
        )

    @classmethod
    def only_reading(cls, options: Iterable[str]) -> bool:
        """
        :param options: Options as written on a command line.
        :return: Whether each is a member marked as reading; one missing counts as
            writing.
        """
        members = [cls.look_up(option) for option in options]
        return all(member is not None and member.reads for member in members)


# %% the options of the subcommands run


class CloneOption(GitOption):
    """
    The options of ``git clone``.
    """

    QUIET = "--quiet", True
    """
    Print no progress.
    """


class RevParseOption(GitOption):
    """
    The options of ``git rev-parse``.
    """

    VERIFY = "--verify", True
    """
    Resolve exactly one revision, failing when it names none.
    """

    QUIET = "--quiet", True
    """
    Fail without a message when the revision names none.
    """

    SHOW_TOPLEVEL = "--show-toplevel", True
    """
    Print the root of the checkout.
    """

    COMMON_DIRECTORY = "--git-common-dir", True
    """
    Print the git directory every worktree of the repository shares.
    """

    ABSOLUTE_PATHS = "--path-format=absolute", True
    """
    Print the paths after it absolute.
    """

    GIT_PATH = "--git-path", True
    """
    Print where a file inside the git directory is for this worktree.
    """


class RemoteOption(GitOption):
    """
    The options of ``git remote``.
    """

    VERBOSE = "--verbose", True
    """
    Print each remote's URLs with its name.
    """

    VERBOSE_SHORT = "-v", True
    """
    Print each remote's URLs with its name, short form.
    """

    PUSH = "--push", True
    """
    Print the URL pushes go to rather than the one fetches come from.
    """

    ALL = "--all", True
    """
    Print every URL of the remote.
    """

    NO_QUERY = "-n", True
    """
    Show a remote without asking it for its branches.
    """


class LsRemoteOption(GitOption):
    """
    The options of ``git ls-remote``.
    """

    HEADS = "--heads", True
    """
    List branches only.
    """

    SYMBOLIC_REFERENCES = "--symref", True
    """
    Name the reference each symbolic reference points at.
    """


class SymbolicRefOption(GitOption):
    """
    The options of ``git symbolic-ref``.
    """

    QUIET = "--quiet", True
    """
    Fail without a message when the reference is not symbolic.
    """


class UpdateRefOption(GitOption):
    """
    The options of ``git update-ref``.
    """

    DELETE = "-d", False
    """
    Delete the reference.
    """


class ReflogOption(GitOption):
    """
    The options of ``git reflog``.
    """

    FORMAT = "--format", True
    """
    Print each entry as the given format says.
    """

    SUBJECTS = "--format=%gs", True
    """
    Print each entry's subject alone: what wrote the reference.
    """

    COMMITS = "--format=%H", True
    """
    Print each entry's commit alone: where the reference was.
    """

    DATE = "--date", True
    """
    Print the entries' dates as the given format says.
    """

    MAX_COUNT = "--max-count", True
    """
    Print at most the given number of entries.
    """


class PushOption(GitOption):
    """
    The options of ``git push``.
    """

    QUIET = "--quiet", True
    """
    Print nothing but errors.
    """

    PORCELAIN = "--porcelain", True
    """
    Print what happened to each reference in a form meant for programs.
    """

    FORCE_WITH_LEASE = "--force-with-lease", False
    """
    Overwrite the remote's history, but only where it is still where the checkout last
    saw it.
    """

    SET_UPSTREAM = "--set-upstream", False
    """
    Make the local branch pushed track the branch it was pushed to.
    """

    NO_VERIFY = "--no-verify", False
    """
    Skip the ``pre-push`` hook.
    """


class FetchOption(GitOption):
    """
    The options of ``git fetch``.
    """

    QUIET = "--quiet", True
    """
    Print no progress.
    """

    VERBOSE = "--verbose", True
    """
    Print every reference fetched.
    """

    NO_WRITE_FETCH_HEAD = "--no-write-fetch-head", True
    """
    Leave ``FETCH_HEAD`` alone.
    """

    PRUNE = "--prune", True
    """
    Forget the remote-tracking branches the remote no longer has.
    """

    ALL = "--all", True
    """
    Fetch from every remote.
    """

    TAGS = "--tags", True
    """
    Fetch every tag too.
    """

    NO_TAGS = "--no-tags", True
    """
    Fetch no tag.
    """

    DEPTH = "--depth", True
    """
    Fetch only the given number of commits of each history.
    """

    UNSHALLOW = "--unshallow", True
    """
    Fetch the whole history of a shallow clone.
    """

    DRY_RUN = "--dry-run", True
    """
    Show what would be fetched, storing nothing.
    """

    FORCE = "--force", True
    """
    Let a fetched reference move to a commit that does not descend from its own.
    """

    SET_UPSTREAM = "--set-upstream", False
    """
    Configure the checked-out branch to track what is fetched.
    """

    REFERENCE_MAP = "--refmap", False
    """
    Store what is fetched where the given refspec says, a local branch among them.
    """

    UPDATE_HEAD_OK = "--update-head-ok", False
    """
    Let the fetch move the checked-out branch.
    """


class MergeBaseOption(GitOption):
    """
    The options of ``git merge-base``.
    """

    IS_ANCESTOR = "--is-ancestor", True
    """
    Succeed only when the first commit is in the second's history.
    """


class RevListOption(GitOption):
    """
    The options of ``git rev-list``.
    """

    COUNT = "--count", True
    """
    Print how many commits it lists instead of listing them.
    """


class MergeTreeOption(GitOption):
    """
    The options of ``git merge-tree``.
    """

    WRITE_TREE = "--write-tree", True
    """
    Merge in full, storing the merged tree as an object nothing refers to.
    """


class HashObjectOption(GitOption):
    """
    The options of ``git hash-object``.
    """

    WRITE = "-w", False
    """
    Store the content as an object.
    """


class UpdateIndexOption(GitOption):
    """
    The options of ``git update-index``.
    """

    ADD = "--add", False
    """
    Let a file not yet in the index be added.
    """

    CACHE_INFORMATION = "--cacheinfo", False
    """
    Set one entry from a mode, an object and a path.
    """


class CommitTreeOption(GitOption):
    """
    The options of ``git commit-tree``.
    """

    PARENT = "-p", True
    """
    Name a parent of the commit.
    """

    MESSAGE = "-m", True
    """
    Give the commit message.
    """


class CheckoutIndexOption(GitOption):
    """
    The options of ``git checkout-index``.
    """

    ALL = "--all", True
    """
    Write every file of the index.
    """

    PREFIX = "--prefix", True
    """
    Write the files under the given prefix.
    """


class SwitchOption(GitOption):
    """
    The options of ``git switch``.
    """

    QUIET = "--quiet", True
    """
    Print no feedback.
    """

    NO_TRACK = "--no-track", True
    """
    Make the new branch track no other.
    """

    CREATE = "--create", False
    """
    Create the branch switched to.
    """


class BranchOption(GitOption):
    """
    The options of ``git branch``.
    """

    LIST = "--list", True
    """
    List the branches, those matching the patterns given when any is.
    """

    LIST_SHORT = "-l", True
    """
    List the branches, short form.
    """

    ALL = "--all", True
    """
    List the remote-tracking branches with the local ones.
    """

    ALL_SHORT = "-a", True
    """
    List the remote-tracking branches with the local ones, short form.
    """

    REMOTES = "--remotes", True
    """
    List the remote-tracking branches alone.
    """

    REMOTES_SHORT = "-r", True
    """
    List the remote-tracking branches alone, short form.
    """

    VERBOSE = "--verbose", True
    """
    List each branch with its commit.
    """

    VERBOSE_SHORT = "-v", True
    """
    List each branch with its commit, short form.
    """

    VERY_VERBOSE = "-vv", True
    """
    List each branch with its commit and the branch it tracks.
    """

    SHOW_CURRENT = "--show-current", True
    """
    Print the checked-out branch, nothing on a detached ``HEAD``.
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
    List only the branches whose history holds the given commit.
    """

    NO_CONTAINS = "--no-contains", True
    """
    List only the branches whose history lacks the given commit.
    """

    MERGED = "--merged", True
    """
    List only the branches the given commit's history holds.
    """

    NO_MERGED = "--no-merged", True
    """
    List only the branches the given commit's history lacks.
    """

    POINTS_AT = "--points-at", True
    """
    List only the branches at the given commit.
    """

    SORT = "--sort", True
    """
    Order the list by the given key.
    """

    FORMAT = "--format", True
    """
    Print each branch as the given format says.
    """


class RmOption(GitOption):
    """
    The options of ``git rm``.
    """

    RECURSIVE = "-r", True
    """
    Remove a directory's files.
    """

    QUIET = "--quiet", True
    """
    Print nothing.
    """

    CACHED = "--cached", True
    """
    Remove from the index only, keeping the working files.
    """

    IGNORE_UNMATCH = "--ignore-unmatch", True
    """
    Succeed even when a path matches no file.
    """


class CommitOption(GitOption):
    """
    The options of ``git commit``.
    """

    QUIET = "--quiet", True
    """
    Print nothing.
    """

    MESSAGE = "--message", True
    """
    Give the commit message.
    """


class StatusOption(GitOption):
    """
    The options of ``git status``.
    """

    PORCELAIN = "--porcelain", True
    """
    Print each changed file on a line, in a form meant for programs.
    """

    TRACKED_ONLY = "--untracked-files=no", True
    """
    Leave untracked files out.
    """


class MergeOption(GitOption):
    """
    The options of ``git merge``.
    """

    QUIET = "--quiet", True
    """
    Print nothing.
    """

    FAST_FORWARD_ONLY = "--ff-only", True
    """
    Only move the branch forward, failing when it has commits of its own.
    """

    NO_EDIT = "--no-edit", True
    """
    Commit with the message given, without opening an editor.
    """

    MESSAGE = "--message", True
    """
    Give the merge commit's message.
    """

    ABORT = "--abort", False
    """
    Undo the merge in progress.
    """


class ResetOption(GitOption):
    """
    The options of ``git reset``.
    """

    QUIET = "--quiet", True
    """
    Print nothing.
    """

    KEEP = "--keep", True
    """
    Keep uncommitted changes, failing when one would be lost.
    """


class DiffOption(GitOption):
    """
    The options of ``git diff``.
    """

    NAME_ONLY = "--name-only", True
    """
    Print only the changed files' names.
    """

    CONFLICTED_ONLY = "--diff-filter=U", True
    """
    Show only the files left conflicting.
    """


# %% the options of the subcommands only told apart


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


class ApplyOption(GitOption):
    """
    The options of ``git apply``.
    """

    CHECK = "--check", True
    """
    Report whether the patch applies, applying nothing.
    """

    STAT = "--stat", True
    """
    Report how many lines the patch changes in each file, applying nothing.
    """

    NUMSTAT = "--numstat", True
    """
    Report the counts of :attr:`STAT` in a form meant for programs.
    """

    SUMMARY = "--summary", True
    """
    Report the files the patch creates, deletes, renames or changes the mode of.
    """

    REVERSE = "--reverse", True
    """
    Take the patch the other way round.
    """

    REVERSE_SHORT = "-R", True
    """
    Take the patch the other way round, short form.
    """

    VERBOSE = "--verbose", True
    """
    Report more about the patch.
    """

    VERBOSE_SHORT = "-v", True
    """
    Report more about the patch, short form.
    """

    APPLY = "--apply", False
    """
    Apply the patch even after an option that only reports.
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


# %% the commands of the subcommands reading in some forms


class RemoteReadingCommand(StrEnum):
    """
    The commands of ``git remote`` that only read, named by its first other argument.
    """

    SHOW = "show"
    """
    Show a remote and its branches.
    """

    GET_URL = "get-url"
    """
    Print a remote's URL.
    """


class ReflogReadingCommand(StrEnum):
    """
    The commands of ``git reflog`` that only read, named by its first other argument.
    """

    SHOW = "show"
    """
    Show where a reference has been.
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
