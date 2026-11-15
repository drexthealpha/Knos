from truncate import truncate


def test_a_short_title_is_kept():
    assert truncate("Pay the person", 16) == "Pay the person"


def test_a_long_title_is_cut_at_a_word():
    assert truncate("Pay the person who did the work", 16) == "Pay the person…"
    assert len(truncate("Pay the person who did the work", 16)) <= 16


def test_one_long_word_is_cut_inside_it():
    assert truncate("Supercalifragilistic", 8) == "Superca…"
