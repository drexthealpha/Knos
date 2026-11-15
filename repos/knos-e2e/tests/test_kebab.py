from kebab import kebab


def test_words_are_lowered_and_joined():
    assert kebab("Pay The Person") == "pay-the-person"


def test_blank_text():
    assert kebab("  ") == ""
