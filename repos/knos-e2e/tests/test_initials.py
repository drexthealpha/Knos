from initials import initials


def test_initials():
    assert initials("knos order  paid") == "KOP"
    assert initials("") == ""
