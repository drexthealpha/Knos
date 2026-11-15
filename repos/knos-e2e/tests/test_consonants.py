from consonants import consonants


def test_consonants():
    assert consonants("Knos") == 3
    assert consonants("AEIOU") == 0
    assert consonants("rhythm 2") == 6
    assert consonants("") == 0
