"""
Pre-commit entry point drawing the diagrams of the domain model's architecture anew into
its README.

Usage: ``python domain_model/scripts/draw_architecture.py``, with the domain model's
source importable.
"""

from __future__ import annotations

from domain_model.architecture.domain_model_readme import DomainModelReadme

# %% drawing

if __name__ == "__main__":
    DomainModelReadme().write()
