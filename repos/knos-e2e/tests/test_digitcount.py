from digitcount import digitcount


def test_digitcount():
    assert digitcount("Knos 0.3.23") == 4
    assert digitcount("abc") == 0
    assert digitcount("") == 0
