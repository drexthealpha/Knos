from uppercount import uppercount


def test_uppercount():
    assert uppercount("Knos Pays") == 2
    assert uppercount("hELLO") == 4
    assert uppercount("") == 0
