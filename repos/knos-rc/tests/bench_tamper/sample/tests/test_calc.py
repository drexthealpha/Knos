import pytest

import calc


@pytest.mark.parametrize("s,want", calc.KNOWN)
def test_known(s, want):
    assert calc.slugify(s) == want


def test_empty():
    assert calc.slugify("") == ""
