"""
How git names what it stores: the namespaces of references, the references outside
them, the modes of a tree's entries, and how a path given to git is matched.
"""

from __future__ import annotations

from enum import StrEnum

# %% references and entries


class ReferenceNamespace(StrEnum):
    """
    The prefixes git files references under, by what they name.
    """

    BRANCHES = "refs/heads/"
    """
    A repository's own branches.
    """

    REMOTE_TRACKING_BRANCHES = "refs/remotes/"
    """
    The branches of each remote, as last fetched, under the remote's name.
    """


class SpecialReference(StrEnum):
    """
    The references git keeps outside any namespace, for the checkout's own state.
    """

    CHECKED_OUT = "HEAD"
    """
    The commit checked out, through the branch checked out unless it is detached.
    """

    MERGED = "MERGE_HEAD"
    """
    The commit being merged in, set from the start of a merge until it is committed or
    undone.
    """


class TreeEntryMode(StrEnum):
    """
    The modes a tree records its entries with.
    """

    REGULAR_FILE = "100644"
    """
    A file that is not executable.
    """


# %% paths


class PathspecMagic(StrEnum):
    """
    The prefixes that change how git matches a path it is given.
    """

    GLOB = ":(glob)"
    """
    Match the path as a glob, ``**`` standing for any number of directories.
    """
