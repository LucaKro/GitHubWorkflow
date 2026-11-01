"""
Every file and directory this package names, each written once.
"""

from __future__ import annotations

from pathlib import Path

from basstler_domain_model.locations import PathEnumeration

# %% what a probe writes


class ProbeFile(PathEnumeration):
    """
    The files a probe run writes into the directory it is handed.
    """

    REPORT = Path("report.md")
    """
    What the probe found, for a person to read.
    """

    RESULTS = Path("results.json")
    """
    What the probe found, for a program to read.
    """
