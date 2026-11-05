"""
A setup script writing the module the doubling package generates, which git ignores,
with the wrong factor.
"""

from pathlib import Path

Path("src", "doubling", "generated.py").write_text("FACTOR = 3\n")
