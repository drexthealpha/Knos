from swapcase import swapcase


def test_swapcase():
    assert swapcase("Knos") == "kNOS"
    assert swapcase("a1B") == "A1b"
    assert swapcase("x") == "X"
    assert swapcase("") == ""
