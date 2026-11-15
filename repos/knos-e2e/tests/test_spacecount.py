from spacecount import spacecount


def test_spacecount():
    assert spacecount("Knos 0.3.24 is out") == 3
    assert spacecount("a\tb\nc") == 2
    assert spacecount("") == 0
