"""
Git's subcommands, how far each only reads, and the options each is given.
"""

from __future__ import annotations

from enum import Enum, StrEnum, auto

# %% how far a subcommand reads


class SubcommandReading(Enum):
    """
    How far a git subcommand only reads: moves no reference, leaves the index and the
    working files alone and runs no program of the caller's choosing.
    """

    ALWAYS = auto()
    """
    It reads whatever its arguments.
    """

    IN_SOME_FORMS = auto()
    """
    It reads only in some forms, told apart by its arguments.
    """

    NEVER = auto()
    """
    It writes, or reads in no form known to.
    """


# %% subcommands


class GitSubcommand(StrEnum):
    """
    The git subcommands this package runs or tells reading forms of apart.
    """

    reading: SubcommandReading
    """
    How far the subcommand only reads.
    """

    def __new__(cls, value: str, reading: SubcommandReading) -> GitSubcommand:
        member = str.__new__(cls, value)
        member._value_ = value
        member.reading = reading
        return member

    STATUS = "status", SubcommandReading.ALWAYS
    """
    Shows the working tree's state.
    """

    DIFF = "diff", SubcommandReading.ALWAYS
    """
    Shows changes.
    """

    LOG = "log", SubcommandReading.ALWAYS
    """
    Shows commits.
    """

    SHOW = "show", SubcommandReading.ALWAYS
    """
    Shows objects.
    """

    BLAME = "blame", SubcommandReading.ALWAYS
    """
    Shows who last changed each line.
    """

    GREP = "grep", SubcommandReading.ALWAYS
    """
    Searches tracked files.
    """

    REV_PARSE = "rev-parse", SubcommandReading.ALWAYS
    """
    Resolves references and git's paths.
    """

    REV_LIST = "rev-list", SubcommandReading.ALWAYS
    """
    Lists commits.
    """

    LS_FILES = "ls-files", SubcommandReading.ALWAYS
    """
    Lists the index's files.
    """

    LS_TREE = "ls-tree", SubcommandReading.ALWAYS
    """
    Lists a tree's files.
    """

    LS_REMOTE = "ls-remote", SubcommandReading.ALWAYS
    """
    Lists a remote's references.
    """

    CAT_FILE = "cat-file", SubcommandReading.ALWAYS
    """
    Prints objects.
    """

    MERGE_BASE = "merge-base", SubcommandReading.ALWAYS
    """
    Finds common ancestors.
    """

    MERGE_TREE = "merge-tree", SubcommandReading.ALWAYS
    """
    Merges without touching a branch, the index or the working tree; it may store the
    merged files as objects nothing refers to, which ``git gc`` removes.
    """

    DESCRIBE = "describe", SubcommandReading.ALWAYS
    """
    Names a commit after the nearest tag.
    """

    SHORTLOG = "shortlog", SubcommandReading.ALWAYS
    """
    Summarizes commits by author.
    """

    FOR_EACH_REF = "for-each-ref", SubcommandReading.ALWAYS
    """
    Lists references.
    """

    SHOW_REF = "show-ref", SubcommandReading.ALWAYS
    """
    Lists references and their commits.
    """

    NAME_REV = "name-rev", SubcommandReading.ALWAYS
    """
    Names a commit after the references reaching it.
    """

    CHECK_IGNORE = "check-ignore", SubcommandReading.ALWAYS
    """
    Says why a path is ignored.
    """

    VAR = "var", SubcommandReading.ALWAYS
    """
    Prints git's logical variables, such as the author's identity.
    """

    VERSION = "version", SubcommandReading.ALWAYS
    """
    Prints git's version.
    """

    HELP = "help", SubcommandReading.ALWAYS
    """
    Prints git's help.
    """

    BRANCH = "branch", SubcommandReading.IN_SOME_FORMS
    """
    Lists, creates, moves or deletes branches; reads when it lists them.
    """

    TAG = "tag", SubcommandReading.IN_SOME_FORMS
    """
    Lists, creates or deletes tags; reads when it lists them.
    """

    REMOTE = "remote", SubcommandReading.IN_SOME_FORMS
    """
    Lists or changes remotes; reads when it lists remotes or shows one.
    """

    CONFIG = "config", SubcommandReading.IN_SOME_FORMS
    """
    Gets or sets configuration; reads when it gets or lists values, or names a single
    key without a value.
    """

    STASH = "stash", SubcommandReading.IN_SOME_FORMS
    """
    Sets changes aside; reads when it lists or shows stashes.
    """

    WORKTREE = "worktree", SubcommandReading.IN_SOME_FORMS
    """
    Manages worktrees; reads when it lists them.
    """

    REFLOG = "reflog", SubcommandReading.IN_SOME_FORMS
    """
    Shows or prunes where references have been; reads when it shows them.
    """

    SUBMODULE = "submodule", SubcommandReading.IN_SOME_FORMS
    """
    Manages submodules; reads when it reports their status.
    """

    FETCH = "fetch", SubcommandReading.IN_SOME_FORMS
    """
    Downloads from a remote; reads from a remote or an HTTPS URL, moving only
    remote-tracking references, unless a refspec names a local branch or the URL another
    transport.
    """

    ARCHIVE = "archive", SubcommandReading.IN_SOME_FORMS
    """
    Packs a commit's files into an archive; reads unless it asks another repository for
    them or writes the archive where git reads its configuration or hooks.
    """

    PUSH = "push", SubcommandReading.NEVER
    """
    Updates a remote's references.
    """

    COMMIT = "commit", SubcommandReading.NEVER
    """
    Records the staged changes.
    """

    ADD = "add", SubcommandReading.NEVER
    """
    Stages changes.
    """

    RM = "rm", SubcommandReading.NEVER
    """
    Removes files from the index and the working tree.
    """

    SWITCH = "switch", SubcommandReading.NEVER
    """
    Changes or creates the checked-out branch.
    """

    CHECKOUT = "checkout", SubcommandReading.NEVER
    """
    Changes the checked-out branch or restores files, the older way.
    """

    PULL = "pull", SubcommandReading.NEVER
    """
    Fetches a branch and merges it into the checked-out one.
    """

    MERGE = "merge", SubcommandReading.NEVER
    """
    Joins another history into the checked-out branch.
    """

    RESET = "reset", SubcommandReading.NEVER
    """
    Moves the checked-out branch, and maybe the index and working tree with it.
    """

    CLONE = "clone", SubcommandReading.NEVER
    """
    Makes a new checkout of a repository.
    """

    UPDATE_REF = "update-ref", SubcommandReading.NEVER
    """
    Sets or deletes a reference.
    """

    SYMBOLIC_REF = "symbolic-ref", SubcommandReading.NEVER
    """
    Reads or sets the reference another names.
    """

    READ_TREE = "read-tree", SubcommandReading.NEVER
    """
    Reads a tree into an index.
    """

    HASH_OBJECT = "hash-object", SubcommandReading.NEVER
    """
    Names a file's content, storing it as an object.
    """

    UPDATE_INDEX = "update-index", SubcommandReading.NEVER
    """
    Changes an index's entries.
    """

    WRITE_TREE = "write-tree", SubcommandReading.NEVER
    """
    Stores an index as a tree.
    """

    COMMIT_TREE = "commit-tree", SubcommandReading.NEVER
    """
    Stores a commit of a tree.
    """

    CHECKOUT_INDEX = "checkout-index", SubcommandReading.NEVER
    """
    Writes an index's files out.
    """
