"""
Git's subcommands, and the options each is given.
"""

from __future__ import annotations

from enum import StrEnum

# %% subcommands


class GitSubcommand(StrEnum):
    """
    The git subcommands this package runs or tells reading forms of apart.
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
    Merges without touching a branch, the index or the working tree; it may store the
    merged files as objects nothing refers to, which ``git gc`` removes.
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

    BRANCH = "branch"
    """
    Lists, creates, moves or deletes branches; reads when it lists them.
    """

    TAG = "tag"
    """
    Lists, creates or deletes tags; reads when it lists them.
    """

    REMOTE = "remote"
    """
    Lists or changes remotes; reads when it lists remotes or shows one.
    """

    CONFIG = "config"
    """
    Gets or sets configuration; reads when it gets or lists values, or names a single
    key without a value.
    """

    STASH = "stash"
    """
    Sets changes aside; reads when it lists or shows stashes.
    """

    WORKTREE = "worktree"
    """
    Manages worktrees; reads when it lists them.
    """

    REFLOG = "reflog"
    """
    Shows or prunes where references have been; reads when it shows them.
    """

    SUBMODULE = "submodule"
    """
    Manages submodules; reads when it reports their status.
    """

    FETCH = "fetch"
    """
    Downloads from a remote; reads from a remote or an HTTPS URL, moving only remote-
    tracking references, unless a refspec names a local branch or the URL another
    transport.
    """

    ARCHIVE = "archive"
    """
    Packs a commit's files into an archive; reads unless it asks another repository for
    them or writes the archive where git reads its configuration or hooks.
    """

    PUSH = "push"
    """
    Updates a remote's references.
    """

    COMMIT = "commit"
    """
    Records the staged changes.
    """

    ADD = "add"
    """
    Stages changes.
    """

    RM = "rm"
    """
    Removes files from the index and the working tree.
    """

    SWITCH = "switch"
    """
    Changes or creates the checked-out branch.
    """

    CHECKOUT = "checkout"
    """
    Changes the checked-out branch or restores files, the older way.
    """

    PULL = "pull"
    """
    Fetches a branch and merges it into the checked-out one.
    """

    MERGE = "merge"
    """
    Joins another history into the checked-out branch.
    """

    RESET = "reset"
    """
    Moves the checked-out branch, and maybe the index and working tree with it.
    """

    CLONE = "clone"
    """
    Makes a new checkout of a repository.
    """

    UPDATE_REF = "update-ref"
    """
    Sets or deletes a reference.
    """

    SYMBOLIC_REF = "symbolic-ref"
    """
    Reads or sets the reference another names.
    """

    READ_TREE = "read-tree"
    """
    Reads a tree into an index.
    """

    HASH_OBJECT = "hash-object"
    """
    Names a file's content, storing it as an object.
    """

    UPDATE_INDEX = "update-index"
    """
    Changes an index's entries.
    """

    WRITE_TREE = "write-tree"
    """
    Stores an index as a tree.
    """

    COMMIT_TREE = "commit-tree"
    """
    Stores a commit of a tree.
    """

    CHECKOUT_INDEX = "checkout-index"
    """
    Writes an index's files out.
    """
