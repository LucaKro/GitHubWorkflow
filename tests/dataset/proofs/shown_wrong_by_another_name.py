"""
A test showing that doubling is wrong, named so that pytest collects it only when told
to collect functions starting with ``check``.
"""

from doubling import double


def check_two_doubled_is_four():
    assert double(2) == 4
