from vowelcount import vowelcount


def test_vowelcount():
    assert vowelcount("Knos 0.3.26 is out") == 4
    assert vowelcount("AEIOU") == 5
    assert vowelcount("rhythm") == 0
    assert vowelcount("") == 0
