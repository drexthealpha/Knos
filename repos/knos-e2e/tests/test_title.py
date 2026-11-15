from title import title


def test_title():
    assert title("hello  wide WORLD") == "Hello Wide World"
    assert title("") == ""
