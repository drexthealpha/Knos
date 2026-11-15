from rev_words import rev_words


def test_rev_words():
    assert rev_words("one two  three") == "three two one"
    assert rev_words("  ") == ""
    assert rev_words("solo") == "solo"
