from words import count_words


def test_words_are_counted():
    assert count_words("one two  three") == 3


def test_blank_text_has_no_words():
    assert count_words("") == 0
    assert count_words("   ") == 0
