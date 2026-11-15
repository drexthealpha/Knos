from squash import squash


def test_squash():
    assert squash("  a \t b\n\nc ") == "a b c"
    assert squash("") == ""
