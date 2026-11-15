from vowels import count_vowels


def test_vowels_of_either_case_are_counted():
    assert count_vowels("Knos Pays") == 2
    assert count_vowels("AEIOU aeiou") == 10


def test_no_vowels():
    assert count_vowels("") == 0
    assert count_vowels("rhythm") == 0
