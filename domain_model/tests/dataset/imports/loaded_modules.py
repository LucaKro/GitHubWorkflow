"""
Imports the module its one argument names and prints every module that loaded, one per
line, so a test can see what importing it alone pulls in.
"""

from __future__ import annotations

import importlib
import sys

# %% the import

importlib.import_module(sys.argv[1])
print("\n".join(sorted(sys.modules)))
