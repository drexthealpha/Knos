from digitsum import digitsum


def test_digitsum():
    assert digitsum("Knos 0.3.27 is out") == 12
    assert digitsum("a1b2c3") == 6
    assert digitsum("none") == 0
    assert digitsum("") == 0
