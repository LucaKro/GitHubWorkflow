"""
Stands in for the plugin's installer while an install it started still runs: started in
the background it says it is installing, run directly it finds the runtime current.
"""

import sys


def main() -> None:
    """
    Say the runtime is being installed when started in the background, nothing else.
    """
    if "--background" in sys.argv:
        print("github-workflow: installing the runtime")
