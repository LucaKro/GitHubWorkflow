"""
A test showing that the generated factor is wrong, which imports a module git ignores
and only a setup script writes.
"""

from doubling.generated import FACTOR


def test_the_factor_is_two():
    assert FACTOR == 2
