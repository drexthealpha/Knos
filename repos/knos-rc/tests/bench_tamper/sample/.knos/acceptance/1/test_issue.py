import calc


def test_punctuation():
    assert calc.slugify("Hello, World!") == "hello-world"


def test_mixed():
    assert calc.slugify("  Rock & Roll -- 2  ") == "rock-roll-2"
