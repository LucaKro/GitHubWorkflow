"""
A test module that cannot be collected, because it imports a module that does not
exist.
"""

from doublings import double


def test_two_doubled_is_four():
    assert double(2) == 4
