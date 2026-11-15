from slug import slugify


def test_spaces_become_hyphens():
    assert slugify("Hello World") == "hello-world"


def test_case_is_lowered():
    assert slugify("KNOS") == "knos"


def test_digits_stay_in_a_slug():
    assert slugify("Top 10 Tips") == "top-10-tips"


def test_a_number_alone_is_a_slug():
    assert slugify("2026") == "2026"


def test_runs_of_spaces_become_one_hyphen():
    assert slugify("a   b") == "a-b"


def test_no_hyphen_at_either_end():
    assert slugify("-a b-") == "a-b"


def test_a_blank_title_gives_an_empty_slug():
    assert slugify("") == ""
    assert slugify("   ") == ""


def test_punctuation_is_dropped():
    assert slugify("Hello, World!") == "hello-world"


def test_a_run_of_hyphens_becomes_one():
    assert slugify("a - b") == "a-b"
