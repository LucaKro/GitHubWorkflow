"""
A test that fails only because it imports a module that does not exist.
"""


def test_two_doubled_is_four():
    from doublings import double

    assert double(2) == 4
