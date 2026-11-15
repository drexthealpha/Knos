from blank import is_blank


def test_empty_and_whitespace_are_blank():
    assert is_blank("")
    assert is_blank(" \t\n")


def test_words_are_not_blank():
    assert not is_blank(" knos ")
