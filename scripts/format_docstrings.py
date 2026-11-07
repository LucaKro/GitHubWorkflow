"""
Pre-commit entry point that formats Python files with black, then keeps docformatter's
changes only where a second black pass leaves them as they are.

Usage: ``python scripts/format_docstrings.py <file>...``; exits with
:attr:`HookStatus.CHANGED` when it rewrote a file.
"""

from __future__ import annotations

import subprocess
import sys
import tempfile
from collections.abc import Sequence
from dataclasses import dataclass
from enum import IntEnum
from pathlib import Path

# %% the tools' exit statuses


class DocformatterStatus(IntEnum):
    """
    The statuses docformatter exits with when it ran.
    """

    UNCHANGED = 0
    """
    It left the file as it was.
    """

    CHANGED = 3
    """
    It rewrote the file.
    """


class HookStatus(IntEnum):
    """
    The statuses this hook exits with, as pre-commit reads a formatter's.
    """

    UNCHANGED = 0
    """
    No file was rewritten.
    """

    CHANGED = 1
    """
    A file was rewritten, so the commit is stopped for it to be staged.
    """


# %% formatting one file


@dataclass(frozen=True)
class FileFormatting:
    """
    One file formatted with black and docformatter in a scratch copy.
    """

    path: Path
    """
    The file to format.
    """

    configuration: Path
    """
    The ``pyproject.toml`` holding docformatter's settings.
    """

    def formatted(self) -> str:
        """
        :return: The file's text formatted by black, then by docformatter where a
            second black pass keeps docformatter's result; the text as it is when black
            refuses it.
        """
        original = self.path.read_text()
        with tempfile.TemporaryDirectory() as scratch_directory:
            scratch = Path(scratch_directory) / self.path.name
            scratch.write_text(original)
            if not self.black(scratch):
                return original
            black_only = scratch.read_text()
            if not self.docformatter(scratch):
                return black_only
            documented = scratch.read_text()
            if not self.black(scratch) or scratch.read_text() != documented:
                return black_only
            return documented

    @staticmethod
    def black(file: Path) -> bool:
        """
        :param file: A file, formatted in place.
        :return: Whether black formatted it.
        """
        result = subprocess.run(["black", "--quiet", str(file)], capture_output=True)
        return result.returncode == 0

    def docformatter(self, file: Path) -> bool:
        """
        :param file: A file whose docstrings are formatted in place.
        :return: Whether docformatter ran.
        """
        result = subprocess.run(
            [
                "docformatter",
                "--in-place",
                "--config",
                str(self.configuration),
                str(file),
            ],
            capture_output=True,
        )
        return result.returncode in list(DocformatterStatus)


# %% the hook


@dataclass(frozen=True)
class FormattingHook:
    """
    The files pre-commit hands the hook, each rewritten where formatting changes it.
    """

    files: Sequence[Path]
    """
    The files to format.
    """

    configuration: Path = Path(__file__).resolve().parents[1] / "pyproject.toml"
    """
    The ``pyproject.toml`` holding docformatter's settings.
    """

    def run(self) -> HookStatus:
        """
        :return: Whether a file was rewritten.
        """
        status = HookStatus.UNCHANGED
        for file in self.files:
            formatted = FileFormatting(file, self.configuration).formatted()
            if formatted != file.read_text():
                file.write_text(formatted)
                status = HookStatus.CHANGED
        return status


if __name__ == "__main__":
    sys.exit(FormattingHook([Path(argument) for argument in sys.argv[1:]]).run())
