from capfirst import capfirst


def test_capfirst():
    assert capfirst("knos pays") == "Knos pays"
    assert capfirst("hELLO") == "HELLO"
    assert capfirst("") == ""
